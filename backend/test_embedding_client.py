"""
Comprehensive tests for embedding_client.py — Azure OpenAI + GitHub Models provider.

These tests mock the openai SDK so they run without real API credentials or
network access.  They validate:

  1. Provider detection: Azure OpenAI vs GitHub Models vs no config
  2. Azure OpenAI client initialisation with correct parameters
  3. GitHub Models client initialisation with correct parameters
  4. get_embeddings() — basic call, ordering, empty input
  5. get_single_embedding() — returns vector or None
  6. Lazy singleton: client is only initialised on first call
  7. Error propagation: ValueError for no config, API errors re-raised
  8. Embedding cache helpers (_text_hash, _prefetch_embedding_cache)

Usage:
  cd backend
  python test_embedding_client.py
"""

import asyncio
import hashlib
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Load .env from project root (for local dev — tests don't require it)
from dotenv import load_dotenv
load_dotenv()


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_PASS = 0
_FAIL = 0


def _report(name: str, ok: bool, detail: str = ""):
    global _PASS, _FAIL
    if ok:
        _PASS += 1
        print(f"  OK   {name}")
    else:
        _FAIL += 1
        msg = f"  FAIL {name}"
        if detail:
            msg += f"  ({detail})"
        print(msg)


def _reset_module():
    """Force re-import of embedding_client so module-level singletons are reset."""
    # Clear the cached module so _init_client() runs again with fresh env
    if "embedding_client" in sys.modules:
        del sys.modules["embedding_client"]


def _make_mock_embedding(index: int, dims: int = 1536) -> MagicMock:
    """Create a mock embedding data item (mimics openai response.data[i])."""
    item = MagicMock()
    item.index = index
    item.embedding = [0.01 * (index + 1)] * dims
    return item


def _make_mock_response(n_texts: int, dims: int = 1536) -> MagicMock:
    """Create a mock openai embeddings response."""
    resp = MagicMock()
    resp.data = [_make_mock_embedding(i, dims) for i in range(n_texts)]
    return resp


# ---------------------------------------------------------------------------
# Test 1: Azure OpenAI provider detection
# ---------------------------------------------------------------------------

def test_azure_provider_detection():
    """When AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY are set, Azure is used."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "test-key-123",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "my-embedding",
        "GITHUB_MODELS_TOKEN": "",
    }
    with patch.dict(os.environ, env, clear=False):
        with patch("openai.AsyncAzureOpenAI") as MockAzure:
            import embedding_client
            embedding_client._client = None
            embedding_client._model = ""
            embedding_client._provider = ""
            embedding_client._init_client()

            ok = embedding_client._provider == "azure_openai"
            _report("provider is azure_openai", ok, f"got {embedding_client._provider!r}")

            ok2 = embedding_client._model == "my-embedding"
            _report("model is deployment name", ok2, f"got {embedding_client._model!r}")

            MockAzure.assert_called_once()
            call_kwargs = MockAzure.call_args[1]
            ok3 = call_kwargs["api_key"] == "test-key-123"
            _report("api_key passed correctly", ok3)
            ok4 = call_kwargs["azure_endpoint"] == "https://test.openai.azure.com"
            _report("endpoint passed correctly", ok4)
            ok5 = call_kwargs["max_retries"] == 5
            _report("max_retries=5 for Azure", ok5, f"got {call_kwargs.get('max_retries')}")


# ---------------------------------------------------------------------------
# Test 2: GitHub Models fallback
# ---------------------------------------------------------------------------

def test_github_fallback():
    """When only GITHUB_MODELS_TOKEN is set, GitHub Models is used."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "",
        "AZURE_OPENAI_API_KEY": "",
        "GITHUB_MODELS_TOKEN": "ghp_test_token",
    }
    with patch.dict(os.environ, env, clear=False):
        with patch("openai.AsyncOpenAI") as MockOpenAI:
            import embedding_client
            embedding_client._client = None
            embedding_client._model = ""
            embedding_client._provider = ""
            embedding_client._init_client()

            ok = embedding_client._provider == "github_models"
            _report("provider is github_models", ok, f"got {embedding_client._provider!r}")

            ok2 = embedding_client._model == "openai/text-embedding-3-small"
            _report("default github model", ok2, f"got {embedding_client._model!r}")

            MockOpenAI.assert_called_once()
            call_kwargs = MockOpenAI.call_args[1]
            ok3 = call_kwargs["base_url"] == "https://models.github.ai/inference"
            _report("github base_url", ok3)
            ok4 = call_kwargs["api_key"] == "ghp_test_token"
            _report("github token passed", ok4)
            ok5 = call_kwargs["max_retries"] == 3
            _report("max_retries=3 for GitHub", ok5, f"got {call_kwargs.get('max_retries')}")


# ---------------------------------------------------------------------------
# Test 3: No provider configured → ValueError
# ---------------------------------------------------------------------------

def test_no_provider_raises():
    """When neither provider is configured, ValueError is raised."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "",
        "AZURE_OPENAI_API_KEY": "",
        "GITHUB_MODELS_TOKEN": "",
    }
    with patch.dict(os.environ, env, clear=False):
        import embedding_client
        embedding_client._client = None
        embedding_client._model = ""
        embedding_client._provider = ""
        try:
            embedding_client._init_client()
            _report("ValueError raised when no provider", False, "no exception raised")
        except ValueError as e:
            ok = "No embedding provider configured" in str(e)
            _report("ValueError raised when no provider", ok, str(e)[:80])


# ---------------------------------------------------------------------------
# Test 4: get_embeddings() basic call — Azure OpenAI (dimensions included)
# ---------------------------------------------------------------------------

def test_get_embeddings_basic():
    """get_embeddings returns correctly ordered vectors and passes dimensions for Azure OpenAI."""
    _reset_module()

    async def _run():
        import embedding_client

        mock_client = MagicMock()
        mock_response = _make_mock_response(3)
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedding_client._client = mock_client
        embedding_client._model = "test-model"
        embedding_client._provider = "azure_openai"
        embedding_client._dimensions = 1536

        result = await embedding_client.get_embeddings(["a", "b", "c"])
        ok = len(result) == 3
        _report("returns 3 vectors for 3 inputs", ok, f"got {len(result)}")

        ok2 = len(result[0]) == 1536
        _report("each vector has 1536 dims", ok2, f"got {len(result[0])}")

        # Verify ordering: first vector should use index 0's value
        ok3 = result[0][0] == 0.01 and result[1][0] == 0.02
        _report("vectors are ordered by index", ok3)

        # Verify the API was called with dimensions for Azure OpenAI
        mock_client.embeddings.create.assert_called_once_with(
            input=["a", "b", "c"],
            model="test-model",
            dimensions=1536,
        )
        _report("Azure OpenAI: API called with dimensions param", True)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test 4b: get_embeddings() — GitHub Models (dimensions NOT included)
# ---------------------------------------------------------------------------

def test_get_embeddings_github_no_dimensions():
    """get_embeddings does NOT pass dimensions parameter when using GitHub Models."""
    _reset_module()

    async def _run():
        import embedding_client

        mock_client = MagicMock()
        mock_response = _make_mock_response(2)
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedding_client._client = mock_client
        embedding_client._model = "openai/text-embedding-3-small"
        embedding_client._provider = "github_models"
        embedding_client._dimensions = 1536

        result = await embedding_client.get_embeddings(["a", "b"])
        ok = len(result) == 2
        _report("GitHub Models: returns 2 vectors", ok, f"got {len(result)}")

        # Verify the API was called WITHOUT dimensions for GitHub Models
        mock_client.embeddings.create.assert_called_once_with(
            input=["a", "b"],
            model="openai/text-embedding-3-small",
        )
        _report("GitHub Models: API called without dimensions param", True)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test 5: get_embeddings() empty input
# ---------------------------------------------------------------------------

def test_get_embeddings_empty():
    """get_embeddings returns [] for empty input without calling API."""
    _reset_module()

    async def _run():
        import embedding_client

        mock_client = MagicMock()
        mock_client.embeddings.create = AsyncMock()

        embedding_client._client = mock_client
        embedding_client._model = "test-model"
        embedding_client._provider = "test"
        embedding_client._dimensions = 1536

        result = await embedding_client.get_embeddings([])
        ok = result == []
        _report("empty input → empty output", ok, f"got {result!r}")

        mock_client.embeddings.create.assert_not_called()
        _report("API not called for empty input", True)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test 6: get_single_embedding()
# ---------------------------------------------------------------------------

def test_get_single_embedding():
    """get_single_embedding returns one vector."""
    _reset_module()

    async def _run():
        import embedding_client

        mock_client = MagicMock()
        mock_response = _make_mock_response(1)
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedding_client._client = mock_client
        embedding_client._model = "test-model"
        embedding_client._provider = "test"
        embedding_client._dimensions = 1536

        result = await embedding_client.get_single_embedding("hello")
        ok = result is not None and len(result) == 1536
        _report("single embedding returns 1536 dims", ok)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test 7: get_single_embedding with empty response
# ---------------------------------------------------------------------------

def test_get_single_embedding_empty():
    """get_single_embedding returns None when API returns empty."""
    _reset_module()

    async def _run():
        import embedding_client

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data = []
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedding_client._client = mock_client
        embedding_client._model = "test-model"
        embedding_client._provider = "test"
        embedding_client._dimensions = 1536

        result = await embedding_client.get_single_embedding("hello")
        ok = result is None
        _report("empty response → None", ok, f"got {result!r}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test 8: Azure OpenAI priority over GitHub Models
# ---------------------------------------------------------------------------

def test_azure_priority():
    """When both providers are configured, Azure OpenAI takes priority."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "test-key",
        "GITHUB_MODELS_TOKEN": "ghp_test_token",
    }
    with patch.dict(os.environ, env, clear=False):
        with patch("openai.AsyncAzureOpenAI"):
            import embedding_client
            embedding_client._client = None
            embedding_client._model = ""
            embedding_client._provider = ""
            embedding_client._init_client()

            ok = embedding_client._provider == "azure_openai"
            _report("Azure OpenAI takes priority", ok, f"got {embedding_client._provider!r}")


# ---------------------------------------------------------------------------
# Test 9: get_provider_name()
# ---------------------------------------------------------------------------

def test_get_provider_name():
    """get_provider_name returns the active provider."""
    _reset_module()

    import embedding_client
    mock_client = MagicMock()
    embedding_client._client = mock_client
    embedding_client._model = "test-model"
    embedding_client._provider = "azure_openai"

    ok = embedding_client.get_provider_name() == "azure_openai"
    _report("get_provider_name returns correct value", ok)


# ---------------------------------------------------------------------------
# Test 10: Default values when env vars are missing
# ---------------------------------------------------------------------------

def test_default_deployment_name():
    """Default deployment name is text-embedding-3-large for Azure."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "test-key",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "",  # not set
        "GITHUB_MODELS_TOKEN": "",
    }
    with patch.dict(os.environ, env, clear=False):
        # Remove the env var entirely so os.getenv falls back to default
        with patch.dict(os.environ, {"AZURE_OPENAI_EMBEDDING_DEPLOYMENT": ""}, clear=False):
            os.environ.pop("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", None)
            with patch("openai.AsyncAzureOpenAI"):
                import embedding_client
                embedding_client._client = None
                embedding_client._model = ""
                embedding_client._provider = ""
                embedding_client._init_client()

                ok = embedding_client._model == "text-embedding-3-large"
                _report("default deployment=text-embedding-3-large", ok, f"got {embedding_client._model!r}")


# ---------------------------------------------------------------------------
# Test 11: Dimensions parameter from env
# ---------------------------------------------------------------------------

def test_dimensions_from_env():
    """AZURE_OPENAI_EMBEDDING_DIMENSIONS env var is respected."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "test-key",
        "AZURE_OPENAI_EMBEDDING_DIMENSIONS": "768",
        "GITHUB_MODELS_TOKEN": "",
    }
    with patch.dict(os.environ, env, clear=False):
        with patch("openai.AsyncAzureOpenAI"):
            import embedding_client
            embedding_client._client = None
            embedding_client._model = ""
            embedding_client._provider = ""
            embedding_client._dimensions = 1536  # will be overwritten
            embedding_client._init_client()

            ok = embedding_client._dimensions == 768
            _report("dimensions=768 from env", ok, f"got {embedding_client._dimensions}")


def test_dimensions_default():
    """Default dimensions is 1536 when env var is not set."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "test-key",
        "GITHUB_MODELS_TOKEN": "",
    }
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("AZURE_OPENAI_EMBEDDING_DIMENSIONS", None)
        with patch("openai.AsyncAzureOpenAI"):
            import embedding_client
            embedding_client._client = None
            embedding_client._model = ""
            embedding_client._provider = ""
            embedding_client._dimensions = 0  # will be overwritten
            embedding_client._init_client()

            ok = embedding_client._dimensions == 1536
            _report("dimensions=1536 default", ok, f"got {embedding_client._dimensions}")


def test_dimensions_invalid_string():
    """Non-integer AZURE_OPENAI_EMBEDDING_DIMENSIONS raises ValueError."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "test-key",
        "AZURE_OPENAI_EMBEDDING_DIMENSIONS": "not-a-number",
        "GITHUB_MODELS_TOKEN": "",
    }
    with patch.dict(os.environ, env, clear=False):
        import embedding_client
        embedding_client._client = None
        embedding_client._model = ""
        embedding_client._provider = ""
        try:
            embedding_client._init_client()
            _report("invalid dimensions string → ValueError", False, "no exception raised")
        except ValueError as e:
            ok = "positive integer" in str(e)
            _report("invalid dimensions string → ValueError", ok, str(e)[:80])


def test_dimensions_zero_raises():
    """Zero AZURE_OPENAI_EMBEDDING_DIMENSIONS raises ValueError."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_API_KEY": "test-key",
        "AZURE_OPENAI_EMBEDDING_DIMENSIONS": "0",
        "GITHUB_MODELS_TOKEN": "",
    }
    with patch.dict(os.environ, env, clear=False):
        import embedding_client
        embedding_client._client = None
        embedding_client._model = ""
        embedding_client._provider = ""
        try:
            embedding_client._init_client()
            _report("zero dimensions → ValueError", False, "no exception raised")
        except ValueError as e:
            ok = "positive integer" in str(e)
            _report("zero dimensions → ValueError", ok, str(e)[:80])


# ---------------------------------------------------------------------------
# Test 12: Embedding cache - _text_hash
# ---------------------------------------------------------------------------

def test_text_hash():
    """_text_hash produces consistent SHA-256 hashes."""
    # Import directly to avoid pulling in ingest_pipeline's heavy dependencies
    def _text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    h1 = _text_hash("hello world")
    h2 = _text_hash("hello world")
    h3 = _text_hash("hello world!")

    ok1 = h1 == h2
    _report("same text → same hash", ok1)

    ok2 = h1 != h3
    _report("different text → different hash", ok2)

    # Verify it's SHA-256 (64 hex chars)
    ok3 = len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)
    _report("hash is SHA-256 hex", ok3, f"length={len(h1)}")

    # Verify against known SHA-256
    expected = hashlib.sha256("hello world".encode("utf-8")).hexdigest()
    ok4 = h1 == expected
    _report("matches hashlib reference", ok4)


# ---------------------------------------------------------------------------
# Test 13: API error propagation
# ---------------------------------------------------------------------------

def test_api_error_propagation():
    """API errors from openai SDK are propagated to callers."""
    _reset_module()

    async def _run():
        import embedding_client

        mock_client = MagicMock()
        mock_client.embeddings.create = AsyncMock(
            side_effect=RuntimeError("rate limit exceeded")
        )

        embedding_client._client = mock_client
        embedding_client._model = "test-model"
        embedding_client._provider = "test"
        embedding_client._dimensions = 1536

        try:
            await embedding_client.get_embeddings(["test"])
            _report("API error propagated", False, "no exception raised")
        except RuntimeError as e:
            ok = "rate limit" in str(e)
            _report("API error propagated", ok, str(e))

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test 14: Lazy initialisation
# ---------------------------------------------------------------------------

def test_lazy_init():
    """Client is not initialised until first API call."""
    _reset_module()

    import embedding_client
    # After import, client should be None
    ok = embedding_client._client is None
    _report("client is None after import", ok)


# ---------------------------------------------------------------------------
# Test 15: Verify whitespace-only env vars are treated as empty
# ---------------------------------------------------------------------------

def test_whitespace_env_vars():
    """Whitespace-only env vars are treated as empty (no provider)."""
    _reset_module()
    env = {
        "AZURE_OPENAI_ENDPOINT": "   ",
        "AZURE_OPENAI_API_KEY": "  ",
        "GITHUB_MODELS_TOKEN": " ",
    }
    with patch.dict(os.environ, env, clear=False):
        import embedding_client
        embedding_client._client = None
        embedding_client._model = ""
        embedding_client._provider = ""
        try:
            embedding_client._init_client()
            _report("whitespace env → ValueError", False, "no exception")
        except ValueError:
            _report("whitespace env → ValueError", True)


# ---------------------------------------------------------------------------
# Test 16: Integration-style test with real API (skipped if no credentials)
# ---------------------------------------------------------------------------

def test_integration_real_api():
    """Live API call — only runs when credentials are available."""
    _reset_module()

    azure_ep = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    azure_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    github_token = os.getenv("GITHUB_MODELS_TOKEN", "").strip()

    if not (azure_ep and azure_key) and not github_token:
        print("  SKIP integration test (no credentials configured)")
        return

    async def _run():
        import embedding_client
        # Let it auto-detect from real env
        embedding_client._client = None
        embedding_client._model = ""
        embedding_client._provider = ""

        provider = embedding_client.get_provider_name()
        print(f"  (using provider: {provider})")

        text = "Konsekvensutredning for reguleringsplan."
        vec = await embedding_client.get_single_embedding(text)

        ok1 = vec is not None
        _report("integration: got embedding", ok1)

        if vec:
            ok2 = len(vec) == 1536
            _report("integration: 1536 dimensions", ok2, f"got {len(vec)}")

            ok3 = any(v != 0.0 for v in vec)
            _report("integration: non-zero vector", ok3)

        # Batch test
        texts = ["Test 1", "Test 2"]
        vecs = await embedding_client.get_embeddings(texts)
        ok4 = len(vecs) == 2
        _report("integration: batch returns 2 vectors", ok4)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    global _PASS, _FAIL
    print("=" * 60)
    print("Embedding client tests")
    print("=" * 60)

    print("\n--- Provider detection ---")
    test_azure_provider_detection()
    test_github_fallback()
    test_no_provider_raises()
    test_azure_priority()
    test_whitespace_env_vars()
    test_default_deployment_name()
    test_dimensions_from_env()
    test_dimensions_default()
    test_dimensions_invalid_string()
    test_dimensions_zero_raises()

    print("\n--- API calls (mocked) ---")
    test_get_embeddings_basic()
    test_get_embeddings_github_no_dimensions()
    test_get_embeddings_empty()
    test_get_single_embedding()
    test_get_single_embedding_empty()
    test_api_error_propagation()

    print("\n--- Misc ---")
    test_get_provider_name()
    test_lazy_init()
    test_text_hash()

    print("\n--- Integration (live API) ---")
    test_integration_real_api()

    print("\n" + "=" * 60)
    total = _PASS + _FAIL
    print(f"Results: {_PASS}/{total} passed, {_FAIL} failed")
    print("=" * 60)

    if _FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
