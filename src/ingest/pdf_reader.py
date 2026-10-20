"""Lector de PDF con capa de texto (PyMuPDF).

Heurísticas: orden de lectura por bloques, eliminación de encabezados/pies repetidos y
números de página, reparación de guiones de fin de línea, unión de párrafos partidos entre
páginas y capítulos a partir de los marcadores (TOC) si existen.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from src.core.models import Chapter, DocumentError, ScannedPdfError
from src.ingest.common import group_into_chapters, normalize_paragraph, unwrap_lines

BAND = 0.08  # fracción superior/inferior de la página tratada como encabezado/pie
REPEAT_RATIO = 0.30  # un bloque en banda repetido en >=30% de páginas es encabezado/pie
MIN_CHARS_PER_PAGE = 25  # por debajo: PDF escaneado
_PAGE_NUM_RE = re.compile(r"^\s*(?:p[áa]g(?:ina)?\.?\s*)?\d{1,4}(?:\s*(?:/|de|of)\s*\d{1,4})?\s*$", re.IGNORECASE)
_SENTENCE_END = tuple('.!?…:;"”»)]')


def _band_key(text: str) -> str:
    return re.sub(r"\d+", "#", normalize_paragraph(text)).lower()


def _page_blocks(page) -> list[tuple[float, float, str]]:
    """Bloques de texto (y0, y1, texto) en orden de lectura."""
    blocks = page.get_text("blocks", sort=True)
    return [(b[1], b[3], b[4]) for b in blocks if b[6] == 0 and b[4].strip()]


def _collect_paragraphs(pdf) -> list[tuple[int, str]]:
    pages = [(p.rect.height, _page_blocks(p)) for p in pdf]
    total_chars = sum(len(t) for _, bl in pages for *_, t in bl)
    if pdf.page_count == 0 or total_chars / pdf.page_count < MIN_CHARS_PER_PAGE:
        raise ScannedPdfError("El PDF no tiene capa de texto (parece escaneado); OCR no soportado.")

    in_band: Counter[str] = Counter()
    for height, blocks in pages:
        for y0, y1, text in blocks:
            if y0 < BAND * height or y1 > (1 - BAND) * height:
                in_band[_band_key(text)] += 1
    threshold = max(3, REPEAT_RATIO * pdf.page_count)
    repeated = {k for k, n in in_band.items() if n >= threshold}

    paragraphs: list[tuple[int, str]] = []
    for page_idx, (height, blocks) in enumerate(pages):
        for y0, y1, text in blocks:
            clean = unwrap_lines(text)
            if not clean:
                continue
            at_edge = y0 < BAND * height or y1 > (1 - BAND) * height
            if at_edge and (_PAGE_NUM_RE.match(clean) or _band_key(text) in repeated):
                continue
            paragraphs.append((page_idx, clean))
    return _merge_split_paragraphs(paragraphs)


def _merge_split_paragraphs(paragraphs: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Une un párrafo que continúa en la página siguiente (sin cierre de oración)."""
    merged: list[tuple[int, str]] = []
    for page, text in paragraphs:
        if merged and merged[-1][0] != page:
            prev_page, prev = merged[-1]
            if not prev.endswith(_SENTENCE_END) and text[:1].islower():
                merged[-1] = (prev_page, f"{prev} {text}")
                continue
        merged.append((page, text))
    return merged


def _chapters_from_toc(paragraphs: list[tuple[int, str]], toc: list[list]) -> tuple[Chapter, ...] | None:
    top = [(page - 1, title) for level, title, page in toc if level == 1 and page >= 1]
    top = sorted({(p, t) for p, t in top})
    if len(top) < 2:
        return None
    chapters: list[Chapter] = []
    starts = [p for p, _ in top]
    head = [t for p, t in paragraphs if p < starts[0]]
    if head:
        chapters.append(Chapter(title="Inicio", paragraphs=tuple(head)))
    for i, (start, title) in enumerate(top):
        end = starts[i + 1] if i + 1 < len(top) else float("inf")
        body = tuple(t for p, t in paragraphs if start <= p < end)
        if body:
            chapters.append(Chapter(title=normalize_paragraph(title), paragraphs=body))
    return tuple(chapters) or None


def read_pdf(path: Path) -> dict:
    import fitz  # PyMuPDF; import diferido para no penalizar otros formatos

    try:
        with fitz.open(path) as pdf:
            if pdf.needs_pass:
                raise DocumentError("El PDF está protegido con contraseña.")
            paragraphs = _collect_paragraphs(pdf)
            toc = pdf.get_toc()
            meta = pdf.metadata or {}
    except (fitz.FileDataError, RuntimeError) as exc:
        raise DocumentError(f"PDF inválido o dañado: {exc}") from exc

    title = (meta.get("title") or "").strip() or path.stem
    chapters = _chapters_from_toc(paragraphs, toc) or group_into_chapters(
        (t for _, t in paragraphs), default_title=title
    )
    return {"title": title, "author": (meta.get("author") or "").strip(), "chapters": chapters}
