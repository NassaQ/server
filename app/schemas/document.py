"""
Pydantic schemas for document processing endpoints.
"""

from pydantic import BaseModel
from typing import Optional


class PageDiagnostic(BaseModel):
    """Per-page quality diagnostic."""

    page_number: int
    status: str
    words_count: int
    avg_confidence: float


class ClassificationInfo(BaseModel):
    """Classification result."""

    category: str
    confidence: float
    reasoning: str
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None


class CostBreakdown(BaseModel):
    """Cost breakdown for OCR + classification."""

    ocr_cost_usd: float = 0.0
    classification_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


class DocumentProcessResponse(BaseModel):
    """Full response from the document processing endpoint."""

    # Status
    success: bool
    error: Optional[str] = None

    # File info
    filename: str = ""

    # OCR results
    extracted_text: str = ""
    cleaned_text: str = ""
    primary_language: str = "unknown"
    tables_markdown: list[str] = []

    # Metrics
    page_count: int = 0
    word_count: int = 0
    avg_confidence: float = 0.0
    ocr_elapsed_seconds: float = 0.0
    chunks_used: int = 1

    # Quality
    quality: dict = {}
    per_page: list[PageDiagnostic] = []

    # Classification
    classification: Optional[ClassificationInfo] = None

    # Costs
    costs: CostBreakdown = CostBreakdown()


class HistoryItem(BaseModel):
    """A single item in the processing history."""

    id: str
    filename: str
    category: str
    confidence: float
    page_count: int
    word_count: int
    primary_language: str
    ocr_cost_usd: float
    classification_cost_usd: float
    total_cost_usd: float
    processed_at: str
    elapsed_seconds: float


class StatsResponse(BaseModel):
    """Dashboard statistics computed from processing history."""

    total_documents: int = 0
    total_pages: int = 0
    total_words: int = 0
    total_cost_usd: float = 0.0
    avg_confidence: float = 0.0
    avg_processing_time: float = 0.0
    categories: dict[str, int] = {}
    languages: dict[str, int] = {}
