"""Cadena de Masterización de Estudio DSP (Broadcast & Audiobook Mastering Chain).

Procesamiento acústico real mediante SciPy y NumPy para elevar la voz sintetizada
a estándar de estudio editorial (Audible / ACX / Broadcast):
1. Filtro Pasa-Altos (HPF) Butterworth de 2º orden a 80 Hz (elimina retumbos sub-graves).
2. De-Esser Dinámico de banda dividida (5.5 kHz – 9.5 kHz) para suavizar sibilancias ('s', 'z').
3. Ecualizador Paramétrico Broadcast (cuerpo cálido en 180 Hz + presencia cristalina en 3.8 kHz).
4. Compresor Dinámico de Rodilla Suave (Soft-Knee RMS) con ganancia de compensación automática.
5. Limitador Brickwall True-Peak a -1.0 dBTP (0.891 lineal) que garantiza cero clipping.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import scipy.signal

logger = logging.getLogger("globaltts.dsp_mastering")


@dataclass(frozen=True)
class MasteringConfig:
    enabled: bool = True
    hpf_cutoff_hz: float = 80.0
    deesser_enabled: bool = True
    deesser_threshold_db: float = -20.0
    deesser_reduction_db: float = 4.5
    warmth_gain_db: float = 1.5
    presence_gain_db: float = 1.8
    compressor_enabled: bool = True
    compressor_threshold_db: float = -18.0
    compressor_ratio: float = 2.5
    ceiling_dbtp: float = -1.0


def _design_peaking_biquad(freq_hz: float, gain_db: float, q: float, sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    """Diseña un filtro biquad peaking EQ (Audio EQ Cookbook de Robert Bristow-Johnson)."""
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * freq_hz / sample_rate
    alpha = np.sin(w0) / (2.0 * q)
    cos_w0 = np.cos(w0)

    b0 = 1.0 + alpha * A
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / A

    b = np.array([b0 / a0, b1 / a0, b2 / a0], dtype=np.float64)
    a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
    return b, a


def apply_highpass_filter(samples: np.ndarray, sample_rate: int, cutoff_hz: float = 80.0) -> np.ndarray:
    """Aplica filtro pasa-altos Butterworth de fase cero para limpiar frecuencias sub-graves."""
    if len(samples) < 64 or cutoff_hz <= 10.0 or cutoff_hz >= sample_rate / 2.2:
        return samples
    sos = scipy.signal.butter(2, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
    return scipy.signal.sosfiltfilt(sos, samples, axis=0).astype(np.float32)


def apply_dynamic_deesser(
    samples: np.ndarray,
    sample_rate: int,
    threshold_db: float = -20.0,
    max_reduction_db: float = 4.5,
) -> np.ndarray:
    """Atenúa dinámicamente los picos de sibilancia en la banda 5.5 kHz – 9.5 kHz."""
    if len(samples) < 128 or sample_rate < 14000:
        return samples

    nyq = sample_rate / 2.0
    low_f = min(5200.0, nyq * 0.65)
    high_f = min(9500.0, nyq * 0.92)
    if low_f >= high_f:
        return samples

    sos_band = scipy.signal.butter(2, [low_f, high_f], btype="bandpass", fs=sample_rate, output="sos")
    sibilance = scipy.signal.sosfiltfilt(sos_band, samples, axis=0).astype(np.float32)

    # Calcular envolvente RMS rápida (ventana ~8ms)
    win_len = max(16, int(0.008 * sample_rate))
    if sibilance.ndim == 2:
        sib_power = np.mean(sibilance ** 2, axis=1)
    else:
        sib_power = sibilance ** 2

    kernel = np.ones(win_len, dtype=np.float32) / win_len
    env_rms = np.sqrt(np.convolve(sib_power, kernel, mode="same") + 1e-12)
    env_db = 20.0 * np.log10(env_rms + 1e-9)

    over_db = np.maximum(0.0, env_db - threshold_db)
    atten_db = np.minimum(max_reduction_db, over_db * 0.65)
    gain_reduction = 10.0 ** (-atten_db / 20.0)

    if samples.ndim == 2:
        gain_reduction = gain_reduction[:, np.newaxis]

    # Restar la porción excedente de la banda sibilante sin afectar el resto del espectro
    cleaned = samples - sibilance * (1.0 - gain_reduction)
    return cleaned.astype(np.float32)


def apply_broadcast_eq(
    samples: np.ndarray,
    sample_rate: int,
    warmth_gain_db: float = 1.5,
    presence_gain_db: float = 1.8,
) -> np.ndarray:
    """Aplica curva de ecualización de estudio: cuerpo en 180Hz y presencia vocal en 3.8kHz."""
    if len(samples) < 64:
        return samples

    out = samples.astype(np.float64)
    if abs(warmth_gain_db) > 0.05 and 180.0 < sample_rate / 2.2:
        b_w, a_w = _design_peaking_biquad(180.0, warmth_gain_db, q=0.9, sample_rate=sample_rate)
        out = scipy.signal.filtfilt(b_w, a_w, out, axis=0)

    if abs(presence_gain_db) > 0.05 and 3800.0 < sample_rate / 2.2:
        b_p, a_p = _design_peaking_biquad(3800.0, presence_gain_db, q=1.1, sample_rate=sample_rate)
        out = scipy.signal.filtfilt(b_p, a_p, out, axis=0)

    return out.astype(np.float32)


def apply_soft_knee_compressor(
    samples: np.ndarray,
    sample_rate: int,
    threshold_db: float = -18.0,
    ratio: float = 2.5,
) -> np.ndarray:
    """Compresor dinámico RMS con ganancia de compensación para nivelar susurros y énfasis."""
    if len(samples) < 128 or ratio <= 1.0:
        return samples

    if samples.ndim == 2:
        mono_sq = np.mean(samples ** 2, axis=1)
    else:
        mono_sq = samples ** 2

    # Ventana de detección de 25ms suavizada
    win_len = max(32, int(0.025 * sample_rate))
    kernel = np.ones(win_len, dtype=np.float32) / win_len
    rms = np.sqrt(np.convolve(mono_sq, kernel, mode="same") + 1e-12)
    level_db = 20.0 * np.log10(rms + 1e-9)

    over_db = np.maximum(0.0, level_db - threshold_db)
    gain_reduction_db = over_db * (1.0 - 1.0 / ratio)

    # Suavizar la curva de ganancia con ventana de liberación (~80ms)
    rel_len = max(64, int(0.080 * sample_rate))
    rel_kernel = np.ones(rel_len, dtype=np.float32) / rel_len
    smooth_gr_db = np.convolve(gain_reduction_db, rel_kernel, mode="same")

    # Makeup gain moderado (+1.8 dB)
    makeup_db = 1.8
    total_gain_lin = 10.0 ** ((makeup_db - smooth_gr_db) / 20.0)

    if samples.ndim == 2:
        total_gain_lin = total_gain_lin[:, np.newaxis]

    return (samples * total_gain_lin).astype(np.float32)


def apply_true_peak_limiter(samples: np.ndarray, ceiling_dbtp: float = -1.0) -> np.ndarray:
    """Limitador brickwall con saturación suave en los picos para evitar distorsión digital."""
    if len(samples) == 0:
        return samples

    ceiling_lin = float(10.0 ** (ceiling_dbtp / 20.0))  # -1.0 dBTP ≈ 0.89125
    peak = float(np.max(np.abs(samples)))
    if peak < 1e-6:
        return samples

    # Si el audio está muy bajo, normalizar suavemente hacia -1.5 dBTP antes de limitar
    target_norm = ceiling_lin * 0.94
    if peak < target_norm * 0.5:
        boost = min(3.5, target_norm / peak)
        samples = samples * boost

    # Rodilla suave hiperbólica por encima del 85% del techo
    knee = ceiling_lin * 0.85
    abs_s = np.abs(samples)
    above = abs_s > knee
    if np.any(above):
        sign = np.sign(samples[above])
        excess = (abs_s[above] - knee) / (ceiling_lin - knee + 1e-9)
        compressed = knee + (ceiling_lin - knee) * np.tanh(excess)
        out = samples.copy()
        out[above] = sign * compressed
    else:
        out = samples.copy()

    return np.clip(out, -ceiling_lin, ceiling_lin).astype(np.float32)


def master_audio_track(
    samples: np.ndarray,
    sample_rate: int,
    config: MasteringConfig | None = None,
) -> np.ndarray:
    """Ejecuta la cadena completa de masterización DSP sobre un vector de audio."""
    cfg = config or MasteringConfig()
    if not cfg.enabled or len(samples) == 0:
        return samples

    out = apply_highpass_filter(samples, sample_rate, cutoff_hz=cfg.hpf_cutoff_hz)
    if cfg.deesser_enabled:
        out = apply_dynamic_deesser(
            out,
            sample_rate,
            threshold_db=cfg.deesser_threshold_db,
            max_reduction_db=cfg.deesser_reduction_db,
        )
    out = apply_broadcast_eq(
        out,
        sample_rate,
        warmth_gain_db=cfg.warmth_gain_db,
        presence_gain_db=cfg.presence_gain_db,
    )
    if cfg.compressor_enabled:
        out = apply_soft_knee_compressor(
            out,
            sample_rate,
            threshold_db=cfg.compressor_threshold_db,
            ratio=cfg.compressor_ratio,
        )
    out = apply_true_peak_limiter(out, ceiling_dbtp=cfg.ceiling_dbtp)
    return out
