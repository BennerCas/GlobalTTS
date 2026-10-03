import os
import sys
import time
import json
import io
import re
from datetime import datetime
import winsound
import win32clipboard
import win32con
import edge_tts
import soundfile as sf
import sounddevice as sd
from dotenv import load_dotenv
from google import genai

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_FILE = os.path.join(BASE_DIR, "global_tts.log")
LOCK_FILE = os.path.join(BASE_DIR, "playback.lock")

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def load_config():
    default_cfg = {
        "voice": "es-ES-AlvaroNeural",
        "alt_voice": "es-MX-DaliaNeural",
        "rate": "+0%",
        "volume": "+0%",
        "save_directory": r"C:\Users\Benner\Downloads\TTS_Audios"
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                default_cfg.update(json.load(f))
        except Exception:
            pass
    return default_cfg

CONFIG = load_config()

EMOJI_MAP = {
    '🎉': 'celebración', '⚠️': 'atención', '✅': 'correcto', '❌': 'error',
    '🔥': 'fuego', '💡': 'idea', '📌': 'nota', '⭐': 'estrella',
    '👍': 'bien', '👎': 'mal', '🚀': 'avance', '💪': 'fuerza', '🎯': 'objetivo',
    '❤️': 'amor', '👀': 'ojo', '💯': 'cien por ciento', '💰': 'dinero'
}

def clean_text_for_tts(text: str) -> str:
    if not text:
        return ""
    for emoji, word in EMOJI_MAP.items():
        text = text.replace(emoji, f" {word} ")
    text = re.sub(r'https?://\S+', 'enlace web', text)
    text = re.sub(r'\$(\d+(?:\.\d+)?)', r'\1 dólares', text)
    text = re.sub(r'€(\d+(?:\.\d+)?)', r'\1 euros', text)
    text = re.sub(r'(\d+)\s*%', r'\1 por ciento', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def make_filename_slug(text: str) -> str:
    clean = re.sub(r'[^\w\s-]', '', text, flags=re.UNICODE)
    words = clean.split()[:5]
    slug = "_".join(words).lower()
    return slug[:40] if slug else "audio"

def get_clipboard_text():
    for _ in range(10):
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

def translate_text_to_spanish(text: str) -> str:
    env_path = r"C:\Users\Benner\.gemini\.env"
    if os.path.exists(env_path):
        load_dotenv(env_path)
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log("[WARN] No se encontró GEMINI_API_KEY en .env, usando texto original.")
        return text

    try:
        log("[AI] Iniciando traducción/adaptación con Gemini...")
        client = genai.Client(api_key=api_key)
        prompt = (
            "Traduce el siguiente texto al español latinoamericano manteniendo el contexto, "
            "la coherencia, la cohesión y la estructura original del mensaje "
            "para que la idea principal quede completamente clara. "
            "Si el texto ya está en español, corrígelo o mejóralo ligeramente si es necesario "
            "para que suene natural al ser leído en voz alta. "
            "Devuelve ÚNICAMENTE el texto resultante, sin explicaciones, ni comillas, ni markdown:\n\n"
            f"{text}"
        )
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        translated = response.text.strip()
        log(f"[AI] Traducción exitosa: {translated[:60]}...")
        return translated
    except Exception as e:
        log(f"[ERROR-AI] Fallo al traducir con Gemini: {e}")
        return text

async def do_save(text: str):
    try:
        target_dir = CONFIG.get("save_directory", r"C:\Users\Benner\Downloads\TTS_Audios")
        os.makedirs(target_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        slug = make_filename_slug(text)
        filename = f"TTS_{timestamp}_{slug}.mp3"
        filepath = os.path.join(target_dir, filename)

        log(f"[SAVE] Generando MP3: {filename} ({len(text)} caracteres)...")
        communicate = edge_tts.Communicate(
            text, CONFIG["voice"], rate=CONFIG.get("rate", "+0%"), volume=CONFIG.get("volume", "+0%")
        )
        await communicate.save(filepath)

        log(f"[SAVE-SUCCESS] Guardado: {filepath}")
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception as e:
        log(f"[ERROR-SAVE] {e}")
        winsound.MessageBeep(winsound.MB_ICONHAND)

async def do_play(text: str):
    try:
        log(f"[PLAY] Sintetizando para reproducir ({len(text)} caracteres)...")
        communicate = edge_tts.Communicate(
            text, CONFIG["voice"], rate=CONFIG.get("rate", "+0%"), volume=CONFIG.get("volume", "+0%")
        )
        audio_buffer = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer += chunk["data"]

        if not audio_buffer:
            return

        data, fs = sf.read(io.BytesIO(audio_buffer))
        sd.play(data, fs)
        sd.wait()
        log("[PLAY-DONE] Reproducción completa.")
    except Exception as e:
        log(f"[ERROR-PLAY] {e}")

def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "play"

    if mode == "stop":
        import psutil
        current_pid = os.getpid()
        killed_any = False
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = p.info.get('cmdline')
                if p.info['pid'] != current_pid and cmdline and 'tts_engine.py' in ' '.join(cmdline):
                    p.kill()
                    killed_any = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        try:
            sd.stop()
        except Exception:
            pass
            
        if killed_any:
            log("[STOP] Procesos de audio anteriores detenidos forzosamente.")
        else:
            log("[STOP] Audio detenido (sd.stop).")
        return

    text = get_clipboard_text()
    if not text:
        log("[WARN] Portapapeles vacío o sin texto.")
        winsound.Beep(400, 100)
        return

    # 1. Traducir el texto al español manteniendo coherencia y estructura
    translated_text = translate_text_to_spanish(text)

    # 2. Limpiar texto para mejorar TTS
    cleaned = clean_text_for_tts(translated_text)
    if not cleaned:
        return

    import asyncio
    if mode == "save":
        asyncio.run(do_save(cleaned))
    else:
        asyncio.run(do_play(cleaned))

if __name__ == "__main__":
    main()
