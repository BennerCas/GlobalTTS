"""Interfaz de línea de comandos (CLI) para procesar audiolibros y videos por consola."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.ai.piper_engine import list_available_piper_voices
from src.core.job import AudiobookPipeline, JobConfig


def main():
    parser = argparse.ArgumentParser(
        description="GlobalTTS — Conversor de Documentos (TXT, PDF, EPUB) a Audiolibro continuo y Video Karaoke."
    )
    parser.add_argument("file", nargs="?", default=None, help="Ruta al archivo de entrada (.txt, .pdf, .epub, .md)")
    parser.add_argument("--voice", default="es_MX-claude-high", help="Clave de voz local Piper (ej. es_MX-claude-high)")
    parser.add_argument("--name", default=None, help="Nombre del archivo de salida")
    parser.add_argument("--outdir", default=None, help="Directorio de guardado (por defecto biblioteca/)")
    parser.add_argument("--no-video", action="store_true", help="No generar video karaoke con pantalla negra")
    parser.add_argument("--no-audio", action="store_true", help="No guardar archivo MP3")
    parser.add_argument("--list-voices", action="store_true", help="Listar voces locales disponibles y salir")

    args = parser.parse_args()

    if args.list_voices:
        voices = list_available_piper_voices()
        print("\nVoces locales encontradas:")
        for k, v in voices.items():
            print(f" - {k}: {v.name} ({v.language})")
        return

    if not Path(args.file).exists():
        print(f"Error: No existe el archivo {args.file}", file=sys.stderr)
        sys.exit(1)

    config = JobConfig(
        source_file=args.file,
        voice_key=args.voice,
        output_name=args.name,
        output_dir=args.outdir,
        generate_audio=not args.no_audio,
        generate_video=not args.no_video,
    )

    print(f"\nIniciando procesamiento de '{Path(args.file).name}' con voz '{args.voice}'...")
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
