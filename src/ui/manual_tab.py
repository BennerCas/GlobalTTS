"""Pestaña Interactiva con el Manual de Uso Completo y Documentación Técnica de GlobalTTS.

Incluye:
- 12 Capítulos exhaustivos que documentan el 100% de las funciones, motores, atajos,
  clonación biométrica, DSP, efectos SFX, video karaoke, servidor WiFi QR y arquitectura.
- Índice lateral navegable + Vista Integral ("Todo el Manual").
- Buscador instantáneo en tiempo real con filtrado y resaltado de términos.
- Lectura en voz alta integrada del propio capítulo activo mediante el motor neuronal local.
- Sincronización automática con el archivo maestro `MANUAL_DE_USO.md` en la raíz del proyecto.
- Adaptabilidad total a monitores Horizontales (16:9) y Verticales (Retrato).
"""
from __future__ import annotations

import html
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import sounddevice as sd
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.ai.piper_engine import PiperTtsEngine
from src.audio.dsp_mastering import MasteringConfig, master_audio_track

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MANUAL_MD_PATH = PROJECT_ROOT / "MANUAL_DE_USO.md"


@dataclass(frozen=True)
class ManualSection:
    id: str
    code: str
    nav_line1: str
    nav_line2: str
    title: str
    subtitle: str
    markdown_body: str
    html_body: str


MANUAL_SECTIONS: list[ManualSection] = [
    ManualSection(
        id="vision_arquitectura",
        code="§ 01",
        nav_line1="§ 01 — Visión General & Arquitectura",
        nav_line2="Inferencia 100% Local y Telemetría",
        title="Visión General, Arquitectura 100% Local & Telemetría",
        subtitle="Inferencia sin nube, aceleración DirectML/Olive, iGPU ROCm y barra superior de estado.",
        markdown_body="""### 1.1 Filosofía Operativa: 100% Local, Privacidad Absoluta y Costo Cero
**GlobalTTS Studio** es una suite integral de ingeniería de voz, producción de audiolibros, masterización acústica DSP y renderizado de video karaoke que opera **100% en tu hardware local**, sin depender de APIs de pago en la nube ni enviar tus documentos fuera de tu equipo.

### 1.2 Aceleración de Hardware DirectML, Olive y ROCm
La aplicación configura automáticamente los parámetros óptimos de inferencia al iniciar:
- **Backend Principal ONNX Runtime / DirectML**: Ejecución directa de modelos cuantizados (`int8`/`fp16`).
- **Límite Dinámico de VRAM (`OLIVE_GPU_MEMORY_LIMIT = 25GB`)**: Garantiza estabilidad en sesiones largas de generación en lote.
- **Hilos de Inferencia CPU (`OLIVE_CPU_THREADS = 12`)**: Paralelismo óptimo para síntesis fonética y procesamiento DSP SciPy.
- **Aceleración iGPU AMD RDNA3 (`OLLAMA_IGPU_ENABLE = 1` y `HSA_OVERRIDE_GFX_VERSION = 11.0.0`)**: Inyección automática para que **Mistral NeMo 12B** acelere por hardware vía `llama.cpp`.
- **Puente Central de Modelos (`C:\\antigravityAS\\Modelos -ai-brains`)**: Todos los cerebros neuronales (`Kokoro-82M`, `Piper ONNX`, `CosyVoice3 campplus.onnx`, `Mistral NeMo`) se consumen desde el repositorio central sin duplicar archivos.

### 1.3 Barra Superior de Telemetría y Accesos Rápidos de Estudio
En la cabecera y barra de navegación principal encontrarás:
1. **Monitor de Hardware en Vivo (`[ HW: ... ]`)**: Se actualiza cada 2 segundos mostrando el proveedor activo (`DirectML` o `ONNX-CPU(12T)`), porcentaje de uso de **CPU**, consumo de **RAM** (`GB usados / GB totales`), tope de **VRAM (`25GB`)** y la tasa de aciertos de la **Caché Acústica SHA-256**.
2. **`[ ↕ ] Modo: Auto / Vertical / Horizontal`**: Alterna la maquetación completa de la interfaz entre monitores panorámicos (`16:9`) y monitores verticales (retrato) sin perder un solo control.
3. **`[ _ ] Minimizar`**: Oculta la ventana en la bandeja del sistema (System Tray) manteniendo activos los atajos globales.
4. **Accesos de Estudio junto a las Pestañas (`[ ↗ ] WiFi QR`, `[ ↗ ] Lexicon`, `[ ★ ] Clonar Voz`, `[ × ] Caché`)**: Ubicados al costado derecho de la pestaña *Manual de Uso Completo* para abrir las herramientas de estudio desde cualquier sección.""",
        html_body="""
<h3>1.1 Filosofía Operativa: 100% Local, Privacidad Absoluta y Costo Cero</h3>
<p><b>GlobalTTS Studio</b> es una suite integral de ingeniería de voz, producción de audiolibros, masterización acústica DSP y renderizado de video karaoke que opera <b>100% en tu hardware local</b>, sin depender de APIs de pago en la nube ni enviar tus documentos fuera de tu equipo.</p>

<h3>1.2 Aceleración de Hardware DirectML, Olive y ROCm</h3>
<ul>
  <li><b>Backend Principal ONNX Runtime / DirectML:</b> Ejecución directa de modelos neuronales optimizados (<code>Kokoro 24kHz</code>, <code>Piper ONNX</code> y <code>CampPlus Biométrico</code>).</li>
  <li><b>Límite Dinámico de VRAM (<code>OLIVE_GPU_MEMORY_LIMIT = 25GB</code>):</b> Protección contra desbordamiento de memoria gráfica en lotes extensos.</li>
  <li><b>Hilos de Inferencia CPU (<code>OLIVE_CPU_THREADS = 12</code>):</b> Paralelismo dedicado para síntesis fonética y filtros DSP SciPy.</li>
  <li><b>Aceleración iGPU AMD RDNA3 (<code>OLLAMA_IGPU_ENABLE = 1</code>, <code>HSA_OVERRIDE_GFX_VERSION = 11.0.0</code>):</b> Variables inyectadas automáticamente para acelerar <b>Mistral NeMo 12B</b> en local.</li>
  <li><b>Puente Central de Modelos:</b> Acceso directo a <code>C:\\antigravityAS\\Modelos -ai-brains</code> con cero duplicación en disco.</li>
</ul>

<h3>1.3 Barra Superior y Herramientas Rápidas en la Barra de Pestañas</h3>
<table width="100%" cellspacing="0" cellpadding="6" style="border:1px solid #1E293B; background:#0F172A; margin-top:6px;">
  <tr style="background:#1E293B; color:#38BDF8; font-weight:bold;">
    <td width="28%">Control</td>
    <td>Función Detallada</td>
  </tr>
  <tr><td><code>[ HW: ... | CPU | RAM | Cache ]</code></td><td>Muestra en tiempo real el uso de CPU, RAM, límite de VRAM (25GB) y porcentaje de aciertos de la caché acústica SHA-256.</td></tr>
  <tr><td><code>[ ↗ ] WiFi QR</code></td><td>Ubicado al costado de la barra de pestañas: inicia el servidor HTTP Range 206 en tu red WiFi local y genera el código QR móvil.</td></tr>
  <tr><td><code>[ ↗ ] Lexicon</code></td><td>Ubicado al costado de la barra de pestañas: abre el Diccionario Fonético para personalizar siglas, acrónimos y extranjerismos.</td></tr>
  <tr><td><code>[ ★ ] Clonar Voz</code></td><td>Ubicado al costado de la barra de pestañas: abre el clonador biométrico de voz local basado en <code>campplus.onnx</code>.</td></tr>
  <tr><td><code>[ × ] Caché</code></td><td>Ubicado al costado de la barra de pestañas: limpia los vectores acústicos almacenados en <code>cache/tts_segments/</code>.</td></tr>
  <tr><td><code>[ ↕ ] Modo: Auto / Vertical / Horizontal</code></td><td>Adapta dinámicamente toda la interfaz a pantallas horizontales (16:9) o monitores verticales sin recortar controles.</td></tr>
  <tr><td><code>[ _ ] Minimizar</code></td><td>Envía la aplicación a la bandeja del sistema (System Tray) manteniendo activos los atajos de lectura global.</td></tr>
</table>
""",
    ),
    ManualSection(
        id="atajos_globales",
        code="§ 02",
        nav_line1="§ 02 — Atajos Globales del Sistema",
        nav_line2="AutoHotkey v2 y Captura en Vivo",
        title="Atajos Globales del Sistema (AutoHotkey v2 & Captura en Vivo)",
        subtitle="Cómo leer en voz alta o exportar a MP3 cualquier texto seleccionado en Windows.",
        markdown_body="""### 2.1 Cómo Funcionan los Atajos Globales
El servicio residente `global_tts.ahk` (AutoHotkey v2) escucha tus gestos de teclado y ratón en todo el sistema operativo (navegadores web, visores PDF, Word, Notion, terminales o editores de código) y envía el texto seleccionado al motor neuronal local `tts_engine.py`.

### 2.2 Tabla Maestra de Combinaciones de Teclas y Ratón
1. **Lectura Inmediata con Ratón (`Seleccionar Texto + Mantener Clic Izquierdo + Barra Espaciadora`)**:
   - Subraya cualquier párrafo con el ratón.
   - Sin soltar el botón izquierdo del ratón (o manteniéndolo presionado sobre la selección), pulsa la **Barra Espaciadora**.
   - Escucharás un breve tono de confirmación y la voz neural comenzará a leer el texto al instante.
2. **Atajo Alternativo Universal (`Alt + Barra Espaciadora`)**:
   - Ideal para editores de código, terminales o visores PDF que interceptan el clic izquierdo.
   - Selecciona el texto y presiona **`Alt + Espacio`**.
3. **Exportación Directa de Selección a MP3 (`Ctrl + Shift + S`)**:
   - Selecciona cualquier texto en cualquier programa y presiona **`Ctrl + Shift + S`**.
   - El sistema sintetiza la voz, la masteriza a `-16 LUFS` (EBU R128) y guarda el archivo `.mp3` junto con su `.json` de metadatos en tu carpeta configurada (`Downloads/TTS_Audios`), abriendo el explorador con el archivo seleccionado.
4. **Parada de Emergencia (`Tecla Escape / Esc`)**:
   - Mientras se esté reproduciendo cualquier lectura rápida, presiona **`Esc`** (o vuelve a pulsar el atajo de lectura) para detener el audio de forma inmediata.

### 2.3 Traducción Automática Inglés → Español al Vuelo
Si activas la casilla **`Traducir Inglés -> Español al vuelo`** en la pestaña *Lectura Rápida & Configuración*, cada vez que selecciones un artículo o párrafo en inglés en tu navegador y pulses el atajo, GlobalTTS detectará el idioma y lo traducirá al español antes de leerlo en voz alta.

### 2.4 Reinicio del Servicio de Captura
Si en algún momento cierras AutoHotkey desde el Administrador de Tareas, simplemente haz clic en el botón **`[ ⟳ ] Reiniciar Atajos`** dentro de la sección *Atajos Globales Activos*.""",
        html_body="""
<h3>2.1 Cómo Funcionan los Atajos Globales</h3>
<p>El servicio residente <code>global_tts.ahk</code> (AutoHotkey v2) escucha tus gestos en todo Windows (navegadores, visores PDF, Word, IDEs) y envía el texto seleccionado al motor neuronal local sin cambiar de ventana.</p>

<h3>2.2 Tabla Maestra de Combinaciones de Teclas y Ratón</h3>
<table width="100%" cellspacing="0" cellpadding="7" style="border:1px solid #1E293B; background:#0F172A; margin-top:6px;">
  <tr style="background:#1E293B; color:#38BDF8; font-weight:bold;">
    <td width="34%">Atajo / Gesto</td>
    <td>Acción Ejecutada</td>
  </tr>
  <tr>
    <td><b>Seleccionar Texto + Clic Izquierdo Sostenido + Barra Espaciadora</b></td>
    <td>Copia silenciosamente el texto resaltado y lo lee en voz alta de inmediato con la voz y velocidad configuradas.</td>
  </tr>
  <tr>
    <td><b>Alt + Barra Espaciadora</b></td>
    <td>Atajo alternativo universal para aplicaciones que bloquean eventos de ratón (terminales, IDEs, visores protegidos).</td>
  </tr>
  <tr>
    <td><b>Ctrl + Shift + S</b></td>
    <td>Sintetiza el texto seleccionado, aplica normalización EBU R128 y guarda un archivo <code>.MP3</code> + <code>_metadata.json</code> en <code>Downloads/TTS_Audios</code>.</td>
  </tr>
  <tr>
    <td><b>Tecla Escape (Esc)</b></td>
    <td>Interrumpe y silencia instantáneamente cualquier reproducción de voz en curso.</td>
  </tr>
</table>

<h3>2.3 Traducción Automática Inglés → Español y Reinicio</h3>
<ul>
  <li><b>Traducción al Vuelo:</b> Con la opción <i>Traducir Inglés → Español al vuelo</i> activa, puedes seleccionar texto en inglés en cualquier web y escucharlo directamente narrado en español.</li>
  <li><b>Botón <code>[ ⟳ ] Reiniciar Atajos</code>:</b> Reinicia el proceso <code>AutoHotkey64.exe</code> en cualquier momento con un solo clic.</li>
</ul>
""",
    ),
    ManualSection(
        id="lectura_rapida",
        code="§ 03",
        nav_line1="§ 03 — Pestaña 1: Lectura Rápida",
        nav_line2="Editor en Vivo, SFX y Configuración",
        title="Pestaña 1: Lectura Rápida & Configuración Profesional",
        subtitle="Editor en vivo, inserción de etiquetas prosódicas/SFX, historial infinito y ajustes del sistema.",
        markdown_body="""### 3.1 El Editor de Lectura en Tiempo Real
La primera pestaña está diseñada para redactar, pegar o importar textos breves, guiones, artículos o capítulos sueltos y escucharlos o exportarlos a MP3 al instante.

### 3.2 Barra de Inserción Rápida de Etiquetas Prosódicas y Foley SFX
Debajo del cuadro de texto dispones de botones de inserción directa que envuelven el texto seleccionado (o insertan en el cursor) marcas acústicas reales:
- **`[+Pausa 1s]`**: Inserta `[pausa:1s]` (admite valores en segundos `1.5s` o milisegundos `500ms`).
- **`[Susurro]`**: Envuelve el texto en `[susurro]...[/susurro]` (reduce volumen y suaviza el ataque).
- **`[Énfasis]`**: Envuelve en `[énfasis]...[/énfasis]` (incrementa presencia y articulación).
- **`[Lento]` / `[Rápido]`**: Modula la cadencia local de la frase (`[lento]...[/lento]`, `[rápido]...[/rápido]`).
- **`[Risa]` / `[Suspiro]`**: Inserta inflexiones humanas naturales (`[risa]`, `[suspiro]`).
- **Selector `[ + SFX ... ]`**: Inserta cualquiera de los 11 efectos acústicos Foley (`[sfx:trueno]`, `[sfx:lluvia]`, `[sfx:puerta]`, `[sfx:pasos]`, `[sfx:campana]`, `[sfx:viento]`, `[sfx:reloj]`, `[sfx:latido]`, `[sfx:fuego]`, `[sfx:alerta_radio]`, `[sfx:transicion]`).

### 3.3 Ingesta Rápida desde URL Web y Controles Pre-Síntesis
En la cabecera del editor encontrarás:
- **`[ ↗ ] URL Web`**: Abre el extractor Readability para descargar el texto limpio de cualquier artículo o noticia web directamente al editor.
- **`[ ↗ ] Lexicon`**: Abre el diccionario fonético.
- **Casillas `Lexicon Fonético`, `Prosodia Emocional` y `SFX Automático`**: Activan o desactivan en tiempo real la conversión de siglas, la modulación emocional por oración y la detección semántica de efectos de sonido.

### 3.4 Historial Infinito Automático
Cada vez que pulsas **`[ ► ] Leer en Voz Alta`**, el audio generado se registra automáticamente en el **Historial Infinito** (`biblioteca/_historial_lecturas/`), quedando disponible de inmediato en la pestaña **Biblioteca & Reproductor** para volver a escucharlo cuando quieras sin tener que regenerarlo.""",
        html_body="""
<h3>3.1 El Editor de Lectura en Tiempo Real</h3>
<p>Diseñado para probar guiones, escuchar artículos web, ajustar la expresividad con IA y exportar locuciones rápidas en MP3 con calidad de estudio.</p>

<h3>3.2 Barra de Etiquetas Prosódicas y Foley SFX</h3>
<ul>
  <li><b>Pausas Exactas:</b> <code>[pausa:500ms]</code>, <code>[pausa:1.5s]</code> insertan silencios digitales exactos entre frases.</li>
  <li><b>Modulación de Voz:</b> <code>[susurro]...[/susurro]</code>, <code>[énfasis]...[/énfasis]</code>, <code>[lento]...[/lento]</code>, <code>[rápido]...[/rápido]</code>.</li>
  <li><b>Expresiones Humanas:</b> <code>[risa]</code>, <code>[suspiro]</code>, <code>[jadeo]</code>.</li>
  <li><b>Efectos Foley SFX:</b> Usa el desplegable <code>[ + SFX ... ]</code> para insertar efectos acústicos reales como <code>[sfx:trueno]</code>, <code>[sfx:puerta]</code> o <code>[sfx:alerta_radio]</code>.</li>
</ul>

<h3>3.3 Historial Infinito y Guardado Rápido</h3>
<ul>
  <li><b>Historial Automático:</b> Toda lectura reproducida en esta pestaña se guarda automáticamente en el <b>Historial Infinito</b> y puede consultarse en la pestaña <i>Biblioteca &amp; Reproductor</i>.</li>
  <li><b>Botón <code>[ ↓ ] Guardar MP3</code>:</b> Exporta el audio masterizado (256 kbps, -16 LUFS) con firma de autoría y archivo <code>_metadata.json</code> en tu carpeta de descargas.</li>
</ul>
""",
    ),
    ManualSection(
        id="generador_lotes_ingesta",
        code="§ 04",
        nav_line1="§ 04 — Pestaña 2: Generador en Lote",
        nav_line2="Ingesta PDF/EPUB/OCR y Cola Activa",
        title="Pestaña 2: Generador de Audiolibros, OCR & Cola en Lote",
        subtitle="Ingesta de PDF/EPUB/TXT/Imágenes OCR/URLs, limpieza editorial y control de cola.",
        markdown_body="""### 4.1 Formatos de Entrada Soportados
El **Generador de Audiolibros** procesa documentos completos de forma secuencial (1 por 1) y acepta:
1. **Libros Digitales (`.epub`, `.pdf`)**: Extrae la estructura jerárquica de capítulos (Tabla de Contenidos TOC, números romanos `Capítulo IV`, o encabezados).
2. **PDFs Escaneados e Imágenes (`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`)**: Si un PDF es un escaneo fotográfico sin texto seleccionable, o si agregas imágenes directamente, entra en acción el **Motor OCR Nativo de Windows (`Windows.Media.Ocr.OcrEngine`)** para reconocer el texto 100% offline.
3. **Texto Plano y Markdown (`.txt`, `.md`)**: Detecta títulos por signos `#`, `##` o líneas de capítulo.
4. **Artículos y Ensayos Web (`[ ↗ ] Extraer URL Web`)**: Descarga cualquier página web eliminando menús, anuncios y barras laterales mediante el motor Readability integrado.

### 4.2 Limpieza Editorial Inteligente (`Limpieza Editorial`)
Cuando la casilla **`Limpieza Editorial`** está marcada (activa por defecto), el preprocesador heurístico analiza todas las páginas antes de sintetizar para eliminar:
- Números de página sueltos (`42`, `- 18 -`, `Página 12 de 300`).
- Cabeceras y pies de página repetidos en 3 o más páginas consecutivas (running headers/footers).
- Llamadas numéricas a notas al pie (`[1]`, `[14, 15]`) y superíndices (`¹`, `²`, `³`) para evitar que el narrador lea números sueltos en mitad de una frase.
- Citas académicas repetitivas (`(Ibid., p. 45)`, `(Op. cit.)`) y líneas de ISBN/imprenta.

### 4.3 Gestión Avanzada de la Cola en Lote
- **Reordenar Prioridad (`[ ↑ ]` y `[ ↓ ]`)**: Selecciona cualquier archivo en la tabla y súbelo o bájalo en la cola de procesamiento.
- **Pausar y Reanudar en Vivo (`[ ❚❚ ] Pausar Cola` / `[ ► ] Reanudar Cola`)**: Congela el lote de forma segura al terminar la oración actual (liberando el uso de CPU/GPU temporalmente) y reanúdalo exactamente donde quedó.
- **Cancelar Cola (`[ ■ ] Cancelar`)**: Detiene limpiamente el procesamiento en lote sin corromper los archivos ya terminados.""",
        html_body="""
<h3>4.1 Formatos de Entrada Soportados e Ingesta OCR</h3>
<ul>
  <li><b>Libros EPUB y PDF Digitales (<code>.epub</code>, <code>.pdf</code>):</b> Detección automática de marcadores TOC, numeración romana (<code>Capítulo I..XX</code>) y partes.</li>
  <li><b>PDFs Escaneados e Imágenes (<code>.png</code>, <code>.jpg</code>, <code>.webp</code>, <code>.bmp</code>):</b> Reconocimiento óptico de caracteres automático mediante <b>Windows WinRT Media OCR</b> (100% local).</li>
  <li><b>Texto y Markdown (<code>.txt</code>, <code>.md</code>):</b> Soporte de encabezados <code>#</code> y bloques narrativos.</li>
  <li><b>Artículos Web (<code>[ ↗ ] Extraer URL Web</code>):</b> Limpieza Readability de blogs, ensayos y noticias en línea.</li>
</ul>

<h3>4.2 Filtro Heurístico de Limpieza Editorial</h3>
<p>Con la casilla <b>Limpieza Editorial</b> activa, el sistema suprime automáticamente números de página aislados, cabeceras repetidas entre páginas, notas al pie <code>[12]</code>, superíndices <code>¹²</code> y referencias <code>Ibid.</code> / <code>Op. cit.</code> para que la lectura fluya sin interrupciones artificiales.</p>

<h3>4.3 Controles de Cola en Tiempo Real</h3>
<table width="100%" cellspacing="0" cellpadding="6" style="border:1px solid #1E293B; background:#0F172A;">
  <tr style="background:#1E293B; color:#38BDF8; font-weight:bold;">
    <td width="25%">Botón</td>
    <td>Comportamiento</td>
  </tr>
  <tr><td><code>[ ↑ ]</code> / <code>[ ↓ ]</code></td><td>Cambia el orden de prioridad de los documentos pendientes en la tabla.</td></tr>
  <tr><td><code>[ ❚❚ ] Pausar Cola</code></td><td>Suspende el procesamiento tras completar el segmento actual y permite reanudarlo (<code>[ ► ] Reanudar Cola</code>) sin perder progreso.</td></tr>
  <tr><td><code>[ ■ ] Cancelar</code></td><td>Detiene de forma segura el lote activo conservando los audiolibros ya finalizados.</td></tr>
</table>
""",
    ),
    ManualSection(
        id="voces_autocasting_clonacion",
        code="§ 05",
        nav_line1="§ 05 — Voces Neurales 24kHz & Casting",
        nav_line2="Auto-Casting y Clonación Biométrica",
        title="Voces Neurales (24kHz), Auto-Casting Multi-Voz & Clonación Biométrica",
        subtitle="Catálogo de 15 voces base, reparto automático de diálogos y clonación con campplus.onnx.",
        markdown_body="""### 5.1 Motores de Voz Integrados (Kokoro 24kHz Studio & Piper ONNX)
GlobalTTS integra dos motores neuronales de alta velocidad:
- **Kokoro 82M (24kHz Studio)**: Voces hiperrealistas de 24,000 Hz con riqueza de formantes e inflexión natural (ej. *Dora*, *Alex*, *Santa*, *Bella*, *Sarah*, *Nicole*, *Sky*, *Michael*, *Adam*, *Heart*, *Emma*, *Isabella*, *George*, *Lewis*).
- **Piper ONNX (16kHz / 22kHz)**: Voces neuronales ligeras en español de México y España (*Claude High*, *Sharvard Medium*, *Ald Medium*, *Carlfm*, *Davefx*).

### 5.2 Auto-Casting Multi-Voz para Diálogos Literarios
Cuando marcas **`Auto-Casting Multi-Voz con IA en diálogos`** en el Generador de Audiolibros:
1. La **Voz Principal (Narrador)** lee toda la prosa descriptiva y acotaciones.
2. El sistema detecta automáticamente las intervenciones de diálogo (`—Hola —dijo María—`, `"..."`, `«...»`) y clasifica el género y rol de cada personaje.
3. Asigna de forma consistente distintas voces del **Pool de Casting** (las casillas marcadas en la tabla de voces) a cada personaje a lo largo de todo el libro.
4. Puedes usar los botones rápidos **`Todas`**, **`Solo Kokoro`**, **`Limpiar`** y **`[ ► ] Probar`** para configurar tu elenco en segundos.

### 5.3 Laboratorio de Clonación Biométrica de Voz (`[ ★ ] Clonar Voz`)
Puedes clonar el timbre, tono y cadencia de cualquier locutor a partir de una grabación de referencia:
1. Haz clic en **`[ ★ ] Clonar Voz`** en la barra superior o en el panel de voces.
2. Escribe un nombre para el perfil (ej. *Narrador Documental*) y selecciona un archivo de audio limpio de **5 a 45 segundos** (`.wav`, `.mp3`, `.flac`, `.ogg`) sin música de fondo.
3. Pulsa **`[ ★ ] Analizar y Clonar Voz`**. El motor ejecutará:
   - Extracción del vector biométrico de 192 dimensiones mediante el modelo **`CosyVoice3-ONNX/campplus.onnx`**.
   - Estimación de la Frecuencia Fundamental mediana ($F_0$ en Hz) por autocorrelación armónica.
   - Análisis de densidad espectral Welch para medir **Calidez de graves (100–380 Hz)** y **Presencia de formantes (2.2–5.5 kHz)**.
   - Cálculo de cadencia silábica y emparejamiento con la base neuronal óptima de 24kHz + matriz de desplazamiento de tono (`pitch_semitones`) sin alterar la velocidad.
4. La nueva voz aparecerá inmediatamente en todos los selectores bajo el prefijo **`Clon IA: ...`** lista para probarse o narrar libros completos.""",
        html_body="""
<h3>5.1 Motores de Voz Integrados (Kokoro 24kHz Studio &amp; Piper ONNX)</h3>
<ul>
  <li><b>Kokoro 82M (24kHz Studio):</b> Síntesis neuronal de 24 kHz con alta fidelidad armónica y expresividad orgánica.</li>
  <li><b>Piper ONNX:</b> Síntesis ultrarrápida optimizada para español de España (<code>es_ES</code>) y Latinoamérica (<code>es_MX</code>).</li>
</ul>

<h3>5.2 Auto-Casting Multi-Voz en Diálogos</h3>
<p>Al activar <b>Auto-Casting Multi-Voz con IA en diálogos</b>, el narrador principal lee la descripción mientras que cada personaje detectado en los diálogos recibe una voz diferenciada y consistente tomada de las voces marcadas en la tabla de <i>Casting</i>.</p>

<h3>5.3 Cómo Clonar una Voz Localmente (Paso a Paso)</h3>
<ol>
  <li>Abre <b><code>[ ★ ] Clonar Voz</code></b> y asigna un nombre al nuevo perfil.</li>
  <li>Selecciona una muestra de audio de referencia (<code>.wav</code>, <code>.mp3</code>, <code>.flac</code> o <code>.ogg</code> de 5 a 45 segundos de voz clara).</li>
  <li>Haz clic en <b><code>[ ★ ] Analizar y Clonar Voz</code></b>. El motor extrae el embedding biométrico 192-D con <code>campplus.onnx</code>, calcula la frecuencia fundamental <i>F0</i> (Hz), el desplazamiento en semitonos y la curva de formantes EQ.</li>
  <li>Selecciona el perfil creado y pulsa <b><code>[ ► ] Escuchar Prueba</code></b>. El perfil queda guardado en <code>config/cloned_voices.json</code> y disponible en toda la app.</li>
</ol>
""",
    ),
    ManualSection(
        id="ia_narrativa_prompts",
        code="§ 06",
        nav_line1="§ 06 — Expresividad y Narración IA",
        nav_line2="6 Modos IA y 16 Estilos CO-STAR",
        title="Expresividad, Narración IA (Mistral NeMo 12B) & Prompts Maestros",
        subtitle="Los 6 modos de IA con <thinking>, los 16 estilos narrativos CO-STAR y el editor de Prompts Maestros.",
        markdown_body="""### 6.1 Cómo Activar el Motor Narrativo Local (Mistral NeMo 12B)
Tanto en *Lectura Rápida* como en el *Generador de Audiolibros* puedes activar la casilla **`Activar análisis con IA (Mistral NeMo 12B local)`**. Además, incluso si no activas la reescritura por LLM, el **Estilo** seleccionado aplica su perfil acústico real (velocidad, ganancia dB y pausas) directamente sobre el sintetizador.

### 6.2 Los 6 Modos de Procesamiento IA (Meta-Prompting CO-STAR + `<thinking>`)
1. **Enriquecer Expresividad (`enhance`)**: Respeta el 100% de las palabras originales del autor e inyecta estratégicamente etiquetas de dirección acústica (`[pausa]`, `[pausa_dramatica]`, `[lento]`, `[rápido]`, `[énfasis]`, `[susurro]`, `[risa]`, `[suspiro]`, `[jadeo]`).
2. **Modo Narrador Completo (`rewrite`)**: Transforma el texto en una narración oral inmersiva adaptando la **Perspectiva Gramatical** (`1ra Persona Yo`, `2da Persona Tú`, `3ra Persona Él/Ella`), el **Tiempo Verbal** (`Pasado`, `Presente`, `Presente Continuo`, `Futuro`) y cualquiera de los **16 Estilos Literarios CO-STAR**.
3. **Traducción y Adaptación (`translate`)**: Traduce textos de otros idiomas al Español Neutro (`es-LA`) literario cuidando la eufonía y el ritmo hablado.
4. **Detección y Clasificación de Diálogos (`dialogue_analysis`)**: Analiza la estructura dramática del capítulo y devuelve los segmentos etiquetados por hablante, género y emoción para el motor de Auto-Casting.
5. **Guion de Audio-Trailer Cinematográfico 90s (`trailer_script`)**: Estructura un avance promocional en 4 actos (*Hook, Conflicto, Clímax y Tagline*) de 130 a 190 palabras con pausas dramáticas y efectos Foley SFX.
6. **Dirección de Paisaje Sonoro y Efectos Foley SFX (`sfx_director`)**: Analiza las acciones físicas y el clima de la escena e inyecta marcadores `[sfx:...]` e inflexiones humanas sin alterar las palabras del autor.

### 6.3 Catálogo de los 16 Estilos Narrativos Industriales y su Perfil Acústico DSP
| Estilo (`ID`) | Nombre Descriptivo | Modulación Acústica Real (Speed / Gain / Pause) |
| :--- | :--- | :--- |
| `cuento` | Cuento Literario Clásico | `0.94x` • `+1.0 dB` • `Pausa 1.35x` |
| `historia` | Crónica Histórica y Documental | `0.95x` • `+1.2 dB` • `Pausa 1.30x` |
| `suceso` | Crónica de Suceso / Reportaje de Impacto | `1.08x` • `+2.2 dB` • `Pausa 0.85x` |
| `epico` | Epopeya Cinematográfica y Fantasía Épica | `0.92x` • `+2.5 dB` • `Pausa 1.45x` |
| `terror_psicologico` | Terror Psicológico y Suspenso Nocturno | `0.86x` • `-1.5 dB` • `Pausa 1.65x` |
| `ensayo_cientifico` | Divulgación Científica y Ensayo Filosófico | `0.96x` • `+0.8 dB` • `Pausa 1.25x` |
| `poetico_lirico` | Prosa Poética y Contemplación Lírica | `0.85x` • `-0.5 dB` • `Pausa 1.70x` |
| `infantil_fabula` | Fábula Infantil y Relato Maravilloso | `0.92x` • `+1.5 dB` • `Pausa 1.40x` |
| `cyberpunk_scifi` | Ciencia Ficción / Cyberpunk Noir | `1.03x` • `+1.5 dB` • `Pausa 1.05x` |
| `confesion_intima` | Diario Personal / Confesión Íntima | `0.88x` • `-1.2 dB` • `Pausa 1.55x` |
| `oratoria_motivacional` | Oratoria Inspiracional y Liderazgo | `1.02x` • `+2.8 dB` • `Pausa 1.20x` |
| `cuentacuentos` | Cuentacuentos Tradicional (Oralidad Viva) | `0.93x` • `+1.2 dB` • `Pausa 1.40x` |
| `locutor_radio` | Locutor de Radio / Podcast Nocturno | `1.06x` • `+2.5 dB` • `Pausa 0.85x` |
| `true_crime_documental` | True Crime & Investigación Forense | `0.91x` • `+0.5 dB` • `Pausa 1.45x` |
| `podcast_conversacional` | Podcast Conversacional & Storytelling Moderno | `1.04x` • `+1.6 dB` • `Pausa 0.95x` |
| `institucional_corporativo` | Institucional, Ejecutivo & E-Learning | `1.00x` • `+1.8 dB` • `Pausa 1.05x` |

### 6.4 Pestaña 4: Gestor de Prompts Maestros & Estilos IA
En la pestaña **PROMPTS MAESTROS & ESTILOS IA** puedes inspeccionar, editar, duplicar, activar prompts personalizados con `[ ★ ] Activar para su Modo` o ajustar los multiplicadores acústicos (`Velocidad`, `Ganancia dB`, `Pausas`). Todo cambio se sincroniza bidireccionalmente con `src/ai/prompts_master.json` y con el documento maestro `PROMPTS_MAESTROS.md`.""",
        html_body="""
<h3>6.1 Los 6 Modos de Procesamiento IA (Mistral NeMo 12B + Scratchpad &lt;thinking&gt;)</h3>
<ul>
  <li><b>Enriquecer Expresividad (<code>enhance</code>):</b> Conserva intacto el texto del autor e inserta etiquetas prosódicas e inflexiones (<code>[pausa]</code>, <code>[pausa_dramatica]</code>, <code>[susurro]</code>, <code>[énfasis]</code>, <code>[risa]</code>, <code>[suspiro]</code>, <code>[jadeo]</code>).</li>
  <li><b>Modo Narrador Completo (<code>rewrite</code>):</b> Reescribe como relato oral aplicando la <b>Perspectiva</b> (1ra/2da/3ra persona), <b>Tiempo Verbal</b> y cualquiera de los <b>16 Estilos CO-STAR</b>.</li>
  <li><b>Traducción y Adaptación (<code>translate</code>):</b> Traduce al español neutro cuidando la musicalidad hablada.</li>
  <li><b>Detección de Diálogos (<code>dialogue_analysis</code>):</b> Clasifica hablantes, géneros y emociones para el Auto-Casting.</li>
  <li><b>Guion de Audio-Trailer 90s (<code>trailer_script</code>):</b> Genera un avance promocional en 4 actos con ganchos dramáticos y efectos Foley.</li>
  <li><b>Dirección de Efectos Foley SFX (<code>sfx_director</code>):</b> Inyecta marcadores <code>[sfx:...]</code> e inflexiones humanas sin tocar las palabras originales.</li>
</ul>

<h3>6.2 Tabla de los 16 Estilos Narrativos Industriales y su Modulación Acústica Real</h3>
<table width="100%" cellspacing="0" cellpadding="5" style="border:1px solid #1E293B; background:#0F172A;">
  <tr style="background:#1E293B; color:#38BDF8; font-weight:bold;">
    <td>Estilo (ID)</td>
    <td>Nombre</td>
    <td>Perfil Acústico DSP</td>
  </tr>
  <tr><td><code>cuento</code></td><td>Cuento Literario Clásico</td><td><code>Speed 0.94x | Gain +1.0 dB | Pause 1.35x</code></td></tr>
  <tr><td><code>historia</code></td><td>Crónica Histórica y Documental</td><td><code>Speed 0.95x | Gain +1.2 dB | Pause 1.30x</code></td></tr>
  <tr><td><code>suceso</code></td><td>Crónica de Suceso / Reportaje</td><td><code>Speed 1.08x | Gain +2.2 dB | Pause 0.85x</code></td></tr>
  <tr><td><code>epico</code></td><td>Epopeya Cinematográfica y Fantasía</td><td><code>Speed 0.92x | Gain +2.5 dB | Pause 1.45x</code></td></tr>
  <tr><td><code>terror_psicologico</code></td><td>Terror Psicológico y Suspenso</td><td><code>Speed 0.86x | Gain -1.5 dB | Pause 1.65x</code></td></tr>
  <tr><td><code>ensayo_cientifico</code></td><td>Divulgación Científica y Ensayo</td><td><code>Speed 0.96x | Gain +0.8 dB | Pause 1.25x</code></td></tr>
  <tr><td><code>poetico_lirico</code></td><td>Prosa Poética y Contemplación</td><td><code>Speed 0.85x | Gain -0.5 dB | Pause 1.70x</code></td></tr>
  <tr><td><code>infantil_fabula</code></td><td>Fábula Infantil y Maravilloso</td><td><code>Speed 0.92x | Gain +1.5 dB | Pause 1.40x</code></td></tr>
  <tr><td><code>cyberpunk_scifi</code></td><td>Ciencia Ficción / Cyberpunk Noir</td><td><code>Speed 1.03x | Gain +1.5 dB | Pause 1.05x</code></td></tr>
  <tr><td><code>confesion_intima</code></td><td>Diario Personal / Confesión Íntima</td><td><code>Speed 0.88x | Gain -1.2 dB | Pause 1.55x</code></td></tr>
  <tr><td><code>oratoria_motivacional</code></td><td>Oratoria Inspiracional y Liderazgo</td><td><code>Speed 1.02x | Gain +2.8 dB | Pause 1.20x</code></td></tr>
  <tr><td><code>cuentacuentos</code></td><td>Cuentacuentos Tradicional</td><td><code>Speed 0.93x | Gain +1.2 dB | Pause 1.40x</code></td></tr>
  <tr><td><code>locutor_radio</code></td><td>Locutor de Radio / Podcast Nocturno</td><td><code>Speed 1.06x | Gain +2.5 dB | Pause 0.85x</code></td></tr>
  <tr><td><code>true_crime_documental</code></td><td>True Crime &amp; Investigación Forense</td><td><code>Speed 0.91x | Gain +0.5 dB | Pause 1.45x</code></td></tr>
  <tr><td><code>podcast_conversacional</code></td><td>Podcast Conversacional Moderno</td><td><code>Speed 1.04x | Gain +1.6 dB | Pause 0.95x</code></td></tr>
  <tr><td><code>institucional_corporativo</code></td><td>Institucional, Ejecutivo &amp; E-Learning</td><td><code>Speed 1.00x | Gain +1.8 dB | Pause 1.05x</code></td></tr>
</table>

<h3>6.3 Pestaña 4: Prompts Maestros &amp; Estilos IA</h3>
<p>Permite editar cada prompt del sistema, duplicar y activar variantes con <b><code>[ ★ ] Activar para su Modo</code></b>, ajustar los multiplicadores acústicos de cada estilo y sincronizarlos en tiempo real con <code>PROMPTS_MAESTROS.md</code>.</p>
""",
    ),
    ManualSection(
        id="acustica_dsp_sfx_soundscapes",
        code="§ 07",
        nav_line1="§ 07 — Ingeniería Acústica & DSP",
        nav_line2="Mastering, Soundscapes, SFX y Cuñas",
        title="Ingeniería Acústica: Masterización DSP, Soundscapes, SFX & Cuñas",
        subtitle="Cadena DSP de 5 etapas, música ambiental con Auto-Ducking, Foley SFX y cuñas radiales.",
        markdown_body="""### 7.1 Cadena de Masterización DSP de Estudio (5 Etapas)
Cuando la casilla **`DSP Mastering`** está activa, el audio sintetizado pasa por el procesador `src/audio/dsp_mastering.py` antes de exportarse:
1. **Filtro Pasa-Altos (HPF) Butterworth a 80 Hz**: Elimina frecuencias sub-graves y retumbos sin afectar el cuerpo de la voz.
2. **De-Esser Dinámico de Banda Dividida (5.5 kHz – 9.5 kHz)**: Detecta excesos de energía sibilante (`s`, `z`, `c`) y los atenúa suavemente hasta `4.5 dB`.
3. **Ecualizador Paramétrico Broadcast**: Realza `+1.5 dB` en `180 Hz` (calidez de pecho) y `+1.8 dB` en `3.8 kHz` (claridad y definición).
4. **Compresor Dinámico RMS Soft-Knee (`Ratio 2.5:1`)**: Nivela las diferencias entre susurros y pasajes intensos con ganancia de compensación automática.
5. **Limitador Brickwall True-Peak (`-1.0 dBTP`) + Normalización EBU R128 (`-16 LUFS`)**: Garantiza cero distorsión digital y el volumen estándar exigido por Audible, Spotify y YouTube.

### 7.2 Paisajes Sonoros Estéreo (Soundscapes) y BGM con Auto-Ducking
En el selector **`Ambiente`** puedes elegir entre 5 atmósferas generativas estéreo libres de derechos o cargar tu propia música con el botón **`[...] BGM`**:
- `Ambient Drone Cálido` (Ficción / Lectura inmersiva)
- `Lluvia Nocturna Suave` (Suspenso / Relato íntimo)
- `Cosmos Profundo Binaural` (Ciencia ficción / Filosofía)
- `Armonía Lo-Fi Editorial` (Ensayo / Podcast / Crónica)
- `Tensión Noir Oscura` (Terror / Thriller)

**¿Cómo funciona el Auto-Ducking RMS?** El motor calcula la envolvente de energía de la voz en ventanas de 50 ms: cuando el narrador habla, la música baja automáticamente a `-25 dBFS`; durante las pausas o cambios de capítulo, la música sube suavemente con una curva exponencial de ataque/relajación.

### 7.3 Efectos Foley SFX (`Foley SFX`)
Con **`Foley SFX`** activo:
- Si el texto contiene etiquetas `[sfx:nombre]`, se sintetiza y mezcla el efecto acústico exacto.
- Además, el analizador semántico detecta acciones dramáticas clave (*trueno*, *portazo*, *pasos en el pasillo*, *campanada*, *latidos*, *reloj*, *viento helado*) e inyecta el efecto de forma sutil sin tapar la voz.

### 7.4 Cuñas Intersticiales (Radio / Separadores)
En la sección *Portada y Cuñas Intersticiales* puedes activar **`Insertar cuñas / separadores de audio`** y añadir tantas filas como desees (`Al Inicio`, `Entre Capítulos`, `Entre Párrafos`, `Al Final`), eligiendo para cada cuña su texto, voz, estilo y pausa posterior, y escuchándola al instante con **`[ ► ] Previa`**.""",
        html_body="""
<h3>7.1 Las 5 Etapas de la Cadena de Masterización DSP</h3>
<ol>
  <li><b>Filtro Pasa-Altos (80 Hz):</b> Limpia frecuencias sub-graves parásitas.</li>
  <li><b>De-Esser Dinámico (5.5–9.5 kHz):</b> Suaviza las sibilancias agudas sin apagar el brillo vocal.</li>
  <li><b>EQ Paramétrico Broadcast:</b> Cuerpo cálido en <code>180 Hz</code> (+1.5 dB) y presencia cristalina en <code>3.8 kHz</code> (+1.8 dB).</li>
  <li><b>Compresor RMS Soft-Knee (2.5:1):</b> Empareja el rango dinámico entre susurros y exclamaciones.</li>
  <li><b>Limitador True-Peak (-1.0 dBTP) + EBU R128 (-16 LUFS):</b> Nivel oficial para Audible, Spotify y YouTube.</li>
</ol>

<h3>7.2 Paisajes Sonoros Estéreo y Auto-Ducking</h3>
<p>Selecciona un paisaje sonoro en <b>Ambiente</b> (<i>Ambient Drone</i>, <i>Lluvia Nocturna</i>, <i>Cosmos Binaural</i>, <i>Lo-Fi Editorial</i>, <i>Tensión Noir</i>) o carga tu propio archivo musical con <b><code>[...] BGM</code></b>. El algoritmo de <b>Auto-Ducking</b> reduce automáticamente el volumen de la música cuando el narrador habla y lo eleva en los silencios.</p>

<h3>7.3 Catálogo Completo de Etiquetas Foley SFX</h3>
<p>Puedes usar cualquiera de estas 11 etiquetas en tu texto: <code>[sfx:trueno]</code>, <code>[sfx:lluvia]</code>, <code>[sfx:puerta]</code>, <code>[sfx:pasos]</code>, <code>[sfx:campana]</code>, <code>[sfx:viento]</code>, <code>[sfx:reloj]</code>, <code>[sfx:latido]</code>, <code>[sfx:fuego]</code>, <code>[sfx:alerta_radio]</code> y <code>[sfx:transicion]</code>, o incluso pasar la ruta a un archivo <code>[sfx:C:/ruta/efecto.wav]</code>.</p>
""",
    ),
    ManualSection(
        id="portadas_trailers_formatos",
        code="§ 08",
        nav_line1="§ 08 — Portadas IA y Formatos Master",
        nav_line2="Carátulas 1024px, Trailer 90s y .M4B",
        title="Portadas IA 1024x1024, Trailers de 90s y Formatos Master (.M4B / .MP3 / .FLAC)",
        subtitle="Generación de arte de portada, sinopsis dramatizada y exportación por capítulos.",
        markdown_body="""### 8.1 Portada Editorial IA Automática (`Portada IA 1024x1024`)
Si no seleccionas una imagen manual en el campo *Portada* y dejas marcada la casilla **`Portada IA 1024x1024`**:
- El generador consulta primero si tienes activo un servidor local SD-Turbo (`http://127.0.0.1:8000/generate`).
- Si no está activo, sintetiza algorítmicamente un lienzo de arte digital en **1024×1024 píxeles** mediante campos vectoriales armónicos adaptados a la paleta cromática del género literario, con marco doble de lujo, sello superior, título autoajustado y firma editorial.
- La imagen `cover.png` se guarda en la carpeta del libro y se incrusta automáticamente en el `.mp3`, en el `.m4b` y en el video `.mp4`.

### 8.2 Audio-Trailer Promocional de 90 Segundos (`Trailer 90s`)
Con la casilla **`Trailer 90s`** marcada, GlobalTTS genera automáticamente un archivo adicional llamado **`trailer_sinopsis.mp3`** en la carpeta del libro:
- Redacta un guion promocional cinematográfico basado en los primeros capítulos de la obra (usando Mistral NeMo si está activo o plantillas dramáticas estructuradas).
- Lo sintetiza con estilo de **Locutor de Radio / Trailer**, le inserta efectos de entrada/salida (`[sfx:transicion]`) y le mezcla una atmósfera acústica con Auto-Ducking, ideal para compartir en redes sociales como adelanto del audiolibro.

### 8.3 Formatos de Audio Generados en la Carpeta del Libro
Cada libro procesado crea su propio directorio en `biblioteca/<nombre_del_libro>/` con:
1. **`<libro>.mp3`**: Audiolibro completo en MP3 a 256 kbps normalizado a `-16 LUFS` con etiquetas ID3v2 y carátula incrustada.
2. **`<libro>.m4b`**: Contenedor nativo de audiolibro Apple/Audible con **Índice de Capítulos Interactivo (`FFMETADATA1`)** y portada para saltar de capítulo y recordar la posición de lectura en aplicaciones móviles.
3. **`<libro>_master.flac`**: Master sin pérdida de calidad (Lossless) para archivo editorial.
4. ** Subcarpeta `capitulos/`**: Cuando marcas **`Capítulos MP3`**, exporta cada capítulo por separado (`01_Capitulo_I.mp3`, `02_Capitulo_II.mp3`, etc.).""",
        html_body="""
<h3>8.1 Portada Editorial IA Automática (1024×1024)</h3>
<p>Cuando <b>Portada IA 1024x1024</b> está activa y no especificas una imagen externa, GlobalTTS diseña automáticamente una carátula cuadrada de alta resolución (<code>cover.png</code>) con estética adaptada al género del libro y la incrusta en los metadatos ID3 del MP3, en el contenedor M4B y en el Video Karaoke.</p>

<h3>8.2 Audio-Trailer Promocional (<code>trailer_sinopsis.mp3</code>)</h3>
<p>Al marcar <b>Trailer 90s</b>, el pipeline produce un avance dramático independiente (<code>trailer_sinopsis.mp3</code>) con introducción de impacto, sinopsis comercial y cierre de locutor con fondo musical y efectos cinemáticos.</p>

<h3>8.3 Comparativa de Formatos Exportados</h3>
<table width="100%" cellspacing="0" cellpadding="6" style="border:1px solid #1E293B; background:#0F172A;">
  <tr style="background:#1E293B; color:#38BDF8; font-weight:bold;">
    <td>Formato</td>
    <td>Características Técnicas y Uso Recomendado</td>
  </tr>
  <tr><td><code>.MP3 (256 kbps)</code></td><td>Compatibilidad universal, normalizado EBU R128 (-16 LUFS) con portada ID3v2.</td></tr>
  <tr><td><code>.M4B (Capítulos)</code></td><td>Formato estándar de audiolibros con tabla de capítulos interactiva (<code>START/END</code> ms) para saltar entre capítulos y guardar posición.</td></tr>
  <tr><td><code>capitulos/*.mp3</code></td><td>Pistas MP3 numeradas individualmente por cada capítulo detectado en el documento.</td></tr>
  <tr><td><code>_master.flac</code></td><td>Audio maestro comprimido sin pérdida (Lossless) para preservación de estudio.</td></tr>
</table>
""",
    ),
    ManualSection(
        id="video_karaoke_subtitulos",
        code="§ 09",
        nav_line1="§ 09 — Video Karaoke MP4 (16:9 / 9:16)",
        nav_line2="Audiograma en Vivo y Subtítulos",
        title="Video Karaoke MP4 (16:9 y 9:16), Audiograma & Subtítulos",
        subtitle="Renderizado con espectro de onda en vivo, formato vertical TikTok/Reels y .SRT/.VTT/.LRC.",
        markdown_body="""### 9.1 Modos Visuales de Video Karaoke (`Video`)
Cuando marcas **`Video Karaoke MP4`**, puedes elegir en el desplegable **`Video`** entre 3 motores visuales de FFmpeg:
1. **`Audiograma de Espectro en Vivo (Waveform + Karaoke)`**: Renderiza en tiempo real la onda acústica (`showwaves` en modo `cline` a 24 fps) sincronizada con la voz sobre el lienzo de la portada oscurecida (o fondo Obsidian) más el resaltado palabra por palabra.
2. **`Portada Editorial de Fondo`**: Utiliza la portada del audiolibro escalada y centrada con ajuste de contraste para máxima legibilidad de los subtítulos.
3. **`Lienzo Obsidian / Negro Clásico`**: Pantalla negra de alto contraste con consumo mínimo de recursos y compresión ultrarrápida.

### 9.2 Relación de Aspecto: Horizontal (`16:9`) vs. Vertical (`9:16`)
En el selector **`Ratio`** puedes elegir:
- **`16:9 Horizontal (1920x1080)`**: Formato panorámico Full HD estándar para YouTube, monitores de escritorio y televisores.
- **`9:16 Vertical (1080x1920)`**: Formato vertical nativo diseñado para **TikTok, Instagram Reels y YouTube Shorts**, con márgenes y tamaño tipográfico recalibrados automáticamente.

### 9.3 Los 5 Temas Tipográficos y Archivos de Subtítulos Independientes
En el selector **`Subtítulos`** dispones de 5 estilos cromáticos (`Cian Ejecutivo`, `Amarillo Neón`, `Blanco Editorial`, `Dorado Épico`, `Esmeralda Cyber`). Además del video `.mp4`, GlobalTTS exporta siempre los **4 archivos de subtítulos independientes** en la carpeta del libro:
- **`.ass`**: Subtítulos Advanced SubStation Alpha con etiquetas `\\k` de karaoke sílaba/palabra.
- **`.srt`**: SubRip estándar para subir a YouTube, Vimeo o reproductores VLC/MPC.
- **`.vtt`**: WebVTT estándar para reproductores web HTML5.
- **`.lrc`**: Letras sincronizadas para reproductores de música y móviles.""",
        html_body="""
<h3>9.1 Los 3 Modos Visuales de Video Karaoke</h3>
<ul>
  <li><b>Audiograma de Espectro en Vivo (<code>audiogram</code>):</b> Dibuja la onda de frecuencia de la voz en tiempo real mediante el filtro <code>showwaves</code> de FFmpeg combinada con la portada y el karaoke sílaba por sílaba.</li>
  <li><b>Portada Editorial de Fondo (<code>cover_backdrop</code>):</b> Muestra el arte de portada con atenuación de luminancia para resaltar el texto activo.</li>
  <li><b>Lienzo Obsidian / Negro Clásico (<code>black</code>):</b> Fondo negro puro de máxima nitidez para lectura nocturna.</li>
</ul>

<h3>9.2 Formatos 16:9 (YouTube) y 9:16 (TikTok / Reels / Shorts)</h3>
<p>Selecciona en <b>Ratio</b> entre <code>16:9 Horizontal (1920x1080)</code> o <code>9:16 Vertical (1080x1920)</code>. El motor recalcula automáticamente el tamaño de fuente, posición del espectro de onda y márgenes laterales.</p>

<h3>9.3 Exportación Automática de Subtítulos (<code>.ASS</code>, <code>.SRT</code>, <code>.VTT</code>, <code>.LRC</code>)</h3>
<p>Junto a cada audiolibro se guardan automáticamente los archivos <code>.srt</code>, <code>.vtt</code>, <code>.lrc</code> y <code>.ass</code> para que puedas cargarlos en cualquier plataforma de video o reproductor externo.</p>
""",
    ),
    ManualSection(
        id="biblioteca_reproductor",
        code="§ 10",
        nav_line1="§ 10 — Pestaña 3: Biblioteca & Player",
        nav_line2="Capítulos, Velocidad y Exportación ZIP",
        title="Pestaña 3: Biblioteca & Reproductor Multimedia Avanzado",
        subtitle="Búsqueda instantánea, selector de capítulos/trailer, velocidad 0.75x-2.0x y exportación ZIP.",
        markdown_body="""### 10.1 Organización de la Biblioteca
La pestaña **BIBLIOTECA & REPRODUCTOR** reúne todas tus producciones en dos sub-pestañas:
1. **`AUDIOLIBROS GENERADOS`**: Todos los proyectos completos almacenados en `biblioteca/<libro>/`, mostrando su portada en gran formato a la izquierda y su ficha técnica completa + metadatos a la derecha.
2. **`HISTORIAL DE LECTURAS RÁPIDAS`**: Registro cronológico infinito de todas las lecturas generadas desde la pestaña de Lectura Rápida o atajos.

### 10.2 Buscador Instantáneo y Selector de Pistas / Capítulos
- **Buscador (`Buscar por título, voz o fecha...`)**: Filtra en tiempo real las tablas a medida que escribes.
- **Selector `Pista / Capítulo`**: Al seleccionar un audiolibro, este desplegable se llena automáticamente con:
  * El **Audiolibro Completo (`.mp3` / `.m4b`)**.
  * El **Trailer Promocional de 90s (`trailer_sinopsis.mp3`)** si fue generado.
  * Cada uno de los **Capítulos individuales (`01_...mp3`, `02_...mp3`)** para saltar directamente a cualquier sección.

### 10.3 Controles del Reproductor Multimedia Integrado
- **Conmutador `Escuchar Audio (MP3/M4B)` / `Ver Video Karaoke (MP4)`**: Alterna con un clic entre el reproductor acústico con portada y el visor de video karaoke integrado.
- **Selector de Velocidad (`0.75x` a `2.0x`)**: Modifica en caliente la velocidad de reproducción (`playbackRate`) sin distorsionar el tono.
- **Acciones de Gestión y Exportación**:
  * **`[ ↗ ] Cargar Texto`**: Envía el texto original de la obra de vuelta al editor de *Lectura Rápida*.
  * **`[ ⤓ ] Exportar ZIP`**: Empaqueta toda la carpeta del audiolibro (audios, capítulos, portada, subtítulos, SEO y RSS) en un único archivo `.zip` listo para compartir o respaldar.
  * **`[ ↗ ] Streaming WiFi QR`**: Abre el código QR para escuchar la biblioteca en tu móvil.""",
        html_body="""
<h3>10.1 Navegación Dual: Audiolibros e Historial Infinito</h3>
<p>Alterna entre <b>AUDIOLIBROS GENERADOS</b> y <b>HISTORIAL DE LECTURAS RÁPIDAS</b>. Usa la barra de búsqueda superior para filtrar instantáneamente por título, voz o fecha.</p>

<h3>10.2 Selector de Pistas, Capítulos y Velocidad</h3>
<ul>
  <li><b>Desplegable <code>Pista / Capítulo</code>:</b> Permite elegir entre reproducir la obra completa, el <b>Trailer de 90s</b> o cualquiera de los <b>capítulos individuales</b>.</li>
  <li><b>Velocidad de Reproducción:</b> Ajusta en tiempo real entre <code>0.75x</code>, <code>1.0x</code>, <code>1.25x</code>, <code>1.5x</code>, <code>1.75x</code> y <code>2.0x</code>.</li>
  <li><b><code>[ ⤓ ] Exportar ZIP</code>:</b> Comprime todos los artefactos del libro seleccionado en un paquete <code>.zip</code> portable.</li>
  <li><b><code>[ ↗ ] Cargar Texto</code>:</b> Reabre el texto en la pestaña de <i>Lectura Rápida</i> para editarlo o probar otra voz.</li>
</ul>
""",
    ),
    ManualSection(
        id="distribucion_wifi_seo_rss",
        code="§ 11",
        nav_line1="§ 11 — Distribución WiFi QR & SEO",
        nav_line2="Streaming Móvil, YouTube y RSS 2.0",
        title="Distribución: Streaming Móvil WiFi (QR) & Kit SEO YouTube / Spotify / RSS",
        subtitle="Cómo escuchar en tu teléfono sin cables y cómo publicar en YouTube y Spotify.",
        markdown_body="""### 11.1 Servidor WiFi de Streaming Móvil (`[ ↗ ] WiFi QR`)
GlobalTTS incluye un micro-servidor HTTP multihilo (`src/api/mobile_server.py`) con codificador QR ISO/IEC 18004 nativo:
1. Asegúrate de que tu teléfono móvil y tu PC estén conectados a la **misma red WiFi**.
2. Haz clic en **`[ ↗ ] WiFi QR`** (en la barra superior, en la Biblioteca o al terminar un lote).
3. Apunta con la cámara de tu iPhone o Android al **Código QR** que aparece en pantalla (o abre la dirección `http://192.168.x.x:8765/` en tu navegador móvil).
4. Verás el portal oscuro de **GlobalTTS Studio Mobile** con reproductores HTML5 para cada libro, su Trailer de 90s, descarga directa del `.M4B` con capítulos y reproducción del video Karaoke `.MP4`.
5. **Soporte `HTTP 206 Partial Content` (`Range`)**: Puedes adelantar o retroceder a cualquier minuto de un audiolibro de varias horas en Safari o Chrome móvil de forma instantánea.

### 11.2 Paquete Automatizado SEO para YouTube y Spotify (`youtube_spotify_seo.txt`)
En la carpeta de cada audiolibro generado encontrarás el archivo **`youtube_spotify_seo.txt`**, que contiene listos para copiar y pegar:
- **Título optimizado para CTR y búsqueda orgánica**.
- **Descripción comercial** con ficha técnica y resumen de la obra.
- **Índice de Capítulos con Marcas de Tiempo (`00:00 Capítulo 1...`)**: Calculado al milisegundo exacto para que YouTube divida automáticamente la barra de progreso del video en capítulos.
- **Etiquetas / Tags SEO** separados por comas.

### 11.3 Feed Podcast RSS 2.0 (`podcast_rss.xml`)
Junto al archivo SEO se genera **`podcast_rss.xml`**, un feed XML estándar RSS 2.0 con namespace `<itunes:...>` que incluye título, autor, portada, duración y `<enclosure>` del audio masterizado para importar en gestores de podcasts.""",
        html_body="""
<h3>11.1 Cómo Escuchar tus Audiolibros en el Teléfono vía WiFi QR</h3>
<ol>
  <li>Conecta tu teléfono a la misma red WiFi que tu computadora.</li>
  <li>Haz clic en el botón <b><code>[ ↗ ] WiFi QR</code></b> de la barra superior.</li>
  <li>Escanea el código QR con la cámara de tu móvil. Se abrirá el portal web de <b>GlobalTTS Studio</b> con todos tus audiolibros, trailers y videos karaoke listos para reproducir con soporte <i>HTTP 206 Range</i>.</li>
</ol>

<h3>11.2 Artefactos de Publicación en YouTube y Spotify</h3>
<ul>
  <li><b><code>youtube_spotify_seo.txt</code>:</b> Incluye título optimizado, descripción, etiquetas SEO y la lista exacta de marcas de tiempo (<code>00:00 ...</code>) para activar los capítulos automáticos en la barra de reproducción de YouTube.</li>
  <li><b><code>podcast_rss.xml</code>:</b> Feed XML RSS 2.0 con metadatos iTunes/Spotify para sindicación de podcasts.</li>
</ul>
""",
    ),
    ManualSection(
        id="lexicon_cache_troubleshooting",
        code="§ 12",
        nav_line1="§ 12 — Diccionario Fonético & Caché",
        nav_line2="Reglas Lexicon, SHA-256 y Soporte",
        title="Diccionario Fonético (Lexicon), Caché SHA-256 & Solución de Problemas",
        subtitle="Reglas de pronunciación, optimización de caché en disco y diagnóstico técnico.",
        markdown_body="""### 12.1 Cómo Personalizar la Pronunciación en el Diccionario Fonético (`[ ↗ ] Lexicon`)
Si un libro contiene siglas técnicas (`NVMe`, `SaaS`, `EBITDA`), extranjerismos (`Borges`, `Nietzsche`, `Cache`) o abreviaturas que deseas que la voz pronuncie de una manera específica:
1. Abre **`[ ↗ ] Lexicon`**. Verás más de 45 reglas preconfiguradas (`IA` → *inteligencia artificial*, `GPU` → *ge pe u*, `ONNX` → *ónix*, `s. XXI` → *siglo veintiuno*, `Dr.` → *Doctor*).
2. En el panel **Agregar / Actualizar Regla Fonética**, escribe el término original, cómo debe sonar fonéticamente en español, su categoría y si debe distinguir mayúsculas/minúsculas.
3. Pulsa **`[ + ] Guardar Regla`** y comprueba el resultado al instante en el **Probador de Transformación Fonética en Vivo**.
4. El motor reemplaza únicamente palabras completas fuera de los corchetes `[...]`, por lo que jamás altera etiquetas como `[susurro]` o `[sfx:trueno]`.

### 12.2 Caché Acústica Inteligente SHA-256 (`cache/tts_segments/`)
Cada oración sintetizada se indexa mediante el hash SHA-256 de `(voz, frecuencia, velocidad, ganancia, texto)`. Si vuelves a generar un libro tras corregir un párrafo o reutilizas cuñas radiales, los segmentos idénticos se recuperan del disco en **~0.2 ms** sin repetir la inferencia neuronal. Puedes vaciar la caché en cualquier momento con el botón superior **`[ × ] Caché`**.

### 12.3 Solución Rápida de Problemas Frecuentes
- **El atajo global no responde en una ventana**: Algunas aplicaciones ejecutadas como *Administrador* bloquean hooks estándar; usa `Alt + Espacio` o pulsa `[ ⟳ ] Reiniciar Atajos` en la pestaña 1.
- **Aviso de Mistral NeMo / Ollama no disponible**: Verifica que el servidor local `ollama serve` esté activo en `http://localhost:11434`. Recuerda que los estilos acústicos, el Auto-Casting heurístico, el DSP y las voces Kokoro/Piper funcionan al 100% incluso con Ollama apagado.
- **El teléfono no abre el enlace del código QR**: Asegúrate de que el perfil de red de Windows esté en modo *Red Privada* (no Pública) para permitir conexiones entrantes en el puerto local `8765`.""",
        html_body="""
<h3>12.1 Uso del Diccionario Fonético (<code>[ ↗ ] Lexicon</code>)</h3>
<p>Agrega cualquier sigla, acrónimo, apellido extranjero o abreviatura en el gestor de <b>Lexicon</b>. El reemplazo fonético respeta los límites de palabra y protege intactas todas las etiquetas entre corchetes <code>[...]</code>.</p>

<h3>12.2 Caché Acústica SHA-256</h3>
<p>Los segmentos sintetizados se guardan en <code>cache/tts_segments/</code> indexados por su huella SHA-256. Esto acelera drásticamente las regeneraciones parciales y las cuñas repetidas. Usa el botón <b><code>[ × ] Caché</code></b> en la barra superior cuando desees liberar espacio.</p>

<h3>12.3 Diagnóstico Rápido</h3>
<table width="100%" cellspacing="0" cellpadding="6" style="border:1px solid #1E293B; background:#0F172A;">
  <tr style="background:#1E293B; color:#38BDF8; font-weight:bold;">
    <td width="32%">Situación</td>
    <td>Solución Inmediata</td>
  </tr>
  <tr><td>Atajo de ratón interceptado por un IDE</td><td>Utiliza el atajo alternativo <b><code>Alt + Barra Espaciadora</code></b> o haz clic en <b><code>[ ⟳ ] Reiniciar Atajos</code></b>.</td></tr>
  <tr><td>Ollama / Mistral NeMo desconectado</td><td>Ejecuta <code>ollama serve</code> localmente. Aun sin LLM activo, las voces neurales, estilos acústicos, SFX y DSP operan al 100%.</td></tr>
  <tr><td>QR móvil no carga en el teléfono</td><td>Verifica que PC y móvil estén en la misma red WiFi y que el perfil de red de Windows esté configurado como <i>Red Privada</i>.</td></tr>
</table>
""",
    ),
]


def build_full_markdown_manual() -> str:
    """Construye el documento Markdown completo y lo persiste en MANUAL_DE_USO.md."""
    lines = [
        "# MANUAL DE USO COMPLETO — GLOBALTTS STUDIO (EDICIÓN 2026)",
        "",
        "> **Sistema Integral de Lectura en Vivo, Generación de Audiolibros, Clonación Biométrica, Masterización DSP y Video Karaoke 100% Local**",
        "",
        "---",
        "",
    ]
    for sec in MANUAL_SECTIONS:
        lines.append(f"## {sec.code}. {sec.title}")
        lines.append(f"*{sec.subtitle}*")
        lines.append("")
        lines.append(sec.markdown_body.strip())
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("**HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®**")
    content = "\n".join(lines) + "\n"
    try:
        MANUAL_MD_PATH.write_text(content, encoding="utf-8")
    except Exception:
        pass
    return content


class ManualSpeechWorker(QThread):
    """Hilo en segundo plano para narrar en voz alta cualquier sección del manual."""

    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, plain_text: str, voice_key: str = "kokoro-ef_dora"):
        super().__init__()
        self.plain_text = plain_text
        self.voice_key = voice_key
        self.is_cancelled = False

    def run(self):
        try:
            sd.stop()
            engine = PiperTtsEngine(voice_key=self.voice_key)
            # Limitar a los primeros 1800 caracteres para respuesta ágil
            clean = re.sub(r"[`#*_|>]+", " ", self.plain_text)
            clean = re.sub(r"\s{2,}", " ", clean).strip()[:1800]
            if not clean or self.is_cancelled:
                self.finished_signal.emit()
                return
            samples = engine.synthesize(clean)
            if len(samples) > 128 and not self.is_cancelled:
                samples = master_audio_track(samples, engine.sample_rate, MasteringConfig(enabled=True))
                sd.play(samples, engine.sample_rate)
                sd.wait()
            self.finished_signal.emit()
        except Exception as exc:
            self.error_signal.emit(str(exc))


class ManualTab(QWidget):
    """Pestaña interactiva con el Manual de Uso Completo de GlobalTTS."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.speech_worker: Optional[ManualSpeechWorker] = None
        self.current_orientation = "horizontal"
        build_full_markdown_manual()
        self.init_ui()
        self.select_section(0)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 8, 10, 8)
        self.main_layout.setSpacing(8)

        # Barra de Herramientas Superior del Manual
        top_bar = QFrame()
        top_bar.setObjectName("cardFrame")
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(12, 8, 12, 8)
        top_lay.setSpacing(8)

        lbl_icon = QLabel("[ ≡ ] MANUAL OFICIAL DE USUARIO & ARQUITECTURA")
        lbl_icon.setStyleSheet("color: #38BDF8; font-weight: 800; font-size: 13px; letter-spacing: 0.4px;")
        top_lay.addWidget(lbl_icon)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("[ ⌕ ] Buscar función, atajo, etiqueta SFX, formato (.M4B, QR, DSP, Clonación)...")
        self.search_edit.textChanged.connect(self.on_search_changed)
        top_lay.addWidget(self.search_edit, stretch=1)

        self.btn_read_aloud = QPushButton("[ ► ] Escuchar Capítulo")
        self.btn_read_aloud.setObjectName("actionButton")
        self.btn_read_aloud.setToolTip("Narra en voz alta la sección activa del manual usando la voz neural local")
        self.btn_read_aloud.clicked.connect(self.toggle_read_section_aloud)
        top_lay.addWidget(self.btn_read_aloud)

        self.btn_export_md = QPushButton("[ ⤓ ] Exportar Manual (.MD)")
        self.btn_export_md.setObjectName("secondaryActionButton")
        self.btn_export_md.setToolTip("Guardar una copia completa del manual en formato Markdown")
        self.btn_export_md.clicked.connect(self.export_manual_file)
        top_lay.addWidget(self.btn_export_md)

        self.btn_open_md = QPushButton("[ ↗ ] Abrir Archivo .MD")
        self.btn_open_md.setObjectName("secondaryActionButton")
        self.btn_open_md.setToolTip("Abrir MANUAL_DE_USO.md en el visor del sistema")
        self.btn_open_md.clicked.connect(self.open_root_manual_md)
        top_lay.addWidget(self.btn_open_md)

        self.main_layout.addWidget(top_bar)

        # Splitter adaptable (Horizontal: Índice a la izquierda / Lector a la derecha; Vertical: Índice arriba / Lector abajo)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        # Panel de Índice de Capítulos
        self.index_frame = QFrame()
        self.index_frame.setObjectName("cardFrame")
        idx_lay = QVBoxLayout(self.index_frame)
        idx_lay.setContentsMargins(8, 8, 8, 8)
        idx_lay.setSpacing(6)

        lbl_idx = QLabel("ÍNDICE DE CAPÍTULOS (12 SECCIONES)")
        lbl_idx.setStyleSheet("color: #94A3B8; font-weight: 700; font-size: 11px; letter-spacing: 0.5px;")
        idx_lay.addWidget(lbl_idx)

        self.section_list = QListWidget()
        self.section_list.setWordWrap(True)
        self.section_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.section_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.section_list.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; background: transparent; }")
        self.section_list.horizontalScrollBar().setStyleSheet("QScrollBar:horizontal { height: 0px; background: transparent; }")
        self.section_list.setStyleSheet(
            "QListWidget { background-color: #0B0F19; border: 1px solid #1E293B; border-radius: 6px; padding: 3px; } "
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #161F30; border-radius: 4px; color: #E2E8F0; } "
            "QListWidget::item:selected { background-color: #1E3A8A; color: #38BDF8; font-weight: 700; }"
        )
        self.section_list.currentRowChanged.connect(self.on_section_row_changed)
        idx_lay.addWidget(self.section_list, stretch=1)

        # Panel Visor de Contenido Detallado
        self.viewer_frame = QFrame()
        self.viewer_frame.setObjectName("cardFrame")
        view_lay = QVBoxLayout(self.viewer_frame)
        view_lay.setContentsMargins(12, 10, 12, 10)
        view_lay.setSpacing(6)

        hdr_row = QHBoxLayout()
        self.lbl_sec_title = QLabel("Manual Completo de GlobalTTS Studio")
        self.lbl_sec_title.setStyleSheet("color: #F8FAFC; font-weight: 800; font-size: 16px;")
        hdr_row.addWidget(self.lbl_sec_title)
        hdr_row.addStretch()
        self.lbl_match_count = QLabel("")
        self.lbl_match_count.setStyleSheet("color: #10B981; font-weight: 700; font-size: 12px;")
        hdr_row.addWidget(self.lbl_match_count)
        view_lay.addLayout(hdr_row)

        self.lbl_sec_sub = QLabel("Guía exhaustiva paso a paso de todas las herramientas y flujos de trabajo.")
        self.lbl_sec_sub.setStyleSheet("color: #38BDF8; font-size: 12px; font-weight: 600;")
        view_lay.addWidget(self.lbl_sec_sub)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.browser.verticalScrollBar().setStyleSheet("QScrollBar:vertical { width: 0px; background: transparent; }")
        self.browser.horizontalScrollBar().setStyleSheet("QScrollBar:horizontal { height: 0px; background: transparent; }")
        self.browser.setStyleSheet(
            "QTextBrowser { background-color: #0B0F19; color: #E2E8F0; border: 1px solid #1E293B; "
            "border-radius: 6px; padding: 14px; font-size: 13px; line-height: 1.55; }"
        )
        view_lay.addWidget(self.browser, stretch=1)

        self.splitter.addWidget(self.index_frame)
        self.splitter.addWidget(self.viewer_frame)
        self.splitter.setStretchFactor(0, 28)
        self.splitter.setStretchFactor(1, 72)

        self.main_layout.addWidget(self.splitter, stretch=1)
        self.populate_section_list()

    def populate_section_list(self, filter_query: str = ""):
        self.section_list.blockSignals(True)
        self.section_list.clear()
        q = filter_query.strip().lower()

        # Opción 0: Manual Completo Integrado (en 2 líneas de texto)
        all_item = QListWidgetItem("[ ◈ ] MANUAL COMPLETO\n   Vista Integral de los 12 Capítulos")
        all_item.setData(Qt.ItemDataRole.UserRole, "__ALL__")
        self.section_list.addItem(all_item)

        matched_sections = 0
        for sec in MANUAL_SECTIONS:
            haystack = f"{sec.code} {sec.title} {sec.subtitle} {sec.markdown_body}".lower()
            if q and q not in haystack:
                continue
            matched_sections += 1
            item = QListWidgetItem(f"{sec.nav_line1}\n   {sec.nav_line2}")
            item.setToolTip(f"{sec.code} — {sec.title}\n{sec.subtitle}")
            item.setData(Qt.ItemDataRole.UserRole, sec.id)
            self.section_list.addItem(item)

        self.section_list.blockSignals(False)
        if self.section_list.count() > 1 and q:
            self.section_list.setCurrentRow(1)
        elif self.section_list.count() > 0:
            self.section_list.setCurrentRow(0)

        if q:
            self.lbl_match_count.setText(f"[ {matched_sections} capítulo(s) coinciden con '{filter_query.strip()}' ]")
        else:
            self.lbl_match_count.setText(f"[ {len(MANUAL_SECTIONS)} capítulos documentados ]")

    def select_section(self, row: int):
        if 0 <= row < self.section_list.count():
            self.section_list.setCurrentRow(row)

    def on_section_row_changed(self, row: int):
        if row < 0 or row >= self.section_list.count():
            return
        item = self.section_list.item(row)
        sec_id = item.data(Qt.ItemDataRole.UserRole) if item else "__ALL__"
        self.render_section_content(sec_id, highlight_term=self.search_edit.text().strip())

    def render_section_content(self, sec_id: str, highlight_term: str = ""):
        css = """
        <style>
          body { font-family: 'Segoe UI', 'Inter', sans-serif; color: #E2E8F0; background-color: #0B0F19; }
          h2 { color: #38BDF8; border-bottom: 1px solid #1E293B; padding-bottom: 6px; margin-top: 18px; }
          h3 { color: #F8FAFC; margin-top: 14px; margin-bottom: 6px; }
          p, li { color: #CBD5E1; font-size: 13px; line-height: 1.55; }
          code { background-color: #1E293B; color: #38BDF8; padding: 2px 5px; border-radius: 4px; font-family: Consolas, monospace; }
          table { border-collapse: collapse; width: 100%; margin-top: 8px; margin-bottom: 12px; }
          td { border: 1px solid #1E293B; padding: 7px; font-size: 12px; }
          .sec-badge { color: #10B981; font-weight: bold; font-size: 12px; }
        </style>
        """

        if sec_id == "__ALL__":
            self.lbl_sec_title.setText("Manual de Uso Completo — GlobalTTS Studio (12 Capítulos)")
            self.lbl_sec_sub.setText("Documentación integral de todas las funciones, atajos, motores IA, DSP, M4B, Karaoke y Streaming.")
            blocks = []
            for sec in MANUAL_SECTIONS:
                blocks.append(
                    f"<h2>{html.escape(sec.code)} — {html.escape(sec.title)}</h2>"
                    f"<p class='sec-badge'>{html.escape(sec.subtitle)}</p>"
                    f"{sec.html_body}"
                )
            full_html = f"<html><head>{css}</head><body>{''.join(blocks)}</body></html>"
        else:
            sec = next((s for s in MANUAL_SECTIONS if s.id == sec_id), MANUAL_SECTIONS[0])
            self.lbl_sec_title.setText(f"{sec.code} — {sec.title}")
            self.lbl_sec_sub.setText(sec.subtitle)
            full_html = f"<html><head>{css}</head><body>{sec.html_body}</body></html>"

        self.browser.setHtml(full_html)

        if highlight_term:
            self._highlight_search_term(highlight_term)

    def _highlight_search_term(self, term: str):
        if not term:
            return
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.browser.setTextCursor(cursor)
        self.browser.find(term)

    def on_search_changed(self, text: str):
        self.populate_section_list(text)

    def toggle_read_section_aloud(self):
        if self.speech_worker and self.speech_worker.isRunning():
            self.speech_worker.is_cancelled = True
            try:
                sd.stop()
            except Exception:
                pass
            self.speech_worker.terminate()
            self.speech_worker.wait(300)
            self.speech_worker = None
            self.btn_read_aloud.setText("[ ► ] Escuchar Capítulo")
            return

        plain = f"{self.lbl_sec_title.text()}. {self.lbl_sec_sub.text()}. {self.browser.toPlainText()}"
        self.btn_read_aloud.setText("[ ■ ] Detener Lectura")
        self.speech_worker = ManualSpeechWorker(plain_text=plain)
        self.speech_worker.finished_signal.connect(lambda: self.btn_read_aloud.setText("[ ► ] Escuchar Capítulo"))
        self.speech_worker.error_signal.connect(lambda _: self.btn_read_aloud.setText("[ ► ] Escuchar Capítulo"))
        self.speech_worker.start()

    def export_manual_file(self):
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar Manual Completo de GlobalTTS",
            str(Path.home() / "Desktop" / "MANUAL_DE_USO_GLOBALTTS.md"),
            "Markdown (*.md);;Texto Plano (*.txt)",
        )
        if dest:
            content = build_full_markdown_manual()
            Path(dest).write_text(content, encoding="utf-8")
            QMessageBox.information(
                self,
                "Manual Exportado",
                f"El Manual de Uso Completo se ha exportado correctamente en:\n\n{dest}",
            )

    def open_root_manual_md(self):
        build_full_markdown_manual()
        if MANUAL_MD_PATH.exists():
            os.startfile(str(MANUAL_MD_PATH))

    def set_orientation(self, mode: str):
        """Ajusta el divisor del manual según la orientación Horizontal o Vertical de la pantalla."""
        self.current_orientation = mode
        if mode == "vertical":
            self.splitter.setOrientation(Qt.Orientation.Vertical)
            self.index_frame.setMaximumHeight(230)
            self.index_frame.setMaximumWidth(16777215)
            self.splitter.setSizes([200, 750])
        else:
            self.splitter.setOrientation(Qt.Orientation.Horizontal)
            self.index_frame.setMaximumHeight(16777215)
            self.index_frame.setMaximumWidth(420)
            self.splitter.setSizes([340, 960])
