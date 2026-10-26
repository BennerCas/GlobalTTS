"""Generador de Paquetes de Publicación Automatizada (YouTube SEO, Marcas de Tiempo y Podcast RSS).

Construye los artefactos de distribución profesional junto a cada audiolibro:
1. `youtube_spotify_seo.txt`: Título optimizado, sinopsis comercial, marcas de tiempo
   exactas de capítulos (`00:00 Capítulo 1`) compatibles con la barra de capítulos de YouTube,
   y etiquetas SEO.
2. `podcast_rss.xml`: Feed XML RSS 2.0 con namespace `<itunes:...>` listo para distribuir
   en Spotify for Podcasters, Apple Podcasts o gestores de audiolibros.
"""
from __future__ import annotations

import datetime
import html
import logging
import uuid
import zipfile
from pathlib import Path
from typing import Optional, Sequence

from src.audio.assembler import ChapterTiming
from src.audio.karaoke import TimedSentence

logger = logging.getLogger("globaltts.publisher")


def _format_yt_timestamp(ms: int) -> str:
    total_s = max(0, int(round(ms / 1000.0)))
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def generate_publication_package(
    project_dir: Path,
    title: str,
    author: str,
    duration_s: float,
    chapters: list[ChapterTiming],
    style: str = "cuento",
    summary_text: str = "",
) -> dict[str, Path]:
    """Genera `youtube_spotify_seo.txt` y `podcast_rss.xml` dentro de `project_dir`."""
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    clean_title = (title or "Audiolibro Completo").strip()
    clean_author = (author or "GlobalTTS Studio").strip()
    dur_min = max(1, int(round(duration_s / 60.0)))

    # 1. Construir marcas de tiempo de capítulos para YouTube (siempre iniciando en 00:00)
    ts_lines: list[str] = []
    if chapters:
        for idx, ch in enumerate(chapters):
            ts = "00:00" if idx == 0 else _format_yt_timestamp(ch.start_ms)
            ts_lines.append(f"{ts} {ch.title}")
    else:
        ts_lines.append(f"00:00 {clean_title}")

    seo_content = f"""================================================================================
PAQUETE DE PUBLICACIÓN SEO — YOUTUBE / SPOTIFY / AUDIBLE
================================================================================

[TÍTULO SUGERIDO PARA YOUTUBE / SPOTIFY]
{clean_title} — {clean_author} | Audiolibro Completo en Español ({style.replace('_', ' ').title()}) [Hi-Fi 24kHz]

[DESCRIPCIÓN OPTIMIZADA]
Disfruta del audiolibro completo "{clean_title}" de {clean_author}, producido con síntesis neuronal expresiva de 24kHz y masterización de estudio.

{summary_text.strip() or f'Una producción inmersiva en estilo {style.replace("_", " ")} con una duración total aproximada de {dur_min} minutos.'}

[ÍNDICE DE CAPÍTULOS / TIMESTAMPS YOUTUBE]
{chr(10).join(ts_lines)}

[ETIQUETAS / TAGS SEO]
audiolibro, audiolibro completo en español, {clean_title.lower()}, {clean_author.lower()}, {style.replace('_', ' ')}, lectura en voz alta, literatura narrada, podcast en español, globaltts studio

================================================================================
HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®
================================================================================
"""
    seo_path = project_dir / "youtube_spotify_seo.txt"
    seo_path.write_text(seo_content, encoding="utf-8")

    # 2. Construir Feed RSS 2.0 compatible con Apple Podcasts / Spotify
    pub_date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    dur_int = int(round(duration_s))
    esc_title = html.escape(clean_title)
    esc_author = html.escape(clean_author)
    esc_summary = html.escape(summary_text.strip() or f"Audiolibro completo: {clean_title} ({clean_author}).")

    rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>{esc_title} — Audiolibro</title>
    <link>http://localhost:8765/</link>
    <language>es-ES</language>
    <copyright>HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®</copyright>
    <itunes:author>{esc_author}</itunes:author>
    <description>{esc_summary}</description>
    <itunes:explicit>false</itunes:explicit>
    <itunes:image href="cover.png"/>
    <item>
      <title>{esc_title} (Edición Completa)</title>
      <itunes:author>{esc_author}</itunes:author>
      <description>{esc_summary}</description>
      <enclosure url="audiolibro_completo.mp3" length="{dur_int * 24000}" type="audio/mpeg"/>
      <guid isPermaLink="false">{esc_title.lower().replace(' ', '_')}_master</guid>
      <pubDate>{pub_date}</pubDate>
      <itunes:duration>{dur_int}</itunes:duration>
    </item>
  </channel>
</rss>
"""
    rss_path = project_dir / "podcast_rss.xml"
    rss_path.write_text(rss_xml, encoding="utf-8")

    return {"seo": seo_path, "rss": rss_path}


def export_epub3_readaloud(
    output_epub_path: Path,
    title: str,
    author: str,
    sentences: Sequence[TimedSentence],
    audio_mp3_path: Path,
    cover_image_path: Optional[Path] = None,
) -> Optional[Path]:
    """Empaqueta un libro electrónico EPUB 3.0 con Media Overlays (SMIL) sincronizados oración por oración."""
    try:
        output_epub_path = Path(output_epub_path)
        output_epub_path.parent.mkdir(parents=True, exist_ok=True)
        audio_mp3_path = Path(audio_mp3_path)
        if not audio_mp3_path.exists():
            return None

        esc_title = html.escape((title or "Audiolibro Sincronizado").strip())
        esc_author = html.escape((author or "GlobalTTS Studio").strip())
        book_uuid = str(uuid.uuid4())
        total_dur_s = max((float(s.end_s) for s in sentences), default=0.0)
        modified_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        has_cover = bool(cover_image_path and Path(cover_image_path).exists())
        cover_ext = Path(cover_image_path).suffix.lower() if has_cover else ".png"
        cover_mime = "image/jpeg" if cover_ext in (".jpg", ".jpeg") else "image/png"
        cover_href = f"cover{cover_ext}"

        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

        span_lines: list[str] = []
        smil_pars: list[str] = []
        for idx, s in enumerate(sentences, start=1):
            sid = f"s{idx}"
            raw_txt = getattr(s, "sentence", getattr(s, "text", ""))
            stext = html.escape(str(raw_txt).strip())
            if not stext:
                continue
            cls = ' class="chapter-title"' if getattr(s, "is_title", False) else ""
            span_lines.append(f'    <p{cls}><span id="{sid}">{stext}</span></p>')
            smil_pars.append(
                f'      <par id="par{idx}">\n'
                f'        <text src="chapter.xhtml#{sid}"/>\n'
                f'        <audio src="audio.mp3" clipBegin="{s.start_s:.2f}s" clipEnd="{s.end_s:.2f}s"/>\n'
                f'      </par>'
            )

        chapter_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="es" lang="es">
<head>
  <meta charset="utf-8"/>
  <title>{esc_title}</title>
  <style type="text/css">
    body {{ font-family: Georgia, serif; background: #0B0F19; color: #F8FAFC; line-height: 1.65; padding: 1.5em; }}
    h1 {{ color: #38BDF8; font-family: sans-serif; }}
    p.chapter-title {{ font-weight: bold; font-size: 1.25em; color: #38BDF8; margin-top: 1.4em; }}
    .-epub-media-overlay-active {{ background-color: #1E3A5F; color: #38BDF8; border-radius: 3px; padding: 1px 3px; }}
  </style>
</head>
<body>
  <section epub:type="bodymatter chapter">
    <h1>{esc_title}</h1>
{chr(10).join(span_lines)}
  </section>
</body>
</html>"""

        overlay_smil = f"""<?xml version="1.0" encoding="UTF-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">
  <body>
    <seq id="seq1" epub:textref="chapter.xhtml">
{chr(10).join(smil_pars)}
    </seq>
  </body>
</smil>"""

        nav_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="es" lang="es">
<head><meta charset="utf-8"/><title>Índice</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>{esc_title}</h1>
    <ol><li><a href="chapter.xhtml">{esc_title}</a></li></ol>
  </nav>
</body>
</html>"""

        cover_manifest = (
            f'    <item id="cover-img" href="{cover_href}" media-type="{cover_mime}" properties="cover-image"/>\n'
            if has_cover
            else ""
        )
        content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId" xml:lang="es">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookId">urn:uuid:{book_uuid}</dc:identifier>
    <dc:title>{esc_title}</dc:title>
    <dc:creator>{esc_author}</dc:creator>
    <dc:language>es</dc:language>
    <dc:rights>HUMAN AI SYNERGY BY BENNER CASTILLO - 2026®</dc:rights>
    <meta property="dcterms:modified">{modified_iso}</meta>
    <meta property="media:duration" refines="#ch1_overlay">{total_dur_s:.2f}s</meta>
    <meta property="media:duration">{total_dur_s:.2f}s</meta>
    <meta property="media:active-class">-epub-media-overlay-active</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ch1" href="chapter.xhtml" media-type="application/xhtml+xml" media-overlay="ch1_overlay"/>
    <item id="ch1_overlay" href="overlay.smil" media-type="application/smil+xml"/>
    <item id="audio1" href="audio.mp3" media-type="audio/mpeg"/>
{cover_manifest}  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>"""

        with zipfile.ZipFile(output_epub_path, "w") as zf:
            # Estándar EPUB 3: el archivo 'mimetype' DEBE ser el primero y sin compresión (ZIP_STORED)
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", container_xml, compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/content.opf", content_opf, compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/nav.xhtml", nav_xhtml, compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/chapter.xhtml", chapter_xhtml, compress_type=zipfile.ZIP_DEFLATED)
            zf.writestr("OEBPS/overlay.smil", overlay_smil, compress_type=zipfile.ZIP_DEFLATED)
            zf.write(audio_mp3_path, "OEBPS/audio.mp3", compress_type=zipfile.ZIP_STORED)
            if has_cover and cover_image_path:
                zf.write(cover_image_path, f"OEBPS/{cover_href}", compress_type=zipfile.ZIP_STORED)

        return output_epub_path
    except Exception as exc:
        logger.warning("Aviso exportando EPUB3 Read-Aloud: %s", exc)
        return None
