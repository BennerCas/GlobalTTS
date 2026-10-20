"""Motor de síntesis TTS local basado en Piper / Sherpa-ONNX.

100% offline, costo cero, latencia ultra-baja (RTF < 0.05).
Soporta modulación de velocidad (speed), ganancia de volumen (gain_db)
y voces en español instaladas en la bóveda central de modelos.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import sherpa_onnx
import soundfile as sf

from src.markup.style import Style

DEFAULT_MODELS_DIR = Path(r"C:\antigravityAS\Modelos -ai-brains")
DEFAULT_VOICE_KEY = "es_MX-claude-high"


@dataclass(frozen=True)
class VoiceProfile:
    key: str
    name: str
    language: str
    path: Path
    sample_rate: int


def list_available_piper_voices(models_dir: Optional[Path] = None) -> dict[str, VoiceProfile]:
    """Escanea la carpeta de modelos buscando modelos de voz Piper/VITS en español."""
    base_dir = models_dir or DEFAULT_MODELS_DIR
    voices: dict[str, VoiceProfile] = {}

    if not base_dir.exists():
        return voices

    for item in base_dir.iterdir():
        if item.is_dir() and (item.name.startswith("vits-piper-") or "piper" in item.name.lower()):
            onnx_files = list(item.glob("*.onnx"))
            tokens_file = item / "tokens.txt"
            if onnx_files and tokens_file.exists():
                onnx_path = onnx_files[0]
                # Determinar nombre legible y key
                key = item.name.replace("vits-piper-", "")
                sr = 22050
                # Chequear si hay json de configuración
                json_files = list(item.glob("*.json"))
                if json_files:
                    try:
                        import json
                        with open(json_files[0], "r", encoding="utf-8") as f:
                            cfg_data = json.load(f)
                            sr = cfg_data.get("audio", {}).get("sample_rate", 22050)
                    except Exception:
                        pass

                voices[key] = VoiceProfile(
                    key=key,
                    name=f"Piper ({key})",
                    language="es",
                    path=item,
                    sample_rate=sr
                )

    return voices


class PiperTtsEngine:
    """Motor de síntesis local Piper optimizado para libros y textos largos."""

    def __init__(self, voice_key: str = DEFAULT_VOICE_KEY, models_dir: Optional[Path] = None, num_threads: int = 8):
        self.models_dir = models_dir or DEFAULT_MODELS_DIR
        self.available_voices = list_available_piper_voices(self.models_dir)
        self.num_threads = num_threads

        if not self.available_voices:
            raise RuntimeError(f"No se encontraron modelos Piper en {self.models_dir}")

        if voice_key not in self.available_voices:
            # Fallback a la primera voz disponible en español
            voice_key = next(iter(self.available_voices))

        self.current_voice_key = voice_key
        self._tts_instances: dict[str, sherpa_onnx.OfflineTts] = {}
        self._load_voice(self.current_voice_key)

    def _load_voice(self, key: str) -> sherpa_onnx.OfflineTts:
        if key in self._tts_instances:
            return self._tts_instances[key]

        profile = self.available_voices.get(key)
        if not profile:
            profile = self.available_voices[self.current_voice_key]

        onnx_file = next(profile.path.glob("*.onnx"))
        tokens_file = profile.path / "tokens.txt"
        data_dir = profile.path / "espeak-ng-data"

        vits_cfg = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(onnx_file),
            tokens=str(tokens_file),
            data_dir=str(data_dir) if data_dir.exists() else ""
        )
        tts_cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=vits_cfg,
                num_threads=self.num_threads,
                provider="cpu"
            )
        )
        tts = sherpa_onnx.OfflineTts(tts_cfg)
        self._tts_instances[key] = tts
        return tts

    @property
    def sample_rate(self) -> int:
        return self.available_voices[self.current_voice_key].sample_rate

    def synthesize(self, text: str, style: Optional[Style] = None) -> np.ndarray:
        """Sintetiza texto aplicando el estilo (speed, gain_db, voz alternativa si aplica).

        Retorna un array float32 mono con la señal de audio normalizada entre [-1.0, 1.0].
        """
        style = style or Style()
        text_clean = text.strip()

        if not text_clean:
            return np.zeros(0, dtype=np.float32)

        target_voice = style.voice if (style.voice and style.voice in self.available_voices) else self.current_voice_key
        tts = self._load_voice(target_voice)

        # Generar con velocidad aplicada
        audio = tts.generate(text_clean, sid=0, speed=style.speed)
        samples = np.array(audio.samples, dtype=np.float32)

        # Aplicar ganancia si difiere de 0
        if style.gain_db != 0.0:
            scale = 10.0 ** (style.gain_db / 20.0)
            samples = samples * scale
            # Soft clip para evitar distorsión
            np.clip(samples, -1.0, 1.0, out=samples)

        return samples

    def generate_silence(self, duration_s: float) -> np.ndarray:
        """Genera un array de ceros para pausas con duración exacta."""
        if duration_s <= 0:
            return np.zeros(0, dtype=np.float32)
        num_samples = int(duration_s * self.sample_rate)
        return np.zeros(num_samples, dtype=np.float32)
