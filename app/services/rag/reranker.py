"""
Cohere Rerank v4.0 Fast client via Azure AI Foundry.

Two-stage retrieval pattern:
  Stage 1 (Recall):   FAISS returns top-K candidates (fast, broad)
  Stage 2 (Precision): Cohere cross-attention reranker re-scores → top-N

The reranker reads query + document together (cross-attention), catching
semantic relationships that embedding dot-product misses.  Cohere reports
15–30 % improvement in NDCG@10 on BEIR benchmarks with reranking.

If the reranker endpoint is not configured the module gracefully degrades
to a no-op (returns the input list unchanged).
"""

import json
import urllib.request
import urllib.error
from dataclasses import dataclass


@dataclass
class RerankResult:
    """A single reranked document."""

    index: int  # Original position in the input list
    relevance_score: float
    text: str  # The document text


def rerank(
    query: str,
    documents: list[str],
    endpoint: str,
    api_key: str,
    model: str = "cohere-rerank-v4-0-fast",
    top_n: int = 5,
) -> list[RerankResult]:
    """
    Rerank *documents* against *query* using Cohere Rerank on Azure AI Foundry.

    Args:
        query:     The search query.
        documents: List of candidate document texts (from FAISS stage).
        endpoint:  Azure AI Foundry model endpoint URL.
        api_key:   API key for the endpoint.
        model:     Model name (for the request body).
        top_n:     Number of top results to return.

    Returns:
        List of :class:`RerankResult` sorted by descending relevance.
        If the reranker is unavailable or fails, returns the input
        documents in their original order (graceful degradation).
    """
    # ── Guard: not configured ─────────────────────────────────────────
    if not endpoint or not api_key:
        return [
            RerankResult(index=i, relevance_score=0.0, text=doc)
            for i, doc in enumerate(documents[:top_n])
        ]

    if not documents:
        return []

    # ── Build request ─────────────────────────────────────────────────
    # The endpoint may already be the full URL (e.g. .../v2/rerank)
    # or just the base URL.  Only append /v2/rerank if not present.
    url = endpoint.rstrip("/")
    if not url.endswith("/rerank"):
        url = url + "/v2/rerank"

    payload = json.dumps(
        {
            "model": model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
            "return_documents": True,
        }
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "api-key": api_key,
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    # ── Call endpoint ─────────────────────────────────────────────────
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return [
            RerankResult(index=i, relevance_score=0.0, text=doc)
            for i, doc in enumerate(documents[:top_n])
        ]
    except Exception:
        return [
            RerankResult(index=i, relevance_score=0.0, text=doc)
            for i, doc in enumerate(documents[:top_n])
        ]

    # ── Parse response ────────────────────────────────────────────────
    results: list[RerankResult] = []
    for item in body.get("results", []):
        idx = item.get("index", 0)
        score = float(item.get("relevance_score", 0.0))
        text = item.get("document", {}).get(
            "text", documents[idx] if idx < len(documents) else ""
        )
        results.append(RerankResult(index=idx, relevance_score=score, text=text))

    # Already sorted by relevance (Cohere API returns sorted), but be safe
    results.sort(key=lambda r: r.relevance_score, reverse=True)

    return results
