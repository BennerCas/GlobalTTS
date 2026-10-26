"""Utilidades compartidas por los lectores de documentos."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from src.core.models import Chapter

# Encabezados de capítulo habituales (ES/EN), números romanos o encabezados Markdown en una sola línea corta.
HEADING_RE = re.compile(
    r"^\s*(?:"
    r"(?:#{1,3}\s+.{1,80})|"
    r"(?:(?:cap[ií]tulo|chapter|parte|part|libro|book|pr[oó]logo|ep[ií]logo|prologue|epilogue|introducci[oó]n|conclusi[oó]n|acto|escena|secci[oó]n|ap[eé]ndice)\b.{0,80})|"
    r"(?:(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII|XIV|XV|XVI|XVII|XVIII|XIX|XX)[\.\s:-]+\s*[A-ZÁÉÍÓÚÑ].{1,70})"
    r")$",
    re.IGNORECASE,
)
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\s*\n\s*([a-záéíóúñü])")


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Hash SHA-256 en streaming (soporta archivos grandes)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_paragraph(text: str) -> str:
    """Quita caracteres invisibles/de control y colapsa espacios en blanco."""
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    text = _CONTROL_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def unwrap_lines(block: str) -> str:
    """Une líneas cortadas por maquetación y repara palabras partidas con guion."""
    block = _HYPHEN_BREAK_RE.sub(r"\1\2", block)
    return normalize_paragraph(block)


def is_heading(line: str) -> bool:
    return bool(HEADING_RE.match(line)) and len(line.strip()) <= 100


def group_into_chapters(blocks: Iterable[str], default_title: str) -> tuple[Chapter, ...]:
    """Agrupa párrafos en capítulos usando líneas de encabezado como separadores."""
    chapters: list[Chapter] = []
    title = default_title
    current: list[str] = []

    def flush() -> None:
        if current:
            chapters.append(Chapter(title=title, paragraphs=tuple(current)))

    for block in blocks:
        if is_heading(block):
            flush()
            title, current = normalize_paragraph(block), []
        else:
            current.append(block)
    flush()
    return tuple(chapters)
