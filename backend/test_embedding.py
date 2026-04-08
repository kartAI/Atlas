"""
Minimal test: call the GitHub Models embeddings API with a sample string.

Usage:
  cd backend
  python test_embedding.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Load .env from project root
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from embedding_client import get_single_embedding, get_embeddings


async def main():
    token = os.getenv("GITHUB_MODELS_TOKEN")
    if not token:
        print("ERROR: GITHUB_MODELS_TOKEN is not set in .env")
        sys.exit(1)

    print("Token loaded (length: %d)" % len(token))

    # Test 1: single embedding
    print("\n--- Test 1: single embedding ---")
    text = "Konsekvensutredning for nytt boligfelt i Trondheim kommune."
    vec = await get_single_embedding(text)
    print("Input:      %s" % text[:60])
    print("Dimensions: %d" % len(vec))
    print("First 5:    %s" % vec[:5])

    # Test 2: batch of two texts
    print("\n--- Test 2: batch embedding ---")
    texts = [
        "Naturmangfoldloven stiller krav til utredning av biologisk mangfold.",
        "Plan- og bygningsloven regulerer arealplanlegging i Norge.",
    ]
    vecs = await get_embeddings(texts)
    print("Inputs:     %d texts" % len(texts))
    print("Vectors:    %d" % len(vecs))
    for i, v in enumerate(vecs):
        print("  [%d] dims=%d, first 3=%s" % (i, len(v), v[:3]))

    print("\nAll tests passed.")


if __name__ == "__main__":
    asyncio.run(main())
