"""
RAG (Retrieval-Augmented Generation) service package.

Submodules:
    engine           — Orchestrates ingest, search, and ask pipelines
    embedding_client — Azure OpenAI text embeddings
    vector_store     — Azure AI Search index-backed vector store
    reranker         — Cohere Rerank v4.0 Fast via Azure AI Foundry
    text_processor   — Structure-aware chunking and embedding-ready cleaning

Public API re-exported below for convenience:
    from app.services.rag import ingest, search, ask, ...
"""

from app.services.rag.engine import (
    get_store,
    ingest,
    search,
    ask,
    list_documents,
    remove_document,
    store_stats,
)

__all__ = [
    "get_store",
    "ingest",
    "search",
    "ask",
    "list_documents",
    "remove_document",
    "store_stats",
]
