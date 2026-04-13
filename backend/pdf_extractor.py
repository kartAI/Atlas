import re

import fitz

from blob_storage import download_blob_bytes
from chunker import _is_known_ku_keyword

_HEADER_FOOTER_EDGE_RATIO = 0.07
_HEADER_FOOTER_MAX_TEXT_LENGTH = 80
_HEADING_FONT_SIZE_THRESHOLD = 13.0

_NUMBERED_SECTION_HEADING_RE = re.compile(
    r"^\s*\d{1,2}(?:\.\d{1,2}){0,3}\s+\S+",
    re.UNICODE,
)
_ALTERNATIVE_HEADING_RE = re.compile(
    r"\b(nullalternativ(?:et|en)?|alternativ\s*(?:\d+[a-z]?|[a-z])(?![a-zæøå0-9]))",
    re.IGNORECASE | re.UNICODE,
)


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


def _looks_like_headingish_edge_block(block_text: str, font_size: float, is_bold: bool) -> bool:
    text = block_text.strip()
    if not text:
        return False
    if re.match(r"^-?\s*\d{1,3}\s*-?$", text):
        return False
    if font_size >= _HEADING_FONT_SIZE_THRESHOLD:
        return True
    if _NUMBERED_SECTION_HEADING_RE.match(text):
        return True
    if _ALTERNATIVE_HEADING_RE.search(text):
        return True
    if _is_known_ku_keyword(text):
        return True
    # Plain bold text near page edges is too noisy: many PDFs repeat bold
    # running headers/footers on every page. Keep only stronger heading signals.
    return False


def _should_skip_edge_block(
    block_text: str,
    bbox: tuple,
    page_height: float,
    font_size: float,
    is_bold: bool,
) -> bool:
    y0, y1 = bbox[1], bbox[3]
    near_edge = (
        y0 < page_height * _HEADER_FOOTER_EDGE_RATIO
        or y1 > page_height * (1 - _HEADER_FOOTER_EDGE_RATIO)
    )
    if not near_edge or len(block_text) >= _HEADER_FOOTER_MAX_TEXT_LENGTH:
        return False
    if _looks_like_headingish_edge_block(block_text, font_size, is_bold):
        return False
    return True


def fetch_document_blocks(blob_name: str) -> list[dict]:
    """
    Fetch the PDF from Blob Storage and return structured text blocks with font metadata.

    Used by the structure-aware chunking pipeline (chunker.py).
    Does not replace fetch_document() - that function is still used by docs_server.py.

    Each returned block dict:
        text        str   - all text in the block (lines joined with newlines)
        page        int   - 1-indexed page number
        font_size   float - maximum font size among all spans in the block
        is_bold     bool  - True if any span in the block has the bold flag (flags & 16)
        bbox        tuple - (x0, y0, x1, y1) bounding box of the block

    Image blocks (type=1) are skipped.
    Blocks positioned in the top 7% or bottom 7% of the page that are shorter
    than 80 characters are skipped (heuristic for page numbers / running headers).
    """
    doc = _open_pdf_from_blob(blob_name)
    blocks = []

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

                bbox = block.get("bbox", (0, 0, 0, page_height))
                if _should_skip_edge_block(
                    block_text,
                    bbox,
                    page_height,
                    max_font_size,
                    is_bold,
                ):
                    continue

                blocks.append(
                    {
                        "text": block_text,
                        "page": page_num,
                        "font_size": max_font_size,
                        "is_bold": is_bold,
                        "bbox": bbox,
                    }
                )

        return blocks
    finally:
        doc.close()
