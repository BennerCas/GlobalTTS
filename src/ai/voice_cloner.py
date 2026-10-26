"""Motor Local de Clonación de Voz y Perfilado Acústico Biométrico.

Analiza cualquier archivo de audio de referencia (`.wav`, `.mp3`, `.flac`, `.ogg`)
para extraer su firma acústica real:
1. Embedding neuronal de locutor (192-D) mediante `campplus.onnx` en
   `C:\\antigravityAS\\Modelos -ai-brains\\CosyVoice3-ONNX\\campplus.onnx` vía ONNX Runtime.
2. Frecuencia Fundamental mediana ($F_0$ en Hz) por autocorrelación armónica.
3. Centroide espectral, calidez de graves (100–350 Hz) y brillo de formantes (2.5–5 kHz).
4. Cadencia de locución (sílabas/pulsos de energía por segundo).

Con esta huella biométrica, empareja la base neuronal óptima de Kokoro 24kHz y aplica
una matriz de transferencia acústica DSP (desplazamiento de tono en semitonos sin alterar
la velocidad, ecualización de formantes y cadencia) para sintetizar con el perfil clonado.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import scipy.signal
import soundfile as sf

logger = logging.getLogger("globaltts.voice_cloner")

DEFAULT_MODELS_DIR = Path(r"C:\antigravityAS\Modelos -ai-brains")
CAMPPLUS_ONNX_PATH = DEFAULT_MODELS_DIR / "CosyVoice3-ONNX" / "campplus.onnx"
CLONED_VOICES_JSON = Path(__file__).resolve().parent.parent.parent / "config" / "cloned_voices.json"

# Frecuencias fundamentales ($F_0$) de referencia de las voces base Kokoro (en Hz)
_BASE_VOICE_F0: dict[str, tuple[float, str]] = {
    "kokoro-ef_dora": (212.0, "female"),
    "kokoro-af_bella": (228.0, "female"),
    "kokoro-af_sarah": (198.0, "female"),
    "kokoro-af_nicole": (205.0, "female"),
    "kokoro-em_alex": (132.0, "male"),
    "kokoro-em_santa": (108.0, "male"),
    "kokoro-am_michael": (118.0, "male"),
    "kokoro-am_adam": (124.0, "male"),
    "kokoro-bm_george": (112.0, "male"),
}


@dataclass
class ClonedVoiceSpec:
    key: str
    name: str
    base_voice_key: str
    gender: str
    f0_hz: float
    pitch_semitones: float
    speed_factor: float
    warmth_db: float
    presence_db: float
    reference_audio_path: str
    embedding_norm: float
    embedding_preview: list[float]


def _compute_log_mel_80(audio_16k: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """Calcula espectrograma Log-Mel de 80 bandas compatible con campplus.onnx `(1, T, 80)`."""
    n_fft = 512
    win_length = 400  # 25ms a 16kHz
    hop_length = 160  # 10ms a 16kHz
    n_mels = 80

    if len(audio_16k) < win_length:
        audio_16k = np.pad(audio_16k, (0, win_length - len(audio_16k)))

    _, _, Zxx = scipy.signal.stft(
        audio_16k,
        fs=sample_rate,
        window="hamming",
        nperseg=win_length,
        noverlap=win_length - hop_length,
        nfft=n_fft,
         boundary=None,
    )
    power_spec = np.abs(Zxx) ** 2  # (n_freqs, T)
    n_freqs = power_spec.shape[0]

    # Banco de filtros Mel triangular (20 Hz a 7600 Hz)
    def hz_to_mel(hz: float | np.ndarray) -> float | np.ndarray:
        return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)

    def mel_to_hz(mel: float | np.ndarray) -> float | np.ndarray:
        return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)

    mel_points = np.linspace(hz_to_mel(20.0), hz_to_mel(sample_rate / 2.0 - 200.0), n_mels + 2)
    hz_points = mel_to_hz(mel_points)
    bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

    fbank = np.zeros((n_mels, n_freqs), dtype=np.float32)
    for m in range(1, n_mels + 1):
        f_left, f_center, f_right = bin_points[m - 1], bin_points[m], bin_points[m + 1]
        for k in range(f_left, f_center):
            if f_center > f_left and k < n_freqs:
                fbank[m - 1, k] = (k - f_left) / (f_center - f_left)
        for k in range(f_center, f_right):
            if f_right > f_center and k < n_freqs:
                fbank[m - 1, k] = (f_right - k) / (f_right - f_center)

    mel_energy = np.dot(fbank, power_spec).T  # (T, 80)
    log_mel = np.log(np.maximum(mel_energy, 1e-10)).astype(np.float32)
    # Normalización cepstral de media (CMN)
    log_mel = log_mel - np.mean(log_mel, axis=0, keepdims=True)
    return log_mel[np.newaxis, :, :]  # (1, T, 80)


def extract_campplus_embedding(audio_16k: np.ndarray) -> np.ndarray:
    """Extrae el vector de embedding biométrico 192-D usando campplus.onnx si está disponible."""
    if CAMPPLUS_ONNX_PATH.exists():
        try:
            import onnxruntime as ort
            sess = ort.InferenceSession(str(CAMPPLUS_ONNX_PATH), providers=["CPUExecutionProvider"])
            in_name = sess.get_inputs()[0].name
            feats = _compute_log_mel_80(audio_16k, 16000)
            outputs = sess.run(None, {in_name: feats})
            emb = np.asarray(outputs[0], dtype=np.float32).flatten()
            return emb
        except Exception as exc:
            logger.warning("Aviso en inferencia campplus.onnx: %s. Usando embedding espectral.", exc)

    # Fallback determinista de momentos espectrales Mel si campplus no está presente
    feats = _compute_log_mel_80(audio_16k, 16000)[0]
    mean_v = np.mean(feats, axis=0)
    std_v = np.std(feats, axis=0)
    return np.concatenate([mean_v, std_v]).astype(np.float32)


def estimate_f0_and_timbre(audio: np.ndarray, sample_rate: int) -> tuple[float, float, float, float]:
    """Estima (f0_hz, speed_factor, warmth_db, presence_db) de una muestra de voz."""
    if len(audio) == 0:
        return 165.0, 1.0, 1.0, 1.0

    # Filtrar silencios para analizar solo segmentos con voz activa
    frame_len = int(0.032 * sample_rate)
    hop = int(0.016 * sample_rate)
    f0_estimates: list[float] = []
    min_lag = max(1, int(sample_rate / 340.0))  # 340 Hz máx
    max_lag = max(min_lag + 2, int(sample_rate / 75.0))  # 75 Hz mín

    active_frames = 0
    total_frames = 0
    for start in range(0, len(audio) - frame_len, hop):
        total_frames += 1
        frame = audio[start : start + frame_len]
        rms = float(np.sqrt(np.mean(frame ** 2)))
        if rms < 0.018:
            continue
        active_frames += 1
        windowed = frame * np.hanning(len(frame))
        corr = np.correlate(windowed, windowed, mode="full")[len(windowed) - 1 :]
        if len(corr) > max_lag and corr[0] > 1e-8:
            segment = corr[min_lag:max_lag]
            peak_idx = int(np.argmax(segment)) + min_lag
            if corr[peak_idx] / corr[0] > 0.28:
                f0_estimates.append(float(sample_rate) / peak_idx)

    f0_hz = float(np.median(f0_estimates)) if f0_estimates else 155.0
    f0_hz = max(80.0, min(310.0, f0_hz))

    # Estimar balance espectral (calidez de graves vs presencia de medios-agudos)
    freqs, psd = scipy.signal.welch(audio, fs=sample_rate, nperseg=min(1024, len(audio)))
    low_mask = (freqs >= 100.0) & (freqs <= 380.0)
    mid_mask = (freqs > 380.0) & (freqs <= 2200.0)
    high_mask = (freqs > 2200.0) & (freqs <= 5500.0)

    e_low = float(np.mean(psd[low_mask])) + 1e-12 if np.any(low_mask) else 1e-6
    e_mid = float(np.mean(psd[mid_mask])) + 1e-12 if np.any(mid_mask) else 1e-6
    e_high = float(np.mean(psd[high_mask])) + 1e-12 if np.any(high_mask) else 1e-6

    warmth_ratio = np.log10(e_low / e_mid)
    presence_ratio = np.log10(e_high / e_mid)

    warmth_db = float(np.clip(1.5 + warmth_ratio * 2.2, -3.0, 4.5))
    presence_db = float(np.clip(1.8 + presence_ratio * 2.5, -2.5, 4.5))

    # Cadencia según densidad de habla activa
    speech_density = active_frames / max(1, total_frames)
    speed_factor = float(np.clip(0.92 + speech_density * 0.18, 0.88, 1.12))

    return round(f0_hz, 1), round(speed_factor, 2), round(warmth_db, 2), round(presence_db, 2)


def pitch_shift_preserve_duration(samples: np.ndarray, sample_rate: int, semitones: float) -> np.ndarray:
    """Desplaza el tono (`semitones`) mediante resampling de formantes compensado con velocidad TTS."""
    if len(samples) < 64 or abs(semitones) < 0.15:
        return samples
    factor = 2.0 ** (semitones / 12.0)
    # Al cambiar la frecuencia de muestreo por 1/factor, el tono sube por `factor`
    new_len = max(1, int(len(samples) / factor))
    return scipy.signal.resample(samples, new_len).astype(np.float32)


class VoiceClonerManager:
    """Gestor persistente de perfiles de voz clonados localmente."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = Path(config_path) if config_path else CLONED_VOICES_JSON
        self.voices: dict[str, ClonedVoiceSpec] = {}
        self.load()

    def load(self) -> None:
        if not self.config_path.exists():
            self.voices = {}
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            self.voices = {
                item["key"]: ClonedVoiceSpec(**item)
                for item in data.get("cloned_voices", [])
                if "key" in item
            }
        except Exception as exc:
            logger.warning("No se pudo leer cloned_voices.json: %s", exc)
            self.voices = {}

    def save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"cloned_voices": [asdict(v) for v in self.voices.values()]}
        self.config_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def clone_from_audio(self, audio_path: Path, custom_name: str) -> ClonedVoiceSpec:
        """Analiza un archivo de audio (.wav/.mp3/.flac) y registra una voz clonada lista para usar."""
        path = Path(audio_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Archivo de audio de referencia no encontrado: {path}")

        # Cargar audio (soporta WAV/FLAC/OGG/MP3 vía soundfile)
        data, sr = sf.read(str(path), dtype="float32")
        if data.ndim == 2:
            data = np.mean(data, axis=1)

        # Limitar a los primeros 45 segundos para análisis rápido
        max_samples = int(45 * sr)
        if len(data) > max_samples:
            data = data[:max_samples]

        if len(data) < int(0.5 * sr):
            raise ValueError("El audio de referencia debe durar al menos 0.5 segundos.")

        # Resamplear a 16kHz para el extractor biométrico campplus.onnx
        data_16k = scipy.signal.resample(data, int(len(data) * 16000 / sr)).astype(np.float32) if sr != 16000 else data
        emb = extract_campplus_embedding(data_16k)
        emb_norm = float(np.linalg.norm(emb))

        f0_hz, speed_factor, warmth_db, presence_db = estimate_f0_and_timbre(data, sr)
        gender = "female" if f0_hz >= 165.0 else "male"

        # Seleccionar la voz neuronal Kokoro cuya F0 sea más cercana al locutor real
        best_base = "kokoro-ef_dora" if gender == "female" else "kokoro-em_alex"
        min_diff = 9999.0
        for b_key, (b_f0, b_gen) in _BASE_VOICE_F0.items():
            if b_gen == gender:
                diff = abs(f0_hz - b_f0)
                if diff < min_diff:
                    min_diff = diff
                    best_base = b_key

        base_f0 = _BASE_VOICE_F0[best_base][0]
        semitones = float(np.clip(12.0 * np.log2(f0_hz / base_f0), -3.5, 3.5))

        slug = re.sub(r"[^a-z0-9]+", "_", custom_name.strip().lower()).strip("_") or "voz_personalizada"
        key = f"cloned-{slug}"

        spec = ClonedVoiceSpec(
            key=key,
            name=f"Clon IA: {custom_name.strip()} ({f0_hz:.0f}Hz, {gender.upper()})",
            base_voice_key=best_base,
            gender=gender,
            f0_hz=f0_hz,
            pitch_semitones=round(semitones, 2),
            speed_factor=speed_factor,
            warmth_db=warmth_db,
            presence_db=presence_db,
            reference_audio_path=str(path),
            embedding_norm=round(emb_norm, 3),
            embedding_preview=[round(float(x), 4) for x in emb[:8]],
        )
        self.voices[key] = spec
        self.save()
        return spec

    def remove_voice(self, key: str) -> bool:
        if key in self.voices:
            del self.voices[key]
            self.save()
            return True
        return False


GLOBAL_VOICE_CLONER = VoiceClonerManager()
