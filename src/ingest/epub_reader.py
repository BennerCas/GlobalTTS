"""Lector de EPUB (EbookLib + BeautifulSoup/lxml).

Respeta el orden del *spine*, omite navegación y páginas lineales=no, y protege contra
zip-bombs. Se usa el parser HTML de lxml (no resuelve entidades externas).
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

from src.core.models import Chapter, DocumentError, UnsafeArchiveError
from src.ingest.common import normalize_paragraph

MAX_UNCOMPRESSED_BYTES = 1_000_000_000
MAX_ENTRIES = 20_000
MAX_RATIO = 200
MIN_CHAPTER_CHARS = 200  # páginas más cortas (copyright, portadilla) se descartan
_BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote")
_TITLE_TAGS = ("h1", "h2", "h3")


def _guard_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise DocumentError(f"EPUB inválido (no es un ZIP): {exc}") from exc
    if len(infos) > MAX_ENTRIES:
        raise UnsafeArchiveError(f"EPUB con demasiadas entradas ({len(infos)}).")
    if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
        raise UnsafeArchiveError("El EPUB descomprimido excede el límite de tamaño.")
    for i in infos:
        if i.compress_size and i.file_size > 1_000_000 and i.file_size / i.compress_size > MAX_RATIO:
            raise UnsafeArchiveError(f"Ratio de compresión sospechoso en {i.filename}.")


def _parse_chapter(content: bytes) -> tuple[str, list[str]]:
    soup = BeautifulSoup(content, "lxml")
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    title_el = soup.find(_TITLE_TAGS)
    title = normalize_paragraph(title_el.get_text(" ")) if title_el else ""
    if not title and soup.title:
        title = normalize_paragraph(soup.title.get_text(" "))
    paragraphs = []
    for el in soup.find_all(_BLOCK_TAGS):
        if el.find(_BLOCK_TAGS):  # contenedor: se leen sus hijos, no se duplica
            continue
        text = normalize_paragraph(el.get_text(" "))
        if text:
            paragraphs.append(text)
    if title and paragraphs and paragraphs[0] == title:
        paragraphs = paragraphs[1:]  # el título se narra aparte
    return title, paragraphs


def _metadata(book, key: str) -> str:
    values = book.get_metadata("DC", key)
    return normalize_paragraph(values[0][0]) if values else ""


def read_epub(path: Path) -> dict:
    import ebooklib
    from ebooklib import epub

    _guard_archive(path)
    try:
        book = epub.read_epub(str(path), options={"ignore_ncx": True})
    except Exception as exc:  # EbookLib lanza tipos variados ante EPUB corruptos
        raise DocumentError(f"No se pudo leer el EPUB: {exc}") from exc

    chapters: list[Chapter] = []
    for item_id, linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT or linear == "no":
            continue
        if "nav" in (getattr(item, "properties", None) or []):
            continue
        title, paragraphs = _parse_chapter(item.get_content())
        if sum(len(p) for p in paragraphs) < MIN_CHAPTER_CHARS:
            continue
        chapters.append(Chapter(title=title or f"Sección {len(chapters) + 1}", paragraphs=tuple(paragraphs)))

    return {
        "title": _metadata(book, "title") or path.stem,
        "author": _metadata(book, "creator"),
        "chapters": tuple(chapters),
    }
