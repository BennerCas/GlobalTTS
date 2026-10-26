"""Micro-Servidor Local de Streaming para Móviles (WiFi / HTTP Range 206 + Generador QR Nativo).

Levanta un servidor HTTP multihilo en la red local WiFi que sirve todos los audiolibros,
capítulos, trailers y videos karaoke con soporte de `Range: bytes=...` (`206 Partial Content`)
para reproducción y búsqueda instantánea en iOS Safari y Android Chrome.
Incluye un codificador QR ISO/IEC 18004 (Reed-Solomon GF(256)) 100% nativo en Python + Pillow.
"""
from __future__ import annotations

import html
import io
import json
import logging
import mimetypes
import os
import re
import socket
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

logger = logging.getLogger("globaltts.mobile_server")

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent.parent / "biblioteca"


def get_lan_ip() -> str:
    """Obtiene la dirección IP privada de la interfaz WiFi/LAN activa."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
    except Exception:
        return "127.0.0.1"


# ==============================================================================
# Codificador QR ISO/IEC 18004 Nativo (Byte Mode, Versiones 1 a 4, Nivel L)
# ==============================================================================
# Capacidad máxima de bytes en Nivel L para versiones 1..4: V1=17, V2=32, V3=53, V4=78
_QR_VER_INFO = {
    1: (21, 19, 7, []),
    2: (25, 34, 10, [6, 18]),
    3: (29, 55, 15, [6, 22]),
    4: (33, 80, 20, [6, 26]),
}


def _gf_mul(x: int, y: int) -> int:
    res = 0
    while y:
        if y & 1:
            res ^= x
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
        y >>= 1
    return res


def _rs_generator_poly(nsym: int) -> list[int]:
    g = [1]
    for i in range(nsym):
        p = [1, 1]
        # 2^i en GF(256)
        root = 1
        for _ in range(i):
            root = _gf_mul(root, 2)
        p[1] = root
        new_g = [0] * (len(g) + 1)
        for j, gj in enumerate(g):
            new_g[j] ^= gj
            new_g[j + 1] ^= _gf_mul(gj, p[1])
        g = new_g
    return g


def _rs_encode(data: list[int], nsym: int) -> list[int]:
    gen = _rs_generator_poly(nsym)
    res = list(data) + [0] * nsym
    for i in range(len(data)):
        coef = res[i]
        if coef != 0:
            for j in range(1, len(gen)):
                res[i + j] ^= _gf_mul(gen[j], coef)
    return res[len(data) :]


def generate_qr_image(text: str, box_size: int = 8, border: int = 4) -> Image.Image:
    """Genera una imagen QR estándar ISO/IEC 18004 escaneable por cualquier cámara móvil."""
    raw = text.encode("utf-8")
    ver = 2 if len(raw) <= 32 else (3 if len(raw) <= 53 else 4)
    if len(raw) > 78:
        raw = raw[:78]
    size, total_data_cw, ec_cw, align_pos = _QR_VER_INFO[ver]

    # Construir flujo de bits: Modo Byte (0100) + Longitud (8 bits) + Datos + Terminador
    bits: list[int] = [0, 1, 0, 0]
    for i in range(7, -1, -1):
        bits.append((len(raw) >> i) & 1)
    for b in raw:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    for _ in range(min(4, total_data_cw * 8 - len(bits))):
        bits.append(0)
    while len(bits) % 8 != 0:
        bits.append(0)

    codewords: list[int] = []
    for i in range(0, len(bits), 8):
        byte_val = 0
        for bit in bits[i : i + 8]:
            byte_val = (byte_val << 1) | bit
        codewords.append(byte_val)

    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(codewords) < total_data_cw:
        codewords.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    ec_bytes = _rs_encode(codewords, ec_cw)
    all_cw = codewords + ec_bytes
    all_bits: list[int] = []
    for b in all_cw:
        for i in range(7, -1, -1):
            all_bits.append((b >> i) & 1)

    matrix: list[list[Optional[int]]] = [[None] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_mod(r: int, c: int, val: int, res: bool = True) -> None:
        if 0 <= r < size and 0 <= c < size:
            matrix[r][c] = val
            if res:
                reserved[r][c] = True

    # Patrones de búsqueda (Finder patterns) + separadores
    for fr, fc in ((0, 0), (0, size - 7), (size - 7, 0)):
        for r in range(-1, 8):
            for c in range(-1, 8):
                if 0 <= fr + r < size and 0 <= fc + c < size:
                    if 0 <= r <= 6 and 0 <= c <= 6:
                        is_dark = r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)
                        set_mod(fr + r, fc + c, 1 if is_dark else 0)
                    else:
                        set_mod(fr + r, fc + c, 0)

    # Patrones de alineación
    for ar in align_pos:
        for ac in align_pos:
            if reserved[ar][ac]:
                continue
            for r in range(-2, 3):
                for c in range(-2, 3):
                    is_dark = abs(r) == 2 or abs(c) == 2 or (r == 0 and c == 0)
                    set_mod(ar + r, ac + c, 1 if is_dark else 0)

    # Patrones de sincronización (Timing patterns)
    for i in range(8, size - 8):
        if not reserved[6][i]:
            set_mod(6, i, 1 if i % 2 == 0 else 0)
        if not reserved[i][6]:
            set_mod(i, 6, 1 if i % 2 == 0 else 0)

    # Módulo oscuro fijo y reserva de información de formato
    set_mod(4 * ver + 9, 8, 1)
    for i in range(9):
        if not reserved[8][i]:
            set_mod(8, i, 0)
        if not reserved[i][8]:
            set_mod(i, 8, 0)
    for i in range(8):
        if not reserved[8][size - 1 - i]:
            set_mod(8, size - 1 - i, 0)
        if not reserved[size - 1 - i][8]:
            set_mod(size - 1 - i, 8, 0)

    # Colocar bits de datos en zigzag de abajo hacia arriba
    bit_idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c_off in (0, -1):
                cc = col + c_off
                if not reserved[r][cc]:
                    val = all_bits[bit_idx] if bit_idx < len(all_bits) else 0
                    bit_idx += 1
                    # Aplicar máscara 0: (r + cc) % 2 == 0
                    if (r + cc) % 2 == 0:
                        val ^= 1
                    matrix[r][cc] = val
        upward = not upward
        col -= 2

    # Información de formato precalculada para Nivel L (01) + Máscara 0 (000) -> 0x77C4
    fmt_bits = [(0x77C4 >> i) & 1 for i in range(14, -1, -1)]
    fmt_coords_1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    fmt_coords_2 = [
        (size - 1, 8), (size - 2, 8), (size - 3, 8), (size - 4, 8), (size - 5, 8), (size - 6, 8), (size - 7, 8),
        (8, size - 8), (8, size - 7), (8, size - 6), (8, size - 5), (8, size - 4), (8, size - 3), (8, size - 2), (8, size - 1),
    ]
    for idx, bit in enumerate(fmt_bits):
        r1, c1 = fmt_coords_1[idx]
        r2, c2 = fmt_coords_2[idx]
        matrix[r1][c1] = bit
        matrix[r2][c2] = bit

    total_px = (size + border * 2) * box_size
    img = Image.new("RGB", (total_px, total_px), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    for r in range(size):
        for c in range(size):
            if matrix[r][c] == 1:
                x0 = (c + border) * box_size
                y0 = (r + border) * box_size
                draw.rectangle((x0, y0, x0 + box_size - 1, y0 + box_size - 1), fill=(11, 15, 25))
    return img


class _StreamingRequestHandler(BaseHTTPRequestHandler):
    output_root: Path = DEFAULT_OUTPUT_ROOT

    def log_message(self, format: str, *args) -> None:
        pass  # Silenciar logs HTTP estándar en consola

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        rel_path = urllib.parse.unquote(parsed.path)

        if rel_path in ("/", "/index.html"):
            self._serve_portal()
            return

        if rel_path.startswith("/media/"):
            sub = rel_path[len("/media/") :]
            target = (self.output_root / sub).resolve()
            if not str(target).startswith(str(self.output_root.resolve())) or not target.is_file():
                self.send_error(404, "Archivo no encontrado")
                return
            self._serve_file_with_range(target)
            return

        self.send_error(404, "Ruta no encontrada")

    def _serve_portal(self) -> None:
        cards_html: list[str] = []
        if self.output_root.exists():
            projects = sorted(
                [d for d in self.output_root.iterdir() if d.is_dir() and d.name != "covers"],
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
            for proj in projects:
                title = proj.name.replace("_", " ").title()
                meta_files = list(proj.glob("*_metadata.json")) + list(proj.glob("metadata.json"))
                if meta_files:
                    try:
                        m = json.loads(meta_files[0].read_text(encoding="utf-8"))
                        title = m.get("title") or m.get("source_file") or title
                        if isinstance(title, str) and ("/" in title or "\\" in title):
                            title = Path(title).stem.replace("_", " ").title()
                    except Exception:
                        pass

                mp3_candidates = [p for p in proj.glob("*.mp3") if p.name != "trailer_sinopsis.mp3"]
                m4b_candidates = list(proj.glob("*.m4b"))
                mp4_candidates = list(proj.glob("*.mp4"))
                trailer = proj / "trailer_sinopsis.mp3"

                audio_f = mp3_candidates[0] if mp3_candidates else None
                m4b = m4b_candidates[0] if m4b_candidates else None
                mp4 = mp4_candidates[0] if mp4_candidates else None
                if not audio_f and not m4b and not mp4:
                    continue

                links: list[str] = []
                if audio_f:
                    u = f"/media/{urllib.parse.quote(proj.name)}/{urllib.parse.quote(audio_f.name)}"
                    links.append(f'<div style="margin-top:8px;"><audio controls preload="none" src="{u}" style="width:100%;"></audio></div>')
                if trailer.exists():
                    tu = f"/media/{urllib.parse.quote(proj.name)}/trailer_sinopsis.mp3"
                    links.append(f'<div style="margin-top:6px;font-size:12px;color:#38bdf8;">[ ► ] Trailer 90s: <audio controls preload="none" src="{tu}" style="width:100%;height:32px;"></audio></div>')
                if m4b and m4b.exists():
                    mu = f"/media/{urllib.parse.quote(proj.name)}/{urllib.parse.quote(m4b.name)}"
                    links.append(f'<a href="{mu}" download style="color:#38bdf8;font-size:13px;margin-right:14px;">[ ⤓ ] Descargar .M4B (Capítulos)</a>')
                if mp4 and mp4.exists():
                    vu = f"/media/{urllib.parse.quote(proj.name)}/{urllib.parse.quote(mp4.name)}"
                    links.append(f'<a href="{vu}" target="_blank" style="color:#10b981;font-size:13px;">[ ► ] Ver Video Karaoke MP4</a>')

                cards_html.append(
                    f'<div style="background:#111726;border:1px solid #1E293B;border-radius:10px;padding:16px;margin-bottom:14px;">'
                    f'<div style="font-weight:700;font-size:16px;color:#F8FAFC;">{html.escape(title)}</div>'
                    f'{"".join(links)}'
                    f"</div>"
                )

        body = "".join(cards_html) or "<p style='color:#94A3B8;'>Aún no hay audiolibros generados en la biblioteca.</p>"
        page = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GlobalTTS Studio — Mobile Streaming</title>
</head>
<body style="background:#0B0F19;color:#F8FAFC;font-family:'Segoe UI',sans-serif;margin:0;padding:20px;">
<h2 style="color:#38BDF8;margin-top:0;">GLOBAL TTS STUDIO • WIFI STREAMING</h2>
<p style="color:#94A3B8;font-size:13px;">Escucha tus audiolibros y videos karaoke directamente en tu dispositivo móvil.</p>
{body}
<footer style="margin-top:30px;font-size:11px;color:#64748B;text-align:center;">HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®</footer>
</body>
</html>"""
        encoded = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _serve_file_with_range(self, file_path: Path) -> None:
        file_size = file_path.stat().st_size
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if file_path.suffix.lower() == ".m4b":
            mime_type = "audio/mp4"
        mime_type = mime_type or "application/octet-stream"

        range_header = self.headers.get("Range")
        start, end = 0, file_size - 1
        status = 200

        if range_header:
            m = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if m:
                start = int(m.group(1))
                if m.group(2):
                    end = min(file_size - 1, int(m.group(2)))
                if start < file_size:
                    status = 206

        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", mime_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        with file_path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionResetError, BrokenPipeError):
                    break
                remaining -= len(chunk)


class MobileStreamingServer:
    """Controlador singleton del micro-servidor WiFi de streaming."""

    def __init__(self, output_root: Optional[Path] = None, port: int = 8765):
        self.output_root = Path(output_root) if output_root else DEFAULT_OUTPUT_ROOT
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        return f"http://{get_lan_ip()}:{self.port}/"

    def start(self) -> str:
        if self._server is not None:
            return self.url

        self.output_root.mkdir(parents=True, exist_ok=True)
        _StreamingRequestHandler.output_root = self.output_root

        for p in range(self.port, self.port + 15):
            try:
                srv = ThreadingHTTPServer(("0.0.0.0", p), _StreamingRequestHandler)
                self.port = p
                self._server = srv
                break
            except OSError:
                continue

        if self._server is None:
            raise RuntimeError("No se encontró un puerto TCP disponible para el servidor de streaming móvil.")

        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="GlobalTTSMobileServer")
        self._thread.start()
        logger.info("Servidor de Streaming Móvil activo en %s", self.url)
        return self.url

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
            self._thread = None


GLOBAL_MOBILE_SERVER = MobileStreamingServer()
