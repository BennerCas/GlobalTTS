# MANUAL DE USO COMPLETO — GLOBALTTS STUDIO (EDICIÓN 2026)

> **Sistema Integral de Lectura en Vivo, Generación de Audiolibros, Clonación Biométrica, Masterización DSP y Video Karaoke 100% Local**

---

## § 01. Visión General, Arquitectura 100% Local & Telemetría
*Inferencia sin nube, aceleración DirectML/Olive, iGPU ROCm y barra superior de estado.*

### 1.1 Filosofía Operativa: 100% Local, Privacidad Absoluta y Costo Cero
**GlobalTTS Studio** es una suite integral de ingeniería de voz, producción de audiolibros, masterización acústica DSP y renderizado de video karaoke que opera **100% en tu hardware local**, sin depender de APIs de pago en la nube ni enviar tus documentos fuera de tu equipo.

### 1.2 Aceleración de Hardware DirectML, Olive y ROCm
La aplicación configura automáticamente los parámetros óptimos de inferencia al iniciar:
- **Backend Principal ONNX Runtime / DirectML**: Ejecución directa de modelos cuantizados (`int8`/`fp16`).
- **Límite Dinámico de VRAM (`OLIVE_GPU_MEMORY_LIMIT = 25GB`)**: Garantiza estabilidad en sesiones largas de generación en lote.
- **Hilos de Inferencia CPU (`OLIVE_CPU_THREADS = 12`)**: Paralelismo óptimo para síntesis fonética y procesamiento DSP SciPy.
- **Aceleración iGPU AMD RDNA3 (`OLLAMA_IGPU_ENABLE = 1` y `HSA_OVERRIDE_GFX_VERSION = 11.0.0`)**: Inyección automática para que **Mistral NeMo 12B** acelere por hardware vía `llama.cpp`.
- **Puente Central de Modelos (`C:\antigravityAS\Modelos -ai-brains`)**: Todos los cerebros neuronales (`Kokoro-82M`, `Piper ONNX`, `CosyVoice3 campplus.onnx`, `Mistral NeMo`) se consumen desde el repositorio central sin duplicar archivos.

### 1.3 Barra Superior de Telemetría y Accesos Rápidos de Estudio
En la parte superior de la ventana principal encontrarás:
1. **Monitor de Hardware en Vivo (`[ HW: ... ]`)**: Se actualiza cada 2 segundos mostrando el proveedor activo (`DirectML` o `ONNX-CPU(12T)`), porcentaje de uso de **CPU**, consumo de **RAM** (`GB usados / GB totales`), tope de **VRAM (`25GB`)** y la tasa de aciertos de la **Caché Acústica SHA-256**.
2. **`[ ↗ ] WiFi QR`**: Abre el servidor local de streaming móvil con código QR escaneable.
3. **`[ ↗ ] Lexicon`**: Abre el gestor del Diccionario Fonético y pronunciación de siglas.
4. **`[ ★ ] Clonar Voz`**: Abre el laboratorio de clonación biométrica de voz local.
5. **`[ × ] Caché`**: Purga los segmentos `.npy` almacenados en la caché de disco.
6. **`[ ? ] Manual`**: Te lleva directamente a esta pestaña de documentación interactiva.
7. **`[ ↕ ] Modo: Auto / Vertical / Horizontal`**: Alterna la maquetación completa de la interfaz entre monitores panorámicos (`16:9`) y monitores verticales (retrato) sin perder un solo control.
8. **`[ _ ] Minimizar`**: Oculta la ventana en la bandeja del sistema (System Tray) manteniendo activos los atajos globales.

---

## § 02. Atajos Globales del Sistema (AutoHotkey v2 & Captura en Vivo)
*Cómo leer en voz alta o exportar a MP3 cualquier texto seleccionado en Windows.*

### 2.1 Cómo Funcionan los Atajos Globales
El servicio residente `global_tts.ahk` (AutoHotkey v2) escucha tus gestos de teclado y ratón en todo el sistema operativo (navegadores web, visores PDF, Word, Notion, terminales o editores de código) y envía el texto seleccionado al motor neuronal local `speak_selection.py`.

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
Si en algún momento cierras AutoHotkey desde el Administrador de Tareas, simplemente haz clic en el botón **`[ ⟳ ] Reiniciar Atajos`** dentro de la sección *Atajos Globales Activos*.

---

## § 03. Pestaña 1: Lectura Rápida & Configuración Profesional
*Editor en vivo, inserción de etiquetas prosódicas/SFX, historial infinito y ajustes del sistema.*

### 3.1 El Editor de Lectura en Tiempo Real
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
Cada vez que pulsas **`[ ► ] Leer en Voz Alta`**, el audio generado se registra automáticamente en el **Historial Infinito** (`biblioteca/_historial_lecturas/`), quedando disponible de inmediato en la pestaña **Biblioteca & Reproductor** para volver a escucharlo cuando quieras sin tener que regenerarlo.

---

## § 04. Pestaña 2: Generador de Audiolibros, OCR & Cola en Lote
*Ingesta de PDF/EPUB/TXT/Imágenes OCR/URLs, limpieza editorial y control de cola.*

### 4.1 Formatos de Entrada Soportados
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
- **Cancelar Cola (`[ ■ ] Cancelar`)**: Detiene limpiamente el procesamiento en lote sin corromper los archivos ya terminados.

---

## § 05. Voces Neurales (24kHz), Auto-Casting Multi-Voz & Clonación Biométrica
*Catálogo de 15 voces base, reparto automático de diálogos y clonación con campplus.onnx.*

### 5.1 Motores de Voz Integrados (Kokoro 24kHz Studio & Piper ONNX)
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
4. La nueva voz aparecerá inmediatamente en todos los selectores bajo el prefijo **`Clon IA: ...`** lista para probarse o narrar libros completos.

---

## § 06. Expresividad, Narración IA (Mistral NeMo 12B) & Prompts Maestros
*Los 4 modos de IA, los 9 estilos narrativos y el editor de Prompts Maestros.*

### 6.1 Cómo Activar el Motor Narrativo Local (Mistral NeMo 12B)
Tanto en *Lectura Rápida* como en el *Generador de Audiolibros* puedes activar la casilla **`Activar análisis con IA (Mistral NeMo 12B local)`**. Además, incluso si no activas la reescritura por LLM, el **Estilo** seleccionado aplica su perfil acústico real (velocidad, ganancia dB y pausas) directamente sobre el sintetizador.

### 6.2 Los 4 Modos de Procesamiento IA
1. **Enriquecer Expresividad (`enhance`)**: Respeta el 100% de las palabras originales del autor e inyecta estratégicamente etiquetas de dirección acústica (`[pausa]`, `[lento]`, `[rápido]`, `[énfasis]`, `[susurro]`, `[risa]`, `[suspiro]`).
2. **Modo Narrador Completo (`rewrite`)**: Transforma el texto en una narración oral inmersiva adaptando la **Perspectiva Gramatical** (`1ra Persona Yo`, `2da Persona Tú`, `3ra Persona Él/Ella`), el **Tiempo Verbal** (`Pasado`, `Presente`, `Presente Continuo`, `Futuro`) y el **Estilo Literario**.
3. **Traducción y Adaptación (`translate`)**: Traduce textos de otros idiomas al Español Neutro (`es-LA`) literario cuidando la eufonía y el ritmo hablado.
4. **Detección y Clasificación de Diálogos (`dialogue_analysis`)**: Analiza la estructura dramática del capítulo y devuelve los segmentos etiquetados por hablante y emoción para el motor de Auto-Casting.

### 6.3 Catálogo de los 9 Estilos Narrativos y su Efecto Acústico Real
| Estilo | Perfil Narrativo | Modulación Acústica Real |
| :--- | :--- | :--- |
| **Cuentacuentos (`cuento`)** | Cálido, envolvente, tradición oral | Velocidad `0.94x`, pausas `+35%`, calidez `+1.0 dB` |
| **Locutor de Radio (`locutor_radio`)** | Dinámico, sonrisa vocal, punch FM | Velocidad `1.06x`, compresión y presencia `+2.5 dB` |
| **Terror y Suspenso (`terror`)** | Atmosférico, tenso, silencios largos | Velocidad `0.86x`, pausas `+60%`, tono sombrío `-1.5 dB` |
| **Épico y Cinematográfico (`epico`)** | Solemne, heroico, gran proyección | Velocidad `0.92x`, ganancia `+2.0 dB`, pausas `+40%` |
| **Ciencia Ficción (`ciencia_ficcion`)** | Preciso, futurista, analítico | Velocidad `0.98x`, articulación cristalina `+1.0 dB` |
| **Ensayo Filosófico (`ensayo`)** | Reflexivo, sereno, didáctico | Velocidad `0.93x`, pausas meditativas `+35%` |
| **Crónica Histórica (`historia`)** | Documental, riguroso, evocador | Velocidad `0.95x`, equilibrio tonal clásico |
| **Declamación Poética (`poesia`)** | Lírico, cadencioso, íntimo | Velocidad `0.85x`, pausas de verso `+65%` |
| **Drama Intenso (`drama`)** | Emotivo, visceral, alto contraste | Velocidad `0.94x`, rango dinámico expandido `+1.5 dB` |

### 6.4 Pestaña 4: Gestor de Prompts Maestros & Estilos IA
En la pestaña **PROMPTS MAESTROS & ESTILOS IA** puedes inspeccionar, editar, crear nuevos estilos o modificar los *System Prompts* bajo arquitectura CO-STAR / XML-Framing. Todo cambio se sincroniza bidireccionalmente con `config/prompts_library.json` y con el documento maestro `PROMPTS_MAESTROS.md`.

---

## § 07. Ingeniería Acústica: Masterización DSP, Soundscapes, SFX & Cuñas
*Cadena DSP de 5 etapas, música ambiental con Auto-Ducking, Foley SFX y cuñas radiales.*

### 7.1 Cadena de Masterización DSP de Estudio (5 Etapas)
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
En la sección *Portada y Cuñas Intersticiales* puedes activar **`Insertar cuñas / separadores de audio`** y añadir tantas filas como desees (`Al Inicio`, `Entre Capítulos`, `Entre Párrafos`, `Al Final`), eligiendo para cada cuña su texto, voz, estilo y pausa posterior, y escuchándola al instante con **`[ ► ] Previa`**.

---

## § 08. Portadas IA 1024x1024, Trailers de 90s y Formatos Master (.M4B / .MP3 / .FLAC)
*Generación de arte de portada, sinopsis dramatizada y exportación por capítulos.*

### 8.1 Portada Editorial IA Automática (`Portada IA 1024x1024`)
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
4. ** Subcarpeta `capitulos/`**: Cuando marcas **`Capítulos MP3`**, exporta cada capítulo por separado (`01_Capitulo_I.mp3`, `02_Capitulo_II.mp3`, etc.).

---

## § 09. Video Karaoke MP4 (16:9 y 9:16), Audiograma & Subtítulos
*Renderizado con espectro de onda en vivo, formato vertical TikTok/Reels y .SRT/.VTT/.LRC.*

### 9.1 Modos Visuales de Video Karaoke (`Video`)
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
- **`.ass`**: Subtítulos Advanced SubStation Alpha con etiquetas `\k` de karaoke sílaba/palabra.
- **`.srt`**: SubRip estándar para subir a YouTube, Vimeo o reproductores VLC/MPC.
- **`.vtt`**: WebVTT estándar para reproductores web HTML5.
- **`.lrc`**: Letras sincronizadas para reproductores de música y móviles.

---

## § 10. Pestaña 3: Biblioteca & Reproductor Multimedia Avanzado
*Búsqueda instantánea, selector de capítulos/trailer, velocidad 0.75x-2.0x y exportación ZIP.*

### 10.1 Organización de la Biblioteca
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
  * **`[ ↗ ] Streaming WiFi QR`**: Abre el código QR para escuchar la biblioteca en tu móvil.

---

## § 11. Distribución: Streaming Móvil WiFi (QR) & Kit SEO YouTube / Spotify / RSS
*Cómo escuchar en tu teléfono sin cables y cómo publicar en YouTube y Spotify.*

### 11.1 Servidor WiFi de Streaming Móvil (`[ ↗ ] WiFi QR`)
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
Junto al archivo SEO se genera **`podcast_rss.xml`**, un feed XML estándar RSS 2.0 con namespace `<itunes:...>` que incluye título, autor, portada, duración y `<enclosure>` del audio masterizado para importar en gestores de podcasts.

---

## § 12. Diccionario Fonético (Lexicon), Caché SHA-256 & Solución de Problemas
*Reglas de pronunciación, optimización de caché en disco y diagnóstico técnico.*

### 12.1 Cómo Personalizar la Pronunciación en el Diccionario Fonético (`[ ↗ ] Lexicon`)
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
- **El teléfono no abre el enlace del código QR**: Asegúrate de que el perfil de red de Windows esté en modo *Red Privada* (no Pública) para permitir conexiones entrantes en el puerto local `8765`.

---

**HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®**
