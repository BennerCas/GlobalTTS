"""Segmentación en oraciones y construcción de elocuciones sintetizables.

Una *elocución* (``Utterance``) es la unidad de síntesis: una oración con su estilo.
Sintetizar oración por oración da duraciones exactas para sincronizar subtítulos/karaoke
y permite reanudar trabajos largos sin repetir lo ya generado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.core.models import Document
from src.markup.parser import parse_markup
from src.markup.style import Style

_ABBREVIATIONS = frozenset(
    "sr sra srta dr dra prof lic ing etc vs mr mrs ms jr st núm pág art vol cap ee uu".split()
)
_CLOSERS = "\"'”’»)]"
_BOUNDARY = re.compile(
    rf"([.!?…]+[{re.escape(_CLOSERS)}]*)\s+(?=[\"'“‘«(\[¿¡]*[A-ZÁÉÍÓÚÑÜ0-9])"
)
_LAST_WORD = re.compile(rf"(\w+)\.[{re.escape(_CLOSERS)}]*$")
_SOFT_BREAK = re.compile(r"(?<=[,;:])\s+")


@dataclass(frozen=True)
class PausePolicy:
    """Silencio (s) que se añade tras cada tipo de unidad."""

    sentence: float = 0.25
    paragraph: float = 0.6
    chapter_title: float = 1.0
    chapter_end: float = 1.5


@dataclass(frozen=True)
class Utterance:
    """Unidad de síntesis. ``text`` vacío = solo silencio de ``pause_after`` s."""

    text: str
    style: Style
    pause_after: float
    chapter_index: int
    paragraph_index: int  # -1 para el título del capítulo
    is_title: bool = False


@dataclass(frozen=True)
class BuildResult:
    utterances: tuple[Utterance, ...]
    warnings: tuple[str, ...]


def _is_abbreviation(head: str) -> bool:
    m = _LAST_WORD.search(head)
    if not m:
        return False
    word = m.group(1)
    return word.lower() in _ABBREVIATIONS or (len(word) == 1 and word.isalpha() and word.isupper())


def split_sentences(text: str) -> list[str]:
    """Divide en oraciones respetando abreviaturas, iniciales y puntos suspensivos."""
    out: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        end = m.end(1)
        if m.group(1).startswith(".") and m.group(1) == "." and _is_abbreviation(text[start:end]):
            continue
        out.append(text[start:end].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def _pack(pieces: list[str], max_chars: int) -> list[str]:
    packed: list[str] = []
    for piece in pieces:
        if packed and len(packed[-1]) + 1 + len(piece) <= max_chars:
            packed[-1] = f"{packed[-1]} {piece}"
        else:
            packed.append(piece)
    return packed


def split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """Parte una oración larga en comas/punto y coma y, en último caso, por palabras."""
    if len(sentence) <= max_chars:
        return [sentence]
    pieces: list[str] = []
    for part in _pack(_SOFT_BREAK.split(sentence), max_chars):
        pieces.extend([part] if len(part) <= max_chars else _pack(part.split(" "), max_chars))
    return pieces


def build_utterances(
    document: Document,
    max_chars: int = 400,
    policy: PausePolicy | None = None,
    use_markup: bool = True,
) -> BuildResult:
    """Convierte un documento en elocuciones con estilo, pausas y límites de longitud."""
    if max_chars < 20:
        raise ValueError("max_chars debe ser >= 20")
    policy = policy or PausePolicy()
    utterances: list[Utterance] = []
    warnings: list[str] = []

    def add_pause(extra: float, ch: int, par: int) -> None:
        """Suma/ajusta un silencio al último elemento del mismo párrafo o crea uno."""
        if utterances and utterances[-1].chapter_index == ch and utterances[-1].paragraph_index == par:
            last = utterances[-1]
            utterances[-1] = Utterance(
                last.text, last.style, max(last.pause_after, extra), ch, par, last.is_title
            )
        else:
            utterances.append(Utterance("", Style(), extra, ch, par))

    for ch_idx, chapter in enumerate(document.chapters):
        if chapter.title:
            utterances.append(Utterance(chapter.title, Style(), policy.chapter_title, ch_idx, -1, True))
        for par_idx, paragraph in enumerate(chapter.paragraphs):
            if use_markup:
                result = parse_markup(paragraph)
                segments, warnings = result.segments, warnings + [
                    f"cap {ch_idx + 1} párr {par_idx + 1}: {w}" for w in result.warnings
                ]
            else:
                from src.markup.parser import Segment

                segments = (Segment(text=paragraph),)
            for seg in segments:
                if not seg.text:
                    add_pause(seg.pause_s, ch_idx, par_idx)
                    continue
                for sentence in split_sentences(seg.text):
                    for piece in split_long_sentence(sentence, max_chars):
                        utterances.append(
                            Utterance(piece, seg.style, policy.sentence, ch_idx, par_idx)
                        )
            add_pause(policy.paragraph, ch_idx, par_idx)
        add_pause(policy.chapter_end, ch_idx, len(chapter.paragraphs) - 1)

    return BuildResult(utterances=tuple(utterances), warnings=tuple(warnings))
