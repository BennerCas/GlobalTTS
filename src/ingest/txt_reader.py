"""Lector de texto plano (.txt / .md)."""
from __future__ import annotations

import re
from pathlib import Path

from src.core.models import DocumentError
from src.ingest.common import group_into_chapters, is_heading, unwrap_lines

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
    raw_blocks = _BLANK_LINES_RE.split(text)
    blocks: list[str] = []
    for b in raw_blocks:
        b_clean = unwrap_lines(b)
        if not b_clean:
            continue
        lines = [l.strip() for l in b.split("\n") if l.strip()]
        if len(lines) > 1 and is_heading(lines[0]):
            blocks.append(lines[0])
            rest = unwrap_lines("\n".join(lines[1:]))
            if rest:
                blocks.append(rest)
        else:
            blocks.append(b_clean)

    return {
        "title": path.stem,
        "author": "",
        "chapters": group_into_chapters(blocks, default_title=path.stem),
    }
