"""Lector Nativo de URLs y Artículos Web (Readability Engine).

Descarga artículos web, blogs, noticias o ensayos en línea, elimina menús,
scripts, anuncios, barras laterales y pies de página, y extrae únicamente
el cuerpo editorial limpio y estructurado por capítulos/secciones.
"""
from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag

from src.core.editorial_cleaner import clean_editorial_blocks
from src.core.language import detect_language
from src.core.models import Document, DocumentError
from src.ingest.common import group_into_chapters, normalize_paragraph, unwrap_lines

logger = logging.getLogger("globaltts.url_reader")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36 GlobalTTS/2.0"
)

_NOISE_TAGS = (
    "script", "style", "noscript", "nav", "footer", "header",
    "aside", "form", "iframe", "svg", "canvas", "button", "input",
    "select", "textarea", "dialog", "menu",
)

_NOISE_CLASS_ID_RE = re.compile(
    r"(?:nav|navbar|menu|sidebar|footer|header|comment|promo|advert|ad-|ads-|cookie|popup|modal|share|social|related|newsletter|breadcrumb)",
    re.IGNORECASE,
)


def _select_main_container(soup: BeautifulSoup) -> Tag:
    """Selecciona el contenedor semántico con mayor densidad de texto editorial."""
    for selector in ("article", "main", "[role='main']", ".post-content", ".article-body", ".entry-content"):
        found = soup.select_one(selector)
        if found and len(found.get_text(strip=True)) >= 200:
            return found

    # Heurística Readability: evaluar contenedores candidatos por longitud de texto en <p>
    best_node: Tag = soup.body or soup
    best_score = -1
    for candidate in soup.find_all(["div", "section", "article", "main"]):
        p_tags = candidate.find_all("p", recursive=False)
        if not p_tags:
            continue
        score = sum(len(p.get_text(strip=True)) for p in p_tags)
        if score > best_score:
            best_score = score
            best_node = candidate

    return best_node


def extract_text_from_html(html: str, source_url: str = "") -> tuple[str, str, list[str]]:
    """Extrae (title, author, blocks) limpios desde un documento HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Extraer título
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = str(og_title["content"]).strip()
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
    if not title and source_url:
        parsed = urlparse(source_url)
        title = parsed.netloc + parsed.path.rstrip("/")
    title = normalize_paragraph(title or "Artículo Web")

    # Extraer autor
    author = ""
    meta_author = soup.find("meta", attrs={"name": re.compile(r"author", re.I)})
    if meta_author and meta_author.get("content"):
        author = normalize_paragraph(str(meta_author["content"]))

    # Eliminar etiquetas de ruido
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag) or tag.attrs is None:
            continue
        cls_str = " ".join(tag.get("class", [])) if isinstance(tag.get("class"), list) else str(tag.get("class", ""))
        id_str = str(tag.get("id", ""))
        if _NOISE_CLASS_ID_RE.search(f"{cls_str} {id_str}"):
            # No eliminar si es el body o article principal
            if tag.name not in ("body", "article", "main"):
                tag.decompose()

    container = _select_main_container(soup)

    blocks: list[str] = []
    for elem in container.find_all(["h1", "h2", "h3", "p", "blockquote", "li"]):
        txt = unwrap_lines(elem.get_text(" ", strip=True))
        if not txt:
            continue
        if elem.name in ("h1", "h2", "h3"):
            if len(txt) <= 100 and not txt.lower().startswith(("capítulo", "parte", "sección")):
                blocks.append(f"Capítulo: {txt}")
            else:
                blocks.append(txt)
        elif len(txt) >= 20 or elem.name == "p":
            if not blocks or blocks[-1] != txt:
                blocks.append(txt)

    # Fallback si la página no usa <p> estándar
    if not blocks:
        raw_lines = (soup.body or soup).get_text("\n", strip=True).splitlines()
        blocks = [unwrap_lines(line) for line in raw_lines if len(unwrap_lines(line)) >= 25]

    blocks = clean_editorial_blocks(blocks, strip_page_numbers=True, strip_footnotes=True)
    return title, author, blocks


def extract_text_from_url(url: str, timeout: int = 15) -> tuple[str, str]:
    """Descarga una URL y devuelve (título, texto_plano_limpio) para Lectura Rápida."""
    doc = read_url(url, timeout=timeout)
    full_lines: list[str] = []
    for ch in doc.chapters:
        if ch.title and ch.title != doc.title:
            full_lines.append(ch.title)
        full_lines.extend(ch.paragraphs)
    return doc.title, "\n\n".join(full_lines)


def read_url(url: str, timeout: int = 15) -> Document:
    """Descarga una URL web y construye un objeto Document estructurado."""
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    try:
        resp = requests.get(
            clean_url,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"},
            timeout=timeout,
        )
        resp.raise_for_status()
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text
    except Exception as exc:
        raise DocumentError(f"No se pudo descargar la URL '{clean_url}': {exc}") from exc

    title, author, blocks = extract_text_from_html(html, source_url=clean_url)
    if not blocks:
        raise DocumentError(f"No se encontró contenido de artículo legible en la URL: {clean_url}")

    chapters = group_into_chapters(blocks, default_title=title)
    sample = " ".join(p for c in chapters for p in c.paragraphs)[:4000]
    url_hash = hashlib.sha256(clean_url.encode("utf-8")).hexdigest()

    return Document(
        title=title,
        author=author,
        language=detect_language(sample),
        chapters=chapters,
        source_path=clean_url,
        source_sha256=url_hash,
    )
