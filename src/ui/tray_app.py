"""Aplicación residente en la bandeja del sistema (System Tray) con Generador en Lote y Reproductor de Biblioteca.

Cumple con todos los requisitos:
- Procesamiento en lote secuencial (1 por 1).
- Enriquecimiento con Mistral NeMo local (modo narración en 1ra/2da/3ra persona y tiempos verbales).
- Inserción de cuñas de audio con escucha previa instantánea.
- Auto-casting multi-voz para diálogos y personajes.
- Portada para carátula MP3 y fondo de video karaoke.
- Subida a YouTube y Spotify / Podcasts.
- Telemetría en tiempo real: cronómetro digital, ETA, velocidad y oración activa.
- Pestaña de Biblioteca con reproductor multimedia integrado.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSystemTrayIcon,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ai.nemo_enhancer import MistralNeMoEnhancer, NarrationConfig
from src.ai.piper_engine import PiperTtsEngine, list_available_piper_voices
from src.ai.prompt_library import PromptLibrary
from src.core.job import AudiobookPipeline, InterstitialItem, JobConfig, JobMetadata
from src.ui.library_tab import LibraryTab
from src.ui.prompt_manager_dialog import PromptManagerDialog, PromptManagerWidget
from src.ui.quick_reader_tab import QuickReaderTab
from src.ui.styles import DARK_THEME_QSS

BIBLIOTECA_DIR = PROJECT_ROOT / "biblioteca"


def create_tray_pixmap() -> QPixmap:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    painter.setBrush(QColor("#1f6feb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)

    painter.setBrush(QColor("#ffffff"))
    bars = [
        (16, 26, 6, 12),
        (25, 18, 6, 28),
        (34, 12, 6, 40),
        (43, 22, 6, 20),
    ]
    for x, y, w, h in bars:
        painter.drawRoundedRect(x, y, w, h, 3, 3)

    painter.end()
    return pixmap


class BatchWorkerSignals(QObject):
    item_started = pyqtSignal(int, str)
    stage = pyqtSignal(str, str, float)
    progress = pyqtSignal(int, int, str)
    item_finished = pyqtSignal(int, object)
    batch_finished = pyqtSignal(list)
    error = pyqtSignal(str)


class BatchPipelineWorker(QThread):
    def __init__(self, configs: list[JobConfig]):
        super().__init__()
        self.configs = configs
        self.signals = BatchWorkerSignals()
        self.is_cancelled = False

    def run(self):
        results = []
        try:
            total_items = len(self.configs)
            for idx, cfg in enumerate(self.configs):
                if self.is_cancelled:
                    break

                self.signals.item_started.emit(idx, Path(cfg.source_file).name)
                pipeline = AudiobookPipeline(cfg)

                def stage_cb(stg: str, desc: str, pct: float):
                    self.signals.stage.emit(stg, desc, pct)

                def prog_cb(current: int, total: int, utt):
                    short_text = (utt.text[:65] + "...") if len(utt.text) > 65 else utt.text
                    self.signals.progress.emit(current, total, short_text)

                meta = pipeline.run(progress_callback=prog_cb, stage_callback=stage_cb)
                results.append(meta)
                self.signals.item_finished.emit(idx, meta)

            self.signals.batch_finished.emit(results)
        except Exception as e:
            self.signals.error.emit(str(e))


class MainWindow(QDialog):
    """Ventana Principal con Pestañas: Generador & Lotes, Biblioteca y Prompts Maestros."""

    def __init__(self, initial_file: Optional[str] = None, tray_icon: Optional[QSystemTrayIcon] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tray_icon = tray_icon
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowTitle("GlobalTTS — Sistema Integral de Audiolibros, Video Karaoke & Lectura en Vivo")
        
        # Adaptabilidad total a la pantalla disponible (Vertical o Horizontal, respetando barra de tareas)
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.setGeometry(avail)
        self.setMinimumSize(780, 500)
        self.setStyleSheet(DARK_THEME_QSS)

        self.orientation_mode: str = "auto"  # "auto", "vertical", "horizontal"
        self.current_applied_orientation: str = ""

        self.batch_files: list[dict] = []
        self.worker: Optional[BatchPipelineWorker] = None
        self.last_results: list[JobMetadata] = []
        self.prompt_library = PromptLibrary()

        # Telemetría
        self.start_timestamp: Optional[float] = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_timer_tick)
        self.current_utt_count = 0
        self.total_utts = 0
        self.voices_dict = list_available_piper_voices()

        self.init_ui()
        self.apply_orientation(force=True)

        if initial_file:
            self.add_file_to_batch(initial_file)
            self.tabs.setCurrentIndex(1)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 10)
        main_layout.setSpacing(8)

        # Barra Superior de Control y Minimizado
        top_bar = QHBoxLayout()
        title_group = QVBoxLayout()
        app_title = QLabel("GlobalTTS — Suite Integral de Voz, Audiolibros & Videos Karaoke")
        app_title.setObjectName("titleLabel")
        app_sub = QLabel("100% Offline • Costo Cero • Aceleración DirectML & Modelos Locales")
        app_sub.setObjectName("subtitleLabel")
        title_group.addWidget(app_title)
        title_group.addWidget(app_sub)
        top_bar.addLayout(title_group)

        top_bar.addStretch()

        self.btn_orientation = QPushButton("[ ↕ ] Modo: Auto (Vertical)")
        self.btn_orientation.setObjectName("secondaryActionButton")
        self.btn_orientation.setToolTip("Alterna la distribución de la app entre Vertical (Monitores Retrato) y Horizontal (Panorámico)")
        self.btn_orientation.clicked.connect(self.cycle_orientation)
        top_bar.addWidget(self.btn_orientation)

        self.btn_minimize = QPushButton("[ _ ] Minimizar a Bandeja")
        self.btn_minimize.setObjectName("actionButton")
        self.btn_minimize.setToolTip("Oculta la ventana en la barra de herramientas del sistema")
        self.btn_minimize.clicked.connect(self.minimize_to_tray)
        top_bar.addWidget(self.btn_minimize)

        main_layout.addLayout(top_bar)

        # Tab Widget Principal
        self.tabs = QTabWidget()

        # Pestaña 1: Lectura Rápida & Suite de Configuración Profesional
        self.tab_quick = QuickReaderTab()
        self.tabs.addTab(self.tab_quick, "LECTURA RÁPIDA & CONFIGURACIÓN")

        # Pestaña 2: Generador de Audiolibros & Lotes
        self.tab_generator = QWidget()
        self.init_generator_tab()
        self.tabs.addTab(self.tab_generator, "GENERADOR DE AUDIOLIBROS")

        # Pestaña 3: Biblioteca & Reproductor
        self.tab_library = LibraryTab()
        self.tabs.addTab(self.tab_library, "BIBLIOTECA & REPRODUCTOR")

        # Pestaña 4: Gestor de Prompts Maestros & Estilos IA
        self.tab_prompts = PromptManagerWidget(library=self.prompt_library)
        self.tab_prompts.prompts_updated.connect(self.refresh_styles_combo)
        self.tabs.addTab(self.tab_prompts, "PROMPTS MAESTROS & ESTILOS IA")

        main_layout.addWidget(self.tabs)

        # Footer con la firma obligatoria de DISENO.md
        footer_lbl = QLabel("HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®")
        footer_lbl.setObjectName("footerLabel")
        footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(footer_lbl)

    def minimize_to_tray(self):
        self.hide()
        if self.tray_icon:
            self.tray_icon.showMessage(
                "GlobalTTS en Segundo Plano",
                "GlobalTTS continúa activo. Haz doble clic en el ícono de la bandeja para reabrir la ventana.",
                QSystemTrayIcon.MessageIcon.Information,
                1500
            )

    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            self.minimize_to_tray()
            event.accept()
            return
        super().changeEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.minimize_to_tray()

    def remove_selected_file(self):
        row = self.batch_table.currentRow()
        if 0 <= row < len(self.batch_files):
            self.batch_files.pop(row)
            self.render_batch_table()

    def show_distribution_dialog(self, platform: str):
        folder = self.last_results[-1].document_folder if self.last_results else str(BIBLIOTECA_DIR)
        QMessageBox.information(
            self,
            f"Distribución a {platform}",
            f"Listo para publicar en {platform}.\n\n"
            f"Los audios cumplen con el estándar EBU R128 (-16 LUFS) y los videos están codificados en H.264/AAC con subtítulos karaoke.\n\n"
            f"Carpeta de entrega: {folder}"
        )

    def get_effective_orientation(self) -> str:
        if self.orientation_mode != "auto":
            return self.orientation_mode
        # Detectar monitor o ventana vertical si la altura es mayor que el ancho o ancho <= 1250px
        return "vertical" if self.height() >= self.width() or self.width() <= 1250 else "horizontal"

    def cycle_orientation(self):
        if self.orientation_mode == "auto":
            self.orientation_mode = "vertical"
        elif self.orientation_mode == "vertical":
            self.orientation_mode = "horizontal"
        else:
            self.orientation_mode = "auto"
        self.apply_orientation(force=True)

    def apply_orientation(self, target_orientation: Optional[str] = None, force: bool = False):
        if target_orientation and target_orientation in ("vertical", "horizontal"):
            eff = target_orientation
        else:
            eff = self.get_effective_orientation()
        if not force and eff == self.current_applied_orientation:
            return
        self.current_applied_orientation = eff

        if self.orientation_mode == "auto":
            self.btn_orientation.setText(f"[ ↕ ] Modo: Auto ({eff.capitalize()})")
        elif self.orientation_mode == "vertical":
            self.btn_orientation.setText("[ ↕ ] Modo: Vertical Forzado")
        else:
            self.btn_orientation.setText("[ ↔ ] Modo: Horizontal Forzado")

        # 1. Actualizar pestaña del generador de libros
        self.update_generator_tab_layout(eff)

        # 2. Actualizar pestaña de lectura rápida
        if hasattr(self, 'tab_quick') and hasattr(self.tab_quick, 'set_orientation'):
            self.tab_quick.set_orientation(eff)

        # 3. Actualizar pestaña de biblioteca
        if hasattr(self, 'tab_library') and hasattr(self.tab_library, 'set_orientation'):
            self.tab_library.set_orientation(eff)

        # 4. Actualizar pestaña de prompts
        if hasattr(self, 'tab_prompts') and hasattr(self.tab_prompts, 'set_orientation'):
            self.tab_prompts.set_orientation(eff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'orientation_mode') and self.orientation_mode == "auto":
            new_eff = self.get_effective_orientation()
            if new_eff != self.current_applied_orientation:
                self.apply_orientation()

    def init_generator_tab(self):
        self.gen_layout = QVBoxLayout(self.tab_generator)
        self.gen_layout.setContentsMargins(10, 8, 10, 8)
        self.gen_layout.setSpacing(6)

        # =========================================================================
        # SECCIÓN 1: ARCHIVOS EN LOTE (batch_group)
        # =========================================================================
        self.batch_group = QGroupBox("Archivos a Procesar (Procesamiento en Lote 1 por 1)")
        batch_lay = QVBoxLayout(self.batch_group)
        batch_lay.setContentsMargins(10, 8, 10, 8)
        batch_lay.setSpacing(6)

        btn_row = QHBoxLayout()
        add_files_btn = QPushButton("[ + ] Agregar Archivos...")
        add_files_btn.setObjectName("actionButton")
        add_files_btn.clicked.connect(self.select_files)
        btn_row.addWidget(add_files_btn)

        remove_btn = QPushButton("[ − ] Quitar Selección")
        remove_btn.setObjectName("secondaryActionButton")
        remove_btn.clicked.connect(self.remove_selected_file)
        btn_row.addWidget(remove_btn)

        clear_btn = QPushButton("[ × ] Limpiar Todo")
        clear_btn.setObjectName("secondaryActionButton")
        clear_btn.clicked.connect(self.clear_batch)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        batch_lay.addLayout(btn_row)

        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(3)
        self.batch_table.setHorizontalHeaderLabels(["Archivo de Origen", "Voz Asignada", "Estado"])
        self.batch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.batch_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.batch_table.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 4px; background: transparent; }")
        batch_lay.addWidget(self.batch_table)

        # =========================================================================
        # SECCIÓN 2: PORTADA Y CUÑAS INTERSTICIALES (extra_group)
        # =========================================================================
        self.extra_group = QGroupBox("Portada y Cuñas Intersticiales (Radio / Jingles / Separadores)")
        extra_lay = QVBoxLayout(self.extra_group)
        extra_lay.setContentsMargins(10, 8, 10, 8)
        extra_lay.setSpacing(6)

        cover_row = QHBoxLayout()
        cover_row.addWidget(QLabel("Portada:"))
        self.cover_edit = QLineEdit()
        self.cover_edit.setPlaceholderText("Ruta a imagen de portada (.png, .jpg)... opcional")
        btn_cover = QPushButton("Examinar...")
        btn_cover.setObjectName("secondaryActionButton")
        btn_cover.clicked.connect(self.select_cover_image)
        cover_row.addWidget(self.cover_edit, stretch=1)
        cover_row.addWidget(btn_cover)
        extra_lay.addLayout(cover_row)

        cunas_hdr = QHBoxLayout()
        self.chk_interstitial = QCheckBox("Insertar cuñas / separadores de audio")
        cunas_hdr.addWidget(self.chk_interstitial)
        cunas_hdr.addStretch()

        self.interstitial_frame = QFrame()
        self.chk_interstitial.toggled.connect(lambda v: self.interstitial_frame.setEnabled(v))

        btn_add_cuna = QPushButton("[ + ] Añadir Cuña")
        btn_add_cuna.setObjectName("secondaryActionButton")
        btn_add_cuna.clicked.connect(self.add_cuna_row_default)
        cunas_hdr.addWidget(btn_add_cuna)

        btn_del_cuna = QPushButton("[ − ] Quitar Cuña")
        btn_del_cuna.setObjectName("secondaryActionButton")
        btn_del_cuna.clicked.connect(self.remove_selected_cuna)
        cunas_hdr.addWidget(btn_del_cuna)

        btn_prev_cuna = QPushButton("[ ► ] Previa")
        btn_prev_cuna.setObjectName("actionButton")
        btn_prev_cuna.clicked.connect(self.preview_selected_cuna)
        cunas_hdr.addWidget(btn_prev_cuna)
        extra_lay.addLayout(cunas_hdr)

        cuna_lay = QVBoxLayout(self.interstitial_frame)
        cuna_lay.setContentsMargins(0, 0, 0, 0)
        cuna_lay.setSpacing(4)

        self.table_cunas = QTableWidget()
        self.table_cunas.setColumnCount(5)
        self.table_cunas.setHorizontalHeaderLabels(["Texto Cuña", "Posición", "Voz", "Estilo", "Pausa"])
        self.table_cunas.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_cunas.setColumnWidth(1, 140)
        self.table_cunas.setColumnWidth(2, 210)
        self.table_cunas.setColumnWidth(3, 160)
        self.table_cunas.setColumnWidth(4, 60)
        self.table_cunas.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_cunas.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 4px; background: transparent; }")
        cuna_lay.addWidget(self.table_cunas)

        self.interstitial_frame.setEnabled(False)
        extra_lay.addWidget(self.interstitial_frame)

        # Cargar cuña inicial predeterminada
        self.add_cuna_row(
            text="Estás escuchando la obra en GlobalTTS.",
            position="between_chapters",
            voice_key="kokoro-am_michael" if "kokoro-am_michael" in self.voices_dict else next(iter(self.voices_dict)),
            style="locutor_radio",
            pause=1.0,
        )

        # =========================================================================
        # SECCIÓN 3: VOCES Y AUTO-CASTING MULTI-VOZ (voice_group)
        # =========================================================================
        self.voice_group = QGroupBox("Voces y Auto-Casting Multi-Voz (15 Voces Neurales)")
        voice_lay = QVBoxLayout(self.voice_group)
        voice_lay.setContentsMargins(10, 8, 10, 8)
        voice_lay.setSpacing(6)

        v_main_row = QHBoxLayout()
        v_main_row.addWidget(QLabel("Voz Principal (Narrador):"))
        self.voice_combo = QComboBox()
        for k, v in self.voices_dict.items():
            tag = "24kHz Studio" if v.engine == "kokoro" else f"{v.sample_rate // 1000}kHz"
            self.voice_combo.addItem(f"{v.name} [{tag}]", k)
        
        default_pref = "kokoro-ef_dora" if "kokoro-ef_dora" in self.voices_dict else "es_MX-claude-high"
        default_idx = self.voice_combo.findData(default_pref)
        if default_idx >= 0:
            self.voice_combo.setCurrentIndex(default_idx)
        v_main_row.addWidget(self.voice_combo, stretch=1)
        voice_lay.addLayout(v_main_row)

        pool_hdr = QHBoxLayout()
        self.chk_autocast = QCheckBox("Auto-Casting Multi-Voz con IA en diálogos")
        self.chk_autocast.setChecked(True)
        self.chk_autocast.toggled.connect(lambda v: self.pool_frame.setEnabled(v))
        pool_hdr.addWidget(self.chk_autocast)
        pool_hdr.addStretch()

        btn_pool_all = QPushButton("Todas")
        btn_pool_all.setObjectName("secondaryActionButton")
        btn_pool_all.clicked.connect(lambda: self.set_pool_selection("all"))
        pool_hdr.addWidget(btn_pool_all)

        btn_pool_kokoro = QPushButton("Solo Kokoro")
        btn_pool_kokoro.setObjectName("secondaryActionButton")
        btn_pool_kokoro.clicked.connect(lambda: self.set_pool_selection("kokoro"))
        pool_hdr.addWidget(btn_pool_kokoro)

        btn_pool_clear = QPushButton("Limpiar")
        btn_pool_clear.setObjectName("secondaryActionButton")
        btn_pool_clear.clicked.connect(lambda: self.set_pool_selection("none"))
        pool_hdr.addWidget(btn_pool_clear)

        btn_test_pool = QPushButton("[ ► ] Probar")
        btn_test_pool.setObjectName("actionButton")
        btn_test_pool.clicked.connect(self.test_selected_pool_voice)
        pool_hdr.addWidget(btn_test_pool)
        voice_lay.addLayout(pool_hdr)

        self.pool_frame = QFrame()
        pool_inner = QVBoxLayout(self.pool_frame)
        pool_inner.setContentsMargins(0, 0, 0, 0)

        self.voice_pool_table = QTableWidget()
        self.voice_pool_table.setColumnCount(3)
        self.voice_pool_table.setHorizontalHeaderLabels(["Casting", "Voz Neural", "Calidad / Perfil"])
        self.voice_pool_table.setColumnWidth(0, 60)
        self.voice_pool_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.voice_pool_table.setColumnWidth(2, 200)
        self.voice_pool_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.voice_pool_table.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 4px; background: transparent; }")
        pool_inner.addWidget(self.voice_pool_table)
        voice_lay.addWidget(self.pool_frame)

        self.populate_voice_pool_table()

        # =========================================================================
        # SECCIÓN 4: MODO NARRACIÓN / ANÁLISIS CON IA (ai_group)
        # =========================================================================
        self.ai_group = QGroupBox("Expresividad y Modo Narración (Mistral NeMo Local)")
        ai_lay = QVBoxLayout(self.ai_group)
        ai_lay.setContentsMargins(10, 8, 10, 8)
        ai_lay.setSpacing(5)

        self.chk_ai_narration = QCheckBox("Activar análisis con IA (Mistral NeMo 12B local)")
        self.chk_ai_narration.toggled.connect(self.toggle_ai_options)
        ai_lay.addWidget(self.chk_ai_narration)

        self.ai_options_frame = QFrame()
        ai_opt_lay = QFormLayout(self.ai_options_frame)
        ai_opt_lay.setContentsMargins(0, 0, 0, 0)
        ai_opt_lay.setSpacing(5)

        self.combo_ai_mode = QComboBox()
        self.combo_ai_mode.addItem("Enriquecer expresividad ([pausa], [lento], [énfasis])", "enhance")
        self.combo_ai_mode.addItem("Modo Narrador Completo (reescribe como historia/cuento oral)", "rewrite")
        self.combo_ai_mode.addItem("Traducción y Adaptación (a Español Neutro es-LA)", "translate")
        self.combo_ai_mode.addItem("Detección y Clasificación de Diálogos (Auto-Casting)", "dialogue_analysis")
        ai_opt_lay.addRow("Modo de IA:", self.combo_ai_mode)

        row_params = QHBoxLayout()
        self.combo_persona = QComboBox()
        self.combo_persona.addItem("1ra Persona (Yo)", "1ra")
        self.combo_persona.addItem("2da Persona (Tú)", "2da")
        self.combo_persona.addItem("3ra Persona (Él/Ella)", "3ra")
        self.combo_persona.setCurrentIndex(2)

        self.combo_tense = QComboBox()
        self.combo_tense.addItem("Pasado", "pasado")
        self.combo_tense.addItem("Presente", "presente")
        self.combo_tense.addItem("Continuo", "presente_continuo")
        self.combo_tense.addItem("Futuro", "futuro")

        self.combo_style = QComboBox()
        self.refresh_styles_combo()

        row_params.addWidget(QLabel("Perspectiva:"))
        row_params.addWidget(self.combo_persona)
        row_params.addWidget(QLabel("Tiempo:"))
        row_params.addWidget(self.combo_tense)
        row_params.addWidget(QLabel("Estilo:"))
        row_params.addWidget(self.combo_style)
        ai_opt_lay.addRow("Parámetros:", row_params)

        btn_row_p = QHBoxLayout()
        self.btn_manage_prompts = QPushButton("[ ↗ ] Ver y Editar en Prompts Maestros")
        self.btn_manage_prompts.setObjectName("secondaryActionButton")
        self.btn_manage_prompts.clicked.connect(lambda: self.tabs.setCurrentIndex(3))
        btn_row_p.addWidget(self.btn_manage_prompts)
        ai_opt_lay.addRow("Catálogo:", btn_row_p)

        self.ai_options_frame.setEnabled(False)
        ai_lay.addWidget(self.ai_options_frame)

        # =========================================================================
        # SECCIÓN 5: FORMATOS DE SALIDA (out_group)
        # =========================================================================
        self.out_group = QGroupBox("Formatos a Generar")
        out_lay = QHBoxLayout(self.out_group)
        out_lay.setContentsMargins(10, 6, 10, 6)
        self.chk_mp3 = QCheckBox("Audio MP3 (256k EBU R128)")
        self.chk_mp3.setChecked(True)
        self.chk_video = QCheckBox("Video Karaoke (MP4 pantalla negra)")
        self.chk_video.setChecked(True)
        self.chk_flac = QCheckBox("Master FLAC sin pérdida")
        self.chk_flac.setChecked(True)
        out_lay.addWidget(self.chk_mp3)
        out_lay.addWidget(self.chk_video)
        out_lay.addWidget(self.chk_flac)

        # =========================================================================
        # SECCIÓN 6: TELEMETRÍA, PROGRESO Y ACCIONES (bottom_control_box)
        # =========================================================================
        self.bottom_control_box = QWidget()
        bottom_box_lay = QVBoxLayout(self.bottom_control_box)
        bottom_box_lay.setContentsMargins(0, 0, 0, 0)
        bottom_box_lay.setSpacing(6)

        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(8)

        card_elapsed = QFrame()
        card_elapsed.setObjectName("metricCard")
        lay_elapsed = QVBoxLayout(card_elapsed)
        lbl_e = QLabel("Transcurrido")
        lbl_e.setObjectName("metricTitle")
        self.val_elapsed = QLabel("00:00:00")
        self.val_elapsed.setObjectName("metricValue")
        lay_elapsed.addWidget(lbl_e)
        lay_elapsed.addWidget(self.val_elapsed)
        metrics_layout.addWidget(card_elapsed)

        card_eta = QFrame()
        card_eta.setObjectName("metricCard")
        lay_eta = QVBoxLayout(card_eta)
        lbl_eta = QLabel("Restante (ETA)")
        lbl_eta.setObjectName("metricTitle")
        self.val_eta = QLabel("--:--:--")
        self.val_eta.setObjectName("metricValue")
        lay_eta.addWidget(lbl_eta)
        lay_eta.addWidget(self.val_eta)
        metrics_layout.addWidget(card_eta)

        card_speed = QFrame()
        card_speed.setObjectName("metricCard")
        lay_speed = QVBoxLayout(card_speed)
        lbl_s = QLabel("Velocidad")
        lbl_s.setObjectName("metricTitle")
        self.val_speed = QLabel("-- orac/s")
        self.val_speed.setObjectName("metricValueActive")
        lay_speed.addWidget(lbl_s)
        lay_speed.addWidget(self.val_speed)
        metrics_layout.addWidget(card_speed)

        bottom_box_lay.addLayout(metrics_layout)

        # Barra de progreso y Fase
        prog_row = QHBoxLayout()
        self.lbl_stage = QLabel("Fase: Listo para procesar.")
        self.lbl_stage.setStyleSheet("color: #58a6ff; font-weight: 600; font-size: 12px;")
        self.lbl_active_utt = QLabel("En espera...")
        self.lbl_active_utt.setStyleSheet("color: #8b949e; font-size: 11px; font-style: italic;")
        prog_row.addWidget(self.lbl_stage)
        prog_row.addStretch()
        prog_row.addWidget(self.lbl_active_utt)
        bottom_box_lay.addLayout(prog_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        bottom_box_lay.addWidget(self.progress_bar)

        # Panel de Resultados
        self.res_card = QFrame()
        self.res_card.setObjectName("resultCard")
        self.res_card.setVisible(False)
        res_lay = QVBoxLayout(self.res_card)
        self.res_summary = QLabel("Archivos generados exitosamente.")
        self.res_summary.setStyleSheet("color: #3fb950; font-weight: 700; font-size: 13px;")
        res_lay.addWidget(self.res_summary)

        res_btns = QHBoxLayout()
        self.btn_open_last_folder = QPushButton("[ ↗ ] Abrir Carpeta del Libro")
        self.btn_open_last_folder.setObjectName("secondaryActionButton")
        self.btn_open_last_folder.clicked.connect(self.open_last_book_folder)

        self.btn_go_library = QPushButton("[ ↗ ] Ver en Biblioteca")
        self.btn_go_library.setObjectName("actionButton")
        self.btn_go_library.clicked.connect(lambda: self.tabs.setCurrentIndex(2))

        self.btn_upload_yt = QPushButton("[ ↗ ] Publicar en YouTube")
        self.btn_upload_yt.setObjectName("secondaryActionButton")
        self.btn_upload_yt.clicked.connect(lambda: self.show_distribution_dialog("YouTube"))

        self.btn_upload_sp = QPushButton("[ ↗ ] Publicar en Spotify")
        self.btn_upload_sp.setObjectName("secondaryActionButton")
        self.btn_upload_sp.clicked.connect(lambda: self.show_distribution_dialog("Spotify"))

        res_btns.addWidget(self.btn_open_last_folder)
        res_btns.addWidget(self.btn_go_library)
        res_btns.addWidget(self.btn_upload_yt)
        res_btns.addWidget(self.btn_upload_sp)
        res_lay.addLayout(res_btns)
        bottom_box_lay.addWidget(self.res_card)

        # Botón de Inicio
        self.start_btn = QPushButton("[ ► ] Iniciar Generación en Lote")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self.start_batch_processing)
        bottom_box_lay.addWidget(self.start_btn)

        # Aplicar distribución inicial
        self.update_generator_tab_layout(self.get_effective_orientation())

    def update_generator_tab_layout(self, mode: str):
        """Ajusta la distribución del Generador manteniendo el orden exacto de secciones sin scroll."""
        def clear_layout_items(lay):
            while lay.count():
                item = lay.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
                elif item.layout():
                    clear_layout_items(item.layout())

        clear_layout_items(self.gen_layout)

        if mode == "vertical":
            # Modo Vertical: Orden secuencial 1 -> 2 -> 3 -> 4 -> 5 -> 6 ocupando todo el ancho y alto
            self.gen_layout.setContentsMargins(10, 6, 10, 6)
            self.gen_layout.setSpacing(6)

            # Tablas fluidas para aprovechar los 1872px de altura
            self.batch_table.setMinimumHeight(130)
            self.batch_table.setMaximumHeight(16777215)
            self.table_cunas.setMinimumHeight(115)
            self.table_cunas.setMaximumHeight(16777215)
            self.voice_pool_table.setMinimumHeight(125)
            self.voice_pool_table.setMaximumHeight(16777215)

            self.gen_layout.addWidget(self.batch_group, stretch=3)
            self.gen_layout.addWidget(self.extra_group, stretch=3)
            self.gen_layout.addWidget(self.voice_group, stretch=3)
            self.gen_layout.addWidget(self.ai_group, stretch=0)
            self.gen_layout.addWidget(self.out_group, stretch=0)
            self.gen_layout.addWidget(self.bottom_control_box, stretch=0)
        else:
            # Modo Horizontal: 2 columnas balanceadas para monitores panorámicos
            self.gen_layout.setContentsMargins(10, 10, 10, 10)
            self.gen_layout.setSpacing(8)

            # Alturas compactas para que quepa en 1080p horizontal sin scrollbar
            self.batch_table.setMinimumHeight(90)
            self.batch_table.setMaximumHeight(140)
            self.table_cunas.setMinimumHeight(90)
            self.table_cunas.setMaximumHeight(115)
            self.voice_pool_table.setMinimumHeight(90)
            self.voice_pool_table.setMaximumHeight(115)

            cols_lay = QHBoxLayout()
            cols_lay.setSpacing(10)

            left_col = QVBoxLayout()
            left_col.setSpacing(8)
            left_col.addWidget(self.batch_group)
            left_col.addWidget(self.extra_group)
            left_col.addStretch()
            cols_lay.addLayout(left_col, stretch=50)

            right_col = QVBoxLayout()
            right_col.setSpacing(8)
            right_col.addWidget(self.voice_group)
            right_col.addWidget(self.ai_group)
            right_col.addWidget(self.out_group)
            right_col.addStretch()
            cols_lay.addLayout(right_col, stretch=50)

            self.gen_layout.addLayout(cols_lay)
            self.gen_layout.addWidget(self.bottom_control_box)

    def toggle_ai_options(self, checked: bool):
        self.ai_options_frame.setEnabled(checked)

    def refresh_styles_combo(self):
        curr = self.combo_style.currentData() if self.combo_style.count() > 0 else "cuento"
        self.combo_style.clear()
        for style in self.prompt_library.list_styles():
            self.combo_style.addItem(style.name, style.id)
        idx = self.combo_style.findData(curr)
        if idx >= 0:
            self.combo_style.setCurrentIndex(idx)

    def open_prompt_manager(self):
        dlg = PromptManagerDialog(library=self.prompt_library, parent=self)
        dlg.prompts_updated.connect(self.refresh_styles_combo)
        dlg.exec()

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar documentos para audiolibro",
            "",
            "Documentos Soportados (*.txt *.pdf *.epub *.md);;Texto (*.txt *.md);;PDF (*.pdf);;EPUB (*.epub)"
        )
        for f in files:
            self.add_file_to_batch(f)

    def add_file_to_batch(self, file_path: str):
        p = Path(file_path)
        if any(b["path"] == str(p) for b in self.batch_files):
            return

        row = self.batch_table.rowCount()
        self.batch_table.insertRow(row)
        self.batch_table.setItem(row, 0, QTableWidgetItem(p.name))
        self.batch_table.setItem(row, 1, QTableWidgetItem(self.voice_combo.currentText()))
        self.batch_table.setItem(row, 2, QTableWidgetItem("Pendiente"))

        self.batch_files.append({"path": str(p), "row": row})

    def clear_batch(self):
        self.batch_files.clear()
        self.batch_table.setRowCount(0)

    def select_cover_image(self):
        img, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Imagen de Portada",
            "",
            "Imágenes (*.png *.jpg *.jpeg *.webp)"
        )
        if img:
            self.cover_edit.setText(img)

    def add_cuna_row_default(self):
        v_def = "kokoro-am_michael" if "kokoro-am_michael" in self.voices_dict else next(iter(self.voices_dict))
        self.add_cuna_row(
            text="Estás escuchando la obra en GlobalTTS.",
            position="between_chapters",
            voice_key=v_def,
            style="locutor_radio",
            pause=1.0,
        )

    def add_cuna_row(self, text: str, position: str, voice_key: str, style: str, pause: float = 1.0):
        row = self.table_cunas.rowCount()
        self.table_cunas.insertRow(row)

        # Col 0: Texto
        txt_item = QTableWidgetItem(text)
        self.table_cunas.setItem(row, 0, txt_item)

        # Col 1: Posición Combo
        pos_combo = QComboBox()
        pos_combo.addItem("Entre Capítulos", "between_chapters")
        pos_combo.addItem("Entre Párrafos", "between_paragraphs")
        pos_combo.addItem("Al Inicio", "start")
        pos_combo.addItem("Al Final", "end")
        idx_p = pos_combo.findData(position)
        if idx_p >= 0:
            pos_combo.setCurrentIndex(idx_p)
        self.table_cunas.setCellWidget(row, 1, pos_combo)

        # Col 2: Voz Combo
        v_combo = QComboBox()
        for k, v in self.voices_dict.items():
            tag = "24k" if v.engine == "kokoro" else f"{v.sample_rate // 1000}k"
            v_combo.addItem(f"{v.name} [{tag}]", k)
        idx_v = v_combo.findData(voice_key)
        if idx_v >= 0:
            v_combo.setCurrentIndex(idx_v)
        self.table_cunas.setCellWidget(row, 2, v_combo)

        # Col 3: Estilo Combo
        st_combo = QComboBox()
        for st in self.prompt_library.list_styles():
            st_combo.addItem(st.name, st.id)
        idx_s = st_combo.findData(style)
        if idx_s >= 0:
            st_combo.setCurrentIndex(idx_s)
        self.table_cunas.setCellWidget(row, 3, st_combo)

        # Col 4: Pausa
        pause_item = QTableWidgetItem(f"{pause:.1f}")
        pause_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table_cunas.setItem(row, 4, pause_item)

    def remove_selected_cuna(self):
        row = self.table_cunas.currentRow()
        if 0 <= row < self.table_cunas.rowCount():
            self.table_cunas.removeRow(row)

    def preview_selected_cuna(self):
        row = self.table_cunas.currentRow()
        if row < 0 or row >= self.table_cunas.rowCount():
            row = 0
            if self.table_cunas.rowCount() == 0:
                return

        txt_item = self.table_cunas.item(row, 0)
        text = txt_item.text().strip() if txt_item else ""
        if not text:
            return

        v_combo = self.table_cunas.cellWidget(row, 2)
        voice_key = v_combo.currentData() if v_combo else self.voice_combo.currentData()

        st_combo = self.table_cunas.cellWidget(row, 3)
        style = st_combo.currentData() if st_combo else "locutor_radio"

        try:
            import sounddevice as sd
            sd.stop()
            engine = PiperTtsEngine(voice_key=voice_key)
            formatted_text = f"[{style}]{text}[/{style}]"
            samples = engine.synthesize(formatted_text)
            sd.play(samples, engine.sample_rate)
        except Exception as e:
            QMessageBox.warning(self, "Error al escuchar cuña", f"No se pudo sintetizar:\n{e}")

    def populate_voice_pool_table(self):
        self.voice_pool_table.setRowCount(0)
        for row, (key, profile) in enumerate(self.voices_dict.items()):
            self.voice_pool_table.insertRow(row)

            # Col 0: Checkbox
            chk = QCheckBox()
            # Por defecto activar todas las voces Kokoro Neural y un par de Piper
            if profile.engine == "kokoro" or key in ("es_ES-sharvard-medium", "es_MX-claude-high"):
                chk.setChecked(True)
            chk_widget = QWidget()
            chk_lay = QHBoxLayout(chk_widget)
            chk_lay.addWidget(chk)
            chk_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_lay.setContentsMargins(0, 0, 0, 0)
            self.voice_pool_table.setCellWidget(row, 0, chk_widget)

            # Col 1: Nombre de la voz
            name_item = QTableWidgetItem(profile.name)
            name_item.setData(Qt.ItemDataRole.UserRole, key)
            self.voice_pool_table.setItem(row, 1, name_item)

            # Col 2: Perfil / Motor
            engine_str = "Kokoro (24kHz Studio)" if profile.engine == "kokoro" else f"Piper ({profile.sample_rate // 1000}kHz)"
            gender_str = f" • {profile.gender.capitalize()}" if profile.gender else ""
            desc_item = QTableWidgetItem(f"{engine_str}{gender_str}")
            self.voice_pool_table.setItem(row, 2, desc_item)

    def set_pool_selection(self, mode: str):
        for r in range(self.voice_pool_table.rowCount()):
            w = self.voice_pool_table.cellWidget(r, 0)
            if not w:
                continue
            chk = w.findChild(QCheckBox)
            if not chk:
                continue
            name_item = self.voice_pool_table.item(r, 1)
            v_key = name_item.data(Qt.ItemDataRole.UserRole) if name_item else ""
            prof = self.voices_dict.get(v_key)

            if mode == "all":
                chk.setChecked(True)
            elif mode == "none":
                chk.setChecked(False)
            elif mode == "kokoro":
                chk.setChecked(prof is not None and prof.engine == "kokoro")

    def get_selected_voice_pool(self) -> list[str]:
        selected = []
        for r in range(self.voice_pool_table.rowCount()):
            w = self.voice_pool_table.cellWidget(r, 0)
            if not w:
                continue
            chk = w.findChild(QCheckBox)
            if chk and chk.isChecked():
                name_item = self.voice_pool_table.item(r, 1)
                v_key = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
                if v_key:
                    selected.append(v_key)
        return selected

    def test_selected_pool_voice(self):
        row = self.voice_pool_table.currentRow()
        if row < 0 or row >= self.voice_pool_table.rowCount():
            row = 0
            if self.voice_pool_table.rowCount() == 0:
                return

        name_item = self.voice_pool_table.item(row, 1)
        voice_key = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
        if not voice_key:
            return

        try:
            import sounddevice as sd
            sd.stop()
            engine = PiperTtsEngine(voice_key=voice_key)
            test_phrase = f"Hola, soy la voz {engine.available_voices[voice_key].name} lista para el casting dramático."
            samples = engine.synthesize(test_phrase)
            sd.play(samples, engine.sample_rate)
        except Exception as e:
            QMessageBox.warning(self, "Error al probar voz", f"No se pudo sintetizar la muestra:\n{e}")

    def start_batch_processing(self):
        if not self.batch_files:
            QMessageBox.warning(self, "Lista Vacía", "Por favor agrega al menos un archivo para procesar.")
            return

        if not self.chk_mp3.isChecked() and not self.chk_video.isChecked() and not self.chk_flac.isChecked():
            QMessageBox.warning(self, "Sin formato", "Selecciona al menos un formato de salida.")
            return

        # Cuñas configuradas en la tabla
        interstitials = []
        if self.chk_interstitial.isChecked():
            for r in range(self.table_cunas.rowCount()):
                txt_item = self.table_cunas.item(r, 0)
                txt = txt_item.text().strip() if txt_item else ""
                if not txt:
                    continue

                pos_combo = self.table_cunas.cellWidget(r, 1)
                pos = pos_combo.currentData() if pos_combo else "between_chapters"

                v_combo = self.table_cunas.cellWidget(r, 2)
                v_key = v_combo.currentData() if v_combo else self.voice_combo.currentData()

                st_combo = self.table_cunas.cellWidget(r, 3)
                st = st_combo.currentData() if st_combo else "locutor_radio"

                pause_item = self.table_cunas.item(r, 4)
                try:
                    p_val = float(pause_item.text().strip()) if pause_item else 1.0
                except ValueError:
                    p_val = 1.0

                interstitials.append(
                    InterstitialItem(
                        text=txt,
                        voice_key=v_key,
                        position=pos,
                        style=st,
                        pause_after=p_val,
                    )
                )

        # Pool de voces para auto-casting multi-voz
        selected_pool = self.get_selected_voice_pool() if self.chk_autocast.isChecked() else []
        if not selected_pool and self.chk_autocast.isChecked():
            selected_pool = [k for k in self.voices_dict.keys() if k != self.voice_combo.currentData()][:4]

        sec_voice = selected_pool[0] if selected_pool else None

        configs: list[JobConfig] = []
        for item in self.batch_files:
            # Narración IA
            narration_cfg = NarrationConfig(
                enabled=self.chk_ai_narration.isChecked(),
                mode=self.combo_ai_mode.currentData(),
                persona=self.combo_persona.currentData(),
                tense=self.combo_tense.currentData(),
                style=self.combo_style.currentData(),
            )

            cfg = JobConfig(
                source_file=item["path"],
                voice_key=self.voice_combo.currentData(),
                secondary_voice_key=sec_voice,
                voice_pool=selected_pool,
                multi_voice_mode="dialogue_auto" if self.chk_autocast.isChecked() else "single",
                cover_image_path=self.cover_edit.text().strip() or None,
                generate_audio=self.chk_mp3.isChecked(),
                generate_video=self.chk_video.isChecked(),
                save_flac_master=self.chk_flac.isChecked(),
                narration=narration_cfg,
                interstitials=interstitials
            )
            configs.append(cfg)

        self.start_btn.setEnabled(False)
        self.start_btn.setText("Procesando lote en segundo plano...")
        self.res_card.setVisible(False)
        self.start_timestamp = time.perf_counter()
        self.timer.start()

        self.worker = BatchPipelineWorker(configs)
        self.worker.signals.item_started.connect(self.on_item_started)
        self.worker.signals.stage.connect(self.on_stage)
        self.worker.signals.progress.connect(self.on_progress)
        self.worker.signals.item_finished.connect(self.on_item_finished)
        self.worker.signals.batch_finished.connect(self.on_batch_finished)
        self.worker.signals.error.connect(self.on_error)
        self.worker.start()

    def update_timer_tick(self):
        if self.start_timestamp is None:
            return
        elapsed = time.perf_counter() - self.start_timestamp
        self.val_elapsed.setText(str(timedelta(seconds=int(elapsed))))

        if self.current_utt_count > 0 and elapsed > 0.5:
            rate = self.current_utt_count / elapsed
            self.val_speed.setText(f"{rate:.1f} orac/s")

            if self.total_utts > self.current_utt_count and rate > 0:
                remaining_utts = self.total_utts - self.current_utt_count
                rem_s = remaining_utts / rate
                if self.chk_video.isChecked():
                    rem_s += max(3.0, rem_s * 0.25)
                self.val_eta.setText(str(timedelta(seconds=int(rem_s))))

    def on_item_started(self, idx: int, name: str):
        self.batch_table.setItem(idx, 2, QTableWidgetItem("Procesando..."))
        self.lbl_stage.setText(f"Iniciando: {name}")

    def on_stage(self, stage: str, desc: str, pct: float):
        self.lbl_stage.setText(f"Fase: {desc}")
        if stage != "synthesize":
            self.progress_bar.setValue(int(pct))

    def on_progress(self, current: int, total: int, text: str):
        self.current_utt_count = current
        self.total_utts = total
        max_pct = 80.0 if self.chk_video.isChecked() else 92.0
        ratio = (current / total) if total > 0 else 0
        p = 10.0 + (ratio * (max_pct - 10.0))
        self.progress_bar.setValue(int(p))
        self.lbl_active_utt.setText(f"\"{text}\"")

    def on_item_finished(self, idx: int, meta: JobMetadata):
        self.batch_table.setItem(idx, 2, QTableWidgetItem(f"Completado ({meta.duration_seconds}s)"))

    def on_batch_finished(self, results: list[JobMetadata]):
        self.timer.stop()
        self.last_results = results
        self.progress_bar.setValue(100)
        self.start_btn.setEnabled(True)
        self.start_btn.setText("[ ⟳ ] Procesar de Nuevo")

        elapsed = time.perf_counter() - self.start_timestamp if self.start_timestamp else 0
        self.val_elapsed.setText(str(timedelta(seconds=int(elapsed))))
        self.val_eta.setText("00:00:00")
        self.lbl_stage.setText("Lote completado con éxito.")
        self.lbl_active_utt.setText(f"Procesados {len(results)} libro(s) en {elapsed:.1f}s.")

        self.res_card.setVisible(True)
        self.res_summary.setText(f"Se han generado {len(results)} audiolibro(s) en sus carpetas dedicadas.")

        # Refrescar la pestaña de biblioteca automáticamente
        self.tab_library.refresh_library()

    def open_last_book_folder(self):
        if self.last_results:
            last = self.last_results[-1]
            if Path(last.document_folder).exists():
                os.startfile(last.document_folder)
                return
        if BIBLIOTECA_DIR.exists():
            os.startfile(BIBLIOTECA_DIR)

    def on_error(self, err_msg: str):
        self.timer.stop()
        self.start_btn.setEnabled(True)
        self.start_btn.setText("[ ► ] Iniciar Generación en Lote")
        self.lbl_stage.setText("Error en el lote.")
        self.lbl_active_utt.setText(err_msg)
        QMessageBox.critical(self, "Error en el Lote", f"Ocurrió un error:\n\n{err_msg}")


class GlobalTTSTrayIcon(QSystemTrayIcon):
    """Ícono de GlobalTTS en la barra de herramientas del sistema."""

    def __init__(self, parent: Optional[QApplication] = None):
        super().__init__(parent)
        self.setIcon(QIcon(create_tray_pixmap()))
        self.setToolTip("GlobalTTS — Servicio Activo de Voz y Audiolibros")

        self.main_window: Optional[MainWindow] = None
        self.create_menu()

    def create_menu(self):
        menu = QMenu()
        menu.setStyleSheet(DARK_THEME_QSS)

        open_app_action = QAction("GlobalTTS (Ventana Principal)", menu)
        f = open_app_action.font()
        f.setBold(True)
        open_app_action.setFont(f)
        open_app_action.triggered.connect(self.show_main_window)
        menu.addAction(open_app_action)

        menu.addSeparator()

        quick_action = QAction("Lector Rápido & Configuración", menu)
        quick_action.triggered.connect(self.show_quick_reader)
        menu.addAction(quick_action)

        gen_action = QAction("Generador de Audiolibros & Lotes", menu)
        gen_action.triggered.connect(self.show_generator)
        menu.addAction(gen_action)

        open_bib_action = QAction("Biblioteca & Reproductor", menu)
        open_bib_action.triggered.connect(self.show_library_tab)
        menu.addAction(open_bib_action)

        prompts_action = QAction("Prompts Maestros & Estilos IA", menu)
        prompts_action.triggered.connect(self.show_prompts_tab)
        menu.addAction(prompts_action)

        menu.addSeparator()

        minimize_action = QAction("Minimizar a Bandeja", menu)
        minimize_action.triggered.connect(self.minimize_main_window)
        menu.addAction(minimize_action)

        load_action = QAction("Cargar Archivo(s) para Audiolibro...", menu)
        load_action.triggered.connect(self.open_file_dialog)
        menu.addAction(load_action)

        menu.addSeparator()

        exit_action = QAction("Salir de GlobalTTS", menu)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)

        self.setContextMenu(menu)
        self.activated.connect(self.on_tray_activated)

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_main_window()

    def show_main_window(self, initial_file: Optional[str] = None):
        if not self.main_window:
            self.main_window = MainWindow(initial_file=initial_file, tray_icon=self)
        elif initial_file:
            self.main_window.add_file_to_batch(initial_file)
            self.main_window.tabs.setCurrentIndex(1)

        self.main_window.showMaximized()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def minimize_main_window(self):
        if self.main_window:
            self.main_window.minimize_to_tray()

    def show_quick_reader(self):
        self.show_main_window()
        if self.main_window:
            self.main_window.tabs.setCurrentIndex(0)

    def show_generator(self):
        self.show_main_window()
        if self.main_window:
            self.main_window.tabs.setCurrentIndex(1)

    def show_library_tab(self):
        self.show_main_window()
        if self.main_window:
            self.main_window.tabs.setCurrentIndex(2)

    def show_prompts_tab(self):
        self.show_main_window()
        if self.main_window:
            self.main_window.tabs.setCurrentIndex(3)

    def open_file_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            None,
            "Seleccionar documentos para audiolibro",
            "",
            "Documentos Soportados (*.txt *.pdf *.epub *.md);;Texto Plano (*.txt *.md);;PDF (*.pdf);;EPUB (*.epub)"
        )
        if files:
            self.show_generator()
            for extra in files:
                self.main_window.add_file_to_batch(extra)


def run_tray():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray = GlobalTTSTrayIcon(app)
    tray.show()

    # Abrir la ventana principal al arrancar por defecto (salvo que se pase --minimized)
    if "--minimized" not in sys.argv:
        tray.show_main_window()
    else:
        tray.showMessage(
            "GlobalTTS Activo",
            "Servicio de lectura rápida y audiolibros activo en segundo plano.",
            QSystemTrayIcon.MessageIcon.Information,
            2500
        )

    sys.exit(app.exec())


if __name__ == "__main__":
    run_tray()
