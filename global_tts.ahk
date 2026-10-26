#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent()

; ============================================================
; Global TTS - Antigravity Listener (AutoHotkey v2)
; ============================================================
; Atajos Principales:
; 1. Texto seleccionado + Click Izquierdo sostenido + Barra Espaciadora -> Reproducir en vivo
; 2. Texto seleccionado por arrastre + Soltar + Barra Espaciadora inmediata (< 1.3s) -> Reproducir en vivo
; 3. Alt + Barra Espaciadora -> Reproducir en vivo (atajo alternativo ultra-estable)
; 4. Click Izquierdo sostenido + S  |  Alt + S -> Guardar audio MP3
; 5. Escape (Esc) -> Detener lectura inmediatamente
; 6. Rueda del ratón (WheelUp / WheelDown) con Alt o Espacio -> Ajustar velocidad
; ============================================================

PythonExe := "C:\Users\Benner\miniconda3\pythonw.exe"
EngineScript := "C:\antigravityAS\GlobalTTS\tts_engine.py"

; Variables globales para detección de selección por arrastre de mouse
global MouseStartX := 0
global MouseStartY := 0
global IsMouseDragging := false
global LastDragEndTime := 0

; Monitorear el inicio de arrastre del botón izquierdo
~LButton:: {
    global MouseStartX, MouseStartY, IsMouseDragging
    MouseGetPos &MouseStartX, &MouseStartY
    IsMouseDragging := true
}

; Monitorear el fin de arrastre del botón izquierdo
~LButton Up:: {
    global MouseStartX, MouseStartY, IsMouseDragging, LastDragEndTime
    if (!IsMouseDragging)
        return
    IsMouseDragging := false
    MouseGetPos &curX, &curY
    ; Distancia euclidiana recorrida por el cursor
    dist := Sqrt((curX - MouseStartX)**2 + (curY - MouseStartY)**2)
    ; Si el cursor se movió al menos 10 píxeles, se considera una selección de texto activa
    if (dist >= 10) {
        LastDragEndTime := A_TickCount
    }
}

; Función condicional para detectar si se acaba de soltar una selección de texto con mouse
CanTriggerRecentSelection() {
    global LastDragEndTime
    return (LastDragEndTime > 0 && (A_TickCount - LastDragEndTime < 1300))
}

; ============================================================
; --- 1. REPRODUCIR (ESCUCHAR EN VIVO) ---
; ============================================================

; Opción A: Mantener presionado el Click Izquierdo y pulsar Barra Espaciadora
~LButton & Space:: {
    global LastDragEndTime
    LastDragEndTime := 0
    TriggerAction("play", false)
}

; Opción B: Soltar el mouse tras arrastrar sobre texto y pulsar Barra Espaciadora dentro de 1.3 seg
#HotIf CanTriggerRecentSelection()
$Space:: {
    global LastDragEndTime
    LastDragEndTime := 0
    TriggerAction("play", true)
}
#HotIf

; Opción C: Atajo alternativo universal de teclado (Alt + Espacio)
!Space:: {
    global LastDragEndTime
    LastDragEndTime := 0
    if GetKeyState("Alt", "P") || GetKeyState("Alt") {
        Send "{Alt up}"
        Sleep 25
    }
    TriggerAction("play", false)
}

; ============================================================
; --- 2. GUARDAR / DESCARGAR ARCHIVO MP3 ---
; ============================================================

; Opción A: Mantener presionado el Click Izquierdo y pulsar 'S'
~LButton & s:: {
    global LastDragEndTime
    LastDragEndTime := 0
    TriggerAction("save", false)
}

; Opción B: Atajo alternativo de teclado (Alt + S)
!s:: {
    global LastDragEndTime
    LastDragEndTime := 0
    if GetKeyState("Alt", "P") || GetKeyState("Alt") {
        Send "{Alt up}"
        Sleep 25
    }
    TriggerAction("save", false)
}

; Opción C: Atajo ejecutivo de guardado rápido (Ctrl + Shift + S)
^+s:: {
    global LastDragEndTime
    LastDragEndTime := 0
    TriggerAction("save", false)
}

; ============================================================
; --- 3. DETENER LECTURA ---
; ============================================================
; Se utiliza ~Esc para no bloquear la funcionalidad nativa de Escape en Windows
~Esc:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" stop', , "Hide")
}

; ============================================================
; --- 4. CONTROL DE VELOCIDAD ---
; ============================================================
; Alt + WheelUp / WheelDown (Ergonómico con una sola mano)
!WheelUp:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" speedup', , "Hide")
}
!WheelDown:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" speeddown', , "Hide")
}

; Combinación sostenida con Espacio o LButton
#HotIf GetKeyState("Space", "P") or (GetKeyState("LButton", "P") and GetKeyState("Space", "P"))
WheelUp:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" speedup', , "Hide")
}
WheelDown:: {
    Run('"' . PythonExe . '" "' . EngineScript . '" speeddown', , "Hide")
}
#HotIf

; ============================================================
; --- NÚCLEO DE ACCIÓN: COPIA SEGURA Y EJECUCIÓN TTS ---
; ============================================================
TriggerAction(mode, isRecentSpace := false) {
    ; 1. Si el botón izquierdo está físicamente presionado, enviamos una liberación lógica.
    ; Esto es VITAL en Windows: muchas aplicaciones (Chrome, Word, VS Code, lectores PDF)
    ; mantienen captura activa del ratón y bloquean o ignoran el copiado (Ctrl+C)
    ; hasta que reciben WM_LBUTTONUP.
    if GetKeyState("LButton", "P") || GetKeyState("LButton") {
        Send "{LButton up}"
        Sleep 40
    }
    
    ; 2. Asegurar que modificadores no interfieran con el copiado
    if GetKeyState("Alt", "P") || GetKeyState("Alt") {
        Send "{Alt up}"
        Sleep 20
    }

    ; Guardar portapapeles anterior para restaurar en caso de fallo
    oldClip := ClipboardAll()
    A_Clipboard := ""

    ; 3. Enviar orden de copiado estándar
    Send "^c"
    clipSuccess := ClipWait(0.35)

    ; 4. Si el copiado estándar no obtuvo texto, intentar con el comando secundario universal (Ctrl + Insert)
    if (!clipSuccess || StrLen(Trim(A_Clipboard)) == 0) {
        A_Clipboard := ""
        Send "^{Insert}"
        clipSuccess := ClipWait(0.20)
    }

    ; 5. Validación del texto capturado
    if (!clipSuccess || StrLen(Trim(A_Clipboard)) == 0) {
        ; Restaurar portapapeles previo
        try A_Clipboard := oldClip
        
        ; Si fue un Space solitario tras un arrastre pero no había texto real
        ; (por ejemplo, mover un slider o un scrollbar), reenviar el espacio nativo
        if (isRecentSpace) {
            Send "{Space}"
        } else {
            ; Tono grave sutil indicando que no se pudo copiar texto
            SoundBeep 400, 100
        }
        return
    }

    ; 6. Retroalimentación acústica inmediata: Atajo detectado y texto copiado exitosamente
    ; Tono agudo y limpio (1200 Hz por 50 ms)
    SoundBeep 1200, 50

    ; 7. Lanzar el motor TTS local en segundo plano
    Run('"' . PythonExe . '" "' . EngineScript . '" ' . mode, , "Hide")
}
