"""Gestor y biblioteca de Prompts Maestros para GlobalTTS.

Gestiona de forma persistente y modular los prompts maestros, modos de IA
(enriquecimiento prosódico, reescritura narrativa, traducción, análisis de diálogos)
y estilos narrativos basados en Meta-Prompting CO-STAR y control de etiquetas TTS.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("globaltts.prompt_library")

DEFAULT_PROMPTS_PATH = Path(__file__).parent / "prompts_master.json"

PERSONA_DESCRIPTIONS: Dict[str, str] = {
    "1ra": "Primera persona ('Yo', 'Nosotros' - testimonio y vivencia directa)",
    "2da": "Segunda persona ('Tú', 'Usted' - interpelación directa que involucra al oyente)",
    "3ra": "Tercera persona ('Él', 'Ella', 'Ellos' - narrador omnisciente u observador cinematográfico)",
}

TENSE_DESCRIPTIONS: Dict[str, str] = {
    "pasado": "Tiempo pasado (pretérito / imperfecto, como un acontecimiento ya consumado)",
    "presente": "Tiempo presente (en vivo, haciendo que el oyente viva el suceso en este instante)",
    "presente_continuo": "Presente continuo / progresivo ('está ocurriendo', 'vamos presenciando')",
    "futuro": "Tiempo futuro (visión profética, anticipatoria o destino inevitable)",
}


@dataclass
class PromptItem:
    """Representa un prompt maestro o personalizado en el catálogo."""
    id: str
    category: str  # "mode" | "style" | "custom"
    name: str
    description: str
    system_prompt: str
    user_template: str = "{text}"
    mode_key: Optional[str] = None  # ej. "enhance", "rewrite", "translate", "dialogue_analysis"
    parameters: Dict[str, Any] = field(default_factory=lambda: {"temperature": 0.4, "top_p": 0.9, "num_ctx": 4096})
    is_builtin: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptItem":
        return cls(
            id=data.get("id", ""),
            category=data.get("category", "custom"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", ""),
            user_template=data.get("user_template", "{text}"),
            mode_key=data.get("mode_key"),
            parameters=data.get("parameters", {"temperature": 0.4, "top_p": 0.9, "num_ctx": 4096}),
            is_builtin=data.get("is_builtin", False),
            metadata=data.get("metadata", {}),
        )


@dataclass
class NarrativeStyleDef:
    """Definición exhaustiva de un estilo narrativo bajo CO-STAR."""
    id: str
    name: str
    tone: str
    cadence: str
    vocabulary_profile: str
    prosody_guidance: str
    costar_framework: Dict[str, str] = field(default_factory=dict)
    system_prompt_addon: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NarrativeStyleDef":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            tone=data.get("tone", ""),
            cadence=data.get("cadence", ""),
            vocabulary_profile=data.get("vocabulary_profile", ""),
            prosody_guidance=data.get("prosody_guidance", ""),
            costar_framework=data.get("costar_framework", {}),
            system_prompt_addon=data.get("system_prompt_addon", ""),
        )

    def get_full_guidance(self) -> str:
        """Sintetiza las directrices estilísticas para inyectar en el system prompt."""
        lines = [
            f"- Tono emocional: {self.tone}",
            f"- Cadencia y ritmo: {self.cadence}",
            f"- Perfil de vocabulario: {self.vocabulary_profile}",
            f"- Directrices de prosodia y pausas: {self.prosody_guidance}",
        ]
        if self.system_prompt_addon:
            lines.append(f"- Reglas de estilo:\n{self.system_prompt_addon}")
        return "\n".join(lines)


class PromptLibrary:
    """Biblioteca y gestor central de prompts maestros persistente en JSON."""

    def __init__(self, json_path: Optional[str | Path] = None):
        self.json_path = Path(json_path) if json_path else DEFAULT_PROMPTS_PATH
        self.version: str = "1.0.0"
        self.metadata: Dict[str, Any] = {}
        self.active_configuration: Dict[str, str] = {
            "enhance": "builtin_enhance",
            "rewrite": "builtin_rewrite",
            "translate": "builtin_translate",
            "dialogue_analysis": "builtin_dialogue_analysis",
        }
        self.modes: Dict[str, PromptItem] = {}
        self.styles: Dict[str, NarrativeStyleDef] = {}
        self.custom_prompts: Dict[str, PromptItem] = {}

        self.load()

    def load(self) -> None:
        """Carga el catálogo desde el archivo JSON o crea defaults si no existe."""
        if not self.json_path.exists():
            logger.warning("Archivo de prompts no existe en %s. Creando inicial...", self.json_path)
            self._create_factory_defaults()
            self.save()
            return

        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.version = data.get("version", "1.0.0")
            self.metadata = data.get("metadata", {})
            self.active_configuration = data.get("active_configuration", self.active_configuration)

            self.modes = {}
            for k, v in data.get("modes", {}).items():
                self.modes[k] = PromptItem.from_dict(v)

            self.styles = {}
            for k, v in data.get("styles", {}).items():
                self.styles[k] = NarrativeStyleDef.from_dict(v)

            self.custom_prompts = {}
            for k, v in data.get("custom_prompts", {}).items():
                self.custom_prompts[k] = PromptItem.from_dict(v)

        except Exception as e:
            logger.error("Error al cargar %s: %s. Reconstruyendo defaults seguros...", self.json_path, e)
            self._create_factory_defaults()

    def save(self) -> None:
        """Persiste atómicamente el catálogo de prompts en formato JSON UTF-8."""
        data = {
            "version": self.version,
            "metadata": self.metadata,
            "active_configuration": self.active_configuration,
            "modes": {k: v.to_dict() for k, v in self.modes.items()},
            "styles": {k: v.to_dict() for k, v in self.styles.items()},
            "custom_prompts": {k: v.to_dict() for k, v in self.custom_prompts.items()},
        }
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.json_path.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_file.replace(self.json_path)
        logger.info("Catálogo de prompts guardado exitosamente en %s", self.json_path)

    def reset_to_defaults(self) -> None:
        """Restaura el catálogo a sus valores predeterminados de fábrica."""
        self._create_factory_defaults()
        self.save()

    def _create_factory_defaults(self) -> None:
        """Inicializa los modos y estilos de fábrica en memoria."""
        # Se asegura de poblar con la suite completa si el JSON no estuviera
        self.version = "1.0.0"
        self.metadata = {
            "engine": "Mistral NeMo 12B Instruct (Local Ollama)",
            "context_window": 4096,
            "framework": "Meta-Prompting CO-STAR & Voice Tag Ingestion",
            "description": "Catálogo Maestro de Prompts y Estilos Narrativos para GlobalTTS"
        }
        self.active_configuration = {
            "enhance": "builtin_enhance",
            "rewrite": "builtin_rewrite",
            "translate": "builtin_translate",
            "dialogue_analysis": "builtin_dialogue_analysis",
        }
        # Si el archivo JSON default existe en el repo, podemos leerlo
        if DEFAULT_PROMPTS_PATH.exists() and self.json_path != DEFAULT_PROMPTS_PATH:
            try:
                with open(DEFAULT_PROMPTS_PATH, "r", encoding="utf-8") as f:
                    master_data = json.load(f)
                self.modes = {k: PromptItem.from_dict(v) for k, v in master_data.get("modes", {}).items()}
                self.styles = {k: NarrativeStyleDef.from_dict(v) for k, v in master_data.get("styles", {}).items()}
                self.custom_prompts = {k: PromptItem.from_dict(v) for k, v in master_data.get("custom_prompts", {}).items()}
                return
            except Exception:
                pass

        # Fallback de código duro si el archivo maestro no existiera
        self._populate_fallback_objects()

    def _populate_fallback_objects(self) -> None:
        self.modes["builtin_enhance"] = PromptItem(
            id="builtin_enhance",
            category="mode",
            mode_key="enhance",
            name="Enriquecimiento Prosódico y Emocional",
            description="Inyecta etiquetas prosódicas y emocionales sin alterar palabras del texto original.",
            system_prompt=(
                "Eres el Principal Audio Narrative Director especializado en audiolibros dramáticos de alta fidelidad.\n"
                "Tu única tarea es enriquecer el texto insertando etiquetas de voz TTS.\n\n"
                "Etiquetas permitidas:\n"
                "- [pausa:1s], [pausa:500ms], [pausa:300ms]\n"
                "- [lento]...[/lento], [rapido]...[/rapido]\n"
                "- [susurro]...[/susurro], [enfasis]...[/enfasis]\n"
                "- [misterioso]...[/misterioso], [alegre]...[/alegre], [triste]...[/triste], [serio]...[/serio], [emocionado]...[/emocionado], [enojado]...[/enojado]\n\n"
                "REGLAS:\n"
                "1. NO cambies ni elimines ninguna palabra del texto original.\n"
                "2. Cierra siempre las etiquetas de rango.\n"
                "3. Devuelve únicamente el texto enriquecido sin introducciones ni comentarios."
            ),
            user_template="Texto a enriquecer:\n\n{text}",
            is_builtin=True,
        )

        self.modes["builtin_rewrite"] = PromptItem(
            id="builtin_rewrite",
            category="mode",
            mode_key="rewrite",
            name="Reescritura Narrativa Integral",
            description="Transforma el texto base en narración oral según persona, tiempo y estilo.",
            system_prompt=(
                "Eres un Master Storyteller y Narrador de Audiolibros.\n"
                "Tu misión es transformar el texto en una narración oral fluida y atrapante.\n\n"
                "PARÁMETROS:\n"
                "- Perspectiva: {persona_desc}\n"
                "- Tiempo verbal: {tense_desc}\n"
                "- Estilo: {style_name}\n"
                "{style_guidance}\n\n"
                "REGLAS:\n"
                "1. Conserva la esencia y hechos clave.\n"
                "2. Aplica la perspectiva y tiempo indicados.\n"
                "3. Inyecta etiquetas TTS ([pausa:1s], [lento], [susurro], [enfasis], [misterioso]).\n"
                "4. Responde únicamente con la narración final terminada."
            ),
            user_template="Texto base para transformar en narración:\n\n{text}",
            is_builtin=True,
        )

        self.modes["builtin_translate"] = PromptItem(
            id="builtin_translate",
            category="mode",
            mode_key="translate",
            name="Traducción y Adaptación Narrativa (es-LA)",
            description="Traduce y adapta cualquier texto al español latinoamericano neutro con alta eufonía para audiolibros.",
            system_prompt=(
                "Eres un Traductor Literario y Adaptador de Audio para Español Latinoamericano Neutro.\n"
                "Tu objetivo es traducir y adaptar el texto para que suene natural, fluido y expresivo al ser leído en voz alta.\n\n"
                "REGLAS:\n"
                "1. Traduce con fidelidad semántica priorizando fluidez oral.\n"
                "2. Emplea español latinoamericano estándar neutro.\n"
                "3. Responde únicamente con la traducción adaptada."
            ),
            user_template="Texto a traducir y adaptar:\n\n{text}",
            is_builtin=True,
        )

        self.modes["builtin_dialogue_analysis"] = PromptItem(
            id="builtin_dialogue_analysis",
            category="mode",
            mode_key="dialogue_analysis",
            name="Detección y Clasificación Dramática de Diálogos (Auto-Casting)",
            description="Segmenta el texto identificando narrador vs diálogos y emociones para casting multivoz.",
            system_prompt=(
                "Eres el Director de Casting y Analista Dramático de GlobalTTS.\n"
                "Desglosa el texto en segmentos JSON (narrador vs personajes), género vocal y emoción.\n"
                "Devuelve EXCLUSIVAMENTE JSON válido con characters y segments."
            ),
            user_template="Texto dramático a analizar:\n\n{text}",
            is_builtin=True,
        )

    # ==========================================
    # Consultas y Gestión de Modos
    # ==========================================
    def list_modes(self) -> List[PromptItem]:
        """Retorna la lista de modos maestros disponibles."""
        return list(self.modes.values())

    def get_mode_keys(self) -> List[str]:
        """Retorna las claves únicas de modo ("enhance", "rewrite", "translate", "dialogue_analysis")."""
        return ["enhance", "rewrite", "translate", "dialogue_analysis"]

    def get_mode_prompt(self, mode_key: str) -> Optional[PromptItem]:
        """Obtiene el PromptItem activo para un modo específico."""
        active_id = self.active_configuration.get(mode_key)
        if active_id:
            # Buscar en custom o en modes
            if active_id in self.custom_prompts:
                return self.custom_prompts[active_id]
            if active_id in self.modes:
                return self.modes[active_id]

        # Fallback: buscar por mode_key en self.modes
        for m in self.modes.values():
            if m.mode_key == mode_key:
                return m
        return None

    # ==========================================
    # Consultas y Gestión de Estilos
    # ==========================================
    def list_styles(self) -> List[NarrativeStyleDef]:
        """Retorna todos los estilos narrativos registrados."""
        return list(self.styles.values())

    def list_style_keys(self) -> List[str]:
        """Retorna las claves de los estilos disponibles."""
        return list(self.styles.keys())

    def get_style(self, style_id: str) -> Optional[NarrativeStyleDef]:
        """Obtiene la definición de un estilo por su identificador."""
        return self.styles.get(style_id)

    def add_style(self, style: NarrativeStyleDef, persist: bool = True) -> NarrativeStyleDef:
        """Registra o reemplaza un estilo narrativo."""
        self.styles[style.id] = style
        if persist:
            self.save()
        return style

    def update_style(self, style_id: str, **kwargs) -> NarrativeStyleDef:
        """Actualiza atributos de un estilo existente."""
        style = self.styles.get(style_id)
        if not style:
            raise KeyError(f"El estilo '{style_id}' no existe en el catálogo.")
        for k, v in kwargs.items():
            if hasattr(style, k) and v is not None:
                setattr(style, k, v)
        self.save()
        return style

    # ==========================================
    # Gestión de Prompts Personalizados / Duplicación
    # ==========================================
    def get_prompt(self, prompt_id: str) -> Optional[PromptItem]:
        """Busca un prompt por ID en modos, estilos o custom."""
        if prompt_id in self.modes:
            return self.modes[prompt_id]
        if prompt_id in self.custom_prompts:
            return self.custom_prompts[prompt_id]
        return None

    def list_all_prompts(self) -> List[PromptItem]:
        """Retorna la lista unificada de todos los prompts (modos y personalizados)."""
        all_items = list(self.modes.values()) + list(self.custom_prompts.values())
        return all_items

    def add_prompt(self, item: PromptItem, persist: bool = True) -> PromptItem:
        """Agrega un nuevo prompt personalizado."""
        item.is_builtin = False
        self.custom_prompts[item.id] = item
        if persist:
            self.save()
        return item

    def duplicate_prompt(self, source_id: str, new_id: str, new_name: str) -> PromptItem:
        """Duplica un prompt maestro existente para personalizarlo sin riesgo."""
        source = self.get_prompt(source_id)
        if not source:
            raise KeyError(f"Prompt origen '{source_id}' no encontrado.")
        if new_id in self.modes or new_id in self.custom_prompts:
            raise ValueError(f"El ID '{new_id}' ya está en uso.")

        new_item = copy.deepcopy(source)
        new_item.id = new_id
        new_item.name = new_name
        new_item.is_builtin = False
        new_item.category = "custom"
        self.custom_prompts[new_id] = new_item
        self.save()
        return new_item

    def update_prompt(self, prompt_id: str, **fields) -> PromptItem:
        """Actualiza campos de un prompt (system_prompt, user_template, parameters, etc.)."""
        target: Optional[PromptItem] = None
        if prompt_id in self.custom_prompts:
            target = self.custom_prompts[prompt_id]
        elif prompt_id in self.modes:
            target = self.modes[prompt_id]

        if not target:
            raise KeyError(f"Prompt '{prompt_id}' no encontrado.")

        for k, v in fields.items():
            if hasattr(target, k) and v is not None:
                setattr(target, k, v)
        self.save()
        return target

    def delete_prompt(self, prompt_id: str) -> bool:
        """Elimina un prompt personalizado (los built-in no se pueden eliminar)."""
        if prompt_id in self.modes and self.modes[prompt_id].is_builtin:
            raise ValueError(f"No se puede eliminar el prompt predeterminado del sistema '{prompt_id}'.")

        if prompt_id in self.custom_prompts:
            del self.custom_prompts[prompt_id]
            # Si era el activo en algún modo, revertir a default
            for k, active_id in list(self.active_configuration.items()):
                if active_id == prompt_id:
                    self.active_configuration[k] = f"builtin_{k}"
            self.save()
            return True
        return False

    def set_active_prompt(self, mode_key: str, prompt_id: str) -> None:
        """Configura el prompt activo para un modo específico."""
        prompt = self.get_prompt(prompt_id)
        if not prompt:
            raise KeyError(f"Prompt '{prompt_id}' no existe en la biblioteca.")
        self.active_configuration[mode_key] = prompt_id
        self.save()

    def get_active_prompt_id(self, mode_key: str) -> str:
        """Obtiene el ID del prompt activo para el modo dado."""
        return self.active_configuration.get(mode_key, f"builtin_{mode_key}")

    # ==========================================
    # Sincronización Bidireccional con Markdown
    # ==========================================
    def import_from_markdown(self, md_path: Path | str) -> int:
        """Importa y actualiza modos y estilos narrativos desde el archivo PROMPTS_MAESTROS.md."""
        md_file = Path(md_path)
        if not md_file.exists():
            raise FileNotFoundError(f"Archivo de prompts markdown no encontrado: {md_file}")

        text = md_file.read_text(encoding="utf-8")
        updated_count = 0

        # 1. Parsear Modos de IA (Sección 3)
        mode_matches = re.split(r"(?=### Modo \d+:)", text)
        for block in mode_matches:
            if not block.strip().startswith("### Modo"):
                continue
            id_m = re.search(r"-\s+\*\*ID:\*\*\s+`?([a-zA-Z0-9_]+)`?", block)
            key_m = re.search(r"-\s+\*\*Modo Key:\*\*\s+`?([a-zA-Z0-9_]+)`?", block)
            name_m = re.search(r"-\s+\*\*Nombre:\*\*\s+(.+)", block)
            desc_m = re.search(r"-\s+\*\*Descripción:\*\*\s+(.+)", block)
            temp_m = re.search(r"`temperature`:\s*([0-9.]+)", block)
            topp_m = re.search(r"`top_p`:\s*([0-9.]+)", block)
            ctx_m = re.search(r"`num_ctx`:\s*([0-9]+)", block)

            blocks_code = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", block)
            user_tmpl = "{text}"
            sys_prompt = ""
            if len(blocks_code) >= 2:
                user_tmpl = blocks_code[0].strip()
                sys_prompt = blocks_code[1].strip()
            elif len(blocks_code) == 1:
                sys_prompt = blocks_code[0].strip()

            if id_m:
                m_id = id_m.group(1).strip()
                m_key = key_m.group(1).strip() if key_m else m_id.replace("builtin_", "")
                m_name = name_m.group(1).strip() if name_m else m_id
                m_desc = desc_m.group(1).strip() if desc_m else ""

                params = {"temperature": 0.4, "top_p": 0.9, "num_ctx": 4096}
                if temp_m:
                    params["temperature"] = float(temp_m.group(1))
                if topp_m:
                    params["top_p"] = float(topp_m.group(1))
                if ctx_m:
                    params["num_ctx"] = int(ctx_m.group(1))

                if m_id in self.modes:
                    item = self.modes[m_id]
                    item.name = m_name
                    item.description = m_desc
                    item.parameters = params
                    if sys_prompt:
                        item.system_prompt = sys_prompt
                    if user_tmpl:
                        item.user_template = user_tmpl
                else:
                    self.modes[m_id] = PromptItem(
                        id=m_id,
                        category="mode",
                        name=m_name,
                        description=m_desc,
                        system_prompt=sys_prompt,
                        user_template=user_tmpl,
                        mode_key=m_key,
                        parameters=params,
                        is_builtin=True,
                    )
                updated_count += 1

        # 2. Parsear Estilos Narrativos (Sección 4)
        style_matches = re.split(r"(?=### \d+\.\s+`[^`]+`)", text)
        for block in style_matches:
            header_m = re.match(r"### \d+\.\s+`([^`]+)`\s+\(([^)]+)\)", block.strip())
            if not header_m:
                continue
            s_id = header_m.group(1).strip()
            fallback_name = header_m.group(2).strip()

            name_m = re.search(r"-\s+\*\*Nombre:\*\*\s+(.+)", block)
            tone_m = re.search(r"-\s+\*\*Tono:\*\*\s+(.+)", block)
            cad_m = re.search(r"-\s+\*\*Cadencia:\*\*\s+(.+)", block)
            voc_m = re.search(r"-\s+\*\*Perfil de Vocabulario:\*\*\s+(.+)", block)
            pros_m = re.search(r"-\s+\*\*Guía Prosódica:\*\*\s+(.+)", block)

            addon_blocks = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", block)
            sys_addon = addon_blocks[0].strip() if addon_blocks else ""

            s_name = name_m.group(1).strip() if name_m else fallback_name
            s_tone = tone_m.group(1).strip() if tone_m else ""
            s_cad = cad_m.group(1).strip() if cad_m else ""
            s_voc = voc_m.group(1).strip() if voc_m else ""
            s_pros = pros_m.group(1).strip() if pros_m else ""

            if s_id in self.styles:
                style_item = self.styles[s_id]
                style_item.name = s_name
                style_item.tone = s_tone
                style_item.cadence = s_cad
                style_item.vocabulary_profile = s_voc
                style_item.prosody_guidance = s_pros
                if sys_addon:
                    style_item.system_prompt_addon = sys_addon
            else:
                self.styles[s_id] = NarrativeStyleDef(
                    id=s_id,
                    name=s_name,
                    tone=s_tone,
                    cadence=s_cad,
                    vocabulary_profile=s_voc,
                    prosody_guidance=s_pros,
                    system_prompt_addon=sys_addon,
                )
            updated_count += 1

        self.save()
        logger.info("Sincronizados exitosamente %d prompts y estilos desde %s", updated_count, md_file.name)
        return updated_count

    def export_to_markdown(self, md_path: Path | str) -> None:
        """Exporta el catálogo completo de prompts maestros y estilos a formato Markdown PROMPTS_MAESTROS.md."""
        md_file = Path(md_path)
        lines = [
            "# GLOBAL TTS — CATÁLOGO MAESTRO DE PROMPTS Y DIRECTRICES DE INFERENCIA LOCAL",
            "",
            "> **DOCUMENTO MAESTRO VINCULANTE (SSOT - SINGLE SOURCE OF TRUTH)**  ",
            "> **Firma Institucional:** `HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®`  ",
            "> **Motor de Inferencia Local:** Mistral NeMo 12B Instruct (`mistral-nemo-local:latest`) vía Ollama  ",
            "> **Motor de Síntesis Vocal:** Piper VITS Local (Sherpa-ONNX 22.05 kHz / 16 kHz) con Normalización EBU R128 (-16 LUFS)  ",
            "> **Context Window:** 8,192 tokens  ",
            f"> **Última Actualización:** {datetime.now().strftime('%Y-%m-%d')}  ",
            "",
            "---",
            "",
            "## 1. Contexto de Arquitectura para Agentes e Ingenieros de Prompts",
            "",
            "Este documento define la configuración operativa, los *System Prompts*, los esquemas de *Meta-Prompting* y los parámetros de hiperajuste para el pipeline de inteligencia artificial local de **GlobalTTS**.",
            "",
            "Cualquier agente inteligente o desarrollador que consulte este documento debe comprender el pipeline técnico:",
            "",
            "```",
            "[ Texto Original ] ",
            "       │",
            "       ▼",
            "[ Preprocesamiento & Limpieza Fonética (text_clean.py) ]",
            "       │",
            "       ▼",
            "[ Mistral NeMo 12B Local (Ollama - Context 4096) ]",
            "       │  ├── Modo Enhance: Inyección de tags prosódicos sin cambiar texto",
            "       │  ├── Modo Rewrite: Reescritura narrativa en 11 estilos CO-STAR",
            "       │  ├── Modo Translate: Adaptación a español latino neutro (es-LA)",
            "       │  └── Modo Dialogue: Auto-casting dramático narrador vs personajes",
            "       │",
            "       ▼",
            "[ Intérprete Fonético & Segmentador de Cláusulas (markup/parser.py) ]",
            "       │",
            "       ▼",
            "[ Motor de Síntesis Piper VITS (piper_engine.py / ONNX DirectML) ]",
            "       │",
            "       ▼",
            "[ Normalización EBU R128 / Empaquetado MP3 256k & Video Karaoke MP4 ]",
            "```",
            "",
            "### Reglas Críticas para la Modificación de Prompts por Agentes:",
            "1. **Cero Texto Conversacional:** Los prompts deben obligar al modelo a entregar **únicamente** el texto transformado. Queda estrictamente prohibido que el modelo genere preámbulos, saludos, comentarios o despedidas (\"Aquí tienes tu texto:\", \"Espero que te guste:\", etc.).",
            "2. **Preservación Estricta de Etiquetas:** Las etiquetas de rango (`[lento]...[/lento]`, `[susurro]...[/susurro]`) deben estar correctamente balanceadas. Las etiquetas de punto (`[pausa:1s]`, `[pausa:500ms]`) no llevan cierre.",
            "3. **Fidelidad Semántica:** En el modo `enhance`, está prohibido añadir o eliminar palabras. En el modo `rewrite`, los hechos, cronología y nombres propios deben mantenerse invariables.",
            "4. **Sincronización Bidireccional:** Cualquier edición realizada en este documento se sincroniza automáticamente con el archivo [`src/ai/prompts_master.json`](file:///c:/antigravityAS/GlobalTTS/src/ai/prompts_master.json) y se refleja en caliente en la interfaz de usuario de GlobalTTS.",
            "",
            "---",
            "",
            "## 2. Etiquetas Prosódicas y Fonéticas Soportadas por el Motor TTS",
            "",
            "| Etiqueta | Tipo | Función Sonora | Ejemplo de Uso |",
            "| :--- | :--- | :--- | :--- |",
            "| `[pausa:1s]` | Punto | Silencio dramático de 1.0 segundo | `La puerta se abrió lentamente. [pausa:1s] No había nadie.` |",
            "| `[pausa:500ms]` | Punto | Respiración o inflexión de medio segundo | `Miró a su alrededor, [pausa:500ms] dudando si avanzar.` |",
            "| `[pausa:300ms]` | Punto | Micropausa de cadencia rítmica | `Era verdad; [pausa:300ms] lo sabía muy bien.` |",
            "| `[lento]...[/lento]` | Rango | Reduce la velocidad al 75% | `[lento]El tiempo parecía haberse detenido en la sala.[/lento]` |",
            "| `[rapido]...[/rapido]` | Rango | Aumenta la velocidad al 130% | `[rapido]¡Corre, antes de que sea demasiado tarde![/rapido]` |",
            "| `[susurro]...[/susurro]` | Rango | Modulación de baja amplitud e intimidad | `[susurro]No hagas ningún ruido, nos están buscando.[/susurro]` |",
            "| `[enfasis]...[/enfasis]` | Rango | Realce de intensidad y claridad fonética | `Esa fue [enfasis]la única vez[/enfasis] que volvieron a verlo.` |",
            "| `[misterioso]...[/misterioso]` | Rango | Atmósfera tensa, sombría y pausada | `[misterioso]Bajo las sombras del bosque, algo se movía.[/misterioso]` |",
            "| `[alegre]...[/alegre]` | Rango | Tono brillante, ritmo ágil y ascendente | `[alegre]¡Por fin lo hemos conseguido todos juntos![/alegre]` |",
            "| `[triste]...[/triste]` | Rango | Cadencia descendente y melancólica | `[triste]Ya nada volvió a ser como en aquellos días.[/triste]` |",
            "| `[serio]...[/serio]` | Rango | Solemnidad, firmeza y peso institucional | `[serio]El dictamen final fue inapelable y contundente.[/serio]` |",
            "| `[emocionado]...[/emocionado]` | Rango | Intensidad dramática y vibración vocal | `[emocionado]¡El descubrimiento cambiará el rumbo de la ciencia![/emocionado]` |",
            "| `[enojado]...[/enojado]` | Rango | Golpe seco, ritmo tajante y firme | `[enojado]¡Basta de excusas inútiles, quiero resultados![/enojado]` |",
            "",
            "---",
            "",
            "## 3. Catálogo Maestro de Modos de IA",
            ""
        ]

        mode_num = 1
        for mode in self.list_modes():
            lines.extend([
                f"### Modo {mode_num}: `{mode.id}`",
                f"- **ID:** `{mode.id}`",
                f"- **Modo Key:** `{mode.mode_key or mode.id.replace('builtin_', '')}`",
                f"- **Nombre:** {mode.name}",
                f"- **Descripción:** {mode.description}",
                "- **Parámetros:**",
                f"  - `temperature`: {mode.parameters.get('temperature', 0.4):.2f}",
                f"  - `top_p`: {mode.parameters.get('top_p', 0.9):.2f}",
                f"  - `num_ctx`: {mode.parameters.get('num_ctx', 4096)}",
                "- **Plantilla de Usuario:**",
                "```",
                mode.user_template,
                "```",
                "- **System Prompt:**",
                "```",
                mode.system_prompt,
                "```",
                "",
                "---",
                ""
            ])
            mode_num += 1

        lines.extend([
            "## 4. Catálogo de los 11 Estilos Narrativos Industriales",
            ""
        ])

        style_num = 1
        for style in self.list_styles():
            lines.extend([
                f"### {style_num}. `{style.id}` ({style.name})",
                f"- **Nombre:** {style.name}",
                f"- **Tono:** {style.tone}",
                f"- **Cadencia:** {style.cadence}",
                f"- **Perfil de Vocabulario:** {style.vocabulary_profile}",
                f"- **Guía Prosódica:** {style.prosody_guidance}",
                "- **Addon del System Prompt:**",
                "```",
                style.system_prompt_addon,
                "```",
                "",
                "---",
                ""
            ])
            style_num += 1

        lines.extend([
            "## 5. Protocolo de Sincronización Automática",
            "",
            "El motor `PromptLibrary` ([`src/ai/prompt_library.py`](file:///c:/antigravityAS/GlobalTTS/src/ai/prompt_library.py)) dispone de sincronización bidireccional entre este documento y el sistema:",
            "",
            "1. **Desde este documento a la aplicación:**",
            "   Al editar cualquiera de las secciones de este archivo, la aplicación GlobalTTS permite sincronizar los cambios de inmediato presionando el botón `[ Sincronizar desde PROMPTS_MAESTROS.md ]` dentro de la pestaña `PROMPTS MAESTROS & ESTILOS`, o ejecutando:",
            "   ```powershell",
            "   python -c \"from src.ai.prompt_library import PromptLibrary; PromptLibrary().import_from_markdown('PROMPTS_MAESTROS.md')\"",
            "   ```",
            "2. **Desde la aplicación a este documento:**",
            "   Cualquier nuevo prompt o modificación realizada a través de la interfaz gráfica puede exportarse de vuelta para actualizar este documento mediante:",
            "   ```powershell",
            "   python -c \"from src.ai.prompt_library import PromptLibrary; PromptLibrary().export_to_markdown('PROMPTS_MAESTROS.md')\"",
            "   ```",
            ""
        ])

        md_file.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Exportado exitosamente catálogo maestro a %s", md_file.name)

    # ==========================================
    # Motor de Meta-Prompting y Renderizado
    # ==========================================
    @staticmethod
    def safe_format(template: str, clean_unmatched: bool = True, **kwargs) -> str:
        """Interpola variables en la plantilla de forma segura y tolerante.

        Si clean_unmatched es True, los marcadores simples no provistos ({missing})
        se limpian sin afectar llaves literales del texto del usuario.
        """
        result = template
        user_text = kwargs.pop("text", None)

        for k, v in kwargs.items():
            placeholder = "{" + k + "}"
            result = result.replace(placeholder, str(v) if v is not None else "")

        if user_text is not None:
            result = result.replace("{text}", "__GLOBAL_TTS_USER_TEXT__")

        if clean_unmatched:
            result = re.sub(r"\{[A-Za-z_][A-Za-z0-9_]*\}", "", result)

        if user_text is not None:
            result = result.replace("__GLOBAL_TTS_USER_TEXT__", str(user_text))

        return result

    def get_persona_desc(self, persona_code: str) -> str:
        return PERSONA_DESCRIPTIONS.get(persona_code, PERSONA_DESCRIPTIONS["3ra"])

    def get_tense_desc(self, tense_code: str) -> str:
        return TENSE_DESCRIPTIONS.get(tense_code, TENSE_DESCRIPTIONS["pasado"])

    def build_prompt_for_mode(
        self,
        mode: str,
        text: str,
        persona: str = "3ra",
        tense: str = "pasado",
        style: str = "cuento",
        prompt_id: Optional[str] = None,
        custom_system_prompt: Optional[str] = None,
        custom_template: Optional[str] = None,
        **extra_vars: Any
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Construye e interpola el par (system_prompt, user_prompt, parameters) listo para inferencia."""
        # 1. Determinar el prompt item base
        item: Optional[PromptItem] = None
        if prompt_id:
            item = self.get_prompt(prompt_id)

        if not item:
            item = self.get_mode_prompt(mode)

        if not item:
            # Fallback seguro
            item = self.modes.get(f"builtin_{mode}") or self.modes.get("builtin_enhance")

        # 2. Obtener definición del estilo si aplica
        style_def = self.get_style(style)
        if not style_def:
            style_def = self.get_style("cuento") or NarrativeStyleDef(
                id="cuento",
                name="Cuento Literario",
                tone="Cálido y cautivador",
                cadence="Pausada",
                vocabulary_profile="Literario refinado",
                prosody_guidance="Pausas y susurros sutiles",
                system_prompt_addon="",
            )

        # 3. Preparar variables de interpolación
        persona_desc = self.get_persona_desc(persona)
        tense_desc = self.get_tense_desc(tense)
        style_guidance = style_def.get_full_guidance()

        interpolations = {
            "text": text,
            "persona": persona,
            "persona_desc": persona_desc,
            "tense": tense,
            "tense_desc": tense_desc,
            "style": style,
            "style_name": style_def.name,
            "style_guidance": style_guidance,
            **extra_vars,
        }

        # 4. Formatear System Prompt
        sys_template = custom_system_prompt if custom_system_prompt else item.system_prompt
        rendered_sys = self.safe_format(sys_template, **interpolations)

        # 5. Formatear User Prompt
        usr_template = custom_template if custom_template else item.user_template
        rendered_usr = self.safe_format(usr_template, **interpolations)

        parameters = copy.deepcopy(item.parameters)
        return rendered_sys, rendered_usr, parameters
