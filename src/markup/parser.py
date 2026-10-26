"""Lenguaje de etiquetas de voz y su parser.

Sintaxis (no distingue mayúsculas ni acentos)::

    [pausa]  [pausa:1.5s]  [pausa:400ms]          pausa explícita (por defecto 0.8 s)
    [lento]texto[/lento]   [rapido]texto[/rapido]
    [susurro]texto[/susurro]   [enfasis]texto[/enfasis]
    [alegre] [triste] [serio] [misterioso] [enojado] [emocionado]  (+ cierre [/tag])
    [voz:nombre]texto[/voz]                       cambia de voz (narrador/personajes)

Reglas:
- Un alcance abierto vale hasta su cierre o, a falta de este, hasta el final del párrafo.
- Una etiqueta desconocida se descarta con una advertencia: nunca se lee en voz alta.
- Corchetes no alfabéticos (por ejemplo ``[12]``) no son etiquetas y se conservan.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from src.markup.style import Style

DEFAULT_PAUSE_S = 0.8
MIN_PAUSE_S, MAX_PAUSE_S = 0.1, 10.0

TAG_RE = re.compile(r"\[\s*(/)?\s*([A-Za-zÁÉÍÓÚáéíóúÑñ_]+)\s*(?::\s*([^\[\]]{1,60}))?\s*\]")


@dataclass(frozen=True)
class _Effect:
    speed: float = 1.0
    gain_db: float = 0.0
    instruct: str = ""


# Cada etiqueta: efecto numérico (Piper) + instrucción natural (motores expresivos).
EFFECTS: dict[str, _Effect] = {
    "lento": _Effect(speed=0.85, instruct="habla despacio y con calma"),
    "rapido": _Effect(speed=1.15, instruct="habla con rapidez y energía"),
    "susurro": _Effect(speed=0.9, gain_db=-9.0, instruct="susurra en voz baja"),
    "enfasis": _Effect(speed=0.95, gain_db=2.0, instruct="habla con énfasis y firmeza"),
    "alegre": _Effect(speed=1.05, gain_db=1.0, instruct="habla con alegría y entusiasmo"),
    "emocionado": _Effect(speed=1.1, gain_db=2.0, instruct="habla muy emocionado"),
    "triste": _Effect(speed=0.88, gain_db=-2.0, instruct="habla con tristeza y voz apagada"),
    "serio": _Effect(speed=0.95, instruct="habla en tono serio y solemne"),
    "misterioso": _Effect(speed=0.9, gain_db=-4.0, instruct="habla con tono misterioso y pausado"),
    "enojado": _Effect(speed=1.05, gain_db=3.0, instruct="habla con enojo contenido"),
    # Estilos narrativos acústicos completos (11 estilos CO-STAR)
    "cuentacuentos": _Effect(speed=0.92, gain_db=0.5, instruct="narra con cadencia cálida de cuentacuentos teatral"),
    "locutor_radio": _Effect(speed=1.08, gain_db=2.0, instruct="locución radial dinámica, enérgica y proyectada"),
    "terror": _Effect(speed=0.87, gain_db=-1.5, instruct="tono sombrío, tenso e inquietante de terror psicológico"),
    "epico": _Effect(speed=0.95, gain_db=2.0, instruct="declamación solemne, heroica y resonante"),
    "ciencia_ficcion": _Effect(speed=0.98, gain_db=0.5, instruct="cadencia analítica, nítida y futurista"),
    "ensayo": _Effect(speed=0.96, gain_db=0.5, instruct="exposición reflexiva, didáctica y articulada"),
    "historia": _Effect(speed=0.94, gain_db=1.0, instruct="crónica documental solemne y envolvente"),
    "poesia": _Effect(speed=0.86, gain_db=-0.5, instruct="recitación lírica musical y contemplativa"),
    "drama": _Effect(speed=0.91, gain_db=1.0, instruct="interpretación emotiva, intensa y profunda"),
    "institucional": _Effect(speed=1.00, gain_db=1.5, instruct="dicción ejecutiva, clara y corporativa"),
}
_ALIASES = {
    "rápido": "rapido", "énfasis": "enfasis", "slow": "lento", "fast": "rapido",
    "whisper": "susurro", "pause": "pausa", "voice": "voz", "happy": "alegre",
    "sad": "triste", "angry": "enojado", "excited": "emocionado",
    "radio": "locutor_radio", "locutor": "locutor_radio", "cuento": "cuentacuentos",
    "épico": "epico", "ciencia_ficción": "ciencia_ficcion", "poesía": "poesia",
    "misterio": "misterioso",
}
_VOCAL_INFLECTIONS: dict[str, tuple[str, float, Style]] = {
    "risa": ("ja, ja", 0.25, Style(speed=1.08, gain_db=1.0)),
    "suspiro": ("...", 0.55, Style(speed=0.85, gain_db=-3.0)),
    "jadeo": ("...", 0.35, Style(speed=1.10, gain_db=-2.0)),
    "pausa_dramatica": ("", 1.40, Style()),
}
_SPECIAL = {"pausa", "voz", "sfx"} | set(_VOCAL_INFLECTIONS.keys())


@dataclass(frozen=True)
class Segment:
    """Fragmento con estilo. ``text`` vacío = silencio de ``pause_s`` segundos o efecto ``sfx``."""

    text: str
    style: Style = field(default_factory=Style)
    pause_s: float = 0.0
    sfx: str = ""


@dataclass(frozen=True)
class ParseResult:
    segments: tuple[Segment, ...]
    warnings: tuple[str, ...]


def _canon(raw: str) -> str | None:
    name = raw.strip().lower()
    name = _ALIASES.get(name, name)
    if name not in EFFECTS and name not in _SPECIAL:
        stripped = "".join(c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn")
        name = _ALIASES.get(stripped, stripped)
    return name if name in EFFECTS or name in _SPECIAL else None


def _parse_seconds(arg: str | None, warnings: list[str]) -> float:
    if not arg:
        return DEFAULT_PAUSE_S
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(ms|s)?\s*", arg.lower())
    if not m:
        warnings.append(f"Duración de pausa inválida '{arg}'; se usa {DEFAULT_PAUSE_S}s")
        return DEFAULT_PAUSE_S
    value = float(m.group(1).replace(",", "."))
    secs = value / 1000 if m.group(2) == "ms" else value
    clamped = max(MIN_PAUSE_S, min(MAX_PAUSE_S, secs))
    if clamped != secs:
        warnings.append(f"Pausa de {secs}s fuera de rango; se ajusta a {clamped}s")
    return clamped


def _fold(stack: list[tuple[str, str | None]]) -> Style:
    speed, gain, voice, instruct = 1.0, 0.0, None, []
    for name, arg in stack:
        if name == "voz":
            voice = arg
            continue
        eff = EFFECTS[name]
        speed *= eff.speed
        gain += eff.gain_db
        if eff.instruct not in instruct:
            instruct.append(eff.instruct)
    return Style(speed=speed, gain_db=gain, voice=voice, instruct=tuple(instruct))


def parse_markup(text: str) -> ParseResult:
    """Convierte un párrafo con etiquetas en segmentos con estilo y advertencias."""
    segments: list[Segment] = []
    warnings: list[str] = []
    stack: list[tuple[str, str | None]] = []
    pos = 0

    def emit(chunk: str) -> None:
        if chunk.strip():
            segments.append(Segment(text=chunk.strip(), style=_fold(stack)))

    for m in TAG_RE.finditer(text):
        emit(text[pos:m.start()])
        pos = m.end()
        closing, raw, arg = bool(m.group(1)), m.group(2), (m.group(3) or "").strip() or None
        name = _canon(raw)
        if name is None:
            warnings.append(f"Etiqueta desconocida [{raw}] descartada")
            continue
        if name == "pausa":
            if closing:
                warnings.append("[/pausa] no existe; ignorada")
            else:
                segments.append(Segment(text="", pause_s=_parse_seconds(arg, warnings)))
            continue
        if name in _VOCAL_INFLECTIONS:
            if not closing:
                v_text, v_pause, v_style = _VOCAL_INFLECTIONS[name]
                base_style = _fold(stack)
                merged_style = Style(
                    speed=base_style.speed * v_style.speed,
                    gain_db=base_style.gain_db + v_style.gain_db,
                    voice=base_style.voice,
                    instruct=base_style.instruct,
                )
                segments.append(Segment(text=v_text if v_text != "..." else "", style=merged_style, pause_s=v_pause))
            continue
        if name == "sfx":
            if closing or not arg:
                warnings.append("[sfx] requiere un nombre ([sfx:trueno]); ignorada")
            else:
                segments.append(Segment(text="", sfx=arg.strip()))
            continue
        if closing:
            idx = next((i for i in range(len(stack) - 1, -1, -1) if stack[i][0] == name), None)
            if idx is None:
                warnings.append(f"Cierre [/{raw}] sin apertura; ignorado")
            else:
                if idx != len(stack) - 1:
                    warnings.append(f"Etiquetas anidadas incorrectamente al cerrar [/{raw}]")
                del stack[idx:]
            continue
        if name == "voz" and not arg:
            warnings.append("[voz] requiere un nombre ([voz:nombre]); ignorada")
            continue
        stack.append((name, arg))
    emit(text[pos:])
    return ParseResult(segments=tuple(segments), warnings=tuple(warnings))
