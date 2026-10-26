"""Gestión de trabajos persistentes y orquestador del pipeline Documento -> Audiolibro.

Cumple estrictamente con ESTRUCTURA.md:
- Almacena cada documento procesado en su propia carpeta: biblioteca/<NombreDocumento>/
- Guarda master sin pérdida (FLAC/WAV), versión MP3 normalizada a 256k con portada y audiolibro .M4B con capítulos.
- Soporta portadas automáticas IA (1024x1024), Audio-Trailers promocionales (90s), exportación por capítulos,
  Diccionario Fonético (Lexicon), modulación emocional dinámica, Foley SFX, Masterización DSP y Soundscape Ducking.
- Genera video karaoke MP4 (16:9 Horizontal / 9:16 Vertical Shorts/Reels, Audiograma de espectro o portada)
  y subtítulos universales (.ass, .srt, .vtt, .lrc) + Paquete SEO YouTube/Spotify/Podcast RSS.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import soundfile as sf

from src.ai.cover_generator import generate_audiobook_cover
from src.ai.nemo_enhancer import MistralNeMoEnhancer, NarrationConfig
from src.ai.piper_engine import PiperTtsEngine
from src.audio.assembler import AudioAssembler, compute_chapter_timings
from src.audio.karaoke import (
    export_all_subtitle_formats,
    generate_ass_subtitles,
    render_karaoke_video,
)
from src.audio.sfx_engine import inject_semantic_sfx_tags
from src.audio.soundscape import mix_voice_with_soundscape
from src.core.editorial_cleaner import clean_inline_editorial_noise
from src.core.emotion_analyzer import apply_emotional_modulation
from src.core.lexicon import PhoneticLexicon
from src.core.models import Chapter, Document
from src.core.publisher import generate_publication_package
from src.core.text_clean import make_filename_slug
from src.core.utterances import Utterance, build_utterances
from src.ingest.loader import load_document
from src.markup.style import Style

logger = logging.getLogger("globaltts.job")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BIBLIOTECA_DIR = PROJECT_ROOT / "biblioteca"


@dataclass
class InterstitialItem:
    text: str
    voice_key: Optional[str] = None
    style: str = "locutor_radio"  # "locutor_radio", "cuentacuentos", "institucional", "misterioso"
    position: str = "between_chapters"  # "start", "between_chapters", "end"
    pause_after: float = 1.0


@dataclass
class JobConfig:
    source_file: str = ""
    voice_key: str = "kokoro-ef_dora"
    secondary_voice_key: Optional[str] = "kokoro-em_alex"
    voice_pool: list[str] = field(default_factory=list)  # Pool de 2 o más voces para auto-casting
    multi_voice_mode: str = "single"  # "single", "manual", "dialogue_auto", "ai_casting"
    output_name: Optional[str] = None
    output_dir: Optional[str] = None
    cover_image_path: Optional[str] = None
    generate_video: bool = True
    generate_audio: bool = True
    save_flac_master: bool = True
    speed_factor: float = 1.0
    narration: Optional[NarrationConfig] = None
    interstitials: list[InterstitialItem] = field(default_factory=list)
    # Nuevas capacidades de estudio (100% reales y retrocompatibles)
    export_m4b: bool = False
    split_chapters: bool = False
    clean_editorial: bool = True
    apply_lexicon: bool = True
    emotional_modulation: bool = True
    auto_sfx: bool = False
    dsp_mastering: bool = True
    soundscape_preset: str = "none"
    custom_bgm_path: Optional[str] = None
    generate_cover_ai: bool = False
    generate_trailer: bool = False
    generate_seo_package: bool = True
    video_aspect_ratio: str = "16:9"       # "16:9" | "9:16"
    video_background: str = "black"        # "black" | "cover_backdrop" | "audiogram"
    subtitle_theme: str = "cyan_ejecutivo"


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
    app_version: str = "2.5.0"
    output_m4b_path: Optional[str] = None
    output_trailer_path: Optional[str] = None
    chapters_info: list[dict] = field(default_factory=list)


class AudiobookPipeline:
    """Orquestador completo del procesamiento de libros a audiolibro y video sincronizado."""

    def __init__(self, config: JobConfig):
        self.config = config
        self.base_output_dir = Path(config.output_dir) if config.output_dir else BIBLIOTECA_DIR
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        self.lexicon = PhoneticLexicon()

    def run(
        self,
        progress_callback: Optional[callable] = None,
        stage_callback: Optional[callable] = None,
        pause_event: Optional[object] = None,
    ) -> JobMetadata:
        start_time = time.perf_counter()
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        def emit_stage(stage: str, desc: str, pct: float):
            if stage_callback:
                stage_callback(stage, desc, pct)

        # 1. Ingesta del documento (soporta TXT, PDF con OCR local, EPUB, Imágenes y URLs Web)
        emit_stage("ingest", "Analizando documento y extrayendo capítulos...", 2.0)
        doc: Document = load_document(self.config.source_file)

        # 2. Carpeta dedicada en biblioteca/ para este libro
        src_stem = "articulo_web" if str(self.config.source_file).startswith(("http://", "https://")) else Path(self.config.source_file).stem
        base_name = self.config.output_name or doc.title or src_stem
        slug = make_filename_slug(base_name, max_words=5, max_len=45)

        book_folder = self.base_output_dir / slug
        book_folder.mkdir(parents=True, exist_ok=True)

        job_id = f"{timestamp_str}_audio_{slug}"
        doc_display_title = doc.title or slug.replace("_", " ").title()
        active_style = (self.config.narration.style if (self.config.narration and self.config.narration.enabled) else "cuento")

        # 3. Portada si existe o generación automática con IA Local (1024x1024)
        copied_cover_path: Optional[Path] = None
        if self.config.cover_image_path and Path(self.config.cover_image_path).exists():
            orig_cover = Path(self.config.cover_image_path)
            copied_cover_path = book_folder / f"cover{orig_cover.suffix}"
            try:
                shutil.copy2(orig_cover, copied_cover_path)
            except Exception:
                copied_cover_path = orig_cover
        elif self.config.generate_cover_ai:
            emit_stage("cover_ai", "Generando portada editorial de alta resolución (1024x1024)...", 3.5)
            try:
                copied_cover_path = generate_audiobook_cover(
                    title=doc_display_title,
                    author=doc.author or "GlobalTTS Studio",
                    style=active_style,
                    output_path=book_folder / "cover.png",
                )
            except Exception as exc:
                logger.warning("Aviso generando portada IA: %s", exc)

        # 4. Preprocesamiento Editorial, Lexicon, SFX y Enriquecimiento con Mistral NeMo
        enhancer = MistralNeMoEnhancer()
        nemo_ready = bool(self.config.narration and self.config.narration.enabled and enhancer.is_available())
        if nemo_ready:
            emit_stage("ai_analysis", "Analizando con Mistral NeMo (narración / expresividad)...", 5.0)

        new_chapters = []
        for ch in doc.chapters:
            if pause_event is not None and hasattr(pause_event, "wait"):
                pause_event.wait()
            new_paragraphs = []
            for par in ch.paragraphs:
                processed = par
                if self.config.clean_editorial:
                    processed = clean_inline_editorial_noise(processed, strip_footnotes=True)

                if nemo_ready and self.config.narration:
                    if self.config.narration.mode == "rewrite":
                        processed = enhancer.rewrite_as_narration(processed, self.config.narration)
                    elif self.config.narration.mode == "translate":
                        processed = enhancer.translate_and_adapt(
                            processed,
                            target_lang=self.config.narration.target_language,
                            prompt_id=self.config.narration.prompt_id,
                        )
                    elif self.config.narration.mode == "dialogue_analysis":
                        analysis = enhancer.analyze_dialogues(processed, prompt_id=self.config.narration.prompt_id)
                        char_map: dict[str, str] = {"narrador": self.config.voice_key}
                        pool = [v for v in self.config.voice_pool if v != self.config.voice_key]
                        if not pool and self.config.secondary_voice_key:
                            pool = [self.config.secondary_voice_key]
                        if not pool:
                            pool = [self.config.voice_key]

                        char_meta_gender = {
                            c.get("name", "").strip().lower(): c.get("gender", "neutral").lower()
                            for c in analysis.get("characters", [])
                            if isinstance(c, dict)
                        }

                        seg_texts = []
                        for seg in analysis.get("segments", []):
                            stext = seg.get("text", "").strip()
                            if not stext:
                                continue
                            spk = seg.get("speaker", "Narrador").strip()
                            spk_lower = spk.lower()
                            if spk_lower not in char_map:
                                req_gender = char_meta_gender.get(spk_lower, "neutral")
                                from src.ai.piper_engine import list_available_piper_voices
                                v_profiles = list_available_piper_voices()
                                if req_gender in ("female", "male"):
                                    subpool = [v for v in pool if v_profiles.get(v) and v_profiles[v].gender == req_gender]
                                    chosen_voice = subpool[(len(char_map) - 1) % len(subpool)] if subpool else pool[(len(char_map) - 1) % len(pool)]
                                else:
                                    chosen_voice = pool[(len(char_map) - 1) % len(pool)]
                                char_map[spk_lower] = chosen_voice
                            v_assigned = char_map[spk_lower]

                            emotion = seg.get("emotion")
                            if emotion and emotion not in ("neutral", ""):
                                stext = f"[{emotion}]{stext}[/{emotion}]"
                            if v_assigned and v_assigned != self.config.voice_key:
                                stext = f"[voz:{v_assigned}]{stext}[/voz]"
                            seg_texts.append(stext)
                        processed = " ".join(seg_texts) if seg_texts else processed
                    else:
                        processed = enhancer.enhance_expressiveness(processed, prompt_id=self.config.narration.prompt_id)

                if self.config.auto_sfx:
                    processed = inject_semantic_sfx_tags(processed)

                if self.config.apply_lexicon:
                    processed = self.lexicon.apply(processed)

                if processed.strip():
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

        # 5. Segmentación en elocuciones y modulación emocional dinámica línea por línea
        emit_stage("markup", "Estructurando oraciones y curva prosódica emocional...", 8.0)
        build_res = build_utterances(doc, max_chars=350, use_markup=True)
        raw_utterances = list(build_res.utterances)
        if self.config.emotional_modulation:
            raw_utterances = list(apply_emotional_modulation(tuple(raw_utterances), intensity=1.0))

        # 6. Auto-casting Multi-voz (si está habilitado con pool de más de 2 voces)
        if self.config.multi_voice_mode in ("dialogue_auto", "ai_casting"):
            pool = [v for v in self.config.voice_pool if v != self.config.voice_key]
            if not pool and self.config.secondary_voice_key:
                pool = [self.config.secondary_voice_key]
            if pool:
                emit_stage("autocast", f"Aplicando auto-casting multi-voz con pool de {len(pool)} voces...", 9.0)
                dialogue_chars = ('"', "«", "“", "—", "- ")
                processed_utts = []
                dialogue_idx = 0
                for utt in raw_utterances:
                    text_stripped = utt.text.strip()
                    if any(text_stripped.startswith(dc) for dc in dialogue_chars) and not utt.style.voice:
                        assigned_v = pool[dialogue_idx % len(pool)]
                        dialogue_idx += 1
                        new_style = Style(
                            speed=utt.style.speed,
                            gain_db=utt.style.gain_db,
                            voice=assigned_v,
                            instruct=utt.style.instruct,
                        )
                        processed_utts.append(
                            Utterance(utt.text, new_style, utt.pause_after, utt.chapter_index, utt.paragraph_index, utt.is_title)
                        )
                    else:
                        processed_utts.append(utt)
                raw_utterances = processed_utts

        # 7. Inserción de cuñas de audio intersticiales
        if self.config.interstitials:
            emit_stage("interstitials", f"Insertando {len(self.config.interstitials)} cuñas de audio...", 9.5)
            final_utts = []
            for item in self.config.interstitials:
                if item.position == "start":
                    v_key = item.voice_key or self.config.voice_key
                    txt = f"[{item.style}]{item.text}[/{item.style}]" if item.style else item.text
                    final_utts.append(Utterance(txt, Style(voice=v_key), item.pause_after, -1, -1))

            current_chapter = -1
            for utt in raw_utterances:
                if utt.chapter_index != current_chapter and utt.is_title and current_chapter != -1:
                    for item in self.config.interstitials:
                        if item.position == "between_chapters":
                            v_key = item.voice_key or self.config.voice_key
                            txt = f"[{item.style}]{item.text}[/{item.style}]" if item.style else item.text
                            final_utts.append(Utterance(txt, Style(voice=v_key), item.pause_after, -1, -1))
                current_chapter = utt.chapter_index
                final_utts.append(utt)

            for item in self.config.interstitials:
                if item.position == "end":
                    v_key = item.voice_key or self.config.voice_key
                    txt = f"[{item.style}]{item.text}[/{item.style}]" if item.style else item.text
                    final_utts.append(Utterance(txt, Style(voice=v_key), item.pause_after, -1, -1))

            utterances = tuple(final_utts)
        else:
            utterances = tuple(raw_utterances)

        # Aplicar speed_factor global si es distinto de 1.0
        if abs(self.config.speed_factor - 1.0) > 0.01:
            utterances = tuple(
                Utterance(
                    u.text,
                    Style(
                        speed=u.style.speed * self.config.speed_factor,
                        gain_db=u.style.gain_db,
                        voice=u.style.voice,
                        instruct=u.style.instruct,
                    ),
                    u.pause_after,
                    u.chapter_index,
                    u.paragraph_index,
                    u.is_title,
                )
                for u in utterances
            )

        # 8. Inicialización de motor de síntesis
        emit_stage("engine", f"Inicializando sintetizador con voz '{self.config.voice_key}'...", 10.0)
        engine = PiperTtsEngine(voice_key=self.config.voice_key)
        assembler = AudioAssembler(sample_rate=engine.sample_rate)

        temp_wav = book_folder / f"{job_id}_temp.wav"
        master_audio_path: Optional[Path] = None
        if self.config.save_flac_master:
            master_audio_path = book_folder / f"{job_id}_master.flac"

        final_mp3 = book_folder / f"{job_id}.mp3"
        final_video = book_folder / f"{timestamp_str}_video_{slug}.mp4"
        ass_subtitles = book_folder / f"{job_id}_subtitles.ass"

        # 9. Síntesis, Masterización DSP y Soundscape Ducking a WAV
        emit_stage("synthesize", "Sintetizando elocuciones con masterización DSP local...", 12.0)
        assembly_res = assembler.assemble_to_wav(
            utterances=utterances,
            engine=engine,
            output_wav_path=temp_wav,
            progress_callback=progress_callback,
            pause_event=pause_event,
            dsp_mastering=self.config.dsp_mastering,
            soundscape_preset=self.config.soundscape_preset,
            custom_bgm_path=Path(self.config.custom_bgm_path) if self.config.custom_bgm_path else None,
        )

        now_dt = datetime.now()
        fecha_str = now_dt.strftime("%Y-%m-%d")
        hora_str = now_dt.strftime("%H:%M:%S")
        dur_s = round(assembly_res.duration_s, 2)
        dur_fmt = time.strftime("%H:%M:%S", time.gmtime(dur_s))
        firma_str = "HUMAN AI SYNERGY BY BENNER CASTILLO"

        # Calcular tiempos de capítulos
        ch_titles = [c.title for c in doc.chapters]
        ch_timings = compute_chapter_timings(
            assembly_res.sentences,
            total_duration_s=dur_s,
            chapter_titles=ch_titles,
        )

        # 10. Guardar copia Master FLAC sin pérdida si se solicitó
        out_master_str = None
        if self.config.save_flac_master and temp_wav.exists():
            try:
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
                    str(master_audio_path),
                ]
                subprocess.run(cmd_flac, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cflags)
                if master_audio_path and master_audio_path.exists():
                    out_master_str = str(master_audio_path.resolve())
            except Exception:
                pass

        # 11. Conversión a MP3 de alta calidad con portada y metadatos ID3
        out_audio_str = None
        if self.config.generate_audio:
            emit_stage("normalize", "Normalizando audio a MP3 alta calidad con portada...", 78.0)
            assembler.convert_to_mp3(
                wav_path=temp_wav,
                output_mp3_path=final_mp3,
                bitrate="256k",
                cover_image_path=copied_cover_path,
                title=doc_display_title,
                artist=firma_str,
                comment=f"Firma: {firma_str} | Fecha: {fecha_str} {hora_str} | Duración: {dur_fmt}",
                date=fecha_str,
            )
            out_audio_str = str(final_mp3.resolve())

        # 11.1 Exportar Audiolibro Nativo .M4B con índice de capítulos y portada
        out_m4b_str = None
        if self.config.export_m4b and temp_wav.exists():
            emit_stage("m4b", "Empaquetando audiolibro .M4B con capítulos navegables...", 81.0)
            m4b_file = assembler.export_m4b(
                source_wav_or_mp3=temp_wav,
                output_m4b_path=book_folder / f"{job_id}.m4b",
                title=doc_display_title,
                artist=firma_str,
                chapters=ch_timings,
                cover_image_path=copied_cover_path,
            )
            if m4b_file and m4b_file.exists():
                out_m4b_str = str(m4b_file.resolve())

        # 11.2 Exportar capítulos individuales divididos si se solicitó
        split_ch_files: list[Path] = []
        if self.config.split_chapters and temp_wav.exists() and ch_timings:
            emit_stage("split_chapters", f"Exportando {len(ch_timings)} capítulos individuales...", 83.0)
            split_ch_files = assembler.export_split_chapters_from_wav(
                wav_path=temp_wav,
                chapters=ch_timings,
                output_dir=book_folder,
                cover_image_path=copied_cover_path,
                artist=firma_str,
            )

        # 12. Subtítulos sincronizados (.ASS, .SRT, .VTT, .LRC) y Video Karaoke (MP4)
        out_video_str = None
        generate_ass_subtitles(
            sentences=assembly_res.sentences,
            output_ass_path=ass_subtitles,
            title=doc_display_title,
            fecha=fecha_str,
            hora=hora_str,
            duracion=dur_fmt,
            aspect_ratio=self.config.video_aspect_ratio,
            theme=self.config.subtitle_theme,
        )
        extra_subs = export_all_subtitle_formats(
            sentences=assembly_res.sentences,
            base_dir=book_folder,
            base_prefix=f"{job_id}_subtitles",
            title=doc_display_title,
        )

        if self.config.generate_video:
            emit_stage("video", f"Renderizando video MP4 ({self.config.video_aspect_ratio} / {self.config.video_background})...", 88.0)
            render_karaoke_video(
                audio_path=temp_wav,
                ass_subtitles_path=ass_subtitles,
                output_video_path=final_video,
                cover_image_path=copied_cover_path,
                title=doc_display_title,
                artist=firma_str,
                comment=f"Firma: {firma_str} | Fecha: {fecha_str} {hora_str} | Duración: {dur_fmt}",
                date=fecha_str,
                aspect_ratio=self.config.video_aspect_ratio,
                background_mode=self.config.video_background,
                subtitle_theme=self.config.subtitle_theme,
            )
            out_video_str = str(final_video.resolve())

        # 12.1 Generar Audio-Trailer promocional de 90s si se solicitó
        out_trailer_str = None
        if self.config.generate_trailer:
            emit_stage("trailer", "Produciendo Audio-Trailer promocional de 90 segundos...", 94.0)
            trailer_p = self.generate_standalone_trailer(
                doc=doc,
                book_folder=book_folder,
                engine=engine,
                enhancer=enhancer,
                style=active_style,
                cover_image_path=copied_cover_path,
            )
            if trailer_p and trailer_p.exists():
                out_trailer_str = str(trailer_p.resolve())

        # 12.2 Generar Paquete SEO YouTube / Spotify / Podcast RSS
        if self.config.generate_seo_package:
            try:
                generate_publication_package(
                    project_dir=book_folder,
                    title=doc_display_title,
                    author=doc.author or firma_str,
                    duration_s=dur_s,
                    chapters=ch_timings,
                    style=active_style,
                )
            except Exception as exc:
                logger.warning("Aviso generando paquete SEO: %s", exc)

        # Limpiar archivo temporal intermedio
        if temp_wav.exists():
            try:
                temp_wav.unlink()
            except Exception:
                pass

        total_latency = time.perf_counter() - start_time
        completed_at_str = datetime.now().isoformat()
        emit_stage("done", "Audiolibro y artefactos de estudio generados con éxito.", 100.0)

        # 13. Cálculo de tamaños de archivo
        archivos_dict = {}
        if out_audio_str and Path(out_audio_str).exists():
            sz = Path(out_audio_str).stat().st_size
            archivos_dict["mp3"] = {
                "ruta": out_audio_str,
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / (1024 * 1024):.2f} MB",
                "formato": "MP3 256k EBU R128 + DSP",
            }
        if out_m4b_str and Path(out_m4b_str).exists():
            sz = Path(out_m4b_str).stat().st_size
            archivos_dict["m4b"] = {
                "ruta": out_m4b_str,
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / (1024 * 1024):.2f} MB",
                "formato": "Audiolibro M4B (Capítulos Navegables)",
            }
        if out_master_str and Path(out_master_str).exists():
            sz = Path(out_master_str).stat().st_size
            archivos_dict["master_flac"] = {
                "ruta": out_master_str,
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / (1024 * 1024):.2f} MB",
                "formato": "FLAC Master (Sin Pérdida)",
            }
        if out_video_str and Path(out_video_str).exists():
            sz = Path(out_video_str).stat().st_size
            archivos_dict["video_mp4"] = {
                "ruta": out_video_str,
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / (1024 * 1024):.2f} MB",
                "formato": f"Video Karaoke MP4 ({self.config.video_aspect_ratio})",
            }
        if out_trailer_str and Path(out_trailer_str).exists():
            sz = Path(out_trailer_str).stat().st_size
            archivos_dict["trailer_mp3"] = {
                "ruta": out_trailer_str,
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / (1024 * 1024):.2f} MB",
                "formato": "Audio-Trailer Promocional 90s",
            }
        if ass_subtitles.exists():
            sz = ass_subtitles.stat().st_size
            archivos_dict["subtitulos_ass"] = {
                "ruta": str(ass_subtitles.resolve()),
                "tamano_bytes": sz,
                "tamano_mb": f"{sz / 1024:.1f} KB",
                "formato": "Subtítulos Karaoke ASS",
            }
        for s_fmt, s_path in extra_subs.items():
            if s_path.exists():
                sz = s_path.stat().st_size
                archivos_dict[f"subtitulos_{s_fmt}"] = {
                    "ruta": str(s_path.resolve()),
                    "tamano_bytes": sz,
                    "tamano_mb": f"{sz / 1024:.1f} KB",
                    "formato": f"Subtítulos {s_fmt.upper()}",
                }
        if split_ch_files:
            archivos_dict["capitulos_divididos"] = {
                "ruta": str((book_folder / "capitulos").resolve()),
                "cantidad": len(split_ch_files),
                "formato": f"{len(split_ch_files)} Pistas MP3 por Capítulo",
            }

        # 14. Metadatos según ESTRUCTURA.md y directrices industriales
        src_resolved = (
            self.config.source_file
            if str(self.config.source_file).startswith(("http://", "https://"))
            else str(Path(self.config.source_file).resolve())
        )
        metadata = JobMetadata(
            job_id=job_id,
            document_folder=str(book_folder.resolve()),
            created_at=timestamp_str,
            completed_at=completed_at_str,
            model_name="Kokoro-24kHz / Piper-VITS (Sherpa-ONNX)",
            voice_key=self.config.voice_key,
            secondary_voice_key=self.config.secondary_voice_key if self.config.multi_voice_mode != "single" else None,
            parameters={
                "speed_factor": self.config.speed_factor,
                "sample_rate": engine.sample_rate,
                "bitrate": "256k",
                "loudnorm": "EBU R128 (-16 LUFS) + Studio DSP (-1.0 dBTP)",
                "multi_voice_mode": self.config.multi_voice_mode,
                "narration_enabled": bool(self.config.narration and self.config.narration.enabled),
                "dsp_mastering": self.config.dsp_mastering,
                "soundscape_preset": self.config.soundscape_preset,
                "video_aspect_ratio": self.config.video_aspect_ratio,
                "video_background": self.config.video_background,
                "subtitle_theme": self.config.subtitle_theme,
                "export_m4b": self.config.export_m4b,
                "split_chapters": self.config.split_chapters,
            },
            source_file=src_resolved,
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
            archivos_generados=archivos_dict,
            output_m4b_path=out_m4b_str,
            output_trailer_path=out_trailer_str,
            chapters_info=[asdict(c) for c in ch_timings],
        )

        metadata_path = book_folder / f"{job_id}_metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(asdict(metadata), f, indent=2, ensure_ascii=False)

        return metadata

    def generate_standalone_trailer(
        self,
        doc: Document,
        book_folder: Path,
        engine: Optional[PiperTtsEngine] = None,
        enhancer: Optional[MistralNeMoEnhancer] = None,
        style: str = "epico",
        cover_image_path: Optional[Path] = None,
    ) -> Optional[Path]:
        """Sintetiza un Audio-Trailer dramático de 60-90s con música ambiental y Foley."""
        try:
            tts = engine or PiperTtsEngine(voice_key=self.config.voice_key)
            nemo = enhancer or MistralNeMoEnhancer()
            sample_text = " ".join(p for c in doc.chapters for p in c.paragraphs)[:5000]
            script = nemo.generate_synopsis_trailer_script(sample_text, title=doc.title, style=style)
            script = self.lexicon.apply(script)
            samples = tts.synthesize(script)
            if len(samples) == 0:
                return None

            bgm_preset = "mystery_thriller" if style in ("terror", "misterio") else "ambient_drone"
            mixed = mix_voice_with_soundscape(
                voice_samples=samples,
                sample_rate=tts.sample_rate,
                preset=bgm_preset,
                ducked_db=-19.0,
                pause_db=-11.5,
            )
            tmp_wav = book_folder / "trailer_temp.wav"
            final_trailer = book_folder / "trailer_sinopsis.mp3"
            sf.write(str(tmp_wav), mixed, tts.sample_rate, subtype="PCM_16")
            AudioAssembler.convert_to_mp3(
                wav_path=tmp_wav,
                output_mp3_path=final_trailer,
                bitrate="256k",
                cover_image_path=cover_image_path,
                title=f"{doc.title} (Audio-Trailer 90s)",
            )
            tmp_wav.unlink(missing_ok=True)
            return final_trailer
        except Exception as exc:
            logger.warning("Aviso generando Audio-Trailer: %s", exc)
            return None
