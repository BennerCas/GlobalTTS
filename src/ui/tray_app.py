"""Aplicación residente en la bandeja del sistema (System Tray) con pop-up de configuración.

Permite cargar cualquier archivo (TXT, PDF, EPUB), personalizar la voz local,
la carpeta de salida, el nombre del archivo, y generar tanto el audiolibro continuo
como el video karaoke con pantalla negra sincronizada en segundo plano.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BIBLIOTECA_DIR = PROJECT_ROOT / "biblioteca"


def create_tray_pixmap() -> QPixmap:
    """Genera un ícono nítido de 64x64 con estilo tecnológico para la bandeja."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Fondo redondeado
    painter.setBrush(QColor("#1f6feb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)

    # Ondas de sonido estilizadas
    painter.setPen(Qt.PenStyle.NoPen)
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

            def progress_cb(current, total, utt):
                short_text = (utt.text[:40] + "...") if len(utt.text) > 40 else utt.text
                self.signals.progress.emit(current, total, short_text)

            metadata = pipeline.run(progress_callback=progress_cb)
            self.signals.finished.emit(metadata)
        except Exception as e:
            self.signals.error.emit(str(e))


class AudiobookDialog(QDialog):
    """Pop-up rectangular para configurar y procesar el documento seleccionado."""

    def __init__(self, file_path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.source_file = Path(file_path)
        self.worker: Optional[PipelineWorker] = None

        self.setWindowTitle("GlobalTTS — Generador de Audiolibro")
        self.setFixedSize(580, 520)
        self.setStyleSheet(DARK_THEME_QSS)

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 16)
        main_layout.setSpacing(14)

        # Encabezado
        title_lbl = QLabel("Generador de Audiolibro & Video Karaoke")
        title_lbl.setObjectName("titleLabel")
        subtitle_lbl = QLabel(f"Documento cargado: {self.source_file.name}")
        subtitle_lbl.setObjectName("subtitleLabel")
        main_layout.addWidget(title_lbl)
        main_layout.addWidget(subtitle_lbl)

        # Formulario
        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        # 1. Nombre de salida
        self.name_edit = QLineEdit(self.source_file.stem)
        form_layout.addRow("Nombre de salida:", self.name_edit)

        # 2. Selector de Voz
        self.voice_combo = QComboBox()
        voices = list_available_piper_voices()
        for k, v in voices.items():
            self.voice_combo.addItem(f"{v.name} ({v.language.upper()})", k)
        # Seleccionar es_MX-claude-high por defecto si existe
        default_idx = self.voice_combo.findData("es_MX-claude-high")
        if default_idx >= 0:
            self.voice_combo.setCurrentIndex(default_idx)
        form_layout.addRow("Voz narradora:", self.voice_combo)

        # 3. Carpeta de destino
        dest_layout = QHBoxLayout()
        self.dest_edit = QLineEdit(str(BIBLIOTECA_DIR))
        self.browse_btn = QPushButton("Examinar...")
        self.browse_btn.clicked.connect(self.browse_folder)
        dest_layout.addWidget(self.dest_edit)
        dest_layout.addWidget(self.browse_btn)
        form_layout.addRow("Guardar en:", dest_layout)

        main_layout.addLayout(form_layout)

        # Formatos
        format_group = QHBoxLayout()
        self.chk_audio = QCheckBox("Archivo de Audio (MP3 alta fidelidad)")
        self.chk_audio.setChecked(True)
        self.chk_video = QCheckBox("Video con Karaoke (Pantalla negra)")
        self.chk_video.setChecked(True)
        format_group.addWidget(self.chk_audio)
        format_group.addWidget(self.chk_video)
        main_layout.addLayout(format_group)

        # Barra de progreso y estado
        self.status_label = QLabel("Listo para iniciar.")
        self.status_label.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.status_label)
        main_layout.addWidget(self.progress_bar)

        # Botón de Generar
        self.generate_btn = QPushButton("Iniciar Generación")
        self.generate_btn.setObjectName("primaryButton")
        self.generate_btn.clicked.connect(self.start_generation)
        main_layout.addWidget(self.generate_btn)

        # Footer obligatorio (DISENO.md)
        footer_lbl = QLabel("HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®")
        footer_lbl.setObjectName("footerLabel")
        footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(footer_lbl)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta de Destino", self.dest_edit.text())
        if folder:
            self.dest_edit.setText(folder)

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

        self.generate_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.name_edit.setEnabled(False)
        self.voice_combo.setEnabled(False)
        self.status_label.setText("Procesando documento...")

        self.worker = PipelineWorker(config)
        self.worker.signals.progress.connect(self.on_progress)
        self.worker.signals.finished.connect(self.on_finished)
        self.worker.signals.error.connect(self.on_error)
        self.worker.start()

    def on_progress(self, current: int, total: int, text: str):
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"Sintetizando ({current}/{total}): {text}")

    def on_finished(self, meta: JobMetadata):
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Completado con éxito en {meta.latency_seconds}s.")
        self.generate_btn.setText("Finalizado")

        msg = f"Se generó exitosamente el audiolibro:\n\nDuración: {meta.duration_seconds}s\n"
        if meta.output_audio_path:
            msg += f"Audio: {Path(meta.output_audio_path).name}\n"
        if meta.output_video_path:
            msg += f"Video: {Path(meta.output_video_path).name}\n"

        reply = QMessageBox.information(
            self,
            "Generación Completa",
            msg,
            QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Ok
        )
        if reply == QMessageBox.StandardButton.Open:
            folder = Path(self.dest_edit.text())
            if folder.exists():
                os.startfile(folder)

        self.accept()

    def on_error(self, err_msg: str):
        self.generate_btn.setEnabled(True)
        self.status_label.setText("Error durante la generación.")
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

        # 1. Cargar archivo (Opción principal solicitada por el usuario)
        load_action = QAction("📄 Cargar archivo (Libro / Documento)...", menu)
        load_action.triggered.connect(self.open_file_dialog)
        menu.addAction(load_action)

        menu.addSeparator()

        # 2. Abrir biblioteca
        open_bib_action = QAction("📂 Abrir Biblioteca de Audios", menu)
        open_bib_action.triggered.connect(self.open_biblioteca)
        menu.addAction(open_bib_action)

        menu.addSeparator()

        # 3. Salir
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
