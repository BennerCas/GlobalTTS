@echo off
title Detener Global TTS
taskkill /F /IM AutoHotkey64.exe 2>nul
taskkill /F /FI "WINDOWTITLE eq Global TTS*" 2>nul
wmic process where "commandline like '%%tts_engine.py%%'" call terminate >nul 2>&1
wmic process where "commandline like '%%global_tts%%'" call terminate >nul 2>&1
echo Global TTS detenido.
timeout /t 2 >nul
exit
