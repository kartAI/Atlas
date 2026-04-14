"""
Structure-aware chunking for Norwegian KU (consequence assessment) documents.

Overview
--------
chunk_document(blocks, document_name, source_blob) -> list[dict]

Input:  A list of text blocks produced by config.fetch_document_blocks().
        Each block: {"text": str, "page": int, "font_size": float, "is_bold": bool}

Output: A list of chunk dicts, each containing:
        - local_id          int       sequential ID (used to resolve parent relationships)
        - local_parent_id   int|None  local_id of the parent chunk, or None for top-level
        - chunk_index       int       order within the document
        - text              str       chunk content (may include heading prefix for context)
        - char_count        int
        - metadata          dict      all metadata fields (see _build_metadata)

Chunking strategy (two-level)
------------------------------
1. Detect section boundaries via heading detection (font size + bold + numbered
   section regex + known Norwegian KU section keyword matching).
2. Each detected section becomes a PARENT chunk.
3. If a section body exceeds MAX_PARENT_CHARS, it is split into CHILD chunks
   by paragraph groups with a small overlap.
4. If fewer than MIN_HEADINGS_FOR_STRUCTURE headings are found, the pipeline
   falls back to paragraph-based chunking (still respects paragraph boundaries).

Heuristics — marked # TUNE for easy adjustment
------------------------------------------------
HEADING_FONT_SIZE_THRESHOLD  Font size above which a block is unconditionally a heading.
HEADING_BOLD_MAX_CHARS       Max length for a bold block to be treated as a heading.
MAX_PARENT_CHARS             Section size above which child chunks are created.
CHILD_CHUNK_TARGET           Target character count for each child chunk.
CHILD_OVERLAP_CHARS          Overlap appended to the start of each subsequent child.
MIN_SECTION_CHARS            Sections shorter than this are kept as-is (no splitting).
MIN_HEADINGS_FOR_STRUCTURE   Min headings required before falling back to paragraph mode.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

HEADING_FONT_SIZE_THRESHOLD = 13.0   # TUNE — absolute font-size heading threshold (pt)
HEADING_BOLD_MAX_CHARS      = 120    # TUNE — bold block shorter than this → heading
MAX_PARENT_CHARS            = 3000   # TUNE — split sections larger than this
CHILD_CHUNK_TARGET          = 1200   # TUNE — target size of each child chunk
CHILD_OVERLAP_CHARS         = 150    # TUNE — overlap between consecutive child chunks
MIN_SECTION_CHARS           = 80     # TUNE — sections shorter than this are not split
MIN_HEADINGS_FOR_STRUCTURE  = 2      # TUNE — fallback threshold

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Numbered section: "1", "1.1", "3.2.1", "10.1.2" followed by a word character.
# Groups: (1) section number, (2) section title text
_NUMBERED_SECTION_RE = re.compile(
    r'^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\s+(.+)',
    re.UNICODE,
)

# Alternative detection: nullalternativ, alternativ 0/1/2/A/B …
# Trailing \b is intentionally omitted: Norwegian uses definite article suffixes
# (-et, -en) so "nullalternativet" must also match. The leading \b prevents
# false positives on unrelated words.
_ALTERNATIVE_RE = re.compile(
    r'\b(nullalternativ|alternativ\s*\d+[a-z]?|alternativ\s*[a-z])',
    re.IGNORECASE | re.UNICODE,
)

# Area code detection: N01, S03, ØFA1, NFA2, delområde N04, etc.
_DELOMRADE_RE = re.compile(
    r'\b([NØSV][A-ZÆØÅ]?[A-ZÆØÅ]?\d{1,3}[a-z]?)\b',
    re.UNICODE,
)

# ---------------------------------------------------------------------------
# Known Norwegian KU section keywords (lowercase, exact or prefix match)
# ---------------------------------------------------------------------------

_KU_SECTION_KEYWORDS: set[str] = {
    "sammendrag", "innledning", "bakgrunn", "formål",
    "tiltaksbeskrivelse", "planforslag", "prosjektbeskrivelse", "planområde",
    "metode", "kunnskapsgrunnlag", "datagrunnlag", "metodikk",
    "verdivurdering", "verdi og status",
    "påvirkning", "vurdering av påvirkning", "konsekvensvurdering",
    "konsekvens", "samlet konsekvens", "konsekvensgradering",
    "skadereduserende tiltak", "avbøtende tiltak", "kompenserende tiltak",
    "avbøtende og kompenserende tiltak",
    "naturmangfoldloven", "lovverk", "juridisk vurdering",
    "oppsummering", "sammenstilling",
    "usikkerhet", "kunnskapsmangler",
    "referanser", "litteratur", "kilder", "vedlegg",
}

# ---------------------------------------------------------------------------
# Topic classification rules (first match wins)
# ---------------------------------------------------------------------------

# Each entry: (list_of_keywords_to_match, topic_type_string)
_TOPIC_RULES: list[tuple[list[str], str]] = [
    (["sammendrag", "sammenstilling", "oppsummering"],                       "summary"),
    (["innledning", "bakgrunn", "formål"],                                   "introduction"),
    (["tiltaksbeskrivelse", "planforslag", "prosjektbeskrivelse",
      "planområde"],                                                          "project_description"),
    (["metode", "kunnskapsgrunnlag", "datagrunnlag", "metodikk"],            "method"),
    (["verdivurdering", "verdi og status"],                                  "value_assessment"),
    (["påvirkning", "vurdering av påvirkning", "konsekvensvurdering"],       "impact_assessment"),
    (["samlet konsekvens", "konsekvensgradering", "konsekvens"],             "consequence"),
    (["skadereduserende", "avbøtende tiltak", "kompenserende tiltak",
      "avbøtende og kompenserende"],                                         "mitigation"),
    (["naturmangfoldloven", "§§ 8-12", "lovverk", "juridisk", "§"],         "law"),
    (["usikkerhet", "kunnskapsmangler", "mangler"],                         "uncertainty"),
    (["referanser", "litteratur", "kilder", "vedlegg"],                      "references"),
]


# ===========================================================================
# Public API
# ===========================================================================

def chunk_document(
    blocks: list[dict],
    document_name: str,
    source_blob: str,
    file_type: str = "pdf",
) -> list[dict]:
    """
    Main entry point.

    Takes a list of text blocks (from config.fetch_document_blocks) and returns
    a list of chunk dicts ready for storage and embedding.

    Returned chunk dict fields:
        local_id          int       — sequential ID (temporary, for parent tracking)
        local_parent_id   int|None  — local_id of parent, None = top-level
        chunk_index       int
        text              str
        char_count        int
        metadata          dict      — all metadata fields (document_name, heading_path, …)
    """
    if not blocks:
        logger.warning("chunk_document: no blocks provided for '%s'", document_name)
        return []

    body_font_size = _detect_body_font_size(blocks)
    logger.debug("chunk_document: body_font_size=%.1f for '%s'", body_font_size, document_name)

    sections = _detect_sections(blocks, body_font_size)

    if not sections:
        logger.info("chunk_document: heading detection weak — using paragraph fallback for '%s'", document_name)
        return _fallback_paragraph_chunks(blocks, document_name, source_blob, file_type)

    return _structure_based_chunks(sections, document_name, source_blob, file_type)


def blocks_to_text(blocks: list[dict]) -> str:
    """
    Convert a list of blocks back to plain text (joined by double newlines).
    Used to populate documents.content for full-text and fuzzy search.
    """
    return "\n\n".join(
        b.get("text", "").strip()
        for b in blocks
        if b.get("text", "").strip()
    )


# ===========================================================================
# Heading detection
# ===========================================================================

def _detect_body_font_size(blocks: list[dict]) -> float:
    """
    Return the most common (mode) font size across all blocks.
    Used as the baseline for relative heading detection.
    Falls back to 11.0 pt if no font size data is available.
    """
    from collections import Counter
    sizes = [
        round(b.get("font_size", 0))
        for b in blocks
        if b.get("font_size", 0) > 0
    ]
    if not sizes:
        return 11.0
    return float(Counter(sizes).most_common(1)[0][0])


def _parse_numbered_heading(text: str) -> Optional[tuple[str, str, int]]:
    """
    If text matches a numbered section heading, return (number, title, depth).
    Example: "5.1 Alternativ 1" → ("5.1", "Alternativ 1", 2)
    Returns None if text is not a numbered heading.
    """
    m = _NUMBERED_SECTION_RE.match(text.strip())
    if not m:
        return None
    number = m.group(1)
    title  = m.group(2).strip()
    depth  = number.count(".") + 1
    return (number, title, depth)


def _is_known_ku_keyword(text: str) -> bool:
    """Return True if text (lowercased, stripped) matches a known KU section keyword."""
    lower = text.strip().lower()
    if lower in _KU_SECTION_KEYWORDS:
        return True
    # Allow "keyword: ..." or "keyword — ..." prefix forms
    for kw in _KU_SECTION_KEYWORDS:
        if lower.startswith(kw) and len(lower) < len(kw) + 40:
            return True
    return False


def _is_heading(block: dict, body_font_size: float) -> bool:
    """
    Heuristically decide if a block is a section heading.

    Priority order:
      1. Numbered section pattern (strongest — most reliable in KU documents).
      2. Font size >= threshold (absolute or relative to body).
      3. Bold block with short text.
      4. Known Norwegian KU section keyword.

    Rejects:
      - Very short text (< 2 chars), likely artifacts.
      - Pure page numbers (e.g. "1", "42", "- 3 -").
    """
    text = block.get("text", "").strip()
    if len(text) < 2:
        return False

    # Reject pure page numbers / short numeric artifacts
    if re.match(r'^-?\s*\d{1,3}\s*-?$', text):
        return False

    # 1. Numbered section heading (most reliable signal)
    if _parse_numbered_heading(text) is not None:
        return True

    font_size = block.get("font_size", 0.0)
    is_bold   = block.get("is_bold", False)

    # 2. Large font size (absolute threshold OR > 1.2× body size)
    size_threshold = max(HEADING_FONT_SIZE_THRESHOLD, body_font_size * 1.2)
    if font_size >= size_threshold:
        return True

    # 3. Bold and short (un-numbered heading like "Sammendrag" in bold)
    if is_bold and 2 <= len(text) <= HEADING_BOLD_MAX_CHARS:
        return True

    # 4. Known KU section keyword
    if _is_known_ku_keyword(text):
        return True

    return False


# ===========================================================================
# Heading path / stack management
# ===========================================================================

def _update_heading_stack(
    stack: list[tuple[str, str, int]],
    number: str,
    title:  str,
    depth:  int,
) -> list[tuple[str, str, int]]:
    """
    Maintain a heading hierarchy stack.
    Pops all entries at the same depth or deeper, then pushes the new heading.
    Mutates and returns the stack.

    Example:
        stack = [("5", "Vurdering", 1), ("5.1", "Alt 1", 2)]
        new heading: ("5.2", "Alt 2", 2)
        → pops ("5.1", "Alt 1", 2), pushes ("5.2", "Alt 2", 2)
        → stack = [("5", "Vurdering", 1), ("5.2", "Alt 2", 2)]
    """
    while stack and stack[-1][2] >= depth:
        stack.pop()
    stack.append((number, title, depth))
    return stack


def _build_heading_path(stack: list[tuple[str, str, int]]) -> str:
    """
    Render the heading stack as a breadcrumb path string.
    Example: [("5", "Vurdering", 1), ("5.1", "Alt 1", 2)] → "5 Vurdering > 5.1 Alt 1"
    """
    parts = [
        f"{number} {title}".strip() if number else title
        for number, title, _ in stack
    ]
    return " > ".join(parts)


# ===========================================================================
# Metadata helpers
# ===========================================================================

def _classify_topic(heading_path: str, section_title: str) -> str:
    """
    Rule-based topic classification.
    Searches heading_path + section_title (lowercased) against _TOPIC_RULES.
    Returns the first matching topic type, or "other".
    """
    haystack = (heading_path + " " + section_title).lower()
    for keywords, topic in _TOPIC_RULES:
        if any(kw in haystack for kw in keywords):
            return topic
    return "other"


def _detect_alternative(text: str) -> Optional[str]:
    """
    Detect alternative references in heading text (nullalternativ, alternativ 1 …).
    Returns the normalised match or None.
    """
    m = _ALTERNATIVE_RE.search(text)
    if m:
        return re.sub(r'\s+', ' ', m.group(1).lower())
    return None


def _detect_delomrade(text: str) -> Optional[str]:
    """
    Detect area codes (delområde) like N01, ØFA1, S03 in a heading or path.
    Returns the first match or None.
    """
    m = _DELOMRADE_RE.search(text)
    if m:
        return m.group(1)
    return None


def _detect_table(text: str) -> bool:
    """
    Heuristic: returns True if the text likely contains a table.
    Looks for 3+ lines with tab-separated or pipe-delimited content.
    """
    lines = text.splitlines()
    if len(lines) < 3:
        return False
    table_line_count = sum(
        1 for line in lines
        if "\t" in line or line.count("|") >= 2
    )
    return table_line_count >= 3


def _build_metadata(
    document_name: str,
    source_blob:   str,
    file_type:     str,
    heading_path:  str,
    section_title: str,
    section_number: Optional[str],
    topic_type:    str,
    alternative:   Optional[str],
    delomrade:     Optional[str],
    contains_table: bool,
    page_start:    int,
    page_end:      int,
) -> dict:
    return {
        "document_name":  document_name,
        "source_blob":    source_blob,
        "file_type":      file_type,
        "heading_path":   heading_path or None,
        "section_title":  section_title or None,
        "section_number": section_number or None,
        "topic_type":     topic_type,
        "alternative":    alternative,
        "delomrade":      delomrade,
        "contains_table": contains_table,
        "page_start":     page_start,
        "page_end":       page_end,
    }


# ===========================================================================
# Section detection
# ===========================================================================

def _detect_sections(blocks: list[dict], body_font_size: float) -> list[dict]:
    """
    Walk all blocks and split them into sections at every detected heading.

    Returns a list of section dicts:
        heading_text    str   — full text of the heading block
        heading_number  str   — e.g. "5.1" or "" for un-numbered headings
        heading_title   str   — e.g. "Alternativ 1"
        heading_depth   int   — 1 = top-level section
        page_start      int
        page_end        int
        blocks          list  — content blocks that follow this heading

    Returns an empty list if fewer than MIN_HEADINGS_FOR_STRUCTURE headings
    are detected (signals the caller to use paragraph fallback).
    """
    sections: list[dict]       = []
    current: Optional[dict]    = None

    for block in blocks:
        text = block.get("text", "").strip()
        page = block.get("page", 1)

        if _is_heading(block, body_font_size):
            # Save the section we were building
            if current is not None:
                sections.append(current)

            parsed = _parse_numbered_heading(text)
            if parsed:
                number, title, depth = parsed
            else:
                number, title, depth = "", text, 1

            current = {
                "heading_text":   text,
                "heading_number": number,
                "heading_title":  title,
                "heading_depth":  depth,
                "page_start":     page,
                "page_end":       page,
                "blocks":         [],
            }

        else:
            if current is None:
                # Text before any heading — collect in a preamble section
                current = {
                    "heading_text":   "",
                    "heading_number": "",
                    "heading_title":  "Preamble",
                    "heading_depth":  0,
                    "page_start":     page,
                    "page_end":       page,
                    "blocks":         [],
                }
            if text:
                current["blocks"].append(block)
                current["page_end"] = page

    # Flush the last open section
    if current is not None:
        sections.append(current)

    # Evaluate whether structure detection was successful
    named_sections = [
        s for s in sections
        if s["heading_number"] or s["heading_title"] not in ("Preamble", "")
    ]
    if len(named_sections) < MIN_HEADINGS_FOR_STRUCTURE:
        logger.warning(
            "_detect_sections: only %d named sections found — signalling fallback",
            len(named_sections),
        )
        return []

    return sections


# ===========================================================================
# Paragraph helpers
# ===========================================================================

def _split_into_paragraphs(text: str) -> list[str]:
    """
    Split text at double-newline boundaries.
    Merges very short fragments (< 80 chars) with the following paragraph
    to avoid creating context-less micro-chunks.
    """
    raw_paras = re.split(r'\n{2,}', text)
    result: list[str] = []
    buffer = ""

    for para in raw_paras:
        para = para.strip()
        if not para:
            continue
        if buffer:
            buffer += "\n\n" + para
            if len(buffer) >= 80:
                result.append(buffer)
                buffer = ""
        elif len(para) < 80:
            buffer = para
        else:
            result.append(para)

    if buffer:
        result.append(buffer)

    return result if result else [text.strip()]


def _group_paragraphs_into_children(
    paragraphs:     list[str],
    target_size:    int = CHILD_CHUNK_TARGET,
    overlap_chars:  int = CHILD_OVERLAP_CHARS,
) -> list[str]:
    """
    Greedily accumulate paragraphs until target_size is reached, then flush.
    Each subsequent group starts with overlap_chars from the end of the
    previous group to preserve cross-boundary context.
    """
    if not paragraphs:
        return []

    groups: list[str] = []
    current_parts: list[str] = []
    current_len   = 0
    overlap_prefix = ""  # appended to the start of the next group

    for para in paragraphs:
        para_len = len(para)

        if current_len + para_len > target_size and current_parts:
            # Flush current group
            joined = "\n\n".join(current_parts)
            group_text = (overlap_prefix + "\n\n" + joined) if overlap_prefix else joined
            groups.append(group_text.strip())

            # Compute overlap for the next group
            overlap_prefix = joined[-overlap_chars:] if len(joined) > overlap_chars else joined

            current_parts = [para]
            current_len   = para_len
        else:
            current_parts.append(para)
            current_len += para_len

    # Flush final group
    if current_parts:
        joined = "\n\n".join(current_parts)
        group_text = (overlap_prefix + "\n\n" + joined) if (overlap_prefix and groups) else joined
        groups.append(group_text.strip())

    return [g for g in groups if g.strip()]


# ===========================================================================
# Structure-based chunking
# ===========================================================================

def _structure_based_chunks(
    sections:      list[dict],
    document_name: str,
    source_blob:   str,
    file_type:     str,
) -> list[dict]:
    """
    Build parent and child chunks from a list of detected sections.

    - Short sections (≤ MAX_PARENT_CHARS) → single parent chunk.
    - Long sections (> MAX_PARENT_CHARS) → one parent chunk (heading + intro para)
      followed by N child chunks covering the full section body.
    """
    chunks: list[dict] = []
    local_id     = 0
    chunk_index  = 0
    heading_stack: list[tuple[str, str, int]] = []

    for section in sections:
        number = section["heading_number"]
        title  = section["heading_title"]
        depth  = section["heading_depth"]

        # Update path stack (skip the synthetic preamble section)
        if number or title not in ("Preamble", ""):
            _update_heading_stack(heading_stack, number, title, depth)

        heading_path = _build_heading_path(heading_stack)

        # Build body text from all content blocks in this section
        body_text = "\n\n".join(
            b.get("text", "").strip()
            for b in section["blocks"]
            if b.get("text", "").strip()
        )

        # A section with a heading but no body text still produces a chunk
        # (the heading itself may be informative for retrieval)
        if not body_text and not section["heading_text"]:
            continue

        page_start     = section.get("page_start", 1)
        page_end       = section.get("page_end", page_start)
        contains_table = _detect_table(body_text)
        alternative    = _detect_alternative(heading_path)
        delomrade      = _detect_delomrade(heading_path)
        topic_type     = _classify_topic(heading_path, title)

        base_meta = _build_metadata(
            document_name  = document_name,
            source_blob    = source_blob,
            file_type      = file_type,
            heading_path   = heading_path,
            section_title  = title,
            section_number = number or None,
            topic_type     = topic_type,
            alternative    = alternative,
            delomrade      = delomrade,
            contains_table = contains_table,
            page_start     = page_start,
            page_end       = page_end,
        )

        # Heading prefix used to anchor chunks to their section
        heading_prefix = section["heading_text"]

        parent_local_id = local_id

        if len(body_text) <= MAX_PARENT_CHARS:
            # ── Short section: single chunk ──────────────────────────────
            full_text = (
                f"{heading_prefix}\n\n{body_text}".strip()
                if heading_prefix else body_text
            )
            chunks.append({
                "local_id":        local_id,
                "local_parent_id": None,
                "chunk_index":     chunk_index,
                "text":            full_text,
                "char_count":      len(full_text),
                "metadata":        dict(base_meta),
            })
            local_id    += 1
            chunk_index += 1

        else:
            # ── Long section: parent + child chunks ──────────────────────
            paragraphs   = _split_into_paragraphs(body_text)
            child_groups = _group_paragraphs_into_children(paragraphs)

            # Parent chunk: heading + first paragraph (orientation / intro)
            intro = paragraphs[0] if paragraphs else body_text[:300]
            parent_text = (
                f"{heading_prefix}\n\n{intro}".strip()
                if heading_prefix else intro
            )
            chunks.append({
                "local_id":        parent_local_id,
                "local_parent_id": None,
                "chunk_index":     chunk_index,
                "text":            parent_text,
                "char_count":      len(parent_text),
                "metadata":        dict(base_meta),
            })
            local_id    += 1
            chunk_index += 1

            # Child chunks: cover the full section body
            for group_text in child_groups:
                chunks.append({
                    "local_id":        local_id,
                    "local_parent_id": parent_local_id,
                    "chunk_index":     chunk_index,
                    "text":            group_text,
                    "char_count":      len(group_text),
                    "metadata":        dict(base_meta),
                })
                local_id    += 1
                chunk_index += 1

    logger.info(
        "chunk_document: '%s' → %d chunks (structure-based, %d sections)",
        document_name, len(chunks), len(sections),
    )
    return chunks


# ===========================================================================
# Paragraph-based fallback
# ===========================================================================

def _fallback_paragraph_chunks(
    blocks:        list[dict],
    document_name: str,
    source_blob:   str,
    file_type:     str,
) -> list[dict]:
    """
    Used when heading structure detection fails.
    Groups all blocks into paragraph-based chunks of ~CHILD_CHUNK_TARGET chars.
    Respects paragraph boundaries (always better than raw fixed-size splitting).
    """
    full_text  = blocks_to_text(blocks)
    paragraphs = _split_into_paragraphs(full_text)
    groups     = _group_paragraphs_into_children(
        paragraphs,
        target_size   = CHILD_CHUNK_TARGET,
        overlap_chars = CHILD_OVERLAP_CHARS,
    )

    total_pages = max((b.get("page", 1) for b in blocks), default=1)
    chunks: list[dict] = []

    for i, group_text in enumerate(groups):
        # Rough page estimate: spread chunks evenly from page 1 to total_pages
        if len(groups) <= 1:
            page_est = 1
        else:
            page_est = max(1, round(1 + i * (total_pages - 1) / (len(groups) - 1)))
        meta = _build_metadata(
            document_name  = document_name,
            source_blob    = source_blob,
            file_type      = file_type,
            heading_path   = None,
            section_title  = None,
            section_number = None,
            topic_type     = "other",
            alternative    = None,
            delomrade      = None,
            contains_table = _detect_table(group_text),
            page_start     = page_est,
            page_end       = page_est,
        )
        chunks.append({
            "local_id":        i,
            "local_parent_id": None,
            "chunk_index":     i,
            "text":            group_text,
            "char_count":      len(group_text),
            "metadata":        meta,
        })

    logger.info(
        "chunk_document: '%s' → %d chunks (paragraph fallback)",
        document_name, len(chunks),
    )
    return chunks
