"""Suite de pruebas integrales para todas las funciones avanzadas de GlobalTTS."""
from __future__ import annotations

from pathlib import Path
import urllib.request

import numpy as np
import soundfile as sf

from src.ai.cover_generator import generate_audiobook_cover
from src.ai.voice_cloner import VoiceClonerManager, pitch_shift_preserve_duration
from src.api.mobile_server import MobileStreamingServer, generate_qr_image
from src.audio.assembler import ChapterTiming
from src.audio.dsp_mastering import MasteringConfig, master_audio_track
from src.audio.karaoke import (
    TimedSentence,
    calculate_word_timings,
    export_lrc_subtitles,
    export_srt_subtitles,
    export_vtt_subtitles,
)
from src.audio.sfx_engine import (
    SFX_CATALOG,
    extract_and_strip_sfx_tags,
    inject_semantic_sfx_tags,
    synthesize_sfx,
)
from src.audio.soundscape import mix_voice_with_soundscape
from src.core.audio_cache import AudioSegmentCache
from src.core.editorial_cleaner import clean_editorial_blocks, detect_repeating_headers_footers
from src.core.emotion_analyzer import analyze_sentence_emotion, apply_emotional_modulation
from src.core.hardware_monitor import HardwareMonitor
from src.core.job import AudiobookPipeline, JobConfig
from src.core.lexicon import PhoneticLexicon
from src.core.publisher import generate_publication_package
from src.core.utterances import Utterance
from src.ingest.url_reader import extract_text_from_html
from src.markup.parser import Style


def test_editorial_cleaner_strips_noise():
    pages = [
        ["CABECERA REPETIDA DEL LIBRO", "42"],
        ["CABECERA REPETIDA DEL LIBRO", "Página 12 de 300"],
        ["CABECERA REPETIDA DEL LIBRO", "Este es un párrafo real con citas[12] y superíndices¹² que deben limpiarse."],
        ["CABECERA REPETIDA DEL LIBRO", "ISBN: 978-3-16-148410-0"],
    ]
    repeating = detect_repeating_headers_footers(pages, min_occurrences=3)
    flat_blocks = [b for p in pages for b in p]
    cleaned = clean_editorial_blocks(flat_blocks, repeating_patterns=repeating)
    assert len(cleaned) == 1
    txt = cleaned[0]
    assert "[12]" not in txt
    assert "¹" not in txt
    assert "párrafo real" in txt


def test_url_html_readability_extractor():
    html = """
    <html>
      <head><title>Artículo de Inteligencia Artificial</title></head>
      <body>
        <nav>Menú Principal</nav>
        <article>
          <h1>Capítulo I: El Futuro de DirectML</h1>
          <p>La inferencia local permite ejecutar modelos neuronales sin latencia de red ni costos externos.</p>
          <p>Además garantiza privacidad absoluta en el procesamiento acústico y narrativo.</p>
        </article>
        <footer>Derechos reservados</footer>
      </body>
    </html>
    """
    title, author, blocks = extract_text_from_html(html, source_url="https://example.com/ia")
    joined = "\n".join(blocks)
    assert "Inteligencia Artificial" in title or "Futuro de DirectML" in title
    assert "inferencia local" in joined
    assert "Menú Principal" not in joined


def test_phonetic_lexicon_tag_safe(tmp_path: Path):
    lex_file = tmp_path / "lexicon.json"
    lex = PhoneticLexicon(path=lex_file)
    lex.add_entry("ONNX", "ónix", case_sensitive=False, category="anglicismo")

    sample = "[susurro]El modelo ONNX corre en GPU con PyQt6.[/susurro]"
    out = lex.apply(sample)
    assert "[susurro]" in out
    assert "[/susurro]" in out
    assert "ónix" in out


def test_emotion_analyzer_and_modulation():
    e_excited = analyze_sentence_emotion("¡Qué victoria tan extraordinaria y brillante!")
    assert e_excited.emotion == "excited"

    e_whisper = analyze_sentence_emotion("Shh, susurró en voz baja casi en silencio.")
    assert e_whisper.emotion == "whisper"

    utts = (
        Utterance(
            text="¡Qué victoria tan extraordinaria y brillante!",
            style=Style(speed=1.0, gain_db=0.0),
            pause_after=0.5,
            chapter_index=0,
            paragraph_index=0,
            is_title=False,
        ),
    )
    mod_utts = apply_emotional_modulation(utts, intensity=1.0)
    assert mod_utts[0].style.speed != 1.0 or mod_utts[0].style.gain_db != 0.0


def test_audio_segment_cache(tmp_path: Path):
    cache = AudioSegmentCache(cache_dir=tmp_path / "cache", max_entries=50)
    assert cache.get("kokoro-ef_dora", 24000, 1.0, 0.0, "Hola mundo") is None

    arr = np.linspace(-0.5, 0.5, 2400, dtype=np.float32)
    cache.put("kokoro-ef_dora", 24000, 1.0, 0.0, "Hola mundo", arr)

    loaded = cache.get("kokoro-ef_dora", 24000, 1.0, 0.0, "Hola mundo")
    assert loaded is not None
    assert len(loaded) == 2400
    assert np.allclose(arr, loaded)
    assert cache.stats().files_count == 1
    assert cache.clear() == 1


def test_hardware_monitor_snapshot():
    mon = HardwareMonitor()
    snap = mon.snapshot()
    assert snap.cpu_threads == 12
    assert snap.ram_total_gb > 0
    assert "25GB" in snap.vram_limit
    assert "HW:" in snap.format_badge_text()


def test_dsp_mastering_chain():
    sr = 24000
    t = np.linspace(0, 1.0, sr, dtype=np.float32)
    raw = (0.4 * np.sin(2 * np.pi * 30 * t) + 0.6 * np.sin(2 * np.pi * 220 * t) + 0.3 * np.sin(2 * np.pi * 7000 * t)).astype(np.float32)
    mastered = master_audio_track(raw, sr, MasteringConfig(enabled=True, ceiling_dbtp=-1.0))
    assert mastered.shape == raw.shape
    peak_linear = float(np.max(np.abs(mastered)))
    assert peak_linear <= 0.90


def test_soundscape_and_autoducking():
    sr = 24000
    voice = np.zeros(sr * 2, dtype=np.float32)
    t = np.linspace(0, 1.0, sr, dtype=np.float32)
    voice[:sr] = 0.5 * np.sin(2 * np.pi * 300 * t)

    mixed = mix_voice_with_soundscape(voice, sr, preset="rain_night")
    assert mixed.ndim == 2
    assert mixed.shape == (sr * 2, 2)


def test_sfx_engine_and_tags():
    sr = 24000
    for sfx_name in SFX_CATALOG:
        samples = synthesize_sfx(sfx_name, sample_rate=sr)
        assert len(samples) > 1000
        assert samples.dtype == np.float32

    tagged = inject_semantic_sfx_tags("De pronto un trueno sacudió la noche bajo la lluvia.")
    assert "[sfx:" in tagged

    clean_txt, effects = extract_and_strip_sfx_tags("[sfx:trueno] La tormenta comenzó.")
    assert "trueno" in effects
    assert "[sfx:" not in clean_txt


def test_biometric_voice_cloner(tmp_path: Path):
    sr = 24000
    t = np.linspace(0, 2.5, int(sr * 2.5), dtype=np.float32)
    sample_wav = tmp_path / "ref_speaker.wav"
    sig = (0.5 * np.sin(2 * np.pi * 145 * t) + 0.25 * np.sin(2 * np.pi * 290 * t) + 0.1 * np.sin(2 * np.pi * 2800 * t)).astype(np.float32)
    sf.write(str(sample_wav), sig, sr)

    cloner = VoiceClonerManager(config_path=tmp_path / "cloned_voices.json")
    prof = cloner.clone_from_audio(sample_wav, custom_name="Locutor Clon Prueba")
    assert prof.key.startswith("cloned-")
    assert 70.0 <= prof.f0_hz <= 310.0
    assert len(prof.embedding_preview) == 8

    shifted = pitch_shift_preserve_duration(sig[:sr], sr, prof.pitch_semitones)
    assert len(shifted) > 1000


def test_cover_generator_and_qr(tmp_path: Path):
    cover_path = tmp_path / "cover.png"
    out = generate_audiobook_cover(
        title="El Imperio de los Algoritmos",
        author="Edición Magistral",
        style="ciencia_ficcion",
        output_path=cover_path,
    )
    assert out.exists()
    assert out.stat().st_size > 5000

    qr_img = generate_qr_image("http://192.168.1.10:8765/", box_size=6, border=2)
    assert qr_img.size[0] > 100
    assert qr_img.size[0] == qr_img.size[1]


def test_mobile_streaming_server_http_and_range(tmp_path: Path):
    book_dir = tmp_path / "libro_demo"
    book_dir.mkdir(parents=True)
    dummy_mp3 = book_dir / "demo.mp3"
    dummy_mp3.write_bytes(b"ID3_DUMMY_AUDIO_CONTENT_" * 200)

    srv = MobileStreamingServer(output_root=tmp_path, port=18765)
    url = srv.start()
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            html = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "GlobalTTS" in html or "GLOBAL TTS" in html

        req = urllib.request.Request(
            f"{url}media/libro_demo/demo.mp3",
            headers={"Range": "bytes=0-99"},
        )
        with urllib.request.urlopen(req, timeout=3) as r_range:
            assert r_range.status == 206
            chunk = r_range.read()
            assert len(chunk) == 100
    finally:
        srv.stop()


def test_publisher_seo_and_rss_and_subtitles(tmp_path: Path):
    chapters = [
        ChapterTiming(index=1, title="Capítulo 1: Introducción", start_ms=0, end_ms=45000),
        ChapterTiming(index=2, title="Capítulo 2: Desarrollo", start_ms=45000, end_ms=120000),
    ]
    pkg = generate_publication_package(
        project_dir=tmp_path,
        title="Obra Maestra",
        author="GlobalTTS Studio",
        duration_s=120.0,
        chapters=chapters,
        style="cuento",
        summary_text="Un relato fascinante sobre tecnología y humanidad.",
    )
    assert Path(pkg["seo"]).exists()
    assert Path(pkg["rss"]).exists()
    seo_content = Path(pkg["seo"]).read_text(encoding="utf-8")
    assert "00:00 Capítulo 1: Introducción" in seo_content
    assert "00:45 Capítulo 2: Desarrollo" in seo_content

    s1 = "Primera oración del libro."
    s2 = "Segunda oración con emoción."
    timed = [
        TimedSentence(sentence=s1, start_s=0.0, end_s=2.5, words=calculate_word_timings(s1, 2.5), chapter_index=0),
        TimedSentence(sentence=s2, start_s=2.5, end_s=5.2, words=calculate_word_timings(s2, 2.7), chapter_index=0),
    ]
    srt_p = export_srt_subtitles(timed, tmp_path / "subs.srt")
    vtt_p = export_vtt_subtitles(timed, tmp_path / "subs.vtt")
    lrc_p = export_lrc_subtitles(timed, tmp_path / "subs.lrc")
    assert srt_p.exists() and "-->" in srt_p.read_text(encoding="utf-8")
    assert vtt_p.exists() and "WEBVTT" in vtt_p.read_text(encoding="utf-8")
    assert lrc_p.exists() and "[00:00.00]" in lrc_p.read_text(encoding="utf-8")


def test_pipeline_with_m4b_chapters_sfx_and_seo(tmp_path: Path):
    book_txt = tmp_path / "libro_completo.txt"
    book_txt.write_text(
        "# Capítulo I: El Despertar\n\n"
        "[sfx:campana] La mañana comenzó con claridad en el valle. "
        "Los sistemas ONNX procesaban cada señal con precisión.\n\n"
        "# Capítulo II: La Tormenta\n\n"
        "De pronto un trueno resonó en el horizonte lejano.",
        encoding="utf-8",
    )

    out_dir = tmp_path / "biblioteca_out"
    cfg = JobConfig(
        source_file=str(book_txt),
        voice_key="es_MX-claude-high",
        output_name="libro_completo",
        output_dir=str(out_dir),
        generate_audio=True,
        export_m4b=True,
        export_epub3=True,
        split_chapters=True,
        generate_trailer=True,
        generate_video=False,
        generate_cover_ai=True,
        dsp_mastering=True,
        auto_sfx=True,
        soundscape_preset="ambient_drone",
        generate_seo_package=True,
    )
    pipeline = AudiobookPipeline(cfg)
    meta = pipeline.run()

    assert meta.output_audio_path and Path(meta.output_audio_path).exists()
    assert meta.output_m4b_path and Path(meta.output_m4b_path).exists()
    assert meta.output_epub3_path and Path(meta.output_epub3_path).exists()
    assert meta.output_trailer_path and Path(meta.output_trailer_path).exists()
    doc_folder = Path(meta.document_folder)
    assert (doc_folder / "youtube_spotify_seo.txt").exists()
    assert (doc_folder / "podcast_rss.xml").exists()
    assert (doc_folder / "cover.png").exists()
    assert len(meta.chapters_info) >= 1
    assert meta.style == "cuento"
    assert meta.title != ""


def test_ui_mainwindow_and_studio_dialogs_init():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from src.ui.tray_app import MainWindow
    from src.ui.manual_tab import MANUAL_MD_PATH, MANUAL_SECTIONS
    from src.ui.studio_dialogs import (
        LexiconManagerDialog,
        VoiceClonerDialog,
        UrlIngestDialog,
    )

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    assert win.tabs.count() == 5
    assert hasattr(win, "tab_manual")
    assert not hasattr(win, "btn_top_manual")
    assert win.tabs.cornerWidget(Qt.Corner.TopRightCorner) is win.tab_corner_bar
    assert win.tab_manual.section_list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert win.tab_manual.section_list.count() == len(MANUAL_SECTIONS) + 1
    for i in range(win.tab_manual.section_list.count()):
        item_text = win.tab_manual.section_list.item(i).text()
        assert "\n" in item_text
    assert MANUAL_MD_PATH.exists()
    assert "MANUAL DE USO COMPLETO" in MANUAL_MD_PATH.read_text(encoding="utf-8")

    # Probar búsqueda interactiva en el manual
    win.tab_manual.search_edit.setText("campplus.onnx")
    assert win.tab_manual.section_list.count() >= 2
    win.tab_manual.search_edit.clear()
    assert win.tab_manual.section_list.count() == len(MANUAL_SECTIONS) + 1

    assert hasattr(win, "chk_m4b")
    assert hasattr(win, "chk_split_chapters")
    assert hasattr(win, "chk_auto_cover_ai")
    assert hasattr(win, "chk_generate_trailer")
    assert hasattr(win, "pause_btn")
    assert hasattr(win, "cancel_btn")
    assert hasattr(win, "lbl_hw_telemetry")

    # Probar alternancia de orientación Vertical <-> Horizontal
    win.apply_orientation("vertical", force=True)
    win.apply_orientation("horizontal", force=True)

    # Probar cableado entre Biblioteca -> Lector Rápido
    win.tab_library.load_text_requested.emit("Texto enviado desde la biblioteca.", "Prueba Biblioteca")
    assert win.tab_quick.text_edit.toPlainText() == "Texto enviado desde la biblioteca."
    assert win.tabs.currentIndex() == 0

    # Probar barra de inserción de etiquetas prosódicas y SFX en Lector Rápido
    win.tab_quick.insert_prosody_tag("[pausa:1s]", is_wrap=False)
    assert "[pausa:1s]" in win.tab_quick.text_edit.toPlainText()
    win.tab_quick.on_sfx_combo_selected(1)
    assert "[sfx:" in win.tab_quick.text_edit.toPlainText()
    assert win.tab_quick.combo_ai_style.isEnabled()
    assert win.combo_style.isEnabled()

    # Probar controles del reproductor de Biblioteca (Pista / Capítulo y Velocidad)
    assert hasattr(win.tab_library, "combo_track")
    assert hasattr(win.tab_library, "combo_speed")
    assert hasattr(win.tab_library, "btn_export_zip")
    win.tab_library.combo_speed.setCurrentIndex(2)  # 1.25x

    # Probar sincronización de estilos desde Prompts Maestros hacia Generador y Lector Rápido
    win.tab_prompts.prompts_updated.emit()
    assert win.tab_quick.combo_ai_style.count() >= 9
    assert win.combo_style.count() >= 9

    dlg_lex = LexiconManagerDialog()
    assert dlg_lex.table.rowCount() >= 20
    dlg_lex.close()

    dlg_clone = VoiceClonerDialog()
    dlg_clone.close()

    dlg_url = UrlIngestDialog()
    dlg_url.close()

    win.hw_timer.stop()
    win.close()


def test_global_hotkey_tts_engine_pipeline():
    import tts_engine

    cfg = tts_engine.load_config()
    cfg["voice"] = "kokoro-ef_dora"
    cfg["style_id"] = "locutor_radio"
    cfg["apply_lexicon"] = True
    cfg["emotional_modulation"] = True
    cfg["dsp_mastering"] = True

    samples, sr = tts_engine.synthesize_audio(
        "Prueba de lectura global con IA y GPU.",
        voice_key=cfg["voice"],
        speed_factor=1.0,
        cfg=cfg,
    )
    assert sr in (16000, 22050, 24000)
    assert len(samples) > 1000
