"""Motor de Efectos de Sonido Automáticos (Foley / SFX Dinámico).

Sintetiza y mezcla efectos acústicos cinematográficos reales cuando el texto
incluye etiquetas `[sfx:nombre]` o cuando se activa la inserción semántica
automática de Foley en narraciones dramáticas:
- `trueno`: Estruendo atmosférico grave con reverberación decaída.
- `lluvia`: Ráfaga de lluvia intensa sobre cristal.
- `puerta`: Crujido de madera y golpe seco de cerradura.
- `pasos`: Secuencia rítmica de pasos sobre suelo resonante.
- `campana`: Campana tubular solemne con armónicos inarmónicos.
- `viento`: Ráfaga de viento invernal con barrido de filtro.
- `reloj`: Tic-tac mecánico de péndulo.
- `latido`: Doble pulso cardíaco sub-grave ("lub-dub").
- `fuego`: Crepitar cálido de hoguera.
- `alerta_radio`: Cortinilla / estinger informativo de boletín radial.
- `transicion`: Whoosh cinematográfico suave para cambio de escena.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
import scipy.signal
import soundfile as sf

logger = logging.getLogger("globaltts.sfx_engine")

SFX_CATALOG: dict[str, str] = {
    "trueno": "Trueno Atmosférico",
    "lluvia": "Ráfaga de Lluvia",
    "puerta": "Golpe / Cierre de Puerta",
    "pasos": "Pasos en la Penumbra",
    "campana": "Campana Solemne",
    "viento": "Ráfaga de Viento",
    "reloj": "Tic-Tac de Reloj",
    "latido": "Latido Cardíaco Tensivo",
    "fuego": "Hoguera Crepitante",
    "alerta_radio": "Stinger de Boletín Radial",
    "transicion": "Transición Cinemática (Whoosh)",
}

_SFX_TAG_RE = re.compile(r"\[\s*sfx\s*:\s*([^\[\]]+?)\s*\]", re.IGNORECASE)

_SEMANTIC_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:trueno|relámpago|tormenta\s+estalló)\b", re.IGNORECASE), "trueno"),
    (re.compile(r"\b(?:tocaron\s+la\s+puerta|cerró\s+la\s+puerta|abrió\s+la\s+puerta|portazo)\b", re.IGNORECASE), "puerta"),
    (re.compile(r"\b(?:se\s+oyeron\s+pasos|pasos\s+en\s+el\s+pasillo|caminaba\s+en\s+silencio)\b", re.IGNORECASE), "pasos"),
    (re.compile(r"\b(?:sonó\s+la\s+campana|campanada|repicaron\s+las\s+campanas)\b", re.IGNORECASE), "campana"),
    (re.compile(r"\b(?:corazón\s+latía|latidos\s+de\s+su\s+corazón|palpitaba\s+con\s+fuerza)\b", re.IGNORECASE), "latido"),
    (re.compile(r"\b(?:tic\s*tac|reloj\s+marcaba|agujas\s+del\s+reloj)\b", re.IGNORECASE), "reloj"),
    (re.compile(r"\b(?:viento\s+aullaba|ráfaga\s+de\s+viento|viento\s+helado)\b", re.IGNORECASE), "viento"),
]


def synthesize_sfx(name: str, sample_rate: int = 24000) -> np.ndarray:
    """Genera un vector mono float32 con el efecto acústico solicitado."""
    clean = name.strip().lower()

    # Si es una ruta a un archivo de audio existente, cargarlo
    cand_path = Path(name.strip())
    if cand_path.suffix.lower() in {".wav", ".mp3", ".ogg", ".flac"} and cand_path.exists():
        try:
            data, sr = sf.read(str(cand_path), dtype="float32")
            if data.ndim == 2:
                data = np.mean(data, axis=1)
            if sr != sample_rate and len(data) > 0:
                data = scipy.signal.resample(data, int(len(data) * sample_rate / sr)).astype(np.float32)
            return data * 0.55
        except Exception as exc:
            logger.warning("No se pudo cargar SFX personalizado %s: %s", cand_path, exc)

    rng = np.random.default_rng(seed=abs(hash(clean)) % 10000)

    if clean in ("trueno", "thunder"):
        dur = 2.2
        n = int(dur * sample_rate)
        t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
        noise = rng.standard_normal(n, dtype=np.float32)
        sos = scipy.signal.butter(3, [35.0, 260.0], btype="bandpass", fs=sample_rate, output="sos")
        rumble = scipy.signal.sosfilt(sos, noise).astype(np.float32)
        env = np.exp(-2.2 * t) * (1.0 - np.exp(-25.0 * t)) * (0.7 + 0.3 * np.sin(2 * np.pi * 3.5 * t))
        out = rumble * env

    elif clean in ("puerta", "door"):
        dur = 0.85
        n = int(dur * sample_rate)
        t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
        # Chirrido breve + impacto grave seco
        creak_t = t[: int(0.45 * sample_rate)]
        creak = 0.25 * np.sin(2 * np.pi * (320 + 90 * np.sin(2 * np.pi * 6 * creak_t)) * creak_t) * np.hanning(len(creak_t))
        slam_t = t[: int(0.35 * sample_rate)]
        slam = (
            0.8 * np.sin(2 * np.pi * 68.0 * slam_t) * np.exp(-18.0 * slam_t)
            + 0.4 * rng.standard_normal(len(slam_t), dtype=np.float32) * np.exp(-35.0 * slam_t)
        )
        out = np.zeros(n, dtype=np.float32)
        out[: len(creak)] += creak
        offset = int(0.42 * sample_rate)
        out[offset : offset + len(slam)] += slam[: n - offset]

    elif clean in ("pasos", "footsteps"):
        dur = 1.6
        n = int(dur * sample_rate)
        out = np.zeros(n, dtype=np.float32)
        step_len = int(0.18 * sample_rate)
        st_t = np.linspace(0, 0.18, step_len, endpoint=False, dtype=np.float32)
        for i, pos_s in enumerate((0.05, 0.50, 0.95, 1.38)):
            idx = int(pos_s * sample_rate)
            if idx + step_len <= n:
                freq = 95.0 if i % 2 == 0 else 108.0
                thud = (
                    0.6 * np.sin(2 * np.pi * freq * st_t) * np.exp(-28.0 * st_t)
                    + 0.25 * rng.standard_normal(step_len, dtype=np.float32) * np.exp(-45.0 * st_t)
                )
                out[idx : idx + step_len] += thud * (0.65 + 0.1 * i)

    elif clean in ("campana", "bell"):
        dur = 1.8
        n = int(dur * sample_rate)
        t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
        # Parciales de campana (f0 = 440Hz, 2.0, 2.76, 3.4)
        out = (
            0.50 * np.sin(2 * np.pi * 440.0 * t) * np.exp(-2.0 * t)
            + 0.30 * np.sin(2 * np.pi * 880.0 * t) * np.exp(-3.2 * t)
            + 0.20 * np.sin(2 * np.pi * 1214.4 * t) * np.exp(-4.5 * t)
            + 0.12 * np.sin(2 * np.pi * 1496.0 * t) * np.exp(-6.0 * t)
        )

    elif clean in ("latido", "heartbeat"):
        dur = 1.2
        n = int(dur * sample_rate)
        out = np.zeros(n, dtype=np.float32)
        beat_len = int(0.22 * sample_rate)
        bt = np.linspace(0, 0.22, beat_len, endpoint=False, dtype=np.float32)
        lub = np.sin(2 * np.pi * 52.0 * bt) * np.exp(-16.0 * bt) * (1.0 - np.exp(-80.0 * bt))
        dub = 0.75 * np.sin(2 * np.pi * 62.0 * bt) * np.exp(-20.0 * bt) * (1.0 - np.exp(-80.0 * bt))
        out[int(0.05 * sample_rate) : int(0.05 * sample_rate) + beat_len] += lub
        out[int(0.32 * sample_rate) : int(0.32 * sample_rate) + beat_len] += dub

    elif clean in ("reloj", "clock"):
        dur = 1.1
        n = int(dur * sample_rate)
        out = np.zeros(n, dtype=np.float32)
        tick_len = int(0.04 * sample_rate)
        tt = np.linspace(0, 0.04, tick_len, endpoint=False, dtype=np.float32)
        tick = np.sin(2 * np.pi * 1800.0 * tt) * np.exp(-90.0 * tt)
        tock = np.sin(2 * np.pi * 1350.0 * tt) * np.exp(-90.0 * tt)
        out[int(0.05 * sample_rate) : int(0.05 * sample_rate) + tick_len] += tick
        out[int(0.55 * sample_rate) : int(0.55 * sample_rate) + tick_len] += tock

    elif clean in ("alerta_radio", "radio"):
        dur = 0.9
        n = int(dur * sample_rate)
        t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
        # Arpegio informativo de 3 tonos rápidos (C5 -> E5 -> G5)
        freqs = np.where(t < 0.18, 523.25, np.where(t < 0.36, 659.25, 783.99))
        phase = 2.0 * np.pi * np.cumsum(freqs) / sample_rate
        env = np.where(t < 0.36, 0.8, np.exp(-4.5 * (t - 0.36)))
        out = (0.6 * np.sin(phase) + 0.25 * np.sin(2.0 * phase)) * env

    elif clean in ("viento", "wind", "lluvia", "rain", "fuego", "fire"):
        dur = 1.4
        n = int(dur * sample_rate)
        t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
        noise = rng.standard_normal(n, dtype=np.float32)
        band = [300.0, 1800.0] if "viento" in clean or "wind" in clean else [600.0, 4200.0]
        sos = scipy.signal.butter(2, band, btype="bandpass", fs=sample_rate, output="sos")
        filtered = scipy.signal.sosfilt(sos, noise).astype(np.float32)
        out = filtered * np.hanning(n)

    else:
        # "transicion" / whoosh cinematográfico por defecto
        dur = 0.75
        n = int(dur * sample_rate)
        t = np.linspace(0, dur, n, endpoint=False, dtype=np.float32)
        sweep = np.sin(2 * np.pi * (120.0 + 480.0 * np.sin(np.pi * t / dur)) * t)
        noise = rng.standard_normal(n, dtype=np.float32) * 0.25
        sos = scipy.signal.butter(2, [200.0, 2400.0], btype="bandpass", fs=sample_rate, output="sos")
        out = (0.4 * sweep + scipy.signal.sosfilt(sos, noise)) * np.hanning(n)

    peak = float(np.max(np.abs(out)))
    if peak > 1e-6:
        out = (out / peak) * 0.42  # Nivel equilibrado (-7.5 dBFS) para no tapar la voz
    return out.astype(np.float32)


def extract_and_strip_sfx_tags(text: str) -> tuple[str, list[str]]:
    """Extrae las etiquetas `[sfx:nombre]` de una oración y devuelve `(texto_limpio, lista_sfx)`."""
    if not text or "sfx" not in text.lower():
        return text, []
    found = [m.group(1).strip() for m in _SFX_TAG_RE.finditer(text)]
    cleaned = _SFX_TAG_RE.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, found


def inject_semantic_sfx_tags(text: str) -> str:
    """Inyecta sutilmente etiquetas `[sfx:...]` cuando detecta acciones acústicas claras en el texto."""
    if not text.strip():
        return text

    sentences = re.split(r"(?<=[.!?…])\s+", text)
    out: list[str] = []
    used_recently: set[str] = set()

    for sent in sentences:
        if "[sfx:" in sent.lower():
            out.append(sent)
            continue
        matched_sfx = None
        for pattern, sfx_name in _SEMANTIC_RULES:
            if sfx_name not in used_recently and pattern.search(sent):
                matched_sfx = sfx_name
                used_recently.add(sfx_name)
                break
        if matched_sfx:
            out.append(f"[sfx:{matched_sfx}] {sent}")
        else:
            out.append(sent)

    return " ".join(out)
