#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; Global TTS - Antigravity Listener (AutoHotkey v2)
; ============================================================

PythonExe := "C:\Users\Benner\miniconda3\pythonw.exe"
EngineScript := "C:\antigravityAS\GlobalTTS\tts_engine.py"

; --- 1. REPRODUCIR (ESCUCHAR EN VIVO) ---
~LButton & Space:: {
    TriggerAction("play")
}

!Space:: {
    TriggerAction("play")
}

; --- 2. GUARDAR / DESCARGAR ARCHIVO MP3 ---
~LButton & s:: {
    TriggerAction("save")
}

!s:: {
    TriggerAction("save")
}

; --- 3. DETENER LECTURA ---
Esc:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" stop', , "Hide")
}

; --- 4. CONTROL DE VELOCIDAD ---
#HotIf GetKeyState("LButton", "P") and GetKeyState("Space", "P")
WheelUp:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" speedup', , "Hide")
}
WheelDown:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" speeddown', , "Hide")
}
#HotIf

#HotIf GetKeyState("Alt", "P") and GetKeyState("Space", "P")
WheelUp:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" speedup', , "Hide")
}
WheelDown:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" speeddown', , "Hide")
}
#HotIf

TriggerAction(mode) {
    ; Limpiar portapapeles y copiar la selección
    A_Clipboard := ""
    Send "^c"
    
    ; Esperar hasta 400ms a que Windows copie el texto
    if !ClipWait(0.4) {
        SoundBeep 400, 120
        return
    }
    
    if (StrLen(Trim(A_Clipboard)) == 0) {
        return
    }
    
    ; Tono sutil inmediato: atajo recibido y procesando
    SoundBeep 1200, 45
    
    ; Lanzar motor de voz en segundo plano
    Run('"' . PythonExe . '" "' . EngineScript . '" ' . mode, , "Hide")
}
