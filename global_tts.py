import os
import sys
import time
import json
import io
import re
import ctypes
import threading
import asyncio
from datetime import datetime
import winsound
from pynput import keyboard
import win32clipboard
import win32con
import edge_tts
import soundfile as sf
import sounddevice as sd
from dotenv import load_dotenv
from google import genai

# Configuración y Rutas
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_FILE = os.path.join(BASE_DIR, "global_tts.log")

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
        "save_directory": r"C:\Users\Benner\Downloads\TTS_Audios",
        "enable_escape_to_stop": True,
        "enable_alt_space_fallback": True,
        "enable_save_hotkey": True
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                default_cfg.update(json.load(f))
        except Exception as e:
            log(f"Error cargando config: {e}")
    return default_cfg

CONFIG = load_config()

# Preprocesamiento de texto
EMOJI_MAP = {
    '🎉': 'celebración', '⚠️': 'atención', '✅': 'correcto', '❌': 'error',
    '🔥': 'fuego', '💡': 'idea', '📌': 'nota', '⭐': 'estrella',
    '👍': 'bien', '👎': 'mal', '🚀': 'avance', '💪': 'fuerza', '🎯': 'objetivo',
    '❤️': 'amor', '👀': 'ojo', '💯': 'cien por ciento', '💰': 'dinero'
}

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
            "Traduce el siguiente texto al español manteniendo el contexto, "
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

# Audio Control
is_speaking = False

def stop_speech():
    global is_speaking
    try:
        sd.stop()
    except Exception:
        pass
    is_speaking = False

async def synthesize_and_play(text: str, voice: str, rate: str, volume: str):
    global is_speaking
    try:
        stop_speech()
        is_speaking = True
        log(f"[PLAY] Sintetizando {len(text)} caracteres con {voice}...")
        
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
        audio_buffer = b""
        async for chunk in communicate.stream():
            if not is_speaking:
                log("[PLAY] Cancelado por el usuario.")
                return
            if chunk["type"] == "audio":
                audio_buffer += chunk["data"]

        if not audio_buffer or not is_speaking:
            return

        data, fs = sf.read(io.BytesIO(audio_buffer))
        if is_speaking:
            sd.play(data, fs)
            log(f"[PLAY] Reproduciendo audio ({round(len(data)/fs, 1)}s)...")
            while sd.get_stream() and sd.get_stream().active and is_speaking:
                await asyncio.sleep(0.05)
            log("[PLAY] Reproducción finalizada.")
    except Exception as e:
        log(f"[ERROR-PLAY] {e}")
    finally:
        is_speaking = False

async def synthesize_and_save(text: str, voice: str, rate: str, volume: str):
    try:
        target_dir = CONFIG.get("save_directory", r"C:\Users\Benner\Downloads\TTS_Audios")
        os.makedirs(target_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        slug = make_filename_slug(text)
        filename = f"TTS_{timestamp}_{slug}.mp3"
        filepath = os.path.join(target_dir, filename)

        log(f"[SAVE] Generando archivo MP3: {filename}...")
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume)
        await communicate.save(filepath)

        log(f"[SAVE-SUCCESS] Archivo guardado en: {filepath}")
        # Campanita de confirmación
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception as e:
        log(f"[ERROR-SAVE] {e}")
        try:
            winsound.Beep(400, 200)
        except Exception:
            pass

def run_tts_worker(text: str, mode: str = "play"):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if mode == "save":
            loop.run_until_complete(
                synthesize_and_save(text, CONFIG["voice"], CONFIG["rate"], CONFIG["volume"])
            )
        else:
            loop.run_until_complete(
                synthesize_and_play(text, CONFIG["voice"], CONFIG["rate"], CONFIG["volume"])
            )
    finally:
        loop.close()

# Captura de Portapapeles Robusta en Windows
VK_CONTROL = 0x11
VK_C = 0x43
VK_MENU = 0x12     # Alt
VK_SHIFT = 0x10
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
user32 = ctypes.windll.user32

def clear_clipboard():
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.CloseClipboard()
            return
        except Exception:
            time.sleep(0.01)

def get_clipboard_text():
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
        time.sleep(0.025)
    return ""

def simulate_copy_clean():
    # 1. IMPORTANTE: Liberar ratón y modificadores para que la aplicación
    # procese la selección y acepte Ctrl+C sin 'Alt' de por medio
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.04)

    # 2. Enviar Ctrl + C limpio
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

def trigger_action(mode: str = "play"):
    def _worker():
        log(f"[ACTION] Atajo detectado para modo: {mode.upper()}")
        # Sonido sutil inmediato para confirmar que el atajo fue recibido
        try:
            winsound.Beep(1000, 40)
        except Exception:
            pass

        clear_clipboard()
        simulate_copy_clean()

        text = get_clipboard_text()
        if not text:
            log("[WARN] No se detectó texto seleccionado en el portapapeles.")
            try:
                winsound.Beep(450, 80)
            except Exception:
                pass
            return

        log(f"[INFO] Texto capturado ({len(text)} chars): {text[:60]}...")
        
        translated_text = translate_text_to_spanish(text)
        
        cleaned = clean_text_for_tts(translated_text)
        if cleaned:
            threading.Thread(target=run_tts_worker, args=(cleaned, mode), daemon=True).start()

    threading.Thread(target=_worker, daemon=True).start()

# Filtro de Eventos de Teclado Win32
def win32_event_filter(msg, data):
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    VK_SPACE = 0x20
    VK_S = 0x53        # 'S'
    VK_ESCAPE = 0x1B
    VK_LBUTTON = 0x01
    VK_MENU = 0x12      # Alt

    if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
        # 1. ESCAPE: Detener reproducción si está hablando
        if data.vkCode == VK_ESCAPE and CONFIG.get("enable_escape_to_stop", True):
            if is_speaking:
                stop_speech()
                log("[ACTION] Lectura detenida con Escape.")
                return False

        is_lbutton_down = bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
        is_alt_down = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)

        # 2. ESPACIO -> Modo Reproducir / Escuchar
        if data.vkCode == VK_SPACE:
            if is_lbutton_down or (is_alt_down and CONFIG.get("enable_alt_space_fallback", True)):
                trigger_action(mode="play")
                return False  # Suprimir espacio para no alterar la pantalla

        # 3. LETRA 'S' -> Modo Guardar / Descargar MP3
        if data.vkCode == VK_S and CONFIG.get("enable_save_hotkey", True):
            if is_lbutton_down or is_alt_down:
                trigger_action(mode="save")
                return False  # Suprimir 'S' para no escribir la letra

    return True

def main():
    log("==================================================")
    log("      Global TTS Activo (Antigravity Service)     ")
    log("==================================================")
    log(f"Destino MP3     : {CONFIG.get('save_directory')}")
    log(f"Voz configurada : {CONFIG.get('voice')}")
    log("Atajos:")
    log(" - Escuchar: Click Izq + Espacio  |  Alt + Espacio")
    log(" - Guardar : Click Izq + S        |  Alt + S")
    log(" - Detener : Escape (Esc)")
    log("==================================================")

    with keyboard.Listener(win32_event_filter=win32_event_filter) as listener:
        listener.join()

if __name__ == "__main__":
    main()
