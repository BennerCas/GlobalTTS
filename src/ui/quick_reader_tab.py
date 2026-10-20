"""Pestaña de Lectura Rápida y Suite de Configuración Profesional para GlobalTTS.

Incluye:
- Lector rápido con caja de texto y scroll invisible para pegar y escuchar inmediatamente.
- Suite de Expresividad y Modo Narración con Mistral NeMo 12B local (11 estilos CO-STAR, 4 modos).
- Controles de reproducción instantánea con Piper TTS local (100% offline).
- Suite de configuración profesional: voces locales, velocidad, volumen, directorios.
- Gestión de atajos globales de AutoHotkey v2 (Texto + Click Izq + Espacio).
- Inicio automático con Windows (abriendo la ventana al arrancar la PC).
- Metadatos con firma institucional 'HUMAN AI SYNERGY BY BENNER CASTILLO'.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import sounddevice as sd

from src.ai.nemo_enhancer import MistralNeMoEnhancer, NarrationConfig
from src.ai.piper_engine import PiperTtsEngine, list_available_piper_voices
from src.ai.prompt_library import PromptLibrary
from src.core.text_clean import clean_text_for_tts, make_filename_slug
from src.markup.style import Style

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"


def get_startup_file_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / r"Microsoft\Windows\Start Menu\Programs\Startup\GlobalTTS.bat"
    return Path.home() / r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\GlobalTTS.bat"


def is_startup_enabled() -> bool:
    return get_startup_file_path().exists()


def set_startup_enabled(enable: bool):
    p = get_startup_file_path()
    if enable:
        p.parent.mkdir(parents=True, exist_ok=True)
        iniciar_bat = PROJECT_ROOT / "INICIAR_TTS.bat"
        content = f'@echo off\r\nstart "" "{iniciar_bat}"\r\n'
        p.write_text(content, encoding="utf-8")
    else:
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass


class TtsWorkerSignals(QObject):
    started = pyqtSignal()
    finished = pyqtSignal()
    error = pyqtSignal(str)


class TtsPlayWorker(QThread):
    def __init__(self, text: str, voice_key: str, speed: float, volume: float):
        super().__init__()
        self.text = text
        self.voice_key = voice_key
        self.speed = speed
        self.volume = volume
        self.signals = TtsWorkerSignals()
        self.is_interrupted = False

    def run(self):
        try:
            self.signals.started.emit()
            engine = PiperTtsEngine(voice_key=self.voice_key)
            style = Style(speed=self.speed)
            samples = engine.synthesize(self.text, style=style)

            if self.volume != 1.0:
                samples = samples * self.volume

            if not self.is_interrupted:
                sd.play(samples, engine.sample_rate)
                sd.wait()
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit(str(e))


class AiEnhanceWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, text: str, config: NarrationConfig):
        super().__init__()
        self.text = text
        self.config = config

    def run(self):
        try:
            enhancer = MistralNeMoEnhancer()
            if not enhancer.is_available():
                self.error.emit("Ollama o el modelo Mistral NeMo local no están disponibles en http://localhost:11434.")
                return

            res = enhancer.process(self.text, self.config)
            if isinstance(res, dict):
                seg_texts = []
                for seg in res.get("segments", []):
                    st = seg.get("text", "")
                    emo = seg.get("emotion")
                    if emo and emo not in ("neutral", ""):
                        st = f"[{emo}]{st}[/{emo}]"
                    seg_texts.append(st)
                result_text = " ".join(seg_texts) if seg_texts else self.text
            else:
                result_text = res
            self.finished.emit(result_text)
        except Exception as e:
            self.error.emit(str(e))


class QuickReaderTab(QWidget):
    """Pestaña de Lectura Rápida y Configuración Profesional con Expresividad IA."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.play_worker: Optional[TtsPlayWorker] = None
        self.ai_worker: Optional[AiEnhanceWorker] = None
        self.prompt_library = PromptLibrary()
        self.config = self.load_config_values()
        self.init_ui()

    def load_config_values(self) -> dict:
        default_cfg = {
            "voice": "es_MX-claude-high",
            "speed_factor": 1.0,
            "volume": 100,
            "save_directory": str(Path.home() / "Downloads" / "TTS_Audios"),
            "auto_translate_en": True,
            "enable_escape_to_stop": True,
            "enable_alt_space_fallback": True,
            "enable_save_hotkey": True,
            "start_with_windows": True,
            "firma": "HUMAN AI SYNERGY BY BENNER CASTILLO"
        }
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    default_cfg.update(data)
            except Exception:
                pass
        return default_cfg

    def init_ui(self):
        # Usar diseño de 2 columnas para aprovechar toda la pantalla sin barras de desplazamiento
        columns_layout = QHBoxLayout(self)
        columns_layout.setContentsMargins(10, 10, 10, 10)
        columns_layout.setSpacing(12)

        # =========================================================================
        # COLUMNA IZQUIERDA: LECTOR RÁPIDO & EXPRESIVIDAD IA (55% espacio)
        # =========================================================================
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        # 1. Tarjeta de Lector Rápido
        reader_box = QFrame()
        reader_box.setObjectName("cardFrame")
        r_lay = QVBoxLayout(reader_box)
        r_lay.setContentsMargins(12, 12, 12, 12)
        r_lay.setSpacing(8)

        # Cabecera
        header_row = QHBoxLayout()
        title_lbl = QLabel("⚡ Lector Rápido en Tiempo Real")
        title_lbl.setObjectName("titleLabel")
        header_row.addWidget(title_lbl)

        self.lbl_status = QLabel("● Listo (Motor Piper Local Activo)")
        self.lbl_status.setStyleSheet("color: #3fb950; font-weight: 600; font-size: 11px;")
        header_row.addWidget(self.lbl_status, alignment=Qt.AlignmentFlag.AlignRight)
        r_lay.addLayout(header_row)

        desc_lbl = QLabel(
            "Pega texto aquí para lectura instantánea offline, o usa el atajo en cualquier app: "
            "Texto seleccionado + Click Izq + Barra Espaciadora."
        )
        desc_lbl.setObjectName("subtitleLabel")
        desc_lbl.setWordWrap(True)
        r_lay.addWidget(desc_lbl)

        # Caja de texto con scroll invisible
        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("quickTextBox")
        self.text_edit.setPlaceholderText("Pega o escribe aquí cualquier texto para escucharlo o enriquecerlo con IA...")
        self.text_edit.textChanged.connect(self.on_text_changed)

        # Ocultar visualmente la barra de desplazamiento manteniendo el scroll funcional
        self.text_edit.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                width: 0px;
                height: 0px;
                background: transparent;
            }
        """)
        self.text_edit.horizontalScrollBar().setStyleSheet("""
            QScrollBar:horizontal {
                width: 0px;
                height: 0px;
                background: transparent;
            }
        """)
        r_lay.addWidget(self.text_edit, stretch=1)

        # Barra de información de texto
        info_row = QHBoxLayout()
        self.lbl_counter = QLabel("Caracteres: 0 | Palabras: 0 | Duración est.: ~0s")
        self.lbl_counter.setStyleSheet("color: #8b949e; font-size: 11px;")
        info_row.addWidget(self.lbl_counter)
        r_lay.addLayout(info_row)

        # Botonera de acciones
        btns_row = QHBoxLayout()
        btns_row.setSpacing(6)

        self.btn_play = QPushButton("▶️ Leer en Voz Alta")
        self.btn_play.setObjectName("primaryButton")
        self.btn_play.clicked.connect(self.play_text)
        btns_row.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⏹️ Detener")
        self.btn_stop.setObjectName("secondaryActionButton")
        self.btn_stop.clicked.connect(self.stop_text)
        btns_row.addWidget(self.btn_stop)

        self.btn_paste = QPushButton("📋 Pegar")
        self.btn_paste.setObjectName("actionButton")
        self.btn_paste.clicked.connect(self.paste_clipboard)
        btns_row.addWidget(self.btn_paste)

        self.btn_clear = QPushButton("🗑️ Limpiar")
        self.btn_clear.setObjectName("secondaryActionButton")
        self.btn_clear.clicked.connect(self.text_edit.clear)
        btns_row.addWidget(self.btn_clear)

        self.btn_save_mp3 = QPushButton("💾 Guardar MP3")
        self.btn_save_mp3.setObjectName("secondaryActionButton")
        self.btn_save_mp3.clicked.connect(self.save_text_mp3)
        btns_row.addWidget(self.btn_save_mp3)

        r_lay.addLayout(btns_row)
        left_col.addWidget(reader_box, stretch=3)

        # 2. Tarjeta de Expresividad y Modo Narración (Mistral NeMo Local)
        ai_box = QGroupBox("🧠 Expresividad y Modo Narración (Mistral NeMo 12B Local)")
        ai_lay = QVBoxLayout(ai_box)
        ai_lay.setContentsMargins(10, 10, 10, 10)
        ai_lay.setSpacing(8)

        self.chk_ai_enabled = QCheckBox("Activar Enriquecimiento / Modo Narración con IA")
        self.chk_ai_enabled.toggled.connect(self.toggle_ai_panel)
        ai_lay.addWidget(self.chk_ai_enabled)

        self.ai_controls_frame = QFrame()
        ai_ctrl_lay = QVBoxLayout(self.ai_controls_frame)
        ai_ctrl_lay.setContentsMargins(0, 0, 0, 0)
        ai_ctrl_lay.setSpacing(6)

        # Fila 1: Modo y Estilo
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Modo IA:"))
        self.combo_ai_mode = QComboBox()
        self.combo_ai_mode.addItem("Enriquecer prosodia ([pausa], [lento], [énfasis])", "enhance")
        self.combo_ai_mode.addItem("Modo Narrador (reescritura literaria oral)", "rewrite")
        self.combo_ai_mode.addItem("Traducción & Adaptación es-LA", "translate")
        self.combo_ai_mode.addItem("Análisis de Diálogos y Emociones", "dialogue_analysis")
        row1.addWidget(self.combo_ai_mode, stretch=1)

        row1.addWidget(QLabel("Estilo:"))
        self.combo_ai_style = QComboBox()
        for st in self.prompt_library.list_styles():
            self.combo_ai_style.addItem(st.name, st.id)
        row1.addWidget(self.combo_ai_style, stretch=1)
        ai_ctrl_lay.addLayout(row1)

        # Fila 2: Perspectiva y Tiempo verbal
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Perspectiva:"))
        self.combo_persona = QComboBox()
        self.combo_persona.addItem("1ra Persona (Yo)", "1ra")
        self.combo_persona.addItem("2da Persona (Tú/Usted)", "2da")
        self.combo_persona.addItem("3ra Persona (Él/Ella/Narrador)", "3ra")
        self.combo_persona.setCurrentIndex(2)
        row2.addWidget(self.combo_persona)

        row2.addWidget(QLabel("Tiempo:"))
        self.combo_tense = QComboBox()
        self.combo_tense.addItem("Pasado (pretérito)", "pasado")
        self.combo_tense.addItem("Presente (en vivo)", "presente")
        self.combo_tense.addItem("Presente Continuo", "presente_continuo")
        self.combo_tense.addItem("Futuro", "futuro")
        row2.addWidget(self.combo_tense)

        self.btn_apply_ai = QPushButton("✨ Aplicar Expresividad / Narrar al Texto")
        self.btn_apply_ai.setObjectName("actionButton")
        self.btn_apply_ai.clicked.connect(self.apply_ai_enhancement)
        row2.addWidget(self.btn_apply_ai)

        ai_ctrl_lay.addLayout(row2)
        self.ai_controls_frame.setEnabled(False)
        ai_lay.addWidget(self.ai_controls_frame)

        left_col.addWidget(ai_box, stretch=1)
        columns_layout.addLayout(left_col, stretch=55)

        # =========================================================================
        # COLUMNA DERECHA: SUITE DE CONFIGURACIÓN Y ATAJOS (45% espacio)
        # =========================================================================
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        # 1. Configuración de Voz y Audio
        voice_box = QGroupBox("🎙️ Motor de Voz Local & Modulación")
        v_lay = QVBoxLayout(voice_box)
        v_lay.setContentsMargins(10, 10, 10, 10)
        v_lay.setSpacing(8)

        v_row1 = QHBoxLayout()
        v_row1.addWidget(QLabel("Voz Local:"))
        self.voice_combo = QComboBox()
        self.populate_voices()
        v_row1.addWidget(self.voice_combo, stretch=1)

        self.btn_test_voice = QPushButton("🔊 Probar")
        self.btn_test_voice.setObjectName("secondaryActionButton")
        self.btn_test_voice.clicked.connect(self.test_voice_sample)
        v_row1.addWidget(self.btn_test_voice)
        v_lay.addLayout(v_row1)

        # Slider de Velocidad
        spd_row = QHBoxLayout()
        self.lbl_speed = QLabel("Velocidad: 1.0x (Normal)")
        self.lbl_speed.setMinimumWidth(150)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(5, 25)
        spd_val = int(float(self.config.get("speed_factor", 1.0)) * 10)
        self.speed_slider.setValue(spd_val)
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        spd_row.addWidget(self.lbl_speed)
        spd_row.addWidget(self.speed_slider)
        v_lay.addLayout(spd_row)

        # Slider de Volumen
        vol_row = QHBoxLayout()
        self.lbl_vol = QLabel("Volumen: 100%")
        self.lbl_vol.setMinimumWidth(150)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 150)
        vol_init = int(self.config.get("volume", 100)) if isinstance(self.config.get("volume"), (int, float)) else 100
        self.vol_slider.setValue(vol_init)
        self.vol_slider.valueChanged.connect(self.on_volume_changed)
        vol_row.addWidget(self.lbl_vol)
        vol_row.addWidget(self.vol_slider)
        v_lay.addLayout(vol_row)

        # Directorio de guardado
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Guardar en:"))
        self.dir_edit = QLineEdit(self.config.get("save_directory", str(Path.home() / "Downloads" / "TTS_Audios")))
        dir_row.addWidget(self.dir_edit, stretch=1)
        btn_browse_dir = QPushButton("📂")
        btn_browse_dir.setObjectName("secondaryActionButton")
        btn_browse_dir.clicked.connect(self.browse_save_dir)
        dir_row.addWidget(btn_browse_dir)
        v_lay.addLayout(dir_row)

        right_col.addWidget(voice_box)

        # 2. Atajos Globales de Teclado
        hk_box = QGroupBox("⌨️ Atajos Globales Activos (AutoHotkey v2)")
        hk_lay = QVBoxLayout(hk_box)
        hk_lay.setContentsMargins(10, 10, 10, 10)
        hk_lay.setSpacing(6)

        self.lbl_ahk_status = QLabel("🟢 Servicio de Atajos Globales Operativo")
        self.lbl_ahk_status.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 11px;")
        hk_lay.addWidget(self.lbl_ahk_status)

        shortcuts_info = QLabel(
            "• Texto Seleccionado + Click Izq + Espacio: Lectura en voz alta instantánea.\n"
            "• Arrastre sobre texto + Soltar + Espacio (<1.3s): Lectura inmediata.\n"
            "• Alt + Espacio: Atajo alternativo universal.\n"
            "• Click Izq + S / Alt + S: Guardar selección en MP3 con metadatos.\n"
            "• Escape (Esc): Detener reproducción activa.\n"
            "• Alt + Rueda del Ratón: Ajustar velocidad al vuelo."
        )
        shortcuts_info.setStyleSheet("color: #8b949e; font-size: 11px; line-height: 1.4;")
        hk_lay.addWidget(shortcuts_info)

        btn_reload_ahk = QPushButton("🔄 Reiniciar Servicio de Atajos")
        btn_reload_ahk.setObjectName("secondaryActionButton")
        btn_reload_ahk.clicked.connect(self.restart_ahk_service)
        hk_lay.addWidget(btn_reload_ahk, alignment=Qt.AlignmentFlag.AlignLeft)

        right_col.addWidget(hk_box)

        # 3. Preferencias del Sistema
        sys_box = QGroupBox("⚙️ Sistema, Arranque & Metadatos")
        s_lay = QVBoxLayout(sys_box)
        s_lay.setContentsMargins(10, 10, 10, 10)
        s_lay.setSpacing(6)

        self.chk_startup = QCheckBox("Iniciar con Windows automáticamente (abrir la app)")
        self.chk_startup.setChecked(is_startup_enabled() or bool(self.config.get("start_with_windows", True)))
        s_lay.addWidget(self.chk_startup)

        self.chk_translate = QCheckBox("Traducir automáticamente al español textos en inglés")
        self.chk_translate.setChecked(bool(self.config.get("auto_translate_en", True)))
        s_lay.addWidget(self.chk_translate)

        lbl_sig = QLabel("Firma en Metadatos: HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®")
        lbl_sig.setStyleSheet("color: #58a6ff; font-size: 11px; font-weight: 600;")
        s_lay.addWidget(lbl_sig)

        btn_save_cfg = QPushButton("💾 Guardar Configuración Predeterminada")
        btn_save_cfg.setObjectName("primaryButton")
        btn_save_cfg.clicked.connect(self.save_all_settings)
        s_lay.addWidget(btn_save_cfg)

        right_col.addWidget(sys_box)
        right_col.addStretch()

        columns_layout.addLayout(right_col, stretch=45)

    def toggle_ai_panel(self, checked: bool):
        self.ai_controls_frame.setEnabled(checked)

    def populate_voices(self):
        self.voice_combo.clear()
        voices = list_available_piper_voices()
        current_voice = self.config.get("voice", "es_MX-claude-high")

        idx_to_select = 0
        for i, (key, profile) in enumerate(voices.items()):
            label = f"{key} ({profile.language.upper()}, {profile.sample_rate // 1000}kHz)"
            self.voice_combo.addItem(label, key)
            if key == current_voice:
                idx_to_select = i

        if self.voice_combo.count() > 0:
            self.voice_combo.setCurrentIndex(idx_to_select)

    def on_text_changed(self):
        text = self.text_edit.toPlainText().strip()
        num_chars = len(text)
        num_words = len(text.split()) if text else 0
        est_sec = int((num_words / 150) * 60)
        est_time_str = f"{est_sec // 60}m {est_sec % 60}s" if est_sec >= 60 else f"{est_sec}s"
        self.lbl_counter.setText(f"Caracteres: {num_chars:,} | Palabras: {num_words:,} | Duración est.: ~{est_time_str}")

    def on_speed_changed(self, val: int):
        speed = val / 10.0
        label_text = f"Velocidad: {speed:.1f}x "
        if speed == 1.0:
            label_text += "(Normal)"
        elif speed < 1.0:
            label_text += "(Lento)"
        else:
            label_text += "(Rápido)"
        self.lbl_speed.setText(label_text)

    def on_volume_changed(self, val: int):
        self.lbl_vol.setText(f"Volumen: {val}%")

    def paste_clipboard(self):
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            self.text_edit.setText(text)

    def apply_ai_enhancement(self):
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Texto Vacío", "Por favor pega o escribe texto antes de aplicar IA.")
            return

        cfg = NarrationConfig(
            enabled=True,
            mode=self.combo_ai_mode.currentData(),
            persona=self.combo_persona.currentData(),
            tense=self.combo_tense.currentData(),
            style=self.combo_ai_style.currentData(),
        )

        self.btn_apply_ai.setEnabled(False)
        self.btn_apply_ai.setText("✨ Analizando con Mistral NeMo...")
        self.lbl_status.setText("● Procesando con IA (Mistral NeMo 12B local)...")
        self.lbl_status.setStyleSheet("color: #a371f7; font-weight: 600;")

        self.ai_worker = AiEnhanceWorker(text, cfg)
        self.ai_worker.finished.connect(self.on_ai_finished)
        self.ai_worker.error.connect(self.on_ai_error)
        self.ai_worker.start()

    def on_ai_finished(self, enhanced_text: str):
        self.text_edit.setPlainText(enhanced_text)
        self.btn_apply_ai.setEnabled(True)
        self.btn_apply_ai.setText("✨ Aplicar Expresividad / Narrar al Texto")
        self.lbl_status.setText("● Texto enriquecido exitosamente con IA")
        self.lbl_status.setStyleSheet("color: #3fb950; font-weight: 600;")

    def on_ai_error(self, err_msg: str):
        self.btn_apply_ai.setEnabled(True)
        self.btn_apply_ai.setText("✨ Aplicar Expresividad / Narrar al Texto")
        self.lbl_status.setText("● Error en análisis de IA")
        self.lbl_status.setStyleSheet("color: #f85149; font-weight: 600;")
        QMessageBox.warning(self, "Aviso de IA", f"No se pudo completar el análisis con IA:\n{err_msg}")

    def play_text(self):
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Texto Vacío", "Por favor escribe o pega texto para escuchar.")
            return

        self.stop_text()

        voice_key = self.voice_combo.currentData() or "es_MX-claude-high"
        speed = self.speed_slider.value() / 10.0
        volume = self.vol_slider.value() / 100.0

        self.btn_play.setEnabled(False)
        self.btn_play.setText("🔊 Reproduciendo...")
        self.lbl_status.setText("● Reproduciendo en voz alta...")
        self.lbl_status.setStyleSheet("color: #e3b341; font-weight: 600;")

        self.play_worker = TtsPlayWorker(text=text, voice_key=voice_key, speed=speed, volume=volume)
        self.play_worker.signals.finished.connect(self.on_play_finished)
        self.play_worker.signals.error.connect(self.on_play_error)
        self.play_worker.start()

    def stop_text(self):
        if self.play_worker and self.play_worker.isRunning():
            self.play_worker.is_interrupted = True
            try:
                sd.stop()
            except Exception:
                pass
            self.play_worker.terminate()
            self.play_worker.wait(500)
            self.play_worker = None
        else:
            try:
                sd.stop()
            except Exception:
                pass

        self.on_play_finished()

    def on_play_finished(self):
        self.btn_play.setEnabled(True)
        self.btn_play.setText("▶️ Leer en Voz Alta")
        self.lbl_status.setText("● Listo (Motor Piper Local Activo)")
        self.lbl_status.setStyleSheet("color: #3fb950; font-weight: 600;")

    def on_play_error(self, err_msg: str):
        self.on_play_finished()
        QMessageBox.warning(self, "Error de Síntesis", f"Ocurrió un error al reproducir:\n{err_msg}")

    def test_voice_sample(self):
        voice_key = self.voice_combo.currentData() or "es_MX-claude-high"
        test_phrase = "Hola, esta es una prueba de la voz local configurada en GlobalTTS."
        try:
            sd.stop()
            engine = PiperTtsEngine(voice_key=voice_key)
            samples = engine.synthesize(test_phrase, style=Style(speed=self.speed_slider.value() / 10.0))
            vol = self.vol_slider.value() / 100.0
            if vol != 1.0:
                samples = samples * vol
            sd.play(samples, engine.sample_rate)
        except Exception as e:
            QMessageBox.warning(self, "Error al probar voz", f"No se pudo sintetizar la muestra:\n{e}")

    def save_text_mp3(self):
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Texto Vacío", "No hay texto para guardar.")
            return

        target_dir = Path(self.dir_edit.text().strip() or (Path.home() / "Downloads" / "TTS_Audios"))
        target_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        fecha_str = now.strftime("%Y-%m-%d")
        hora_str = now.strftime("%H:%M:%S")

        slug = make_filename_slug(text, max_words=5, max_len=40)
        filename_mp3 = f"TTS_{timestamp}_{slug}.mp3"
        filepath_mp3 = target_dir / filename_mp3
        temp_wav = target_dir / f"temp_{timestamp}_{slug}.wav"

        voice_key = self.voice_combo.currentData() or "es_MX-claude-high"
        speed = self.speed_slider.value() / 10.0

        try:
            import soundfile as sf
            engine = PiperTtsEngine(voice_key=voice_key)
            samples = engine.synthesize(text, style=Style(speed=speed))
            vol = self.vol_slider.value() / 100.0
            if vol != 1.0:
                samples = samples * vol
            sf.write(str(temp_wav), samples, engine.sample_rate)

            dur_s = len(samples) / float(engine.sample_rate)
            dur_fmt = time.strftime("%H:%M:%S", time.gmtime(dur_s))
            firma_str = "HUMAN AI SYNERGY BY BENNER CASTILLO"

            cflags = 0x08000000 if sys.platform == "win32" else 0
            cmd = [
                "ffmpeg", "-y",
                "-i", str(temp_wav),
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-codec:a", "libmp3lame",
                "-b:a", "256k",
                "-metadata", f"artist={firma_str}",
                "-metadata", f"album_artist={firma_str}",
                "-metadata", f"title={slug.replace('_', ' ').title()}",
                "-metadata", f"date={fecha_str}",
                "-metadata", f"comment=Firma: {firma_str} | Fecha: {fecha_str} {hora_str} | Duración: {dur_fmt}",
                "-metadata", f"copyright={firma_str} - 2026®",
                str(filepath_mp3)
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=cflags)

            if temp_wav.exists():
                try:
                    temp_wav.unlink()
                except Exception:
                    pass

            tamano_bytes = filepath_mp3.stat().st_size if filepath_mp3.exists() else 0
            tamano_mb = f"{tamano_bytes / (1024 * 1024):.2f} MB"

            # Metadatos JSON complementarios
            meta_json = target_dir / f"TTS_{timestamp}_{slug}_metadata.json"
            meta_dict = {
                "firma": firma_str,
                "fecha": fecha_str,
                "hora": hora_str,
                "tiempo_duracion_segundos": round(dur_s, 2),
                "tiempo_duracion_formato": dur_fmt,
                "tamano_bytes": tamano_bytes,
                "tamano_mb": tamano_mb,
                "modelo_tts": f"Piper ({voice_key})",
                "velocidad": speed,
                "texto_origen": text[:200]
            }
            with open(meta_json, "w", encoding="utf-8") as f:
                json.dump(meta_dict, f, indent=2, ensure_ascii=False)

            QMessageBox.information(
                self,
                "Audio Guardado",
                f"✅ Archivo MP3 guardado exitosamente:\n\n{filepath_mp3}\n\n"
                f"Duración: {dur_fmt} | Tamaño: {tamano_mb}\n"
                f"Firma: {firma_str}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error al guardar MP3", f"No se pudo generar el archivo:\n{e}")

    def browse_save_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta para audios rápidos")
        if d:
            self.dir_edit.setText(d)

    def restart_ahk_service(self):
        try:
            ahk_exe = r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"
            ahk_script = PROJECT_ROOT / "global_tts.ahk"
            subprocess.run(["taskkill", "/F", "/IM", "AutoHotkey64.exe"], capture_output=True)
            time.sleep(0.3)
            subprocess.Popen([ahk_exe, str(ahk_script)])
            QMessageBox.information(self, "Atajos Reiniciados", "El servicio de atajos globales de AutoHotkey se ha reiniciado correctamente.")
        except Exception as e:
            QMessageBox.warning(self, "Aviso", f"No se pudo reiniciar AutoHotkey automáticamente:\n{e}")

    def save_all_settings(self):
        cfg = {
            "voice": self.voice_combo.currentData(),
            "speed_factor": self.speed_slider.value() / 10.0,
            "volume": self.vol_slider.value(),
            "save_directory": self.dir_edit.text().strip(),
            "auto_translate_en": self.chk_translate.isChecked(),
            "enable_escape_to_stop": True,
            "enable_alt_space_fallback": True,
            "enable_save_hotkey": True,
            "start_with_windows": self.chk_startup.isChecked(),
            "firma": "HUMAN AI SYNERGY BY BENNER CASTILLO"
        }

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Fallo al guardar config.json: {e}")
            return

        set_startup_enabled(self.chk_startup.isChecked())

        QMessageBox.information(
            self,
            "Configuración Guardada",
            "✅ La configuración se ha guardado correctamente.\n\n"
            f"Voz: {cfg['voice']}\n"
            f"Velocidad: {cfg['speed_factor']}x\n"
            f"Volumen: {cfg['volume']}%\n"
            f"Inicio con Windows: {'Activado' if cfg['start_with_windows'] else 'Desactivado'}\n"
            f"Firma: HUMAN AI SYNERGY BY BENNER CASTILLO"
        )
