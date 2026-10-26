"""Pruebas unitarias para el analizador de etiquetas de voz (Markup Parser)."""
from src.markup.parser import parse_markup
from src.markup.style import Style


def test_parse_plain_text_no_tags():
    res = parse_markup("Este es un texto plano sin ninguna etiqueta.")
    assert len(res.segments) == 1
    assert res.segments[0].text == "Este es un texto plano sin ninguna etiqueta."
    assert res.segments[0].style.is_default
    assert len(res.warnings) == 0


def test_parse_pause_tag_default_and_custom():
    res = parse_markup("Hola mundo. [pausa] ¿Cómo estás? [pausa:1.2s] Fin.")
    assert len(res.segments) == 5
    # Segmentos: "Hola mundo.", pausa(0.8), "¿Cómo estás?", pausa(1.2), "Fin."
    assert res.segments[0].text == "Hola mundo."
    assert res.segments[1].text == ""
    assert res.segments[1].pause_s == 0.8
    assert res.segments[2].text == "¿Cómo estás?"
    assert res.segments[3].pause_s == 1.2
    assert res.segments[4].text == "Fin."


def test_parse_speed_and_whisper_tags():
    res = parse_markup("Inicio. [lento]Voz muy lenta.[/lento] [susurro]Un secreto.[/susurro]")
    assert len(res.segments) == 3
    assert res.segments[0].style.is_default

    # Lento
    assert res.segments[1].text == "Voz muy lenta."
    assert res.segments[1].style.speed < 1.0

    # Susurro
    assert res.segments[2].text == "Un secreto."
    assert res.segments[2].style.gain_db < 0.0


def test_parse_unknown_tag_is_safely_ignored_and_not_read():
    res = parse_markup("Texto antes [etiqueta_inventada]contenido[/etiqueta_inventada] texto después.")
    # La etiqueta debe ser descartada sin colapsar ni leer la etiqueta en voz alta
    assert any("desconocida" in w.lower() for w in res.warnings)
    full_text = " ".join(s.text for s in res.segments)
    assert "[etiqueta_inventada]" not in full_text
    assert "contenido" in full_text


def test_parse_unclosed_tag_applies_until_end():
    res = parse_markup("Texto normal. [rapido]Esto se acelera y no cierra nunca.")
    assert len(res.segments) == 2
    assert res.segments[1].style.speed > 1.0


def test_parse_estilo_tag_and_vocal_inflections():
    res = parse_markup("[estilo:terror_psicologico]No mires detrás de ti.[/estilo] [risa] [pausa_dramatica] Fin.")
    assert len(res.warnings) == 0
    assert res.segments[0].text == "No mires detrás de ti."
    assert res.segments[0].style.speed < 1.0
    assert res.segments[0].style.gain_db < 0.0
    assert any(s.pause_s >= 1.2 for s in res.segments)
