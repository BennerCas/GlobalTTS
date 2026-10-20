@echo off
title Detener Global TTS
taskkill /F /IM AutoHotkey64.exe 2>nul
taskkill /F /FI "WINDOWTITLE eq Global TTS*" 2>nul
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*tts_engine.py*' -or $_.CommandLine -like '*global_tts.py*' -or $_.CommandLine -like '*tray_app.py*' } | Invoke-CimMethod -MethodName Terminate | Out-Null"
echo Global TTS detenido.
timeout /t 2 >nul
exit
