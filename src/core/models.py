"""Modelos de datos inmutables del pipeline Documento -> Audiolibro."""
from __future__ import annotations

from dataclasses import dataclass


class DocumentError(Exception):
    """Error base al leer o validar un documento de entrada."""


class UnsupportedFormatError(DocumentError):
    """Extensión de archivo no soportada."""


class ScannedPdfError(DocumentError):
    """PDF sin capa de texto (escaneado); el OCR queda fuera del alcance."""


class UnsafeArchiveError(DocumentError):
    """Archivo comprimido (EPUB) con tamaño o ratio sospechoso (zip-bomb)."""


@dataclass(frozen=True)
class Chapter:
    """Capítulo: título y párrafos de texto plano."""

    title: str
    paragraphs: tuple[str, ...]

    @property
    def char_count(self) -> int:
        return sum(len(p) for p in self.paragraphs)


@dataclass(frozen=True)
class Document:
    """Documento ya leído y normalizado, independiente del formato de origen."""

    title: str
    author: str
    language: str  # "es" | "en" | "unknown"
    chapters: tuple[Chapter, ...]
    source_path: str
    source_sha256: str

    @property
    def char_count(self) -> int:
        return sum(c.char_count for c in self.chapters)
