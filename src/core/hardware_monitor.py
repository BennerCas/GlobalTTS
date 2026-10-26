"""Monitor de Telemetría de Hardware DirectML y Olive en Tiempo Real.

Proporciona métricas en vivo de uso de CPU, RAM, estado de aceleración DirectML/ROCm,
límites configurados de Olive (`25 GB VRAM` / `12 CPU Threads`) y tasa de aciertos
de la caché acústica para la barra de estado de GlobalTTS.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import psutil

from src.core.audio_cache import GLOBAL_AUDIO_CACHE

# Garantizar que las variables maestras de hardware estén configuradas según GEMINI.md
os.environ["OLIVE_GPU_MEMORY_LIMIT"] = "25GB"
os.environ["OLIVE_CPU_THREADS"] = "12"
os.environ["OLLAMA_IGPU_ENABLE"] = "1"
os.environ["HSA_OVERRIDE_GFX_VERSION"] = "11.0.0"


@dataclass(frozen=True)
class HardwareTelemetry:
    cpu_percent: float
    ram_used_gb: float
    ram_total_gb: float
    ram_percent: float
    vram_limit: str
    cpu_threads: int
    dml_available: bool
    rocm_igpu_enabled: bool
    cache_hits: int
    cache_hit_rate: float

    def format_badge_text(self) -> str:
        backend = "DirectML+ROCm" if self.dml_available else "ONNX-CPU(12T)"
        return (
            f"[ HW: {backend} | CPU: {self.cpu_percent:04.1f}% | "
            f"RAM: {self.ram_used_gb:.1f}/{self.ram_total_gb:.0f}GB | "
            f"VRAM Cap: {self.vram_limit} | Cache: {self.cache_hit_rate:.0f}% ({self.cache_hits}) ]"
        )


class HardwareMonitor:
    """Recolector ligero de telemetría del sistema y aceleradores IA."""

    def __init__(self) -> None:
        self._dml_available = self._check_dml_provider()
        # Primera llamada a cpu_percent sin bloqueo para inicializar el contador
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    @staticmethod
    def _check_dml_provider() -> bool:
        try:
            import onnxruntime as ort
            providers = ort.get_available_providers()
            return "DmlExecutionProvider" in providers or "ROCMExecutionProvider" in providers or "CUDAExecutionProvider" in providers
        except Exception:
            return False

    def snapshot(self) -> HardwareTelemetry:
        try:
            cpu_pct = float(psutil.cpu_percent(interval=None))
            vm = psutil.virtual_memory()
            ram_used = round(vm.used / (1024 ** 3), 2)
            ram_total = round(vm.total / (1024 ** 3), 2)
            ram_pct = float(vm.percent)
        except Exception:
            cpu_pct, ram_used, ram_total, ram_pct = 0.0, 0.0, 32.0, 0.0

        vram_limit = os.environ.get("OLIVE_GPU_MEMORY_LIMIT", "25GB")
        try:
            threads = int(os.environ.get("OLIVE_CPU_THREADS", "12"))
        except ValueError:
            threads = 12

        rocm_flag = os.environ.get("OLLAMA_IGPU_ENABLE", "0") == "1"
        c_stats = GLOBAL_AUDIO_CACHE.stats()

        return HardwareTelemetry(
            cpu_percent=cpu_pct,
            ram_used_gb=ram_used,
            ram_total_gb=ram_total,
            ram_percent=ram_pct,
            vram_limit=vram_limit,
            cpu_threads=threads,
            dml_available=self._dml_available,
            rocm_igpu_enabled=rocm_flag,
            cache_hits=c_stats.hits,
            cache_hit_rate=c_stats.hit_rate_percent,
        )
