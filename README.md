# GlobalTTS — Sistema Integral de Text-to-Speech y Audiolibros

Sistema avanzado de Text-to-Speech (TTS) local de grado industrial, diseñado para lectura en vivo del portapapeles, conversión de libros completos (.txt, .pdf, .epub) a audiolibros continuos en un solo archivo de audio de alta fidelidad, y generación audiovisual sincronizada (video con pantalla negra y subtítulos estilo karaoke).

---

## 🚀 Capacidades Principales

1. **Lectura Instantánea Global (Portapapeles):**
   - Atajos globales en Windows (AutoHotkey v2 + Python) para escuchar cualquier texto seleccionado al instante (`Alt + Espacio` o `Click Izquierdo + Espacio`).
   - Control de velocidad dinámico al vuelo con la rueda del ratón (`WheelUp` / `WheelDown`).

2. **Conversor de Documentos a Audiolibros (Capacidad Ebooks):**
   - Soporte nativo para formatos `.txt`, `.md`, `.pdf` (con capa de texto y extracción estructurada sin números de página ni encabezados ruidosos) y `.epub` (parseo seguro por capítulos y spine).
   - Generación del audio en un **único archivo continuo**, sin interrupciones, procesado en streaming para no saturar memoria RAM en libros de cientos de páginas.
   - Normalización de sonoridad profesional **EBU R128 (-16 LUFS)** para un volumen parejo en toda la obra.

3. **Formato Audiovisual (Video Karaoke en Pantalla Negra):**
   - Generación de video MP4 (1080p a 24 fps con pantalla negra).
   - Subtítulos avanzados `.ass` sincronizados palabra por palabra con efecto **Karaoke** (`\k`).
   - Permite escuchar el libro y leer el texto en tiempo real con resaltado dinámico.

4. **Lenguaje de Instrucciones y Etiquetas de Voz:**
   - Modulación emocional y de prosodia mediante etiquetas en el texto:
     - `[pausa:1.2s]` o `[pausa:400ms]`: silencios exactos para pausas dramáticas o respiración.
     - `[lento]...[/lento]`: lectura reflexiva o pausada (speed < 1.0).
     - `[rapido]...[/rapido]`: narración ágil o enérgica (speed > 1.0).
     - `[susurro]...[/susurro]`: reducción de ganancia y volumen tenue.
     - `[enfasis]...[/enfasis]`: realce de volumen y presencia.
     - `[voz:nombre]...[/voz]`: cambio de voz para diálogos o personajes.
   - **Tolerancia a fallos:** Cualquier etiqueta desconocida o mal cerrada se descarta limpiamente y **jamás** es leída en voz alta por el sintetizador.

5. **Icono Residente en la Bandeja del Sistema (System Tray):**
   - Icono en la barra de herramientas de Windows con menú contextual (clic derecho / anticlic):
     - **Cargar archivo (Libro / Documento)...**
     - **Abrir Biblioteca de Audios**
     - **Salir**
   - Pop-up rectangular estilizado con modo oscuro Glassmorphism (`DISENO.md`):
     - Muestra el documento cargado.
     - Permite editar el nombre de salida.
     - Permite elegir la voz narradora entre las instaladas localmente.
     - Permite seleccionar la carpeta de destino.
     - Permite elegir los formatos de exportación (Audio MP3, Video Karaoke MP4 o ambos).
     - Barra de progreso en tiempo real con monitoreo por elocución.

6. **100% Local y Costo Cero:**
   - Modelos de inferencia ONNX basados en Piper / VITS (`sherpa-onnx`) alojados en `C:\antigravityAS\Modelos -ai-brains\`.
   - Rendimiento ultra-rápido: Factor de Tiempo Real (RTF) menor a `0.04` (genera 1 hora de audio en menos de 2.5 minutos de CPU).

---

## 📁 Estructura del Proyecto (`ESTRUCTURA.md`)

```text
GlobalTTS/
├── src/
│   ├── main/           # Puntos de entrada (CLI y lanzador del tray)
│   ├── core/           # Modelos de datos, limpieza de texto, detección de idioma, orquestador de jobs
│   ├── ingest/         # Lectores especializados (txt_reader, pdf_reader, epub_reader, loader)
│   ├── markup/         # Parser de etiquetas de voz y AST de estilos
│   ├── ai/             # Motor TTS local Piper (Sherpa-ONNX)
│   ├── audio/          # Ensamblador de audio en streaming y renderizador de video karaoke
│   └── ui/             # Bandeja del sistema (PyQt6), pop-up y estilos Dark Glassmorphism
├── biblioteca/         # Repositorio de audiolibros, videos y metadatos generados
├── tests/              # Suite completa de pruebas unitarias y de integración E2E
├── scripts/            # Scripts de análisis y benchmarks
├── INICIAR_TTS.bat     # Lanzador principal (AutoHotkey + Bandeja de Audiolibros)
├── DETENER_TTS.bat     # Detención limpia de todos los procesos
└── pytest.ini          # Configuración de pruebas
```

---

## 📊 Convención de Metadatos Obligatoria

Todo archivo producido en `biblioteca/` sigue la nomenclatura:
`YYYYMMDD_HHMMSS_[Tipo]_[NombreBreve].[ext]`

Junto a cada archivo generado se almacena un archivo JSON complementario con:
- `job_id`: Identificador único.
- `model_name`: Modelo de síntesis utilizado.
- `voice_key`: Voz seleccionada.
- `parameters`: Configuración de bitrate, loudness y velocidad.
- `source_file` y `source_sha256`: Trazabilidad completa del archivo de origen.
- `total_characters` y `total_utterances`: Métricas de texto.
- `duration_seconds` y `latency_seconds`: Métricas de audio e inferencia.

---

## 🛠️ Ejecución y Uso

### Iniciar el Servicio
Hacer doble clic en `INICIAR_TTS.bat`.
Aparecerá el ícono de **GlobalTTS** en la bandeja del sistema (junto al reloj de Windows).

### Cargar un Libro / Documento
1. Hacer clic derecho sobre el ícono de GlobalTTS en la bandeja del sistema.
2. Seleccionar **"📄 Cargar archivo (Libro / Documento)..."**.
3. Elegir un archivo `.txt`, `.pdf`, `.epub` o `.md`.
4. En el pop-up que aparece:
   - Configurar el nombre y la voz narradora deseada.
   - Seleccionar si deseas Audio (MP3), Video con Karaoke (MP4) o ambos.
   - Pulsar **"Iniciar Generación"**.

### Modo Consola (CLI)
Para procesar documentos por terminal:
```bash
python src/main/cli.py "ruta/a/mi_libro.epub" --voice es_MX-claude-high
```
Para listar las voces locales disponibles:
```bash
python src/main/cli.py --list-voices
```

### Ejecutar Pruebas
```bash
python -m pytest tests -v
```

---

HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®
