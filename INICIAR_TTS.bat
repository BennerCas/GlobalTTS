@echo off
title Iniciar Global TTS
cd /d "%~dp0"
taskkill /F /FI "WINDOWTITLE eq Global TTS*" 2>nul

:: 1. Iniciar atajos globales con AutoHotkey v2
start "" "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe" "%~dp0global_tts.ahk"

:: 2. Iniciar ícono en la bandeja del sistema (System Tray) para audiolibros y video karaoke
start "" "C:\Users\Benner\miniconda3\pythonw.exe" "%~dp0src\ui\tray_app.py"

echo Global TTS y Bandeja de Audiolibros iniciados correctamente.
timeout /t 2 >nul
exit
