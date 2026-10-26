"""Ensamblador de audio en streaming continuo, Masterización DSP, Soundscape Ducking y Exportación M4B/Capítulos.

Escribe fragmentos de audio progresivamente a disco sin acumular gigabytes en memoria RAM,
aplica opcionalmente la cadena de Masterización de Estudio DSP (-1.0 dBTP, De-Esser, Compresor),
mezcla paisajes sonoros estéreo con Audio Ducking dinámico, exporta audiolibros `.m4b` con
índice de capítulos navegables y divide pistas individuales por capítulo.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import soundfile as sf

from src.ai.piper_engine import PiperTtsEngine
from src.audio.dsp_mastering import MasteringConfig, master_audio_track
from src.audio.karaoke import TimedSentence, calculate_word_timings
from src.audio.soundscape import mix_voice_with_soundscape
from src.core.utterances import Utterance

logger = logging.getLogger("globaltts.assembler")


@dataclass(frozen=True)
class ChapterTiming:
    """Marcador temporal exacto de un capítulo en milisegundos (para contenedores M4B y corte de pistas)."""
    index: int
    title: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class AssemblyResult:
    audio_path: Path
    duration_s: float
    sample_rate: int
    sentences: tuple[TimedSentence, ...]


def compute_chapter_timings(
    sentences: Sequence[TimedSentence],
    total_duration_s: float,
    chapter_titles: Optional[list[str]] = None,
) -> list[ChapterTiming]:
    """Calcula los tiempos de inicio y fin (en ms) de cada capítulo a partir de las oraciones sincronizadas."""
    if not sentences:
        return []

    by_chapter: dict[int, list[TimedSentence]] = {}
    for seg in sentences:
        if seg.chapter_index < 0:
            continue
        by_chapter.setdefault(seg.chapter_index, []).append(seg)

    if not by_chapter:
        by_chapter[0] = list(sentences)

    sorted_indices = sorted(by_chapter.keys())
    timings: list[ChapterTiming] = []

    for i, ch_idx in enumerate(sorted_indices):
        segs = by_chapter[ch_idx]
        start_s = segs[0].start_s if i > 0 else 0.0
        if i + 1 < len(sorted_indices):
            next_segs = by_chapter[sorted_indices[i + 1]]
            end_s = next_segs[0].start_s
        else:
            end_s = max(total_duration_s, segs[-1].end_s)

        title = ""
        if chapter_titles and 0 <= ch_idx < len(chapter_titles):
            title = chapter_titles[ch_idx]
        if not title:
            title_seg = next((s for s in segs if s.is_title), None)
            title = title_seg.sentence if title_seg else f"Capítulo {ch_idx + 1}"

        start_ms = max(0, int(round(start_s * 1000)))
        end_ms = max(start_ms + 500, int(round(end_s * 1000)))
        timings.append(ChapterTiming(index=ch_idx, title=title, start_ms=start_ms, end_ms=end_ms))

    return timings


def _escape_ffmetadata(val: str) -> str:
    return (
        val.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("\n", " ")
    )


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
        pause_event: Optional[object] = None,
        dsp_mastering: bool = True,
        soundscape_preset: str = "none",
        custom_bgm_path: Optional[Path] = None,
    ) -> AssemblyResult:
        """Sintetiza y escribe progresivamente las elocuciones a un archivo WAV aplicando DSP por bloque."""
        output_wav_path = Path(output_wav_path)
        output_wav_path.parent.mkdir(parents=True, exist_ok=True)

        timed_sentences: list[TimedSentence] = []
        current_time_s = 0.0
        master_cfg = MasteringConfig(enabled=dsp_mastering)

        with sf.SoundFile(
            str(output_wav_path),
            mode="w",
            samplerate=self.sample_rate,
            channels=1,
            subtype="PCM_16",
        ) as wav_file:

            total = len(utterances)
            for idx, utt in enumerate(utterances):
                if pause_event is not None and hasattr(pause_event, "wait"):
                    pause_event.wait()

                # 1. Sintetizar texto (si no está vacío)
                if utt.text.strip():
                    audio_chunk = engine.synthesize(utt.text, utt.style)
                    if dsp_mastering and len(audio_chunk) > 128:
                        audio_chunk = master_audio_track(audio_chunk, self.sample_rate, config=master_cfg)

                    chunk_dur_s = len(audio_chunk) / self.sample_rate
                    start_s = current_time_s
                    end_s = current_time_s + chunk_dur_s

                    if len(audio_chunk) > 0:
                        wav_file.write(audio_chunk)
                        current_time_s += chunk_dur_s

                    is_pure_sfx = utt.text.strip().lower().startswith("[sfx:") and utt.text.strip().endswith("]")
                    if not is_pure_sfx:
                        clean_sub_txt = re.sub(
                            r"\[\s*/?\s*[A-Za-zÁÉÍÓÚáéíóúÑñ0-9_]+(?:\s*:[^\[\]]*)?\s*\]",
                            "",
                            utt.text,
                            flags=re.IGNORECASE,
                        )
                        clean_sub_txt = re.sub(r"\s{2,}", " ", clean_sub_txt).strip()
                        if clean_sub_txt:
                            words = calculate_word_timings(clean_sub_txt, chunk_dur_s)
                            timed_sentences.append(
                                TimedSentence(
                                    sentence=clean_sub_txt,
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

        # Si se seleccionó música ambiental / paisaje sonoro con Audio Ducking, mezclar en estéreo
        if (soundscape_preset and soundscape_preset != "none") or (custom_bgm_path and Path(custom_bgm_path).exists()):
            try:
                voice_data, sr = sf.read(str(output_wav_path), dtype="float32")
                mixed_stereo = mix_voice_with_soundscape(
                    voice_samples=voice_data,
                    sample_rate=sr,
                    preset=soundscape_preset,
                    custom_bgm_path=Path(custom_bgm_path) if custom_bgm_path else None,
                )
                sf.write(str(output_wav_path), mixed_stereo, sr, subtype="PCM_16")
            except Exception as exc:
                logger.warning("Aviso mezclando paisaje sonoro en WAV: %s", exc)

        return AssemblyResult(
            audio_path=output_wav_path,
            duration_s=current_time_s,
            sample_rate=self.sample_rate,
            sentences=tuple(timed_sentences),
        )

    @staticmethod
    def convert_to_mp3(
        wav_path: Path,
        output_mp3_path: Path,
        bitrate: str = "256k",
        cover_image_path: Optional[Path] = None,
        title: str = "",
        artist: str = "HUMAN AI SYNERGY BY BENNER CASTILLO",
        comment: str = "",
        date: str = "",
    ) -> Path:
        """Convierte WAV a MP3 usando ffmpeg con normalización loudnorm, portada y metadatos ID3 completos."""
        output_mp3_path = Path(output_mp3_path)
        output_mp3_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(wav_path),
        ]

        if cover_image_path and Path(cover_image_path).exists():
            cmd.extend([
                "-i", str(cover_image_path),
                "-map", "0:a",
                "-map", "1:v",
                "-c:v", "copy",
                "-id3v2_version", "3",
                "-metadata:s:v", "title=Album cover",
                "-metadata:s:v", "comment=Cover (front)",
            ])

        cmd.extend([
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-codec:a", "libmp3lame",
            "-b:a", bitrate,
            "-metadata", f"artist={artist}",
            "-metadata", f"album_artist={artist}",
            "-metadata", f"composer={artist}",
            "-metadata", f"publisher={artist}",
            "-metadata", f"copyright={artist} - 2026®",
        ])

        if title:
            cmd.extend(["-metadata", f"title={title}"])
        if date:
            cmd.extend(["-metadata", f"date={date}"])
        if comment:
            cmd.extend(["-metadata", f"comment={comment}"])

        cmd.append(str(output_mp3_path))

        creationflags = 0x08000000 if sys.platform == "win32" else 0

        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )

        if output_mp3_path.exists() and output_mp3_path.stat().st_size > 1000:
            return output_mp3_path

        if res.returncode != 0:
            raise RuntimeError(f"Fallo al convertir audio a MP3 con ffmpeg: {res.stderr[-500:]}")

        return output_mp3_path

    @staticmethod
    def export_m4b(
        source_wav_or_mp3: Path,
        output_m4b_path: Path,
        title: str,
        artist: str = "HUMAN AI SYNERGY BY BENNER CASTILLO",
        chapters: Optional[list[ChapterTiming]] = None,
        cover_image_path: Optional[Path] = None,
        bitrate: str = "192k",
    ) -> Optional[Path]:
        """Empaqueta el audiolibro en formato estándar `.m4b` (AAC) con índice de capítulos y portada."""
        if not shutil.which("ffmpeg") or not Path(source_wav_or_mp3).exists():
            return None

        output_m4b_path = Path(output_m4b_path).with_suffix(".m4b")
        output_m4b_path.parent.mkdir(parents=True, exist_ok=True)
        meta_file = output_m4b_path.with_suffix(".ffmetadata.txt")

        lines = [
            ";FFMETADATA1",
            f"title={_escape_ffmetadata(title or 'Audiolibro')}",
            f"artist={_escape_ffmetadata(artist)}",
            f"album_artist={_escape_ffmetadata(artist)}",
            f"album={_escape_ffmetadata(title or 'Audiolibro')}",
            f"copyright={_escape_ffmetadata(artist)} - 2026®",
            "genre=Audiobook",
            "",
        ]
        for ch in chapters or []:
            lines.extend([
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={ch.start_ms}",
                f"END={ch.end_ms}",
                f"title={_escape_ffmetadata(ch.title)}",
                "",
            ])

        meta_file.write_text("\n".join(lines), encoding="utf-8")
        creationflags = 0x08000000 if sys.platform == "win32" else 0

        try:
            has_cover = cover_image_path is not None and Path(cover_image_path).exists()
            cmd = ["ffmpeg", "-y", "-i", str(source_wav_or_mp3), "-i", str(meta_file)]
            if has_cover:
                cmd.extend(["-i", str(cover_image_path)])

            cmd.extend(["-map", "0:a", "-map_metadata", "1", "-c:a", "aac", "-b:a", bitrate])
            if has_cover:
                cmd.extend(["-map", "2:v", "-c:v", "png", "-disposition:v:0", "attached_pic"])

            cmd.extend(["-movflags", "+faststart", str(output_m4b_path)])
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
            return output_m4b_path
        except Exception as exc:
            logger.warning("Aviso al exportar M4B: %s", exc)
            return None
        finally:
            meta_file.unlink(missing_ok=True)

    @staticmethod
    def export_split_chapters_from_wav(
        wav_path: Path,
        chapters: list[ChapterTiming],
        output_dir: Path,
        cover_image_path: Optional[Path] = None,
        artist: str = "HUMAN AI SYNERGY BY BENNER CASTILLO",
    ) -> list[Path]:
        """Divide el WAV maestro en archivos MP3 individuales numerados por capítulo."""
        if not Path(wav_path).exists() or not chapters or not shutil.which("ffmpeg"):
            return []

        ch_dir = Path(output_dir) / "capitulos"
        ch_dir.mkdir(parents=True, exist_ok=True)
        exported: list[Path] = []
        creationflags = 0x08000000 if sys.platform == "win32" else 0

        for idx, ch in enumerate(chapters, start=1):
            start_s = ch.start_ms / 1000.0
            dur_s = max(0.5, (ch.end_ms - ch.start_ms) / 1000.0)
            safe_title = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ_-]+", "_", ch.title).strip("_")[:45] or f"Capitulo_{idx}"
            out_mp3 = ch_dir / f"{idx:02d}_{safe_title}.mp3"

            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start_s:.3f}",
                "-t", f"{dur_s:.3f}",
                "-i", str(wav_path),
            ]
            if cover_image_path and Path(cover_image_path).exists():
                cmd.extend([
                    "-i", str(cover_image_path),
                    "-map", "0:a", "-map", "1:v", "-c:v", "copy", "-id3v2_version", "3",
                ])
            cmd.extend([
                "-codec:a", "libmp3lame",
                "-b:a", "192k",
                "-metadata", f"title={ch.title}",
                "-metadata", f"artist={artist}",
                "-metadata", f"track={idx}/{len(chapters)}",
                str(out_mp3),
            ])
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
                if out_mp3.exists():
                    exported.append(out_mp3)
            except Exception as exc:
                logger.warning("Aviso exportando capítulo %d: %s", idx, exc)

        return exported
