"""
Configurable embedding client — Azure OpenAI (production) or GitHub Models (fallback).

Used by ingest_pipeline.py (document ingestion) and search_service.py (query embedding).

Provider selection (checked in order):
  1. AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY → Azure OpenAI  (recommended)
  2. GITHUB_MODELS_TOKEN                          → GitHub Models  (free tier, rate-limited)
  3. Neither configured                           → raises ValueError

Both providers use the ``openai`` Python SDK, which provides:
  - Native async (no thread-executor workaround)
  - Automatic exponential-backoff retries on 429 / 5xx errors
  - Retry-After header respect
  - Configurable timeout and max-retries

Environment variables:
  # Azure OpenAI (primary — recommended for production)
  AZURE_OPENAI_ENDPOINT              = https://<resource>.openai.azure.com
  AZURE_OPENAI_API_KEY               = <key>
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT  = text-embedding-3-large   (default)
  AZURE_OPENAI_API_VERSION           = 2024-10-21               (default)
  AZURE_OPENAI_EMBEDDING_DIMENSIONS  = 1536                     (default — must match DB vector column)

  # GitHub Models (fallback — free tier, limited)
  GITHUB_MODELS_TOKEN                = ghp_...
  GITHUB_MODELS_EMBEDDING_MODEL      = openai/text-embedding-3-small  (default)
"""

import logging
import os
from typing import Optional

from openai import AsyncAzureOpenAI, AsyncOpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_AZURE_API_VERSION = "2024-10-21"
_DEFAULT_AZURE_DEPLOYMENT = "text-embedding-3-large"
_DEFAULT_GITHUB_MODEL = "openai/text-embedding-3-small"

# Output dimensions — MUST match the DB schema's vector(N) column size.
# text-embedding-3-large natively outputs 3072 dims but supports Matryoshka
# truncation; 1536 from large outperforms 1536 from small.
_DEFAULT_EMBEDDING_DIMENSIONS = 1536

# Azure OpenAI — higher limits, more retries
_AZURE_MAX_RETRIES = 5
_AZURE_TIMEOUT = 60.0

# GitHub Models — lower limits, fewer retries
_GITHUB_MAX_RETRIES = 3
_GITHUB_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# Module-level singleton (lazy init on first call)
# ---------------------------------------------------------------------------

_client: Optional[AsyncAzureOpenAI | AsyncOpenAI] = None
_model: str = ""
_provider: str = ""
_dimensions: int = _DEFAULT_EMBEDDING_DIMENSIONS


def _init_client() -> None:
    """
    Detect provider from environment and initialise the embedding client.

    Raises ValueError when no provider is configured — callers (e.g.
    ingest_pipeline.save_chunks) catch this to gracefully degrade.
    """
    global _client, _model, _provider, _dimensions

    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    azure_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    azure_deployment = os.getenv(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", _DEFAULT_AZURE_DEPLOYMENT
    )
    azure_api_version = os.getenv(
        "AZURE_OPENAI_API_VERSION", _DEFAULT_AZURE_API_VERSION
    )
    raw_dims = os.getenv("AZURE_OPENAI_EMBEDDING_DIMENSIONS", "").strip()
    if raw_dims:
        try:
            parsed_dims = int(raw_dims)
        except ValueError:
            raise ValueError(
                f"AZURE_OPENAI_EMBEDDING_DIMENSIONS must be a positive integer, got {raw_dims!r}"
            )
        if parsed_dims <= 0:
            raise ValueError(
                f"AZURE_OPENAI_EMBEDDING_DIMENSIONS must be a positive integer, got {parsed_dims}"
            )
        _dimensions = parsed_dims
    else:
        _dimensions = _DEFAULT_EMBEDDING_DIMENSIONS

    github_token = os.getenv("GITHUB_MODELS_TOKEN", "").strip()

    if azure_endpoint and azure_key:
        _client = AsyncAzureOpenAI(
            api_key=azure_key,
            api_version=azure_api_version,
            azure_endpoint=azure_endpoint,
            max_retries=_AZURE_MAX_RETRIES,
            timeout=_AZURE_TIMEOUT,
        )
        _model = azure_deployment
        _provider = "azure_openai"
        logger.info(
            "Embedding provider: Azure OpenAI (endpoint=%s, deployment=%s, "
            "api_version=%s, max_retries=%d)",
            azure_endpoint, azure_deployment, azure_api_version,
            _AZURE_MAX_RETRIES,
        )
    elif github_token:
        _client = AsyncOpenAI(
            base_url="https://models.github.ai/inference",
            api_key=github_token,
            max_retries=_GITHUB_MAX_RETRIES,
            timeout=_GITHUB_TIMEOUT,
        )
        _model = os.getenv("GITHUB_MODELS_EMBEDDING_MODEL", _DEFAULT_GITHUB_MODEL)
        _provider = "github_models"
        logger.info(
            "Embedding provider: GitHub Models (model=%s, max_retries=%d) "
            "— free tier with strict rate limits; consider Azure OpenAI for production",
            _model, _GITHUB_MAX_RETRIES,
        )
    else:
        raise ValueError(
            "No embedding provider configured. "
            "Set AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY for Azure OpenAI, "
            "or GITHUB_MODELS_TOKEN for GitHub Models."
        )


def _get_client() -> tuple[AsyncAzureOpenAI | AsyncOpenAI, str]:
    """Return the initialised client and model name. Initialises on first call."""
    if _client is None:
        _init_client()
    if _client is None:  # _init_client raises ValueError if unconfigured; this guards against unexpected states
        raise RuntimeError("Embedding client failed to initialise.")
    return _client, _model


def get_provider_name() -> str:
    """Return the active provider name (for logging / diagnostics)."""
    if _client is None:
        _init_client()
    return _provider


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts.

    Returns one embedding vector per input text, in the same order.
    Raises ValueError if no provider is configured.
    Raises openai.APIError (or subclasses) on transient API failures
    after all retries are exhausted.
    """
    if not texts:
        return []

    client, model = _get_client()

    # GitHub Models does not support the `dimensions` parameter — only pass it for Azure OpenAI
    extra_kwargs: dict = {}
    if _provider == "azure_openai":
        extra_kwargs["dimensions"] = _dimensions

    response = await client.embeddings.create(
        input=texts,
        model=model,
        **extra_kwargs,
    )

    items = sorted(response.data, key=lambda x: x.index)
    embeddings = [item.embedding for item in items]

    logger.info(
        "Embeddings [%s]: %d texts → %d vectors (%d dims)",
        _provider,
        len(texts),
        len(embeddings),
        len(embeddings[0]) if embeddings else 0,
    )
    return embeddings


async def get_single_embedding(text: str) -> list[float] | None:
    """Embed a single text string, return one vector (or None on failure)."""
    results = await get_embeddings([text])
    if not results:
        return None
    return results[0]
