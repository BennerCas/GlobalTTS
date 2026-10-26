"""Generador de Portadas de Audiolibros con IA Local y Composición Editorial (1024x1024).

Conecta con el servidor local SD-Turbo (`http://127.0.0.1:8000/generate`) si está activo,
o ejecuta el motor algorítmico de arte digital generativo en alta resolución (`1024x1024`)
con paletas atmosféricas adaptadas al estilo narrativo (`terror`, `ciencia_ficcion`, `epico`,
`cuento`, `ensayo`, `historia`, `poesia`, `locutor_radio`) y maquetación tipográfica de lujo.
"""
from __future__ import annotations

import io
import logging
import textwrap
import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger("globaltts.cover_generator")

# Paletas cromáticas editoriales por género/estilo (RGB fondo oscuro, acento primario, acento secundario)
STYLE_PALETTES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "terror": ((10, 12, 18), (185, 28, 28), (120, 140, 165)),
    "ciencia_ficcion": ((8, 13, 28), (6, 182, 212), (99, 102, 241)),
    "epico": ((18, 12, 10), (245, 158, 11), (217, 119, 6)),
    "cuento": ((12, 20, 24), (56, 189, 248), (251, 191, 36)),
    "ensayo": ((15, 23, 42), (14, 165, 233), (148, 163, 184)),
    "historia": ((24, 18, 14), (217, 160, 91), (168, 130, 90)),
    "poesia": ((19, 14, 28), (192, 132, 252), (244, 114, 182)),
    "locutor_radio": ((10, 15, 25), (34, 211, 238), (59, 130, 246)),
}


def _load_editorial_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Carga tipografía del sistema Windows con fallback seguro."""
    candidates = (
        ["segoeuib.ttf", "georgia.ttf", "arialbd.ttf", "calibrib.ttf"]
        if bold
        else ["segoeui.ttf", "georgia.ttf", "arial.ttf", "calibri.ttf"]
    )
    win_fonts = Path(r"C:\Windows\Fonts")
    for name in candidates:
        fp = win_fonts / name
        if fp.exists():
            try:
                return ImageFont.truetype(str(fp), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _try_sdturbo_background(title: str, style: str, size: int = 1024) -> Optional[Image.Image]:
    """Intenta generar el lienzo artístico con el servidor local SD-Turbo si está corriendo."""
    try:
        import json
        prompt = (
            f"cinematic book cover illustration for '{title}', style {style}, "
            "dark obsidian atmospheric lighting, ultra detailed, no text, masterpiece"
        )
        payload = json.dumps({"prompt": prompt, "steps": 2, "width": 512, "height": 512}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8000/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            raw = resp.read()
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            return img.resize((size, size), Image.Resampling.LANCZOS)
    except Exception:
        return None


def _render_procedural_canvas(title: str, style: str, size: int = 1024) -> Image.Image:
    """Sintetiza un lienzo de arte digital abstracto/astronómico en 1024x1024 usando campos vectoriales NumPy."""
    bg_rgb, acc1_rgb, acc2_rgb = STYLE_PALETTES.get(style.lower(), STYLE_PALETTES["ensayo"])
    seed = abs(hash(f"{title}_{style}")) % 100000
    rng = np.random.default_rng(seed=seed)

    # Coordenadas normalizadas [-1, 1]
    y, x = np.ogrid[-1.0 : 1.0 : complex(0, size), -1.0 : 1.0 : complex(0, size)]
    r = np.sqrt(x * x + y * y)
    theta = np.arctan2(y, x)

    # Ondas armónicas interferenciales (nebulosa / topografía de luz)
    freq1 = rng.uniform(2.5, 4.5)
    freq2 = rng.uniform(3.0, 6.0)
    phase = rng.uniform(0.0, 2.0 * np.pi)

    wave_a = np.sin(freq1 * x + np.cos(freq2 * y + phase)) * np.exp(-1.1 * r * r)
    wave_b = np.cos(freq2 * r * 3.0 - theta * 2.0 + phase) * np.exp(-1.4 * ((x - 0.1) ** 2 + (y + 0.15) ** 2))

    mask1 = np.clip((wave_a + 1.0) * 0.5, 0.0, 1.0) ** 2.2
    mask2 = np.clip((wave_b + 1.0) * 0.5, 0.0, 1.0) ** 2.6
    vignette = np.clip(1.15 - 0.75 * (r ** 1.6), 0.15, 1.0)

    canvas = np.zeros((size, size, 3), dtype=np.float32)
    for c in range(3):
        layer = (
            bg_rgb[c] * 1.1
            + acc1_rgb[c] * mask1 * 0.65
            + acc2_rgb[c] * mask2 * 0.50
        ) * vignette
        canvas[:, :, c] = np.clip(layer, 0.0, 255.0)

    img = Image.fromarray(canvas.astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    # Anillos geométricos sutiles de estudio en el centro-superior
    cx, cy = size // 2, int(size * 0.40)
    for rad in (160, 220, 285):
        draw.ellipse(
            (cx - rad, cy - rad, cx + rad, cy + rad),
            outline=(acc1_rgb[0], acc1_rgb[1], acc1_rgb[2], 55),
            width=2,
        )

    # Partículas de luz estelar
    for _ in range(95):
        px = int(rng.integers(60, size - 60))
        py = int(rng.integers(60, size - 60))
        pr = int(rng.integers(1, 4))
        alpha = int(rng.integers(60, 185))
        draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(255, 255, 255, alpha))

    return img.filter(ImageFilter.SMOOTH)


def generate_audiobook_cover(
    title: str,
    author: str = "",
    style: str = "cuento",
    output_path: Optional[Path] = None,
    size: int = 1024,
) -> Path:
    """Genera una portada cuadrada 1024x1024 en PNG y devuelve la ruta del archivo."""
    clean_title = (title or "Audiolibro Maestro").strip()
    clean_author = (author or "GlobalTTS Studio").strip()
    _, acc1_rgb, _ = STYLE_PALETTES.get(style.lower(), STYLE_PALETTES["ensayo"])

    img = _try_sdturbo_background(clean_title, style, size=size)
    if img is None:
        img = _render_procedural_canvas(clean_title, style, size=size)

    draw = ImageDraw.Draw(img, "RGBA")

    # Sombra degradada inferior y superior para máxima legibilidad tipográfica
    for y in range(int(size * 0.52), size):
        ratio = max(0.0, (y - size * 0.52) / (size * 0.48))
        alpha = int(min(225, 240 * (ratio ** 1.3)))
        draw.line([(0, y), (size, y)], fill=(8, 12, 22, alpha))

    # Marco doble editorial de lujo
    margin = 36
    draw.rectangle(
        (margin, margin, size - margin, size - margin),
        outline=(acc1_rgb[0], acc1_rgb[1], acc1_rgb[2], 160),
        width=3,
    )
    inner_m = 48
    draw.rectangle(
        (inner_m, inner_m, size - inner_m, size - inner_m),
        outline=(255, 255, 255, 45),
        width=1,
    )

    # Sello superior: EDICIÓN AUDIOLIBRO NEURAL
    font_badge = _load_editorial_font(22, bold=True)
    badge_text = f"EDICIÓN AUDIOLIBRO NEURAL  •  {style.upper().replace('_', ' ')}"
    draw.text((size // 2, 92), badge_text, fill=(acc1_rgb[0], acc1_rgb[1], acc1_rgb[2], 240), font=font_badge, anchor="mm")

    # Título principal con ajuste automático de líneas
    font_title = _load_editorial_font(62 if len(clean_title) < 35 else 48, bold=True)
    wrapped_lines = textwrap.wrap(clean_title.upper(), width=18 if len(clean_title) < 35 else 24)[:4]
    y_cursor = size - 320 - (len(wrapped_lines) - 1) * 36
    for line in wrapped_lines:
        # Sombra suave
        draw.text((size // 2 + 3, y_cursor + 3), line, fill=(0, 0, 0, 210), font=font_title, anchor="mm")
        draw.text((size // 2, y_cursor), line, fill=(248, 250, 252, 255), font=font_title, anchor="mm")
        y_cursor += 72 if len(clean_title) < 35 else 58

    # Línea divisoria de acento
    div_y = y_cursor + 8
    draw.line([(size // 2 - 140, div_y), (size // 2 + 140, div_y)], fill=(acc1_rgb[0], acc1_rgb[1], acc1_rgb[2], 220), width=3)

    # Autor y firma inferior
    font_author = _load_editorial_font(30, bold=False)
    draw.text((size // 2, div_y + 48), clean_author, fill=(203, 213, 225, 245), font=font_author, anchor="mm")

    font_footer = _load_editorial_font(18, bold=True)
    draw.text(
        (size // 2, size - 72),
        "GLOBAL TTS STUDIO  •  24KHZ HI-FI MASTER",
        fill=(148, 163, 184, 190),
        font=font_footer,
        anchor="mm",
    )

    if output_path is None:
        out_dir = Path(__file__).resolve().parent.parent.parent / "output" / "covers"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_slug = "".join(c if c.isalnum() else "_" for c in clean_title)[:40]
        output_path = out_dir / f"cover_{safe_slug}.png"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    img.save(str(output_path), format="PNG")
    return output_path
