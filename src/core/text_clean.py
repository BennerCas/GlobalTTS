"""Limpieza de texto para TTS y utilidades de nombres de archivo (fuente única, DRY).

Antes duplicado en ``global_tts.py`` y ``tts_engine.py``.
"""
from __future__ import annotations

import re

EMOJI_MAP = {
    "🎉": "celebración", "⚠️": "atención", "✅": "correcto", "❌": "error",
    "🔥": "fuego", "💡": "idea", "📌": "nota", "⭐": "estrella",
    "👍": "bien", "👎": "mal", "🚀": "avance", "💪": "fuerza", "🎯": "objetivo",
    "❤️": "amor", "👀": "ojo", "💯": "cien por ciento", "💰": "dinero",
}


def clean_text_for_tts(text: str) -> str:
    """Normaliza emojis, URLs, monedas y porcentajes a texto pronunciable."""
    if not text:
        return ""
    for emoji, word in EMOJI_MAP.items():
        text = text.replace(emoji, f" {word} ")
    text = re.sub(r"https?://\S+", "enlace web", text)
    text = re.sub(r"\$(\d+(?:\.\d+)?)", r"\1 dólares", text)
    text = re.sub(r"€(\d+(?:\.\d+)?)", r"\1 euros", text)
    text = re.sub(r"(\d+)\s*%", r"\1 por ciento", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_filename_slug(text: str, max_words: int = 5, max_len: int = 40) -> str:
    """Slug corto en minúsculas a partir de las primeras palabras del texto."""
    clean = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    slug = "_".join(clean.split()[:max_words]).lower()
    return slug[:max_len] if slug else "audio"
