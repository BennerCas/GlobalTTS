"""Caché Inteligente de Fonemas y Segmentos de Audio (SHA-256 Content-Addressable Cache).

Almacena en disco los vectores acústicos ya sintetizados indexados por el hash SHA-256
de `(voice_key, sample_rate, speed, gain_db, text)`. Permite que re-generaciones parciales,
cuñas radiales repetidas, estribillos o correcciones de capítulos se ensamblen de forma
instantánea (latencia ~0.2ms) sin recalcular inferencia ONNX.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("globaltts.audio_cache")

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "tts_segments"


@dataclass
class CacheStats:
    hits: int
    misses: int
    files_count: int
    size_mb: float

    @property
    def hit_rate_percent(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100.0) if total > 0 else 0.0


class AudioSegmentCache:
    """Caché en disco thread-safe para arrays acústicos numpy float32."""

    def __init__(self, cache_dir: Optional[Path] = None, enabled: bool = True, max_entries: int = 5000):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.enabled = enabled
        self.max_entries = max_entries
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()
        if self.enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_key(voice_key: str, sample_rate: int, speed: float, gain_db: float, text: str) -> str:
        payload = f"{voice_key}|{sample_rate}|{speed:.3f}|{gain_db:.2f}|{text.strip()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _path_for_key(self, key: str) -> Path:
        return self.cache_dir / f"{key}.npy"

    def get(self, voice_key: str, sample_rate: int, speed: float, gain_db: float, text: str) -> Optional[np.ndarray]:
        if not self.enabled or not text.strip():
            return None
        key = self.compute_key(voice_key, sample_rate, speed, gain_db, text)
        path = self._path_for_key(key)
        if path.exists():
            try:
                arr = np.load(str(path), allow_pickle=False)
                with self._lock:
                    self._hits += 1
                return arr.astype(np.float32, copy=False)
            except Exception as exc:
                logger.debug("Entrada de caché corrupta %s: %s", path.name, exc)
        with self._lock:
            self._misses += 1
        return None

    def put(self, voice_key: str, sample_rate: int, speed: float, gain_db: float, text: str, samples: np.ndarray) -> None:
        if not self.enabled or not text.strip() or len(samples) == 0:
            return
        key = self.compute_key(voice_key, sample_rate, speed, gain_db, text)
        path = self._path_for_key(key)
        if path.exists():
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            np.save(str(path), samples.astype(np.float32, copy=False), allow_pickle=False)
        except Exception as exc:
            logger.debug("No se pudo guardar segmento en caché: %s", exc)

    def clear(self) -> int:
        """Elimina todos los segmentos en caché y retorna el número de archivos borrados."""
        removed = 0
        if self.cache_dir.exists():
            for f in self.cache_dir.glob("*.npy"):
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        with self._lock:
            self._hits = 0
            self._misses = 0
        return removed

    def stats(self) -> CacheStats:
        files = list(self.cache_dir.glob("*.npy")) if self.cache_dir.exists() else []
        total_bytes = sum(f.stat().st_size for f in files if f.exists())
        with self._lock:
            hits, misses = self._hits, self._misses
        return CacheStats(
            hits=hits,
            misses=misses,
            files_count=len(files),
            size_mb=round(total_bytes / (1024 * 1024), 2),
        )


# Instancia global compartida por PiperTtsEngine y la UI
GLOBAL_AUDIO_CACHE = AudioSegmentCache()
