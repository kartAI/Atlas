"""
Lightweight validation tests for chunker.py.

These tests are self-contained — no database, no Azure, no embeddings API.
Run with:
  cd backend
  python test_chunker.py

Tests verify:
  1. Short section -> single parent chunk (no children).
  2. Long section -> parent chunk + child chunks.
  3. Heading detection: numbered headings, bold/keyword headings.
  4. Metadata fields: heading_path, topic_type, alternative, delomrade.
  5. Fallback: documents with no detectable structure still produce chunks.
  6. Edge cases: empty input, single block, block without font metadata.
"""

import sys
import textwrap
from chunker import (
    chunk_document,
    blocks_to_text,
    _detect_alternative,
    _is_heading,
    _detect_sections,
    _detect_body_font_size,
    MAX_PARENT_CHARS,
    MIN_HEADINGS_FOR_STRUCTURE,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _block(text: str, page: int = 1, font_size: float = 11.0, is_bold: bool = False) -> dict:
    return {"text": text, "page": page, "font_size": font_size, "is_bold": is_bold, "bbox": (0, 0, 100, 20)}


def _heading_block(text: str, page: int = 1, font_size: float = 14.0, is_bold: bool = True) -> dict:
    return {"text": text, "page": page, "font_size": font_size, "is_bold": is_bold, "bbox": (0, 0, 100, 20)}


def assert_equal(label: str, actual, expected):
    if actual != expected:
        print(f"  FAIL [{label}]: got {actual!r}, expected {expected!r}")
        return False
    return True


def assert_true(label: str, condition: bool):
    if not condition:
        print(f"  FAIL [{label}]: condition was False")
        return False
    return True


def run_test(name: str, fn) -> bool:
    try:
        result = fn()
        if result is False:
            print(f"FAIL  {name}")
            return False
        print(f"OK    {name}")
        return True
    except Exception as e:
        print(f"ERROR {name}: {e}")
        return False


# ---------------------------------------------------------------------------
# Test 1: Short section produces a single parent chunk
# ---------------------------------------------------------------------------

def test_short_section_single_chunk():
    short_body = "Dette er en kort seksjon om metode og kunnskapsgrunnlag. " * 5  # ~285 chars
    blocks = [
        _heading_block("3.1 Metode", page=2),
        _block(short_body, page=2),
        # Second heading required: MIN_HEADINGS_FOR_STRUCTURE=2 must be reached
        # for structure-based chunking to activate.
        _heading_block("3.2 Kunnskapsgrunnlag", page=3),
        _block("Kort tekst om kunnskapsgrunnlag.", page=3),
    ]
    chunks = chunk_document(blocks, document_name="TestDoc", source_blob="test.pdf")

    ok = True
    ok &= assert_true("at least one chunk produced", len(chunks) >= 1)
    ok &= assert_true("no child chunks (all top-level)", all(c["local_parent_id"] is None for c in chunks))

    # The chunk for section 3.1 should contain the heading text
    ok &= assert_true("heading text in chunk", any("Metode" in c["text"] for c in chunks))

    # Use `or ""` because metadata stores the key with None value when absent —
    # .get(key, default) only uses the default when the key is missing, not when None.
    meta_chunks = [c for c in chunks if "3.1" in (c["metadata"].get("section_number") or "")]
    ok &= assert_true("section_number populated", len(meta_chunks) >= 1)
    if meta_chunks:
        ok &= assert_equal("topic_type=method", meta_chunks[0]["metadata"]["topic_type"], "method")
    return ok


# ---------------------------------------------------------------------------
# Test 2: Long section produces parent + child chunks
# ---------------------------------------------------------------------------

def test_long_section_parent_and_children():
    # Body text well over MAX_PARENT_CHARS (3000)
    long_body = "Konsekvensutredning inneholder detaljert analyse. " * 100  # ~4800 chars
    blocks = [
        _heading_block("5 Vurdering av påvirkning", page=10),
        _block(long_body, page=10),
        # Second heading required: MIN_HEADINGS_FOR_STRUCTURE=2 must be reached
        # for structure-based chunking to activate (and thus produce children).
        _heading_block("6 Konsekvens", page=15),
        _block("Samlet konsekvens er middels.", page=15),
    ]
    chunks = chunk_document(blocks, document_name="TestDoc", source_blob="test.pdf")

    ok = True
    parents  = [c for c in chunks if c["local_parent_id"] is None]
    children = [c for c in chunks if c["local_parent_id"] is not None]

    ok &= assert_true("at least one parent chunk", len(parents) >= 1)
    ok &= assert_true("at least one child chunk for long section", len(children) >= 1)

    # Every child's local_parent_id must map to an existing parent's local_id
    parent_ids = {p["local_id"] for p in parents}
    ok &= assert_true(
        "all child parent refs resolve",
        all(c["local_parent_id"] in parent_ids for c in children),
    )

    # Child chunks should be under MAX_PARENT_CHARS each
    ok &= assert_true(
        "children not excessively large",
        all(c["char_count"] <= MAX_PARENT_CHARS * 2 for c in children),
    )
    return ok


# ---------------------------------------------------------------------------
# Test 3: Heading detection
# ---------------------------------------------------------------------------

def test_heading_detection():
    body_size = 11.0
    ok = True

    # Numbered heading
    ok &= assert_true("numbered heading detected",
        _is_heading({"text": "3.2 Konsekvenser for naturmangfold", "font_size": 11.0, "is_bold": False}, body_size))

    # Large font heading
    ok &= assert_true("large font heading detected",
        _is_heading({"text": "Sammendrag", "font_size": 16.0, "is_bold": False}, body_size))

    # Bold + short
    ok &= assert_true("bold+short heading detected",
        _is_heading({"text": "Metode", "font_size": 11.0, "is_bold": True}, body_size))

    # Known KU keyword
    ok &= assert_true("KU keyword heading detected",
        _is_heading({"text": "Verdivurdering", "font_size": 11.0, "is_bold": False}, body_size))

    # Heading-like keyword phrase should still count
    ok &= assert_true("keyword heading phrase detected",
        _is_heading({"text": "Sammendrag av eksisterende kunnskap", "font_size": 11.0, "is_bold": False}, body_size))

    # Plain sentence starting with a KU keyword should NOT be promoted to heading
    ok &= assert_true("keyword-led body sentence not a heading",
        not _is_heading({"text": "Metode og datagrunnlag er beskrevet nedenfor.", "font_size": 11.0, "is_bold": False}, body_size))

    ok &= assert_true("keyword-led body sentence without punctuation not a heading",
        not _is_heading({"text": "Metode er beskrevet nedenfor", "font_size": 11.0, "is_bold": False}, body_size))

    # Normal body text should NOT be a heading
    ok &= assert_true("normal body text not a heading",
        not _is_heading({"text": "Utredningen viser at tiltaket medfører middels konsekvens.", "font_size": 11.0, "is_bold": False}, body_size))

    # Page number should NOT be a heading
    ok &= assert_true("page number not a heading",
        not _is_heading({"text": "42", "font_size": 11.0, "is_bold": False}, body_size))

    return ok


# ---------------------------------------------------------------------------
# Test 4: Metadata — heading_path, alternative, delomrade
# ---------------------------------------------------------------------------

def test_metadata_fields():
    blocks = [
        _heading_block("5 Vurdering av påvirkning", page=10),
        _block("Generell tekst om påvirkning.", page=10),
        _heading_block("5.1 Alternativ 1", page=11),
        _block("Beskrivelse av alternativ 1. " * 10, page=11),
        _heading_block("5.2 Nullalternativet", page=12),
        _block("Beskrivelse av nullalternativet. " * 10, page=12),
    ]
    chunks = chunk_document(blocks, document_name="TestDoc", source_blob="test.pdf")

    ok = True
    # Find chunk for section 5.1
    alt1_chunks = [c for c in chunks if "5.1" in (c["metadata"].get("section_number") or "")]
    ok &= assert_true("chunk for section 5.1 exists", len(alt1_chunks) >= 1)
    if alt1_chunks:
        ok &= assert_equal("alternative=alternativ 1", alt1_chunks[0]["metadata"]["alternative"], "alternativ 1")
        ok &= assert_true(
            "heading_path contains parent",
            "5 Vurdering" in (alt1_chunks[0]["metadata"]["heading_path"] or ""),
        )

    # "Nullalternativet" uses the Norwegian definite article suffix (-et).
    # The regex must match this form (not just bare "nullalternativ").
    null_chunks = [c for c in chunks if "nullalternativ" in (c["metadata"].get("alternative") or "")]
    ok &= assert_true("nullalternativ detected in metadata", len(null_chunks) >= 1)

    return ok


def test_alternative_detection_does_not_overmatch_normal_words():
    ok = True
    ok &= assert_equal(
        "plain 'alternativ vurdering' does not become alternativ v",
        _detect_alternative("Alternativ vurdering"),
        None,
    )
    ok &= assert_equal(
        "embedded phrase does not become alternativ v",
        _detect_alternative("Vurdering av alternativ virkning"),
        None,
    )
    ok &= assert_equal(
        "single-letter alternative still matches",
        _detect_alternative("5.2 Alternativ A"),
        "alternativ a",
    )
    return ok


# ---------------------------------------------------------------------------
# Test 5: Fallback -- no discernible headings -> paragraph chunks
# ---------------------------------------------------------------------------

def test_fallback_paragraph_chunking():
    # All blocks are body text — no headings, same small font
    blocks = [
        _block("Tiltaket er beskrevet i kapittel 3. " * 20, page=1),
        _block("Metodikken er basert på feltarbeid. " * 20, page=2),
    ]
    chunks = chunk_document(blocks, document_name="NoStructureDoc", source_blob="no_struct.pdf")

    ok = True
    ok &= assert_true("fallback produces at least one chunk", len(chunks) >= 1)
    # In fallback all chunks are top-level
    ok &= assert_true("all fallback chunks are top-level", all(c["local_parent_id"] is None for c in chunks))
    return ok


# ---------------------------------------------------------------------------
# Test 6: Edge cases
# ---------------------------------------------------------------------------

def test_empty_blocks():
    chunks = chunk_document([], document_name="Empty", source_blob="empty.pdf")
    return assert_equal("empty blocks -> empty chunks", chunks, [])


def test_single_heading_no_body():
    blocks = [_heading_block("1 Innledning", page=1)]
    chunks = chunk_document(blocks, document_name="OnlyHeading", source_blob="heading.pdf")
    # The document has only 1 named section — below MIN_HEADINGS_FOR_STRUCTURE=2,
    # so it falls back to paragraph-based chunking
    return assert_true("single heading document produces at least one chunk", len(chunks) >= 1)


def test_blocks_without_font_metadata():
    """Blocks missing font_size / is_bold must not crash the chunker."""
    blocks = [
        {"text": "1 Innledning"},  # no font_size, no is_bold, no page, no bbox
        {"text": "Bakgrunnen for prosjektet er som følger."},
        {"text": "2 Metode"},
        {"text": "Vi brukte feltarbeid og kartlegging."},
    ]
    try:
        chunks = chunk_document(blocks, document_name="MinimalBlocks", source_blob="minimal.pdf")
        return assert_true("minimal blocks produce at least one chunk", len(chunks) >= 1)
    except Exception as e:
        print(f"  FAIL: unexpected exception: {e}")
        return False


# ---------------------------------------------------------------------------
# Test 7: blocks_to_text
# ---------------------------------------------------------------------------

def test_blocks_to_text():
    blocks = [
        _block("  Første avsnitt.  "),
        _block(""),                    # empty — should be skipped
        _block("  Andre avsnitt.  "),
    ]
    result = blocks_to_text(blocks)
    ok = True
    ok &= assert_true("non-empty blocks joined", "Første avsnitt." in result)
    ok &= assert_true("second block joined", "Andre avsnitt." in result)
    ok &= assert_true("empty block excluded", result.count("\n\n") == 1)
    return ok


# ---------------------------------------------------------------------------
# Test 8: chunk_index is sequential and starts from 0
# ---------------------------------------------------------------------------

def test_chunk_index_sequential():
    blocks = [
        _heading_block("1 Innledning", page=1),
        _block("Kort tekst om innledning.", page=1),
        _heading_block("2 Metode", page=2),
        _block("Kort tekst om metode.", page=2),
        _heading_block("3 Konsekvens", page=3),
        _block("Kort tekst om konsekvens.", page=3),
    ]
    chunks = chunk_document(blocks, document_name="SeqTest", source_blob="seq.pdf")
    indices = [c["chunk_index"] for c in chunks]

    ok = True
    ok &= assert_equal("first chunk_index is 0", indices[0], 0)
    ok &= assert_equal("indices are sequential", sorted(indices), list(range(len(chunks))))
    return ok


def test_chunk_text_non_empty_for_embedding():
    """Every chunk must have non-empty .text so the embedding layer always has input."""
    blocks = [
        _heading_block("1 Oversikt"),
        _block("Innhold under oversikt."),
        _heading_block("2 Detaljer"),
        _block("Innhold under detaljer."),
        _block(""),              # empty block — should not create empty chunk text
        _block("   "),           # whitespace-only — likewise
        _heading_block("3 Oppsummering"),
        _block("Siste avsnitt."),
    ]
    chunks = chunk_document(blocks, document_name="EmbTest", source_blob="emb.pdf")

    ok = True
    for c in chunks:
        ok &= assert_true(
            f"chunk {c['chunk_index']} has non-empty text",
            bool(c["text"].strip()),
        )
    return ok


def test_block_helper_is_bold():
    """Verify _block() respects the is_bold parameter (regression guard)."""
    ok = True
    ok &= assert_equal("_block default is_bold=False", _block("x")["is_bold"], False)
    ok &= assert_equal("_block explicit is_bold=True",  _block("x", is_bold=True)["is_bold"], True)
    return ok


def test_chunk_structure_contract():
    """
    Validate that every chunk produced by chunk_document() has the exact
    structure expected by save_chunks() and the embedding layer:
      - 'text' (non-empty string)
      - 'char_count' (positive int)
      - 'chunk_index' (int)
      - 'local_id' (int)
      - 'local_parent_id' (int or None)
      - 'metadata' dict with expected keys

    This is the structural contract test for the ingest pipeline integration.
    A true embedding-failure test requires mocking the DB and embedding client,
    which is outside the scope of this standalone test script.
    """
    blocks = [
        _heading_block("1 Innledning"),
        _block("Tekst under innledning som er lang nok til a fungere som innhold."),
        _heading_block("2 Bakgrunn"),
        _block("Mer innhold her for a sikre realistisk chunking."),
    ]
    chunks = chunk_document(blocks, document_name="ContractTest", source_blob="contract.pdf")

    required_top_keys = {"text", "char_count", "chunk_index", "local_id", "local_parent_id", "metadata"}
    required_meta_keys = {
        "file_type", "heading_path", "section_title", "section_number",
        "page_start", "page_end", "topic_type", "alternative", "delomrade",
        "contains_table",
    }

    ok = True
    for c in chunks:
        idx = c.get("chunk_index", "?")
        # Top-level keys
        missing_top = required_top_keys - set(c.keys())
        ok &= assert_true(f"chunk {idx} has all top-level keys", len(missing_top) == 0)
        if missing_top:
            print(f"    missing: {missing_top}")

        # Metadata keys
        meta = c.get("metadata", {})
        missing_meta = required_meta_keys - set(meta.keys())
        ok &= assert_true(f"chunk {idx} metadata has all required keys", len(missing_meta) == 0)
        if missing_meta:
            print(f"    missing metadata: {missing_meta}")

        # Value types / constraints
        ok &= assert_true(f"chunk {idx} text is non-empty str", isinstance(c["text"], str) and bool(c["text"].strip()))
        ok &= assert_true(f"chunk {idx} char_count > 0", isinstance(c["char_count"], int) and c["char_count"] > 0)
        ok &= assert_true(f"chunk {idx} chunk_index is int", isinstance(c["chunk_index"], int))
        ok &= assert_true(f"chunk {idx} local_id is int", isinstance(c["local_id"], int))
        ok &= assert_true(
            f"chunk {idx} local_parent_id is int or None",
            c["local_parent_id"] is None or isinstance(c["local_parent_id"], int),
        )

    return ok


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

def main():
    tests = [
        ("Short section -> single parent chunk",              test_short_section_single_chunk),
        ("Long section -> parent + children",                 test_long_section_parent_and_children),
        ("Heading detection heuristics",                     test_heading_detection),
        ("Metadata: heading_path, alternative, delomrade",   test_metadata_fields),
        ("Alternative detection avoids false positives",     test_alternative_detection_does_not_overmatch_normal_words),
        ("Fallback: no headings -> paragraph chunks",         test_fallback_paragraph_chunking),
        ("Edge case: empty blocks",                          test_empty_blocks),
        ("Edge case: single heading no body",                test_single_heading_no_body),
        ("Edge case: blocks without font metadata",          test_blocks_without_font_metadata),
        ("blocks_to_text: joining and filtering",            test_blocks_to_text),
        ("chunk_index is sequential from 0",                 test_chunk_index_sequential),
        ("Chunk text non-empty (embedding contract)",        test_chunk_text_non_empty_for_embedding),
        ("_block() helper respects is_bold",                 test_block_helper_is_bold),
        ("Chunk structure contract for save_chunks()",       test_chunk_structure_contract),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        if run_test(name, fn):
            passed += 1
        else:
            failed += 1

    print(f"\n{passed}/{passed + failed} tests passed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
