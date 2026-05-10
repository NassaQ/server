"""
Pinecone vector store for the RAG pipeline.

Stores chunk embeddings and metadata in a Pinecone serverless index using
cosine similarity.  All vectors MUST be L2-normalised before insertion
so that cosine scoring is consistent with the embedding pipeline.

Pinecone schema (auto-created on first use):
    dimension  = 1536 (text-embedding-3-small)
    metric     = cosine
    spec       = Serverless (AWS / us-east-1)

Vector metadata fields:
    document_id     — filterable string
    chunk_index     — int
    page_number     — int
    token_count     — int
    section_heading — string
    text_clean      — string
    text_original   — string
    classification  — filterable string
    language        — filterable string
    source_file     — string
    created_at      — string (ISO-8601)
"""

from typing import Optional

import numpy as np

from pinecone import Pinecone, ServerlessSpec

_UPSERT_BATCH_SIZE = 100
_NEUTRAL_VEC_CACHE: Optional[list[float]] = None


def _neutral_vector(dims: int) -> list[float]:
    """Return a cached zero-vector for filter-only queries."""
    global _NEUTRAL_VEC_CACHE
    if _NEUTRAL_VEC_CACHE is None or len(_NEUTRAL_VEC_CACHE) != dims:
        _NEUTRAL_VEC_CACHE = [0.0] * dims
    return _NEUTRAL_VEC_CACHE


class PineconeVectorStore:
    """Pinecone serverless index backed vector store."""

    def __init__(
        self,
        api_key: str,
        index_name: str = "nassaq",
        dimensions: int = 1536,
        cloud: str = "aws",
        region: str = "us-east-1",
    ):
        self._api_key = api_key
        self._index_name = index_name
        self._dims = dimensions
        self._cloud = cloud
        self._region = region

        self._pc: Optional[Pinecone] = None
        self._index = None
        self._document_ids: set[str] = set()
        self._synced = False

        if api_key:
            self._pc = Pinecone(api_key=api_key)
            self._ensure_index()
            self._index = self._pc.Index(index_name)

    # ── Index management ────────────────────────────────────────────────

    def _ensure_index(self) -> None:
        """Create the Pinecone index if it does not already exist."""
        existing = self._pc.list_indexes().names()
        if self._index_name not in existing:
            self._pc.create_index(
                name=self._index_name,
                dimension=self._dims,
                metric="cosine",
                spec=ServerlessSpec(cloud=self._cloud, region=self._region),
            )

    def _ready(self) -> bool:
        """Check whether the index is available for operations."""
        return self._index is not None

    # ── Lazy document-ID sync ───────────────────────────────────────────

    def _sync_docs(self) -> None:
        """Populate the in-memory set of known document IDs from Pinecone."""
        if self._synced or not self._ready():
            return
        try:
            results = self._index.query(
                vector=_neutral_vector(self._dims),
                top_k=10000,
                include_metadata=True,
                filter={"chunk_index": 0},
            )
            for r in results.get("matches", []):
                doc_id = (r.get("metadata") or {}).get("document_id")
                if doc_id:
                    self._document_ids.add(doc_id)
        except Exception:
            pass
        self._synced = True

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def total_vectors(self) -> int:
        """Return the total number of vectors (chunks) in the index."""
        if not self._ready():
            return 0
        stats = self._index.describe_index_stats()
        return int(stats.get("total_vector_count", 0))

    @property
    def total_documents(self) -> int:
        """Return the number of distinct documents in the index."""
        if not self._ready():
            return 0
        self._sync_docs()
        return len(self._document_ids)

    # ── Document existence check ────────────────────────────────────────

    def has_document(self, document_id: str) -> bool:
        """Check if a document has been ingested."""
        if not self._ready():
            return False
        if document_id in self._document_ids:
            return True
        # Double-check via a lightweight query
        try:
            results = self._index.query(
                vector=_neutral_vector(self._dims),
                top_k=1,
                include_metadata=False,
                filter={"document_id": document_id},
            )
            exists = len(results.get("matches", [])) > 0
            if exists:
                self._document_ids.add(document_id)
            return exists
        except Exception:
            return False

    # ── Add / upsert vectors ────────────────────────────────────────────

    def add(
        self,
        vectors: np.ndarray,
        metadatas: list[dict],
        document_id: str,
    ) -> list[str]:
        """
        Upload vectors and metadata for a single document.

        Args:
            vectors:     ``(n, dims)`` float32 array, **already L2-normalised**.
            metadatas:   One dict per vector with at least ``text_clean``.
            document_id: Unique document identifier.

        Returns:
            List of assigned vector IDs (``{document_id}_{chunk_index}``).
        """
        if not self._ready():
            return []

        assert len(vectors) == len(metadatas), "vectors/metadata length mismatch"

        ids: list[str] = []
        pinecone_vectors: list[tuple[str, list[float], dict]] = []

        for i, (vec, meta) in enumerate(zip(vectors, metadatas)):
            chunk_index = meta.get("chunk_index", i)
            vec_id = f"{document_id}_{chunk_index}"
            ids.append(vec_id)
            pinecone_vectors.append((vec_id, vec.tolist(), dict(meta)))

        # Batch upsert in chunks to avoid payload limits
        for start in range(0, len(pinecone_vectors), _UPSERT_BATCH_SIZE):
            batch = pinecone_vectors[start : start + _UPSERT_BATCH_SIZE]
            self._index.upsert(vectors=batch)

        self._document_ids.add(document_id)
        return ids

    # ── Search ──────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: np.ndarray,
        k: int = 20,
    ) -> list[dict]:
        """
        Search for the top-*k* most similar vectors.

        Args:
            query_vector: ``(1, dims)`` float32 array, **L2-normalised**.
            k:            Number of results to return.

        Returns:
            List of dicts, each containing the chunk metadata plus
            ``chunk_id`` and ``score`` (cosine similarity).
        """
        if not self._ready():
            return []

        results = self._index.query(
            vector=query_vector[0].tolist(),
            top_k=k,
            include_metadata=True,
        )

        output: list[dict] = []
        for r in results.get("matches", []):
            meta = r.get("metadata") or {}
            output.append(
                {
                    "chunk_id": r.get("id", ""),
                    "score": float(r.get("score", 0.0)),
                    "document_id": meta.get("document_id", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                    "page_number": meta.get("page_number", 1),
                    "token_count": meta.get("token_count", 0),
                    "section_heading": meta.get("section_heading", ""),
                    "text_clean": meta.get("text_clean", ""),
                    "text_original": meta.get("text_original", ""),
                    "classification": meta.get("classification", ""),
                    "language": meta.get("language", ""),
                    "source_file": meta.get("source_file", ""),
                    "created_at": meta.get("created_at", ""),
                }
            )

        return output

    # ── Remove document ─────────────────────────────────────────────────

    def remove_document(self, document_id: str) -> int:
        """
        Remove all vectors belonging to a document.

        Returns the number of vectors removed.
        """
        if not self._ready():
            return 0

        # Count first
        results = self._index.query(
            vector=_neutral_vector(self._dims),
            top_k=10000,
            include_metadata=False,
            filter={"document_id": document_id},
        )
        count = len(results.get("matches", []))

        if count > 0:
            self._index.delete(filter={"document_id": document_id})

        self._document_ids.discard(document_id)
        return count

    # ── List documents ──────────────────────────────────────────────────

    def list_documents(self) -> list[dict]:
        """List all ingested documents with summary info."""
        if not self._ready():
            return []
        self._sync_docs()

        docs: list[dict] = []
        for doc_id in self._document_ids:
            # Fetch one representative chunk's metadata
            try:
                results = self._index.query(
                    vector=_neutral_vector(self._dims),
                    top_k=1,
                    include_metadata=True,
                    filter={"document_id": doc_id, "chunk_index": 0},
                )
                matches = results.get("matches", [])
                if matches:
                    meta = matches[0].get("metadata") or {}
                    docs.append(
                        {
                            "document_id": doc_id,
                            "chunks_count": self._count_chunks(doc_id),
                            "source_file": meta.get("source_file", ""),
                            "classification": meta.get("classification", ""),
                            "language": meta.get("language", ""),
                        }
                    )
                else:
                    # Fallback: query without chunk_index filter
                    results = self._index.query(
                        vector=_neutral_vector(self._dims),
                        top_k=1,
                        include_metadata=True,
                        filter={"document_id": doc_id},
                    )
                    matches = results.get("matches", [])
                    if matches:
                        meta = matches[0].get("metadata") or {}
                        docs.append(
                            {
                                "document_id": doc_id,
                                "chunks_count": self._count_chunks(doc_id),
                                "source_file": meta.get("source_file", ""),
                                "classification": meta.get("classification", ""),
                                "language": meta.get("language", ""),
                            }
                        )
            except Exception:
                continue

        return docs

    # ── Internal helpers ────────────────────────────────────────────────

    def _count_chunks(self, document_id: str) -> int:
        """Return the number of chunks stored for a given document."""
        try:
            results = self._index.query(
                vector=_neutral_vector(self._dims),
                top_k=10000,
                include_metadata=False,
                filter={"document_id": document_id},
            )
            return len(results.get("matches", []))
        except Exception:
            return 0
