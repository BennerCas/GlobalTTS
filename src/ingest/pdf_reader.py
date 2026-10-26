"""Lector de archivos PDF (PyMuPDF / fitz) con OCR Local Automático y Limpieza Editorial."""
from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

from src.core.editorial_cleaner import (
    clean_editorial_blocks,
    detect_repeating_headers_footers,
)
from src.core.language import detect_language
from src.core.models import Document, DocumentError, ScannedPdfError
from src.ingest.common import group_into_chapters, normalize_paragraph, sha256_file, unwrap_lines
from src.ingest.ocr_engine import ocr_pdf_page

logger = logging.getLogger("globaltts.pdf_reader")

MIN_CHARS_PER_PAGE = 25  # por debajo de esto se activa OCR local; si sigue vacío se considera PDF en blanco


def read_pdf(path: Path, enable_ocr: bool = True, clean_editorial: bool = True) -> Document:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise DocumentError(f"No se pudo abrir el PDF {path.name}: {exc}") from exc

    with doc:
        if doc.is_encrypted:
            raise DocumentError(f"El PDF está cifrado con contraseña: {path.name}")
        if doc.page_count == 0:
            raise DocumentError(f"El PDF no tiene páginas: {path.name}")

        meta = doc.metadata or {}
        title = normalize_paragraph(meta.get("title") or "") or path.stem
        author = normalize_paragraph(meta.get("author") or "")

        # Extraer índice (TOC) nativo del PDF para enriquecer títulos de capítulos
        toc_headings: dict[int, list[str]] = {}
        try:
            for level, toc_title, page_num in doc.get_toc():
                if level <= 2 and toc_title and page_num >= 1:
                    clean_t = normalize_paragraph(toc_title)
                    if clean_t:
                        toc_headings.setdefault(page_num - 1, []).append(clean_t)
        except Exception:
            pass

        pages_blocks: list[list[str]] = []
        total_chars = 0

        for page_idx, page in enumerate(doc):
            page_list: list[str] = []
            # Inyectar encabezados del TOC si existen para esta página
            if page_idx in toc_headings:
                for h_title in toc_headings[page_idx]:
                    if not h_title.lower().startswith(("capítulo", "chapter", "parte", "prólogo", "epílogo")):
                        page_list.append(f"Capítulo: {h_title}")
                    else:
                        page_list.append(h_title)

            page_chars = 0
            for block in page.get_text("blocks"):
                if len(block) >= 7 and block[6] != 0:  # 0 = texto; 1 = imagen
                    continue
                cleaned = unwrap_lines(block[4])
                if cleaned:
                    page_list.append(cleaned)
                    page_chars += len(cleaned)

            # Si la página parece escaneada (sin capa de texto), ejecutar OCR local WinRT
            if page_chars < MIN_CHARS_PER_PAGE and enable_ocr:
                logger.info("Página %d de '%s' sin capa de texto (%d chars). Ejecutando OCR local...", page_idx + 1, path.name, page_chars)
                ocr_text = ocr_pdf_page(page)
                if ocr_text.strip():
                    for raw_b in ocr_text.split("\n\n"):
                        cleaned_ocr = unwrap_lines(raw_b)
                        if cleaned_ocr:
                            page_list.append(cleaned_ocr)
                            page_chars += len(cleaned_ocr)

            total_chars += page_chars
            pages_blocks.append(page_list)

        page_count = doc.page_count

    if total_chars / page_count < MIN_CHARS_PER_PAGE:
        raise ScannedPdfError(
            f"{path.name} no contiene texto legible tras inspección y OCR "
            f"({total_chars} caracteres en {page_count} páginas)."
        )

    # Limpieza heurística de encabezados/pies repetitivos y numeración de páginas
    if clean_editorial:
        repeating = detect_repeating_headers_footers(pages_blocks)
        flat_blocks: list[str] = []
        for p_blocks in pages_blocks:
            flat_blocks.extend(clean_editorial_blocks(p_blocks, repeating_patterns=repeating))
    else:
        flat_blocks = [b for p_blocks in pages_blocks for b in p_blocks]

    if not flat_blocks:
        raise ScannedPdfError(f"{path.name} no contiene bloques de texto tras limpieza.")

    chapters = group_into_chapters(flat_blocks, default_title=title)
    sample = " ".join(p for c in chapters for p in c.paragraphs)[:4000]
    return Document(
        title=title,
        author=author,
        language=detect_language(sample),
        chapters=chapters,
        source_path=str(path.resolve()),
        source_sha256=sha256_file(path),
    )
