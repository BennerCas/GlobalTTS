"""Spike: tamaño por carpeta/variante de repos de Hugging Face candidatos."""
import json
import sys
import urllib.request
from collections import defaultdict

REPOS = sys.argv[1:] or ["wavekat/Qwen3-TTS-0.6B-Base-ONNX", "onnx-community/chatterbox-multilingual-ONNX"]

for repo in REPOS:
    url = f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true"
    with urllib.request.urlopen(url, timeout=30) as r:
        files = json.load(r)
    groups: dict[str, int] = defaultdict(int)
    for f in files:
        if f.get("type") != "file":
            continue
        size = f.get("lfs", {}).get("size", f.get("size", 0))
        top = f["path"].split("/")[0] if "/" in f["path"] else "(raiz)"
        groups[top] += size
    print(f"\n## {repo}  total={sum(groups.values()) / 1e9:.2f} GB")
    for k, v in sorted(groups.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<28} {v / 1e6:9.1f} MB")
    if "chatterbox" in repo:
        for f in files:
            if f["path"].endswith(".onnx") or f["path"].endswith(".onnx_data"):
                print("   ", f["path"], round(f.get("lfs", {}).get("size", f.get("size", 0)) / 1e6, 1), "MB")
