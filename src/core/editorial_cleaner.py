"""Filtro Heurístico de Ruido Editorial para libros, PDFs y documentos académicos.

Limpia automáticamente elementos paratextuales que interrumpen la fluidez de la
lectura en voz alta:
1. Numeración de páginas aislada (`12`, `- 45 -`, `Página 12 de 300`, `Pág. 8`).
2. Encabezados y pies de página repetitivos entre páginas.
3. Referencias bibliográficas y marcadores de notas al pie huérfanos (`[1]`, `[14, 15]`).
4. Líneas de metadatos de imprenta (ISBN, Depósito Legal, derechos reservados repetidos).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

# Número de página aislado: "12", "- 12 -", "Página 12", "Pág. 12 / 50", "[ 14 ]"
_STANDALONE_PAGE_RE = re.compile(
    r"^\s*(?:[-–—•|]*\s*)?(?:p[aá]gina|p[aá]g\.?|page|pg\.?)?\s*\d{1,5}(?:\s*(?:de|of|/)\s*\d{1,5})?(?:\s*[-–—•|]*)?\s*$",
    re.IGNORECASE,
)

# Citas numéricas tipo [1], [12], [2, 5], [1-4] pero SIN tocar etiquetas de voz como [pausa] o [voz:...]
# Nota: el parser de markup conserva [12] como texto literal, por lo que limpiarlo aquí evita que el TTS lea " doce ".
_FOOTNOTE_BRACKET_RE = re.compile(r"\s*\[\s*\d{1,3}(?:\s*[,;-]\s*\d{1,3})*\s*\]")

# Superíndices Unicode de notas al pie (¹ ² ³ ⁴ ⁵ ⁶ ⁷ ⁸ ⁹) pegados al final de palabra
_SUPERSCRIPT_FOOTNOTE_RE = re.compile(r"(?<=[a-zA-ZáéíóúÁÉÍÓÚñÑ.,;:])[¹²³⁴⁵⁶⁷⁸⁹⁰]+")

# Citas académicas breves tipo (Ibid., p. 23) o (Op. cit., pág. 14)
_IBID_CITATION_RE = re.compile(
    r"\s*\(\s*(?:ib[ií]d(?:em)?\.?|op\.?\s*cit\.?|loc\.?\s*cit\.?)(?:[^()]{0,40})\)",
    re.IGNORECASE,
)

# Ruido de imprenta aislado en una línea corta
_BOILERPLATE_LINE_RE = re.compile(
    r"^\s*(?:isbn\s*[:\s\d-]{10,}|dep[oó]sito\s+legal\s*:.*|impreso\s+en\s+.*|printed\s+in\s+.*|todos\s+los\s+derechos\s+reservados\.?)\s*$",
    re.IGNORECASE,
)


def clean_inline_editorial_noise(
    text: str,
    strip_footnotes: bool = True,
    strip_academic_ibid: bool = True,
) -> str:
    """Limpia notas al pie numéricas y marcadores paratextuales dentro de un párrafo."""
    if not text:
        return ""
    cleaned = text
    if strip_footnotes:
        cleaned = _FOOTNOTE_BRACKET_RE.sub("", cleaned)
        cleaned = _SUPERSCRIPT_FOOTNOTE_RE.sub("", cleaned)
    if strip_academic_ibid:
        cleaned = _IBID_CITATION_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def is_editorial_noise_block(block: str, strip_page_numbers: bool = True, strip_boilerplate: bool = True) -> bool:
    """Determina si un bloque completo es un número de página aislado o ruido de imprenta."""
    stripped = block.strip()
    if not stripped:
        return True
    if strip_page_numbers and _STANDALONE_PAGE_RE.match(stripped):
        return True
    if strip_boilerplate and len(stripped) < 120 and _BOILERPLATE_LINE_RE.match(stripped):
        return True
    return False


def detect_repeating_headers_footers(pages_blocks: list[list[str]], min_occurrences: int = 3) -> set[str]:
    """Detecta líneas cortas que se repiten al inicio o final de múltiples páginas (running headers/footers)."""
    if len(pages_blocks) < min_occurrences:
        return set()

    edge_counter: Counter[str] = Counter()
    for blocks in pages_blocks:
        if not blocks:
            continue
        candidates = set()
        first = blocks[0].strip()
        if 3 <= len(first) <= 90:
            # Normalizar dígitos para detectar encabezados con número de página ("CAPÍTULO 1   24")
            norm_first = re.sub(r"\d+", "#", first.lower())
            candidates.add(norm_first)
        if len(blocks) > 1:
            last = blocks[-1].strip()
            if 3 <= len(last) <= 90:
                norm_last = re.sub(r"\d+", "#", last.lower())
                candidates.add(norm_last)
        for c in candidates:
            edge_counter[c] += 1

    return {pattern for pattern, count in edge_counter.items() if count >= min_occurrences}


def clean_editorial_blocks(
    blocks: Iterable[str],
    repeating_patterns: set[str] | None = None,
    strip_page_numbers: bool = True,
    strip_footnotes: bool = True,
) -> list[str]:
    """Filtra y limpia una secuencia de bloques de texto eliminando ruido editorial."""
    repeating = repeating_patterns or set()
    cleaned_blocks: list[str] = []

    for b in blocks:
        raw = b.strip()
        if not raw:
            continue
        if is_editorial_noise_block(raw, strip_page_numbers=strip_page_numbers):
            continue
        if repeating and len(raw) <= 90:
            norm = re.sub(r"\d+", "#", raw.lower())
            if norm in repeating:
                continue

        inline_clean = clean_inline_editorial_noise(raw, strip_footnotes=strip_footnotes)
        if inline_clean and not is_editorial_noise_block(inline_clean, strip_page_numbers=strip_page_numbers):
            cleaned_blocks.append(inline_clean)

    return cleaned_blocks
