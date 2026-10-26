"""Motor OCR Local Acelerado para PDFs Escaneados e Imágenes.

Utiliza el motor nativo de Windows WinRT (`Windows.Media.Ocr.OcrEngine`) con soporte
para español (`es-ES`, `es-MX`) e inglés (`en-US`), ejecutándose 100% offline y sin
dependencias externas pesadas. Convierte imágenes (`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`)
y páginas de PDF sin capa de texto en estructuras `Document` listas para síntesis TTS.
"""
from __future__ import annotations

import base64
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image

from src.core.language import detect_language
from src.core.models import Chapter, Document, DocumentError, ScannedPdfError
from src.ingest.common import group_into_chapters, sha256_file, unwrap_lines

logger = logging.getLogger("globaltts.ocr_engine")

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})

_PS_OCR_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

Function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Foundation.IAsyncOperation`1,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Globalization.Language,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null

$imgPath = "{IMAGE_PATH}"
$langTag = "{LANG_TAG}"

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imgPath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$lang = New-Object Windows.Globalization.Language($langTag)
if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($lang)) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
} else {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) {
    Write-Output $line.Text
}
$stream.Dispose()
"""


def ocr_image_file(image_path: Path, lang: str = "es-ES", timeout: int = 30) -> str:
    """Extrae texto de un archivo de imagen usando Windows.Media.Ocr (WinRT nativo)."""
    path = Path(image_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Imagen no encontrada para OCR: {path}")

    # Si es webp o formato no soportado directamente por WinRT decoder, convertir a PNG temporal
    temp_png: Optional[Path] = None
    target_path = path
    if path.suffix.lower() in {".webp"}:
        fd, tmp_name = tempfile.mkstemp(suffix=".png", prefix="globaltts_ocr_")
        import os
        os.close(fd)
        temp_png = Path(tmp_name)
        with Image.open(path) as im:
            im.convert("RGB").save(temp_png, format="PNG")
        target_path = temp_png

    try:
        escaped_path = str(target_path).replace('"', '`"')
        ps_code = _PS_OCR_TEMPLATE.replace("{IMAGE_PATH}", escaped_path).replace("{LANG_TAG}", lang)
        encoded_cmd = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")

        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_cmd],
            capture_output=True,
            timeout=timeout,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.decode("utf-8", errors="ignore").strip()
            logger.warning("Advertencia en WinRT OCR (%s): %s", path.name, err_msg)
            return ""

        text = proc.stdout.decode("utf-8", errors="ignore").strip()
        return text
    except Exception as exc:
        logger.warning("Fallo ejecutando OCR local sobre %s: %s", path.name, exc)
        return ""
    finally:
        if temp_png and temp_png.exists():
            try:
                temp_png.unlink()
            except OSError:
                pass


def ocr_pdf_page(page, dpi: int = 200, lang: str = "es-ES") -> str:
    """Renderiza una página de PyMuPDF (fitz.Page) a imagen y ejecuta OCR local."""
    import os
    fd, tmp_name = tempfile.mkstemp(suffix=".png", prefix="globaltts_pdfpage_")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        pix.save(str(tmp_path))
        return ocr_image_file(tmp_path, lang=lang)
    except Exception as exc:
        logger.warning("Fallo en OCR de página PDF: %s", exc)
        return ""
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def read_image_document(path: Path) -> Document:
    """Convierte una imagen escaneada (.png, .jpg, .webp, .bmp) en un Document estructurado."""
    raw_text = ocr_image_file(path)
    if not raw_text.strip():
        raise DocumentError(f"No se pudo detectar texto legible mediante OCR en la imagen: {path.name}")

    paragraphs = [unwrap_lines(b) for b in raw_text.split("\n\n") if unwrap_lines(b)]
    if not paragraphs:
        paragraphs = [unwrap_lines(line) for line in raw_text.splitlines() if unwrap_lines(line)]

    if not paragraphs:
        raise DocumentError(f"La imagen no contiene texto válido: {path.name}")

    title = path.stem
    chapters = group_into_chapters(paragraphs, default_title=title)
    sample = " ".join(p for c in chapters for p in c.paragraphs)[:4000]

    return Document(
        title=title,
        author="",
        language=detect_language(sample),
        chapters=chapters,
        source_path=str(path.resolve()),
        source_sha256=sha256_file(path),
    )
