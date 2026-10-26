"""Generador de subtítulos sincronizados estilo Karaoke (ASS / SRT / VTT / LRC) y renderizado de video MP4.

Soporta:
1. Subtítulos ASS con resaltado palabra por palabra (`\\k`), metadatos de firma y 5 temas tipográficos.
2. Exportación universal de subtítulos independientes (`.srt`, `.vtt`, `.lrc`, `.ass`).
3. Relación de aspecto Horizontal (`16:9` `1920x1080` YouTube) y Vertical (`9:16` `1080x1920` Shorts/Reels/TikTok).
4. Tres modos de fondo visual en FFmpeg:
   - `black`: Pantalla negra / Obsidian de alto contraste.
   - `cover_backdrop`: Portada del libro como lienzo 1080p con ajuste de brillo.
   - `audiogram`: Espectro de onda acústica en tiempo real (`showwaves`) + portada + karaoke.
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

logger = logging.getLogger("globaltts.karaoke")

SUBTITLE_THEMES: dict[str, dict[str, str]] = {
    "cyan_ejecutivo": {
        "name": "Cian Ejecutivo (Resaltado Amarillo / Cian)",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000D0FF",
        "outline": "&H00000000",
        "wave_color": "0x06b6d4|0x38bdf8",
    },
    "amarillo_neon": {
        "name": "Amarillo Neón (Alto Contraste Shorts/Reels)",
        "primary": "&H0000EAFF",
        "secondary": "&H00D4D4D8",
        "outline": "&H00000000",
        "wave_color": "0xfacc15|0xfbbf24",
    },
    "blanco_editorial": {
        "name": "Blanco Editorial Minimalista",
        "primary": "&H00FFFFFF",
        "secondary": "&H0094A3B8",
        "outline": "&H000F172A",
        "wave_color": "0xe2e8f0|0x94a3b8",
    },
    "dorado_epico": {
        "name": "Dorado Épico (Ficción / Historia)",
        "primary": "&H0024B6FB",
        "secondary": "&H00E2E8F0",
        "outline": "&H00090D16",
        "wave_color": "0xf59e0b|0xd97706",
    },
    "verde_matrix": {
        "name": "Esmeralda Cyber (Sci-Fi / Tecnología)",
        "primary": "&H0080FF00",
        "secondary": "&H00CBD5E1",
        "outline": "&H00051005",
        "wave_color": "0x10b981|0x34d399",
    },
}

VIDEO_BACKGROUNDS: dict[str, str] = {
    "black": "Lienzo Obsidian / Negro Clásico",
    "cover_backdrop": "Portada Editorial de Fondo",
    "audiogram": "Audiograma de Espectro en Vivo (Waveform + Karaoke)",
}

ASPECT_RATIOS: dict[str, tuple[int, int, str]] = {
    "16:9": (1920, 1080, "16:9 Horizontal (YouTube / Desktop 1920x1080)"),
    "9:16": (1080, 1920, "9:16 Vertical (TikTok / Reels / Shorts 1080x1920)"),
}


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
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _format_srt_time(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    return _format_srt_time(seconds).replace(",", ".")


def _format_lrc_time(seconds: float) -> str:
    total_cs = int(round(max(0.0, seconds) * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = total_s // 60
    return f"[{m:02d}:{s:02d}.{cs:02d}]"


def calculate_word_timings(sentence: str, duration_s: float) -> tuple[TimedWord, ...]:
    """Distribuye la duración de una oración entre sus palabras proporcionalmente a su longitud silábica."""
    words = sentence.strip().split()
    if not words or duration_s <= 0:
        return ()

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
    title: str = "GlobalTTS Audiobook",
    fecha: str = "",
    hora: str = "",
    duracion: str = "",
    aspect_ratio: str = "16:9",
    theme: str = "cyan_ejecutivo",
) -> Path:
    """Genera archivo de subtítulos .ass con estilos karaoke de alta legibilidad y metadatos de firma."""
    output_ass_path = Path(output_ass_path)
    output_ass_path.parent.mkdir(parents=True, exist_ok=True)

    w, h, _ = ASPECT_RATIOS.get(aspect_ratio, ASPECT_RATIOS["16:9"])
    t_cfg = SUBTITLE_THEMES.get(theme, SUBTITLE_THEMES["cyan_ejecutivo"])
    is_vertical = h > w
    font_size = 58 if is_vertical else 56
    title_size = 66 if is_vertical else 68
    margin_h = 70 if is_vertical else 160
    margin_v = 240 if is_vertical else 120

    header = f"""; Script generated by GlobalTTS
; Firma: HUMAN AI SYNERGY BY BENNER CASTILLO
; Fecha: {fecha}
; Hora: {hora}
; Duración: {duracion}
; Copyright: HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®
[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: {w}
PlayResY: {h}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Segoe UI,{font_size},{t_cfg['primary']},{t_cfg['secondary']},{t_cfg['outline']},&H80000000,-1,0,0,0,100,100,0,0,1,3,2,5,{margin_h},{margin_h},{margin_v},1
Style: ChapterTitle,Segoe UI,{title_size},&H0000E0FF,&H00FFFFFF,{t_cfg['outline']},&H80000000,-1,0,0,0,100,100,0,0,1,4,3,5,120,120,{margin_v},1

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

        karaoke_text_parts = []
        for tw in item.words:
            clean_w = tw.word.replace("{", "(").replace("}", ")")
            karaoke_text_parts.append(f"{{\\k{tw.duration_cs}}}{clean_w}")
        text_line = " ".join(karaoke_text_parts)

        lines.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{text_line}\n")

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return output_ass_path


def export_srt_subtitles(sentences: Sequence[TimedSentence], srt_path: Path) -> Path:
    """Exporta subtítulos estándar SubRip (.srt)."""
    srt_path = Path(srt_path).with_suffix(".srt")
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = []
    for idx, item in enumerate(sentences, start=1):
        blocks.append(f"{idx}\n{_format_srt_time(item.start_s)} --> {_format_srt_time(item.end_s)}\n{item.sentence.strip()}\n")
    srt_path.write_text("\n".join(blocks), encoding="utf-8")
    return srt_path


def export_vtt_subtitles(sentences: Sequence[TimedSentence], vtt_path: Path) -> Path:
    """Exporta subtítulos estándar WebVTT (.vtt)."""
    vtt_path = Path(vtt_path).with_suffix(".vtt")
    vtt_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["WEBVTT", ""]
    for idx, item in enumerate(sentences, start=1):
        lines.append(f"{idx}")
        lines.append(f"{_format_vtt_time(item.start_s)} --> {_format_vtt_time(item.end_s)}")
        lines.append(item.sentence.strip())
        lines.append("")
    vtt_path.write_text("\n".join(lines), encoding="utf-8")
    return vtt_path


def export_lrc_subtitles(sentences: Sequence[TimedSentence], lrc_path: Path, title: str = "Audiolibro") -> Path:
    """Exporta letras sincronizadas (.lrc)."""
    lrc_path = Path(lrc_path).with_suffix(".lrc")
    lrc_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [f"[ti:{title}]", "[by:HUMAN AI SYNERGY BY BENNER CASTILLO]", ""]
    for item in sentences:
        lines.append(f"{_format_lrc_time(item.start_s)}{item.sentence.strip()}")
    lrc_path.write_text("\n".join(lines), encoding="utf-8")
    return lrc_path


def export_all_subtitle_formats(
    sentences: Sequence[TimedSentence],
    base_dir: Path,
    base_prefix: str = "subtitles",
    title: str = "Audiolibro",
) -> dict[str, Path]:
    """Exporta .srt, .vtt y .lrc junto al archivo .ass en la carpeta del libro."""
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    return {
        "srt": export_srt_subtitles(sentences, base_dir / f"{base_prefix}.srt"),
        "vtt": export_vtt_subtitles(sentences, base_dir / f"{base_prefix}.vtt"),
        "lrc": export_lrc_subtitles(sentences, base_dir / f"{base_prefix}.lrc", title=title),
    }


def render_karaoke_video(
    audio_path: Path,
    ass_subtitles_path: Path,
    output_video_path: Path,
    cover_image_path: Optional[Path] = None,
    ffmpeg_exe: str = "ffmpeg",
    title: str = "",
    artist: str = "HUMAN AI SYNERGY BY BENNER CASTILLO",
    comment: str = "",
    date: str = "",
    aspect_ratio: str = "16:9",
    background_mode: str = "black",
    subtitle_theme: str = "cyan_ejecutivo",
) -> Path:
    """Renderiza video MP4 (16:9 o 9:16, pantalla negra, portada o audiograma de espectro) con subtítulos ASS incrustados."""
    if not shutil.which(ffmpeg_exe):
        raise RuntimeError("ffmpeg no se encuentra en el PATH del sistema.")

    output_video_path = Path(output_video_path)
    output_video_path.parent.mkdir(parents=True, exist_ok=True)

    w, h, _ = ASPECT_RATIOS.get(aspect_ratio, ASPECT_RATIOS["16:9"])
    t_cfg = SUBTITLE_THEMES.get(subtitle_theme, SUBTITLE_THEMES["cyan_ejecutivo"])
    ass_escaped = str(ass_subtitles_path.resolve()).replace("\\", "/").replace(":", "\\:")

    cmd = [ffmpeg_exe, "-y"]
    has_cover = cover_image_path is not None and Path(cover_image_path).exists()

    if background_mode == "audiogram":
        wave_h = 220 if h > w else 180
        wave_y = int(h * 0.72) if h > w else int(h * 0.76)
        wave_colors = t_cfg["wave_color"]
        if has_cover:
            filter_complex = (
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=#0B0F19,eq=brightness=-0.22[bg];"
                f"[1:a]showwaves=s={w}x{wave_h}:mode=cline:rate=24:colors={wave_colors}[sw];"
                f"[bg][sw]overlay=0:{wave_y}:shortest=1[v1];"
                f"[v1]ass='{ass_escaped}'[v]"
            )
            cmd.extend([
                "-loop", "1",
                "-i", str(cover_image_path),
                "-i", str(audio_path),
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "1:a",
            ])
        else:
            filter_complex = (
                f"color=c=#0B0F19:s={w}x{h}:r=24[bg];"
                f"[0:a]showwaves=s={w}x{wave_h}:mode=cline:rate=24:colors={wave_colors}[sw];"
                f"[bg][sw]overlay=0:{wave_y}:shortest=1[v1];"
                f"[v1]ass='{ass_escaped}'[v]"
            )
            cmd.extend([
                "-i", str(audio_path),
                "-filter_complex", filter_complex,
                "-map", "[v]",
                "-map", "0:a",
            ])
        cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])

    elif has_cover and background_mode == "cover_backdrop":
        # Portada como fondo 1080p/Vertical con sutil oscurecimiento para legibilidad
        cmd.extend([
            "-loop", "1",
            "-i", str(cover_image_path),
            "-i", str(audio_path),
            "-filter_complex",
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,eq=brightness=-0.15[bg];[bg]ass='{ass_escaped}'[v]",
            "-map", "[v]",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "stillimage",
            "-crf", "20",
        ])
    else:
        # Pantalla negra clásica 1080p o Vertical 9:16
        cmd.extend([
            "-f", "lavfi",
            "-i", f"color=c=black:s={w}x{h}:r=24",
            "-i", str(audio_path),
            "-vf", f"ass='{ass_escaped}'",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "stillimage",
            "-crf", "20",
        ])

    cmd.extend([
        "-c:a", "aac",
        "-b:a", "256k",
        "-pix_fmt", "yuv420p",
        "-metadata", f"artist={artist}",
        "-metadata", f"album_artist={artist}",
        "-metadata", f"copyright={artist} - 2026®",
        "-shortest",
    ])

    if title:
        cmd.extend(["-metadata", f"title={title}"])
    if date:
        cmd.extend(["-metadata", f"date={date}"])
    if comment:
        cmd.extend(["-metadata", f"comment={comment}"])

    cmd.append(str(output_video_path))

    creationflags = 0x08000000 if sys.platform == "win32" else 0
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=creationflags)

    if output_video_path.exists() and output_video_path.stat().st_size > 1000:
        return output_video_path

    if result.returncode != 0:
        raise RuntimeError(f"Fallo al renderizar video con ffmpeg:\n{result.stderr[-800:]}")

    return output_video_path
