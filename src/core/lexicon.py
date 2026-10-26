"""Diccionario Fonético y Corrector Léxico Persistente (Lexicon).

Transforma siglas, acrónimos técnicos, abreviaturas, unidades de medida y
anglicismos a su fonética exacta en español antes de la síntesis TTS,
garantizando que las redes neurales Kokoro y Piper pronuncien cada término
con naturalidad nativa sin alterar las etiquetas prosódicas `[...]`.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("globaltts.lexicon")

DEFAULT_LEXICON_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "lexicon.json"


@dataclass
class LexiconEntry:
    term: str
    phonetic: str
    case_sensitive: bool = True
    category: str = "general"  # "acronimo" | "anglicismo" | "unidad" | "abreviatura" | "custom"
    enabled: bool = True


DEFAULT_ENTRIES: list[LexiconEntry] = [
    LexiconEntry("IA", "inteligencia artificial", True, "acronimo"),
    LexiconEntry("IAs", "inteligencias artificiales", True, "acronimo"),
    LexiconEntry("LLM", "ele ele eme", True, "acronimo"),
    LexiconEntry("LLMs", "modelos de lenguaje", True, "acronimo"),
    LexiconEntry("GPU", "ge pe u", True, "acronimo"),
    LexiconEntry("GPUs", "ge pe us", True, "acronimo"),
    LexiconEntry("iGPU", "ge pe u integrada", True, "acronimo"),
    LexiconEntry("CPU", "ce pe u", True, "acronimo"),
    LexiconEntry("VRAM", "ve ram", True, "acronimo"),
    LexiconEntry("SQL", "ese cu ele", True, "acronimo"),
    LexiconEntry("NoSQL", "no ese cu ele", True, "acronimo"),
    LexiconEntry("API", "api", True, "acronimo"),
    LexiconEntry("APIs", "apis", True, "acronimo"),
    LexiconEntry("TTS", "te te ese", True, "acronimo"),
    LexiconEntry("OCR", "o ce erre", True, "acronimo"),
    LexiconEntry("DSP", "de ese pe", True, "acronimo"),
    LexiconEntry("UI", "interfaz de usuario", True, "acronimo"),
    LexiconEntry("UX", "experiencia de usuario", True, "acronimo"),
    LexiconEntry("URL", "u erre ele", True, "acronimo"),
    LexiconEntry("HTML", "hache te eme ele", True, "acronimo"),
    LexiconEntry("CSS", "ce ese ese", True, "acronimo"),
    LexiconEntry("JSON", "yeison", True, "anglicismo"),
    LexiconEntry("ONNX", "ónix", True, "anglicismo"),
    LexiconEntry("PyTorch", "páitorch", False, "anglicismo"),
    LexiconEntry("DirectML", "direct eme ele", False, "anglicismo"),
    LexiconEntry("ROCm", "roc eme", False, "anglicismo"),
    LexiconEntry("WiFi", "güifi", False, "anglicismo"),
    LexiconEntry("Podcast", "pódcast", False, "anglicismo"),
    LexiconEntry("Streaming", "estríming", False, "anglicismo"),
    LexiconEntry("Framework", "fréimwork", False, "anglicismo"),
    LexiconEntry("Pipeline", "páip-lain", False, "anglicismo"),
    LexiconEntry("Prompt", "prompt", False, "anglicismo"),
    LexiconEntry("Prompts", "prompts", False, "anglicismo"),
    LexiconEntry("kHz", "kilohercios", True, "unidad"),
    LexiconEntry("MHz", "megahercios", True, "unidad"),
    LexiconEntry("GHz", "gigahercios", True, "unidad"),
    LexiconEntry("dB", "decibelios", True, "unidad"),
    LexiconEntry("dBTP", "decibelios de pico real", True, "unidad"),
    LexiconEntry("LUFS", "lufs", True, "unidad"),
    LexiconEntry("GB", "gigabytes", True, "unidad"),
    LexiconEntry("MB", "megabytes", True, "unidad"),
    LexiconEntry("KB", "kilobytes", True, "unidad"),
    LexiconEntry("EE. UU.", "Estados Unidos", False, "abreviatura"),
    LexiconEntry("EE.UU.", "Estados Unidos", False, "abreviatura"),
    LexiconEntry("s. XXI", "siglo veintiuno", False, "abreviatura"),
    LexiconEntry("s. XX", "siglo veinte", False, "abreviatura"),
    LexiconEntry("s. XIX", "siglo diecinueve", False, "abreviatura"),
    LexiconEntry("s. XVIII", "siglo dieciocho", False, "abreviatura"),
    LexiconEntry("Dr.", "Doctor", True, "abreviatura"),
    LexiconEntry("Dra.", "Doctora", True, "abreviatura"),
    LexiconEntry("Sr.", "Señor", True, "abreviatura"),
    LexiconEntry("Sra.", "Señora", True, "abreviatura"),
    LexiconEntry("Prof.", "Profesor", True, "abreviatura"),
    LexiconEntry("Pág.", "Página", False, "abreviatura"),
    LexiconEntry("Cap.", "Capítulo", False, "abreviatura"),
]

_TAG_SPLIT_RE = re.compile(r"(\[[^\[\]]+\])")


class PhoneticLexicon:
    """Gestor del diccionario fonético con persistencia JSON y reemplazo seguro."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_LEXICON_PATH
        self.entries: dict[str, LexiconEntry] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.reset_defaults()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries.clear()
            for item in raw.get("entries", []):
                entry = LexiconEntry(
                    term=str(item["term"]).strip(),
                    phonetic=str(item["phonetic"]).strip(),
                    case_sensitive=bool(item.get("case_sensitive", True)),
                    category=str(item.get("category", "custom")),
                    enabled=bool(item.get("enabled", True)),
                )
                if entry.term:
                    self.entries[entry.term] = entry
        except Exception as exc:
            logger.warning("Error cargando lexicon.json (%s). Restaurando valores por defecto.", exc)
            self.reset_defaults()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [asdict(e) for e in self.entries.values()]}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def reset_defaults(self) -> None:
        self.entries = {e.term: LexiconEntry(**asdict(e)) for e in DEFAULT_ENTRIES}
        self.save()

    def add_entry(
        self,
        term: str,
        phonetic: str,
        case_sensitive: bool = True,
        category: str = "custom",
        enabled: bool = True,
    ) -> LexiconEntry:
        clean_term = term.strip()
        clean_phon = phonetic.strip()
        if not clean_term or not clean_phon:
            raise ValueError("El término y su fonética no pueden estar vacíos.")
        entry = LexiconEntry(
            term=clean_term,
            phonetic=clean_phon,
            case_sensitive=case_sensitive,
            category=category,
            enabled=enabled,
        )
        self.entries[clean_term] = entry
        self.save()
        return entry

    def remove_entry(self, term: str) -> bool:
        if term in self.entries:
            del self.entries[term]
            self.save()
            return True
        return False

    def list_entries(self) -> list[LexiconEntry]:
        return list(self.entries.values())

    def apply(self, text: str) -> str:
        """Aplica todas las reglas fonéticas activas respetando intactas las etiquetas [...] de prosodia/SFX."""
        if not text or not self.entries:
            return text

        active = [e for e in self.entries.values() if e.enabled and e.term and e.phonetic]
        if not active:
            return text

        # Ordenar por longitud descendente para evitar reemplazos parciales ("EE. UU." antes que "UU.")
        active.sort(key=lambda x: len(x.term), reverse=True)

        parts = _TAG_SPLIT_RE.split(text)
        out_parts: list[str] = []

        for part in parts:
            if not part:
                continue
            if part.startswith("[") and part.endswith("]"):
                out_parts.append(part)
                continue

            segment = part
            for entry in active:
                escaped = re.escape(entry.term)
                # Si el término termina en punto (ej. "Dr."), no exigir \b al final
                prefix = r"(?<![\wáéíóúÁÉÍÓÚñÑ])"
                suffix = r"(?![\wáéíóúÁÉÍÓÚñÑ])"
                flags = 0 if entry.case_sensitive else re.IGNORECASE
                pattern = re.compile(f"{prefix}{escaped}{suffix}", flags)
                segment = pattern.sub(entry.phonetic, segment)

            out_parts.append(segment)

        return "".join(out_parts)
