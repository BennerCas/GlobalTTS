"""Pruebas unitarias para la segmentación de oraciones y elocuciones."""
from src.core.models import Chapter, Document
from src.core.utterances import build_utterances, split_long_sentence, split_sentences


def test_split_sentences_standard_and_abbreviations():
    text = "El Dr. Pérez llegó a las 5 p.m. con el Sr. Gómez. Fue un éxito rotundo."
    sentences = split_sentences(text)
    assert len(sentences) == 2
    assert sentences[0] == "El Dr. Pérez llegó a las 5 p.m. con el Sr. Gómez."
    assert sentences[1] == "Fue un éxito rotundo."


def test_split_long_sentence_with_commas():
    long_text = "Esta es una oración bastante extensa, que contiene varias cláusulas coordinadas, y que debe ser dividida para no saturar al sintetizador."
    pieces = split_long_sentence(long_text, max_chars=60)
    assert len(pieces) > 1
    for p in pieces:
        assert len(p) <= 80  # margen seguro


def test_build_utterances_from_document():
    doc = Document(
        title="Libro de Prueba",
        author="Autor Desconocido",
        language="es",
        chapters=(
            Chapter(
                title="Capítulo I",
                paragraphs=(
                    "Había una vez en un reino muy lejano. Todos vivían en paz.",
                    "[lento]Pero un día llegó la tormenta.[/lento]"
                )
            ),
        ),
        source_path="dummy.txt",
        source_sha256="abc123"
    )

    res = build_utterances(doc, max_chars=100)
    utts = res.utterances
    assert len(utts) >= 3

    # Primera elocución debe ser el título del capítulo
    assert utts[0].is_title is True
    assert utts[0].text == "Capítulo I"

    # Una elocución con estilo lento
    lento_utts = [u for u in utts if u.style.speed < 1.0]
    assert len(lento_utts) >= 1
    assert "tormenta" in lento_utts[0].text
