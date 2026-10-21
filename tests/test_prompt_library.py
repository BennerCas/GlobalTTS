"""Tests unitarios exhaustivos para el Gestor de Prompts Maestros,

Estilos Narrativos CO-STAR y Cliente de Inferencia Mistral NeMo.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ai.nemo_enhancer import MistralNeMoEnhancer, NarrationConfig
from src.ai.prompt_library import (
    NarrativeStyleDef,
    PromptItem,
    PromptLibrary,
)


@pytest.fixture
def temp_library(tmp_path: Path) -> PromptLibrary:
    """Crea una instancia aislada de PromptLibrary en directorio temporal."""
    json_path = tmp_path / "prompts_test.json"
    return PromptLibrary(json_path=json_path)


def test_catalog_contains_all_required_modes(temp_library: PromptLibrary):
    modes = temp_library.list_modes()
    mode_keys = [m.mode_key for m in modes]

    assert "enhance" in mode_keys
    assert "rewrite" in mode_keys
    assert "translate" in mode_keys
    assert "dialogue_analysis" in mode_keys

    # Verificar que el active_configuration apunte a los identificadores correctos
    assert temp_library.get_active_prompt_id("enhance") == "builtin_enhance"
    assert temp_library.get_active_prompt_id("rewrite") == "builtin_rewrite"
    assert temp_library.get_active_prompt_id("translate") == "builtin_translate"
    assert temp_library.get_active_prompt_id("dialogue_analysis") == "builtin_dialogue_analysis"


def test_catalog_contains_all_11_narrative_styles(temp_library: PromptLibrary):
    expected_styles = [
        "cuento",
        "historia",
        "suceso",
        "epico",
        "terror_psicologico",
        "ensayo_cientifico",
        "poetico_lirico",
        "infantil_fabula",
        "cyberpunk_scifi",
        "confesion_intima",
        "oratoria_motivacional",
        "cuentacuentos",
        "locutor_radio",
    ]

    registered_styles = temp_library.list_style_keys()
    for s in expected_styles:
        assert s in registered_styles, f"Estilo requerido faltante: {s}"
        style_def = temp_library.get_style(s)
        assert style_def is not None
        assert style_def.name
        assert style_def.tone
        assert style_def.cadence
        assert style_def.vocabulary_profile
        assert style_def.prosody_guidance
        # Verificar que tiene el framework CO-STAR
        assert "context" in style_def.costar_framework or "style" in style_def.costar_framework


def test_prompt_library_crud_operations(temp_library: PromptLibrary):
    # 1. Agregar prompt personalizado
    custom_item = PromptItem(
        id="custom_scifi_horror",
        category="custom",
        name="Sci-Fi Horror Thriller",
        description="Terror en estaciones espaciales abandonadas",
        system_prompt="Eres un narrador de horror cósmico en el espacio profundo.",
        user_template="Texto: {text}",
        parameters={"temperature": 0.5, "top_p": 0.95, "num_ctx": 4096},
    )
    temp_library.add_prompt(custom_item)
    assert temp_library.get_prompt("custom_scifi_horror") is not None

    # 2. Duplicar prompt
    cloned = temp_library.duplicate_prompt(
        source_id="custom_scifi_horror",
        new_id="custom_scifi_horror_v2",
        new_name="Sci-Fi Horror V2",
    )
    assert cloned.id == "custom_scifi_horror_v2"
    assert cloned.name == "Sci-Fi Horror V2"
    assert temp_library.get_prompt("custom_scifi_horror_v2") is not None

    # 3. Actualizar campos
    temp_library.update_prompt(
        "custom_scifi_horror_v2",
        description="Descripción actualizada",
        parameters={"temperature": 0.7, "top_p": 0.85, "num_ctx": 4096},
    )
    updated = temp_library.get_prompt("custom_scifi_horror_v2")
    assert updated.description == "Descripción actualizada"
    assert updated.parameters["temperature"] == 0.7

    # 4. Asignar como prompt activo para un modo
    temp_library.set_active_prompt("rewrite", "custom_scifi_horror_v2")
    assert temp_library.get_active_prompt_id("rewrite") == "custom_scifi_horror_v2"
    active_prompt = temp_library.get_mode_prompt("rewrite")
    assert active_prompt.id == "custom_scifi_horror_v2"

    # 5. Intentar eliminar un prompt built-in (debe levantar ValueError)
    with pytest.raises(ValueError, match="No se puede eliminar"):
        temp_library.delete_prompt("builtin_rewrite")

    # 6. Eliminar prompt personalizado
    assert temp_library.delete_prompt("custom_scifi_horror_v2") is True
    assert temp_library.get_prompt("custom_scifi_horror_v2") is None
    # Como era el activo, debe haberse revertido al default
    assert temp_library.get_active_prompt_id("rewrite") == "builtin_rewrite"


def test_prompt_library_reset_to_defaults(temp_library: PromptLibrary):
    # Modificar o añadir un prompt
    temp_library.add_prompt(
        PromptItem(
            id="temp_item",
            category="custom",
            name="Temporal",
            description="",
            system_prompt="",
        )
    )
    assert temp_library.get_prompt("temp_item") is not None

    # Resetear
    temp_library.reset_to_defaults()
    assert temp_library.get_prompt("temp_item") is None
    assert len(temp_library.list_modes()) == 4
    assert len(temp_library.list_styles()) >= 11


def test_safe_format_and_interpolation(temp_library: PromptLibrary):
    template = "Hola {nombre}, bienvenido a {lugar}. {missing_key}"
    result = temp_library.safe_format(template, nombre="Carlos", lugar="la nave")
    assert "Hola Carlos, bienvenido a la nave." in result
    # Llave no provista queda vacía
    assert "{missing_key}" not in result

    # Texto con llaves no deseadas o código
    text_with_braces = "Variables en python: {a + b} y {json: true}"
    formatted = temp_library.safe_format("Procesar:\n{text}", text=text_with_braces)
    assert text_with_braces in formatted


def test_build_prompt_for_mode_with_costar(temp_library: PromptLibrary):
    sys_prompt, user_prompt, params = temp_library.build_prompt_for_mode(
        mode="rewrite",
        text="La tripulación detectó una anomalía en el reactor.",
        persona="1ra",
        tense="presente",
        style="cyberpunk_scifi",
    )

    assert "Primera persona" in sys_prompt
    assert "Tiempo presente" in sys_prompt
    assert "Cyberpunk" in sys_prompt
    assert "La tripulación detectó una anomalía" in user_prompt
    assert params.get("num_ctx") == 4096


def test_nemo_enhancer_methods_with_mock():
    library = PromptLibrary()
    enhancer = MistralNeMoEnhancer(prompt_library=library)

    # 1. Enriquecimiento prosódico
    with patch.object(enhancer, "_call_ollama", return_value="El viajero [pausa:500ms] caminó en silencio."):
        res = enhancer.enhance_expressiveness("El viajero caminó en silencio.")
        assert "[pausa:500ms]" in res

    # 2. Reescritura narrativa
    cfg = NarrationConfig(enabled=True, mode="rewrite", persona="1ra", tense="pasado", style="epico")
    with patch.object(enhancer, "_call_ollama", return_value="Cabalgué hacia el horizonte [enfasis]con gloria[/enfasis]."):
        res = enhancer.rewrite_as_narration("El héroe cabalgó hacia el horizonte.", cfg)
        assert "[enfasis]con gloria[/enfasis]" in res

    # 3. Traducción y adaptación es-LA
    with patch.object(enhancer, "_call_ollama", return_value="Hola, ¿cómo estás el día de hoy?"):
        res = enhancer.translate_and_adapt("Hello, how are you today?", target_lang="es-LA")
        assert res == "Hola, ¿cómo estás el día de hoy?"

    # 4. Análisis dramático de diálogos
    sample_json = json.dumps({
        "characters": [{"name": "Guardia", "gender": "male", "tone": "firme"}],
        "segments": [
            {
                "speaker": "Guardia",
                "type": "dialogue",
                "text": "—¡Alto ahí!—",
                "emotion": "enojado",
                "suggested_tags": ["[enfasis]"],
            }
        ]
    })
    with patch.object(enhancer, "_call_ollama", return_value=sample_json):
        analysis = enhancer.analyze_dialogues("—¡Alto ahí!— gritó el guardia.")
        assert "characters" in analysis
        assert analysis["characters"][0]["name"] == "Guardia"
        assert analysis["segments"][0]["emotion"] == "enojado"

    # 5. Fallback seguro ante fallo de JSON en dialogue_analysis
    with patch.object(enhancer, "_call_ollama", return_value="Respuesta no JSON inválida"):
        fallback_res = enhancer.analyze_dialogues("Texto sin formato")
        assert "characters" in fallback_res
        assert fallback_res["segments"][0]["text"] == "Texto sin formato"


def test_prompt_library_markdown_roundtrip(tmp_path: Path):
    """Verifica la exportación e importación bidireccional entre PromptLibrary y Markdown."""
    json_path = tmp_path / "prompts_roundtrip.json"
    lib1 = PromptLibrary(json_path=json_path)

    # Exportar a Markdown
    md_path = tmp_path / "PROMPTS_TEST.md"
    lib1.export_to_markdown(md_path)
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "Catálogo Maestro de Modos de IA" in content
    assert "Estilos Narrativos Industriales" in content

    # Crear una nueva librería vacía e importar desde el Markdown generado
    json_path2 = tmp_path / "prompts_imported.json"
    lib2 = PromptLibrary(json_path=json_path2)
    # Modificar un parámetro antes de importar para comprobar sobreescritura
    lib2.modes["builtin_enhance"].parameters["temperature"] = 0.99

    count = lib2.import_from_markdown(md_path)
    assert count >= 15
    # Comprobar que temperature se restauró al valor del markdown
    assert lib2.modes["builtin_enhance"].parameters["temperature"] == 0.35
    assert len(lib2.styles) == len(lib1.styles)
    assert lib2.get_style("terror_psicologico") is not None


def test_nemo_enhancer_live_call_if_available():
    """Ejecuta una inferencia real contra Ollama si mistral-nemo-local está corriendo."""
    enhancer = MistralNeMoEnhancer()
    if not enhancer.is_available():
        pytest.skip("Ollama o mistral-nemo-local:latest no está disponible en este entorno.")

    # Inferencia real breve
    text = "El silencio reinaba en la vieja biblioteca de madera."
    result = enhancer.enhance_expressiveness(text)

    # Verificar que devolvió una cadena válida no vacía
    assert isinstance(result, str)
    assert len(result) > 10
    # No debe contener etiquetas de pensamiento no limpiadas
    assert "<thinking>" not in result
