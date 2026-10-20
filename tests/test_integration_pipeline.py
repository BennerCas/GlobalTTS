"""Test de integración para el pipeline completo de Audiobook (audio MP3 + video karaoke)."""
from pathlib import Path

from src.core.job import AudiobookPipeline, JobConfig


def test_full_audiobook_pipeline_e2e(tmp_path: Path):
    sample_txt = tmp_path / "mini_libro.txt"
    sample_txt.write_text(
        "Capítulo Único: Aventuras\n\n"
        "Este es un breve texto de prueba. [pausa:500ms] "
        "[lento]Aquí se habla con calma y reflexión.[/lento] "
        "Y finalmente llegamos al desenlace de la historia.",
        encoding="utf-8"
    )

    out_dir = tmp_path / "salida"
    config = JobConfig(
        source_file=str(sample_txt),
        voice_key="es_MX-claude-high",
        output_name="test_audiolibro",
        output_dir=str(out_dir),
        generate_audio=True,
        generate_video=True
    )

    pipeline = AudiobookPipeline(config)
    meta = pipeline.run()

    # Verificar que los metadatos y archivos existen
    assert meta.total_utterances >= 3
    assert meta.duration_seconds > 0.0

    assert meta.output_audio_path is not None
    audio_path = Path(meta.output_audio_path)
    assert audio_path.exists()
    assert audio_path.stat().st_size > 1000  # Archivo MP3 válido

    assert meta.output_video_path is not None
    video_path = Path(meta.output_video_path)
    assert video_path.exists()
    assert video_path.stat().st_size > 1000  # Archivo MP4 válido

    # Verificar metadata JSON en disco dentro de la carpeta del libro
    meta_json = Path(meta.document_folder) / f"{meta.job_id}_metadata.json"
    assert meta_json.exists()
    assert Path(meta.document_folder).exists()
    if meta.output_master_path:
        assert Path(meta.output_master_path).exists()
