"""Motor de síntesis TTS local basado en Kokoro Neural y Piper / Sherpa-ONNX.

100% offline, costo cero, latencia ultra-baja (RTF < 0.05).
Soporta:
- Voces neurales hiper-humanas Kokoro (StyleTTS2, 24kHz) con entonación natural, cadencia emocional y modulación prosódica.
- Voces neurales Piper VITS (16-22kHz) de alta velocidad.
- Resampling transparente entre frecuencias de muestreo (22.05kHz <-> 24kHz).
- Modulación acústica en decibelios (dB), velocidad (speed), silencios digitales ([pausa:1s]) y auto-casting multi-voz ([voz:id]).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import scipy.signal
import sherpa_onnx
import soundfile as sf

from src.markup.style import Style

logger = logging.getLogger("globaltts.tts_engine")

DEFAULT_MODELS_DIR = Path(r"C:\antigravityAS\Modelos -ai-brains")
DEFAULT_VOICE_KEY = "kokoro-ef_dora"


@dataclass(frozen=True)
class VoiceProfile:
    key: str
    name: str
    language: str
    path: Path
    sample_rate: int
    engine: str = "piper"  # "kokoro" | "piper"
    gender: str = "neutral"


# Catálogo de Voces Neurales Kokoro multi-idioma (24kHz, StyleTTS2)
KOKORO_NEURAL_VOICES = {
    "kokoro-ef_dora": {
        "name": "Kokoro Neural: Dora (Español Neutro Femenino - Expresiva y Cálida)",
        "sid": 28,
        "gender": "female",
    },
    "kokoro-em_alex": {
        "name": "Kokoro Neural: Alex (Español Neutro Masculino - Joven y Dinámico)",
        "sid": 29,
        "gender": "male",
    },
    "kokoro-em_santa": {
        "name": "Kokoro Neural: Santa (Español Masculino - Profundo y Maduro)",
        "sid": 30,
        "gender": "male",
    },
    "kokoro-af_bella": {
        "name": "Kokoro Neural: Bella (Español Femenino - Suave y Melódica)",
        "sid": 2,
        "gender": "female",
    },
    "kokoro-af_sarah": {
        "name": "Kokoro Neural: Sarah (Español Femenino - Cuentacuentos y Serena)",
        "sid": 9,
        "gender": "female",
    },
    "kokoro-af_nicole": {
        "name": "Kokoro Neural: Nicole (Español Femenino - Teatral y Artística)",
        "sid": 6,
        "gender": "female",
    },
    "kokoro-am_michael": {
        "name": "Kokoro Neural: Michael (Español Masculino - Locutor de Radio y Épica)",
        "sid": 16,
        "gender": "male",
    },
    "kokoro-am_adam": {
        "name": "Kokoro Neural: Adam (Español Masculino - Firme y Resonante)",
        "sid": 11,
        "gender": "male",
    },
    "kokoro-bm_george": {
        "name": "Kokoro Neural: George (Español Masculino - Clásica y Solemne)",
        "sid": 26,
        "gender": "male",
    },
}


def list_available_piper_voices(models_dir: Optional[Path] = None) -> dict[str, VoiceProfile]:
    """Escanea la carpeta de modelos central y devuelve todas las voces neurales Kokoro y Piper."""
    base_dir = models_dir or DEFAULT_MODELS_DIR
    voices: dict[str, VoiceProfile] = {}

    if not base_dir.exists():
        return voices

    # 1. Registrar voces neurales Kokoro si el modelo multi-lang existe
    kokoro_dir = base_dir / "kokoro-multi-lang-v1_1"
    if kokoro_dir.exists() and (kokoro_dir / "model.onnx").exists():
        for key, meta in KOKORO_NEURAL_VOICES.items():
            voices[key] = VoiceProfile(
                key=key,
                name=meta["name"],
                language="es",
                path=kokoro_dir,
                sample_rate=24000,
                engine="kokoro",
                gender=meta["gender"],
            )

    # 2. Registrar voces Piper VITS
    for item in base_dir.iterdir():
        if item.is_dir() and (item.name.startswith("vits-piper-") or "piper" in item.name.lower()):
            onnx_files = list(item.glob("*.onnx"))
            tokens_file = item / "tokens.txt"
            if onnx_files and tokens_file.exists():
                key = item.name.replace("vits-piper-", "")
                sr = 22050
                json_files = list(item.glob("*.json"))
                if json_files:
                    try:
                        import json
                        with open(json_files[0], "r", encoding="utf-8") as f:
                            cfg_data = json.load(f)
                            sr = cfg_data.get("audio", {}).get("sample_rate", 22050)
                    except Exception:
                        pass

                clean_name = key
                gender = "neutral"
                if "daniela" in key.lower():
                    gender = "female"
                    clean_name = "Daniela (Argentina, Femenino)"
                elif "claude" in key.lower():
                    clean_name = "Claude (México, Alta Definición)"
                elif "ald" in key.lower():
                    clean_name = "Ald (México, Neutro)"
                elif "sharvard" in key.lower():
                    clean_name = "Sharvard (España, Estudio)"
                elif "davefx" in key.lower():
                    clean_name = "Davefx (España, Masculino)"
                elif "carlfm" in key.lower():
                    clean_name = "Carlfm (España, Rápido)"

                voices[key] = VoiceProfile(
                    key=key,
                    name=f"Piper: {clean_name}",
                    language="es",
                    path=item,
                    sample_rate=sr,
                    engine="piper",
                    gender=gender,
                )

    return voices


class PiperTtsEngine:
    """Motor de síntesis TTS local híbrido (Kokoro Neural 24kHz + Piper VITS)."""

    def __init__(self, voice_key: str = DEFAULT_VOICE_KEY, models_dir: Optional[Path] = None, num_threads: int = 8):
        self.models_dir = models_dir or DEFAULT_MODELS_DIR
        self.available_voices = list_available_piper_voices(self.models_dir)
        self.num_threads = num_threads

        if not self.available_voices:
            raise RuntimeError(f"No se encontraron modelos de voz en {self.models_dir}")

        if voice_key not in self.available_voices:
            voice_key = next(iter(self.available_voices))

        self.current_voice_key = voice_key
        self._piper_instances: dict[str, sherpa_onnx.OfflineTts] = {}
        self._kokoro_instance: Optional[sherpa_onnx.OfflineTts] = None

    def _get_kokoro_tts(self) -> sherpa_onnx.OfflineTts:
        """Carga o retorna la instancia compartida de Kokoro multi-lingual."""
        if self._kokoro_instance is not None:
            return self._kokoro_instance

        kokoro_dir = self.models_dir / "kokoro-multi-lang-v1_1"
        k_cfg = sherpa_onnx.OfflineTtsKokoroModelConfig(
            model=str(kokoro_dir / "model.onnx"),
            voices=str(kokoro_dir / "voices.bin"),
            tokens=str(kokoro_dir / "tokens.txt"),
            data_dir=str(kokoro_dir / "espeak-ng-data"),
            lang="es",
        )
        tts_cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                kokoro=k_cfg,
                num_threads=self.num_threads,
                provider="cpu",
            )
        )
        self._kokoro_instance = sherpa_onnx.OfflineTts(tts_cfg)
        return self._kokoro_instance

    def _load_piper_voice(self, key: str) -> sherpa_onnx.OfflineTts:
        """Carga o retorna una instancia específica de Piper VITS."""
        if key in self._piper_instances:
            return self._piper_instances[key]

        profile = self.available_voices.get(key)
        if not profile or profile.engine != "piper":
            # Fallback a la primera voz Piper disponible
            piper_keys = [k for k, v in self.available_voices.items() if v.engine == "piper"]
            profile = self.available_voices[piper_keys[0]] if piper_keys else profile

        onnx_file = next(profile.path.glob("*.onnx"))
        tokens_file = profile.path / "tokens.txt"
        data_dir = profile.path / "espeak-ng-data"

        vits_cfg = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(onnx_file),
            tokens=str(tokens_file),
            data_dir=str(data_dir) if data_dir.exists() else "",
        )
        tts_cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=vits_cfg,
                num_threads=self.num_threads,
                provider="cpu",
            )
        )
        tts = sherpa_onnx.OfflineTts(tts_cfg)
        self._piper_instances[key] = tts
        return tts

    @property
    def sample_rate(self) -> int:
        return self.available_voices[self.current_voice_key].sample_rate

    def _generate_raw_audio(self, text: str, voice_key: str, speed: float) -> tuple[np.ndarray, int]:
        """Genera el audio crudo para un segmento de texto según su motor de voz."""
        profile = self.available_voices.get(voice_key, self.available_voices[self.current_voice_key])

        if profile.engine == "kokoro" and voice_key in KOKORO_NEURAL_VOICES:
            tts = self._get_kokoro_tts()
            sid = KOKORO_NEURAL_VOICES[voice_key]["sid"]
            audio = tts.generate(text, sid=sid, speed=speed)
            return np.array(audio.samples, dtype=np.float32), 24000
        else:
            tts = self._load_piper_voice(voice_key)
            audio = tts.generate(text, sid=0, speed=speed)
            return np.array(audio.samples, dtype=np.float32), profile.sample_rate

    def synthesize(self, text: str, style: Optional[Style] = None) -> np.ndarray:
        """Sintetiza texto interpretando dinámicamente etiquetas fonéticas y prosódicas.

        Soporta de forma nativa:
        - Pausas exactas ([pausa], [pausa:1s], [pausa:500ms]) en silencio digital.
        - Modulación dinámica de tempo/velocidad ([lento], [rapido]).
        - Modulación dinámica de volumen e intimidad ([susurro], [enfasis]).
        - Expresividad emocional ([misterioso], [alegre], [triste], [serio], [emocionado], [enojado]).
        - Cambio dinámico de voces ([voz:kokoro-em_alex] o [voz:es_ES-sharvard-medium]).
        - Concatenación segura y resampling automático a la frecuencia base.
        """
        style = style or Style()
        text_clean = text.strip()

        if not text_clean:
            return np.zeros(0, dtype=np.float32)

        base_sr = self.sample_rate

        # Si contiene etiquetas prosódicas entre corchetes, procesar mediante el parser de markup
        if "[" in text_clean and "]" in text_clean:
            from src.markup.parser import parse_markup
            parse_res = parse_markup(text_clean)
            if parse_res.segments:
                chunks: list[np.ndarray] = []
                for seg in parse_res.segments:
                    # 1. Inserción de pausa exacta en silencio digital
                    if seg.pause_s > 0:
                        chunks.append(self.generate_silence(seg.pause_s))

                    # 2. Síntesis acústica del segmento
                    seg_text = seg.text.strip()
                    if seg_text:
                        # Limpiar acotaciones espurias
                        seg_text = re.sub(r"\[(?:Yo|Narrador|Personaje|Voz|Actor)[^\]]*\]", "", seg_text).strip()
                        if not seg_text:
                            continue

                        # Determinar voz del segmento
                        target_voice = (
                            seg.style.voice
                            if (seg.style.voice and seg.style.voice in self.available_voices)
                            else (style.voice if (style.voice and style.voice in self.available_voices) else self.current_voice_key)
                        )

                        # Modulación de velocidad combinada (base * segmento)
                        eff_speed = style.speed * seg.style.speed
                        eff_speed = max(0.5, min(2.5, eff_speed))

                        seg_samples, seg_sr = self._generate_raw_audio(seg_text, target_voice, eff_speed)

                        # Resamplear si la frecuencia de muestreo difiere de la base
                        if seg_sr != base_sr and len(seg_samples) > 0:
                            target_len = int(len(seg_samples) * base_sr / seg_sr)
                            seg_samples = scipy.signal.resample(seg_samples, target_len).astype(np.float32)

                        # Modulación de ganancia combinada (base + segmento)
                        eff_gain = style.gain_db + seg.style.gain_db
                        if eff_gain != 0.0:
                            scale = 10.0 ** (eff_gain / 20.0)
                            seg_samples = seg_samples * scale
                            np.clip(seg_samples, -1.0, 1.0, out=seg_samples)

                        chunks.append(seg_samples)

                if chunks:
                    return np.concatenate(chunks)

        # Texto plano sin etiquetas
        target_voice = style.voice if (style.voice and style.voice in self.available_voices) else self.current_voice_key
        samples, seg_sr = self._generate_raw_audio(text_clean, target_voice, style.speed)

        if seg_sr != base_sr and len(samples) > 0:
            target_len = int(len(samples) * base_sr / seg_sr)
            samples = scipy.signal.resample(samples, target_len).astype(np.float32)

        if style.gain_db != 0.0:
            scale = 10.0 ** (style.gain_db / 20.0)
            samples = samples * scale
            np.clip(samples, -1.0, 1.0, out=samples)

        return samples

    def generate_silence(self, duration_s: float) -> np.ndarray:
        """Genera un array de ceros para pausas con duración exacta."""
        if duration_s <= 0:
            return np.zeros(0, dtype=np.float32)
        num_samples = int(duration_s * self.sample_rate)
        return np.zeros(num_samples, dtype=np.float32)
