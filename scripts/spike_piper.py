"""Spike: sintetiza con una voz Piper local (sherpa-onnx) y mide el factor de tiempo real (RTF)."""
import sys
import time
from pathlib import Path

import sherpa_onnx
import soundfile as sf

VAULT = Path(r"C:\antigravityAS\Modelos -ai-brains")
VOICES = {
    "mx_claude": VAULT / "vits-piper-es_MX-claude-high",
    "es_sharvard": VAULT / "vits-piper-es_ES-sharvard-medium",
}
TEXT = (
    "En un lugar de la Mancha, de cuyo nombre no quiero acordarme, "
    "no ha mucho tiempo que vivía un hidalgo de los de lanza en astillero."
)


def build(voice_dir: Path) -> sherpa_onnx.OfflineTts:
    onnx = next(voice_dir.glob("*.onnx"))
    vits = sherpa_onnx.OfflineTtsVitsModelConfig(
        model=str(onnx), tokens=str(voice_dir / "tokens.txt"), data_dir=str(voice_dir / "espeak-ng-data")
    )
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=8, provider="cpu")
    )
    return sherpa_onnx.OfflineTts(cfg)


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, vdir in VOICES.items():
        tts = build(vdir)
        for speed in (1.0, 0.85):
            t0 = time.perf_counter()
            audio = tts.generate(TEXT, sid=0, speed=speed)
            dt = time.perf_counter() - t0
            dur = len(audio.samples) / audio.sample_rate
            path = out / f"spike_piper_{name}_speed{speed}.wav"
            sf.write(path, audio.samples, audio.sample_rate)
            print(f"{name} speed={speed} sr={audio.sample_rate} dur={dur:.2f}s gen={dt:.2f}s RTF={dt / dur:.3f} -> {path.name}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scratch")
