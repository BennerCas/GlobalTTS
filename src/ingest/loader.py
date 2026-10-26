"""Punto de entrada único para cargar documentos (TXT, PDF, EPUB, Imágenes OCR y URLs Web)."""
from __future__ import annotations

from pathlib import Path

from src.core.language import detect_language
from src.core.models import Document, DocumentError, UnsupportedFormatError
from src.ingest.common import sha256_file
from src.ingest.epub_reader import read_epub
from src.ingest.ocr_engine import read_image_document
from src.ingest.pdf_reader import read_pdf
from src.ingest.txt_reader import read_txt
from src.ingest.url_reader import read_url

_READERS = {
    ".txt": read_txt,
    ".md": read_txt,
    ".pdf": read_pdf,
    ".epub": read_epub,
    ".png": read_image_document,
    ".jpg": read_image_document,
    ".jpeg": read_image_document,
    ".webp": read_image_document,
    ".bmp": read_image_document,
}
SUPPORTED_EXTENSIONS = frozenset(_READERS)


def load_document(path: str | Path) -> Document:
    """Detecta el formato (archivo local o URL http/https) y devuelve un ``Document`` normalizado."""
    raw_str = str(path).strip()
    if raw_str.startswith(("http://", "https://")):
        return read_url(raw_str)

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {file_path}")
    if not file_path.is_file():
        raise DocumentError(f"La ruta no es un archivo regular: {file_path}")

    ext = file_path.suffix.lower()
    reader = _READERS.get(ext)
    if reader is None:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedFormatError(f"Formato '{ext or '(sin extensión)'}' no soportado (válidos: {supported})")

    result = reader(file_path)
    if isinstance(result, Document):
        return result

    # Si el lector devuelve un dict {"title", "author", "chapters"}
    chapters = tuple(result.get("chapters", ()))
    if not chapters or sum(c.char_count for c in chapters) == 0:
        raise DocumentError(f"El documento no contiene texto legible: {file_path.name}")
    sample = " ".join(p for c in chapters for p in c.paragraphs)[:4000]
    return Document(
        title=result.get("title") or file_path.stem,
        author=result.get("author") or "",
        language=detect_language(sample),
        chapters=chapters,
        source_path=str(file_path.resolve()),
        source_sha256=sha256_file(file_path),
    )
