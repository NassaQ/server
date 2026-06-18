from pydantic import BaseModel, Field


class PageDiagnosticSchema(BaseModel):
    page_number: int
    status: str
    words_count: int
    avg_confidence: float


class ClassificationInfoSchema(BaseModel):
    domain: str
    category: str
    confidence: float
    reasoning: str
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: str | None = None


class CostBreakdownSchema(BaseModel):
    ocr_cost_usd: float
    classification_cost_usd: float
    total_cost_usd: float


class ProcessResponse(BaseModel):
    success: bool
    error: str | None = None
    filename: str = ""
    document_id: str = ""
    extracted_text: str = ""
    cleaned_text: str = ""
    primary_language: str = "unknown"
    tables_markdown: list[str] = []
    page_count: int = 0
    word_count: int = 0
    avg_confidence: float = 0.0
    ocr_elapsed_seconds: float = 0.0
    chunks_used: int = 1
    quality: dict = {}
    per_page: list[PageDiagnosticSchema] = []
    classification: ClassificationInfoSchema | None = None
    costs: CostBreakdownSchema | None = None


class HistoryItemSchema(BaseModel):
    id: str
    doc_id: int = 0
    document_id: str = ""
    filename: str
    domain: str = ""
    category: str = "Unknown"
    confidence: float = 0.0
    page_count: int
    word_count: int
    primary_language: str
    ocr_cost_usd: float
    classification_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    processed_at: str
    elapsed_seconds: float


class StatsResponseSchema(BaseModel):
    total_documents: int
    total_pages: int
    total_words: int
    total_cost_usd: float
    avg_confidence: float
    avg_processing_time: float
    domains: dict[str, int]
    categories: dict[str, int]
    languages: dict[str, int]
