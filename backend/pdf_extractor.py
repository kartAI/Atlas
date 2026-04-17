import re
from collections import Counter

import fitz

from blob_storage import download_blob_bytes
from chunker import (
    HEADING_FONT_SIZE_THRESHOLD,
    _ALTERNATIVE_RE,
    _is_known_ku_keyword,
    _parse_numbered_heading,
)

_HEADER_FOOTER_EDGE_RATIO = 0.07
_HEADER_FOOTER_MAX_TEXT_LENGTH = 80


def _open_pdf_from_blob(blob_name: str):
    blob_data = download_blob_bytes(blob_name)
    return fitz.open(stream=blob_data, filetype="pdf")


def fetch_document(blob_name: str) -> str:
    doc = _open_pdf_from_blob(blob_name)
    try:
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    finally:
        doc.close()


def _extract_block_text_and_style(lines: list[dict]) -> tuple[str, float, bool]:
    line_texts: list[str] = []
    max_font_size = 0.0
    is_bold = False

    for line in lines:
        span_texts: list[str] = []
        for span in line.get("spans", []):
            span_text = span.get("text", "").strip()
            if span_text:
                span_texts.append(span_text)
            size = span.get("size", 0.0)
            flags = span.get("flags", 0)
            if size > max_font_size:
                max_font_size = size
            if flags & 16:
                is_bold = True
        if span_texts:
            line_texts.append(" ".join(span_texts))

    return "\n".join(line_texts).strip(), max_font_size, is_bold


def _looks_like_headingish_edge_block(block_text: str, font_size: float, is_bold: bool, body_font_size: float = 11.0) -> bool:
    text = block_text.strip()
    if not text:
        return False
    if re.match(r"^-?\s*\d{1,3}\s*-?$", text):
        return False
    if font_size >= max(HEADING_FONT_SIZE_THRESHOLD, body_font_size * 1.2):
        return True
    if _parse_numbered_heading(text) is not None:
        return True
    if _ALTERNATIVE_RE.search(text):
        return True
    if _is_known_ku_keyword(text):
        return True
    # Bold+short is intentionally omitted here — unlike the chunker (which
    # accepts bold blocks ≤ 120 chars as headings), edge blocks in the
    # top/bottom 7 % of pages include too many bold running headers/footers.
    # The remaining checks (size, numbering, alternative, keyword) are
    # sufficient for genuine headings near page edges.
    return False


def _should_skip_edge_block(
    block_text: str,
    bbox: tuple | None,
    page_height: float,
    font_size: float,
    is_bold: bool,
    body_font_size: float = 11.0,
) -> bool:
    if bbox is None:
        return False
    y0, y1 = bbox[1], bbox[3]
    near_edge = (
        y0 < page_height * _HEADER_FOOTER_EDGE_RATIO
        or y1 > page_height * (1 - _HEADER_FOOTER_EDGE_RATIO)
    )
    if not near_edge or len(block_text) >= _HEADER_FOOTER_MAX_TEXT_LENGTH:
        return False
    if _looks_like_headingish_edge_block(block_text, font_size, is_bold, body_font_size):
        return False
    return True


def fetch_document_blocks(blob_name: str) -> list[dict]:
    """
    Fetch the PDF from Blob Storage and return structured text blocks with font metadata.

    Used by the structure-aware chunking pipeline (chunker.py).
    Does not replace fetch_document() - that function is still used by docs_server.py.

    Each returned block dict:
        text        str         - all text in the block (lines joined with newlines)
        page        int         - 1-indexed page number
        font_size   float       - maximum font size among all spans in the block
        is_bold     bool        - True if any span in the block has the bold flag (flags & 16)
        bbox        tuple|None  - (x0, y0, x1, y1) bounding box of the block, or None if absent

    Image blocks (type=1) are skipped.
    Blocks in the top/bottom 7% of the page shorter than 80 characters are
    filtered using a body-relative heading threshold so that genuine section
    headings placed near a page edge are always preserved.
    """
    doc = _open_pdf_from_blob(blob_name)
    raw: list[dict] = []

    try:
        for page_num, page in enumerate(doc, start=1):
            page_dict = page.get_text("dict")
            page_height = page_dict.get("height", 1000)

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue

                lines = block.get("lines", [])
                if not lines:
                    continue

                block_text, max_font_size, is_bold = _extract_block_text_and_style(lines)
                if not block_text:
                    continue

                raw.append({
                    "text": block_text,
                    "page": page_num,
                    "font_size": max_font_size,
                    "is_bold": is_bold,
                    "bbox": block.get("bbox"),
                    "_page_height": page_height,
                })
    finally:
        doc.close()

    # Compute body font size from all raw blocks before filtering so the
    # edge-block threshold is body-relative (same logic as chunker._detect_body_font_size).
    sizes = [round(b["font_size"]) for b in raw if b["font_size"] > 0]
    body_font_size = float(Counter(sizes).most_common(1)[0][0]) if sizes else 11.0

    blocks = []
    for b in raw:
        if _should_skip_edge_block(
            b["text"],
            b["bbox"],
            b["_page_height"],
            b["font_size"],
            b["is_bold"],
            body_font_size,
        ):
            continue
        blocks.append({
            "text": b["text"],
            "page": b["page"],
            "font_size": b["font_size"],
            "is_bold": b["is_bold"],
            "bbox": b["bbox"],
        })

    return blocks
