import time
from pynput import keyboard

with open(r"C:\antigravityAS\GlobalTTS\test_hook.txt", "w") as f:
    f.write("Started\n")

def on_press(key):
    with open(r"C:\antigravityAS\GlobalTTS\test_hook.txt", "a") as f:
        f.write(f"Key: {key}\n")

with keyboard.Listener(on_press=on_press) as l:
    time.sleep(5)
