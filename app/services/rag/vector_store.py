"""
Azure AI Search vector store for the RAG pipeline.

Stores chunk embeddings and metadata in an Azure AI Search index using
HNSW vector search with cosine similarity.  All vectors MUST be
L2-normalised before insertion so that cosine scoring is consistent
with the embedding pipeline.

Index schema (auto-created on first use):
    id              — deterministic key ``{document_id}_{chunk_index}``
    document_id     — filterable string
    chunk_index     — int32
    page_number     — int32
    token_count     — int32
    section_heading — string
    text_clean      — searchable string
    text_original   — string
    classification  — filterable string
    language        — filterable string
    source_file     — string
    created_at      — string (ISO-8601)
    embedding       — Collection(Edm.Single), 1536 dims, HNSW / cosine
"""

from typing import Optional

import numpy as np
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

_UPLOAD_BATCH_SIZE = 1000


class AzureSearchVectorStore:
    """Azure AI Search index backed vector store."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        index_name: str = "nassaq-chunks",
        dimensions: int = 1536,
    ):
        self._endpoint = endpoint
        self._credential = AzureKeyCredential(api_key)
        self._index_name = index_name
        self._dims = dimensions

        self._index_client = SearchIndexClient(
            endpoint=self._endpoint,
            credential=self._credential,
        )
        self._search_client = SearchClient(
            endpoint=self._endpoint,
            index_name=self._index_name,
            credential=self._credential,
        )

        self._ensure_index()

    def _ensure_index(self) -> None:
        """Create the search index if it does not already exist."""
        fields = [
            SimpleField(
                name="id",
                type=SearchFieldDataType.String,
                key=True,
                filterable=True,
            ),
            SimpleField(
                name="document_id",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="chunk_index",
                type=SearchFieldDataType.Int32,
                filterable=True,
            ),
            SimpleField(
                name="page_number",
                type=SearchFieldDataType.Int32,
                filterable=True,
            ),
            SimpleField(
                name="token_count",
                type=SearchFieldDataType.Int32,
            ),
            SearchableField(
                name="section_heading",
                type=SearchFieldDataType.String,
            ),
            SearchableField(
                name="text_clean",
                type=SearchFieldDataType.String,
            ),
            SimpleField(
                name="text_original",
                type=SearchFieldDataType.String,
            ),
            SimpleField(
                name="classification",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="language",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="source_file",
                type=SearchFieldDataType.String,
            ),
            SimpleField(
                name="created_at",
                type=SearchFieldDataType.String,
            ),
            SearchField(
                name="embedding",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=self._dims,
                vector_search_profile_name="default-vector-profile",
            ),
        ]

        vector_search = VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(name="default-hnsw"),
            ],
            profiles=[
                VectorSearchProfile(
                    name="default-vector-profile",
                    algorithm_configuration_name="default-hnsw",
                ),
            ],
        )

        index = SearchIndex(
            name=self._index_name,
            fields=fields,
            vector_search=vector_search,
        )

        self._index_client.create_or_update_index(index)

    @property
    def total_vectors(self) -> int:
        """Return the total number of chunks in the index."""
        return self._search_client.get_document_count()

    @property
    def total_documents(self) -> int:
        """Return the number of distinct documents in the index."""
        results = self._search_client.search(
            search_text="*",
            filter="chunk_index eq 0",
            top=0,
            include_total_count=True,
        )
        return results.get_count() or 0

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
            List of assigned document IDs (``{document_id}_{chunk_index}``).
        """
        assert len(vectors) == len(metadatas), "vectors/metadata length mismatch"

        docs = []
        ids = []
        for vec, meta in zip(vectors, metadatas):
            chunk_index = meta.get("chunk_index", 0)
            doc_id = f"{document_id}_{chunk_index}"
            ids.append(doc_id)
            docs.append(
                {
                    "id": doc_id,
                    "document_id": document_id,
                    "chunk_index": int(chunk_index),
                    "page_number": int(meta.get("page_number", 1)),
                    "token_count": int(meta.get("token_count", 0)),
                    "section_heading": meta.get("section_heading", ""),
                    "text_clean": meta.get("text_clean", ""),
                    "text_original": meta.get("text_original", ""),
                    "classification": meta.get("classification", ""),
                    "language": meta.get("language", ""),
                    "source_file": meta.get("source_file", ""),
                    "created_at": meta.get("created_at", ""),
                    "embedding": vec.tolist(),
                }
            )

        for i in range(0, len(docs), _UPLOAD_BATCH_SIZE):
            batch = docs[i : i + _UPLOAD_BATCH_SIZE]
            self._search_client.upload_documents(documents=batch)

        return ids

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
        vector_query = VectorizedQuery(
            vector=query_vector[0].tolist(),
            k_nearest_neighbors=k,
            fields="embedding",
        )

        results = self._search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            top=k,
            select=[
                "id",
                "document_id",
                "chunk_index",
                "page_number",
                "token_count",
                "section_heading",
                "text_clean",
                "text_original",
                "classification",
                "language",
                "source_file",
                "created_at",
            ],
        )

        output: list[dict] = []
        for result in results:
            output.append(
                {
                    "chunk_id": result["id"],
                    "score": float(result["@search.score"]),
                    "document_id": result.get("document_id", ""),
                    "chunk_index": result.get("chunk_index", 0),
                    "page_number": result.get("page_number", 1),
                    "token_count": result.get("token_count", 0),
                    "section_heading": result.get("section_heading", ""),
                    "text_clean": result.get("text_clean", ""),
                    "text_original": result.get("text_original", ""),
                    "classification": result.get("classification", ""),
                    "language": result.get("language", ""),
                    "source_file": result.get("source_file", ""),
                    "created_at": result.get("created_at", ""),
                }
            )

        return output

    def remove_document(self, document_id: str) -> int:
        """
        Remove all vectors belonging to a document.

        Returns the number of vectors removed.
        """
        results = self._search_client.search(
            search_text="*",
            filter=f"document_id eq '{document_id}'",
            select=["id"],
            top=10000,
        )

        docs_to_delete = [{"id": r["id"]} for r in results]
        if not docs_to_delete:
            return 0

        for i in range(0, len(docs_to_delete), _UPLOAD_BATCH_SIZE):
            batch = docs_to_delete[i : i + _UPLOAD_BATCH_SIZE]
            self._search_client.delete_documents(documents=batch)

        return len(docs_to_delete)

    def list_documents(self) -> list[dict]:
        """List all ingested documents with summary info."""
        results = self._search_client.search(
            search_text="*",
            filter="chunk_index eq 0",
            select=[
                "document_id",
                "source_file",
                "classification",
                "language",
            ],
            top=10000,
        )

        docs: list[dict] = []
        seen: set[str] = set()
        for r in results:
            doc_id = r["document_id"]
            if doc_id in seen:
                continue
            seen.add(doc_id)

            chunk_count = self._count_chunks_for_document(doc_id)
            docs.append(
                {
                    "document_id": doc_id,
                    "chunks_count": chunk_count,
                    "source_file": r.get("source_file", ""),
                    "classification": r.get("classification", ""),
                    "language": r.get("language", ""),
                }
            )

        return docs

    def has_document(self, document_id: str) -> bool:
        """Check if a document has been ingested."""
        results = self._search_client.search(
            search_text="*",
            filter=f"document_id eq '{document_id}'",
            select=["id"],
            top=1,
            include_total_count=True,
        )
        return (results.get_count() or 0) > 0

    def _count_chunks_for_document(self, document_id: str) -> int:
        """Return the number of chunks stored for a given document."""
        results = self._search_client.search(
            search_text="*",
            filter=f"document_id eq '{document_id}'",
            select=["id"],
            top=0,
            include_total_count=True,
        )
        return results.get_count() or 0
