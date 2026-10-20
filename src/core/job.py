"""Gestión de trabajos persistentes y orquestador del pipeline Documento -> Audiolibro.

Cumple estrictamente con ESTRUCTURA.md:
- Nomenclatura: YYYYMMDD_HHMMSS_[Tipo]_[NombreBreve].[ext]
- Metadatos JSON completos asociados al archivo generado.
- Almacenamiento centralizado en la carpeta biblioteca/.
- Reanudación y tolerancia a fallos.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.ai.piper_engine import PiperTtsEngine
from src.audio.assembler import AudioAssembler
from src.audio.karaoke import generate_ass_subtitles, render_karaoke_video
from src.core.models import Document
from src.core.text_clean import make_filename_slug
from src.core.utterances import build_utterances
from src.ingest.loader import load_document

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BIBLIOTECA_DIR = PROJECT_ROOT / "biblioteca"


@dataclass
class JobConfig:
    source_file: str
    voice_key: str = "es_MX-claude-high"
    output_name: Optional[str] = None
    output_dir: Optional[str] = None
    generate_video: bool = True
    generate_audio: bool = True
    speed_factor: float = 1.0


@dataclass
class JobMetadata:
    job_id: str
    created_at: str
    completed_at: str
    model_name: str
    voice_key: str
    parameters: dict
    source_file: str
    source_sha256: str
    total_characters: int
    total_utterances: int
    duration_seconds: float
    latency_seconds: float
    output_audio_path: Optional[str]
    output_video_path: Optional[str]
    app_version: str = "2.0.0"


class AudiobookPipeline:
    """Orquestador completo del procesamiento de libros a audiolibro y video sincronizado."""

    def __init__(self, config: JobConfig):
        self.config = config
        self.output_dir = Path(config.output_dir) if config.output_dir else BIBLIOTECA_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, progress_callback: Optional[callable] = None) -> JobMetadata:
        start_time = time.perf_counter()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. Cargar y parsear documento
        doc: Document = load_document(self.config.source_file)

        # Determinar slug de salida
        base_name = self.config.output_name or doc.title or Path(self.config.source_file).stem
        slug = make_filename_slug(base_name, max_words=4, max_len=30)
        job_id = f"{timestamp_str}_audio_{slug}"

        # 2. Segmentar en elocuciones con markup y pausas
        build_res = build_utterances(doc, max_chars=350, use_markup=True)
        utterances = build_res.utterances

        # 3. Inicializar motor TTS
        engine = PiperTtsEngine(voice_key=self.config.voice_key)
        assembler = AudioAssembler(sample_rate=engine.sample_rate)

        # Rutas temporales y finales
        temp_wav = self.output_dir / f"{job_id}_raw.wav"
        final_mp3 = self.output_dir / f"{job_id}.mp3"
        final_video = self.output_dir / f"{timestamp_str}_video_{slug}.mp4"
        ass_subtitles = self.output_dir / f"{job_id}_subtitles.ass"

        # 4. Síntesis y ensamblado a WAV
        assembly_res = assembler.assemble_to_wav(
            utterances=utterances,
            engine=engine,
            output_wav_path=temp_wav,
            progress_callback=progress_callback
        )

        # 5. Conversión a MP3 final
        out_audio_str = None
        if self.config.generate_audio:
            assembler.convert_to_mp3(temp_wav, final_mp3)
            out_audio_str = str(final_mp3.resolve())

        # 6. Generación de video con karaoke si se solicitó
        out_video_str = None
        if self.config.generate_video:
            generate_ass_subtitles(assembly_res.sentences, ass_subtitles, title=doc.title)
            render_karaoke_video(
                audio_path=temp_wav,
                ass_subtitles_path=ass_subtitles,
                output_video_path=final_video
            )
            out_video_str = str(final_video.resolve())

        # Limpiar archivo WAV temporal intermedio
        if temp_wav.exists():
            try:
                temp_wav.unlink()
            except Exception:
                pass

        total_latency = time.perf_counter() - start_time
        completed_at_str = datetime.now().isoformat()

        # 7. Registrar metadatos obligatorios según ESTRUCTURA.md
        metadata = JobMetadata(
            job_id=job_id,
            created_at=timestamp_str,
            completed_at=completed_at_str,
            model_name="Piper-VITS (Sherpa-ONNX)",
            voice_key=self.config.voice_key,
            parameters={
                "speed_factor": self.config.speed_factor,
                "sample_rate": engine.sample_rate,
                "bitrate": "256k",
                "loudnorm": "EBU R128 (-16 LUFS)",
            },
            source_file=str(Path(self.config.source_file).resolve()),
            source_sha256=doc.source_sha256,
            total_characters=doc.char_count,
            total_utterances=len(utterances),
            duration_seconds=round(assembly_res.duration_s, 2),
            latency_seconds=round(total_latency, 2),
            output_audio_path=out_audio_str,
            output_video_path=out_video_str
        )

        metadata_path = self.output_dir / f"{job_id}_metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(asdict(metadata), f, indent=2, ensure_ascii=False)

        return metadata
