#!/usr/bin/env python3
"""
Unit tests for ingest pipeline and search service status/filtering logic.

Covers:
  - stale-processing recovery in run_pipeline()
  - status transitions in process_document(): ready / partial / failed
  - search query filtering (indexing_status IN ('ready', 'partial'))

All database, Azure Blob Storage, and embedding API calls are mocked.
No running services or environment variables required.

Usage:
  python backend/test_ingest.py
"""

import asyncio
import logging
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# Suppress pipeline log noise during tests (warnings and errors are expected).
logging.disable(logging.CRITICAL)


# ---------------------------------------------------------------------------
# Stub out all infrastructure modules BEFORE importing pipeline code.
# ---------------------------------------------------------------------------

def _stub(name: str, **attrs):
    mod = types.ModuleType(name)
    for attr_name, attr_value in attrs.items():
        setattr(mod, attr_name, attr_value)
    sys.modules[name] = mod
    return mod


_stub(
    "db",
    query=AsyncMock(),
    execute=AsyncMock(),
    get_connection=MagicMock(),
)
_stub(
    "config",
    fetch_document=MagicMock(return_value=""),
    fetch_document_blocks=MagicMock(return_value=[]),
    list_documents_with_metadata=MagicMock(return_value=[]),
)
_stub(
    "embedding_client",
    get_embeddings=AsyncMock(return_value=[]),
    get_single_embedding=AsyncMock(return_value=None),
)
_stub(
    "chunker",
    chunk_document=MagicMock(return_value=[]),
    blocks_to_text=MagicMock(return_value="sample content"),
)

import ingest_pipeline  # noqa: E402 (must come after stubs)
import search_service   # noqa: E402


# ---------------------------------------------------------------------------
# Test framework helpers
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def assert_equal(label: str, got, expected) -> bool:
    global _passed, _failed
    if got == expected:
        print(f"  OK    {label}")
        _passed += 1
        return True
    print(f"  FAIL  {label}")
    print(f"        expected: {expected!r}")
    print(f"        got:      {got!r}")
    _failed += 1
    return False


def assert_true(label: str, condition) -> bool:
    return assert_equal(label, bool(condition), True)


def assert_in(label: str, needle: str, haystack: str) -> bool:
    global _passed, _failed
    if needle in haystack:
        print(f"  OK    {label}")
        _passed += 1
        return True
    print(f"  FAIL  {label}")
    print(f"        expected {needle!r} to appear in SQL")
    _failed += 1
    return False


def _run_test(test_function):
    try:
        test_function()
    except Exception as exception:
        global _failed
        _failed += 1
        print(f"  FAIL  {test_function.__name__}: raised {type(exception).__name__}: {exception}")


# ---------------------------------------------------------------------------
# Blob / chunk fixtures
# ---------------------------------------------------------------------------

def _blob(name="doc.pdf", last_modified="2024-01-01", file_hash="abc"):
    return {"name": name, "last_modified": last_modified, "file_hash": file_hash}


def _fake_chunks(count: int) -> list[dict]:
    return [
        {
            "local_id": chunk_num,
            "local_parent_id": None,
            "chunk_index": chunk_num,
            "text": f"chunk {chunk_num}",
            "char_count": 7,
            "metadata": {},
        }
        for chunk_num in range(count)
    ]


class _FakeCursor:
    def __init__(self, returned_ids: list[int]):
        self._rows = [{"id": row_id} for row_id in returned_ids]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exception_type, exception_value, traceback_value):
        return False

    async def execute(self, query_sql, params=None):
        return None

    async def fetchone(self):
        if not self._rows:
            return None
        return self._rows.pop(0)


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exception_type, exception_value, traceback_value):
        return False


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, exception_type, exception_value, traceback_value):
        return False

    def transaction(self):
        return _FakeTransaction()

    def cursor(self):
        return self._cursor


# ---------------------------------------------------------------------------
# Helper: run process_document with controlled mocks.
# Returns (result_dict, update_index_status_mock).
# ---------------------------------------------------------------------------

def _run_process(
    *,
    claim_returns=None,          # what the atomic claim query returns
    chunks=None,                 # return value of chunker.chunk_document
    blocks_text="content here",  # return value of chunker.blocks_to_text
    save_chunks_returns=(3, 3),  # (total_inserted, embedded_count)
    extract_blocks_raises=None,  # if set, extract_blocks raises this
    generate_emb_returns=None,   # return value of generate_embeddings
):
    if claim_returns is None:
        claim_returns = [{"id": 1}]
    if chunks is None:
        chunks = _fake_chunks(3)

    result_holder = {}
    mock_update_index_status_holder = {}

    async def run_coroutine():
        with (
            patch.object(ingest_pipeline, "query", new_callable=AsyncMock) as mock_query,
            patch.object(ingest_pipeline, "extract_blocks", new_callable=AsyncMock) as mock_extract_blocks,
            patch.object(ingest_pipeline, "save_indexed_document", new_callable=AsyncMock) as mock_save_indexed_document,
            patch.object(ingest_pipeline, "save_chunks", new_callable=AsyncMock) as mock_save_chunks,
            patch.object(ingest_pipeline, "update_index_status", new_callable=AsyncMock) as mock_update_index_status,
            patch.object(ingest_pipeline, "execute", new_callable=AsyncMock),
            patch.object(ingest_pipeline, "generate_embeddings", new_callable=AsyncMock) as mock_generate_embeddings,
            patch("chunker.chunk_document", return_value=chunks),
            patch("chunker.blocks_to_text", return_value=blocks_text),
        ):
            mock_query.return_value = claim_returns
            if extract_blocks_raises:
                mock_extract_blocks.side_effect = extract_blocks_raises
            else:
                mock_extract_blocks.return_value = [{"text": "block"}]
            mock_save_indexed_document.return_value = 1
            mock_save_chunks.return_value = save_chunks_returns
            mock_generate_embeddings.return_value = generate_emb_returns

            result = await ingest_pipeline.process_document(_blob())
            result_holder["result"] = result
            mock_update_index_status_holder["mock"] = mock_update_index_status

    asyncio.run(run_coroutine())
    return result_holder["result"], mock_update_index_status_holder["mock"]


# ===========================================================================
# 1. Stale-processing recovery
# ===========================================================================

print("\n# Stale-processing recovery")


def test_stale_reclaim_sql_resets_to_new():
    """The reclaim UPDATE must target processing rows and reset them to 'new'."""
    async def run_coroutine():
        with (
            patch.object(ingest_pipeline, "query", new_callable=AsyncMock) as mock_query,
            patch.object(ingest_pipeline, "discover_documents", new_callable=AsyncMock) as mock_discover_documents,
        ):
            mock_query.return_value = [{"source_blob": "stale.pdf"}]
            mock_discover_documents.return_value = []
            await ingest_pipeline.run_pipeline()

            captured_sql, params = mock_query.call_args.args
            assert_in("reclaim SQL resets to 'new'", "indexing_status = 'new'", captured_sql)
            assert_in("reclaim SQL targets 'processing' rows", "indexing_status = 'processing'", captured_sql)
            assert_in("reclaim SQL uses updated_at lease", "updated_at", captured_sql)
            assert_equal(
                "reclaim uses _STALE_PROCESSING_MINUTES constant",
                params["mins"],
                ingest_pipeline._STALE_PROCESSING_MINUTES,
            )

    asyncio.run(run_coroutine())


def test_no_stale_rows_pipeline_succeeds():
    """When the reclaim query returns no rows, run_pipeline completes cleanly."""
    async def run_coroutine():
        with (
            patch.object(ingest_pipeline, "query", new_callable=AsyncMock) as mock_query,
            patch.object(ingest_pipeline, "discover_documents", new_callable=AsyncMock) as mock_discover_documents,
        ):
            mock_query.return_value = []   # nothing to reclaim
            mock_discover_documents.return_value = []
            result = await ingest_pipeline.run_pipeline()
            assert_equal("pipeline succeeds with no stale rows", result["status"], "ok")

    asyncio.run(run_coroutine())


def test_discover_called_after_reclaim():
    """discover_documents is always called after reclaim so unlocked docs can be re-indexed."""
    async def run_coroutine():
        with (
            patch.object(ingest_pipeline, "query", new_callable=AsyncMock) as mock_query,
            patch.object(ingest_pipeline, "discover_documents", new_callable=AsyncMock) as mock_discover_documents,
        ):
            mock_query.return_value = [{"source_blob": "stale.pdf"}]
            mock_discover_documents.return_value = []
            await ingest_pipeline.run_pipeline()
            assert_true("discover_documents called after reclaim", mock_discover_documents.called)

    asyncio.run(run_coroutine())


# ===========================================================================
# 2. process_document status transitions
# ===========================================================================

print("\n# process_document status transitions")


def test_already_processing_is_skipped():
    """Atomic claim returns no row -> document already processing -> result=skipped."""
    result, _ = _run_process(claim_returns=[])
    assert_equal("already-processing -> skipped", result["status"], "skipped")


def test_all_chunks_embedded_sets_ready():
    """embedded_count == chunk_count -> indexing_status=ready, result=ok."""
    result, mock_update_index_status = _run_process(save_chunks_returns=(3, 3))
    assert_equal("all embedded -> result ok", result["status"], "ok")
    assert_equal("all embedded -> indexing_status=ready", mock_update_index_status.call_args.args[1], "ready")


def test_partial_embeddings_sets_partial():
    """Some but not all chunks embedded -> indexing_status=partial, result=partial."""
    result, mock_update_index_status = _run_process(save_chunks_returns=(3, 1))
    assert_equal("partial embed -> result partial", result["status"], "partial")
    assert_equal("partial embed -> indexing_status=partial", mock_update_index_status.call_args.args[1], "partial")


def test_zero_embeddings_no_fallback_sets_partial():
    """No chunk embeddings, doc-level fallback also fails -> indexing_status=partial."""
    result, mock_update_index_status = _run_process(
        save_chunks_returns=(3, 0),
        generate_emb_returns=None,  # fallback fails too
    )
    assert_equal("no embed -> result partial", result["status"], "partial")
    assert_equal("no embed -> indexing_status=partial", mock_update_index_status.call_args.args[1], "partial")


def test_zero_embeddings_with_doc_fallback_sets_partial():
    """No chunk embeddings but doc-level fallback succeeds -> still partial (not ready)."""
    result, mock_update_index_status = _run_process(
        save_chunks_returns=(3, 0),
        generate_emb_returns=[0.1] * 10,  # doc-level fallback succeeds
    )
    # has_any_embedding=True but all_chunks_embedded=False -> partial
    assert_equal("doc-fallback embed -> result partial", result["status"], "partial")
    assert_equal("doc-fallback embed -> indexing_status=partial", mock_update_index_status.call_args.args[1], "partial")


def test_extraction_error_sets_failed():
    """Exception during extract_blocks -> indexing_status=failed, result=error."""
    result, mock_update_index_status = _run_process(extract_blocks_raises=RuntimeError("PDF corrupt"))
    assert_equal("extract error -> result error", result["status"], "error")
    assert_equal("extract error -> indexing_status=failed", mock_update_index_status.call_args.args[1], "failed")


def test_single_chunk_fully_embedded_is_ready():
    """Edge case: 1 chunk, 1 embedding -> ready (not partial)."""
    result, mock_update_index_status = _run_process(
        chunks=_fake_chunks(1),
        save_chunks_returns=(1, 1),
    )
    assert_equal("1 chunk fully embedded -> ok", result["status"], "ok")
    assert_equal("1 chunk fully embedded -> ready", mock_update_index_status.call_args.args[1], "ready")


def test_save_chunks_refreshes_processing_lease_between_batches():
    """save_chunks refreshes the processing lease while batched embeddings run."""
    async def run_coroutine():
        fake_cursor = _FakeCursor([101, 102, 103])
        fake_conn = _FakeConnection(fake_cursor)

        with (
            patch.object(ingest_pipeline, "get_connection", return_value=fake_conn),
            patch.object(ingest_pipeline, "refresh_processing_lease", new_callable=AsyncMock) as mock_refresh_lease,
            patch("embedding_client.get_embeddings", new=AsyncMock(side_effect=[
                [[0.1] * 3, [0.2] * 3],
                [[0.3] * 3],
            ])),
            patch.object(ingest_pipeline, "_EMBEDDING_BATCH_SIZE", 2),
        ):
            total, embedded = await ingest_pipeline.save_chunks(
                1,
                _fake_chunks(3),
                lease_blob_name="doc.pdf",
            )
            assert_equal("save_chunks inserts all chunks", total, 3)
            assert_equal("save_chunks counts embedded chunks", embedded, 3)
            assert_true(
                "processing lease refreshed during batched embeddings",
                mock_refresh_lease.await_count >= 2,
            )

    asyncio.run(run_coroutine())


# ===========================================================================
# 3. Search indexing_status filtering
# ===========================================================================

print("\n# Search indexing_status filtering")

_STATUS_FILTER = "indexing_status IN ('ready', 'partial')"


def test_full_text_search_filters_status():
    """search_full_text SQL must exclude new/processing/failed documents."""
    async def run_coroutine():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            await search_service.search_full_text("regelverk")
            captured_sql = mock_query.call_args.args[0]
            assert_in("full_text filters by status", _STATUS_FILTER, captured_sql)

    asyncio.run(run_coroutine())


def test_fuzzy_search_filters_status():
    """search_fuzzy SQL must exclude new/processing/failed documents."""
    async def run_coroutine():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            await search_service.search_fuzzy("regelverk")
            captured_sql = mock_query.call_args.args[0]
            assert_in("fuzzy search filters by status", _STATUS_FILTER, captured_sql)

    asyncio.run(run_coroutine())


def test_semantic_chunk_search_filters_status():
    """_search_semantic_chunks SQL must exclude non-searchable documents."""
    async def run_coroutine():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            await search_service._search_semantic_chunks([0.1] * 10, "regelverk", 10)
            captured_sql = mock_query.call_args.args[0]
            assert_in("semantic chunk search filters by status", _STATUS_FILTER, captured_sql)

    asyncio.run(run_coroutine())


def test_semantic_document_fallback_filters_status():
    """_search_semantic_documents SQL must exclude non-searchable documents."""
    async def run_coroutine():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            await search_service._search_semantic_documents([0.1] * 10, "regelverk", 10)
            captured_sql = mock_query.call_args.args[0]
            assert_in("semantic doc fallback filters by status", _STATUS_FILTER, captured_sql)

    asyncio.run(run_coroutine())


def test_full_text_empty_query_skips_db():
    """search_full_text with blank query returns [] without hitting the DB."""
    async def run_coroutine():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            result = await search_service.search_full_text("   ")
            assert_equal("empty query returns []", result, [])
            assert_equal("empty query skips DB", mock_query.called, False)

    asyncio.run(run_coroutine())


# ===========================================================================
# Runner
# ===========================================================================

_TESTS = [
    # stale reclaim
    test_stale_reclaim_sql_resets_to_new,
    test_no_stale_rows_pipeline_succeeds,
    test_discover_called_after_reclaim,
    # status transitions
    test_already_processing_is_skipped,
    test_all_chunks_embedded_sets_ready,
    test_partial_embeddings_sets_partial,
    test_zero_embeddings_no_fallback_sets_partial,
    test_zero_embeddings_with_doc_fallback_sets_partial,
    test_extraction_error_sets_failed,
    test_single_chunk_fully_embedded_is_ready,
    test_save_chunks_refreshes_processing_lease_between_batches,
    # search filtering
    test_full_text_search_filters_status,
    test_fuzzy_search_filters_status,
    test_semantic_chunk_search_filters_status,
    test_semantic_document_fallback_filters_status,
    test_full_text_empty_query_skips_db,
]

if __name__ == "__main__":
    for test_function in _TESTS:
        _run_test(test_function)

    total = _passed + _failed
    print(f"\n{_passed}/{total} tests passed.")
    sys.exit(0 if _failed == 0 else 1)
