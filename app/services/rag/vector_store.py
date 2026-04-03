"""
FAISS vector store with pickle-backed metadata.

Stores:
  - FAISS ``IndexIDMap2(IndexFlatIP)`` on disk  (``nassaq.index``)
  - Chunk metadata dict via pickle               (``nassaq_meta.pkl``)

Using ``IndexIDMap2`` over a flat inner-product index because:
  1. Custom int64 IDs  → deterministic mapping to chunk metadata
  2. ``remove_ids()``  → supports document deletion
  3. ``IndexFlatIP``   → exact search; at <100 K vectors this is sub-ms

All vectors MUST be L2-normalised before insertion so that inner-product
equals cosine similarity.
"""

import logging
import os
import pickle
import threading
from pathlib import Path
from typing import Optional

import faiss
import numpy as np

logger = logging.getLogger("nassaq.vector_store")

# ── Metadata structure (persisted to pickle) ─────────────────────────────
# {
#   "next_id":    int,                          # auto-increment counter
#   "chunks":     { faiss_id: { ... meta }, },  # per-chunk metadata
#   "documents":  { doc_id: [faiss_id, ...] },  # reverse index for deletion
# }


class FAISSVectorStore:
    """Thread-safe FAISS index with persisted metadata."""

    def __init__(self, index_dir: str, dimensions: int = 1536):
        self._dir = Path(index_dir)
        self._dims = dimensions
        self._lock = threading.Lock()

        self._index_path = self._dir / "nassaq.index"
        self._meta_path = self._dir / "nassaq_meta.pkl"

        self._index: faiss.Index = None  # type: ignore[assignment]
        self._meta: dict = {}

        self._load_or_create()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def _load_or_create(self) -> None:
        """Load existing index from disk, or create an empty one."""
        self._dir.mkdir(parents=True, exist_ok=True)

        if self._index_path.exists() and self._meta_path.exists():
            try:
                self._index = faiss.read_index(str(self._index_path))
                with open(self._meta_path, "rb") as f:
                    self._meta = pickle.load(f)
                logger.info(
                    "Loaded FAISS index: %d vectors, %d documents",
                    self._index.ntotal,
                    len(self._meta.get("documents", {})),
                )
                return
            except Exception as exc:
                logger.warning("Failed to load index, creating fresh: %s", exc)

        # Create empty index
        flat = faiss.IndexFlatIP(self._dims)
        self._index = faiss.IndexIDMap2(flat)
        self._meta = {"next_id": 0, "chunks": {}, "documents": {}}
        logger.info("Created new empty FAISS index (dim=%d)", self._dims)

    def _persist(self) -> None:
        """Write index + metadata to disk.  Called under lock."""
        faiss.write_index(self._index, str(self._index_path))
        with open(self._meta_path, "wb") as f:
            pickle.dump(self._meta, f, protocol=pickle.HIGHEST_PROTOCOL)

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def total_vectors(self) -> int:
        return self._index.ntotal

    @property
    def total_documents(self) -> int:
        return len(self._meta.get("documents", {}))

    def add(
        self,
        vectors: np.ndarray,
        metadatas: list[dict],
        document_id: str,
    ) -> list[int]:
        """
        Add vectors + metadata for a single document.

        Args:
            vectors:     ``(n, dims)`` float32 array, **already L2-normalised**.
            metadatas:   One dict per vector with at least ``text_clean``.
            document_id: Unique document identifier.

        Returns:
            List of assigned FAISS IDs.
        """
        assert len(vectors) == len(metadatas), "vectors/metadata length mismatch"

        with self._lock:
            start_id = self._meta["next_id"]
            ids = np.arange(start_id, start_id + len(vectors), dtype=np.int64)
            self._meta["next_id"] = int(start_id + len(vectors))

            self._index.add_with_ids(vectors, ids)

            # Store metadata
            for fid, meta in zip(ids, metadatas):
                self._meta["chunks"][int(fid)] = meta

            # Reverse index
            self._meta["documents"][document_id] = [int(i) for i in ids]

            self._persist()

        logger.info(
            "Added %d vectors for document %s (total: %d)",
            len(vectors),
            document_id,
            self._index.ntotal,
        )
        return [int(i) for i in ids]

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
            ``faiss_id`` and ``score`` (cosine similarity).
        """
        if self._index.ntotal == 0:
            return []

        actual_k = min(k, self._index.ntotal)

        with self._lock:
            scores, ids = self._index.search(query_vector, actual_k)

        results: list[dict] = []
        for score, fid in zip(scores[0], ids[0]):
            if fid == -1:
                continue
            meta = self._meta["chunks"].get(int(fid))
            if meta is None:
                continue
            results.append(
                {
                    "faiss_id": int(fid),
                    "score": float(score),
                    **meta,
                }
            )
        return results

    def remove_document(self, document_id: str) -> int:
        """
        Remove all vectors belonging to a document.

        Returns the number of vectors removed.
        """
        with self._lock:
            fids = self._meta["documents"].pop(document_id, [])
            if not fids:
                return 0

            id_array = np.array(fids, dtype=np.int64)
            self._index.remove_ids(id_array)

            for fid in fids:
                self._meta["chunks"].pop(fid, None)

            self._persist()

        logger.info(
            "Removed %d vectors for document %s (total: %d)",
            len(fids),
            document_id,
            self._index.ntotal,
        )
        return len(fids)

    def list_documents(self) -> list[dict]:
        """
        List all ingested documents with summary info.
        """
        result: list[dict] = []
        for doc_id, fids in self._meta.get("documents", {}).items():
            if not fids:
                continue
            # Get metadata from first chunk for summary info
            first_meta = self._meta["chunks"].get(fids[0], {})
            result.append(
                {
                    "document_id": doc_id,
                    "chunks_count": len(fids),
                    "source_file": first_meta.get("source_file", ""),
                    "classification": first_meta.get("classification", ""),
                    "language": first_meta.get("language", ""),
                }
            )
        return result

    def has_document(self, document_id: str) -> bool:
        """Check if a document has been ingested."""
        return document_id in self._meta.get("documents", {})
