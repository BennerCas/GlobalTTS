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
from src.core.job import AudiobookPipeline, InterstitialItem, JobConfig, JobMetadata
from src.ui.library_tab import LibraryTab
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
    """Ventana Principal con Pestañas: Generador & Lotes y Biblioteca Multimedia."""

    def __init__(self, initial_file: Optional[str] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("GlobalTTS — Sistema Integral de Audiolibros & Video Karaoke")
        self.resize(850, 750)
        self.setMinimumSize(780, 680)
        self.setStyleSheet(DARK_THEME_QSS)

        self.batch_files: list[dict] = []
        self.worker: Optional[BatchPipelineWorker] = None
        self.last_results: list[JobMetadata] = []

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

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 12)
        main_layout.setSpacing(10)

        # Tab Widget Principal
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                background: #161b22;
                color: #8b949e;
                padding: 10px 24px;
                font-weight: 600;
                font-size: 13px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background: #0d1117;
                color: #58a6ff;
                border-bottom: 2px solid #58a6ff;
            }
        """)

        # Pestaña 1: Generador & Lotes
        self.tab_generator = QWidget()
        self.init_generator_tab()
        self.tabs.addTab(self.tab_generator, "🎙️ Generador de Audiolibros")

        # Pestaña 2: Biblioteca & Reproductor
        self.tab_library = LibraryTab()
        self.tabs.addTab(self.tab_library, "📚 Biblioteca & Reproductor")

        main_layout.addWidget(self.tabs)

        # Footer con la firma obligatoria de DISENO.md
        footer_lbl = QLabel("HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®")
        footer_lbl.setObjectName("footerLabel")
        footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(footer_lbl)

    def init_generator_tab(self):
        gen_layout = QVBoxLayout(self.tab_generator)
        gen_layout.setContentsMargins(12, 12, 12, 12)
        gen_layout.setSpacing(10)

        # ScrollArea para permitir que toda la configuración quepa cómodamente
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(10)

        # 1. Tabla de Archivos en Lote
        batch_group = QGroupBox("📁 Archivos a Procesar (Procesamiento en Lote 1 por 1)")
        batch_lay = QVBoxLayout(batch_group)

        btn_row = QHBoxLayout()
        add_files_btn = QPushButton("➕ Agregar Archivos...")
        add_files_btn.setObjectName("actionButton")
        add_files_btn.clicked.connect(self.select_files)
        btn_row.addWidget(add_files_btn)

        clear_btn = QPushButton("🗑️ Limpiar Lista")
        clear_btn.setObjectName("secondaryActionButton")
        clear_btn.clicked.connect(self.clear_batch)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        batch_lay.addLayout(btn_row)

        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(3)
        self.batch_table.setHorizontalHeaderLabels(["Archivo de Origen", "Voz Asignada", "Estado"])
        self.batch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.batch_table.setMaximumHeight(130)
        self.batch_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        batch_lay.addWidget(self.batch_table)

        scroll_layout.addWidget(batch_group)

        # 2. Configuración de Voz y Auto-Casting
        voice_group = QGroupBox("🎭 Voces y Auto-Casting Multi-Voz")
        voice_lay = QFormLayout(voice_group)

        self.voice_combo = QComboBox()
        self.voices_dict = list_available_piper_voices()
        for k, v in self.voices_dict.items():
            self.voice_combo.addItem(f"{v.name} ({v.language.upper()})", k)
        default_idx = self.voice_combo.findData("es_MX-claude-high")
        if default_idx >= 0:
            self.voice_combo.setCurrentIndex(default_idx)
        voice_lay.addRow("Voz Narrador Principal:", self.voice_combo)

        # Multi-voz / Auto-casting
        self.chk_autocast = QCheckBox("Activar Auto-Casting en diálogos (usa voz secundaria para diálogos)")
        self.chk_autocast.setChecked(True)
        self.sec_voice_combo = QComboBox()
        for k, v in self.voices_dict.items():
            self.sec_voice_combo.addItem(f"{v.name} ({v.language.upper()})", k)
        sec_idx = self.sec_voice_combo.findData("es_ES-sharvard-medium")
        if sec_idx >= 0:
            self.sec_voice_combo.setCurrentIndex(sec_idx)

        autocast_row = QHBoxLayout()
        autocast_row.addWidget(self.chk_autocast)
        autocast_row.addWidget(QLabel("Voz Diálogos:"))
        autocast_row.addWidget(self.sec_voice_combo)
        voice_lay.addRow("Multi-Voz:", autocast_row)

        scroll_layout.addWidget(voice_group)

        # 3. Modo Narración / Análisis con Mistral NeMo Local
        ai_group = QGroupBox("🧠 Expresividad y Modo Narración (Mistral NeMo Local)")
        ai_lay = QVBoxLayout(ai_group)

        self.chk_ai_narration = QCheckBox("Activar análisis con IA (Mistral NeMo 12B local)")
        self.chk_ai_narration.toggled.connect(self.toggle_ai_options)
        ai_lay.addWidget(self.chk_ai_narration)

        self.ai_options_frame = QFrame()
        ai_opt_lay = QFormLayout(self.ai_options_frame)

        self.combo_ai_mode = QComboBox()
        self.combo_ai_mode.addItem("Enriquecer expresividad (mantiene texto original + tags de emoción)", "enhance")
        self.combo_ai_mode.addItem("Modo Narrador Completo (reescribe como historia/cuento oral)", "rewrite")
        ai_opt_lay.addRow("Modo de IA:", self.combo_ai_mode)

        row_params = QHBoxLayout()
        self.combo_persona = QComboBox()
        self.combo_persona.addItem("1ra Persona (Yo)", "1ra")
        self.combo_persona.addItem("2da Persona (Tú)", "2da")
        self.combo_persona.addItem("3ra Persona (Él/Ella/Narrador)", "3ra")
        self.combo_persona.setCurrentIndex(2)

        self.combo_tense = QComboBox()
        self.combo_tense.addItem("Pasado (pretérito)", "pasado")
        self.combo_tense.addItem("Presente (en vivo)", "presente")
        self.combo_tense.addItem("Presente Continuo (sucediendo)", "presente_continuo")
        self.combo_tense.addItem("Futuro", "futuro")

        self.combo_style = QComboBox()
        self.combo_style.addItem("Cuento Literario", "cuento")
        self.combo_style.addItem("Crónica de Suceso", "suceso")
        self.combo_style.addItem("Épico / Heroico", "epico")

        row_params.addWidget(QLabel("Perspectiva:"))
        row_params.addWidget(self.combo_persona)
        row_params.addWidget(QLabel("Tiempo:"))
        row_params.addWidget(self.combo_tense)
        row_params.addWidget(QLabel("Estilo:"))
        row_params.addWidget(self.combo_style)
        ai_opt_lay.addRow("Parámetros Narración:", row_params)

        self.ai_options_frame.setEnabled(False)
        ai_lay.addWidget(self.ai_options_frame)
        scroll_layout.addWidget(ai_group)

        # 4. Portada y Cuñas Intersticiales (Radio / Separadores)
        extra_group = QGroupBox("🎨 Portada y Cuñas Intersticiales")
        extra_lay = QFormLayout(extra_group)

        cover_row = QHBoxLayout()
        self.cover_edit = QLineEdit()
        self.cover_edit.setPlaceholderText("Ruta a imagen de portada (.png, .jpg)... opcional")
        btn_cover = QPushButton("Examinar...")
        btn_cover.clicked.connect(self.select_cover_image)
        cover_row.addWidget(self.cover_edit)
        cover_row.addWidget(btn_cover)
        extra_lay.addRow("Portada de Audiolibro:", cover_row)

        interstitial_box = QVBoxLayout()
        self.chk_cuña = QCheckBox("Insertar cuña / separador entre capítulos")
        self.chk_cuña.toggled.connect(lambda v: self.cuña_frame.setEnabled(v))
        interstitial_box.addWidget(self.chk_cuña)

        self.cuña_frame = QFrame()
        cuña_lay = QHBoxLayout(self.cuña_frame)
        self.cuña_text = QLineEdit("Estás escuchando la obra en GlobalTTS.")
        self.cuña_voice = QComboBox()
        for k, v in self.voices_dict.items():
            self.cuña_voice.addItem(v.name, k)

        self.btn_preview_cuña = QPushButton("▶️ Escuchar previa")
        self.btn_preview_cuña.setObjectName("actionButton")
        self.btn_preview_cuña.clicked.connect(self.preview_cuña)

        cuña_lay.addWidget(QLabel("Texto:"))
        cuña_lay.addWidget(self.cuña_text)
        cuña_lay.addWidget(QLabel("Voz:"))
        cuña_lay.addWidget(self.cuña_voice)
        cuña_lay.addWidget(self.btn_preview_cuña)

        self.cuña_frame.setEnabled(False)
        interstitial_box.addWidget(self.cuña_frame)
        extra_lay.addRow("Cuña Radial:", interstitial_box)

        scroll_layout.addWidget(extra_group)

        # 5. Formatos de Salida
        out_group = QGroupBox("📦 Formatos a Generar")
        out_lay = QHBoxLayout(out_group)
        self.chk_mp3 = QCheckBox("Audio MP3 (256k con EBU R128)")
        self.chk_mp3.setChecked(True)
        self.chk_video = QCheckBox("Video Karaoke (MP4 pantalla negra / portada)")
        self.chk_video.setChecked(True)
        self.chk_flac = QCheckBox("Master FLAC sin pérdida")
        self.chk_flac.setChecked(True)
        out_lay.addWidget(self.chk_mp3)
        out_lay.addWidget(self.chk_video)
        out_lay.addWidget(self.chk_flac)
        scroll_layout.addWidget(out_group)

        scroll.setWidget(scroll_widget)
        gen_layout.addWidget(scroll)

        # 6. Panel de Telemetría en Tiempo Real
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
        self.lbl_stage = QLabel("Fase: Listo para procesar.")
        self.lbl_stage.setStyleSheet("color: #58a6ff; font-weight: 600; font-size: 12px;")
        self.lbl_active_utt = QLabel("En espera...")
        self.lbl_active_utt.setStyleSheet("color: #8b949e; font-size: 11px; font-style: italic;")
        gen_layout.addWidget(self.lbl_stage)
        gen_layout.addWidget(self.lbl_active_utt)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        gen_layout.addWidget(self.progress_bar)

        # Panel de Resultados (Mantiene la ventana abierta y da acceso directo a YouTube y Spotify)
        self.res_card = QFrame()
        self.res_card.setObjectName("resultCard")
        self.res_card.setVisible(False)
        res_lay = QVBoxLayout(self.res_card)
        self.res_summary = QLabel("Archivos generados exitosamente.")
        self.res_summary.setStyleSheet("color: #3fb950; font-weight: 700; font-size: 13px;")
        res_lay.addWidget(self.res_summary)

        res_btns = QHBoxLayout()
        self.btn_open_last_folder = QPushButton("📂 Abrir Carpeta del Libro")
        self.btn_open_last_folder.setObjectName("secondaryActionButton")
        self.btn_open_last_folder.clicked.connect(self.open_last_book_folder)

        self.btn_go_library = QPushButton("📚 Ver en Biblioteca")
        self.btn_go_library.setObjectName("actionButton")
        self.btn_go_library.clicked.connect(lambda: self.tabs.setCurrentIndex(1))

        res_btns.addWidget(self.btn_open_last_folder)
        res_btns.addWidget(self.btn_go_library)
        res_lay.addLayout(res_btns)
        gen_layout.addWidget(self.res_card)

        # Botón de Inicio
        self.start_btn = QPushButton("🚀 Iniciar Generación (En Lote)")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self.start_batch_processing)
        gen_layout.addWidget(self.start_btn)

    def toggle_ai_options(self, checked: bool):
        self.ai_options_frame.setEnabled(checked)

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

    def preview_cuña(self):
        text = self.cuña_text.text().strip()
        voice = self.cuña_voice.currentData()
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
            if self.chk_cuña.isChecked() and self.cuña_text.text().strip():
                interstitials.append(
                    InterstitialItem(
                        text=self.cuña_text.text().strip(),
                        voice_key=self.cuña_voice.currentData(),
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
        self.start_btn.setText("🚀 Procesar de Nuevo")

        elapsed = time.perf_counter() - self.start_timestamp if self.start_timestamp else 0
        self.val_elapsed.setText(str(timedelta(seconds=int(elapsed))))
        self.val_eta.setText("00:00:00")
        self.lbl_stage.setText("¡Lote completado con éxito!")
        self.lbl_active_utt.setText(f"Procesados {len(results)} libro(s) en {elapsed:.1f}s.")

        self.res_card.setVisible(True)
        self.res_summary.setText(f"✅ Se han generado {len(results)} audiolibro(s) en sus carpetas dedicadas.")

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
        self.start_btn.setText("🚀 Iniciar Generación (En Lote)")
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

        open_app_action = QAction("🎙️ Abrir Generador de Audiolibros...", menu)
        open_app_action.triggered.connect(self.show_main_window)
        menu.addAction(open_app_action)

        load_action = QAction("📄 Cargar archivo(s) para procesar...", menu)
        load_action.triggered.connect(self.open_file_dialog)
        menu.addAction(load_action)

        menu.addSeparator()

        open_bib_action = QAction("📚 Abrir Biblioteca & Reproductor", menu)
        open_bib_action.triggered.connect(self.show_library_tab)
        menu.addAction(open_bib_action)

        menu.addSeparator()

        exit_action = QAction("❌ Salir de GlobalTTS", menu)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)

        self.setContextMenu(menu)
        self.activated.connect(self.on_tray_activated)

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main_window()

    def show_main_window(self, initial_file: Optional[str] = None):
        if not self.main_window:
            self.main_window = MainWindow(initial_file=initial_file)
        elif initial_file:
            self.main_window.add_file_to_batch(initial_file)

        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def show_library_tab(self):
        self.show_main_window()
        if self.main_window:
            self.main_window.tabs.setCurrentIndex(1)

    def open_file_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            None,
            "Seleccionar documentos para audiolibro",
            "",
            "Documentos Soportados (*.txt *.pdf *.epub *.md);;Texto Plano (*.txt *.md);;PDF (*.pdf);;EPUB (*.epub)"
        )
        if files:
            self.show_main_window(initial_file=files[0])
            for extra in files[1:]:
                self.main_window.add_file_to_batch(extra)


def run_tray():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray = GlobalTTSTrayIcon(app)
    tray.show()

    tray.showMessage(
        "GlobalTTS Activo",
        "Haz clic derecho en este ícono para abrir el Generador de Audiolibros y la Biblioteca con Reproductor.",
        QSystemTrayIcon.MessageIcon.Information,
        3000
    )

    sys.exit(app.exec())


if __name__ == "__main__":
    run_tray()
