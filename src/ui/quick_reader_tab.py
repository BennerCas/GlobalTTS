"""Pestaña de Lectura Rápida y Suite de Configuración Profesional para GlobalTTS.

Incluye:
- Lector rápido con caja de texto y scroll invisible para pegar y escuchar inmediatamente.
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
    QScrollArea,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import sounddevice as sd

from src.ai.piper_engine import PiperTtsEngine, list_available_piper_voices
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
        content = f'@echo off\nstart "" "{iniciar_bat}"\n'
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


class QuickReaderTab(QWidget):
    """Pestaña que combina el Lector Rápido con scroll invisible y la Suite de Configuración."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.play_worker: Optional[TtsPlayWorker] = None
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
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Scroll área general para permitir pantallas compactas
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(14)

        # =========================================================================
        # SECCIÓN 1: LECTOR RÁPIDO CON SCROLL INVISIBLE
        # =========================================================================
        reader_box = QFrame()
        reader_box.setObjectName("cardFrame")
        r_lay = QVBoxLayout(reader_box)
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
            "Pega cualquier texto aquí para lectura instantánea sin conexión, o usa el atajo global en cualquier "
            "programa: Seleccionar texto + Clic Izquierdo + Barra Espaciadora."
        )
        desc_lbl.setObjectName("subtitleLabel")
        desc_lbl.setWordWrap(True)
        r_lay.addWidget(desc_lbl)

        # Caja de texto con scroll invisible
        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("quickTextBox")
        self.text_edit.setPlaceholderText("Pega o escribe aquí cualquier texto para escucharlo en voz alta...")
        self.text_edit.setMinimumHeight(150)
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
        r_lay.addWidget(self.text_edit)

        # Barra de información de texto
        info_row = QHBoxLayout()
        self.lbl_counter = QLabel("Caracteres: 0 | Palabras: 0 | Duración est.: ~0s")
        self.lbl_counter.setStyleSheet("color: #8b949e; font-size: 11px;")
        info_row.addWidget(self.lbl_counter)
        r_lay.addLayout(info_row)

        # Botonera de acciones
        btns_row = QHBoxLayout()
        btns_row.setSpacing(8)

        self.btn_play = QPushButton("▶️ Leer en Voz Alta (Play)")
        self.btn_play.setObjectName("primaryButton")
        self.btn_play.clicked.connect(self.play_text)
        btns_row.addWidget(self.btn_play)

        self.btn_stop = QPushButton("⏹️ Detener (Esc)")
        self.btn_stop.setObjectName("secondaryActionButton")
        self.btn_stop.clicked.connect(self.stop_text)
        btns_row.addWidget(self.btn_stop)

        self.btn_paste = QPushButton("📋 Pegar del Portapapeles")
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
        layout.addWidget(reader_box)

        # =========================================================================
        # SECCIÓN 2: SUITE DE CONFIGURACIÓN PROFESIONAL
        # =========================================================================
        config_box = QFrame()
        config_box.setObjectName("cardFrame")
        c_lay = QVBoxLayout(config_box)
        c_lay.setSpacing(12)

        cfg_title = QLabel("⚙️ Suite de Configuración Profesional")
        cfg_title.setObjectName("titleLabel")
        c_lay.addWidget(cfg_title)

        # 1. Selector de Voz Local y Velocidad
        v_box = QGroupBox("Voz Local & Modulación de Velocidad")
        v_lay = QVBoxLayout(v_box)

        v_row1 = QHBoxLayout()
        v_row1.addWidget(QLabel("Voz Local Predeterminada:"))
        self.voice_combo = QComboBox()
        self.populate_voices()
        v_row1.addWidget(self.voice_combo, stretch=1)

        self.btn_test_voice = QPushButton("🔊 Probar Voz")
        self.btn_test_voice.setObjectName("secondaryActionButton")
        self.btn_test_voice.clicked.connect(self.test_voice_sample)
        v_row1.addWidget(self.btn_test_voice)
        v_lay.addLayout(v_row1)

        # Slider de Velocidad
        spd_row = QHBoxLayout()
        self.lbl_speed = QLabel("Velocidad: 1.0x (Normal)")
        self.lbl_speed.setMinimumWidth(160)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(5, 25)  # 0.5x a 2.5x
        spd_val = int(float(self.config.get("speed_factor", 1.0)) * 10)
        self.speed_slider.setValue(spd_val)
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        spd_row.addWidget(self.lbl_speed)
        spd_row.addWidget(self.speed_slider)
        v_lay.addLayout(spd_row)

        c_lay.addWidget(v_box)

        # 2. Atajos Globales de Teclado (AutoHotkey v2)
        hk_box = QGroupBox("Atajos Globales de Acceso Rápido (AutoHotkey v2)")
        hk_lay = QVBoxLayout(hk_box)

        self.lbl_ahk_status = QLabel("🟢 Servicio de Atajos Globales Activo")
        self.lbl_ahk_status.setStyleSheet("color: #58a6ff; font-weight: bold;")
        hk_lay.addWidget(self.lbl_ahk_status)

        shortcuts_info = QLabel(
            "• Texto Seleccionado + Clic Izquierdo + Barra Espaciadora: Lectura en voz alta instantánea.\n"
            "• Alt + Barra Espaciadora: Atajo alternativo para leer texto seleccionado.\n"
            "• Clic Izquierdo + S / Alt + S: Guardar selección directamente en MP3.\n"
            "• Escape (Esc): Detener la lectura en cualquier momento.\n"
            "• Clic Izquierdo + Espacio + Rueda del Ratón: Aumentar o reducir la velocidad de lectura al vuelo."
        )
        shortcuts_info.setStyleSheet("color: #c9d1d9; font-size: 11px; line-height: 1.4;")
        hk_lay.addWidget(shortcuts_info)

        btn_reload_ahk = QPushButton("🔄 Reiniciar Atajos Globales")
        btn_reload_ahk.setObjectName("secondaryActionButton")
        btn_reload_ahk.clicked.connect(self.restart_ahk_service)
        hk_lay.addWidget(btn_reload_ahk, alignment=Qt.AlignmentFlag.AlignLeft)

        c_lay.addWidget(hk_box)

        # 3. Preferencias del Sistema e Inicio con Windows
        sys_box = QGroupBox("Opciones del Sistema, Traducción & Arranque")
        s_lay = QVBoxLayout(sys_box)

        # Inicio con Windows
        self.chk_startup = QCheckBox("Iniciar GlobalTTS automáticamente al encender la PC (mostrar la ventana)")
        self.chk_startup.setChecked(is_startup_enabled() or bool(self.config.get("start_with_windows", True)))
        s_lay.addWidget(self.chk_startup)

        # Traducción automática de inglés
        self.chk_translate = QCheckBox("Traducir automáticamente al español si el texto seleccionado está en inglés")
        self.chk_translate.setChecked(bool(self.config.get("auto_translate_en", True)))
        s_lay.addWidget(self.chk_translate)

        # Directorio de guardado
        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Carpeta de Audios Rápidos:"))
        self.dir_edit = QLineEdit(self.config.get("save_directory", str(Path.home() / "Downloads" / "TTS_Audios")))
        dir_row.addWidget(self.dir_edit, stretch=1)
        btn_browse_dir = QPushButton("📂 Explorar")
        btn_browse_dir.setObjectName("secondaryActionButton")
        btn_browse_dir.clicked.connect(self.browse_save_dir)
        dir_row.addWidget(btn_browse_dir)
        s_lay.addLayout(dir_row)

        c_lay.addWidget(sys_box)

        # 4. Firma Institucional y Botón Guardar
        footer_box = QHBoxLayout()
        lbl_sig = QLabel("Firma en Metadatos: HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®")
        lbl_sig.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: 600;")
        footer_box.addWidget(lbl_sig)

        btn_save_cfg = QPushButton("💾 Guardar Configuración")
        btn_save_cfg.setObjectName("primaryButton")
        btn_save_cfg.clicked.connect(self.save_all_settings)
        footer_box.addWidget(btn_save_cfg)
        c_lay.addLayout(footer_box)

        layout.addWidget(config_box)

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

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
        # Estimación promedio: ~150 palabras por minuto
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

    def paste_clipboard(self):
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            self.text_edit.setText(text)

    def play_text(self):
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Texto Vacío", "Por favor escribe o pega texto para escuchar.")
            return

        self.stop_text()

        voice_key = self.voice_combo.currentData() or "es_MX-claude-high"
        speed = self.speed_slider.value() / 10.0

        self.btn_play.setEnabled(False)
        self.btn_play.setText("🔊 Reproduciendo...")
        self.lbl_status.setText("● Reproduciendo en voz alta...")
        self.lbl_status.setStyleSheet("color: #e3b341; font-weight: 600;")

        self.play_worker = TtsPlayWorker(text=text, voice_key=voice_key, speed=speed, volume=1.0)
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
        self.btn_play.setText("▶️ Leer en Voz Alta (Play)")
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

            # Metadatos JSON
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
            "volume": self.config.get("volume", 100),
            "save_directory": self.dir_edit.text().strip(),
            "auto_translate_en": self.chk_translate.isChecked(),
            "enable_escape_to_stop": True,
            "enable_alt_space_fallback": True,
            "enable_save_hotkey": True,
            "start_with_windows": self.chk_startup.isChecked(),
            "firma": "HUMAN AI SYNERGY BY BENNER CASTILLO"
        }

        # Guardar en archivo
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Fallo al guardar config.json: {e}")
            return

        # Configurar inicio con Windows
        set_startup_enabled(self.chk_startup.isChecked())

        QMessageBox.information(
            self,
            "Configuración Guardada",
            "✅ La configuración se ha guardado correctamente.\n\n"
            f"Voz: {cfg['voice']}\n"
            f"Velocidad: {cfg['speed_factor']}x\n"
            f"Inicio con Windows: {'Activado' if cfg['start_with_windows'] else 'Desactivado'}\n"
            f"Firma: HUMAN AI SYNERGY BY BENNER CASTILLO"
        )
