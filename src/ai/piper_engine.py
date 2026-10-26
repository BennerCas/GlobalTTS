"""Motor de síntesis TTS local basado en Kokoro Neural, Perfiles Clonados y Piper / Sherpa-ONNX.

100% offline, costo cero, latencia ultra-baja (RTF < 0.05).
Soporta:
- Voces neurales hiper-humanas Kokoro (StyleTTS2, 24kHz) con entonación natural, cadencia emocional y modulación prosódica.
- Voces neurales Piper VITS (16-22kHz) de alta velocidad.
- Perfiles de voz clonados localmente (CosyVoice3 campplus.onnx + transferencia de F0 y formantes DSP).
- Caché inteligente SHA-256 en disco (`GLOBAL_AUDIO_CACHE`) para evitar re-síntesis redundantes.
- Efectos de sonido Foley (`[sfx:trueno]`, `[sfx:puerta]`, etc.) integrados en línea.
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

from src.ai.voice_cloner import GLOBAL_VOICE_CLONER, pitch_shift_preserve_duration
from src.audio.dsp_mastering import apply_broadcast_eq
from src.audio.sfx_engine import extract_and_strip_sfx_tags, synthesize_sfx
from src.core.audio_cache import GLOBAL_AUDIO_CACHE
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
    engine: str = "piper"  # "kokoro" | "piper" | "cloned"
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
    """Escanea la carpeta de modelos central y devuelve todas las voces neurales Kokoro, Clonadas y Piper."""
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

        # 2. Registrar voces clonadas personalizadas sobre base Kokoro 24kHz
        GLOBAL_VOICE_CLONER.load()
        for c_key, c_spec in GLOBAL_VOICE_CLONER.voices.items():
            voices[c_key] = VoiceProfile(
                key=c_key,
                name=c_spec.name,
                language="es",
                path=kokoro_dir,
                sample_rate=24000,
                engine="cloned",
                gender=c_spec.gender,
            )

    # 3. Registrar voces Piper VITS
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
    """Motor de síntesis TTS local híbrido (Kokoro Neural 24kHz + Voces Clonadas + Piper VITS)."""

    def __init__(
        self,
        voice_key: str = DEFAULT_VOICE_KEY,
        models_dir: Optional[Path] = None,
        num_threads: int = 8,
        use_cache: bool = True,
    ):
        self.models_dir = models_dir or DEFAULT_MODELS_DIR
        self.available_voices = list_available_piper_voices(self.models_dir)
        self.num_threads = num_threads
        self.use_cache = use_cache

        if not self.available_voices:
            raise RuntimeError(f"No se encontraron modelos de voz en {self.models_dir}")

        if voice_key not in self.available_voices:
            voice_key = next(iter(self.available_voices))

        self.current_voice_key = voice_key
        self._piper_instances: dict[str, sherpa_onnx.OfflineTts] = {}
        self._kokoro_instance: Optional[sherpa_onnx.OfflineTts] = None

    def refresh_voices(self) -> None:
        """Recarga el catálogo de voces (incluyendo nuevas voces clonadas)."""
        self.available_voices = list_available_piper_voices(self.models_dir)

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
        """Genera el audio crudo para un segmento de texto según su motor de voz (con soporte de caché y clonación)."""
        profile = self.available_voices.get(voice_key, self.available_voices[self.current_voice_key])
        target_sr = profile.sample_rate

        if self.use_cache:
            cached = GLOBAL_AUDIO_CACHE.get(voice_key, target_sr, speed, 0.0, text)
            if cached is not None:
                return cached, target_sr

        if profile.engine == "cloned":
            spec = GLOBAL_VOICE_CLONER.voices.get(voice_key)
            base_key = spec.base_voice_key if (spec and spec.base_voice_key in KOKORO_NEURAL_VOICES) else "kokoro-ef_dora"
            tts = self._get_kokoro_tts()
            sid = KOKORO_NEURAL_VOICES[base_key]["sid"]
            # Compensar el cambio de duración que produce el pitch shift
            pitch_factor = 2.0 ** ((spec.pitch_semitones if spec else 0.0) / 12.0)
            comp_speed = max(0.5, min(2.2, (speed * (spec.speed_factor if spec else 1.0)) / pitch_factor))
            audio = tts.generate(text, sid=sid, speed=comp_speed)
            samples = np.array(audio.samples, dtype=np.float32)
            if spec and len(samples) > 64:
                samples = pitch_shift_preserve_duration(samples, 24000, spec.pitch_semitones)
                samples = apply_broadcast_eq(
                    samples,
                    24000,
                    warmth_gain_db=spec.warmth_db,
                    presence_gain_db=spec.presence_db,
                )
            sr = 24000

        elif profile.engine == "kokoro" and voice_key in KOKORO_NEURAL_VOICES:
            tts = self._get_kokoro_tts()
            sid = KOKORO_NEURAL_VOICES[voice_key]["sid"]
            audio = tts.generate(text, sid=sid, speed=speed)
            samples = np.array(audio.samples, dtype=np.float32)
            sr = 24000

        else:
            tts = self._load_piper_voice(voice_key)
            audio = tts.generate(text, sid=0, speed=speed)
            samples = np.array(audio.samples, dtype=np.float32)
            sr = profile.sample_rate

        if self.use_cache and len(samples) > 0:
            GLOBAL_AUDIO_CACHE.put(voice_key, sr, speed, 0.0, text, samples)

        return samples, sr

    def synthesize(self, text: str, style: Optional[Style] = None) -> np.ndarray:
        """Sintetiza texto interpretando dinámicamente etiquetas fonéticas, prosódicas y de efectos Foley."""
        style = style or Style()
        text_clean = text.strip()

        if not text_clean:
            return np.zeros(0, dtype=np.float32)

        base_sr = self.sample_rate

        # Si el fragmento es únicamente una etiqueta [sfx:nombre]
        if text_clean.lower().startswith("[sfx:") and text_clean.endswith("]") and text_clean.count("[") == 1:
            sfx_name = text_clean[5:-1].strip()
            return synthesize_sfx(sfx_name, sample_rate=base_sr)

        # Si contiene etiquetas prosódicas o SFX entre corchetes, procesar mediante el parser de markup
        if "[" in text_clean and "]" in text_clean:
            from src.markup.parser import parse_markup
            parse_res = parse_markup(text_clean)
            if parse_res.segments:
                chunks: list[np.ndarray] = []
                for seg in parse_res.segments:
                    # 1. Efecto de sonido Foley [sfx:...]
                    if getattr(seg, "sfx", ""):
                        chunks.append(synthesize_sfx(seg.sfx, sample_rate=base_sr))
                        continue

                    # 2. Inserción de pausa exacta en silencio digital
                    if seg.pause_s > 0:
                        chunks.append(self.generate_silence(seg.pause_s))

                    # 3. Síntesis acústica del segmento
                    seg_text = seg.text.strip()
                    if seg_text:
                        seg_text = re.sub(r"\[(?:Yo|Narrador|Personaje|Voz|Actor)[^\]]*\]", "", seg_text).strip()
                        if not seg_text:
                            continue

                        target_voice = (
                            seg.style.voice
                            if (seg.style.voice and seg.style.voice in self.available_voices)
                            else (style.voice if (style.voice and style.voice in self.available_voices) else self.current_voice_key)
                        )

                        eff_speed = style.speed * seg.style.speed
                        eff_speed = max(0.5, min(2.5, eff_speed))

                        seg_samples, seg_sr = self._generate_raw_audio(seg_text, target_voice, eff_speed)

                        if seg_sr != base_sr and len(seg_samples) > 0:
                            target_len = int(len(seg_samples) * base_sr / seg_sr)
                            seg_samples = scipy.signal.resample(seg_samples, target_len).astype(np.float32)

                        eff_gain = style.gain_db + seg.style.gain_db
                        if eff_gain != 0.0:
                            scale = 10.0 ** (eff_gain / 20.0)
                            seg_samples = seg_samples * scale
                            np.clip(seg_samples, -1.0, 1.0, out=seg_samples)

                        chunks.append(seg_samples)

                if chunks:
                    return np.concatenate(chunks)

        # Texto plano sin etiquetas (o con SFX extraídos preventivamente)
        text_no_sfx, sfx_list = extract_and_strip_sfx_tags(text_clean)
        prefix_sfx = [synthesize_sfx(s, sample_rate=base_sr) for s in sfx_list]

        if not text_no_sfx.strip():
            return np.concatenate(prefix_sfx) if prefix_sfx else np.zeros(0, dtype=np.float32)

        target_voice = style.voice if (style.voice and style.voice in self.available_voices) else self.current_voice_key
        samples, seg_sr = self._generate_raw_audio(text_no_sfx, target_voice, style.speed)

        if seg_sr != base_sr and len(samples) > 0:
            target_len = int(len(samples) * base_sr / seg_sr)
            samples = scipy.signal.resample(samples, target_len).astype(np.float32)

        if style.gain_db != 0.0:
            scale = 10.0 ** (style.gain_db / 20.0)
            samples = samples * scale
            np.clip(samples, -1.0, 1.0, out=samples)

        if prefix_sfx:
            return np.concatenate(prefix_sfx + [samples])
        return samples

    def generate_silence(self, duration_s: float) -> np.ndarray:
        """Genera un array de ceros para pausas con duración exacta."""
        if duration_s <= 0:
            return np.zeros(0, dtype=np.float32)
        num_samples = int(duration_s * self.sample_rate)
        return np.zeros(num_samples, dtype=np.float32)
