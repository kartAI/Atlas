"""
Thin client for the GitHub Models embeddings API.

Used by ingest_pipeline.py (document ingestion) and search_service.py (query embedding).
Uses only stdlib (urllib) — no extra dependencies needed.
"""

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

GITHUB_MODELS_URL = "https://models.github.ai/inference/embeddings"
GITHUB_MODELS_MODEL = "openai/text-embedding-3-small"


def _get_token() -> str:
    """Read GITHUB_MODELS_TOKEN from env. Raises ValueError if missing."""
    token = os.getenv("GITHUB_MODELS_TOKEN")
    if not token:
        raise ValueError(
            "GITHUB_MODELS_TOKEN is not set. "
            "Add it to .env or set it as an environment variable."
        )
    return token


def _call_embeddings_sync(texts: list[str]) -> list[list[float]]:
    """
    Synchronous POST to GitHub Models embeddings API.
    Returns one embedding vector per input text.
    """
    token = _get_token()

    body = json.dumps({
        "input": texts,
        "model": GITHUB_MODELS_MODEL,
    }).encode("utf-8")

    req = urllib.request.Request(
        GITHUB_MODELS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        logger.error("Embeddings API HTTP %d: %s", e.code, error_body)
        raise RuntimeError(f"Embeddings API returned HTTP {e.code}") from e
    except urllib.error.URLError as e:
        logger.error("Embeddings API connection error: %s", e.reason)
        raise RuntimeError(f"Embeddings API connection failed: {e.reason}") from e

    # Response: { data: [ {index, embedding, object}, ... ], model, usage }
    items = sorted(data.get("data", []), key=lambda x: x["index"])
    embeddings = [item["embedding"] for item in items]

    logger.info(
        "Embeddings API: %d texts → %d vectors (%d dims)",
        len(texts), len(embeddings),
        len(embeddings[0]) if embeddings else 0,
    )
    return embeddings


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Async wrapper — runs the blocking HTTP call in a thread executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _call_embeddings_sync, texts)


async def get_single_embedding(text: str) -> list[float]:
    """Embed a single text string, return one vector."""
    results = await get_embeddings([text])
    return results[0]
