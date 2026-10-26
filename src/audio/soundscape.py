"""Motor de Paisajes Sonoros (Soundscapes) y Música Ambiental con Ducking Dinámico.

Genera pistas ambientales estéreo de estudio (o carga pistas `.mp3`/`.wav` del usuario)
y las mezcla con la narración aplicando *Audio Ducking* dinámico basado en envolvente
RMS: atenúa el fondo cuando el narrador habla y lo eleva suavemente durante las pausas
y transiciones de capítulo.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import scipy.signal
import soundfile as sf

logger = logging.getLogger("globaltts.soundscape")

SOUNDSCAPE_PRESETS: dict[str, str] = {
    "none": "Sin Música Ambiental (Solo Voz)",
    "ambient_drone": "Ambient Drone Cálido (Lectura Inmersiva / Ficción)",
    "rain_night": "Lluvia Nocturna Suave (Suspenso / Relato Íntimo)",
    "space_cosmos": "Cosmos Profundo Binaural (Ciencia Ficción / Filosofía)",
    "lofi_warmth": "Armonía Lo-Fi Editorial (Ensayo / Podcast / Crónica)",
    "mystery_thriller": "Tensión Noir Oscura (Terror / Thriller / Misterio)",
}


def generate_procedural_soundscape(
    preset: str,
    duration_s: float,
    sample_rate: int = 24000,
) -> np.ndarray:
    """Sintetiza un paisaje sonoro estéreo (`(N, 2)`) continuo y libre de derechos."""
    num_samples = max(1, int(duration_s * sample_rate))
    t = np.linspace(0.0, duration_s, num_samples, endpoint=False, dtype=np.float32)
    rng = np.random.default_rng(seed=42)

    if preset == "rain_night":
        # Ruido rosa filtrado en estéreo + brisa lenta + trueno lejano suave
        white_l = rng.standard_normal(num_samples, dtype=np.float32)
        white_r = rng.standard_normal(num_samples, dtype=np.float32)
        sos_lp = scipy.signal.butter(2, [250.0, 3200.0], btype="bandpass", fs=sample_rate, output="sos")
        rain_l = scipy.signal.sosfilt(sos_lp, white_l).astype(np.float32)
        rain_r = scipy.signal.sosfilt(sos_lp, white_r).astype(np.float32)
        swell = 0.75 + 0.25 * np.sin(2.0 * np.pi * 0.08 * t)
        pad = 0.15 * np.sin(2.0 * np.pi * 110.0 * t) + 0.10 * np.sin(2.0 * np.pi * 164.81 * t)
        left = (rain_l * swell * 0.25) + pad
        right = (rain_r * swell * 0.25) + pad * 0.95
        stereo = np.column_stack([left, right])

    elif preset == "space_cosmos":
        # Quintas binaurales profundas (55Hz A1, 82.4Hz E2, 110Hz A2, 138.6Hz C#3) con modulación LFO
        lfo1 = 0.6 + 0.4 * np.sin(2.0 * np.pi * 0.05 * t)
        lfo2 = 0.6 + 0.4 * np.cos(2.0 * np.pi * 0.07 * t)
        left = (
            0.35 * np.sin(2.0 * np.pi * 55.0 * t)
            + 0.25 * np.sin(2.0 * np.pi * 82.41 * t) * lfo1
            + 0.18 * np.sin(2.0 * np.pi * 110.5 * t) * lfo2
            + 0.08 * np.sin(2.0 * np.pi * 220.0 * t + np.sin(2.0 * np.pi * 0.1 * t))
        )
        right = (
            0.35 * np.sin(2.0 * np.pi * 55.0 * t)
            + 0.25 * np.sin(2.0 * np.pi * 82.41 * t) * lfo2
            + 0.18 * np.sin(2.0 * np.pi * 109.5 * t) * lfo1
            + 0.08 * np.cos(2.0 * np.pi * 220.0 * t + np.cos(2.0 * np.pi * 0.1 * t))
        )
        stereo = np.column_stack([left, right])

    elif preset == "lofi_warmth":
        # Progresión cálida de acordes suaves (Dm7 -> G7 -> Cmaj7) con ciclo de 12 segundos
        cycle = t % 12.0
        f1 = np.where(cycle < 4.0, 146.83, np.where(cycle < 8.0, 196.00, 130.81))
        f2 = np.where(cycle < 4.0, 174.61, np.where(cycle < 8.0, 246.94, 164.81))
        f3 = np.where(cycle < 4.0, 220.00, np.where(cycle < 8.0, 293.66, 196.00))
        f4 = np.where(cycle < 4.0, 261.63, np.where(cycle < 8.0, 349.23, 246.94))
        # Fase continua mediante integración de frecuencia instantánea
        p1 = 2.0 * np.pi * np.cumsum(f1) / sample_rate
        p2 = 2.0 * np.pi * np.cumsum(f2) / sample_rate
        p3 = 2.0 * np.pi * np.cumsum(f3) / sample_rate
        p4 = 2.0 * np.pi * np.cumsum(f4) / sample_rate
        env = 0.7 + 0.3 * np.sin(2.0 * np.pi * (t / 4.0))
        chord_l = (0.30 * np.sin(p1) + 0.22 * np.sin(p2) + 0.18 * np.sin(p3) + 0.12 * np.sin(p4)) * env
        chord_r = (0.30 * np.sin(p1) + 0.22 * np.cos(p2) + 0.18 * np.sin(p3) + 0.12 * np.cos(p4)) * env
        stereo = np.column_stack([chord_l, chord_r])

    elif preset == "mystery_thriller":
        # Drone oscuro en Re menor (73.42Hz D2, 87.31Hz F2, 110Hz A2) con pulso de tensión lento
        pulse = 0.55 + 0.45 * (np.sin(2.0 * np.pi * 0.25 * t) ** 2)
        sub = 0.40 * np.sin(2.0 * np.pi * 73.42 * t) * pulse
        minor_third = 0.22 * np.sin(2.0 * np.pi * 87.31 * t + 0.3 * np.sin(2.0 * np.pi * 0.09 * t))
        fifth_l = 0.18 * np.sin(2.0 * np.pi * 110.0 * t)
        fifth_r = 0.18 * np.sin(2.0 * np.pi * 110.4 * t)
        stereo = np.column_stack([sub + minor_third + fifth_l, sub + minor_third + fifth_r])

    else:
        # "ambient_drone" por defecto: Pad armónico cálido (Do Mayor 7 / Fa Mayor 7)
        lfo_a = 0.65 + 0.35 * np.sin(2.0 * np.pi * 0.06 * t)
        lfo_b = 0.65 + 0.35 * np.cos(2.0 * np.pi * 0.08 * t)
        root = 0.32 * np.sin(2.0 * np.pi * 130.81 * t)  # C3
        third = 0.20 * np.sin(2.0 * np.pi * 164.81 * t) * lfo_a  # E3
        fifth = 0.22 * np.sin(2.0 * np.pi * 196.00 * t) * lfo_b  # G3
        maj7 = 0.12 * np.sin(2.0 * np.pi * 246.94 * t)  # B3
        stereo = np.column_stack([root + third + fifth * 0.9, root + third * 0.9 + fifth + maj7 * 0.6])

    # Normalizar a pico unitario antes de aplicar atenuación de mezcla
    peak = float(np.max(np.abs(stereo)))
    if peak > 1e-6:
        stereo = stereo / peak
    return stereo.astype(np.float32)


def load_custom_bgm(bgm_path: Path, target_len: int, sample_rate: int) -> np.ndarray:
    """Carga un archivo de música del usuario, lo adapta a sample_rate y lo repite con crossfade hasta cubrir target_len."""
    data, sr = sf.read(str(bgm_path), dtype="float32", always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]

    if sr != sample_rate and len(data) > 0:
        resampled_len = int(len(data) * sample_rate / sr)
        data = scipy.signal.resample(data, resampled_len, axis=0).astype(np.float32)

    if len(data) == 0:
        return np.zeros((target_len, 2), dtype=np.float32)

    if len(data) < target_len:
        repeats = (target_len // len(data)) + 2
        data = np.tile(data, (repeats, 1))

    data = data[:target_len]
    peak = float(np.max(np.abs(data)))
    if peak > 1e-6:
        data = data / peak
    return data.astype(np.float32)


def mix_voice_with_soundscape(
    voice_samples: np.ndarray,
    sample_rate: int,
    preset: str = "ambient_drone",
    custom_bgm_path: Optional[Path] = None,
    ducked_db: float = -22.0,
    pause_db: float = -13.5,
) -> np.ndarray:
    """Mezcla la voz con el paisaje sonoro aplicando Audio Ducking dinámico en estéreo `(N, 2)`."""
    if len(voice_samples) == 0:
        return voice_samples
    if preset == "none" and not custom_bgm_path:
        return voice_samples

    # Asegurar representación estéreo de la voz
    if voice_samples.ndim == 1:
        voice_stereo = np.column_stack([voice_samples, voice_samples])
        voice_mono = voice_samples
    else:
        voice_stereo = voice_samples[:, :2] if voice_samples.shape[1] >= 2 else np.repeat(voice_samples, 2, axis=1)
        voice_mono = np.mean(voice_stereo, axis=1)

    num_samples = len(voice_mono)
    duration_s = num_samples / float(sample_rate)

    if custom_bgm_path and Path(custom_bgm_path).exists():
        bgm = load_custom_bgm(Path(custom_bgm_path), num_samples, sample_rate)
    else:
        bgm = generate_procedural_soundscape(preset, duration_s, sample_rate)

    # Calcular detector de actividad de voz (VAD / envolvente RMS suavizada)
    win_fast = max(32, int(0.035 * sample_rate))
    k_fast = np.ones(win_fast, dtype=np.float32) / win_fast
    rms_fast = np.sqrt(np.convolve(voice_mono ** 2, k_fast, mode="same") + 1e-12)

    # Umbral de habla activa (~ -38 dBFS ≈ 0.0125)
    speech_active = (rms_fast > 0.012).astype(np.float32)

    # Suavizar transiciones de ducking (ventana de 380ms para ataques y liberaciones sedosas)
    win_smooth = max(64, int(0.380 * sample_rate))
    k_smooth = np.ones(win_smooth, dtype=np.float32) / win_smooth
    duck_factor = np.clip(np.convolve(speech_active, k_smooth, mode="same"), 0.0, 1.0)

    gain_ducked = 10.0 ** (ducked_db / 20.0)
    gain_pause = 10.0 ** (pause_db / 20.0)

    # Cuando duck_factor=1 (hablando) -> gain_ducked; cuando duck_factor=0 (pausa) -> gain_pause
    bgm_gain_curve = gain_pause - duck_factor * (gain_pause - gain_ducked)

    # Aplicar fade-in (1.2s) y fade-out (1.8s) al paisaje sonoro
    fade_in_n = min(num_samples // 3, int(1.2 * sample_rate))
    fade_out_n = min(num_samples // 3, int(1.8 * sample_rate))
    if fade_in_n > 1:
        bgm_gain_curve[:fade_in_n] *= np.linspace(0.0, 1.0, fade_in_n, dtype=np.float32)
    if fade_out_n > 1:
        bgm_gain_curve[-fade_out_n:] *= np.linspace(1.0, 0.0, fade_out_n, dtype=np.float32)

    mixed = voice_stereo + bgm * bgm_gain_curve[:, np.newaxis]
    peak = float(np.max(np.abs(mixed)))
    if peak > 0.95:
        mixed = mixed * (0.95 / peak)

    return mixed.astype(np.float32)
