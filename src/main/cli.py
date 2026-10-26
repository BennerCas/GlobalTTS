"""Interfaz de línea de comandos (CLI) para procesar audiolibros y videos por consola."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ai.nemo_enhancer import NarrationConfig
from src.ai.piper_engine import list_available_piper_voices
from src.core.job import AudiobookPipeline, JobConfig


def main():
    parser = argparse.ArgumentParser(
        description="GlobalTTS — Conversor de Documentos (TXT, PDF, EPUB, Imágenes OCR y URLs Web) a Audiolibro M4B/MP3 y Video Karaoke."
    )
    parser.add_argument("file", nargs="?", default=None, help="Ruta al archivo de entrada (.txt, .pdf, .epub, .md, .png, .jpg) o URL web (https://...)")
    parser.add_argument("--voice", default="kokoro-ef_dora", help="Clave de voz local Kokoro/Clonada/Piper (ej. kokoro-ef_dora)")
    parser.add_argument("--name", default=None, help="Nombre del archivo de salida")
    parser.add_argument("--outdir", default=None, help="Directorio de guardado (por defecto biblioteca/)")
    parser.add_argument("--no-video", action="store_true", help="No generar video karaoke MP4")
    parser.add_argument("--no-audio", action="store_true", help="No guardar archivo MP3")
    parser.add_argument("--m4b", action="store_true", help="Exportar audiolibro nativo .M4B con índice de capítulos")
    parser.add_argument("--epub3", action="store_true", help="Exportar libro electrónico sincronizado EPUB3 Read-Aloud (SMIL)")
    parser.add_argument("--split-chapters", action="store_true", help="Exportar pistas MP3 individuales por capítulo")
    parser.add_argument("--trailer", action="store_true", help="Generar Audio-Trailer promocional de 90 segundos")
    parser.add_argument("--cover-ai", action="store_true", help="Generar portada editorial 1024x1024 con IA local")
    parser.add_argument("--style", default="cuento", help="Estilo narrativo (cuento, locutor_radio, terror, epico, etc.)")
    parser.add_argument("--soundscape", default="none", help="Paisaje sonoro con Auto-Ducking (none, rain_cafe, fireplace, mystery_thriller, etc.)")
    parser.add_argument("--aspect-ratio", default="16:9", choices=["16:9", "9:16"], help="Relación de aspecto del video karaoke (16:9 o 9:16)")
    parser.add_argument("--video-bg", default="audiogram", choices=["black", "cover_backdrop", "audiogram"], help="Fondo visual del video karaoke")
    parser.add_argument("--sfx", action="store_true", help="Activar inyección semántica de efectos Foley SFX")
    parser.add_argument("--no-dsp", action="store_true", help="Desactivar cadena de masterización DSP (-1.0 dBTP)")
    parser.add_argument("--list-voices", action="store_true", help="Listar voces locales disponibles y salir")

    args = parser.parse_args()

    if args.list_voices:
        voices = list_available_piper_voices()
        print("\nVoces locales encontradas:")
        for k, v in voices.items():
            print(f" - {k}: {v.name} ({v.language} | {v.engine} {v.sample_rate}Hz)")
        return

    if not args.file:
        parser.print_help()
        sys.exit(1)

    is_url = str(args.file).startswith(("http://", "https://"))
    if not is_url and not Path(args.file).exists():
        print(f"Error: No existe el archivo {args.file}", file=sys.stderr)
        sys.exit(1)

    config = JobConfig(
        source_file=args.file,
        voice_key=args.voice,
        output_name=args.name,
        output_dir=args.outdir,
        generate_audio=not args.no_audio,
        generate_video=not args.no_video,
        export_m4b=args.m4b,
        export_epub3=args.epub3,
        split_chapters=args.split_chapters,
        generate_trailer=args.trailer,
        generate_cover_ai=args.cover_ai,
        soundscape_preset=args.soundscape,
        video_aspect_ratio=args.aspect_ratio,
        video_background=args.video_bg,
        auto_sfx=args.sfx,
        dsp_mastering=not args.no_dsp,
        narration=NarrationConfig(enabled=False, style=args.style),
    )

    src_disp = args.file if is_url else Path(args.file).name
    print(f"\nIniciando procesamiento de '{src_disp}' con voz '{args.voice}' (estilo '{args.style}')...")
    pipeline = AudiobookPipeline(config)

    def progress(cur, total, utt):
        pct = int((cur / total) * 100)
        sys.stdout.write(f"\rProgreso: [{pct:3d}%] ({cur}/{total})")
        sys.stdout.flush()

    meta = pipeline.run(progress_callback=progress)
    print(f"\n\nProceso finalizado con éxito en {meta.latency_seconds:.1f}s.")
    print(f"Duración del audiolibro: {meta.duration_seconds:.1f}s")
    if meta.output_audio_path:
        print(f"Audio generado: {meta.output_audio_path}")
    if meta.output_video_path:
        print(f"Video generado: {meta.output_video_path}")


if __name__ == "__main__":
    main()
