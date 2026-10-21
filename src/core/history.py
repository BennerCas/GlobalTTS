"""Gestor de Historial Infinito de Lecturas Rápidas para GlobalTTS.

Almacena de forma persistente cada generación de audio realizada en el lector rápido,
guardando el archivo de audio reproducible, el texto íntegro, fecha, hora, duración,
voz utilizada y la firma 'HUMAN AI SYNERGY BY BENNER CASTILLO'.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf

from src.core.text_clean import make_filename_slug

logger = logging.getLogger("globaltts.history")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BIBLIOTECA_DIR = PROJECT_ROOT / "biblioteca"
HISTORIAL_DIR = BIBLIOTECA_DIR / "historial_lecturas"
HISTORIAL_JSON = HISTORIAL_DIR / "historial.json"
FIRMA_DEFAULT = "HUMAN AI SYNERGY BY BENNER CASTILLO"


class HistoryManager:
    """Administra el almacenamiento y consulta del historial infinito de lecturas rápidas."""

    def __init__(self, history_dir: Optional[Path] = None):
        self.history_dir = history_dir or HISTORIAL_DIR
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.json_file = self.history_dir / "historial.json"
        if not self.json_file.exists():
            self._save_records([])

    def _load_records(self) -> list[dict[str, Any]]:
        if not self.json_file.exists():
            return []
        try:
            with open(self.json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning("Error leyendo %s: %s", self.json_file, e)
            return []

    def _save_records(self, records: list[dict[str, Any]]) -> None:
        try:
            with open(self.json_file, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Error guardando historial en %s: %s", self.json_file, e)

    def add_entry(
        self,
        text: str,
        voice_key: str,
        voice_name: str,
        samples: np.ndarray,
        sample_rate: int,
        firma: str = FIRMA_DEFAULT,
    ) -> dict[str, Any]:
        """Guarda el archivo de audio y añade una nueva entrada al historial infinito."""
        now = datetime.now()
        timestamp_id = now.strftime("%Y%m%d_%H%M%S_%f")[:19]
        fecha_str = now.strftime("%Y-%m-%d")
        hora_str = now.strftime("%H:%M:%S")

        slug = make_filename_slug(text[:40], max_words=4, max_len=30)
        audio_filename = f"{timestamp_id}_{slug}.wav"
        audio_path = self.history_dir / audio_filename

        # Guardar audio físico
        try:
            sf.write(str(audio_path), samples, sample_rate, subtype="PCM_16")
        except Exception as e:
            logger.error("No se pudo escribir el archivo de audio del historial: %s", e)

        duration_s = round(len(samples) / sample_rate, 2) if sample_rate > 0 else 0.0
        dur_fmt = time.strftime("%M:%S", time.gmtime(duration_s))

        entry: dict[str, Any] = {
            "id": timestamp_id,
            "fecha": fecha_str,
            "hora": hora_str,
            "fecha_completa": f"{fecha_str} {hora_str}",
            "text": text,
            "snippet": text[:90] + ("..." if len(text) > 90 else ""),
            "voice_key": voice_key,
            "voice_name": voice_name,
            "sample_rate": sample_rate,
            "duration_seconds": duration_s,
            "duracion_formato": dur_fmt,
            "file_path": str(audio_path.resolve()),
            "file_size_bytes": audio_path.stat().st_size if audio_path.exists() else 0,
            "firma": firma,
        }

        records = self._load_records()
        records.insert(0, entry)  # El más reciente primero
        self._save_records(records)
        return entry

    def list_entries(self) -> list[dict[str, Any]]:
        """Devuelve todas las lecturas guardadas ordenadas de más reciente a más antigua."""
        records = self._load_records()
        # Verificar que el archivo de audio todavía exista
        valid = []
        for r in records:
            p = Path(r.get("file_path", ""))
            if p.exists():
                valid.append(r)
        return valid

    def delete_entry(self, entry_id: str) -> None:
        """Elimina una lectura específica y su archivo de audio."""
        records = self._load_records()
        updated = []
        for r in records:
            if r.get("id") == entry_id:
                p = Path(r.get("file_path", ""))
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
            else:
                updated.append(r)
        self._save_records(updated)

    def clear_history(self) -> None:
        """Limpia todo el historial y elimina los audios correspondientes."""
        records = self._load_records()
        for r in records:
            p = Path(r.get("file_path", ""))
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass
        self._save_records([])
