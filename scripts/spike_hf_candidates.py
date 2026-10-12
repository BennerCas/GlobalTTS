"""Spike: consulta la API de Hugging Face y lista modelos TTS candidatos (id, descargas, licencia, tamaño)."""
import json
import sys
import urllib.parse
import urllib.request

QUERIES = [
    "qwen3-tts onnx",
    "qwen3-tts gguf",
    "chatterbox multilingual",
    "fish-speech s1-mini",
    "openaudio s1",
    "f5-tts spanish",
    "xtts-v2 onnx",
    "orpheus spanish",
    "kyutai tts",
]


def fetch(q: str):
    url = "https://huggingface.co/api/models?" + urllib.parse.urlencode(
        {"search": q, "sort": "downloads", "limit": 6, "full": "false"}
    )
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


for q in QUERIES:
    print(f"\n## {q}")
    try:
        for m in fetch(q):
            lic = next((t.split(":", 1)[1] for t in m.get("tags", []) if t.startswith("license:")), "?")
            tags = [t for t in m.get("tags", []) if t in ("onnx", "gguf", "voice-cloning", "es")]
            print(f"- {m['id']} | dl={m.get('downloads')} | lic={lic} | {','.join(tags)}")
    except Exception as exc:  # noqa: BLE001 - spike, se reporta y se continúa
        print("  error:", exc, file=sys.stderr)
