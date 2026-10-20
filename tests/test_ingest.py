"""Pruebas unitarias para los lectores de documentos (TXT, PDF, EPUB)."""
import zipfile
from pathlib import Path

import fitz
import pytest

from src.core.models import DocumentError, UnsupportedFormatError
from src.ingest.loader import load_document
from src.ingest.txt_reader import read_txt


def test_txt_reader(tmp_path: Path):
    txt_file = tmp_path / "cuento.txt"
    txt_file.write_text(
        "Capítulo 1: El Comienzo\n\nÉrase una vez en un bosque verde y frondoso.\n\nCapítulo 2: El Final\n\nY vivieron felices.",
        encoding="utf-8"
    )

    doc = load_document(txt_file)
    assert doc.title == "cuento"
    assert len(doc.chapters) == 2
    assert doc.chapters[0].title.lower().startswith("capítulo 1")
    assert doc.chapters[1].title.lower().startswith("capítulo 2")


def test_pdf_reader(tmp_path: Path):
    pdf_file = tmp_path / "documento.pdf"
    doc_fitz = fitz.open()
    page = doc_fitz.new_page()
    page.insert_text((50, 72), "Capítulo Primero", fontsize=16)
    page.insert_text((50, 120), "Este es un párrafo de texto en un documento PDF con capa de texto válida.", fontsize=12)
    doc_fitz.save(str(pdf_file))
    doc_fitz.close()

    doc = load_document(pdf_file)
    assert doc.title == "documento"
    assert len(doc.chapters) >= 1
    assert any("párrafo de texto" in p for c in doc.chapters for p in c.paragraphs)


def test_unsupported_format(tmp_path: Path):
    unknown_file = tmp_path / "archivo.xyz"
    unknown_file.write_text("datos", encoding="utf-8")

    with pytest.raises(UnsupportedFormatError):
        load_document(unknown_file)


def test_empty_txt_raises_error(tmp_path: Path):
    empty_file = tmp_path / "vacio.txt"
    empty_file.write_text("   \n\n  ", encoding="utf-8")

    with pytest.raises(DocumentError):
        load_document(empty_file)
