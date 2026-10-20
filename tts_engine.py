"""Motor de ejecución TTS local para atajos de teclado y lectura rápida en GlobalTTS.

100% offline, costo cero y ultra-baja latencia utilizando Piper VITS local (Sherpa-ONNX).
Soporta atajos de AutoHotkey v2:
- Texto seleccionado + Click Izq + Barra Espaciadora = Reproducir en vivo
- Alt + Barra Espaciadora = Reproducir en vivo (alternativo)
- Click Izq + S / Alt + S = Guardar como MP3 con metadatos y carátula
- Esc = Detener reproducción inmediatamente
- Rueda del ratón = Ajuste de velocidad al vuelo
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import sounddevice as sd
import soundfile as sf
import winsound
import win32clipboard
import win32con

from src.ai.piper_engine import PiperTtsEngine, list_available_piper_voices
from src.core.language import detect_language
from src.core.text_clean import clean_text_for_tts, make_filename_slug
from src.markup.style import Style

CONFIG_FILE = PROJECT_ROOT / "config.json"
LOG_FILE = PROJECT_ROOT / "global_tts.log"
LAST_SPEECH_FILE = PROJECT_ROOT / "last_speech.txt"

DEFAULT_CONFIG = {
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


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg.update(data)
                # Migración de voces viejas de edge-tts si estuvieran guardadas
                if "Neural" in str(cfg.get("voice", "")):
                    cfg["voice"] = "es_MX-claude-high"
        except Exception:
            pass
    return cfg


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        log(f"[WARN] Error guardando config.json: {e}")


def get_clipboard_text() -> str:
    for _ in range(12):
        try:
            win32clipboard.OpenClipboard()
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                if data and data.strip():
                    return data.strip()
            win32clipboard.CloseClipboard()
        except Exception:
            pass
        time.sleep(0.02)
    return ""


def maybe_translate_to_spanish(text: str) -> str:
    """Si el texto está en inglés y el usuario tiene habilitada traducción, traduce localmente o con fallback."""
    lang = detect_language(text)
    if lang != "en":
        return text

    # Intentar traducción con Mistral NeMo local (Ollama)
    try:
        from src.ai.nemo_enhancer import MistralNeMoEnhancer
        enhancer = MistralNeMoEnhancer()
        if enhancer.is_available():
            log("[AI] Traduciendo de inglés a español con Mistral NeMo local...")
            sys_inst = (
                "Eres un traductor experto de inglés a español neutro latinoamericano. "
                "Traduce únicamente el texto dado sin añadir comentarios, explicaciones ni formatos adicionales."
            )
            translated = enhancer._call_ollama(prompt=f"Translate to Spanish:\n\n{text}", system_prompt=sys_inst)
            if translated:
                log(f"[AI] Traducción completada ({len(translated)} chars).")
                return translated
    except Exception:
        pass

    # Si no hay Ollama disponible, intentar Gemini si está configurado en .env
    env_path = Path.home() / ".gemini" / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(str(env_path))
            api_key = os.environ.get("GEMINI_API_KEY")
            if api_key:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=api_key)
                resp = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"Translate this text to Spanish:\n\n{text}",
                    config=types.GenerateContentConfig(
                        system_instruction="Translate the text to fluent Spanish. Return only the translation."
                    )
                )
                if resp.text:
                    return resp.text.strip()
        except Exception:
            pass

    return text


def synthesize_audio(text: str, voice_key: str, speed_factor: float = 1.0) -> tuple[np.ndarray, int]:
    """Sintetiza texto usando Piper TTS local."""
    engine = PiperTtsEngine(voice_key=voice_key)
    style = Style(speed=speed_factor)
    samples = engine.synthesize(text, style=style)
    return samples, engine.sample_rate


def do_play(text: str, cfg: dict):
    try:
        voice = cfg.get("voice", "es_MX-claude-high")
        speed = float(cfg.get("speed_factor", 1.0))
        vol_pct = float(cfg.get("volume", 100)) / 100.0

        log(f"[PLAY] Sintetizando con Piper ({voice}, speed={speed}x, {len(text)} chars)...")
        samples, sr = synthesize_audio(text, voice_key=voice, speed_factor=speed)

        if vol_pct != 1.0:
            samples = samples * vol_pct

        sd.play(samples, sr)
        sd.wait()
        log("[PLAY-DONE] Reproducción completa.")
    except Exception as e:
        log(f"[ERROR-PLAY] {e}")


def do_save(text: str, cfg: dict):
    try:
        target_dir = Path(cfg.get("save_directory", Path.home() / "Downloads" / "TTS_Audios"))
        target_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
        fecha_str = now.strftime("%Y-%m-%d")
        hora_str = now.strftime("%H:%M:%S")

        slug = make_filename_slug(text, max_words=5, max_len=40)
        filename_mp3 = f"TTS_{timestamp}_{slug}.mp3"
        filepath_mp3 = target_dir / filename_mp3
        temp_wav = target_dir / f"temp_{timestamp}_{slug}.wav"

        voice = cfg.get("voice", "es_MX-claude-high")
        speed = float(cfg.get("speed_factor", 1.0))

        log(f"[SAVE] Sintetizando y guardando MP3: {filename_mp3} ({len(text)} chars)...")
        samples, sr = synthesize_audio(text, voice_key=voice, speed_factor=speed)

        # Guardar temporal WAV
        sf.write(str(temp_wav), samples, sr)

        dur_s = len(samples) / float(sr)
        dur_str = time.strftime("%H:%M:%S", time.gmtime(dur_s))

        # Convertir a MP3 con ffmpeg inyectando metadatos obligatorios
        cflags = 0x08000000 if sys.platform == "win32" else 0
        cmd = [
            "ffmpeg", "-y",
            "-i", str(temp_wav),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-codec:a", "libmp3lame",
            "-b:a", "256k",
            "-metadata", "artist=HUMAN AI SYNERGY BY BENNER CASTILLO",
            "-metadata", "album_artist=HUMAN AI SYNERGY BY BENNER CASTILLO",
            "-metadata", f"title={slug.replace('_', ' ').title()}",
            "-metadata", f"date={fecha_str}",
            "-metadata", f"comment=Firma: HUMAN AI SYNERGY BY BENNER CASTILLO | Fecha: {fecha_str} {hora_str} | Duración: {dur_str}",
            "-metadata", "copyright=HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®",
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

        # Guardar metadatos JSON complementarios según ESTRUCTURA.md
        meta_json_path = target_dir / f"TTS_{timestamp}_{slug}_metadata.json"
        meta_dict = {
            "firma": "HUMAN AI SYNERGY BY BENNER CASTILLO",
            "fecha": fecha_str,
            "hora": hora_str,
            "tiempo_duracion_segundos": round(dur_s, 2),
            "tiempo_duracion_formato": dur_str,
            "tamano_bytes": tamano_bytes,
            "tamano_mb": tamano_mb,
            "modelo_tts": f"Piper ({voice})",
            "velocidad": speed,
            "texto_origen": text[:200] + ("..." if len(text) > 200 else "")
        }
        with open(meta_json_path, "w", encoding="utf-8") as f:
            json.dump(meta_dict, f, indent=2, ensure_ascii=False)

        log(f"[SAVE-SUCCESS] Guardado: {filepath_mp3} ({tamano_mb}, {dur_str})")
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception as e:
        log(f"[ERROR-SAVE] {e}")
        winsound.MessageBeep(winsound.MB_ICONHAND)


def stop_audio_processes():
    """Detiene cualquier audio en reproducción activa."""
    try:
        sd.stop()
    except Exception:
        pass

    import psutil
    current_pid = os.getpid()
    killed = False
    for p in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = p.info.get('name', '').lower()
            cmdline = p.info.get('cmdline')
            if p.info['pid'] != current_pid and name in ('python.exe', 'pythonw.exe') and cmdline and 'tts_engine.py' in ' '.join(cmdline):
                # No matarse a sí mismo
                if 'stop' not in ' '.join(cmdline):
                    p.kill()
                    killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    if killed:
        log("[STOP] Procesos de audio anteriores detenidos forzosamente.")
    else:
        log("[STOP] Audio detenido.")


def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "play"

    if mode == "stop":
        stop_audio_processes()
        return

    cfg = load_config()

    if mode in ["speedup", "speeddown"]:
        stop_audio_processes()
        spd = float(cfg.get("speed_factor", 1.0))
        if mode == "speedup":
            spd = min(2.5, round(spd + 0.1, 1))
        else:
            spd = max(0.5, round(spd - 0.1, 1))
        cfg["speed_factor"] = spd
        save_config(cfg)
        winsound.Beep(1200 if mode == "speedup" else 800, 50)
        log(f"[SPEED] Nueva velocidad ajustada a {spd:.1f}x. (Usa el atajo nuevamente para escuchar)")
        return

    # Extraer texto del portapapeles
    text = get_clipboard_text()
    if not text:
        log("[WARN] Portapapeles vacío o sin texto.")
        winsound.Beep(400, 100)
        return

    # Traducción si aplica
    if cfg.get("auto_translate_en", True):
        text = maybe_translate_to_spanish(text)

    # Limpieza de emojis, enlaces y formatos
    cleaned = clean_text_for_tts(text)
    if not cleaned:
        return

    try:
        with open(LAST_SPEECH_FILE, "w", encoding="utf-8") as f:
            f.write(cleaned)
    except Exception:
        pass

    if mode == "save":
        do_save(cleaned, cfg)
    else:
        do_play(cleaned, cfg)


if __name__ == "__main__":
    main()
