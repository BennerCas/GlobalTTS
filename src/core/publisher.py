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
from pathlib import Path

from src.audio.assembler import ChapterTiming

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
