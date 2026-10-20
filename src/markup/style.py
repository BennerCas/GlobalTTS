"""Estilo de voz resuelto para un fragmento de texto.

Un mismo estilo se traduce según el motor:
- Motores simples (Piper): ``speed``, ``gain_db`` y ``voice`` (emulación de prosodia).
- Motores expresivos (CosyVoice3): ``instruct`` en lenguaje natural.
"""
from __future__ import annotations

from dataclasses import dataclass

MIN_SPEED, MAX_SPEED = 0.5, 2.0


@dataclass(frozen=True)
class Style:
    speed: float = 1.0  # multiplicador: >1 más rápido, <1 más lento
    gain_db: float = 0.0
    voice: str | None = None
    instruct: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "speed", max(MIN_SPEED, min(MAX_SPEED, self.speed)))

    @property
    def is_default(self) -> bool:
        return self == Style()

    @property
    def instruct_text(self) -> str:
        """Instrucciones unidas en una sola frase para motores expresivos."""
        return ", ".join(self.instruct)
