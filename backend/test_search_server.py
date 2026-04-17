#!/usr/bin/env python3
"""
Focused regression tests for the MCP search server surface.

These tests stub FastMCP and backend services before importing
mcp_servers.search_server so they run without FastMCP, a database, or network.

Usage:
  python backend/test_search_server.py
"""

import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock, patch


def _stub(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


class _FakeFastMCP:
    def __init__(self, name: str):
        self.name = name

    def tool(self, annotations=None):
        def decorator(fn):
            return fn
        return decorator

    def http_app(self, path="/mcp"):
        return {"path": path, "server": self.name}


async def _noop_async(*args, **kwargs):
    return []


_stub("fastmcp", FastMCP=_FakeFastMCP)
_stub(
    "search_service",
    search_full_text=_noop_async,
    search_fuzzy=_noop_async,
    search_semantic=_noop_async,
    hybrid_search=_noop_async,
    get_chunk_by_id=_noop_async,
)
_stub(
    "ingest_pipeline",
    process_document=_noop_async,
    run_pipeline=_noop_async,
    discover_documents=_noop_async,
    update_index_status=_noop_async,
)
_stub("db", query=_noop_async)

import mcp_servers.search_server as search_server  # noqa: E402


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


def assert_true(label: str, value):
    return assert_equal(label, bool(value), True)


def test_get_search_result_chunk_success():
    async def go():
        with patch.object(search_server, "get_chunk_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"chunk_id": 7, "content": "Full chunk text"}
            payload = json.loads(await search_server.get_search_result_chunk(7))
            assert_equal("chunk payload wrapped in response", payload["chunk"]["chunk_id"], 7)
            assert_equal("chunk payload includes content", payload["chunk"]["content"], "Full chunk text")

    asyncio.run(go())


def test_get_search_result_chunk_invalid_id():
    async def go():
        payload = json.loads(await search_server.get_search_result_chunk(0))
        assert_true("invalid chunk id returns error", "error" in payload)

    asyncio.run(go())


def test_get_search_result_chunk_missing():
    async def go():
        with patch.object(search_server, "get_chunk_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            payload = json.loads(await search_server.get_search_result_chunk(99))
            assert_equal("missing chunk returns error", payload["error"], "Fant ikke chunk 99.")

    asyncio.run(go())


if __name__ == "__main__":
    test_get_search_result_chunk_success()
    test_get_search_result_chunk_invalid_id()
    test_get_search_result_chunk_missing()

    total = _passed + _failed
    print(f"\n{_passed}/{total} tests passed.")
    sys.exit(0 if _failed == 0 else 1)
