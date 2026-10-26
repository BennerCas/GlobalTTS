"""Aplicación residente en la bandeja del sistema (System Tray) con Generador en Lote y Reproductor de Biblioteca.

Cumple con todos los requisitos:
- Procesamiento en lote secuencial (1 por 1) con Pausa/Reanudación, Cancelación y Reordenamiento.
- Ingesta OCR WinRT nativo para PDFs escaneados e imágenes + Extractor Web URL + Limpieza Editorial.
- Enriquecimiento con Mistral NeMo local (modo narración en 1ra/2da/3ra persona, tiempos verbales y Trailer 90s).
- Inserción de cuñas de audio con escucha previa instantánea.
- Auto-casting multi-voz para diálogos y personajes + Clonación Biométrica Local (CampPlus ONNX).
- Portada IA 1024x1024 automática para carátula MP3/M4B y fondo de video karaoke.
- Masterización DSP de 5 etapas, Efectos Foley SFX, Soundscapes Estéreo con Auto-Ducking, Lexicon Fonético y Prosodia Emocional.
- Video Karaoke 16:9 / 9:16 con Espectrograma Showwaves, temas de subtítulos y exportación .SRT/.VTT/.LRC.
- Servidor WiFi Mobile Streaming con QR nativo + Paquete SEO YouTube/Spotify y Feed RSS 2.0.
- Telemetría en tiempo real: DirectML/Olive/RAM/Caché, cronómetro digital, ETA, velocidad y oración activa.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
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
from src.audio.karaoke import ASPECT_RATIOS, SUBTITLE_THEMES, VIDEO_BACKGROUNDS
from src.audio.soundscape import SOUNDSCAPE_PRESETS
from src.core.audio_cache import GLOBAL_AUDIO_CACHE
from src.core.hardware_monitor import HardwareMonitor
from src.core.job import AudiobookPipeline, InterstitialItem, JobConfig, JobMetadata
from src.ui.library_tab import LibraryTab
from src.ui.manual_tab import ManualTab
from src.ui.prompt_manager_dialog import PromptManagerDialog, PromptManagerWidget
from src.ui.quick_reader_tab import QuickReaderTab
from src.ui.studio_dialogs import (
    LexiconManagerDialog,
    MobileStreamingDialog,
    UrlIngestDialog,
    VoiceClonerDialog,
)
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
        self.pause_event = threading.Event()
        self.pause_event.set()  # Despausado por defecto

    def set_paused(self, paused: bool) -> None:
        if paused:
            self.pause_event.clear()
        else:
            self.pause_event.set()

    def is_paused(self) -> bool:
        return not self.pause_event.is_set()

    def cancel(self) -> None:
        self.is_cancelled = True
        self.pause_event.set()

    def run(self):
        results = []
        try:
            for idx, cfg in enumerate(self.configs):
                self.pause_event.wait()
                if self.is_cancelled:
                    break

                src_label = cfg.source_file if cfg.source_file.startswith(("http://", "https://")) else Path(cfg.source_file).name
                self.signals.item_started.emit(idx, src_label)
                pipeline = AudiobookPipeline(cfg)

                def stage_cb(stg: str, desc: str, pct: float):
                    self.signals.stage.emit(stg, desc, pct)

                def prog_cb(current: int, total: int, utt):
                    short_text = (utt.text[:65] + "...") if len(utt.text) > 65 else utt.text
                    self.signals.progress.emit(current, total, short_text)

                meta = pipeline.run(
                    progress_callback=prog_cb,
                    stage_callback=stage_cb,
                    pause_event=self.pause_event,
                )
                results.append(meta)
                self.signals.item_finished.emit(idx, meta)

            self.signals.batch_finished.emit(results)
        except Exception as e:
            self.signals.error.emit(str(e))


class MainWindow(QDialog):
    """Ventana Principal con Pestañas: Lectura Rápida, Generador & Lotes, Biblioteca y Prompts Maestros."""

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
        self.custom_bgm_path: Optional[str] = None

        # Telemetría de proceso y hardware
        self.hw_monitor = HardwareMonitor()
        self.hw_monitor.enforce_environment()
        self.start_timestamp: Optional[float] = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_timer_tick)

        self.hw_timer = QTimer(self)
        self.hw_timer.setInterval(2000)
        self.hw_timer.timeout.connect(self.update_hw_telemetry)
        self.hw_timer.start()

        self.current_utt_count = 0
        self.total_utts = 0
        self.voices_dict = list_available_piper_voices()

        self.init_ui()
        self.update_hw_telemetry()
        self.apply_orientation(force=True)

        if initial_file:
            self.add_file_to_batch(initial_file)
            self.tabs.setCurrentIndex(1)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 10)
        main_layout.setSpacing(8)

        # Barra Superior de Control, Telemetría de Hardware y Accesos de Estudio
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)
        title_group = QVBoxLayout()
        app_title = QLabel("GlobalTTS — Suite Integral de Voz, Audiolibros & Videos Karaoke")
        app_title.setObjectName("titleLabel")
        app_sub = QLabel("100% Offline • Costo Cero • Aceleración DirectML, DSP Mastering & Clonación ONNX")
        app_sub.setObjectName("subtitleLabel")
        title_group.addWidget(app_title)
        title_group.addWidget(app_sub)
        top_bar.addLayout(title_group)

        top_bar.addStretch()

        self.lbl_hw_telemetry = QLabel("DirectML • CPU: --% • RAM: -- GB • Caché: -- MB")
        self.lbl_hw_telemetry.setStyleSheet(
            "background-color: #12161f; color: #58a6ff; border: 1px solid #21262d; "
            "border-radius: 5px; padding: 4px 8px; font-size: 11px; font-weight: 600;"
        )
        self.lbl_hw_telemetry.setToolTip("Telemetría de Hardware y Runtime ONNX/DirectML en Tiempo Real")
        top_bar.addWidget(self.lbl_hw_telemetry)

        self.btn_orientation = QPushButton("[ ↕ ] Modo: Auto (Vertical)")
        self.btn_orientation.setObjectName("secondaryActionButton")
        self.btn_orientation.setToolTip("Alterna la distribución de la app entre Vertical (Monitores Retrato) y Horizontal (Panorámico)")
        self.btn_orientation.clicked.connect(self.cycle_orientation)
        top_bar.addWidget(self.btn_orientation)

        self.btn_minimize = QPushButton("[ _ ] Minimizar")
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
        self.tab_library.load_text_requested.connect(self.on_library_load_text_requested)
        self.tabs.addTab(self.tab_library, "BIBLIOTECA & REPRODUCTOR")

        # Pestaña 4: Gestor de Prompts Maestros & Estilos IA
        self.tab_prompts = PromptManagerWidget(library=self.prompt_library)
        self.tab_prompts.prompts_updated.connect(self.refresh_styles_combo)
        self.tabs.addTab(self.tab_prompts, "PROMPTS MAESTROS & ESTILOS IA")

        # Pestaña 5: Manual de Uso Completo
        self.tab_manual = ManualTab()
        self.tabs.addTab(self.tab_manual, "MANUAL DE USO COMPLETO")

        # Cableado cruzado de señales en tiempo real entre pestañas
        self.tab_quick.history_updated.connect(self.tab_library.refresh_library)
        self.tab_quick.voices_changed.connect(self.refresh_all_voices)
        self.tab_prompts.prompts_updated.connect(self.tab_quick.refresh_styles_combo)

        # Botones de Estudio ubicados en la fila de pestañas (al costado de MANUAL DE USO COMPLETO)
        self.tab_corner_bar = QWidget()
        corner_lay = QHBoxLayout(self.tab_corner_bar)
        corner_lay.setContentsMargins(4, 2, 0, 0)
        corner_lay.setSpacing(4)

        self.btn_top_wifi = QPushButton("[ ↗ ] WiFi QR")
        self.btn_top_wifi.setObjectName("tabCornerButton")
        self.btn_top_wifi.setToolTip("Abrir Servidor Local de Streaming Móvil con Código QR")
        self.btn_top_wifi.clicked.connect(self.open_mobile_streaming_dialog)
        corner_lay.addWidget(self.btn_top_wifi)

        self.btn_top_lexicon = QPushButton("[ ↗ ] Lexicon")
        self.btn_top_lexicon.setObjectName("tabCornerButton")
        self.btn_top_lexicon.setToolTip("Diccionario Fonético Personalizado y Pronunciación")
        self.btn_top_lexicon.clicked.connect(self.open_lexicon_dialog)
        corner_lay.addWidget(self.btn_top_lexicon)

        self.btn_top_cloner = QPushButton("[ ★ ] Clonar Voz")
        self.btn_top_cloner.setObjectName("tabCornerButton")
        self.btn_top_cloner.setToolTip("Clonador Biométrico de Voz Local (CampPlus ONNX)")
        self.btn_top_cloner.clicked.connect(self.open_voice_cloner_dialog)
        corner_lay.addWidget(self.btn_top_cloner)

        self.btn_top_cache = QPushButton("[ × ] Caché")
        self.btn_top_cache.setObjectName("tabCornerButton")
        self.btn_top_cache.setToolTip("Purgar caché en disco de segmentos de voz sintetizados")
        self.btn_top_cache.clicked.connect(self.clear_audio_cache_action)
        corner_lay.addWidget(self.btn_top_cache)

        self.tabs.setCornerWidget(self.tab_corner_bar, Qt.Corner.TopRightCorner)

        main_layout.addWidget(self.tabs)

        # Footer con la firma obligatoria de DISENO.md
        footer_lbl = QLabel("HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®")
        footer_lbl.setObjectName("footerLabel")
        footer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(footer_lbl)

    def update_hw_telemetry(self):
        try:
            snap = self.hw_monitor.snapshot()
            self.lbl_hw_telemetry.setText(snap.format_badge_text())
        except Exception:
            pass

    def open_mobile_streaming_dialog(self):
        dlg = MobileStreamingDialog(parent=self)
        dlg.exec()

    def open_lexicon_dialog(self):
        dlg = LexiconManagerDialog(parent=self)
        dlg.exec()

    def open_voice_cloner_dialog(self):
        dlg = VoiceClonerDialog(parent=self)
        dlg.voice_cloned.connect(lambda _: self.refresh_all_voices())
        dlg.exec()
        self.refresh_all_voices()

    def refresh_all_voices(self):
        self.voices_dict = list_available_piper_voices()
        curr = self.voice_combo.currentData()
        self.voice_combo.clear()
        for k, v in self.voices_dict.items():
            tag = "24kHz Studio" if v.engine in ("kokoro", "cloned") else f"{v.sample_rate // 1000}kHz"
            self.voice_combo.addItem(f"{v.name} [{tag}]", k)
        idx = self.voice_combo.findData(curr)
        if idx >= 0:
            self.voice_combo.setCurrentIndex(idx)
        self.populate_voice_pool_table()
        if hasattr(self, "table_cunas"):
            for r in range(self.table_cunas.rowCount()):
                v_combo = self.table_cunas.cellWidget(r, 2)
                if isinstance(v_combo, QComboBox):
                    c_vk = v_combo.currentData()
                    v_combo.clear()
                    for k, v in self.voices_dict.items():
                        tag = "24k" if v.engine in ("kokoro", "cloned") else f"{v.sample_rate // 1000}k"
                        v_combo.addItem(f"{v.name} [{tag}]", k)
                    idx_v = v_combo.findData(c_vk)
                    if idx_v >= 0:
                        v_combo.setCurrentIndex(idx_v)
        if hasattr(self, "tab_quick") and hasattr(self.tab_quick, "populate_voices"):
            self.tab_quick.populate_voices()

    def clear_audio_cache_action(self):
        removed = GLOBAL_AUDIO_CACHE.clear()
        self.update_hw_telemetry()
        QMessageBox.information(
            self,
            "Caché de Audio Purgada",
            f"Se eliminaron {removed} segmentos de audio en caché correctamente."
        )

    def on_library_load_text_requested(self, text: str, title: str = ""):
        if hasattr(self, "tab_quick"):
            self.tab_quick.text_edit.setPlainText(text)
            if title and hasattr(self.tab_quick, "lbl_status"):
                self.tab_quick.lbl_status.setText(f"[ CARGADO DESDE BIBLIOTECA ] {title[:45]}")
            self.tabs.setCurrentIndex(0)

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

    def render_batch_table(self):
        self.batch_table.setRowCount(0)
        for idx, item in enumerate(self.batch_files):
            item["row"] = idx
            self.batch_table.insertRow(idx)
            src = item["path"]
            disp_name = src if src.startswith(("http://", "https://")) else Path(src).name
            self.batch_table.setItem(idx, 0, QTableWidgetItem(disp_name))
            self.batch_table.setItem(idx, 1, QTableWidgetItem(item.get("voice_label", self.voice_combo.currentText())))
            self.batch_table.setItem(idx, 2, QTableWidgetItem(item.get("status", "Pendiente")))

    def remove_selected_file(self):
        row = self.batch_table.currentRow()
        if 0 <= row < len(self.batch_files):
            self.batch_files.pop(row)
            self.render_batch_table()

    def move_selected_file_up(self):
        row = self.batch_table.currentRow()
        if 0 < row < len(self.batch_files):
            self.batch_files[row - 1], self.batch_files[row] = self.batch_files[row], self.batch_files[row - 1]
            self.render_batch_table()
            self.batch_table.selectRow(row - 1)

    def move_selected_file_down(self):
        row = self.batch_table.currentRow()
        if 0 <= row < len(self.batch_files) - 1:
            self.batch_files[row + 1], self.batch_files[row] = self.batch_files[row], self.batch_files[row + 1]
            self.render_batch_table()
            self.batch_table.selectRow(row + 1)

    def open_url_ingest_dialog(self):
        dlg = UrlIngestDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.extracted_text:
                # Guardar artículo extraído como archivo .txt listo para el lote
                from src.core.text_clean import make_filename_slug
                slug = make_filename_slug(dlg.extracted_title or "articulo_web")
                ingest_dir = BIBLIOTECA_DIR / "_ingesta_web"
                ingest_dir.mkdir(parents=True, exist_ok=True)
                out_txt = ingest_dir / f"{slug}.txt"
                out_txt.write_text(f"# {dlg.extracted_title}\n\n{dlg.extracted_text}", encoding="utf-8")
                self.add_file_to_batch(str(out_txt))
            elif dlg.extracted_url:
                self.add_file_to_batch(dlg.extracted_url)

    def show_distribution_dialog(self, platform: str):
        folder = Path(self.last_results[-1].document_folder) if self.last_results else BIBLIOTECA_DIR
        seo_path = folder / "youtube_spotify_seo.txt"
        rss_path = folder / "podcast_rss.xml"
        extra_info = ""
        if seo_path.exists():
            extra_info += f"\n• Descripción SEO y Timestamps: {seo_path.name}"
        if rss_path.exists():
            extra_info += f"\n• Feed Podcast RSS 2.0: {rss_path.name}"

        QMessageBox.information(
            self,
            f"Distribución a {platform}",
            f"Listo para publicar en {platform}.\n\n"
            f"Los audios cumplen con el estándar EBU R128 (-16 LUFS), Masterización DSP (-1.0 dBTP) y los videos están codificados en H.264/AAC con subtítulos karaoke.{extra_info}\n\n"
            f"Carpeta de entrega: {folder}"
        )
        if seo_path.exists():
            os.startfile(str(seo_path))

    def get_effective_orientation(self) -> str:
        if self.orientation_mode != "auto":
            return self.orientation_mode
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

        # 5. Actualizar pestaña de manual
        if hasattr(self, 'tab_manual') and hasattr(self.tab_manual, 'set_orientation'):
            self.tab_manual.set_orientation(eff)

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
        self.batch_group = QGroupBox("Archivos e Ingesta Inteligente (PDF / EPUB / TXT / OCR Imágenes / Web URL)")
        batch_lay = QVBoxLayout(self.batch_group)
        batch_lay.setContentsMargins(10, 8, 10, 8)
        batch_lay.setSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(5)
        add_files_btn = QPushButton("[ + ] Archivos / OCR...")
        add_files_btn.setObjectName("actionButton")
        add_files_btn.clicked.connect(self.select_files)
        btn_row.addWidget(add_files_btn)

        add_url_btn = QPushButton("[ ↗ ] Extraer URL Web")
        add_url_btn.setObjectName("secondaryActionButton")
        add_url_btn.setToolTip("Extraer artículo limpio desde una URL web y añadirlo a la cola")
        add_url_btn.clicked.connect(self.open_url_ingest_dialog)
        btn_row.addWidget(add_url_btn)

        up_btn = QPushButton("[ ↑ ]")
        up_btn.setObjectName("secondaryActionButton")
        up_btn.setToolTip("Subir prioridad en la cola")
        up_btn.clicked.connect(self.move_selected_file_up)
        btn_row.addWidget(up_btn)

        down_btn = QPushButton("[ ↓ ]")
        down_btn.setObjectName("secondaryActionButton")
        down_btn.setToolTip("Bajar prioridad en la cola")
        down_btn.clicked.connect(self.move_selected_file_down)
        btn_row.addWidget(down_btn)

        remove_btn = QPushButton("[ − ] Quitar")
        remove_btn.setObjectName("secondaryActionButton")
        remove_btn.clicked.connect(self.remove_selected_file)
        btn_row.addWidget(remove_btn)

        clear_btn = QPushButton("[ × ] Limpiar")
        clear_btn.setObjectName("secondaryActionButton")
        clear_btn.clicked.connect(self.clear_batch)
        btn_row.addWidget(clear_btn)

        btn_row.addStretch()

        self.chk_clean_editorial = QCheckBox("Limpieza Editorial")
        self.chk_clean_editorial.setChecked(True)
        self.chk_clean_editorial.setToolTip("Elimina numeración de páginas, cabeceras repetidas, notas al pie [1] y ruido académico")
        btn_row.addWidget(self.chk_clean_editorial)

        batch_lay.addLayout(btn_row)

        self.batch_table = QTableWidget()
        self.batch_table.setColumnCount(3)
        self.batch_table.setHorizontalHeaderLabels(["Archivo / Fuente de Origen", "Voz Asignada", "Estado"])
        self.batch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.batch_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.batch_table.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; background: transparent; }")
        batch_lay.addWidget(self.batch_table)

        # =========================================================================
        # SECCIÓN 2: PORTADA Y CUÑAS INTERSTICIALES (extra_group)
        # =========================================================================
        self.extra_group = QGroupBox("Portada Editorial IA, Trailer 90s y Cuñas Intersticiales")
        extra_lay = QVBoxLayout(self.extra_group)
        extra_lay.setContentsMargins(10, 8, 10, 8)
        extra_lay.setSpacing(6)

        cover_row = QHBoxLayout()
        cover_row.addWidget(QLabel("Portada:"))
        self.cover_edit = QLineEdit()
        self.cover_edit.setPlaceholderText("Ruta a portada (.png, .jpg) o vacía para Auto-Portada IA 1024x1024...")
        btn_cover = QPushButton("Examinar...")
        btn_cover.setObjectName("secondaryActionButton")
        btn_cover.clicked.connect(self.select_cover_image)
        self.chk_auto_cover_ai = QCheckBox("Portada IA 1024x1024")
        self.chk_auto_cover_ai.setChecked(True)
        self.chk_auto_cover_ai.setToolTip("Genera automáticamente una portada artística de 1024x1024 si no se especifica archivo")
        self.chk_generate_trailer = QCheckBox("Trailer 90s")
        self.chk_generate_trailer.setChecked(True)
        self.chk_generate_trailer.setToolTip("Genera un Audio-Trailer dramático (trailer_sinopsis.mp3) con voz de locutor")
        cover_row.addWidget(self.cover_edit, stretch=1)
        cover_row.addWidget(btn_cover)
        cover_row.addWidget(self.chk_auto_cover_ai)
        cover_row.addWidget(self.chk_generate_trailer)
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
        self.table_cunas.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; background: transparent; }")
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
        self.voice_group = QGroupBox("Voces Neurales, Clonación Biométrica y Auto-Casting Multi-Voz")
        voice_lay = QVBoxLayout(self.voice_group)
        voice_lay.setContentsMargins(10, 8, 10, 8)
        voice_lay.setSpacing(6)

        v_main_row = QHBoxLayout()
        v_main_row.addWidget(QLabel("Voz Principal (Narrador):"))
        self.voice_combo = QComboBox()
        for k, v in self.voices_dict.items():
            tag = "24kHz Studio" if v.engine in ("kokoro", "cloned") else f"{v.sample_rate // 1000}kHz"
            self.voice_combo.addItem(f"{v.name} [{tag}]", k)

        default_pref = "kokoro-ef_dora" if "kokoro-ef_dora" in self.voices_dict else "es_MX-claude-high"
        default_idx = self.voice_combo.findData(default_pref)
        if default_idx >= 0:
            self.voice_combo.setCurrentIndex(default_idx)
        v_main_row.addWidget(self.voice_combo, stretch=1)

        btn_clone_gen = QPushButton("[ ★ ] Clonar Voz...")
        btn_clone_gen.setObjectName("secondaryActionButton")
        btn_clone_gen.clicked.connect(self.open_voice_cloner_dialog)
        v_main_row.addWidget(btn_clone_gen)
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
        self.voice_pool_table.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; background: transparent; }")
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

        self.toggle_ai_options(False)
        ai_lay.addWidget(self.ai_options_frame)

        # =========================================================================
        # SECCIÓN 5: FORMATOS DE SALIDA, ACÚSTICA Y VIDEO KARAOKE (out_group)
        # =========================================================================
        self.out_group = QGroupBox("Formatos Master, Acústica DSP, Soundscapes & Video Karaoke")
        out_main_lay = QVBoxLayout(self.out_group)
        out_main_lay.setContentsMargins(10, 6, 10, 6)
        out_main_lay.setSpacing(5)

        out_row1 = QHBoxLayout()
        out_row1.setSpacing(8)
        self.chk_mp3 = QCheckBox("MP3 (EBU R128)")
        self.chk_mp3.setChecked(True)
        self.chk_m4b = QCheckBox(".M4B (Capítulos)")
        self.chk_m4b.setChecked(True)
        self.chk_split_chapters = QCheckBox("Capítulos MP3")
        self.chk_split_chapters.setChecked(True)
        self.chk_video = QCheckBox("Video Karaoke MP4")
        self.chk_video.setChecked(True)
        self.chk_flac = QCheckBox("FLAC")
        self.chk_flac.setChecked(True)
        self.chk_dsp = QCheckBox("DSP Mastering")
        self.chk_dsp.setChecked(True)
        self.chk_sfx = QCheckBox("Foley SFX")
        self.chk_sfx.setChecked(True)
        self.chk_lex_emo = QCheckBox("Lexicon + Emoción")
        self.chk_lex_emo.setChecked(True)

        for chk in (
            self.chk_mp3,
            self.chk_m4b,
            self.chk_split_chapters,
            self.chk_video,
            self.chk_flac,
            self.chk_dsp,
            self.chk_sfx,
            self.chk_lex_emo,
        ):
            out_row1.addWidget(chk)
        out_main_lay.addLayout(out_row1)

        out_row2 = QHBoxLayout()
        out_row2.setSpacing(6)
        out_row2.addWidget(QLabel("Ambiente:"))
        self.combo_gen_soundscape = QComboBox()
        for k, label_sc in SOUNDSCAPE_PRESETS.items():
            self.combo_gen_soundscape.addItem(label_sc, k)
        out_row2.addWidget(self.combo_gen_soundscape)

        self.btn_custom_bgm = QPushButton("[...] BGM")
        self.btn_custom_bgm.setObjectName("secondaryActionButton")
        self.btn_custom_bgm.setToolTip("Seleccionar pista musical personalizada (.mp3/.wav) con Auto-Ducking")
        self.btn_custom_bgm.clicked.connect(self.select_custom_bgm)
        out_row2.addWidget(self.btn_custom_bgm)

        out_row2.addWidget(QLabel("Video:"))
        self.combo_video_bg = QComboBox()
        for k, desc_bg in VIDEO_BACKGROUNDS.items():
            self.combo_video_bg.addItem(desc_bg, k)
        idx_bg = self.combo_video_bg.findData("audiogram")
        if idx_bg >= 0:
            self.combo_video_bg.setCurrentIndex(idx_bg)
        out_row2.addWidget(self.combo_video_bg)

        out_row2.addWidget(QLabel("Ratio:"))
        self.combo_video_aspect = QComboBox()
        for k, meta_ar in ASPECT_RATIOS.items():
            self.combo_video_aspect.addItem(meta_ar[2], k)
        out_row2.addWidget(self.combo_video_aspect)

        out_row2.addWidget(QLabel("Subtítulos:"))
        self.combo_sub_theme = QComboBox()
        for k, meta_th in SUBTITLE_THEMES.items():
            self.combo_sub_theme.addItem(meta_th["name"], k)
        out_row2.addWidget(self.combo_sub_theme)
        out_main_lay.addLayout(out_row2)

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

        self.btn_wifi_res = QPushButton("[ ↗ ] Streaming WiFi QR")
        self.btn_wifi_res.setObjectName("secondaryActionButton")
        self.btn_wifi_res.clicked.connect(self.open_mobile_streaming_dialog)

        self.btn_upload_yt = QPushButton("[ ↗ ] Kit SEO YouTube")
        self.btn_upload_yt.setObjectName("secondaryActionButton")
        self.btn_upload_yt.clicked.connect(lambda: self.show_distribution_dialog("YouTube"))

        self.btn_upload_sp = QPushButton("[ ↗ ] Kit Spotify & RSS")
        self.btn_upload_sp.setObjectName("secondaryActionButton")
        self.btn_upload_sp.clicked.connect(lambda: self.show_distribution_dialog("Spotify"))

        res_btns.addWidget(self.btn_open_last_folder)
        res_btns.addWidget(self.btn_go_library)
        res_btns.addWidget(self.btn_wifi_res)
        res_btns.addWidget(self.btn_upload_yt)
        res_btns.addWidget(self.btn_upload_sp)
        res_lay.addLayout(res_btns)
        bottom_box_lay.addWidget(self.res_card)

        # Barra de Controles de Cola (Iniciar / Pausar / Cancelar)
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self.start_btn = QPushButton("[ ► ] Iniciar Generación en Lote")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.clicked.connect(self.start_batch_processing)
        ctrl_row.addWidget(self.start_btn, stretch=3)

        self.pause_btn = QPushButton("[ ❚❚ ] Pausar Cola")
        self.pause_btn.setObjectName("secondaryActionButton")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self.toggle_pause_batch)
        ctrl_row.addWidget(self.pause_btn, stretch=1)

        self.cancel_btn = QPushButton("[ ■ ] Cancelar")
        self.cancel_btn.setObjectName("secondaryActionButton")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_batch_processing)
        ctrl_row.addWidget(self.cancel_btn, stretch=1)

        bottom_box_lay.addLayout(ctrl_row)

        # Aplicar distribución inicial
        self.update_generator_tab_layout(self.get_effective_orientation())

    def select_custom_bgm(self):
        bgm, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Pista Musical de Fondo (Auto-Ducking) — Cancela para desactivar BGM",
            "",
            "Audio (*.mp3 *.wav *.flac *.ogg)"
        )
        if bgm:
            self.custom_bgm_path = bgm
            self.btn_custom_bgm.setText(f"[✓] {Path(bgm).stem[:12]}")
            self.btn_custom_bgm.setToolTip(f"BGM Personalizado activo: {bgm}")
        else:
            self.custom_bgm_path = None
            self.btn_custom_bgm.setText("[...] BGM")
            self.btn_custom_bgm.setToolTip("Seleccionar pista musical personalizada (.mp3/.wav) con Auto-Ducking")

    def toggle_pause_batch(self):
        if not self.worker or not self.worker.isRunning():
            return
        if self.worker.is_paused():
            self.worker.set_paused(False)
            self.pause_btn.setText("[ ❚❚ ] Pausar Cola")
            self.lbl_stage.setText("Fase: Reanudando procesamiento...")
        else:
            self.worker.set_paused(True)
            self.pause_btn.setText("[ ► ] Reanudar Cola")
            self.lbl_stage.setText("Fase: Cola en pausa (esperando reanudación)...")

    def cancel_batch_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.lbl_stage.setText("Fase: Cancelando lote tras el segmento actual...")
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)

    def update_generator_tab_layout(self, mode: str):
        """Ajusta la distribución del Generador sin espacios vacíos y con scroll invisible en tablas."""
        for w in (self.batch_group, self.extra_group, self.voice_group, self.ai_group, self.out_group, self.bottom_control_box):
            w.setParent(self.tab_generator)

        def clear_layout_items(lay):
            while lay.count():
                item = lay.takeAt(0)
                if item.layout():
                    clear_layout_items(item.layout())

        clear_layout_items(self.gen_layout)

        # Configurar scrollbars invisibles en todas las tablas
        for tbl in (self.batch_table, self.table_cunas, self.voice_pool_table):
            tbl.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; background: transparent; }")
            tbl.horizontalScrollBar().setStyleSheet("QScrollBar:horizontal { height: 0px; background: transparent; }")

        if mode == "vertical":
            self.gen_layout.setContentsMargins(10, 6, 10, 6)
            self.gen_layout.setSpacing(6)

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
            self.gen_layout.setContentsMargins(10, 8, 10, 8)
            self.gen_layout.setSpacing(8)

            self.batch_table.setMinimumHeight(110)
            self.batch_table.setMaximumHeight(16777215)
            self.table_cunas.setMinimumHeight(100)
            self.table_cunas.setMaximumHeight(16777215)
            self.voice_pool_table.setMinimumHeight(110)
            self.voice_pool_table.setMaximumHeight(16777215)

            cols_lay = QHBoxLayout()
            cols_lay.setSpacing(12)

            left_col = QVBoxLayout()
            left_col.setContentsMargins(0, 0, 0, 0)
            left_col.setSpacing(8)
            left_col.addWidget(self.batch_group, stretch=1)
            left_col.addWidget(self.extra_group, stretch=1)
            cols_lay.addLayout(left_col, stretch=50)

            right_col = QVBoxLayout()
            right_col.setContentsMargins(0, 0, 0, 0)
            right_col.setSpacing(8)
            right_col.addWidget(self.voice_group, stretch=1)
            right_col.addWidget(self.ai_group, stretch=0)
            right_col.addWidget(self.out_group, stretch=0)
            cols_lay.addLayout(right_col, stretch=50)

            self.gen_layout.addLayout(cols_lay, stretch=1)
            self.gen_layout.addWidget(self.bottom_control_box, stretch=0)

    def toggle_ai_options(self, checked: bool):
        self.ai_options_frame.setEnabled(True)
        self.combo_style.setEnabled(True)
        self.btn_manage_prompts.setEnabled(True)
        self.combo_ai_mode.setEnabled(checked)
        self.combo_persona.setEnabled(checked)
        self.combo_tense.setEnabled(checked)

    def refresh_styles_combo(self):
        curr = self.combo_style.currentData() if self.combo_style.count() > 0 else "cuento"
        self.combo_style.clear()
        styles = self.prompt_library.list_styles()
        for style in styles:
            self.combo_style.addItem(style.name, style.id)
        idx = self.combo_style.findData(curr)
        if idx >= 0:
            self.combo_style.setCurrentIndex(idx)

        # Actualizar también los selectores de estilo de la tabla de cuñas
        if hasattr(self, "table_cunas"):
            for r in range(self.table_cunas.rowCount()):
                st_combo = self.table_cunas.cellWidget(r, 3)
                if isinstance(st_combo, QComboBox):
                    c_st = st_combo.currentData() or "locutor_radio"
                    st_combo.clear()
                    for style in styles:
                        st_combo.addItem(style.name, style.id)
                    idx_s = st_combo.findData(c_st)
                    if idx_s >= 0:
                        st_combo.setCurrentIndex(idx_s)

    def open_prompt_manager(self):
        dlg = PromptManagerDialog(library=self.prompt_library, parent=self)
        dlg.prompts_updated.connect(self.refresh_styles_combo)
        dlg.exec()

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar documentos o imágenes OCR para audiolibro",
            "",
            "Todos los Soportados (*.txt *.pdf *.epub *.md *.png *.jpg *.jpeg *.webp *.bmp);;"
            "Documentos (*.txt *.pdf *.epub *.md);;"
            "Imágenes OCR (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        for f in files:
            self.add_file_to_batch(f)

    def add_file_to_batch(self, file_path: str):
        p = Path(file_path) if not file_path.startswith(("http://", "https://")) else None
        norm_path = str(p) if p else file_path
        if any(b["path"] == norm_path for b in self.batch_files):
            return

        row = self.batch_table.rowCount()
        self.batch_table.insertRow(row)
        disp_name = p.name if p else norm_path
        voice_label = self.voice_combo.currentText()
        self.batch_table.setItem(row, 0, QTableWidgetItem(disp_name))
        self.batch_table.setItem(row, 1, QTableWidgetItem(voice_label))
        self.batch_table.setItem(row, 2, QTableWidgetItem("Pendiente"))

        self.batch_files.append({
            "path": norm_path,
            "row": row,
            "voice_label": voice_label,
            "status": "Pendiente",
        })

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

        txt_item = QTableWidgetItem(text)
        self.table_cunas.setItem(row, 0, txt_item)

        pos_combo = QComboBox()
        pos_combo.addItem("Entre Capítulos", "between_chapters")
        pos_combo.addItem("Entre Párrafos", "between_paragraphs")
        pos_combo.addItem("Al Inicio", "start")
        pos_combo.addItem("Al Final", "end")
        idx_p = pos_combo.findData(position)
        if idx_p >= 0:
            pos_combo.setCurrentIndex(idx_p)
        self.table_cunas.setCellWidget(row, 1, pos_combo)

        v_combo = QComboBox()
        for k, v in self.voices_dict.items():
            tag = "24k" if v.engine in ("kokoro", "cloned") else f"{v.sample_rate // 1000}k"
            v_combo.addItem(f"{v.name} [{tag}]", k)
        idx_v = v_combo.findData(voice_key)
        if idx_v >= 0:
            v_combo.setCurrentIndex(idx_v)
        self.table_cunas.setCellWidget(row, 2, v_combo)

        st_combo = QComboBox()
        for st in self.prompt_library.list_styles():
            st_combo.addItem(st.name, st.id)
        idx_s = st_combo.findData(style)
        if idx_s >= 0:
            st_combo.setCurrentIndex(idx_s)
        self.table_cunas.setCellWidget(row, 3, st_combo)

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

            chk = QCheckBox()
            if profile.engine in ("kokoro", "cloned") or key in ("es_ES-sharvard-medium", "es_MX-claude-high"):
                chk.setChecked(True)
            chk_widget = QWidget()
            chk_lay = QHBoxLayout(chk_widget)
            chk_lay.addWidget(chk)
            chk_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_lay.setContentsMargins(0, 0, 0, 0)
            self.voice_pool_table.setCellWidget(row, 0, chk_widget)

            name_item = QTableWidgetItem(profile.name)
            name_item.setData(Qt.ItemDataRole.UserRole, key)
            self.voice_pool_table.setItem(row, 1, name_item)

            if profile.engine == "cloned":
                engine_str = "Clon Biométrico (24kHz)"
            elif profile.engine == "kokoro":
                engine_str = "Kokoro (24kHz Studio)"
            else:
                engine_str = f"Piper ({profile.sample_rate // 1000}kHz)"
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
                chk.setChecked(prof is not None and prof.engine in ("kokoro", "cloned"))

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
            QMessageBox.warning(self, "Lista Vacía", "Por favor agrega al menos un archivo o URL para procesar.")
            return

        if not (self.chk_mp3.isChecked() or self.chk_m4b.isChecked() or self.chk_video.isChecked() or self.chk_flac.isChecked()):
            QMessageBox.warning(self, "Sin formato", "Selecciona al menos un formato de salida.")
            return

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

                st_combo = self.table_cunas.cellWidget(row, 3) if False else self.table_cunas.cellWidget(r, 3)
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

        selected_pool = self.get_selected_voice_pool() if self.chk_autocast.isChecked() else []
        if not selected_pool and self.chk_autocast.isChecked():
            selected_pool = [k for k in self.voices_dict.keys() if k != self.voice_combo.currentData()][:4]

        sec_voice = selected_pool[0] if selected_pool else None

        configs: list[JobConfig] = []
        for item in self.batch_files:
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
                generate_cover_ai=self.chk_auto_cover_ai.isChecked(),
                generate_audio=self.chk_mp3.isChecked() or self.chk_m4b.isChecked(),
                export_m4b=self.chk_m4b.isChecked(),
                split_chapters=self.chk_split_chapters.isChecked(),
                generate_trailer=self.chk_generate_trailer.isChecked(),
                generate_video=self.chk_video.isChecked(),
                save_flac_master=self.chk_flac.isChecked(),
                clean_editorial=self.chk_clean_editorial.isChecked(),
                apply_lexicon=self.chk_lex_emo.isChecked(),
                emotional_modulation=self.chk_lex_emo.isChecked(),
                auto_sfx=self.chk_sfx.isChecked(),
                dsp_mastering=self.chk_dsp.isChecked(),
                soundscape_preset=self.combo_gen_soundscape.currentData() or "none",
                custom_bgm_path=self.custom_bgm_path,
                video_background=self.combo_video_bg.currentData() or "black",
                video_aspect_ratio=self.combo_video_aspect.currentData() or "16:9",
                subtitle_theme=self.combo_sub_theme.currentData() or "cyan_ejecutivo",
                generate_seo_package=True,
                narration=narration_cfg,
                interstitials=interstitials,
            )
            configs.append(cfg)

        self.start_btn.setEnabled(False)
        self.start_btn.setText("Procesando lote en segundo plano...")
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("[ ❚❚ ] Pausar Cola")
        self.cancel_btn.setEnabled(True)
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
        if 0 <= idx < len(self.batch_files):
            self.batch_files[idx]["status"] = "Procesando..."
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
        status_str = f"Completado ({meta.duration_seconds}s)"
        if 0 <= idx < len(self.batch_files):
            self.batch_files[idx]["status"] = status_str
        self.batch_table.setItem(idx, 2, QTableWidgetItem(status_str))
        self.update_hw_telemetry()

    def on_batch_finished(self, results: list[JobMetadata]):
        self.timer.stop()
        self.last_results = results
        self.progress_bar.setValue(100)
        self.start_btn.setEnabled(True)
        self.start_btn.setText("[ ⟳ ] Procesar de Nuevo")
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("[ ❚❚ ] Pausar Cola")
        self.cancel_btn.setEnabled(False)

        elapsed = time.perf_counter() - self.start_timestamp if self.start_timestamp else 0
        self.val_elapsed.setText(str(timedelta(seconds=int(elapsed))))
        self.val_eta.setText("00:00:00")
        self.lbl_stage.setText("Lote completado con éxito.")
        self.lbl_active_utt.setText(f"Procesados {len(results)} libro(s) en {elapsed:.1f}s.")

        self.res_card.setVisible(True)
        self.res_summary.setText(f"Se han generado {len(results)} audiolibro(s) con M4B, Capítulos, SEO y RSS en sus carpetas.")

        self.tab_library.refresh_library()
        self.update_hw_telemetry()

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
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
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

        manual_action = QAction("Manual de Uso Completo", menu)
        manual_action.triggered.connect(self.show_manual_tab)
        menu.addAction(manual_action)

        menu.addSeparator()

        wifi_action = QAction("Streaming Móvil WiFi & Código QR", menu)
        wifi_action.triggered.connect(self.show_wifi_dialog)
        menu.addAction(wifi_action)

        lexicon_action = QAction("Diccionario Fonético (Lexicon)", menu)
        lexicon_action.triggered.connect(self.show_lexicon_dialog)
        menu.addAction(lexicon_action)

        cloner_action = QAction("Clonador Biométrico de Voz", menu)
        cloner_action.triggered.connect(self.show_cloner_dialog)
        menu.addAction(cloner_action)

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

    def show_manual_tab(self):
        self.show_main_window()
        if self.main_window:
            self.main_window.tabs.setCurrentIndex(4)

    def show_wifi_dialog(self):
        self.show_main_window()
        if self.main_window:
            self.main_window.open_mobile_streaming_dialog()

    def show_lexicon_dialog(self):
        self.show_main_window()
        if self.main_window:
            self.main_window.open_lexicon_dialog()

    def show_cloner_dialog(self):
        self.show_main_window()
        if self.main_window:
            self.main_window.open_voice_cloner_dialog()

    def open_file_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            None,
            "Seleccionar documentos o imágenes OCR para audiolibro",
            "",
            "Todos los Soportados (*.txt *.pdf *.epub *.md *.png *.jpg *.jpeg *.webp *.bmp);;"
            "Documentos (*.txt *.pdf *.epub *.md);;"
            "Imágenes OCR (*.png *.jpg *.jpeg *.webp *.bmp)"
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
