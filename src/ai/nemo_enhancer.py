"""Módulo de enriquecimiento expresivo y modo narración con Mistral NeMo local (Ollama).

Aplica Meta-Prompting estructurado (CO-STAR, <thinking>, reglas duras) y se apoya
en la biblioteca persistente de prompts maestros (PromptLibrary):
1. Enriquecimiento prosódico (enhance): Inyección de etiquetas de voz, pausas e inflexiones.
2. Reescritura narrativa (rewrite): Adaptación en 16 estilos del catálogo industrial CO-STAR.
3. Traducción y adaptación literaria (translate): Español latinoamericano neutro (es-LA).
4. Detección y clasificación dramática de diálogos (dialogue_analysis): Auto-casting multivoz.
5. Guion de Audio-Trailer Cinematográfico 90s (trailer_script): Avance promocional con SFX.
6. Dirección de Paisaje Sonoro y Efectos Foley SFX (sfx_director): Inyección de [sfx:...].
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from src.ai.prompt_library import NarrativeStyleDef, PromptItem, PromptLibrary

logger = logging.getLogger("globaltts.nemo_enhancer")

OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
DEFAULT_NEMO_MODEL = "mistral-nemo-local:latest"


@dataclass
class NarrationConfig:
    """Configuración de narración y análisis con IA."""
    enabled: bool = False
    mode: str = "enhance"  # "enhance", "rewrite", "translate", "dialogue_analysis", "trailer_script", "sfx_director"
    persona: str = "3ra"   # "1ra", "2da", "3ra"
    tense: str = "pasado"  # "pasado", "presente", "presente_continuo", "futuro"
    style: str = "cuento"  # 16 estilos disponibles en catálogo CO-STAR
    prompt_id: Optional[str] = None
    custom_system_prompt: Optional[str] = None
    custom_template: Optional[str] = None
    target_language: str = "es-LA"
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    num_ctx: Optional[int] = None


class MistralNeMoEnhancer:
    """Cliente robusto para análisis de texto y narración con Mistral NeMo local."""

    def __init__(
        self,
        model_name: str = DEFAULT_NEMO_MODEL,
        timeout: int = 120,
        prompt_library: Optional[PromptLibrary] = None,
        endpoint: str = OLLAMA_ENDPOINT,
    ):
        self.model_name = model_name
        self.timeout = timeout
        self.endpoint = endpoint
        self.library = prompt_library or PromptLibrary()

    def is_available(self) -> bool:
        """Verifica si Ollama está corriendo y el modelo está disponible."""
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                return any(self.model_name in m for m in models)
        except Exception:
            return False

    @staticmethod
    def _clean_response(raw: str) -> str:
        """Limpia etiquetas de pensamiento interno <thinking>, bloques markdown, preámbulos y acotaciones espurias."""
        if not raw:
            return ""
        # 1. Eliminar etiquetas de razonamiento interno <thinking>...</thinking>
        cleaned = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL).strip()
        # 2. Eliminar cercas de markdown (```markdown, ```json, ```text o ```)
        cleaned = re.sub(r"^```(?:markdown|text|json)?\n?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\n?```$", "", cleaned).strip()
        # 3. Eliminar preámbulos conversacionales típicos del LLM ("Aquí tienes...", "Versión narrada:", etc.)
        cleaned = re.sub(r"^(?:Aquí tienes|A continuación|Versión narrada|Texto narrado)[^:\n]*:\s*\n*", "", cleaned, flags=re.IGNORECASE)
        # 4. Eliminar acotaciones teatrales residuales en corchetes que no sean etiquetas de síntesis válidas
        cleaned = re.sub(r"^\s*\[(?:Yo|Narrador|Personaje|Voz|Actor)[^\]]*\]:?\s*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _call_ollama(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0.4,
        top_p: float = 0.9,
        num_ctx: int = 4096,
    ) -> str:
        """Envía la solicitud de inferencia al servidor Ollama local con context window de 4096 (optimizado para Vulkan iGPU)."""
        payload = {
            "model": self.model_name,
            "system": system_prompt,
            "prompt": prompt,
            "options": {
                "num_ctx": num_ctx,
                "temperature": temperature,
                "top_p": top_p,
            },
            "stream": False,
        }
        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw = data.get("response", "")
            return self._clean_response(raw)

    def enhance_expressiveness(self, text: str, prompt_id: Optional[str] = None) -> str:
        """Inyecta etiquetas de prosodia y emoción en el texto original sin cambiar su contenido."""
        if not text.strip():
            return text

        sys_prompt, user_prompt, params = self.library.build_prompt_for_mode(
            mode="enhance",
            text=text,
            prompt_id=prompt_id,
        )

        try:
            enhanced = self._call_ollama(
                prompt=user_prompt,
                system_prompt=sys_prompt,
                temperature=params.get("temperature", 0.35),
                top_p=params.get("top_p", 0.9),
                num_ctx=params.get("num_ctx", 4096),
            )
            return enhanced if enhanced else text
        except Exception as e:
            logger.warning("Fallo en enriquecimiento prosódico con NeMo: %s. Usando texto original.", e)
            return text

    def rewrite_as_narration(
        self,
        text: str,
        config: NarrationConfig,
        prompt_id: Optional[str] = None,
    ) -> str:
        """Reescribe el texto como una historia narrada según persona, tiempo y estilo CO-STAR."""
        if not text.strip():
            return text

        pid = config.prompt_id or prompt_id
        sys_prompt, user_prompt, params = self.library.build_prompt_for_mode(
            mode="rewrite",
            text=text,
            persona=config.persona,
            tense=config.tense,
            style=config.style,
            prompt_id=pid,
            custom_system_prompt=config.custom_system_prompt,
            custom_template=config.custom_template,
        )

        temp = config.temperature if config.temperature is not None else params.get("temperature", 0.45)
        top_p = config.top_p if config.top_p is not None else params.get("top_p", 0.9)
        num_ctx = config.num_ctx if config.num_ctx is not None else params.get("num_ctx", 4096)

        try:
            rewritten = self._call_ollama(
                prompt=user_prompt,
                system_prompt=sys_prompt,
                temperature=temp,
                top_p=top_p,
                num_ctx=num_ctx,
            )
            return rewritten if rewritten else text
        except Exception as e:
            logger.warning("Fallo en reescritura narrativa con NeMo: %s. Usando texto original.", e)
            return text

    def translate_and_adapt(
        self,
        text: str,
        target_lang: str = "es-LA",
        prompt_id: Optional[str] = None,
        custom_system_prompt: Optional[str] = None,
    ) -> str:
        """Traduce y adapta el texto al español neutro latinoamericano optimizado para audiolibros."""
        if not text.strip():
            return text

        sys_prompt, user_prompt, params = self.library.build_prompt_for_mode(
            mode="translate",
            text=text,
            prompt_id=prompt_id,
            custom_system_prompt=custom_system_prompt,
            target_language=target_lang,
        )

        try:
            translated = self._call_ollama(
                prompt=user_prompt,
                system_prompt=sys_prompt,
                temperature=params.get("temperature", 0.3),
                top_p=params.get("top_p", 0.9),
                num_ctx=params.get("num_ctx", 4096),
            )
            return translated if translated else text
        except Exception as e:
            logger.warning("Fallo en traducción con NeMo: %s. Usando texto original.", e)
            return text

    def analyze_dialogues(self, text: str, prompt_id: Optional[str] = None) -> Dict[str, Any]:
        """Detecta personajes, separa narrador de diálogos y clasifica emociones para casting multivoz."""
        fallback: Dict[str, Any] = {
            "characters": [{"name": "Narrador", "gender": "neutral", "tone": "narrador principal"}],
            "segments": [
                {
                    "speaker": "Narrador",
                    "type": "narration",
                    "text": text,
                    "emotion": "neutral",
                    "suggested_tags": [],
                }
            ],
        }

        if not text.strip():
            return fallback

        sys_prompt, user_prompt, params = self.library.build_prompt_for_mode(
            mode="dialogue_analysis",
            text=text,
            prompt_id=prompt_id,
        )

        try:
            raw_output = self._call_ollama(
                prompt=user_prompt,
                system_prompt=sys_prompt,
                temperature=params.get("temperature", 0.2),
                top_p=params.get("top_p", 0.9),
                num_ctx=params.get("num_ctx", 4096),
            )
            data = json.loads(raw_output)
            if isinstance(data, dict) and "segments" in data:
                return data
            return fallback
        except Exception as e:
            logger.warning("Fallo en análisis de diálogos con NeMo: %s. Usando segmentación fallback.", e)
            return fallback

    def generate_synopsis_trailer_script(
        self,
        text: str,
        title: str = "Obra Maestra",
        style: str = "epico",
        prompt_id: Optional[str] = None,
    ) -> str:
        """Genera un guion de Audio-Trailer dramático (60-90s) usando el modo maestro trailer_script."""
        sample = text.strip()[:5500]
        if not sample:
            return f"[sfx:campana] [enfasis]{title}.[/enfasis] [pausa:0.8s] Una producción de GlobalTTS Studio."

        sys_prompt, user_prompt, params = self.library.build_prompt_for_mode(
            mode="trailer_script",
            text=sample,
            style=style,
            prompt_id=prompt_id,
            title=title,
        )

        if self.is_available():
            try:
                script = self._call_ollama(
                    prompt=user_prompt,
                    system_prompt=sys_prompt,
                    temperature=params.get("temperature", 0.65),
                    top_p=params.get("top_p", 0.9),
                    num_ctx=params.get("num_ctx", 4096),
                )
                if script and len(script.split()) >= 20:
                    if "[sfx:" not in script.lower():
                        script = f"[sfx:campana] {script}"
                    return script
            except Exception as exc:
                logger.warning("Aviso en generación de trailer con NeMo: %s. Usando motor extractivo.", exc)

        # Motor determinista extractivo de alta intensidad dramática cuando Ollama no está activo
        sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", sample) if len(s.strip()) >= 35]
        hook = sentences[0] if sentences else sample[:180]
        climax = sentences[min(2, len(sentences) - 1)] if len(sentences) > 1 else ""
        return (
            f"[sfx:viento] [misterioso]En un mundo donde cada palabra guarda un destino...[/misterioso] "
            f"[pausa:0.7s] [enfasis]{title}.[/enfasis] [pausa:0.6s] "
            f"{hook} [pausa:0.8s] "
            f"{f'[lento]{climax}[/lento] [pausa:0.8s] ' if climax else ''}"
            f"[sfx:campana] [enfasis]Descubre la experiencia completa en esta edición magistral de GlobalTTS Studio.[/enfasis]"
        )

    def direct_sfx_and_soundscape(self, text: str, prompt_id: Optional[str] = None) -> str:
        """Analiza el texto e inyecta marcadores de efectos Foley [sfx:...] e inflexiones sin alterar palabras."""
        if not text.strip():
            return text

        sys_prompt, user_prompt, params = self.library.build_prompt_for_mode(
            mode="sfx_director",
            text=text,
            prompt_id=prompt_id,
        )

        if self.is_available():
            try:
                directed = self._call_ollama(
                    prompt=user_prompt,
                    system_prompt=sys_prompt,
                    temperature=params.get("temperature", 0.25),
                    top_p=params.get("top_p", 0.85),
                    num_ctx=params.get("num_ctx", 4096),
                )
                if directed:
                    return directed
            except Exception as exc:
                logger.warning("Aviso en dirección SFX con NeMo: %s. Usando inyector semántico determinista.", exc)

        from src.audio.sfx_engine import inject_semantic_sfx_tags
        return inject_semantic_sfx_tags(text)

    def process(self, text: str, config: NarrationConfig) -> Union[str, Dict[str, Any]]:
        """Método de despacho unificado según la configuración de narración."""
        if not config.enabled or not text.strip():
            return text

        mode = config.mode.lower().strip()
        if mode == "rewrite":
            return self.rewrite_as_narration(text, config)
        elif mode == "translate":
            return self.translate_and_adapt(
                text,
                target_lang=config.target_language,
                prompt_id=config.prompt_id,
                custom_system_prompt=config.custom_system_prompt,
            )
        elif mode == "dialogue_analysis":
            return self.analyze_dialogues(text, prompt_id=config.prompt_id)
        elif mode == "trailer_script":
            return self.generate_synopsis_trailer_script(
                text,
                style=config.style,
                prompt_id=config.prompt_id,
            )
        elif mode == "sfx_director":
            return self.direct_sfx_and_soundscape(text, prompt_id=config.prompt_id)
        else:
            return self.enhance_expressiveness(text, prompt_id=config.prompt_id)
