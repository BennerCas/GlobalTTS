"""Generador de subtítulos sincronizados estilo Karaoke (ASS) y renderizado de video MP4.

Crea un archivo de video en pantalla negra (1920x1080) con el texto resaltándose
palabra por palabra en tiempo real, sincronizado exactamente con la narración.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class TimedWord:
    word: str
    duration_cs: int  # duración en centésimas de segundo (para tag \k de ASS)


@dataclass(frozen=True)
class TimedSentence:
    sentence: str
    start_s: float
    end_s: float
    words: tuple[TimedWord, ...]
    chapter_index: int
    is_title: bool = False


def _format_ass_time(seconds: float) -> str:
    """Convierte segundos a formato ASS: H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def calculate_word_timings(sentence: str, duration_s: float) -> tuple[TimedWord, ...]:
    """Distribuye la duración de una oración entre sus palabras proporcionalmente a su longitud silábica."""
    words = sentence.strip().split()
    if not words or duration_s <= 0:
        return ()

    # Heurística de peso: longitud de caracteres (mínimo 1)
    weights = [max(1, len(re.sub(r"[^\w]", "", w))) for w in words]
    total_weight = sum(weights)

    total_cs = int(round(duration_s * 100))
    assigned_cs = []
    current_assigned = 0

    for i, w in enumerate(weights):
        if i == len(weights) - 1:
            part = max(1, total_cs - current_assigned)
        else:
            part = max(1, int(round((w / total_weight) * total_cs)))
        assigned_cs.append(part)
        current_assigned += part

    return tuple(TimedWord(word=w, duration_cs=cs) for w, cs in zip(words, assigned_cs))


def generate_ass_subtitles(
    sentences: Sequence[TimedSentence],
    output_ass_path: Path,
    title: str = "GlobalTTS Audiobook"
) -> Path:
    """Genera archivo de subtítulos .ass con estilos karaoke de alta legibilidad."""
    output_ass_path = Path(output_ass_path)
    output_ass_path.parent.mkdir(parents=True, exist_ok=True)

    header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Segoe UI,56,&H00FFFFFF,&H0000D0FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,5,160,160,120,1
Style: ChapterTitle,Segoe UI,68,&H0000E0FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,3,5,120,120,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]

    for item in sentences:
        start_str = _format_ass_time(item.start_s)
        end_str = _format_ass_time(item.end_s)
        style_name = "ChapterTitle" if item.is_title else "Default"

        if not item.words:
            continue

        # Construir línea de diálogo con tags karaoke {\k<centésimas>}
        karaoke_text_parts = []
        for tw in item.words:
            karaoke_text_parts.append(f"{{\\k{tw.duration_cs}}}{tw.word}")
        text_line = " ".join(karaoke_text_parts)

        lines.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{text_line}\n")

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return output_ass_path


def render_karaoke_video(
    audio_path: Path,
    ass_subtitles_path: Path,
    output_video_path: Path,
    ffmpeg_exe: str = "ffmpeg"
) -> Path:
    """Renderiza video MP4 con pantalla negra 1080p, audio intacto y subtítulos ASS incrustados."""
    if not shutil.which(ffmpeg_exe):
        raise RuntimeError("ffmpeg no se encuentra en el PATH del sistema.")

    output_video_path = Path(output_video_path)
    output_video_path.parent.mkdir(parents=True, exist_ok=True)

    # Escapar ruta para el filtro ass en Windows (barras invertidas dobladas y dos puntos escapados)
    ass_escaped = str(ass_subtitles_path.resolve()).replace("\\", "/").replace(":", "\\:")

    cmd = [
        ffmpeg_exe,
        "-y",
        "-f", "lavfi",
        "-i", "color=c=black:s=1920x1080:r=24",
        "-i", str(audio_path),
        "-vf", f"ass='{ass_escaped}'",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "stillimage",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "256k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(output_video_path)
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Fallo al renderizar video con ffmpeg:\n{result.stderr[-800:]}")

    return output_video_path
