"""Detección ligera de idioma (español/inglés) por frecuencia de palabras funcionales.

Sin dependencias externas: suficiente para decidir si un libro debe traducirse.
"""
from __future__ import annotations

import re

_ES = frozenset(
    "de la que el en y los se del las un por con una su para es al lo como más pero sus le ya "
    "este sí porque esta entre cuando muy sin sobre también hasta hay donde quien desde todo "
    "nos durante estaba fue era había ser son tiene tenía nada ella él ellos".split()
)
_EN = frozenset(
    "the of and to in is that it was for on are as with his they at be this from have or by "
    "had not but what all were when we there can an your which their said if do will each "
    "about how out them then she many some would into has more her two him could been its "
    "who now my did only where most just".split()
)
_WORD_RE = re.compile(r"[a-záéíóúñü]+")

MIN_WORDS = 20
DOMINANCE = 1.3


def detect_language(text: str, sample_chars: int = 30_000) -> str:
    """Devuelve ``"es"``, ``"en"`` o ``"unknown"`` (muestra insuficiente o ambigua)."""
    words = _WORD_RE.findall(text[:sample_chars].lower())
    if len(words) < MIN_WORDS:
        return "unknown"
    es = sum(1 for w in words if w in _ES)
    en = sum(1 for w in words if w in _EN)
    if es > en * DOMINANCE:
        return "es"
    if en > es * DOMINANCE:
        return "en"
    return "unknown"
