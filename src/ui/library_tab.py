"""Pestaña de Biblioteca y Reproductor Integrado para GlobalTTS.

Diseño Ejecutivo Obsidian & Titanium:
- Cero emojis: sustituidos por glifos de línea [ ► ], [ || ], [ ■ ], [ ⟳ ], [ ↗ ].
- Reproductor multimedia de alta fidelidad con slider de precisión y telemetría de tiempo.
- Selector de obras con metadatos técnicos completos (Voz, oraciones, duración, EBU R128).
- Gestión y lanzamiento de Video Karaoke MP4 y masters de audio MP3/FLAC.
- Acceso sobrio y profesional a YouTube Studio y Spotify for Podcasters.
"""
from __future__ import annotations

import json
import os
import subprocess
import webbrowser
from datetime import timedelta
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BIBLIOTECA_DIR = PROJECT_ROOT / "biblioteca"


class LibraryTab(QWidget):
    """Pestaña de exploración de la biblioteca y reproductor integrado."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        self.books: list[dict] = []
        self.selected_book_data: Optional[dict] = None
        self.init_ui()
        self.setup_player_events()
        self.refresh_library()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # Barra superior con buscador y accesos de carpeta
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("[ ⌕ ] Buscar en la biblioteca por título o autor...")
        self.search_edit.textChanged.connect(self.filter_books)
        top_bar.addWidget(self.search_edit, stretch=1)

        refresh_btn = QPushButton("[ ⟳ ] Actualizar")
        refresh_btn.setObjectName("secondaryActionButton")
        refresh_btn.clicked.connect(self.refresh_library)
        top_bar.addWidget(refresh_btn)

        open_folder_btn = QPushButton("[ ↗ ] Abrir Carpeta Biblioteca")
        open_folder_btn.setObjectName("secondaryActionButton")
        open_folder_btn.clicked.connect(lambda: os.startfile(BIBLIOTECA_DIR) if BIBLIOTECA_DIR.exists() else None)
        top_bar.addWidget(open_folder_btn)

        main_layout.addLayout(top_bar)

        # Splitter central: Lista de obras (izq) y Reproductor Ejecutivo (der)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 1. Tabla de audiolibros
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["TÍTULO / OBRA", "DURACIÓN", "FECHA", "FORMATOS"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.on_book_selected)
        splitter.addWidget(self.table)

        # 2. Panel de Detalles y Reproductor Multimedia Ejecutivo
        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("cardFrame")
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setSpacing(10)
        detail_layout.setContentsMargins(14, 14, 14, 14)

        # Título y metadatos del libro
        self.lbl_book_title = QLabel("Selecciona un audiolibro del catálogo")
        self.lbl_book_title.setObjectName("titleLabel")
        self.lbl_book_title.setWordWrap(True)
        detail_layout.addWidget(self.lbl_book_title)

        self.lbl_book_meta = QLabel("Metadatos técnicos: Selecciona un elemento para inspeccionar.")
        self.lbl_book_meta.setObjectName("subtitleLabel")
        self.lbl_book_meta.setWordWrap(True)
        detail_layout.addWidget(self.lbl_book_meta)

        # Portada / Carátula
        self.cover_label = QLabel("[ Sin Portada ]")
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setFixedSize(170, 170)
        self.cover_label.setStyleSheet(
            "background-color: #0b0f16; border: 1px solid #1e2633; border-radius: 6px; color: #475569;"
        )
        detail_layout.addWidget(self.cover_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Caja de Reproducción Multimedia
        player_box = QFrame()
        player_box.setObjectName("metricCard")
        p_lay = QVBoxLayout(player_box)
        p_lay.setSpacing(8)

        # Slider de posición y marcas de tiempo en monospace
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

        # Botonera de control de transporte y volumen
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

        # Botones de Acción de Archivos
        actions_grid = QHBoxLayout()
        actions_grid.setSpacing(8)

        self.btn_open_video = QPushButton("[ ► ] Ver Video Karaoke")
        self.btn_open_video.setObjectName("actionButton")
        self.btn_open_video.clicked.connect(self.open_video)

        self.btn_open_folder = QPushButton("[ ↗ ] Abrir Carpeta del Libro")
        self.btn_open_folder.setObjectName("secondaryActionButton")
        self.btn_open_folder.clicked.connect(self.open_current_folder)

        actions_grid.addWidget(self.btn_open_video)
        actions_grid.addWidget(self.btn_open_folder)
        detail_layout.addLayout(actions_grid)

        # Módulo de Distribución Ejecutiva
        dist_group = QGroupBox("Distribución y Plataformas")
        dist_lay = QHBoxLayout(dist_group)
        dist_lay.setContentsMargins(10, 8, 10, 8)
        dist_lay.setSpacing(8)

        self.btn_youtube = QPushButton("[ ↗ ] Publicar en YouTube Studio")
        self.btn_youtube.setObjectName("brandButton")
        self.btn_youtube.clicked.connect(self.open_youtube_dialog)

        self.btn_spotify = QPushButton("[ ↗ ] Publicar en Spotify / Podcasts")
        self.btn_spotify.setObjectName("brandButton")
        self.btn_spotify.clicked.connect(self.open_spotify_dialog)

        dist_lay.addWidget(self.btn_youtube)
        dist_lay.addWidget(self.btn_spotify)
        detail_layout.addWidget(dist_group)

        detail_layout.addStretch()
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([500, 440])

        main_layout.addWidget(splitter)

    def setup_player_events(self):
        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_duration_changed)

    def refresh_library(self):
        self.books = []
        if not BIBLIOTECA_DIR.exists():
            return

        for item in sorted(BIBLIOTECA_DIR.iterdir(), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
            if item.is_dir():
                meta_files = list(item.glob("*_metadata.json"))
                meta = {}
                if meta_files:
                    try:
                        with open(meta_files[0], "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        pass

                mp3_files = list(item.glob("*.mp3"))
                mp4_files = list(item.glob("*.mp4"))
                flac_files = list(item.glob("*.flac")) + list(item.glob("*.wav"))
                cover_files = list(item.glob("cover.*"))

                self.books.append({
                    "folder": item,
                    "title": meta.get("output_name") or item.name,
                    "duration": meta.get("duration_seconds", 0),
                    "created": meta.get("created_at", ""),
                    "mp3": mp3_files[0] if mp3_files else None,
                    "mp4": mp4_files[0] if mp4_files else None,
                    "master": flac_files[0] if flac_files else None,
                    "cover": cover_files[0] if cover_files else None,
                    "meta": meta,
                })

        self.filter_books(self.search_edit.text())

    def filter_books(self, query: str = ""):
        self.table.setRowCount(0)
        q = query.lower().strip()

        for b in self.books:
            title = b["title"]
            if q and q not in title.lower():
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)

            # Col 0: Título
            item_title = QTableWidgetItem(title)
            item_title.setData(Qt.ItemDataRole.UserRole, b)
            self.table.setItem(row, 0, item_title)

            # Col 1: Duración
            dur_str = str(timedelta(seconds=int(b["duration"]))) if b["duration"] else "--:--"
            self.table.setItem(row, 1, QTableWidgetItem(dur_str))

            # Col 2: Fecha
            self.table.setItem(row, 2, QTableWidgetItem(b["created"][:10] if b["created"] else "--"))

            # Col 3: Formatos con insignias de texto sobrias
            formats = []
            if b["mp3"]:
                formats.append("[ MP3 ]")
            if b["master"]:
                formats.append("[ FLAC ]")
            if b["mp4"]:
                formats.append("[ MP4 ]")
            self.table.setItem(row, 3, QTableWidgetItem(" ".join(formats)))

        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def on_book_selected(self):
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            return

        book_data = self.table.item(selected_rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        self.selected_book_data = book_data

        # Actualizar UI de detalles
        self.lbl_book_title.setText(book_data["title"])
        meta = book_data["meta"]
        dur = meta.get("duration_seconds", 0)
        dur_str = str(timedelta(seconds=int(dur))) if dur else "--"
        meta_text = (
            f"Voz: {meta.get('voice_key', 'Desconocida')}  •  "
            f"Oraciones: {meta.get('total_utterances', '--')}  •  "
            f"Duración: {dur_str}  •  Normalización: EBU R128 (-16 LUFS)\n"
            f"Directorio: {book_data['folder'].name}"
        )
        self.lbl_book_meta.setText(meta_text)

        # Portada
        if book_data["cover"] and book_data["cover"].exists():
            pix = QPixmap(str(book_data["cover"])).scaled(
                170, 170, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self.cover_label.setPixmap(pix)
        else:
            self.cover_label.setText("[ Sin Portada ]")

        # Configurar audio en reproductor
        if book_data["mp3"] and book_data["mp3"].exists():
            self.player.setSource(QUrl.fromLocalFile(str(book_data["mp3"])))
            self.btn_play.setEnabled(True)
        else:
            self.btn_play.setEnabled(False)

        self.btn_open_video.setEnabled(bool(book_data["mp4"] and book_data["mp4"].exists()))

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
        if self.selected_book_data and self.selected_book_data["folder"]:
            os.startfile(self.selected_book_data["folder"])

    def open_youtube_dialog(self):
        if not self.selected_book_data:
            return
        b = self.selected_book_data
        mp4_path = b.get("mp4")
        if not mp4_path or not mp4_path.exists():
            QMessageBox.warning(self, "Sin Video", "Este audiolibro no tiene un video karaoke generado.")
            return

        title_text = f"Audiolibro Completo | {b['title']} (Voz IA en Español)"
        desc_text = (
            f"Audiolibro completo de '{b['title']}', narrado con inteligencia artificial local y alta fidelidad sonora.\n\n"
            f"Marcas de tiempo:\n00:00 Inicio\n\n"
            f"#Audiolibro #{b['title'].replace(' ', '')} #TTS #Literatura\n"
            f"HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®"
        )

        msg = (
            f"PREPARACIÓN PARA YOUTUBE STUDIO:\n\n"
            f"Archivo a subir:\n{mp4_path.name}\n\n"
            f"Título sugerido:\n{title_text}\n\n"
            f"Descripción y Marcas de Tiempo:\n{desc_text}\n\n"
            f"¿Deseas abrir YouTube Studio en tu navegador y abrir la carpeta del libro?"
        )
        reply = QMessageBox.question(self, "Publicar en YouTube", msg)
        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open("https://studio.youtube.com")
            os.startfile(b["folder"])

    def open_spotify_dialog(self):
        if not self.selected_book_data:
            return
        b = self.selected_book_data
        mp3_path = b.get("mp3")
        if not mp3_path or not mp3_path.exists():
            QMessageBox.warning(self, "Sin Audio Master", "No se encontró el archivo MP3 para podcast.")
            return

        msg = (
            f"PREPARACIÓN PARA SPOTIFY / PODCASTS:\n\n"
            f"Archivo Master MP3:\n{mp3_path.name} (Normalizado EBU R128 a 256k)\n\n"
            f"¿Deseas abrir Spotify for Podcasters en tu navegador y la carpeta con el audio?"
        )
        reply = QMessageBox.question(self, "Publicar en Spotify", msg)
        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open("https://podcasters.spotify.com")
            os.startfile(b["folder"])
