"""Modulación Emocional Dinámica Línea por Línea (Prosodic Emotion Analyzer).

Analiza la valencia emocional, tensión dramática y estructura sintáctica de cada
oración (interrogaciones, exclamaciones, suspenso, diálogos, susurros, urgencia,
melancolía) y ajusta dinámicamente la curva de velocidad (`speed`), ganancia (`gain_db`),
y silencios posteriores (`pause_after`) de cada `Utterance`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.core.utterances import Utterance
from src.markup.style import Style

_SUSPENSE_WORDS = frozenset({
    "sombra", "sombras", "oscuridad", "oscuro", "silencio", "misterio", "oculto",
    "secreto", "escalofrío", "miedo", "terror", "sangre", "noche", "susurro",
    "susurró", "penumbra", "abismo", "extraño", "fantasma", "muerte", "peligro",
    "acechaba", "temblor", "frío", "niebla",
})

_EXCITED_WORDS = frozenset({
    "increíble", "maravilloso", "extraordinario", "victoria", "triunfo", "éxito",
    "brillante", "explosión", "corrió", "gritó", "exclamó", "rápido", "urgente",
    "fuego", "relámpago", "impacto", "energía", "asombroso", "impresionante",
    "despertó", "libertad", "poder",
})

_SAD_WORDS = frozenset({
    "lágrimas", "llanto", "lloró", "triste", "tristeza", "soledad", "dolor",
    "pérdida", "adiós", "olvido", "melancolía", "vacío", "despedida", "suspiró",
    "cansado", "derrota", "lamento", "cenizas", "ausencia", "jamás",
})

_WHISPER_WORDS = frozenset({
    "susurró", "murmuró", "en voz baja", "apenas audible", "casi en silencio",
    "secreto", "calla", "shh",
})

_WORD_RE = re.compile(r"[a-záéíóúñü]+", re.IGNORECASE)


@dataclass(frozen=True)
class EmotionAnalysis:
    emotion: str  # "neutral" | "suspense" | "excited" | "sad" | "whisper" | "question" | "dialogue"
    speed_multiplier: float = 1.0
    gain_db_delta: float = 0.0
    pause_multiplier: float = 1.0


def analyze_sentence_emotion(text: str) -> EmotionAnalysis:
    """Evalúa una oración y devuelve sus multiplicadores acústicos de prosodia."""
    stripped = text.strip()
    if not stripped:
        return EmotionAnalysis("neutral", 1.0, 0.0, 1.0)

    lower = stripped.lower()
    words = set(_WORD_RE.findall(lower))

    # 1. Detectar susurro explícito en el texto
    if any(w in lower for w in _WHISPER_WORDS):
        return EmotionAnalysis("whisper", speed_multiplier=0.91, gain_db_delta=-4.5, pause_multiplier=1.35)

    # 2. Puntuación expresiva fuerte: exclamación
    has_exclamation = "!" in stripped or "¡" in stripped
    has_question = "?" in stripped or "¿" in stripped
    has_ellipsis = "..." in stripped or "…" in stripped
    is_dialogue = stripped.startswith(("—", "- ", "«", '"', "“"))

    suspense_hits = len(words & _SUSPENSE_WORDS)
    excited_hits = len(words & _EXCITED_WORDS)
    sad_hits = len(words & _SAD_WORDS)

    if suspense_hits >= 1 and (has_ellipsis or suspense_hits >= 2):
        return EmotionAnalysis("suspense", speed_multiplier=0.90, gain_db_delta=-2.0, pause_multiplier=1.45)

    if has_exclamation or excited_hits >= 2:
        return EmotionAnalysis("excited", speed_multiplier=1.08, gain_db_delta=1.8, pause_multiplier=0.90)

    if sad_hits >= 1:
        return EmotionAnalysis("sad", speed_multiplier=0.91, gain_db_delta=-1.5, pause_multiplier=1.30)

    if suspense_hits >= 1:
        return EmotionAnalysis("suspense", speed_multiplier=0.93, gain_db_delta=-1.0, pause_multiplier=1.25)

    if has_ellipsis:
        return EmotionAnalysis("suspense", speed_multiplier=0.92, gain_db_delta=-1.0, pause_multiplier=1.40)

    if has_question:
        return EmotionAnalysis("question", speed_multiplier=0.97, gain_db_delta=0.6, pause_multiplier=1.20)

    if is_dialogue:
        return EmotionAnalysis("dialogue", speed_multiplier=1.03, gain_db_delta=0.8, pause_multiplier=1.05)

    # Variación orgánica por longitud de frase (las frases muy cortas son más contundentes)
    word_count = len(stripped.split())
    if 1 <= word_count <= 5:
        return EmotionAnalysis("short_impact", speed_multiplier=0.95, gain_db_delta=0.5, pause_multiplier=1.25)

    return EmotionAnalysis("neutral", 1.0, 0.0, 1.0)


def apply_emotional_modulation(utterances: tuple[Utterance, ...], intensity: float = 1.0) -> tuple[Utterance, ...]:
    """Aplica modulación emocional línea por línea a una secuencia de Utterances.

    `intensity` (0.0 a 2.0) escala el efecto prosódico sin distorsionar el timbre.
    """
    if intensity <= 0.0:
        return utterances

    modulated: list[Utterance] = []
    for u in utterances:
        if not u.text.strip() or u.is_title:
            modulated.append(u)
            continue

        analysis = analyze_sentence_emotion(u.text)
        if analysis.emotion == "neutral":
            modulated.append(u)
            continue

        # Interpolar según la intensidad deseada
        speed_delta = (analysis.speed_multiplier - 1.0) * intensity
        new_speed = max(0.55, min(1.85, u.style.speed * (1.0 + speed_delta)))

        new_gain = max(-12.0, min(6.0, u.style.gain_db + (analysis.gain_db_delta * intensity)))

        pause_delta = (analysis.pause_multiplier - 1.0) * intensity
        new_pause = max(0.1, min(5.0, u.pause_after * (1.0 + pause_delta)))

        new_style = Style(
            speed=new_speed,
            gain_db=new_gain,
            voice=u.style.voice,
            instruct=u.style.instruct,
        )
        modulated.append(
            Utterance(
                text=u.text,
                style=new_style,
                pause_after=new_pause,
                chapter_index=u.chapter_index,
                paragraph_index=u.paragraph_index,
                is_title=u.is_title,
            )
        )

    return tuple(modulated)
