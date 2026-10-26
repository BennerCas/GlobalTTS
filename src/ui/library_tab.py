"""Pestaña de Biblioteca, Catálogo de Audiolibros e Historial Infinito para GlobalTTS.

Diseño Ejecutivo Obsidian & Titanium:
- Dos vistas integradas:
  1. Catálogo de Audiolibros Completos (.MP3, .M4B, .FLAC, Capítulos), Trailers 90s y Videos Karaoke MP4.
  2. Historial Infinito de Lecturas Rápidas generadas desde la pestaña de Lector Rápido.
- Generación instantánea de Portadas IA 1024x1024, Audio-Trailers promocionales, exportación de subtítulos
  (.SRT/.VTT/.LRC/.ASS), Paquete SEO YouTube/Spotify/Podcast RSS y Streaming Móvil WiFi (QR).
- Firma institucional 'HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®'.
"""
from __future__ import annotations

import json
import os
import webbrowser
from datetime import timedelta
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.ai.cover_generator import generate_audiobook_cover
from src.core.history import HistoryManager
from src.core.job import AudiobookPipeline, JobConfig
from src.ui.studio_dialogs import MobileStreamingDialog

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BIBLIOTECA_DIR = PROJECT_ROOT / "biblioteca"


class LibraryTab(QWidget):
    """Pestaña de exploración de la biblioteca, audiolibros e historial infinito."""

    load_text_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self.history_manager = HistoryManager()
        self.books: list[dict] = []
        self.history_items: list[dict] = []
        self.selected_book_data: Optional[dict] = None
        self.selected_history_data: Optional[dict] = None

        self.init_ui()
        self.setup_player_events()
        self.refresh_library()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Barra superior con buscador, Streaming Móvil QR y accesos de carpeta
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("[ ⌕ ] Buscar por título, autor o texto...")
        self.search_edit.textChanged.connect(self.filter_items)
        top_bar.addWidget(self.search_edit, stretch=1)

        refresh_btn = QPushButton("[ ⟳ ] Actualizar")
        refresh_btn.setObjectName("secondaryActionButton")
        refresh_btn.clicked.connect(self.refresh_library)
        top_bar.addWidget(refresh_btn)

        mobile_qr_btn = QPushButton("[ ↗ ] Streaming Móvil WiFi (QR)")
        mobile_qr_btn.setObjectName("actionButton")
        mobile_qr_btn.setToolTip("Levanta el servidor local WiFi y muestra el código QR para escuchar en tu teléfono")
        mobile_qr_btn.clicked.connect(self.open_mobile_streaming_qr)
        top_bar.addWidget(mobile_qr_btn)

        open_folder_btn = QPushButton("[ ↗ ] Abrir Carpeta Biblioteca")
        open_folder_btn.setObjectName("secondaryActionButton")
        open_folder_btn.clicked.connect(lambda: os.startfile(BIBLIOTECA_DIR) if BIBLIOTECA_DIR.exists() else None)
        top_bar.addWidget(open_folder_btn)

        main_layout.addLayout(top_bar)

        # Splitter central: Catálogo / Historial (izq) y Reproductor Ejecutivo (der)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.catalog_tabs = QTabWidget()

        # 1. Tabla de audiolibros
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["TÍTULO / OBRA", "DURACIÓN", "FECHA", "FORMATOS"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_book_selected)
        self.table.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; background: transparent; }")
        self.table.horizontalScrollBar().setStyleSheet("QScrollBar:horizontal { height: 0px; background: transparent; }")
        self.catalog_tabs.addTab(self.table, "AUDIOLIBROS Y VIDEOS")

        # 2. Tabla de historial infinito de lecturas rápidas
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["FECHA / HORA", "VOZ NEURAL", "DURACIÓN", "TEXTO INICIAL"])
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.itemSelectionChanged.connect(self.on_history_selected)
        self.history_table.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; background: transparent; }")
        self.history_table.horizontalScrollBar().setStyleSheet("QScrollBar:horizontal { height: 0px; background: transparent; }")
        self.catalog_tabs.addTab(self.history_table, "HISTORIAL DE LECTURAS RÁPIDAS")

        self.splitter.addWidget(self.catalog_tabs)

        # 2. Panel de Detalles y Reproductor Multimedia Ejecutivo
        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("cardFrame")
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setSpacing(10)
        detail_layout.setContentsMargins(12, 12, 12, 12)

        # Cabecera Ejecutiva: Portada Grande (280x280 izquierda) + Selección y Metadatos (derecha)
        self.header_card = QFrame()
        self.header_card.setObjectName("metricCard")
        header_card_lay = QHBoxLayout(self.header_card)
        header_card_lay.setContentsMargins(10, 10, 10, 10)
        header_card_lay.setSpacing(14)

        self.cover_label = QLabel("[ Sin Portada ]\n\n1:1 Master Art")
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setFixedSize(280, 280)
        self.cover_label.setStyleSheet("""
            QLabel {
                background-color: #070a10;
                border: 1px solid #1e2633;
                border-radius: 8px;
                color: #64748b;
                font-family: Consolas, monospace;
                font-size: 12px;
                font-weight: 600;
                line-height: 1.5;
            }
        """)
        header_card_lay.addWidget(self.cover_label)

        self.meta_panel = QWidget()
        meta_panel_lay = QVBoxLayout(self.meta_panel)
        meta_panel_lay.setContentsMargins(0, 0, 0, 0)
        meta_panel_lay.setSpacing(6)

        self.lbl_book_title = QLabel("Selecciona un elemento para reproducir")
        self.lbl_book_title.setObjectName("titleLabel")
        self.lbl_book_title.setWordWrap(True)
        self.lbl_book_title.setStyleSheet("font-size: 17px; font-weight: 700; color: #f8fafc;")
        meta_panel_lay.addWidget(self.lbl_book_title)

        self.lbl_book_meta = QLabel("Metadatos técnicos: Selecciona un audiolibro o lectura rápida.")
        self.lbl_book_meta.setObjectName("subtitleLabel")
        self.lbl_book_meta.setWordWrap(True)
        self.lbl_book_meta.setStyleSheet("color: #94a3b8; font-size: 11px; line-height: 1.4;")
        meta_panel_lay.addWidget(self.lbl_book_meta)

        # Fila de Badges Técnicos Industriales
        self.badges_widget = QWidget()
        badges_lay = QHBoxLayout(self.badges_widget)
        badges_lay.setContentsMargins(0, 2, 0, 2)
        badges_lay.setSpacing(6)

        self.badge_ebu = QLabel("DSP -1.0 dBTP")
        self.badge_ebu.setStyleSheet("background-color: #0c1523; border: 1px solid #1e3a5f; color: #38bdf8; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: Consolas, monospace;")
        self.badge_mp3 = QLabel("MP3 256K")
        self.badge_mp3.setStyleSheet("background-color: #0c1523; border: 1px solid #1e3a5f; color: #22c55e; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: Consolas, monospace;")
        self.badge_m4b = QLabel("M4B CAPÍTULOS")
        self.badge_m4b.setStyleSheet("background-color: #0c1523; border: 1px solid #1e3a5f; color: #10b981; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: Consolas, monospace;")
        self.badge_flac = QLabel("FLAC 24-BIT")
        self.badge_flac.setStyleSheet("background-color: #0c1523; border: 1px solid #1e3a5f; color: #a855f7; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: Consolas, monospace;")
        self.badge_mp4 = QLabel("KARAOKE MP4")
        self.badge_mp4.setStyleSheet("background-color: #0c1523; border: 1px solid #1e3a5f; color: #f59e0b; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: Consolas, monospace;")
        self.badge_engine = QLabel("KOKORO & PIPER")
        self.badge_engine.setStyleSheet("background-color: #0c1523; border: 1px solid #1e3a5f; color: #60a5fa; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; font-family: Consolas, monospace;")

        badges_lay.addWidget(self.badge_ebu)
        badges_lay.addWidget(self.badge_mp3)
        badges_lay.addWidget(self.badge_m4b)
        badges_lay.addWidget(self.badge_flac)
        badges_lay.addWidget(self.badge_mp4)
        badges_lay.addWidget(self.badge_engine)
        badges_lay.addStretch()
        meta_panel_lay.addWidget(self.badges_widget)

        # Ficha técnica de especificaciones del máster multimedia
        self.spec_card = QFrame()
        self.spec_card.setObjectName("metricCard")
        self.spec_card.setStyleSheet("background-color: #070b12; border: 1px solid #151d2a; border-radius: 6px; padding: 4px;")
        spec_lay = QVBoxLayout(self.spec_card)
        spec_lay.setContentsMargins(8, 6, 8, 6)
        spec_lay.setSpacing(3)
        lbl_spec_title = QLabel("ESPECIFICACIONES DEL MÁSTER MULTIMEDIA")
        lbl_spec_title.setObjectName("metricTitle")
        self.lbl_spec_details = QLabel(
            "• Cadena Acústica: HPF 80Hz + De-Esser + Compresor + Limitador -1.0 dBTP\n"
            "• Formatos: MP3 256k + M4B con Capítulos + Master FLAC + Subtítulos SRT/VTT/LRC\n"
            "• Video Karaoke: MP4 (16:9 / 9:16 Shorts / Audiograma Espectro)\n"
            "• Motor de Síntesis: Kokoro Studio Neural 24kHz, Voces Clonadas & Piper DirectML"
        )
        self.lbl_spec_details.setStyleSheet("color: #8b949e; font-size: 11px; line-height: 1.35;")
        spec_lay.addWidget(lbl_spec_title)
        spec_lay.addWidget(self.lbl_spec_details)
        meta_panel_lay.addWidget(self.spec_card)

        meta_panel_lay.addStretch()
        header_card_lay.addWidget(self.meta_panel, stretch=1)
        detail_layout.addWidget(self.header_card)

        # Vista de texto para lecturas rápidas
        self.text_preview = QTextEdit()
        self.text_preview.setReadOnly(True)
        self.text_preview.setPlaceholderText("Texto íntegro de la lectura rápida...")
        self.text_preview.setMinimumHeight(180)
        self.text_preview.setStyleSheet("""
            QTextEdit {
                background-color: #0b0f16;
                color: #cbd5e1;
                border: 1px solid #1e2633;
                border-radius: 6px;
                font-size: 12px;
                line-height: 1.4;
            }
            QScrollBar:vertical { width: 0px; background: transparent; }
            QScrollBar:horizontal { height: 0px; background: transparent; }
        """)
        self.text_preview.setVisible(False)
        detail_layout.addWidget(self.text_preview, stretch=1)

        # Caja de Reproducción Multimedia
        player_box = QFrame()
        player_box.setObjectName("metricCard")
        p_lay = QVBoxLayout(player_box)
        p_lay.setSpacing(8)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(8)
        self.lbl_cur_time = QLabel("00:00")
        self.lbl_cur_time.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; color: #38bdf8;")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        self.lbl_total_time = QLabel("00:00")
        self.lbl_total_time.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; color: #64748b;")
        slider_row.addWidget(self.lbl_cur_time)
        slider_row.addWidget(self.slider)
        slider_row.addWidget(self.lbl_total_time)
        p_lay.addLayout(slider_row)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)

        self.btn_play = QPushButton("[ ► ] Reproducir")
        self.btn_play.setObjectName("primaryButton")
        self.btn_play.clicked.connect(self.toggle_play)
        controls_row.addWidget(self.btn_play)

        self.btn_stop = QPushButton("[ ■ ] Detener")
        self.btn_stop.setObjectName("secondaryActionButton")
        self.btn_stop.clicked.connect(self.stop_playback)
        controls_row.addWidget(self.btn_stop)

        self.btn_play_trailer = QPushButton("[ ► ] Trailer 90s")
        self.btn_play_trailer.setObjectName("actionButton")
        self.btn_play_trailer.setToolTip("Escucha o genera el Audio-Trailer dramático de 90 segundos")
        self.btn_play_trailer.clicked.connect(self.play_or_generate_trailer)
        controls_row.addWidget(self.btn_play_trailer)

        lbl_vol = QLabel("[ Vol ]")
        lbl_vol.setStyleSheet("font-family: Consolas, monospace; font-size: 11px; color: #64748b;")
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.audio_output.setVolume(0.8)
        self.vol_slider.valueChanged.connect(lambda v: self.audio_output.setVolume(v / 100.0))
        controls_row.addWidget(lbl_vol)
        controls_row.addWidget(self.vol_slider)

        p_lay.addLayout(controls_row)
        detail_layout.addWidget(player_box)

        # Botones de Acción de Archivos y Utilidades
        actions_grid = QHBoxLayout()
        actions_grid.setSpacing(6)

        self.btn_open_video = QPushButton("[ ► ] Video Karaoke")
        self.btn_open_video.setObjectName("actionButton")
        self.btn_open_video.clicked.connect(self.open_video)

        self.btn_open_folder = QPushButton("[ ↗ ] Carpeta")
        self.btn_open_folder.setObjectName("secondaryActionButton")
        self.btn_open_folder.clicked.connect(self.open_current_folder)

        self.btn_change_cover = QPushButton("[ + ] Asignar Portada")
        self.btn_change_cover.setObjectName("secondaryActionButton")
        self.btn_change_cover.clicked.connect(self.change_cover_dialog)

        self.btn_gen_cover_ai = QPushButton("[ ★ ] Portada IA")
        self.btn_gen_cover_ai.setObjectName("actionButton")
        self.btn_gen_cover_ai.setToolTip("Genera una portada editorial 1024x1024 con IA local para esta obra")
        self.btn_gen_cover_ai.clicked.connect(self.generate_cover_ai_for_selected)

        self.btn_open_subs = QPushButton("[ ⤓ ] Subtítulos / SEO")
        self.btn_open_subs.setObjectName("secondaryActionButton")
        self.btn_open_subs.setToolTip("Inspecciona los subtítulos (.SRT/.VTT/.LRC) y el paquete SEO/RSS")
        self.btn_open_subs.clicked.connect(self.inspect_subtitles_and_seo)

        self.btn_load_to_reader = QPushButton("[ ↗ ] Cargar en Lector Rápido")
        self.btn_load_to_reader.setObjectName("actionButton")
        self.btn_load_to_reader.clicked.connect(self.load_selected_to_reader)
        self.btn_load_to_reader.setVisible(False)

        self.btn_delete_history = QPushButton("[ × ] Eliminar")
        self.btn_delete_history.setObjectName("secondaryActionButton")
        self.btn_delete_history.clicked.connect(self.delete_current_history_entry)
        self.btn_delete_history.setVisible(False)

        actions_grid.addWidget(self.btn_open_video)
        actions_grid.addWidget(self.btn_open_folder)
        actions_grid.addWidget(self.btn_change_cover)
        actions_grid.addWidget(self.btn_gen_cover_ai)
        actions_grid.addWidget(self.btn_open_subs)
        actions_grid.addWidget(self.btn_load_to_reader)
        actions_grid.addWidget(self.btn_delete_history)
        detail_layout.addLayout(actions_grid)

        # Módulo de Distribución Ejecutiva
        self.dist_group = QGroupBox("Distribución, YouTube Timestamps y Podcast RSS")
        dist_lay = QHBoxLayout(self.dist_group)
        dist_lay.setContentsMargins(10, 8, 10, 8)
        dist_lay.setSpacing(8)

        self.btn_youtube = QPushButton("[ ↗ ] Publicar en YouTube Studio (SEO + Capítulos)")
        self.btn_youtube.setObjectName("brandButton")
        self.btn_youtube.clicked.connect(self.open_youtube_dialog)

        self.btn_spotify = QPushButton("[ ↗ ] Publicar en Spotify / Podcast RSS")
        self.btn_spotify.setObjectName("brandButton")
        self.btn_spotify.clicked.connect(self.open_spotify_dialog)

        dist_lay.addWidget(self.btn_youtube)
        dist_lay.addWidget(self.btn_spotify)
        detail_layout.addWidget(self.dist_group)

        self.splitter.addWidget(self.detail_panel)
        main_layout.addWidget(self.splitter)

        self.current_orientation = "vertical"
        self.set_orientation("vertical")

    def open_mobile_streaming_qr(self):
        dlg = MobileStreamingDialog(self, biblioteca_dir=BIBLIOTECA_DIR)
        dlg.exec()

    def set_orientation(self, mode: str):
        """Ajusta la orientación del reproductor y catálogo según la pantalla sin barras de scroll."""
        self.current_orientation = mode
        if mode == "vertical":
            self.splitter.setOrientation(Qt.Orientation.Vertical)
            self.splitter.setSizes([950, 600])
            self.text_preview.setMaximumHeight(220)
        else:
            self.splitter.setOrientation(Qt.Orientation.Horizontal)
            self.splitter.setSizes([1000, 850])
            self.text_preview.setMaximumHeight(16777215)

    def setup_player_events(self):
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)

    def refresh_library(self):
        self.books = []
        if BIBLIOTECA_DIR.exists():
            for item in sorted(BIBLIOTECA_DIR.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
                if item.is_dir() and item.name != "historial_lecturas":
                    meta_files = list(item.glob("*_metadata.json")) + list(item.glob("metadata.json"))
                    meta = {}
                    if meta_files:
                        try:
                            with open(meta_files[0], "r", encoding="utf-8") as f:
                                meta = json.load(f)
                        except Exception:
                            pass

                    mp3_files = [p for p in item.glob("*.mp3") if p.name != "trailer_sinopsis.mp3"]
                    m4b_files = list(item.glob("*.m4b"))
                    trailer_file = item / "trailer_sinopsis.mp3"
                    mp4_files = list(item.glob("*.mp4"))
                    flac_files = list(item.glob("*.flac")) + list(item.glob("*.wav"))
                    cover_files = list(item.glob("cover.*"))
                    srt_files = list(item.glob("*.srt"))

                    self.books.append({
                        "folder": item,
                        "title": meta.get("output_name") or meta.get("title") or item.name,
                        "duration": meta.get("duration_seconds", 0),
                        "created": meta.get("created_at", ""),
                        "mp3": mp3_files[0] if mp3_files else None,
                        "m4b": m4b_files[0] if m4b_files else None,
                        "trailer": trailer_file if trailer_file.exists() else None,
                        "mp4": mp4_files[0] if mp4_files else None,
                        "master": flac_files[0] if flac_files else None,
                        "cover": cover_files[0] if cover_files else None,
                        "srt": srt_files[0] if srt_files else None,
                        "meta": meta,
                    })

        self.history_items = self.history_manager.list_entries()
        self.filter_items(self.search_edit.text())

    def filter_items(self, query: str = ""):
        q = query.lower().strip()

        self.table.setRowCount(0)
        for b in self.books:
            title = b["title"]
            if q and q not in title.lower():
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)

            item_title = QTableWidgetItem(title)
            item_title.setData(Qt.ItemDataRole.UserRole, b)
            self.table.setItem(row, 0, item_title)

            dur_str = str(timedelta(seconds=int(b["duration"]))) if b["duration"] else "--:--"
            self.table.setItem(row, 1, QTableWidgetItem(dur_str))
            self.table.setItem(row, 2, QTableWidgetItem(b["created"][:10] if b["created"] else "--"))

            formats = []
            if b["mp3"]:
                formats.append("[ MP3 ]")
            if b.get("m4b"):
                formats.append("[ M4B ]")
            if b["master"]:
                formats.append("[ FLAC ]")
            if b["mp4"]:
                formats.append("[ MP4 ]")
            if b.get("srt"):
                formats.append("[ SRT ]")
            self.table.setItem(row, 3, QTableWidgetItem(" ".join(formats)))

        self.history_table.setRowCount(0)
        for h in self.history_items:
            txt = h.get("text", "")
            vname = h.get("voice_name", "")
            if q and (q not in txt.lower() and q not in vname.lower()):
                continue

            row = self.history_table.rowCount()
            self.history_table.insertRow(row)

            self.history_table.setItem(row, 0, QTableWidgetItem(h.get("fecha_completa", "")))
            self.history_table.setItem(row, 1, QTableWidgetItem(vname))
            self.history_table.setItem(row, 2, QTableWidgetItem(h.get("duracion_formato", "--")))

            snippet_item = QTableWidgetItem(h.get("snippet", ""))
            snippet_item.setData(Qt.ItemDataRole.UserRole, h)
            self.history_table.setItem(row, 3, snippet_item)

    def on_book_selected(self):
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            return

        book_data = self.table.item(selected_rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        self.selected_book_data = book_data
        self.selected_history_data = None

        self.cover_label.setVisible(True)
        self.spec_card.setVisible(True)
        self.badges_widget.setVisible(True)
        self.btn_change_cover.setVisible(True)
        self.btn_gen_cover_ai.setVisible(True)
        self.btn_open_subs.setVisible(True)
        self.btn_play_trailer.setVisible(True)
        self.text_preview.setVisible(False)
        self.btn_open_video.setVisible(True)
        self.dist_group.setVisible(True)
        self.btn_load_to_reader.setVisible(False)
        self.btn_delete_history.setVisible(False)

        self.lbl_book_title.setText(book_data["title"])
        meta = book_data["meta"]
        dur = meta.get("duration_seconds", 0)
        dur_str = str(timedelta(seconds=int(dur))) if dur else "--"
        ch_count = len(meta.get("chapters_info", [])) or meta.get("chapters_count", 1)
        meta_text = (
            f"Voz: {meta.get('voice_key', 'Desconocida')}  •  "
            f"Capítulos: {ch_count}  •  Oraciones: {meta.get('total_utterances', '--')}  •  "
            f"Duración: {dur_str}\n"
            f"Directorio: {book_data['folder'].name}"
        )
        self.lbl_book_meta.setText(meta_text)

        self.badge_mp3.setVisible(bool(book_data.get("mp3") and book_data["mp3"].exists()))
        self.badge_m4b.setVisible(bool(book_data.get("m4b") and book_data["m4b"].exists()))
        self.badge_flac.setVisible(bool(book_data.get("master") and book_data["master"].exists()))
        self.badge_mp4.setVisible(bool(book_data.get("mp4") and book_data["mp4"].exists()))

        if book_data["cover"] and book_data["cover"].exists():
            pix = QPixmap(str(book_data["cover"])).scaled(
                280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.cover_label.setPixmap(pix)
        else:
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setText("[ Sin Portada ]\n\n1:1 Master Art")

        if book_data["mp3"] and book_data["mp3"].exists():
            self.player.setSource(QUrl.fromLocalFile(str(book_data["mp3"])))
            self.btn_play.setEnabled(True)
        elif book_data.get("m4b") and book_data["m4b"].exists():
            self.player.setSource(QUrl.fromLocalFile(str(book_data["m4b"])))
            self.btn_play.setEnabled(True)
        elif book_data["master"] and book_data["master"].exists():
            self.player.setSource(QUrl.fromLocalFile(str(book_data["master"])))
            self.btn_play.setEnabled(True)
        else:
            self.btn_play.setEnabled(False)

        self.btn_open_video.setEnabled(bool(book_data["mp4"] and book_data["mp4"].exists()))

    def on_history_selected(self):
        selected_rows = self.history_table.selectedItems()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        item = self.history_table.item(row, 3)
        if not item:
            return

        h_data = item.data(Qt.ItemDataRole.UserRole)
        self.selected_history_data = h_data
        self.selected_book_data = None

        self.cover_label.setVisible(False)
        self.spec_card.setVisible(False)
        self.badges_widget.setVisible(False)
        self.btn_change_cover.setVisible(False)
        self.btn_gen_cover_ai.setVisible(False)
        self.btn_open_subs.setVisible(False)
        self.btn_play_trailer.setVisible(False)
        self.text_preview.setVisible(True)
        self.text_preview.setPlainText(h_data.get("text", ""))
        self.btn_open_video.setVisible(False)
        self.dist_group.setVisible(False)
        self.btn_load_to_reader.setVisible(True)
        self.btn_delete_history.setVisible(True)

        self.lbl_book_title.setText(f"[ Lectura Rápida ] {h_data.get('snippet', '')[:50]}")
        meta_text = (
            f"Voz: {h_data.get('voice_name', '')}  •  "
            f"Duración: {h_data.get('duracion_formato', '--')}  •  "
            f"Fecha: {h_data.get('fecha_completa', '')}\n"
            f"Firma: {h_data.get('firma', '')}"
        )
        self.lbl_book_meta.setText(meta_text)

        audio_file = Path(h_data.get("file_path", ""))
        if audio_file.exists():
            self.player.setSource(QUrl.fromLocalFile(str(audio_file)))
            self.btn_play.setEnabled(True)
        else:
            self.btn_play.setEnabled(False)

    def generate_cover_ai_for_selected(self):
        """Genera una portada 1024x1024 con IA local para el audiolibro seleccionado."""
        if not self.selected_book_data:
            QMessageBox.information(self, "Generar Portada IA", "Selecciona primero un audiolibro del catálogo.")
            return
        folder: Path = self.selected_book_data["folder"]
        title = self.selected_book_data["title"]
        try:
            dest = generate_audiobook_cover(
                title=title,
                author="GlobalTTS Studio",
                style="epico",
                output_path=folder / "cover.png",
            )
            self.selected_book_data["cover"] = dest
            pix = QPixmap(str(dest)).scaled(
                280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.cover_label.setPixmap(pix)
            QMessageBox.information(self, "Portada IA Generada", f"Portada 1024x1024 creada exitosamente:\n{dest}")
        except Exception as exc:
            QMessageBox.critical(self, "Error en Portada IA", f"No se pudo generar la portada:\n{exc}")

    def play_or_generate_trailer(self):
        """Reproduce el Audio-Trailer de 90s o lo sintetiza bajo demanda si aún no existe."""
        if not self.selected_book_data:
            return
        folder: Path = self.selected_book_data["folder"]
        trailer_p = folder / "trailer_sinopsis.mp3"
        if not trailer_p.exists():
            meta = self.selected_book_data.get("meta", {})
            src_file = meta.get("source_file", "")
            v_key = meta.get("voice_key", "kokoro-ef_dora")
            try:
                from src.core.models import Chapter, Document
                if src_file and Path(src_file).exists():
                    from src.ingest.loader import load_document
                    doc = load_document(src_file)
                else:
                    doc = Document(
                        title=self.selected_book_data["title"],
                        author="GlobalTTS Studio",
                        language="es",
                        chapters=(Chapter(title="Sinopsis", paragraphs=(f"Una obra fascinante titulada {self.selected_book_data['title']}.",)),),
                        source_path="",
                        source_sha256="",
                    )
                pipe = AudiobookPipeline(JobConfig(voice_key=v_key, output_dir=str(BIBLIOTECA_DIR)))
                res = pipe.generate_standalone_trailer(
                    doc=doc,
                    book_folder=folder,
                    style="epico",
                    cover_image_path=self.selected_book_data.get("cover"),
                )
                if res:
                    trailer_p = res
            except Exception as exc:
                QMessageBox.warning(self, "Aviso Trailer", f"No se pudo generar el trailer:\n{exc}")
                return

        if trailer_p.exists():
            self.selected_book_data["trailer"] = trailer_p
            self.player.setSource(QUrl.fromLocalFile(str(trailer_p)))
            self.player.play()
            self.btn_play.setText("[ || ] Pausa (Trailer)")

    def inspect_subtitles_and_seo(self):
        """Muestra o abre los subtítulos (.SRT/.VTT/.LRC/.ASS) y el paquete SEO/RSS."""
        if not self.selected_book_data:
            return
        folder: Path = self.selected_book_data["folder"]
        seo_file = folder / "youtube_spotify_seo.txt"
        srt_files = list(folder.glob("*.srt"))
        vtt_files = list(folder.glob("*.vtt"))
        lrc_files = list(folder.glob("*.lrc"))
        rss_file = folder / "podcast_rss.xml"
        cap_dir = folder / "capitulos"

        info_lines = [f"Carpeta del Proyecto: {folder}", ""]
        if srt_files:
            info_lines.append(f"• Subtítulos SRT: {srt_files[0].name}")
        if vtt_files:
            info_lines.append(f"• Subtítulos WebVTT: {vtt_files[0].name}")
        if lrc_files:
            info_lines.append(f"• Letras LRC: {lrc_files[0].name}")
        if seo_file.exists():
            info_lines.append(f"• Paquete SEO YouTube/Spotify: {seo_file.name}")
        if rss_file.exists():
            info_lines.append(f"• Feed Podcast RSS 2.0: {rss_file.name}")
        if cap_dir.exists():
            ch_mp3s = list(cap_dir.glob("*.mp3"))
            info_lines.append(f"• Capítulos Divididos: {len(ch_mp3s)} pistas en /capitulos")

        if seo_file.exists():
            try:
                seo_preview = seo_file.read_text(encoding="utf-8")[:700]
                info_lines.extend(["", "--- VISTA PREVIA SEO & TIMESTAMPS ---", seo_preview])
            except Exception:
                pass

        reply = QMessageBox.question(
            self,
            "Artefactos de Subtítulos, Capítulos & SEO",
            "\n".join(info_lines) + "\n\n¿Deseas abrir la carpeta del proyecto para usar estos archivos?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            os.startfile(folder)

    def change_cover_dialog(self):
        """Permite asignar o actualizar la portada de un audiolibro existente."""
        if not self.selected_book_data:
            QMessageBox.information(self, "Asignar Portada", "Por favor selecciona primero un audiolibro del catálogo.")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Imagen de Portada (1:1 Recomendado)",
            "",
            "Imágenes (*.png *.jpg *.jpeg *.webp)",
        )
        if file_path:
            import shutil
            p = Path(file_path)
            book_folder = self.selected_book_data["folder"]
            dest = book_folder / f"cover{p.suffix.lower()}"
            try:
                shutil.copy2(p, dest)
                self.selected_book_data["cover"] = dest
                pix = QPixmap(str(dest)).scaled(
                    280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
                self.cover_label.setPixmap(pix)
                QMessageBox.information(
                    self,
                    "Portada Actualizada",
                    f"La portada de '{self.selected_book_data['title']}' se actualizó correctamente.",
                )
            except Exception as e:
                QMessageBox.critical(self, "Error al Guardar Portada", f"No se pudo copiar la imagen:\n{e}")

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.btn_play.setText("[ ► ] Reproducir")
        else:
            self.player.play()
            self.btn_play.setText("[ || ] Pausa")

    def stop_playback(self):
        self.player.stop()
        self.btn_play.setText("[ ► ] Reproducir")

    def on_position_changed(self, pos: int):
        self.slider.setValue(pos)
        self.lbl_cur_time.setText(str(timedelta(seconds=pos // 1000))[2:7])

    def on_duration_changed(self, dur: int):
        self.slider.setRange(0, dur)
        self.lbl_total_time.setText(str(timedelta(seconds=dur // 1000))[2:7])

    def set_position(self, pos: int):
        self.player.setPosition(pos)

    def open_video(self):
        if self.selected_book_data and self.selected_book_data["mp4"]:
            os.startfile(self.selected_book_data["mp4"])

    def open_current_folder(self):
        if self.selected_book_data and self.selected_book_data.get("folder"):
            os.startfile(self.selected_book_data["folder"])
        elif self.selected_history_data:
            p = Path(self.selected_history_data.get("file_path", ""))
            if p.exists():
                os.startfile(p.parent)

    def load_selected_to_reader(self):
        if self.selected_history_data:
            txt = self.selected_history_data.get("text", "")
            self.load_text_requested.emit(txt)

    def delete_current_history_entry(self):
        if not self.selected_history_data:
            return
        hid = self.selected_history_data.get("id")
        reply = QMessageBox.question(self, "Eliminar Lectura", "¿Deseas eliminar permanentemente esta lectura del historial?")
        if reply == QMessageBox.StandardButton.Yes:
            self.stop_playback()
            self.history_manager.delete_entry(hid)
            self.refresh_library()

    def open_youtube_dialog(self):
        if not self.selected_book_data:
            return
        b = self.selected_book_data
        folder: Path = b["folder"]
        mp4_path = b.get("mp4")
        if not mp4_path or not mp4_path.exists():
            QMessageBox.warning(self, "Sin Video", "Este audiolibro no tiene un video karaoke generado.")
            return

        seo_file = folder / "youtube_spotify_seo.txt"
        if seo_file.exists():
            seo_text = seo_file.read_text(encoding="utf-8")
        else:
            seo_text = (
                f"Título sugerido: Audiolibro Completo | {b['title']} (Voz IA en Español)\n\n"
                f"Marcas de tiempo:\n00:00 Inicio\n\n"
                f"HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®"
            )

        msg = (
            f"PAQUETE DE PUBLICACIÓN YOUTUBE STUDIO:\n\n"
            f"Archivo de Video: {mp4_path.name}\n\n"
            f"{seo_text[:900]}\n\n"
            f"¿Deseas abrir YouTube Studio en tu navegador y mostrar la carpeta del libro?"
        )
        reply = QMessageBox.question(self, "Publicar en YouTube Studio", msg)
        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open("https://studio.youtube.com")
            os.startfile(folder)

    def open_spotify_dialog(self):
        if not self.selected_book_data:
            return
        b = self.selected_book_data
        folder: Path = b["folder"]
        mp3_path = b.get("mp3")
        if not mp3_path or not mp3_path.exists():
            QMessageBox.warning(self, "Sin Audio Master", "No se encontró el archivo MP3 para podcast.")
            return

        rss_file = folder / "podcast_rss.xml"
        rss_status = f"Feed RSS 2.0 generado: {rss_file.name}" if rss_file.exists() else "Feed RSS listo en carpeta"

        msg = (
            f"PAQUETE PARA SPOTIFY FOR PODCASTERS & APPLE PODCASTS:\n\n"
            f"• Master Audio: {mp3_path.name} (EBU R128 + Studio DSP -1.0 dBTP)\n"
            f"• {rss_status}\n\n"
            f"¿Deseas abrir Spotify for Podcasters en tu navegador y la carpeta del proyecto?"
        )
        reply = QMessageBox.question(self, "Publicar en Spotify / Podcasts", msg)
        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open("https://podcasters.spotify.com")
            os.startfile(folder)
