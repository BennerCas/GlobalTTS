"""Ensamblador de audio en streaming continuo.

Escribe fragmentos de audio progresivamente a disco sin acumular gigabytes
en memoria RAM. Normaliza volumen y retorna los tiempos exactos de cada oración.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional, Sequence

import numpy as np
import soundfile as sf

from src.ai.piper_engine import PiperTtsEngine
from src.audio.karaoke import TimedSentence, calculate_word_timings
from src.core.utterances import Utterance


@dataclass(frozen=True)
class AssemblyResult:
    audio_path: Path
    duration_s: float
    sample_rate: int
    sentences: tuple[TimedSentence, ...]


class AudioAssembler:
    """Ensambla elocuciones en un archivo continuo de audio de alta fidelidad."""

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate

    def assemble_to_wav(
        self,
        utterances: Sequence[Utterance],
        engine: PiperTtsEngine,
        output_wav_path: Path,
        progress_callback: Optional[callable] = None,
    ) -> AssemblyResult:
        """Sintetiza y escribe progresivamente las elocuciones a un archivo WAV sin saturar memoria."""
        output_wav_path = Path(output_wav_path)
        output_wav_path.parent.mkdir(parents=True, exist_ok=True)

        timed_sentences: list[TimedSentence] = []
        current_time_s = 0.0

        with sf.SoundFile(
            str(output_wav_path),
            mode="w",
            samplerate=self.sample_rate,
            channels=1,
            subtype="PCM_16"
        ) as wav_file:

            total = len(utterances)
            for idx, utt in enumerate(utterances):
                # 1. Sintetizar texto (si no está vacío)
                if utt.text.strip():
                    audio_chunk = engine.synthesize(utt.text, utt.style)
                    chunk_dur_s = len(audio_chunk) / self.sample_rate
                    start_s = current_time_s
                    end_s = current_time_s + chunk_dur_s

                    if len(audio_chunk) > 0:
                        wav_file.write(audio_chunk)
                        current_time_s += chunk_dur_s

                    # Registrar timings para karaoke / subtítulos
                    words = calculate_word_timings(utt.text, chunk_dur_s)
                    timed_sentences.append(
                        TimedSentence(
                            sentence=utt.text,
                            start_s=start_s,
                            end_s=end_s,
                            words=words,
                            chapter_index=utt.chapter_index,
                            is_title=utt.is_title,
                        )
                    )

                # 2. Silencio posterior (pausa entre oraciones, párrafos o capítulos)
                if utt.pause_after > 0:
                    silence_chunk = engine.generate_silence(utt.pause_after)
                    if len(silence_chunk) > 0:
                        wav_file.write(silence_chunk)
                        current_time_s += utt.pause_after

                if progress_callback:
                    progress_callback(idx + 1, total, utt)

        return AssemblyResult(
            audio_path=output_wav_path,
            duration_s=current_time_s,
            sample_rate=self.sample_rate,
            sentences=tuple(timed_sentences)
        )

    @staticmethod
    def convert_to_mp3(wav_path: Path, output_mp3_path: Path, bitrate: str = "256k") -> Path:
        """Convierte WAV a MP3 usando ffmpeg con normalización loudnorm."""
        output_mp3_path = Path(output_mp3_path)
        output_mp3_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(wav_path),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-codec:a", "libmp3lame",
            "-b:a", bitrate,
            str(output_mp3_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Fallo al convertir audio a MP3 con ffmpeg: {res.stderr[-500:]}")

        return output_mp3_path
