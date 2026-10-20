"""Módulo de enriquecimiento expresivo y modo narración con Mistral NeMo local (Ollama).

Aplica Meta-Prompting estructurado (CO-STAR, <thinking>, reglas duras) para:
1. Analizar el texto e inyectar etiquetas expresivas ([lento], [pausa], [susurro], [énfasis]).
2. Reescribir en Modo Narración (cuento, historia, suceso) en 1ra/2da/3ra persona y tiempos verbales.
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional

OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"
DEFAULT_NEMO_MODEL = "mistral-nemo-local:latest"


@dataclass
class NarrationConfig:
    enabled: bool = False
    mode: str = "enhance"  # "enhance" (agrega tags a texto original) o "rewrite" (reescritura narrativa)
    persona: str = "3ra"   # "1ra" ("Yo"), "2da" ("Tú/Usted"), "3ra" ("Él/Ella/Ellos")
    tense: str = "pasado"  # "pasado", "presente", "presente_continuo", "futuro"
    style: str = "cuento"  # "cuento", "historia", "suceso", "epico"


class MistralNeMoEnhancer:
    """Cliente para análisis de texto y narración con Mistral NeMo local."""

    def __init__(self, model_name: str = DEFAULT_NEMO_MODEL, timeout: int = 120):
        self.model_name = model_name
        self.timeout = timeout

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

    def _call_ollama(self, prompt: str, system_prompt: str) -> str:
        payload = {
            "model": self.model_name,
            "system": system_prompt,
            "prompt": prompt,
            "options": {
                "num_ctx": 8192,
                "temperature": 0.4,
                "top_p": 0.9,
            },
            "stream": False,
        }
        req = urllib.request.Request(
            OLLAMA_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw = data.get("response", "").strip()
            # Limpiar etiquetas <thinking> si el modelo las incluye
            cleaned = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL).strip()
            # Limpiar bloques markdown de código si los incluye
            cleaned = re.sub(r"^```(?:markdown|text)?\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
            return cleaned.strip()

    def enhance_expressiveness(self, text: str) -> str:
        """Inyecta etiquetas de prosodia y emoción en el texto original sin cambiar su contenido."""
        if not text.strip():
            return text

        sys_prompt = (
            "Eres el Principal Audio Narrative Director especializado en audiolibros dramáticos. "
            "Tu única misión es enriquecer el texto en español recibido insertando etiquetas de voz para un motor TTS. "
            "Etiquetas permitidas:\n"
            "- [pausa:1s] o [pausa:500ms] para silencios dramáticos, reflexiones o pausas naturales.\n"
            "- [lento]...[/lento] para momentos solemnes, pensativos, misteriosos o de tensión.\n"
            "- [rapido]...[/rapido] para acción, urgencia o aceleración del ritmo.\n"
            "- [susurro]...[/susurro] para secretos, intimidad, miedo o confesiones.\n"
            "- [enfasis]...[/enfasis] para resaltar palabras o frases clave.\n"
            "- [alegre]...[/alegre], [triste]...[/triste], [misterioso]...[/misterioso], [enojado]...[/enojado].\n\n"
            "REGLAS OBLIGATORIAS:\n"
            "1. NO cambies ni elimines ninguna palabra del texto original.\n"
            "2. No agregues introducciones, comentarios ni explicaciones.\n"
            "3. Devuelve únicamente el texto original enriquecido con las etiquetas correspondientes."
        )

        try:
            enhanced = self._call_ollama(prompt=f"Texto a enriquecer:\n\n{text}", system_prompt=sys_prompt)
            return enhanced if enhanced else text
        except Exception:
            return text

    def rewrite_as_narration(self, text: str, config: NarrationConfig) -> str:
        """Reescribe el texto como una historia narrada según persona, tiempo y estilo."""
        if not text.strip():
            return text

        persona_desc = {
            "1ra": "Primera persona ('Yo', 'Nosotros')",
            "2da": "Segunda persona ('Tú', 'Usted', involucrando al oyente)",
            "3ra": "Tercera persona ('Él', 'Ella', 'Ellos', como narrador omnisciente u observador)",
        }.get(config.persona, "Tercera persona")

        tense_desc = {
            "pasado": "Tiempo pasado (pretérito, como un hecho ya acontecido)",
            "presente": "Tiempo presente (haciendo que el oyente viva el suceso ahora mismo)",
            "presente_continuo": "Presente continuo / progresivo ('está ocurriendo', 'vamos viendo')",
            "futuro": "Tiempo futuro (como una predicción, profecía o destino inevitable)",
        }.get(config.tense, "Tiempo pasado")

        style_desc = {
            "cuento": "Cuentacuentos literario, inmersivo, cálido y cautivador",
            "historia": "Narración histórica épica y descriptiva",
            "suceso": "Crónica viva de un suceso impactante, con ritmo periodístico e intrigante",
            "epico": "Relato heroico, legendario y de gran escala",
        }.get(config.style, "Cuentacuentos inmersivo")

        sys_prompt = (
            f"Eres un Master Storyteller y Narrador Profesional de audiolibros.\n"
            f"Tu misión es transformar el texto recibido en una narración oral fluida, viva y atrapante.\n\n"
            f"PARÁMETROS DE NARRACIÓN:\n"
            f"- Perspectiva: {persona_desc}.\n"
            f"- Tiempo verbal: {tense_desc}.\n"
            f"- Estilo narrativo: {style_desc}.\n\n"
            f"REGLAS ESTRICTAS:\n"
            f"1. Conserva todos los hechos, datos y la esencia del texto original, pero cuéntalo como un relato oral.\n"
            f"2. Puedes incluir etiquetas de voz TTS para darle expresividad ([pausa:1s], [lento], [susurro], [enfasis], [misterioso]).\n"
            f"3. Responde únicamente con la narración final, sin introducciones ni despedidas."
        )

        try:
            rewritten = self._call_ollama(prompt=f"Texto base para narrar:\n\n{text}", system_prompt=sys_prompt)
            return rewritten if rewritten else text
        except Exception:
            return text
