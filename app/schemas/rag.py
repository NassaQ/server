"""
Pydantic schemas for the RAG endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional

class IngestRequest(BaseModel):
    """Request body for ``POST /rag/ingest``."""

    document_id: str = Field(
        ..., description="Unique document ID (UUID from processing history)"
    )
    cleaned_text: str = Field(
        ...,
        description="Markdown-formatted text from OCR (PipelineResult.cleaned_text)",
    )
    tables_markdown: list[str] = Field(
        default=[], description="Table markdown strings from OCR"
    )
    classification: str = Field(default="", description="Classification category label")
    language: str = Field(
        default="unknown", description="Detected language: ar / en / mixed"
    )
    source_file: str = Field(default="", description="Original filename")


class IngestResponse(BaseModel):
    """Response from ``POST /rag/ingest``."""

    document_id: str
    status: str  # "ingested", "already_ingested", "no_chunks"
    chunks_created: int = 0
    total_tokens: int = 0
    source_file: str = ""


# ── Search ────────────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    """Request body for ``POST /rag/search``."""

    query: str = Field(..., min_length=1, description="Natural-language search query")
    top_k: int = Field(
        default=5, ge=1, le=50, description="Number of results to return"
    )
    filter_classification: Optional[str] = Field(
        default=None, description="Filter by category"
    )
    filter_language: Optional[str] = Field(
        default=None, description="Filter by language"
    )
    filter_document_id: Optional[str] = Field(
        default=None, description="Filter by document ID"
    )


class SearchResultItem(BaseModel):
    """A single search result chunk."""

    text: str
    text_original: str = ""
    document_id: str = ""
    source_file: str = ""
    page_number: int = 1
    section_heading: str = ""
    classification: str = ""
    language: str = ""
    search_score: float = 0.0
    rerank_score: float = 0.0


class SearchResponse(BaseModel):
    """Response from ``POST /rag/search``."""

    query: str
    results: list[SearchResultItem] = []
    total_results: int = 0


class AskRequest(BaseModel):
    """Request body for ``POST /rag/ask``."""

    query: str = Field(..., min_length=1, description="Natural-language question")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of context chunks")
    filter_classification: Optional[str] = Field(
        default=None, description="Filter by category"
    )
    filter_language: Optional[str] = Field(
        default=None, description="Filter by language"
    )
    filter_document_id: Optional[str] = Field(
        default=None, description="Filter by document ID"
    )

class AskResponse(BaseModel):
    """Response from ``POST /rag/ask``."""

    answer: str
    sources: list[SearchResultItem] = []
    tokens_used: int = 0
    cost_usd: float = 0.0


class DocumentInfo(BaseModel):
    """Summary of an ingested document."""

    document_id: str
    chunks_count: int = 0
    source_file: str = ""
    classification: str = ""
    language: str = ""


class RemoveResponse(BaseModel):
    """Response from ``DELETE /rag/documents/{document_id}``."""

    document_id: str
    status: str  # "removed", "not_found"
    chunks_removed: int = 0


class StoreStatsResponse(BaseModel):
    """Vector store statistics."""

    total_vectors: int = 0
    total_documents: int = 0
