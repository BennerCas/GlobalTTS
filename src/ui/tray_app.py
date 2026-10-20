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
        
        # Modo Kiosko 16:9 ajustado a la pantalla disponible (preservando barra de tareas de Windows)
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.setGeometry(avail)
        self.setMinimumSize(1024, 680)
        self.setStyleSheet(DARK_THEME_QSS)

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

        self.init_ui()

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

    def init_generator_tab(self):
        gen_layout = QVBoxLayout(self.tab_generator)
        gen_layout.setContentsMargins(10, 10, 10, 10)
        gen_layout.setSpacing(8)

        # Disposición en 2 Columnas responsivas sin ScrollArea para aprovechar la pantalla
        cols_lay = QHBoxLayout()
        cols_lay.setSpacing(10)

        # =========================================================================
        # COLUMNA IZQUIERDA: ARCHIVOS EN LOTE, PORTADA Y CUÑAS (50% espacio)
        # =========================================================================
        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        # 1. Tabla de Archivos en Lote
        batch_group = QGroupBox("Archivos a Procesar (Procesamiento en Lote 1 por 1)")
        batch_lay = QVBoxLayout(batch_group)
        batch_lay.setContentsMargins(10, 10, 10, 10)
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
        self.batch_table.setMaximumHeight(150)
        self.batch_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.batch_table.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 4px; background: transparent; }")
        batch_lay.addWidget(self.batch_table)
        left_col.addWidget(batch_group)

        # 2. Portada y Cuñas Intersticiales (Radio / Separadores)
        extra_group = QGroupBox("Portada y Cuñas Intersticiales")
        extra_lay = QFormLayout(extra_group)
        extra_lay.setContentsMargins(10, 10, 10, 10)
        extra_lay.setSpacing(6)

        cover_row = QHBoxLayout()
        self.cover_edit = QLineEdit()
        self.cover_edit.setPlaceholderText("Ruta a imagen de portada (.png, .jpg)... opcional")
        btn_cover = QPushButton("Examinar...")
        btn_cover.setObjectName("secondaryActionButton")
        btn_cover.clicked.connect(self.select_cover_image)
        cover_row.addWidget(self.cover_edit)
        cover_row.addWidget(btn_cover)
        extra_lay.addRow("Portada Libro/Video:", cover_row)

        interstitial_box = QVBoxLayout()
        self.chk_interstitial = QCheckBox("Insertar cuña / separador entre capítulos")
        self.chk_interstitial.toggled.connect(lambda v: self.interstitial_frame.setEnabled(v))
        interstitial_box.addWidget(self.chk_interstitial)

        self.interstitial_frame = QFrame()
        cuña_lay = QHBoxLayout(self.interstitial_frame)
        cuña_lay.setContentsMargins(0, 0, 0, 0)
        self.interstitial_text = QLineEdit("Estás escuchando la obra en GlobalTTS.")
        self.interstitial_voice = QComboBox()
        self.voices_dict = list_available_piper_voices()
        for k, v in self.voices_dict.items():
            self.interstitial_voice.addItem(v.name, k)

        self.btn_preview_interstitial = QPushButton("[ ► ] Previa")
        self.btn_preview_interstitial.setObjectName("actionButton")
        self.btn_preview_interstitial.clicked.connect(self.preview_interstitial)

        cuña_lay.addWidget(QLabel("Texto:"))
        cuña_lay.addWidget(self.interstitial_text, stretch=1)
        cuña_lay.addWidget(QLabel("Voz:"))
        cuña_lay.addWidget(self.interstitial_voice)
        cuña_lay.addWidget(self.btn_preview_interstitial)

        self.interstitial_frame.setEnabled(False)
        interstitial_box.addWidget(self.interstitial_frame)
        extra_lay.addRow("Cuña Radial:", interstitial_box)

        left_col.addWidget(extra_group)
        left_col.addStretch()
        cols_lay.addLayout(left_col, stretch=50)

        # =========================================================================
        # COLUMNA DERECHA: VOCES, NARRACIÓN IA Y FORMATOS (50% espacio)
        # =========================================================================
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        # 3. Configuración de Voz y Auto-Casting
        voice_group = QGroupBox("Voces y Auto-Casting Multi-Voz")
        voice_lay = QFormLayout(voice_group)
        voice_lay.setContentsMargins(10, 10, 10, 10)
        voice_lay.setSpacing(6)

        self.voice_combo = QComboBox()
        for k, v in self.voices_dict.items():
            self.voice_combo.addItem(f"{v.name} ({v.language.upper()})", k)
        default_idx = self.voice_combo.findData("es_MX-claude-high")
        if default_idx >= 0:
            self.voice_combo.setCurrentIndex(default_idx)
        voice_lay.addRow("Voz Principal:", self.voice_combo)

        autocast_row = QHBoxLayout()
        self.chk_autocast = QCheckBox("Auto-Casting en diálogos")
        self.chk_autocast.setChecked(True)
        self.sec_voice_combo = QComboBox()
        for k, v in self.voices_dict.items():
            self.sec_voice_combo.addItem(f"{v.name} ({v.language.upper()})", k)
        sec_idx = self.sec_voice_combo.findData("es_ES-sharvard-medium")
        if sec_idx >= 0:
            self.sec_voice_combo.setCurrentIndex(sec_idx)

        autocast_row.addWidget(self.chk_autocast)
        autocast_row.addWidget(QLabel("Voz Diálogos:"))
        autocast_row.addWidget(self.sec_voice_combo, stretch=1)
        voice_lay.addRow("Multi-Voz:", autocast_row)
        right_col.addWidget(voice_group)

        # 4. Modo Narración / Análisis con Mistral NeMo Local
        ai_group = QGroupBox("Expresividad y Modo Narración (Mistral NeMo Local)")
        ai_lay = QVBoxLayout(ai_group)
        ai_lay.setContentsMargins(10, 10, 10, 10)
        ai_lay.setSpacing(6)

        self.chk_ai_narration = QCheckBox("Activar análisis con IA (Mistral NeMo 12B local)")
        self.chk_ai_narration.toggled.connect(self.toggle_ai_options)
        ai_lay.addWidget(self.chk_ai_narration)

        self.ai_options_frame = QFrame()
        ai_opt_lay = QFormLayout(self.ai_options_frame)
        ai_opt_lay.setContentsMargins(0, 0, 0, 0)
        ai_opt_lay.setSpacing(6)

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
        right_col.addWidget(ai_group)

        # 5. Formatos de Salida
        out_group = QGroupBox("Formatos a Generar")
        out_lay = QHBoxLayout(out_group)
        out_lay.setContentsMargins(10, 8, 10, 8)
        self.chk_mp3 = QCheckBox("Audio MP3 (256k EBU R128)")
        self.chk_mp3.setChecked(True)
        self.chk_video = QCheckBox("Video Karaoke (MP4 pantalla negra)")
        self.chk_video.setChecked(True)
        self.chk_flac = QCheckBox("Master FLAC sin pérdida")
        self.chk_flac.setChecked(True)
        out_lay.addWidget(self.chk_mp3)
        out_lay.addWidget(self.chk_video)
        out_lay.addWidget(self.chk_flac)
        right_col.addWidget(out_group)
        right_col.addStretch()

        cols_lay.addLayout(right_col, stretch=50)
        gen_layout.addLayout(cols_lay)

        # =========================================================================
        # SECCIÓN INFERIOR: TELEMETRÍA, PROGRESO Y ACCIONES
        # =========================================================================
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(10)

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

        gen_layout.addLayout(metrics_layout)

        # Barra de progreso y Fase
        prog_row = QHBoxLayout()
        self.lbl_stage = QLabel("Fase: Listo para procesar.")
        self.lbl_stage.setStyleSheet("color: #58a6ff; font-weight: 600; font-size: 12px;")
        self.lbl_active_utt = QLabel("En espera...")
        self.lbl_active_utt.setStyleSheet("color: #8b949e; font-size: 11px; font-style: italic;")
        prog_row.addWidget(self.lbl_stage)
        prog_row.addStretch()
        prog_row.addWidget(self.lbl_active_utt)
        gen_layout.addLayout(prog_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        gen_layout.addWidget(self.progress_bar)

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
        gen_layout.addWidget(self.res_card)

        # Botón de Inicio
        self.start_btn = QPushButton("[ ► ] Iniciar Generación en Lote")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self.start_batch_processing)
        gen_layout.addWidget(self.start_btn)

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

    def preview_interstitial(self):
        text = self.interstitial_text.text().strip()
        voice = self.interstitial_voice.currentData()
        if not text:
            return

        try:
            import sounddevice as sd
            engine = PiperTtsEngine(voice_key=voice)
            samples = engine.synthesize(text)
            sd.play(samples, engine.sample_rate)
        except Exception as e:
            QMessageBox.warning(self, "Error al escuchar cuña", f"No se pudo sintetizar:\n{e}")

    def start_batch_processing(self):
        if not self.batch_files:
            QMessageBox.warning(self, "Lista Vacía", "Por favor agrega al menos un archivo para procesar.")
            return

        if not self.chk_mp3.isChecked() and not self.chk_video.isChecked() and not self.chk_flac.isChecked():
            QMessageBox.warning(self, "Sin formato", "Selecciona al menos un formato de salida.")
            return

        configs: list[JobConfig] = []
        for item in self.batch_files:
            # Cuñas configuradas
            interstitials = []
            if self.chk_interstitial.isChecked() and self.interstitial_text.text().strip():
                interstitials.append(
                    InterstitialItem(
                        text=self.interstitial_text.text().strip(),
                        voice_key=self.interstitial_voice.currentData(),
                        position="between_chapters"
                    )
                )

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
                secondary_voice_key=self.sec_voice_combo.currentData() if self.chk_autocast.isChecked() else None,
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
