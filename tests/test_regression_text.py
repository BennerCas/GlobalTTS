"""Pruebas de regresión del flujo actual de lectura (limpieza de texto y nombres de archivo).

Fijan el comportamiento existente antes de refactorizar para la capacidad Audiolibros.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tts_engine = pytest.importorskip("tts_engine", reason="requiere dependencias de Windows (pywin32, edge-tts)")


def test_clean_empty_returns_empty():
    assert tts_engine.clean_text_for_tts("") == ""


def test_clean_replaces_emoji_with_word():
    assert "idea" in tts_engine.clean_text_for_tts("Una 💡 genial")


def test_clean_replaces_url():
    assert tts_engine.clean_text_for_tts("Visita https://ejemplo.com/x hoy") == "Visita enlace web hoy"


def test_clean_currency_and_percent():
    out = tts_engine.clean_text_for_tts("Pagó $50 y €20 con 15 % de descuento")
    assert "50 dólares" in out and "20 euros" in out and "15 por ciento" in out


def test_clean_collapses_whitespace():
    assert tts_engine.clean_text_for_tts("a \n\n  b\t c") == "a b c"


def test_slug_max_five_words_and_length():
    slug = tts_engine.make_filename_slug("Uno dos tres cuatro cinco seis siete")
    assert slug == "uno_dos_tres_cuatro_cinco"
    assert len(slug) <= 40


def test_slug_fallback_when_empty():
    assert tts_engine.make_filename_slug("!!! ???") == "audio"
