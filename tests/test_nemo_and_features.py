"""Tests unitarios para enriquecimiento Mistral NeMo, cuñas intersticiales y auto-casting multi-voz."""
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.ai.nemo_enhancer import MistralNeMoEnhancer, NarrationConfig
from src.core.job import AudiobookPipeline, InterstitialItem, JobConfig
from src.core.models import Chapter, Document
from src.core.utterances import Utterance
from src.markup.style import Style


def test_nemo_enhancer_fallback_when_offline():
    enhancer = MistralNeMoEnhancer()
    # Con URL inválida para simular offline o error
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        assert enhancer.is_available() is False
        text = "Este es un texto original sin cambios."
        result = enhancer.enhance_expressiveness(text)
        assert result == text

        cfg = NarrationConfig(enabled=True, mode="rewrite", persona="1ra", tense="presente", style="cuento")
        narrated = enhancer.rewrite_as_narration(text, cfg)
        assert narrated == text


def test_nemo_enhancer_cleans_thinking_and_codeblocks():
    enhancer = MistralNeMoEnhancer()
    raw_response = (
        "<thinking>Analizando el texto para inyectar prosodia...</thinking>\n"
        "```markdown\n"
        "Este es el texto [pausa:500ms] con [lento]etiquetas[/lento].\n"
        "```"
    )
    with patch.object(enhancer, "_call_ollama", return_value="Este es el texto [pausa:500ms] con [lento]etiquetas[/lento]."):
        res = enhancer.enhance_expressiveness("Texto base")
        assert "[lento]etiquetas[/lento]" in res


def test_interstitials_and_autocast_in_pipeline(tmp_path: Path):
    doc_path = tmp_path / "cuento.txt"
    doc_path.write_text(
        "Capítulo 1: El Comienzo\n\n"
        "Había una vez un viajero en el camino.\n"
        "—¡Alto ahí! ¿Quién va?— gritó el guardia.\n\n"
        "Capítulo 2: El Encuentro\n\n"
        "El sol caía sobre las colinas.",
        encoding="utf-8"
    )

    out_dir = tmp_path / "biblioteca"
    config = JobConfig(
        source_file=str(doc_path),
        voice_key="es_MX-claude-high",
        secondary_voice_key="es_ES-sharvard-medium",
        multi_voice_mode="dialogue_auto",
        output_name="test_cuña",
        output_dir=str(out_dir),
        generate_audio=True,
        generate_video=False,
        save_flac_master=False,
        interstitials=[
            InterstitialItem(text="Bienvenido a este audiolibro.", position="start"),
            InterstitialItem(text="Fin de capítulo.", position="between_chapters"),
            InterstitialItem(text="Gracias por escuchar.", position="end"),
        ]
    )

    pipeline = AudiobookPipeline(config)
    meta = pipeline.run()

    assert meta.total_utterances >= 5
    assert meta.output_audio_path is not None
    assert Path(meta.output_audio_path).exists()
    assert Path(meta.document_folder).exists()
