#!/usr/bin/env python3
"""
Unit tests for ingest pipeline and search service status/filtering logic.

Covers:
  - stale-processing recovery in run_pipeline()
  - status transitions in process_document(): ready / partial / failed
  - save_chunks() cleanup when a re-index produces zero chunks
  - search query filtering (indexing_status IN ('ready', 'partial'))
  - semantic chunk search SQL shape (candidate-first vector search)

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
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


_stub(
    "db",
    query=AsyncMock(),
    execute=AsyncMock(),
    get_connection=MagicMock(),
)
_stub(
    "blob_storage",
    list_documents_with_metadata=MagicMock(return_value=[]),
    download_blob_bytes=MagicMock(return_value=b""),
)
_stub(
    "pdf_extractor",
    fetch_document=MagicMock(return_value=""),
    fetch_document_blocks=MagicMock(return_value=[]),
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


def _run_test(fn):
    try:
        fn()
    except Exception as exc:
        global _failed
        _failed += 1
        print(f"  FAIL  {fn.__name__}: raised {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Blob / chunk fixtures
# ---------------------------------------------------------------------------

def _blob(name="doc.pdf", last_modified="2024-01-01", file_hash="abc"):
    return {"name": name, "last_modified": last_modified, "file_hash": file_hash}


def _fake_chunks(n: int) -> list[dict]:
    return [
        {
            "local_id": i,
            "local_parent_id": None,
            "chunk_index": i,
            "text": f"chunk {i}",
            "char_count": 7,
            "metadata": {},
        }
        for i in range(n)
    ]


class _FakeCursor:
    def __init__(self):
        self.execute_calls: list[tuple[str, dict | None]] = []

    async def execute(self, sql: str, params=None):
        self.execute_calls.append((sql, params))

    async def fetchone(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor

    def transaction(self):
        return _FakeTransaction()

    def cursor(self):
        return self._cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


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
    extract_text_returns="",     # return value of extract_text() fallback
    generate_emb_returns=None,   # return value of generate_embeddings
):
    if claim_returns is None:
        claim_returns = [{"id": 1}]
    if chunks is None:
        chunks = _fake_chunks(3)

    result_holder = {}
    mock_update_index_status_holder = {}

    async def go():
        with (
            patch.object(ingest_pipeline, "query", new_callable=AsyncMock) as mock_query,
            patch.object(ingest_pipeline, "extract_blocks", new_callable=AsyncMock) as mock_extract_blocks,
            patch.object(ingest_pipeline, "extract_text", new_callable=AsyncMock) as mock_extract_text,
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
            mock_extract_text.return_value = extract_text_returns
            mock_save_indexed_document.return_value = 1
            mock_save_chunks.return_value = save_chunks_returns
            mock_generate_embeddings.return_value = generate_emb_returns

            result = await ingest_pipeline.process_document(_blob())
            result_holder["result"] = result
            mock_update_index_status_holder["mock"] = mock_update_index_status

    asyncio.run(go())
    return result_holder["result"], mock_update_index_status_holder["mock"]


# ===========================================================================
# 1. Stale-processing recovery
# ===========================================================================

print("\n# Stale-processing recovery")


def test_claim_document_for_processing_uses_atomic_upsert():
    """Step 2 should atomically claim eligible rows in a single upsert statement."""
    async def go():
        with patch.object(ingest_pipeline, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [{"id": 123}]
            claimed = await ingest_pipeline.claim_document_for_processing(
                "doc.pdf",
                "2024-01-01",
                "abc",
                retry_failed=False,
            )

            sql, params = mock_query.call_args.args
            assert_equal("claim helper returns claimed id", claimed, 123)
            assert_in("claim helper inserts new documents", "INSERT INTO documents", sql)
            assert_in("claim helper uses ON CONFLICT upsert", "ON CONFLICT (source_blob) DO UPDATE", sql)
            assert_in(
                "claim helper skips already-processing rows",
                "documents.indexing_status != 'processing'",
                sql,
            )
            assert_equal("claim helper forwards retry flag", params["retry"], False)

    asyncio.run(go())


def test_stale_reclaim_sql_resets_to_new():
    """The reclaim UPDATE must target processing rows and reset them to 'new'."""
    async def go():
        with (
            patch.object(ingest_pipeline, "query", new_callable=AsyncMock) as mock_query,
            patch.object(ingest_pipeline, "discover_documents", new_callable=AsyncMock) as mock_discover_documents,
        ):
            mock_query.return_value = [{"source_blob": "stale.pdf"}]
            mock_discover_documents.return_value = []
            await ingest_pipeline.run_pipeline()

            sql, params = mock_query.call_args.args
            assert_in("reclaim SQL resets to 'new'", "indexing_status = 'new'", sql)
            assert_in("reclaim SQL targets 'processing' rows", "indexing_status = 'processing'", sql)
            assert_in("reclaim SQL uses updated_at lease", "updated_at", sql)
            assert_equal(
                "reclaim uses _STALE_PROCESSING_MINUTES constant",
                params["mins"],
                ingest_pipeline._STALE_PROCESSING_MINUTES,
            )

    asyncio.run(go())


def test_no_stale_rows_pipeline_succeeds():
    """When the reclaim query returns no rows, run_pipeline completes cleanly."""
    async def go():
        with (
            patch.object(ingest_pipeline, "query", new_callable=AsyncMock) as mock_query,
            patch.object(ingest_pipeline, "discover_documents", new_callable=AsyncMock) as mock_discover_documents,
        ):
            mock_query.return_value = []   # nothing to reclaim
            mock_discover_documents.return_value = []
            result = await ingest_pipeline.run_pipeline()
            assert_equal("pipeline succeeds with no stale rows", result["status"], "ok")

    asyncio.run(go())


def test_discover_called_after_reclaim():
    """discover_documents is always called after reclaim so unlocked docs can be re-indexed."""
    async def go():
        with (
            patch.object(ingest_pipeline, "query", new_callable=AsyncMock) as mock_query,
            patch.object(ingest_pipeline, "discover_documents", new_callable=AsyncMock) as mock_discover_documents,
        ):
            mock_query.return_value = [{"source_blob": "stale.pdf"}]
            mock_discover_documents.return_value = []
            await ingest_pipeline.run_pipeline()
            assert_true("discover_documents called after reclaim", mock_discover_documents.called)

    asyncio.run(go())


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


def test_zero_chunks_with_doc_fallback_sets_ready():
    """No chunks plus a document-level fallback embedding -> ready, not partial."""
    result, mock_update_index_status = _run_process(
        chunks=[],
        blocks_text="",
        save_chunks_returns=(0, 0),
        extract_text_returns="plain text fallback content",
        generate_emb_returns=[0.1] * 10,
    )
    assert_equal("0 chunks + doc fallback -> result ok", result["status"], "ok")
    assert_equal("0 chunks + doc fallback -> indexing_status=ready", mock_update_index_status.call_args.args[1], "ready")


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


# ===========================================================================
# 3. save_chunks() cleanup on empty chunk sets
# ===========================================================================

print("\n# save_chunks cleanup")


def test_save_chunks_empty_still_deletes_existing_rows():
    """Re-indexing to zero chunks must still clear stale chunk rows for the document."""
    async def go():
        fake_cursor = _FakeCursor()
        fake_conn = _FakeConnection(fake_cursor)

        with patch.object(ingest_pipeline, "get_connection", return_value=fake_conn):
            result = await ingest_pipeline.save_chunks(123, [])

        assert_equal("empty save_chunks returns zero counts", result, (0, 0))
        assert_equal("empty save_chunks issues one DELETE", len(fake_cursor.execute_calls), 1)
        sql, params = fake_cursor.execute_calls[0]
        assert_in("empty save_chunks deletes old rows", "DELETE FROM chunks", sql)
        assert_equal("delete targets the current document", params["doc_id"], 123)

    asyncio.run(go())


def test_save_chunks_refreshes_processing_lease_when_requested():
    """Embedding batches should refresh the processing lease for long-running work."""
    async def go():
        fake_cursor = _FakeCursor()
        fake_conn = _FakeConnection(fake_cursor)

        with (
            patch.object(ingest_pipeline, "get_connection", return_value=fake_conn),
            patch.object(ingest_pipeline, "refresh_processing_lease", new_callable=AsyncMock) as mock_touch,
            patch.object(ingest_pipeline, "_insert_chunk", new_callable=AsyncMock) as mock_insert,
            patch("embedding_client.get_embeddings", new_callable=AsyncMock) as mock_embed,
        ):
            mock_insert.side_effect = [10, 11]
            mock_embed.return_value = [[0.1, 0.2], [0.3, 0.4]]

            result = await ingest_pipeline.save_chunks(
                123,
                _fake_chunks(2),
                lease_blob_name="doc.pdf",
            )

            assert_equal("save_chunks with lease returns counts", result, (2, 2))
            assert_true("save_chunks refreshes processing lease", mock_touch.await_count >= 1)

    asyncio.run(go())


# ===========================================================================
# 4. Search indexing_status filtering
# ===========================================================================

print("\n# Search indexing_status filtering")

_STATUS_FILTER = "indexing_status IN ('ready', 'partial')"


def test_full_text_search_filters_status():
    """search_full_text SQL must exclude new/processing/failed documents."""
    async def go():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            await search_service.search_full_text("regelverk")
            sql = mock_query.call_args.args[0]
            assert_in("full_text filters by status", _STATUS_FILTER, sql)

    asyncio.run(go())


def test_fuzzy_search_filters_status():
    """search_fuzzy SQL must exclude new/processing/failed documents."""
    async def go():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            await search_service.search_fuzzy("regelverk")
            sql = mock_query.call_args.args[0]
            assert_in("fuzzy search filters by status", _STATUS_FILTER, sql)

    asyncio.run(go())


def test_semantic_chunk_search_filters_status():
    """_search_semantic_chunks SQL must exclude non-searchable documents."""
    async def go():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            await search_service._search_semantic_chunks([0.1] * 10, "regelverk", 10)
            sql = mock_query.call_args.args[0]
            assert_in("semantic chunk search filters by status", _STATUS_FILTER, sql)

    asyncio.run(go())


def test_semantic_chunk_search_uses_hnsw_candidate_stage():
    """Chunk semantic search must use a candidate-limited inner ANN query so the HNSW index is used."""
    async def go():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            await search_service._search_semantic_chunks([0.1] * 10, "regelverk", 10)
            sql, params = mock_query.call_args.args
            # Inner ANN stage must order purely by vector distance (HNSW-friendly).
            assert_in(
                "semantic chunk search inner query orders by vector distance only",
                "ORDER BY embedding <=> %(emb)s::vector",
                sql,
            )
            # Candidate limit must be passed so the inner scan is bounded.
            assert_true(
                "semantic chunk search passes candidate_lim parameter",
                "candidate_lim" in params,
            )
            assert_true(
                "semantic chunk search candidate_lim is larger than final limit",
                params["candidate_lim"] > params["lim"],
            )
            assert_equal(
                "semantic chunk search uses configured ANN floor",
                params["candidate_lim"],
                max(
                    params["lim"] * search_service._ANN_CANDIDATE_FACTOR,
                    search_service._ANN_MIN_CANDIDATES,
                ),
            )
            # Outer dedup still uses DISTINCT ON per document.
            assert_in("semantic chunk search deduplicates by document", "SELECT DISTINCT ON (d.id)", sql)

    asyncio.run(go())


def test_semantic_document_fallback_filters_status():
    """_search_semantic_documents SQL must exclude non-searchable documents."""
    async def go():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            await search_service._search_semantic_documents([0.1] * 10, "regelverk", 10)
            sql = mock_query.call_args.args[0]
            assert_in("semantic doc fallback filters by status", _STATUS_FILTER, sql)

    asyncio.run(go())


def test_semantic_chunk_search_truncates_content():
    """Chunk semantic search should return snippet-sized content like other search backends."""
    async def go():
        long_content = "x" * (search_service._SNIPPET_LENGTH + 25)
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [{
                "id": 1,
                "title": "Doc",
                "content": long_content,
                "score": 0.9,
                "heading_path": "1 Sammendrag",
                "section_title": "Sammendrag",
                "topic_type": "summary",
                "alternative": None,
                "delomrade": None,
                "contains_table": False,
                "page_start": 1,
                "page_end": 1,
                "chunk_index": 0,
                "chunk_id": 10,
            }]
            results = await search_service._search_semantic_chunks([0.1] * 10, "regelverk", 10)
            assert_equal("semantic chunk search returns one row", len(results), 1)
            assert_true("semantic chunk content truncated", results[0]["content"].endswith("…"))
            assert_equal(
                "semantic chunk content truncates to snippet length",
                len(results[0]["content"]),
                search_service._SNIPPET_LENGTH + 1,
            )

    asyncio.run(go())


def test_get_chunk_by_id_returns_plain_dict():
    """get_chunk_by_id should normalize the DB row into a plain dict."""
    async def go():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = [{
                "chunk_id": 10,
                "document_id": 1,
                "document_title": "Doc",
                "content": "Full chunk text",
            }]
            chunk = await search_service.get_chunk_by_id(10)
            assert_equal("get_chunk_by_id returns chunk dict", chunk["chunk_id"], 10)
            assert_equal("get_chunk_by_id returns plain content", chunk["content"], "Full chunk text")

    asyncio.run(go())


def test_get_chunk_by_id_filters_status():
    """get_chunk_by_id must not return chunks for failed/processing documents."""
    async def go():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []
            result = await search_service.get_chunk_by_id(42)
            sql = mock_query.call_args.args[0]
            assert_in("get_chunk_by_id filters by status", _STATUS_FILTER, sql)
            assert_equal("get_chunk_by_id returns None for missing/filtered chunk", result, None)

    asyncio.run(go())


def test_full_text_empty_query_skips_db():
    """search_full_text with blank query returns [] without hitting the DB."""
    async def go():
        with patch.object(search_service, "query", new_callable=AsyncMock) as mock_query:
            result = await search_service.search_full_text("   ")
            assert_equal("empty query returns []", result, [])
            assert_equal("empty query skips DB", mock_query.called, False)

    asyncio.run(go())


# ===========================================================================
# Runner
# ===========================================================================

_TESTS = [
    # step 2 claim helper
    test_claim_document_for_processing_uses_atomic_upsert,
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
    test_zero_chunks_with_doc_fallback_sets_ready,
    test_extraction_error_sets_failed,
    test_single_chunk_fully_embedded_is_ready,
    # save_chunks cleanup
    test_save_chunks_empty_still_deletes_existing_rows,
    test_save_chunks_refreshes_processing_lease_when_requested,
    # search filtering
    test_full_text_search_filters_status,
    test_fuzzy_search_filters_status,
    test_semantic_chunk_search_filters_status,
    test_semantic_chunk_search_uses_hnsw_candidate_stage,
    test_semantic_document_fallback_filters_status,
    test_semantic_chunk_search_truncates_content,
    test_get_chunk_by_id_returns_plain_dict,
    test_get_chunk_by_id_filters_status,
    test_full_text_empty_query_skips_db,
]

if __name__ == "__main__":
    for test_fn in _TESTS:
        _run_test(test_fn)

    total = _passed + _failed
    print(f"\n{_passed}/{total} tests passed.")
    sys.exit(0 if _failed == 0 else 1)
