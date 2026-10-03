@echo off
title Iniciar Global TTS
cd /d "%~dp0"
taskkill /F /FI "WINDOWTITLE eq Global TTS*" 2>nul
start "" "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe" "%~dp0global_tts.ahk"
echo Global TTS iniciado correctamente con AutoHotkey v2 + Python.
timeout /t 2 >nul
exit
