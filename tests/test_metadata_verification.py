"""Test para verificar la inclusión obligatoria de firma, fecha, hora, duración y tamaño."""
from pathlib import Path

from src.core.job import AudiobookPipeline, JobConfig


def test_metadata_has_signature_date_time_duration_and_size(tmp_path: Path):
    doc_path = tmp_path / "metadata_test.txt"
    doc_path.write_text("Capítulo 1: Verificación de Metadatos\n\nPrueba de inclusión de firma institucional.", encoding="utf-8")

    out_dir = tmp_path / "salida"
    cfg = JobConfig(
        source_file=str(doc_path),
        voice_key="es_MX-claude-high",
        output_name="test_meta",
        output_dir=str(out_dir),
        generate_audio=True,
        generate_video=False,
        save_flac_master=False
    )

    pipeline = AudiobookPipeline(cfg)
    meta = pipeline.run()

    # Validar campos de metadatos obligatorios
    assert meta.firma == "HUMAN AI SYNERGY BY BENNER CASTILLO"
    assert len(meta.fecha) == 10  # YYYY-MM-DD
    assert len(meta.hora) == 8   # HH:MM:SS
    assert ":" in meta.duracion_formato
    assert meta.duration_seconds > 0.0

    # Validar estructura de archivos generados
    assert "mp3" in meta.archivos_generados
    mp3_info = meta.archivos_generados["mp3"]
    assert mp3_info["tamano_bytes"] > 1000
    assert "MB" in mp3_info["tamano_mb"] or "KB" in mp3_info["tamano_mb"]
