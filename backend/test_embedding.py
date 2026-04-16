"""
Live integration test: call the configured embeddings provider with real Norwegian text.

Auto-detects the active provider from .env (Azure OpenAI takes priority over GitHub Models).

Usage:
  cd backend
  python test_embedding.py
"""

import asyncio
import sys

from dotenv import load_dotenv
load_dotenv()

from embedding_client import get_single_embedding, get_embeddings, get_provider_name


async def main():
    try:
        provider = get_provider_name()
    except ValueError as e:
        print("ERROR: %s" % e)
        sys.exit(1)

    print("Provider:   %s" % provider)

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
