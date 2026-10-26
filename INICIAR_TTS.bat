@echo off
title Iniciar Global TTS
cd /d "%~dp0"
set OLIVE_GPU_MEMORY_LIMIT=25GB
set OLIVE_CPU_THREADS=12
set OLLAMA_IGPU_ENABLE=1
set HSA_OVERRIDE_GFX_VERSION=11.0.0

taskkill /F /IM AutoHotkey64.exe 2>nul
taskkill /F /FI "WINDOWTITLE eq GlobalTTS*" 2>nul

:: 1. Iniciar atajos globales con AutoHotkey v2
start "" "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe" "%~dp0global_tts.ahk"

:: 2. Iniciar aplicacion y abrir la ventana principal
start "" "C:\Users\Benner\miniconda3\pythonw.exe" "%~dp0src\ui\tray_app.py"

echo Global TTS y Ventana Principal iniciados correctamente.
ping -n 2 127.0.0.1 >nul
exit
