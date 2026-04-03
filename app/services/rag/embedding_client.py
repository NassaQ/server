"""
Azure OpenAI embedding client for the RAG pipeline.

Uses ``text-embedding-3-small`` (1536 dimensions, ~$0.02 / 1M tokens).
All vectors are L2-normalised so that FAISS ``IndexFlatIP`` inner-product
search is equivalent to cosine similarity.
"""

import logging
from typing import Optional

import numpy as np
from openai import AzureOpenAI

logger = logging.getLogger("nassaq.embeddings")

# ── Module-level singleton ────────────────────────────────────────────────
_client: Optional[AzureOpenAI] = None


def _get_client(
    api_key: str,
    endpoint: str,
    api_version: str,
) -> AzureOpenAI:
    """Lazily create a single AzureOpenAI client per process."""
    global _client
    if _client is None:
        _client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )
    return _client


def embed_texts(
    texts: list[str],
    api_key: str,
    endpoint: str,
    api_version: str = "2024-12-01-preview",
    model: str = "text-embedding-3-small",
    batch_size: int = 16,
) -> np.ndarray:
    """
    Embed a list of texts using Azure OpenAI.

    Args:
        texts:       The strings to embed.
        api_key:     Azure OpenAI API key.
        endpoint:    Azure OpenAI endpoint URL.
        api_version: API version string.
        model:       Deployment name (defaults to ``text-embedding-3-small``).
        batch_size:  Max texts per API call (Azure caps at 16).

    Returns:
        ``np.ndarray`` of shape ``(len(texts), dimensions)`` with
        **L2-normalised** float32 vectors ready for FAISS ``IndexFlatIP``.
    """
    if not texts:
        return np.empty((0, 1536), dtype=np.float32)

    client = _get_client(api_key, endpoint, api_version)

    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        # Guard against empty strings (API rejects them)
        batch = [t if t.strip() else "empty" for t in batch]

        logger.debug("Embedding batch %d–%d of %d", i, i + len(batch), len(texts))

        response = client.embeddings.create(input=batch, model=model)

        for item in sorted(response.data, key=lambda d: d.index):
            all_embeddings.append(item.embedding)

    embeddings = np.array(all_embeddings, dtype=np.float32)

    # L2-normalise so inner-product == cosine similarity
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embeddings = embeddings / norms

    logger.info("Embedded %d texts → shape %s", len(texts), embeddings.shape)
    return embeddings


def embed_query(
    query: str,
    api_key: str,
    endpoint: str,
    api_version: str = "2024-12-01-preview",
    model: str = "text-embedding-3-small",
) -> np.ndarray:
    """
    Embed a single query string.

    Convenience wrapper around :func:`embed_texts` that returns a
    2-D array of shape ``(1, dimensions)`` suitable for ``index.search()``.
    """
    return embed_texts(
        [query],
        api_key=api_key,
        endpoint=endpoint,
        api_version=api_version,
        model=model,
    )
