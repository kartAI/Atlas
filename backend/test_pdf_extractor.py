#!/usr/bin/env python3
"""
Focused regression tests for pdf_extractor.py edge-block heuristics.

These tests stub Blob Storage before importing pdf_extractor so no Azure
configuration or network access is required.

Usage:
  python backend/test_pdf_extractor.py
"""

import sys
import types


def _stub_blob_storage():
    mod = types.ModuleType("blob_storage")
    mod.download_blob_bytes = lambda blob_name: b""
    sys.modules["blob_storage"] = mod


_stub_blob_storage()

import pdf_extractor  # noqa: E402


_passed = 0
_failed = 0


def assert_equal(label: str, got, expected):
    global _passed, _failed
    if got == expected:
        print(f"OK    {label}")
        _passed += 1
        return True
    print(f"FAIL  {label}")
    print(f"      expected: {expected!r}")
    print(f"      got:      {got!r}")
    _failed += 1
    return False


def test_bold_running_header_is_still_skipped():
    """Plain bold headers near the page edge should not be preserved as headings."""
    result = pdf_extractor._should_skip_edge_block(
        "KU E6 Moelv",
        (0, 5, 100, 20),
        1000,
        11.0,
        True,
    )
    assert_equal("bold running header is skipped", result, True)


def test_numbered_heading_near_edge_is_kept():
    """A real numbered section heading near the edge should survive the filter."""
    result = pdf_extractor._should_skip_edge_block(
        "5.2 Alternativ A",
        (0, 5, 100, 20),
        1000,
        11.0,
        False,
    )
    assert_equal("numbered heading near edge is kept", result, False)


def test_known_keyword_near_edge_is_kept():
    """Known KU section keywords should still survive header/footer stripping."""
    result = pdf_extractor._should_skip_edge_block(
        "Metode",
        (0, 5, 100, 20),
        1000,
        11.0,
        False,
    )
    assert_equal("known keyword near edge is kept", result, False)


if __name__ == "__main__":
    test_bold_running_header_is_still_skipped()
    test_numbered_heading_near_edge_is_kept()
    test_known_keyword_near_edge_is_kept()

    total = _passed + _failed
    print(f"\n{_passed}/{total} tests passed.")
    sys.exit(0 if _failed == 0 else 1)
