"""
Document processing endpoints.

POST /process   — Upload file -> OCR -> Classify -> Return results
GET  /history   — List previously processed documents (in-memory)
GET  /stats     — Dashboard statistics computed from history
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Query, status

from app.core.config import settings
from app.api.deps import ActiveUser
from app.schemas.document import (
    DocumentProcessResponse,
    ClassificationInfo,
    CostBreakdown,
    PageDiagnostic,
    HistoryItem,
    StatsResponse,
)
from app.services.ocr_client import run_ocr
from app.services.classification_client import run_classification

router = APIRouter()

# ── In-memory history store ───────────────────────────────────────────────
# Key: user_id -> list[HistoryItem]
_history: dict[int, list[dict]] = {}

# Supported file extensions (matching OCR pipeline)
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".heif",
    ".heic",
    ".docx",
    ".xlsx",
    ".pptx",
}

MAX_FILE_SIZE_MB = 50  # 50 MB upload limit


# ── POST /process ─────────────────────────────────────────────────────────
@router.post("/process", response_model=DocumentProcessResponse)
def process_document(
    file: UploadFile = File(...),
    skip_classification: bool = Query(False, description="Skip classification step"),
    user: ActiveUser = None,  # type: ignore
):
    """
    Upload a document, run OCR to extract text, then classify it.

    This endpoint is synchronous — FastAPI runs `def` endpoints in a
    threadpool automatically, so it won't block the event loop.
    Processing time depends on document size (typically 5-30 seconds).
    """

    # ── Validate file ─────────────────────────────────────────────────
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    ext = _get_extension(file.filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            ),
        )

    # Read file bytes
    file_bytes = file.file.read()
    file_size_mb = len(file_bytes) / (1024 * 1024)

    if file_size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large ({file_size_mb:.1f} MB). Maximum is {MAX_FILE_SIZE_MB} MB.",
        )

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # ── Run OCR ───────────────────────────────────────────────────────
    ocr_result = run_ocr(
        file_bytes=file_bytes,
        filename=file.filename,
        endpoint=settings.AZURE_DOC_INTELLIGENCE_ENDPOINT,
        api_key=settings.AZURE_DOC_INTELLIGENCE_KEY,
    )

    if not ocr_result.get("success"):
        return DocumentProcessResponse(
            success=False,
            error=ocr_result.get("error", "OCR processing failed"),
            filename=file.filename,
        )

    # ── Run Classification ────────────────────────────────────────────
    classification_info: Optional[ClassificationInfo] = None
    classification_cost = 0.0

    if not skip_classification:
        plain_text = ocr_result.get("plain_text", "")

        if plain_text.strip():
            cls_result = run_classification(
                plain_text=plain_text,
                api_key=settings.AZURE_OPENAI_API_KEY,
                endpoint=settings.AZURE_OPENAI_ENDPOINT,
                deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                api_version=settings.AZURE_OPENAI_API_VERSION,
            )

            classification_info = ClassificationInfo(
                category=cls_result["category"],
                confidence=cls_result["confidence"],
                reasoning=cls_result["reasoning"],
                tokens_used=cls_result.get("tokens_used", 0),
                cost_usd=cls_result.get("cost_usd", 0.0),
                error=cls_result.get("error"),
            )
            classification_cost = cls_result.get("cost_usd", 0.0)
        else:
            classification_info = ClassificationInfo(
                category="Uncertain",
                confidence=0.0,
                reasoning="No text extracted from document",
            )

    # ── Build per-page diagnostics ────────────────────────────────────
    per_page_raw = ocr_result.get("per_page", [])
    per_page = []
    for p in per_page_raw:
        per_page.append(
            PageDiagnostic(
                page_number=p.get("page_number", 0),
                status=p.get("status", "unknown"),
                words_count=p.get("words_count", 0),
                avg_confidence=p.get("avg_confidence", 0.0),
            )
        )

    # ── Cost breakdown ────────────────────────────────────────────────
    ocr_cost = ocr_result.get("cost_usd", 0.0)
    costs = CostBreakdown(
        ocr_cost_usd=round(ocr_cost, 6),
        classification_cost_usd=round(classification_cost, 6),
        total_cost_usd=round(ocr_cost + classification_cost, 6),
    )

    # ── Save to in-memory history ─────────────────────────────────────
    user_id = user.user_id if user else 0
    history_entry = {
        "id": str(uuid.uuid4()),
        "filename": file.filename,
        "category": classification_info.category if classification_info else "N/A",
        "confidence": classification_info.confidence if classification_info else 0.0,
        "page_count": ocr_result.get("page_count", 0),
        "word_count": ocr_result.get("word_count", 0),
        "primary_language": ocr_result.get("primary_language", "unknown"),
        "ocr_cost_usd": ocr_cost,
        "classification_cost_usd": classification_cost,
        "total_cost_usd": ocr_cost + classification_cost,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": ocr_result.get("elapsed_seconds", 0.0),
    }

    if user_id not in _history:
        _history[user_id] = []
    _history[user_id].insert(0, history_entry)  # newest first

    # ── Return response ───────────────────────────────────────────────
    return DocumentProcessResponse(
        success=True,
        filename=file.filename,
        extracted_text=ocr_result.get("cleaned_text", ""),
        cleaned_text=ocr_result.get("plain_text", ""),
        primary_language=ocr_result.get("primary_language", "unknown"),
        tables_markdown=ocr_result.get("tables_markdown", []),
        page_count=ocr_result.get("page_count", 0),
        word_count=ocr_result.get("word_count", 0),
        avg_confidence=ocr_result.get("avg_confidence", 0.0),
        ocr_elapsed_seconds=ocr_result.get("elapsed_seconds", 0.0),
        chunks_used=ocr_result.get("chunks_used", 1),
        quality=ocr_result.get("quality", {}),
        per_page=per_page,
        classification=classification_info,
        costs=costs,
    )


# ── GET /history ──────────────────────────────────────────────────────────
@router.get("/history", response_model=list[HistoryItem])
async def get_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: ActiveUser = None,  # type: ignore
):
    """Return the processing history for the current user."""
    user_id = user.user_id if user else 0
    items = _history.get(user_id, [])
    return [HistoryItem(**item) for item in items[skip : skip + limit]]


# ── GET /stats ────────────────────────────────────────────────────────────
@router.get("/stats", response_model=StatsResponse)
async def get_stats(user: ActiveUser = None):  # type: ignore
    """Return aggregate statistics from the current user's processing history."""
    user_id = user.user_id if user else 0
    items = _history.get(user_id, [])

    if not items:
        return StatsResponse()

    total_docs = len(items)
    total_pages = sum(i["page_count"] for i in items)
    total_words = sum(i["word_count"] for i in items)
    total_cost = sum(i["total_cost_usd"] for i in items)
    avg_conf = sum(i["confidence"] for i in items) / total_docs
    avg_time = sum(i["elapsed_seconds"] for i in items) / total_docs

    # Category distribution
    categories: dict[str, int] = {}
    for i in items:
        cat = i.get("category", "Unknown")
        categories[cat] = categories.get(cat, 0) + 1

    # Language distribution
    languages: dict[str, int] = {}
    for i in items:
        lang = i.get("primary_language", "unknown")
        languages[lang] = languages.get(lang, 0) + 1

    return StatsResponse(
        total_documents=total_docs,
        total_pages=total_pages,
        total_words=total_words,
        total_cost_usd=round(total_cost, 6),
        avg_confidence=round(avg_conf, 4),
        avg_processing_time=round(avg_time, 2),
        categories=categories,
        languages=languages,
    )


# ── Helper ────────────────────────────────────────────────────────────────
def _get_extension(filename: str) -> str:
    """Extract lowercase file extension."""
    import os

    return os.path.splitext(filename)[1].lower()
