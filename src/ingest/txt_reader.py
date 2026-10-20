"""Lector de texto plano (.txt / .md)."""
from __future__ import annotations

import re
from pathlib import Path

from src.core.models import DocumentError
from src.ingest.common import group_into_chapters, unwrap_lines

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")


def decode_text(raw: bytes) -> str:
    """Decodifica probando UTF-8 (con/sin BOM) y cp1252; ``latin-1`` nunca falla."""
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_txt(path: Path) -> dict:
    """Devuelve ``{"title", "author", "chapters"}`` a partir de un archivo de texto."""
    text = decode_text(path.read_bytes()).replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise DocumentError(f"El archivo está vacío: {path.name}")
    blocks = [unwrap_lines(b) for b in _BLANK_LINES_RE.split(text)]
    blocks = [b for b in blocks if b]
    return {
        "title": path.stem,
        "author": "",
        "chapters": group_into_chapters(blocks, default_title=path.stem),
    }
