"""Gestión de trabajos persistentes y orquestador del pipeline Documento -> Audiolibro.

Cumple estrictamente con ESTRUCTURA.md:
- Almacena cada documento procesado en su propia carpeta: biblioteca/<NombreDocumento>/
- Guarda master sin pérdida (FLAC/WAV) y versión MP3 normalizada a 256k con portada.
- Genera video karaoke MP4 (pantalla negra o fondo de portada).
- Soporta enriquecimiento expresivo y modo narrador con Mistral NeMo local.
- Soporta cuñas de audio / separadores entre capítulos y auto-casting multi-voz.
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.ai.nemo_enhancer import MistralNeMoEnhancer, NarrationConfig
from src.ai.piper_engine import PiperTtsEngine
from src.audio.assembler import AudioAssembler
from src.audio.karaoke import generate_ass_subtitles, render_karaoke_video
from src.core.models import Chapter, Document
from src.core.text_clean import make_filename_slug
from src.core.utterances import Utterance, build_utterances
from src.markup.style import Style
from src.ingest.loader import load_document

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BIBLIOTECA_DIR = PROJECT_ROOT / "biblioteca"


@dataclass
class InterstitialItem:
    text: str
    voice_key: Optional[str] = None
    position: str = "between_chapters"  # "start", "between_chapters", "end"
    pause_after: float = 1.0


@dataclass
class JobConfig:
    source_file: str
    voice_key: str = "es_MX-claude-high"
    secondary_voice_key: Optional[str] = "es_ES-sharvard-medium"
    multi_voice_mode: str = "single"  # "single", "manual", "dialogue_auto"
    output_name: Optional[str] = None
    output_dir: Optional[str] = None
    cover_image_path: Optional[str] = None
    generate_video: bool = True
    generate_audio: bool = True
    save_flac_master: bool = True
    speed_factor: float = 1.0
    narration: Optional[NarrationConfig] = None
    interstitials: list[InterstitialItem] = field(default_factory=list)


@dataclass
class JobMetadata:
    job_id: str
    document_folder: str
    created_at: str
    completed_at: str
    model_name: str
    voice_key: str
    secondary_voice_key: Optional[str]
    parameters: dict
    source_file: str
    source_sha256: str
    total_characters: int
    total_utterances: int
    duration_seconds: float
    latency_seconds: float
    output_audio_path: Optional[str]
    output_video_path: Optional[str]
    output_master_path: Optional[str]
    cover_image_path: Optional[str]
    firma: str = "HUMAN AI SYNERGY BY BENNER CASTILLO"
    fecha: str = ""
    hora: str = ""
    duracion_formato: str = ""
    archivos_generados: dict = field(default_factory=dict)
    app_version: str = "2.2.0"


class AudiobookPipeline:
    """Orquestador completo del procesamiento de libros a audiolibro y video sincronizado."""

    def __init__(self, config: JobConfig):
        self.config = config
        self.base_output_dir = Path(config.output_dir) if config.output_dir else BIBLIOTECA_DIR
        self.base_output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        progress_callback: Optional[callable] = None,
        stage_callback: Optional[callable] = None
    ) -> JobMetadata:
        start_time = time.perf_counter()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        def emit_stage(stage: str, desc: str, pct: float):
            if stage_callback:
                stage_callback(stage, desc, pct)

        # 1. Ingesta del documento
        emit_stage("ingest", "Analizando documento y extrayendo capítulos...", 2.0)
        doc: Document = load_document(self.config.source_file)

        # 2. Carpeta dedicada en biblioteca/ para este libro
        base_name = self.config.output_name or doc.title or Path(self.config.source_file).stem
        slug = make_filename_slug(base_name, max_words=5, max_len=45)

        book_folder = self.base_output_dir / slug
        book_folder.mkdir(parents=True, exist_ok=True)

        job_id = f"{timestamp_str}_audio_{slug}"

        # 3. Portada si existe
        copied_cover_path: Optional[Path] = None
        if self.config.cover_image_path and Path(self.config.cover_image_path).exists():
            orig_cover = Path(self.config.cover_image_path)
            copied_cover_path = book_folder / f"cover{orig_cover.suffix}"
            try:
                shutil.copy2(orig_cover, copied_cover_path)
            except Exception:
                copied_cover_path = orig_cover

        # 4. Modo Narración / Enriquecimiento con Mistral NeMo si está habilitado
        if self.config.narration and self.config.narration.enabled:
            emit_stage("ai_analysis", "Analizando con Mistral NeMo (narración / expresividad)...", 5.0)
            enhancer = MistralNeMoEnhancer()
            if enhancer.is_available():
                new_chapters = []
                for ch in doc.chapters:
                    new_paragraphs = []
                    for par in ch.paragraphs:
                        if self.config.narration.mode == "rewrite":
                            processed = enhancer.rewrite_as_narration(par, self.config.narration)
                        elif self.config.narration.mode == "translate":
                            processed = enhancer.translate_and_adapt(
                                par,
                                target_lang=self.config.narration.target_language,
                                prompt_id=self.config.narration.prompt_id,
                            )
                        elif self.config.narration.mode == "dialogue_analysis":
                            analysis = enhancer.analyze_dialogues(par, prompt_id=self.config.narration.prompt_id)
                            seg_texts = []
                            for seg in analysis.get("segments", []):
                                stext = seg.get("text", "")
                                emotion = seg.get("emotion")
                                if emotion and emotion not in ("neutral", ""):
                                    stext = f"[{emotion}]{stext}[/{emotion}]"
                                seg_texts.append(stext)
                            processed = " ".join(seg_texts) if seg_texts else par
                        else:
                            processed = enhancer.enhance_expressiveness(par, prompt_id=self.config.narration.prompt_id)
                        new_paragraphs.append(processed)
                    new_chapters.append(Chapter(title=ch.title, paragraphs=tuple(new_paragraphs)))
                doc = Document(
                    title=doc.title,
                    author=doc.author,
                    language=doc.language,
                    chapters=tuple(new_chapters),
                    source_path=doc.source_path,
                    source_sha256=doc.source_sha256,
                )

        # 5. Segmentación en elocuciones
        emit_stage("markup", "Estructurando oraciones y etiquetas de voz...", 8.0)
        build_res = build_utterances(doc, max_chars=350, use_markup=True)
        raw_utterances = list(build_res.utterances)

        # 6. Auto-casting Multi-voz (si está habilitado)
        if self.config.multi_voice_mode == "dialogue_auto" and self.config.secondary_voice_key:
            emit_stage("autocast", "Aplicando auto-casting de voces en diálogos...", 9.0)
            dialogue_chars = ('"', "«", "“", "—", "- ")
            processed_utts = []
            for utt in raw_utterances:
                text_stripped = utt.text.strip()
                if any(text_stripped.startswith(dc) for dc in dialogue_chars) and not utt.style.voice:
                    new_style = Style(
                        speed=utt.style.speed,
                        gain_db=utt.style.gain_db,
                        voice=self.config.secondary_voice_key,
                        instruct=utt.style.instruct
                    )
                    processed_utts.append(
                        Utterance(utt.text, new_style, utt.pause_after, utt.chapter_index, utt.paragraph_index, utt.is_title)
                    )
                else:
                    processed_utts.append(utt)
            raw_utterances = processed_utts

        # 7. Inserción de cuñas de audio intersticiales
        if self.config.interstitials:
            emit_stage("interstitials", "Insertando cuñas de audio y separadores...", 9.5)
            final_utts = []
            # Cuñas de inicio
            for item in self.config.interstitials:
                if item.position == "start":
                    v_key = item.voice_key or self.config.voice_key
                    final_utts.append(Utterance(item.text, Style(voice=v_key), item.pause_after, -1, -1))

            current_chapter = -1
            for utt in raw_utterances:
                if utt.chapter_index != current_chapter and utt.is_title and current_chapter != -1:
                    # Entre capítulos
                    for item in self.config.interstitials:
                        if item.position == "between_chapters":
                            v_key = item.voice_key or self.config.voice_key
                            final_utts.append(Utterance(item.text, Style(voice=v_key), item.pause_after, -1, -1))
                current_chapter = utt.chapter_index
                final_utts.append(utt)

            # Cuñas de fin
            for item in self.config.interstitials:
                if item.position == "end":
                    v_key = item.voice_key or self.config.voice_key
                    final_utts.append(Utterance(item.text, Style(voice=v_key), item.pause_after, -1, -1))

            utterances = tuple(final_utts)
        else:
            utterances = tuple(raw_utterances)

        # 8. Inicialización de motor de síntesis
        emit_stage("engine", f"Inicializando sintetizador con voz '{self.config.voice_key}'...", 10.0)
        engine = PiperTtsEngine(voice_key=self.config.voice_key)
        assembler = AudioAssembler(sample_rate=engine.sample_rate)

        # Archivos de salida dentro de la carpeta del libro
        temp_wav = book_folder / f"{job_id}_temp.wav"
        master_audio_path: Optional[Path] = None
        if self.config.save_flac_master:
            master_audio_path = book_folder / f"{job_id}_master.flac"

        final_mp3 = book_folder / f"{job_id}.mp3"
        final_video = book_folder / f"{timestamp_str}_video_{slug}.mp4"
        ass_subtitles = book_folder / f"{job_id}_subtitles.ass"

        # 9. Síntesis y streaming a WAV temporal
        emit_stage("synthesize", "Sintetizando elocuciones con modelo local...", 12.0)
        assembly_res = assembler.assemble_to_wav(
            utterances=utterances,
            engine=engine,
            output_wav_path=temp_wav,
            progress_callback=progress_callback
        )

        # 10. Guardar copia Master sin pérdida si se solicitó
        out_master_str = None
        now_dt = datetime.now()
        fecha_str = now_dt.strftime("%Y-%m-%d")
        hora_str = now_dt.strftime("%H:%M:%S")
        dur_s = round(assembly_res.duration_s, 2)
        dur_fmt = time.strftime("%H:%M:%S", time.gmtime(dur_s))
        firma_str = "HUMAN AI SYNERGY BY BENNER CASTILLO"
        doc_display_title = doc.title or slug.replace("_", " ").title()

        if self.config.save_flac_master and temp_wav.exists():
            try:
                # Convertir a FLAC con metadatos completos
                import subprocess, sys
                cflags = 0x08000000 if sys.platform == "win32" else 0
                cmd_flac = [
                    "ffmpeg", "-y", "-i", str(temp_wav),
                    "-c:a", "flac",
                    "-metadata", f"artist={firma_str}",
                    "-metadata", f"album_artist={firma_str}",
                    "-metadata", f"title={doc_display_title} (Master FLAC)",
                    "-metadata", f"date={fecha_str}",
                    "-metadata", f"comment=Firma: {firma_str} | Fecha: {fecha_str} {hora_str} | Duración: {dur_fmt}",
                    "-metadata", f"copyright={firma_str} - 2026®",
                    str(master_audio_path)
                ]
                subprocess.run(cmd_flac, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cflags)
                if master_audio_path and master_audio_path.exists():
                    out_master_str = str(master_audio_path.resolve())
            except Exception:
                pass

        # 11. Conversión a MP3 de alta calidad con portada y metadatos ID3
        out_audio_str = None
        if self.config.generate_audio:
            emit_stage("normalize", "Normalizando audio a MP3 alta calidad con portada...", 80.0 if self.config.generate_video else 92.0)
            assembler.convert_to_mp3(
                wav_path=temp_wav,
                output_mp3_path=final_mp3,
                bitrate="256k",
                cover_image_path=copied_cover_path,
                title=doc_display_title,
                artist=firma_str,
                comment=f"Firma: {firma_str} | Fecha: {fecha_str} {hora_str} | Duración: {dur_fmt}",
                date=fecha_str
            )
            out_audio_str = str(final_mp3.resolve())

        # 12. Renderizado de video karaoke (MP4) con fondo y metadatos
        out_video_str = None
        if self.config.generate_video:
            emit_stage("subtitles", "Generando subtítulos sincronizados estilo karaoke...", 85.0)
            generate_ass_subtitles(
                sentences=assembly_res.sentences,
                output_ass_path=ass_subtitles,
                title=doc_display_title,
                fecha=fecha_str,
                hora=hora_str,
                duracion=dur_fmt
            )

            emit_stage("video", "Renderizando video MP4 karaoke sincronizado...", 90.0)
            render_karaoke_video(
                audio_path=temp_wav,
                ass_subtitles_path=ass_subtitles,
                output_video_path=final_video,
                cover_image_path=copied_cover_path,
                title=doc_display_title,
                artist=firma_str,
                comment=f"Firma: {firma_str} | Fecha: {fecha_str} {hora_str} | Duración: {dur_fmt}",
                date=fecha_str
            )
            out_video_str = str(final_video.resolve())

        # Limpiar archivo temporal intermedio
        if temp_wav.exists():
            try:
                temp_wav.unlink()
            except Exception:
                pass

        total_latency = time.perf_counter() - start_time
        completed_at_str = datetime.now().isoformat()
        emit_stage("done", "Audiolibro y video generados con éxito.", 100.0)

        # 13. Cálculo de tamaños de archivo
        archivos_dict = {}
        if out_audio_str and Path(out_audio_str).exists():
            sz = Path(out_audio_str).stat().st_size
            archivos_dict["mp3"] = {
                "ruta": out_audio_str,
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / (1024 * 1024):.2f} MB",
                "formato": "MP3 256k EBU R128"
            }
        if out_master_str and Path(out_master_str).exists():
            sz = Path(out_master_str).stat().st_size
            archivos_dict["master_flac"] = {
                "ruta": out_master_str,
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / (1024 * 1024):.2f} MB",
                "formato": "FLAC Master (Sin Pérdida)"
            }
        if out_video_str and Path(out_video_str).exists():
            sz = Path(out_video_str).stat().st_size
            archivos_dict["video_mp4"] = {
                "ruta": out_video_str,
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / (1024 * 1024):.2f} MB",
                "formato": "Video Karaoke MP4 1080p"
            }
        if ass_subtitles.exists():
            sz = ass_subtitles.stat().st_size
            archivos_dict["subtitulos_ass"] = {
                "ruta": str(ass_subtitles.resolve()),
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / 1024:.1f} KB",
                "formato": "Subtítulos Karaoke ASS"
            }

        # 14. Metadatos según ESTRUCTURA.md y directrices industriales
        metadata = JobMetadata(
            job_id=job_id,
            document_folder=str(book_folder.resolve()),
            created_at=timestamp_str,
            completed_at=completed_at_str,
            model_name="Piper-VITS (Sherpa-ONNX)",
            voice_key=self.config.voice_key,
            secondary_voice_key=self.config.secondary_voice_key if self.config.multi_voice_mode != "single" else None,
            parameters={
                "speed_factor": self.config.speed_factor,
                "sample_rate": engine.sample_rate,
                "bitrate": "256k",
                "loudnorm": "EBU R128 (-16 LUFS)",
                "multi_voice_mode": self.config.multi_voice_mode,
                "narration_enabled": bool(self.config.narration and self.config.narration.enabled),
            },
            source_file=str(Path(self.config.source_file).resolve()),
            source_sha256=doc.source_sha256,
            total_characters=doc.char_count,
            total_utterances=len(utterances),
            duration_seconds=dur_s,
            latency_seconds=round(total_latency, 2),
            output_audio_path=out_audio_str,
            output_video_path=out_video_str,
            output_master_path=out_master_str,
            cover_image_path=str(copied_cover_path.resolve()) if copied_cover_path else None,
            firma=firma_str,
            fecha=fecha_str,
            hora=hora_str,
            duracion_formato=dur_fmt,
            archivos_generados=archivos_dict
        )

        metadata_path = book_folder / f"{job_id}_metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(asdict(metadata), f, indent=2, ensure_ascii=False)

        return metadata
