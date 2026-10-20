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
    parameters: Dict[str, Any] = field(default_factory=lambda: {"temperature": 0.4, "top_p": 0.9, "num_ctx": 8192})
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
            parameters=data.get("parameters", {"temperature": 0.4, "top_p": 0.9, "num_ctx": 8192}),
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
            "context_window": 8192,
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
