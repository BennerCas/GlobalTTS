"""Diálogos Interactivos de Estudio para GlobalTTS:
1. LexiconManagerDialog: Gestor del Diccionario Fonético y Siglas.
2. VoiceClonerDialog: Clonador de Voz Biométrico Local (CosyVoice3 campplus.onnx + F0/Formantes DSP).
3. MobileStreamingDialog: Servidor WiFi de Streaming Móvil con Generador de Código QR Nativo.
4. UrlIngestDialog: Extractor Readability de Artículos y Páginas Web.
"""
from __future__ import annotations

import threading
import webbrowser
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

import sounddevice as sd
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.ai.piper_engine import PiperTtsEngine
from src.ai.voice_cloner import GLOBAL_VOICE_CLONER, ClonedVoiceSpec
from src.api.mobile_server import GLOBAL_MOBILE_SERVER, generate_qr_image
from src.core.job import BIBLIOTECA_DIR
from src.core.lexicon import PhoneticLexicon
from src.ingest.url_reader import extract_text_from_url

STUDIO_DIALOG_QSS = """
QDialog {
    background-color: #0B0F19;
    color: #F8FAFC;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 12px;
}
QGroupBox {
    background-color: #111726;
    border: 1px solid #1E293B;
    border-radius: 6px;
    margin-top: 12px;
    padding: 10px;
    font-weight: 700;
    color: #38BDF8;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QLabel {
    color: #CBD5E1;
}
QLineEdit, QPlainTextEdit, QComboBox, QTableWidget, QListWidget {
    background-color: #0F172A;
    border: 1px solid #334155;
    border-radius: 4px;
    color: #F8FAFC;
    padding: 5px;
}
QHeaderView::section {
    background-color: #1E293B;
    color: #38BDF8;
    font-weight: 700;
    padding: 5px;
    border: 1px solid #334155;
}
QPushButton {
    background-color: #1E293B;
    border: 1px solid #334155;
    border-radius: 4px;
    color: #E2E8F0;
    padding: 6px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #334155;
    border-color: #38BDF8;
    color: #FFFFFF;
}
"""


class LexiconManagerDialog(QDialog):
    """Gestor interactivo del Diccionario Fonético y Corrector Léxico."""

    def __init__(self, parent=None, lexicon: Optional[PhoneticLexicon] = None):
        super().__init__(parent)
        self.setWindowTitle("Diccionario Fonético y Corrector Léxico (Lexicon)")
        self.resize(760, 540)
        self.setStyleSheet(STUDIO_DIALOG_QSS)
        self.lexicon = lexicon or PhoneticLexicon()

        layout = QVBoxLayout(self)

        lbl_intro = QLabel(
            "Define cómo deben pronunciarse siglas, acrónimos técnicos, abreviaturas y extranjerismos "
            "antes de pasar al motor neuronal de síntesis."
        )
        lbl_intro.setWordWrap(True)
        layout.addWidget(lbl_intro)

        # Tabla de reglas
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Término / Sigla", "Fonética en Español", "Categoría", "Mayús/Minús"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, stretch=1)

        # Formulario para añadir regla
        grp_add = QGroupBox("AGREGAR / ACTUALIZAR REGLA FONÉTICA")
        add_lay = QHBoxLayout()
        self.txt_term = QLineEdit()
        self.txt_term.setPlaceholderText("Ej: SaaS, NVMe, Borges...")
        self.txt_phonetic = QLineEdit()
        self.txt_phonetic.setPlaceholderText("Ej: sas, ene ve eme e, Bórjes...")
        self.cmb_cat = QComboBox()
        self.cmb_cat.addItems(["acronimo", "anglicismo", "unidad", "abreviatura", "custom"])
        self.chk_case = QCheckBox("Distinguir Mayúsculas")
        self.chk_case.setChecked(True)
        btn_add = QPushButton("[ + ] Guardar Regla")
        btn_add.setStyleSheet("background-color: #0284C7; color: #FFFFFF; font-weight: 700;")
        btn_add.clicked.connect(self._on_add)

        add_lay.addWidget(QLabel("Término:"))
        add_lay.addWidget(self.txt_term, 1)
        add_lay.addWidget(QLabel("Fonética:"))
        add_lay.addWidget(self.txt_phonetic, 2)
        add_lay.addWidget(self.cmb_cat)
        add_lay.addWidget(self.chk_case)
        add_lay.addWidget(btn_add)
        grp_add.setLayout(add_lay)
        layout.addWidget(grp_add)

        # Probador en vivo
        grp_test = QGroupBox("PROBADOR DE TRANSFORMACIÓN FONÉTICA EN VIVO")
        test_lay = QHBoxLayout()
        self.txt_test_in = QLineEdit("El modelo de IA procesa 25 GB de VRAM en la GPU con SQL y API REST en el s. XXI.")
        self.lbl_test_out = QLineEdit()
        self.lbl_test_out.setReadOnly(True)
        self.lbl_test_out.setStyleSheet("color: #38BDF8; font-weight: 600;")
        btn_test = QPushButton("[ ↻ ] Probar")
        btn_test.clicked.connect(self._update_test_preview)
        self.txt_test_in.textChanged.connect(self._update_test_preview)
        test_lay.addWidget(self.txt_test_in, 1)
        test_lay.addWidget(btn_test)
        test_lay.addWidget(self.lbl_test_out, 1)
        grp_test.setLayout(test_lay)
        layout.addWidget(grp_test)

        # Botones inferiores
        bot_lay = QHBoxLayout()
        btn_del = QPushButton("[ ✕ ] Eliminar Seleccionada")
        btn_del.clicked.connect(self._on_delete)
        btn_reset = QPushButton("[ ↺ ] Restaurar Diccionario Base")
        btn_reset.clicked.connect(self._on_reset)
        btn_close = QPushButton("[ ✓ ] Cerrar")
        btn_close.clicked.connect(self.accept)
        bot_lay.addWidget(btn_del)
        bot_lay.addWidget(btn_reset)
        bot_lay.addStretch()
        bot_lay.addWidget(btn_close)
        layout.addLayout(bot_lay)

        self._refresh_table()
        self._update_test_preview()

    def _refresh_table(self) -> None:
        entries = self.lexicon.list_entries()
        self.table.setRowCount(len(entries))
        for r, entry in enumerate(entries):
            self.table.setItem(r, 0, QTableWidgetItem(entry.term))
            self.table.setItem(r, 1, QTableWidgetItem(entry.phonetic))
            self.table.setItem(r, 2, QTableWidgetItem(entry.category))
            self.table.setItem(r, 3, QTableWidgetItem("Sí" if entry.case_sensitive else "No"))

    def _on_add(self) -> None:
        term = self.txt_term.text().strip()
        phon = self.txt_phonetic.text().strip()
        if not term or not phon:
            QMessageBox.warning(self, "Campos Requeridos", "Ingresa tanto el término como su pronunciación fonética.")
            return
        self.lexicon.add_entry(
            term=term,
            phonetic=phon,
            case_sensitive=self.chk_case.isChecked(),
            category=self.cmb_cat.currentText(),
        )
        self.txt_term.clear()
        self.txt_phonetic.clear()
        self._refresh_table()
        self._update_test_preview()

    def _on_delete(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item:
            self.lexicon.remove_entry(item.text())
            self._refresh_table()
            self._update_test_preview()

    def _on_reset(self) -> None:
        self.lexicon.reset_defaults()
        self._refresh_table()
        self._update_test_preview()

    def _update_test_preview(self) -> None:
        self.lbl_test_out.setText(self.lexicon.apply(self.txt_test_in.text()))


class VoiceClonerDialog(QDialog):
    """Laboratorio de Clonación de Voz Biométrica Local (campplus.onnx + F0/Formantes DSP)."""

    voices_updated = pyqtSignal()
    voice_cloned = pyqtSignal(str)

    def __init__(self, parent=None, on_voices_changed: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.setWindowTitle("Clonación de Voz & Perfilado Acústico Local (CosyVoice3 + DSP)")
        self.resize(740, 500)
        self.setStyleSheet(STUDIO_DIALOG_QSS)
        self.on_voices_changed = on_voices_changed
        self.selected_audio_path: Optional[Path] = None

        layout = QVBoxLayout(self)

        grp_new = QGroupBox("CREAR NUEVO PERFIL DE VOZ CLONADA (100% LOCAL / OFFLINE)")
        new_lay = QVBoxLayout()
        lbl_desc = QLabel(
            "Selecciona una grabación de voz de referencia (5 a 45 segundos en WAV, MP3 o FLAC). "
            "El motor extraerá el vector biométrico mediante campplus.onnx, medirá la frecuencia "
            "fundamental F0, formantes y cadencia, y registrará la voz clonada en todos los selectores."
        )
        lbl_desc.setWordWrap(True)
        new_lay.addWidget(lbl_desc)

        row1 = QHBoxLayout()
        self.txt_voice_name = QLineEdit()
        self.txt_voice_name.setPlaceholderText("Nombre del Locutor / Voz Clonada (ej. Narrador Estudio)...")
        self.btn_pick_audio = QPushButton("[ + ] Seleccionar Audio de Referencia...")
        self.btn_pick_audio.clicked.connect(self._pick_reference_audio)
        self.btn_clone = QPushButton("[ ★ ] Analizar y Clonar Voz")
        self.btn_clone.setStyleSheet("background-color: #0284C7; color: #FFFFFF; font-weight: 700;")
        self.btn_clone.clicked.connect(self._run_cloning)
        row1.addWidget(QLabel("Nombre:"))
        row1.addWidget(self.txt_voice_name, 1)
        row1.addWidget(self.btn_pick_audio)
        row1.addWidget(self.btn_clone)
        new_lay.addLayout(row1)

        self.lbl_ref_status = QLabel("Audio de referencia: (Ninguno seleccionado)")
        self.lbl_ref_status.setStyleSheet("color: #38BDF8; font-size: 11px;")
        new_lay.addWidget(self.lbl_ref_status)
        grp_new.setLayout(new_lay)
        layout.addWidget(grp_new)

        grp_list = QGroupBox("PERFILES DE VOZ CLONADOS DISPONIBLES")
        list_lay = QVBoxLayout()
        self.list_cloned = QListWidget()
        list_lay.addWidget(self.list_cloned, stretch=1)

        test_row = QHBoxLayout()
        self.txt_preview = QLineEdit("Hola, esta es una prueba acústica de mi perfil de voz clonado localmente en GlobalTTS Studio.")
        btn_play = QPushButton("[ ► ] Escuchar Prueba")
        btn_play.clicked.connect(self._preview_selected_voice)
        btn_del = QPushButton("[ ✕ ] Eliminar Perfil")
        btn_del.clicked.connect(self._delete_selected_voice)
        test_row.addWidget(self.txt_preview, 1)
        test_row.addWidget(btn_play)
        test_row.addWidget(btn_del)
        list_lay.addLayout(test_row)
        grp_list.setLayout(list_lay)
        layout.addWidget(grp_list, stretch=1)

        bot_row = QHBoxLayout()
        bot_row.addStretch()
        btn_close = QPushButton("[ ✓ ] Cerrar")
        btn_close.clicked.connect(self.accept)
        bot_row.addWidget(btn_close)
        layout.addLayout(bot_row)

        self._refresh_cloned_list()

    def _pick_reference_audio(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Muestra de Voz de Referencia",
            "",
            "Archivos de Audio (*.wav *.mp3 *.flac *.ogg)",
        )
        if file_path:
            self.selected_audio_path = Path(file_path)
            self.lbl_ref_status.setText(f"Referencia cargada: {self.selected_audio_path.name}")
            if not self.txt_voice_name.text().strip():
                self.txt_voice_name.setText(self.selected_audio_path.stem.replace("_", " ").title())

    def _run_cloning(self) -> None:
        if not self.selected_audio_path or not self.selected_audio_path.exists():
            QMessageBox.warning(self, "Falta Audio", "Primero selecciona un archivo de audio de referencia.")
            return
        name = self.txt_voice_name.text().strip() or self.selected_audio_path.stem
        try:
            spec: ClonedVoiceSpec = GLOBAL_VOICE_CLONER.clone_from_audio(self.selected_audio_path, name)
            self.lbl_ref_status.setText(
                f"Clonado exitoso: {spec.name} | F0: {spec.f0_hz}Hz | Pitch: {spec.pitch_semitones:+.2f}st | "
                f"Warmth: {spec.warmth_db:+.1f}dB | Embedding L2: {spec.embedding_norm}"
            )
            self._refresh_cloned_list()
            self.voices_updated.emit()
            self.voice_cloned.emit(spec.key)
            if self.on_voices_changed:
                self.on_voices_changed()
        except Exception as exc:
            QMessageBox.critical(self, "Error en Clonación", f"No se pudo analizar el audio de referencia:\n{exc}")

    def _refresh_cloned_list(self) -> None:
        self.list_cloned.clear()
        GLOBAL_VOICE_CLONER.load()
        for key, spec in GLOBAL_VOICE_CLONER.voices.items():
            label = (
                f"{spec.name}  [ID: {key} | Base: {spec.base_voice_key} | "
                f"F0: {spec.f0_hz}Hz | Pitch: {spec.pitch_semitones:+.2f}st | EQ: {spec.warmth_db:+.1f}/{spec.presence_db:+.1f}dB]"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list_cloned.addItem(item)

    def _preview_selected_voice(self) -> None:
        item = self.list_cloned.currentItem()
        if not item:
            QMessageBox.information(self, "Selecciona un Perfil", "Selecciona un perfil clonado de la lista para probarlo.")
            return
        v_key = item.data(Qt.ItemDataRole.UserRole)
        txt = self.txt_preview.text().strip()
        if not txt:
            return

        def _worker():
            try:
                engine = PiperTtsEngine(voice_key=v_key)
                samples = engine.synthesize(txt)
                if len(samples) > 0:
                    sd.stop()
                    sd.play(samples, samplerate=engine.sample_rate)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _delete_selected_voice(self) -> None:
        item = self.list_cloned.currentItem()
        if not item:
            return
        v_key = item.data(Qt.ItemDataRole.UserRole)
        if GLOBAL_VOICE_CLONER.remove_voice(v_key):
            self._refresh_cloned_list()
            self.voices_updated.emit()
            if self.on_voices_changed:
                self.on_voices_changed()


class MobileStreamingDialog(QDialog):
    """Ventana con servidor WiFi activo y Código QR nativo para reproducción en móviles."""

    def __init__(self, parent=None, biblioteca_dir: Optional[Path] = None):
        super().__init__(parent)
        self.setWindowTitle("Streaming Móvil WiFi (QR / HTTP Range 206)")
        self.resize(480, 520)
        self.setStyleSheet(STUDIO_DIALOG_QSS)

        GLOBAL_MOBILE_SERVER.output_root = Path(biblioteca_dir) if biblioteca_dir else BIBLIOTECA_DIR
        url = GLOBAL_MOBILE_SERVER.start()
        self.stream_url = url

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_head = QLabel("SERVIDOR DE STREAMING WIFI ACTIVO")
        lbl_head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_head.setStyleSheet("color: #38BDF8; font-size: 15px; font-weight: 800;")
        layout.addWidget(lbl_head)

        lbl_sub = QLabel(
            "Escanea el código QR con la cámara de tu teléfono (conectado a la misma red WiFi) "
            "para escuchar tus audiolibros y ver videos karaoke sin transferir cables."
        )
        lbl_sub.setWordWrap(True)
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_sub)

        # Renderizar imagen QR nativa
        qr_lbl = QLabel()
        qr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            pil_qr = generate_qr_image(url, box_size=8, border=4)
            buf = BytesIO()
            pil_qr.save(buf, format="PNG")
            qimg = QImage.fromData(buf.getvalue(), "PNG")
            qr_lbl.setPixmap(QPixmap.fromImage(qimg))
        except Exception as exc:
            qr_lbl.setText(f"[QR: {url}] ({exc})")
        layout.addWidget(qr_lbl)

        self.txt_url = QLineEdit(url)
        self.txt_url.setReadOnly(True)
        self.txt_url.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.txt_url.setStyleSheet("font-size: 14px; font-weight: 700; color: #10B981; padding: 8px;")
        layout.addWidget(self.txt_url)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton("[ ⎘ ] Copiar Enlace")
        btn_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.stream_url))
        btn_open = QPushButton("[ ↗ ] Abrir en Navegador")
        btn_open.clicked.connect(lambda: webbrowser.open(self.stream_url))
        btn_close = QPushButton("[ ✓ ] Cerrar (Mantener Activo)")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_open)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)


class UrlIngestDialog(QDialog):
    """Extractor nativo de artículos web (Readability) para Generador y Lectura Rápida."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Extractor Nativo de Artículos Web (Readability)")
        self.resize(680, 460)
        self.setStyleSheet(STUDIO_DIALOG_QSS)
        self.extracted_url: str = ""
        self.extracted_title: str = ""
        self.extracted_text: str = ""

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self.txt_url = QLineEdit()
        self.txt_url.setPlaceholderText("https://es.wikipedia.org/wiki/... o URL de artículo/blog/noticia")
        btn_fetch = QPushButton("[ ↗ ] Extraer Contenido Limpio")
        btn_fetch.setStyleSheet("background-color: #0284C7; color: #FFFFFF; font-weight: 700;")
        btn_fetch.clicked.connect(self._fetch_article)
        top_row.addWidget(QLabel("URL:"))
        top_row.addWidget(self.txt_url, 1)
        top_row.addWidget(btn_fetch)
        layout.addLayout(top_row)

        self.lbl_title = QLabel("Título detectado: —")
        self.lbl_title.setStyleSheet("color: #38BDF8; font-weight: 700;")
        layout.addWidget(self.lbl_title)

        self.txt_preview = QPlainTextEdit()
        self.txt_preview.setPlaceholderText("La vista previa del artículo limpio aparecerá aquí (puedes editarla antes de importar)...")
        layout.addWidget(self.txt_preview, stretch=1)

        bot_row = QHBoxLayout()
        bot_row.addStretch()
        btn_cancel = QPushButton("[ ✕ ] Cancelar")
        btn_cancel.clicked.connect(self.reject)
        btn_use = QPushButton("[ ✓ ] Importar Artículo")
        btn_use.setStyleSheet("background-color: #059669; color: #FFFFFF; font-weight: 700;")
        btn_use.clicked.connect(self._confirm_import)
        bot_row.addWidget(btn_cancel)
        bot_row.addWidget(btn_use)
        layout.addLayout(bot_row)

    def _fetch_article(self) -> None:
        url = self.txt_url.text().strip()
        if not url:
            return
        try:
            title, body = extract_text_from_url(url)
            self.extracted_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
            self.extracted_title = title
            self.extracted_text = body
            self.lbl_title.setText(f"Título detectado: {title} ({len(body)} caracteres)")
            self.txt_preview.setPlainText(body)
        except Exception as exc:
            QMessageBox.critical(self, "Error al Extraer URL", f"No se pudo extraer el artículo web:\n{exc}")

    def _confirm_import(self) -> None:
        url = self.txt_url.text().strip()
        body = self.txt_preview.toPlainText().strip()
        if not body and url:
            self._fetch_article()
            body = self.txt_preview.toPlainText().strip()
        if not url and not body:
            QMessageBox.warning(self, "Sin Contenido", "Ingresa una URL o extrae el artículo primero.")
            return
        if not self.extracted_url and url:
            self.extracted_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
        if body:
            self.extracted_text = body
        self.accept()
