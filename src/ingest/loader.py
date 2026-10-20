"""Punto de entrada de ingesta: ``load_document(path)`` despacha por extensión."""
from __future__ import annotations

from pathlib import Path

from src.core.language import detect_language
from src.core.models import Document, DocumentError, UnsupportedFormatError
from src.ingest.common import sha256_file
from src.ingest.epub_reader import read_epub
from src.ingest.pdf_reader import read_pdf
from src.ingest.txt_reader import read_txt

MAX_FILE_BYTES = 300 * 1024 * 1024
_READERS = {".txt": read_txt, ".md": read_txt, ".pdf": read_pdf, ".epub": read_epub}
SUPPORTED_EXTENSIONS = tuple(sorted(_READERS))


def load_document(path: str | Path) -> Document:
    """Lee un .txt/.md/.pdf/.epub y devuelve un :class:`Document` normalizado.

    Raises:
        UnsupportedFormatError: extensión no soportada.
        DocumentError: archivo inexistente, demasiado grande, vacío o ilegible.
    """
    p = Path(path)
    if not p.is_file():
        raise DocumentError(f"No existe el archivo: {p}")
    reader = _READERS.get(p.suffix.lower())
    if reader is None:
        raise UnsupportedFormatError(
            f"Formato no soportado: '{p.suffix}'. Soportados: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    if p.stat().st_size > MAX_FILE_BYTES:
        raise DocumentError(f"Archivo demasiado grande (máx. {MAX_FILE_BYTES // (1024 * 1024)} MB).")

    parsed = reader(p)
    chapters = tuple(c for c in parsed["chapters"] if c.paragraphs)
    if not chapters:
        raise DocumentError("No se encontró texto legible en el documento.")
    sample = " ".join(par for c in chapters for par in c.paragraphs[:50])
    return Document(
        title=parsed["title"],
        author=parsed["author"],
        language=detect_language(sample),
        chapters=chapters,
        source_path=str(p.resolve()),
        source_sha256=sha256_file(p),
    )
