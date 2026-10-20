"""Aplicación residente en la bandeja del sistema (System Tray) con pop-up interactivo y monitoreo en tiempo real.

Permite cargar cualquier archivo (TXT, PDF, EPUB), personalizar la voz local,
la carpeta de salida, el nombre del archivo, y monitorear el progreso y tiempos reales
(tiempo transcurrido, tiempo estimado restante, velocidad y fase) manteniendo
la ventana abierta con acceso inmediato a los archivos generados.
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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.ai.piper_engine import list_available_piper_voices
from src.core.job import AudiobookPipeline, JobConfig, JobMetadata
from src.ui.styles import DARK_THEME_QSS

BIBLIOTECA_DIR = PROJECT_ROOT / "biblioteca"


def create_tray_pixmap() -> QPixmap:
    """Genera un ícono nítido de 64x64 con estilo tecnológico para la bandeja."""
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


class WorkerSignals(QObject):
    stage = pyqtSignal(str, str, float)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class PipelineWorker(QThread):
    def __init__(self, config: JobConfig):
        super().__init__()
        self.config = config
        self.signals = WorkerSignals()

    def run(self):
        try:
            pipeline = AudiobookPipeline(self.config)

            def stage_cb(stg: str, desc: str, pct: float):
                self.signals.stage.emit(stg, desc, pct)

            def progress_cb(current: int, total: int, utt):
                short_text = (utt.text[:65] + "...") if len(utt.text) > 65 else utt.text
                self.signals.progress.emit(current, total, short_text)

            metadata = pipeline.run(progress_callback=progress_cb, stage_callback=stage_cb)
            self.signals.finished.emit(metadata)
        except Exception as e:
            self.signals.error.emit(str(e))


class AudiobookDialog(QDialog):
    """Pop-up rectangular para configurar y monitorear en tiempo real el audiolibro."""

    def __init__(self, file_path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.source_file = Path(file_path)
        self.worker: Optional[PipelineWorker] = None
        self.last_metadata: Optional[JobMetadata] = None

        # Variables de tiempo y telemetría
        self.start_timestamp: Optional[float] = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_timer_tick)

        self.current_stage: str = "idle"
        self.stage_base_pct: float = 0.0
        self.current_utt_count: int = 0
        self.total_utts: int = 0

        self.setWindowTitle("GlobalTTS — Generador de Audiolibro & Video Karaoke")
        self.setFixedSize(680, 680)
        self.setStyleSheet(DARK_THEME_QSS)

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 16)
        main_layout.setSpacing(12)

        # Encabezado
        title_lbl = QLabel("Generador de Audiolibro & Video Karaoke")
        title_lbl.setObjectName("titleLabel")
        self.subtitle_lbl = QLabel(f"Documento cargado: {self.source_file.name}")
        self.subtitle_lbl.setObjectName("subtitleLabel")
        main_layout.addWidget(title_lbl)
        main_layout.addWidget(self.subtitle_lbl)

        # 1. Tarjeta de Configuración
        config_card = QFrame()
        config_card.setObjectName("cardFrame")
        form_layout = QFormLayout(config_card)
        form_layout.setSpacing(10)

        self.name_edit = QLineEdit(self.source_file.stem)
        form_layout.addRow("Nombre de salida:", self.name_edit)

        self.voice_combo = QComboBox()
        voices = list_available_piper_voices()
        for k, v in voices.items():
            self.voice_combo.addItem(f"{v.name} ({v.language.upper()})", k)
        default_idx = self.voice_combo.findData("es_MX-claude-high")
        if default_idx >= 0:
            self.voice_combo.setCurrentIndex(default_idx)
        form_layout.addRow("Voz narradora:", self.voice_combo)

        dest_layout = QHBoxLayout()
        self.dest_edit = QLineEdit(str(BIBLIOTECA_DIR))
        self.browse_btn = QPushButton("Examinar...")
        self.browse_btn.clicked.connect(self.browse_folder)
        dest_layout.addWidget(self.dest_edit)
        dest_layout.addWidget(self.browse_btn)
        form_layout.addRow("Guardar en:", dest_layout)

        format_group = QHBoxLayout()
        self.chk_audio = QCheckBox("Archivo de Audio (MP3 alta fidelidad)")
        self.chk_audio.setChecked(True)
        self.chk_video = QCheckBox("Video con Karaoke (Pantalla negra)")
        self.chk_video.setChecked(True)
        format_group.addWidget(self.chk_audio)
        format_group.addWidget(self.chk_video)
        form_layout.addRow("Formatos:", format_group)

        main_layout.addWidget(config_card)

        # 2. Panel de Telemetría y Tiempo Real (Cards de Métricas)
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(10)

        # Métrica: Tiempo Transcurrido
        card_elapsed = QFrame()
        card_elapsed.setObjectName("metricCard")
        lay_elapsed = QVBoxLayout(card_elapsed)
        lay_elapsed.setContentsMargins(6, 6, 6, 6)
        lbl_e_title = QLabel("Transcurrido")
        lbl_e_title.setObjectName("metricTitle")
        self.val_elapsed = QLabel("00:00:00")
        self.val_elapsed.setObjectName("metricValue")
        lay_elapsed.addWidget(lbl_e_title)
        lay_elapsed.addWidget(self.val_elapsed)
        metrics_layout.addWidget(card_elapsed)

        # Métrica: Tiempo Estimado Restante (ETA)
        card_eta = QFrame()
        card_eta.setObjectName("metricCard")
        lay_eta = QVBoxLayout(card_eta)
        lay_eta.setContentsMargins(6, 6, 6, 6)
        lbl_eta_title = QLabel("Restante (ETA)")
        lbl_eta_title.setObjectName("metricTitle")
        self.val_eta = QLabel("--:--:--")
        self.val_eta.setObjectName("metricValue")
        lay_eta.addWidget(lbl_eta_title)
        lay_eta.addWidget(self.val_eta)
        metrics_layout.addWidget(card_eta)

        # Métrica: Velocidad en Tiempo Real
        card_speed = QFrame()
        card_speed.setObjectName("metricCard")
        lay_speed = QVBoxLayout(card_speed)
        lay_speed.setContentsMargins(6, 6, 6, 6)
        lbl_s_title = QLabel("Velocidad")
        lbl_s_title.setObjectName("metricTitle")
        self.val_speed = QLabel("-- orac/s")
        self.val_speed.setObjectName("metricValueActive")
        lay_speed.addWidget(lbl_s_title)
        lay_speed.addWidget(self.val_speed)
        metrics_layout.addWidget(card_speed)

        main_layout.addLayout(metrics_layout)

        # 3. Estado detallado y Barra de Progreso
        self.phase_label = QLabel("Fase: Listo para iniciar.")
        self.phase_label.setStyleSheet("color: #58a6ff; font-weight: 600; font-size: 12px;")
        self.snippet_label = QLabel("Esperando inicio...")
        self.snippet_label.setStyleSheet("color: #8b949e; font-size: 11px; font-style: italic;")
        main_layout.addWidget(self.phase_label)
        main_layout.addWidget(self.snippet_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        main_layout.addWidget(self.progress_bar)

        # 4. Panel de Resultados (Oculto inicialmente, se muestra al terminar y mantiene la ventana abierta)
        self.result_card = QFrame()
        self.result_card.setObjectName("resultCard")
        self.result_card.setVisible(False)
        result_layout = QVBoxLayout(self.result_card)
        result_layout.setSpacing(8)

        self.result_summary = QLabel("Archivos generados exitosamente.")
        self.result_summary.setStyleSheet("color: #3fb950; font-weight: 700; font-size: 13px;")
        result_layout.addWidget(self.result_summary)

        # Botones de Acción sobre los archivos producidos
        action_buttons_layout = QHBoxLayout()
        self.play_audio_btn = QPushButton("▶️ Reproducir Audio")
        self.play_audio_btn.setObjectName("actionButton")
        self.play_audio_btn.clicked.connect(self.play_audio_action)

        self.play_video_btn = QPushButton("🎬 Ver Video Karaoke")
        self.play_video_btn.setObjectName("actionButton")
        self.play_video_btn.clicked.connect(self.play_video_action)

        self.open_folder_btn = QPushButton("📂 Abrir Carpeta")
        self.open_folder_btn.setObjectName("secondaryActionButton")
        self.open_folder_btn.clicked.connect(self.open_folder_action)

        action_buttons_layout.addWidget(self.play_audio_btn)
        action_buttons_layout.addWidget(self.play_video_btn)
        action_buttons_layout.addWidget(self.open_folder_btn)
        result_layout.addLayout(action_buttons_layout)

        main_layout.addWidget(self.result_card)

        # 5. Botones de Control Principal
        ctrl_layout = QHBoxLayout()
        self.generate_btn = QPushButton("Iniciar Generación")
        self.generate_btn.setObjectName("primaryButton")
        self.generate_btn.clicked.connect(self.start_generation)
        ctrl_layout.addWidget(self.generate_btn)

        self.change_file_btn = QPushButton("📄 Cargar otro documento")
        self.change_file_btn.setObjectName("secondaryActionButton")
        self.change_file_btn.clicked.connect(self.change_source_file)
        ctrl_layout.addWidget(self.change_file_btn)

        main_layout.addLayout(ctrl_layout)

        # Footer obligatorio (DISENO.md)
        footer_lbl = QLabel("HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®")
        footer_lbl.setObjectName("footerLabel")
        footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(footer_lbl)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta de Destino", self.dest_edit.text())
        if folder:
            self.dest_edit.setText(folder)

    def change_source_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar nuevo libro o documento",
            "",
            "Documentos Soportados (*.txt *.pdf *.epub *.md);;Texto Plano (*.txt *.md);;PDF (*.pdf);;EPUB (*.epub)"
        )
        if file_path:
            self.source_file = Path(file_path)
            self.subtitle_lbl.setText(f"Documento cargado: {self.source_file.name}")
            self.name_edit.setText(self.source_file.stem)
            self.reset_ui_state()

    def reset_ui_state(self):
        self.result_card.setVisible(False)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Iniciar Generación")
        self.browse_btn.setEnabled(True)
        self.name_edit.setEnabled(True)
        self.voice_combo.setEnabled(True)
        self.chk_audio.setEnabled(True)
        self.chk_video.setEnabled(True)
        self.progress_bar.setValue(0)
        self.val_elapsed.setText("00:00:00")
        self.val_eta.setText("--:--:--")
        self.val_speed.setText("-- orac/s")
        self.phase_label.setText("Fase: Listo para iniciar.")
        self.snippet_label.setText("Esperando inicio...")

    def start_generation(self):
        if not self.chk_audio.isChecked() and not self.chk_video.isChecked():
            QMessageBox.warning(self, "Atención", "Debes seleccionar al menos un formato (Audio o Video).")
            return

        config = JobConfig(
            source_file=str(self.source_file),
            voice_key=self.voice_combo.currentData(),
            output_name=self.name_edit.text().strip(),
            output_dir=self.dest_edit.text().strip(),
            generate_audio=self.chk_audio.isChecked(),
            generate_video=self.chk_video.isChecked(),
        )

        self.reset_ui_state()
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("Procesando en vivo...")
        self.browse_btn.setEnabled(False)
        self.name_edit.setEnabled(False)
        self.voice_combo.setEnabled(False)
        self.chk_audio.setEnabled(False)
        self.chk_video.setEnabled(False)

        # Iniciar cronómetro en tiempo real
        self.start_timestamp = time.perf_counter()
        self.current_utt_count = 0
        self.total_utts = 0
        self.timer.start()

        self.worker = PipelineWorker(config)
        self.worker.signals.stage.connect(self.on_stage)
        self.worker.signals.progress.connect(self.on_progress)
        self.worker.signals.finished.connect(self.on_finished)
        self.worker.signals.error.connect(self.on_error)
        self.worker.start()

    def update_timer_tick(self):
        if self.start_timestamp is None:
            return
        elapsed = time.perf_counter() - self.start_timestamp
        self.val_elapsed.setText(str(timedelta(seconds=int(elapsed))))

        # Calcular velocidad en tiempo real y ETA
        if self.current_utt_count > 0 and elapsed > 0.5:
            rate = self.current_utt_count / elapsed
            self.val_speed.setText(f"{rate:.1f} orac/s")

            # Estimar ETA si conocemos el total de oraciones
            if self.total_utts > self.current_utt_count and rate > 0:
                remaining_utts = self.total_utts - self.current_utt_count
                remaining_secs = remaining_utts / rate
                # Agregar margen proporcional para normalización y video si están activos
                if self.chk_video.isChecked():
                    remaining_secs += max(3.0, remaining_secs * 0.25)
                self.val_eta.setText(str(timedelta(seconds=int(remaining_secs))))

    def on_stage(self, stage: str, desc: str, base_pct: float):
        self.current_stage = stage
        self.stage_base_pct = base_pct
        self.phase_label.setText(f"Fase: {desc}")
        if stage != "synthesize":
            self.progress_bar.setValue(int(base_pct))

    def on_progress(self, current: int, total: int, text: str):
        self.current_utt_count = current
        self.total_utts = total

        # Rango asignado a la síntesis en la barra de progreso
        # Si hay video: 10% a 80%. Si no hay video: 10% a 92%.
        max_synth_pct = 80.0 if self.chk_video.isChecked() else 92.0
        synth_ratio = (current / total) if total > 0 else 0
        global_pct = 10.0 + (synth_ratio * (max_synth_pct - 10.0))

        self.progress_bar.setValue(int(global_pct))
        self.phase_label.setText(f"Fase: Sintetizando oraciones con voz local [{current}/{total}]")
        self.snippet_label.setText(f"\"{text}\"")

    def on_finished(self, meta: JobMetadata):
        self.timer.stop()
        self.last_metadata = meta

        # Calcular tiempo final exacto
        elapsed = time.perf_counter() - self.start_timestamp if self.start_timestamp else meta.latency_seconds
        self.val_elapsed.setText(str(timedelta(seconds=int(elapsed))))
        self.val_eta.setText("00:00:00")
        self.progress_bar.setValue(100)

        self.phase_label.setText("Fase: ¡Audiolibro y Video generados con éxito!")
        self.snippet_label.setText(f"Duración de audio: {meta.duration_seconds:.1f}s | Tiempo de proceso: {elapsed:.1f}s")

        # Activar panel de resultados
        self.result_card.setVisible(True)
        summary_text = (
            f"✅ Proceso completado en {elapsed:.1f}s ({meta.total_utterances} oraciones).\n"
            f"🎵 Duración del audiolibro: {timedelta(seconds=int(meta.duration_seconds))}"
        )
        self.result_summary.setText(summary_text)

        self.play_audio_btn.setVisible(bool(meta.output_audio_path))
        self.play_video_btn.setVisible(bool(meta.output_video_path))

        # Re-habilitar botón principal para nuevos procesamientos manteniendo la ventana abierta
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Volver a Generar")
        self.browse_btn.setEnabled(True)
        self.name_edit.setEnabled(True)
        self.voice_combo.setEnabled(True)
        self.chk_audio.setEnabled(True)
        self.chk_video.setEnabled(True)

    def play_audio_action(self):
        if self.last_metadata and self.last_metadata.output_audio_path:
            p = Path(self.last_metadata.output_audio_path)
            if p.exists():
                os.startfile(p)

    def play_video_action(self):
        if self.last_metadata and self.last_metadata.output_video_path:
            p = Path(self.last_metadata.output_video_path)
            if p.exists():
                os.startfile(p)

    def open_folder_action(self):
        folder = Path(self.dest_edit.text())
        if folder.exists():
            os.startfile(folder)

    def on_error(self, err_msg: str):
        self.timer.stop()
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("Iniciar Generación")
        self.browse_btn.setEnabled(True)
        self.name_edit.setEnabled(True)
        self.voice_combo.setEnabled(True)
        self.chk_audio.setEnabled(True)
        self.chk_video.setEnabled(True)

        self.phase_label.setText("Fase: Error en el proceso.")
        self.snippet_label.setText(err_msg)
        QMessageBox.critical(self, "Error en el Pipeline", f"Ocurrió un error:\n\n{err_msg}")


class GlobalTTSTrayIcon(QSystemTrayIcon):
    """Ícono de GlobalTTS en la barra de herramientas del sistema."""

    def __init__(self, parent: Optional[QApplication] = None):
        super().__init__(parent)
        self.setIcon(QIcon(create_tray_pixmap()))
        self.setToolTip("GlobalTTS — Servicio Activo de Voz y Audiolibros")

        self.current_dialog: Optional[AudiobookDialog] = None
        self.create_menu()

    def create_menu(self):
        menu = QMenu()
        menu.setStyleSheet(DARK_THEME_QSS)

        load_action = QAction("📄 Cargar archivo (Libro / Documento)...", menu)
        load_action.triggered.connect(self.open_file_dialog)
        menu.addAction(load_action)

        menu.addSeparator()

        open_bib_action = QAction("📂 Abrir Biblioteca de Audios", menu)
        open_bib_action.triggered.connect(self.open_biblioteca)
        menu.addAction(open_bib_action)

        menu.addSeparator()

        exit_action = QAction("❌ Salir de GlobalTTS", menu)
        exit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(exit_action)

        self.setContextMenu(menu)

    def open_file_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            None,
            "Seleccionar libro o documento",
            "",
            "Documentos Soportados (*.txt *.pdf *.epub *.md);;Texto Plano (*.txt *.md);;PDF (*.pdf);;EPUB (*.epub)"
        )
        if file_path:
            self.show_config_dialog(file_path)

    def show_config_dialog(self, file_path: str):
        self.current_dialog = AudiobookDialog(file_path)
        self.current_dialog.show()
        self.current_dialog.raise_()
        self.current_dialog.activateWindow()

    def open_biblioteca(self):
        BIBLIOTECA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(BIBLIOTECA_DIR)


def run_tray():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray = GlobalTTSTrayIcon(app)
    tray.show()

    tray.showMessage(
        "GlobalTTS Activo",
        "Haz clic derecho en este ícono para cargar libros o documentos y generar audiolibros.",
        QSystemTrayIcon.MessageIcon.Information,
        3000
    )

    sys.exit(app.exec())


if __name__ == "__main__":
    run_tray()
