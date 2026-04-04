import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Query, UploadFile, status, HTTPException, File, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.api.deps import ActiveUser, AdminUser, DBSession, get_event_broker, get_storage, doc_to_list_item
from app.core.broker import BaseBroker
from app.core.storage import StorageBase
from app.models.models import Documents, VirtualPaths, ProcessingStatus
from app.schemas.docs import DocumentDeleteResponse, DocumentStatusResponse, FileUploadResponse, FileMetadata, DocumentListResponse
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
from app.core.config import settings

router = APIRouter()

# Key: user_id -> list[HistoryItem]
_history: dict[int, list[dict]] = {}


# ── Async pipeline (storage + queue → ocr-api) ───────────────────────────

@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED, summary="Upload file to process",
             description="Accepts a file and metadata, then saves it to the configured storage and queues it for OCR processing.")
async def upload_file(
    db: DBSession,
    current_user: ActiveUser,
    file: UploadFile = File(..., description="The actual file to be uploaded"),
    metadata: FileMetadata = Depends(FileMetadata.as_form),
    storage: StorageBase = Depends(get_storage),
    broker: BaseBroker = Depends(get_event_broker)
) -> FileUploadResponse:
    raw_path = metadata.full_path.strip("/") if metadata.full_path else ""
    lookup_path = raw_path if raw_path else "/"

    query = select(VirtualPaths).where(VirtualPaths.full_path == lookup_path)
    vpath = (await db.execute(query)).scalar_one_or_none()

    if not vpath:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provided path doesn't exist."
        )

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large, Max Limit is set to {settings.MAX_UPLOAD_SIZE_MB} MB",
        )
    
    clean_path = f"{raw_path}/{file.filename}" if raw_path else file.filename
    
    try:
        blob_url = await storage.upload(content, clean_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage upload failed: {str(e)}",
        )
    
    new_doc = Documents(
        filename=file.filename,
        path_id=vpath.path_id,
        uploaded_by_user_id=current_user.user_id,
        mongo_doc_id="pending",
    )
    
    try:
        db.add(new_doc)
        await db.flush()

        processing_status = ProcessingStatus(
            doc_id=new_doc.doc_id,
            stage_name="OCR",
            status="Queued",
        )
        db.add(processing_status)
        await db.flush()
        
        message_payload = {
            "doc_id": new_doc.doc_id,
            "file_path": blob_url,
            "filename": new_doc.filename,
            "user_id": current_user.user_id,
        }
        await broker.publish(settings.OCR_QUEUE_NAME, message_payload)
        
        await db.commit()
        await db.refresh(new_doc)
    
    except IntegrityError:
        await db.rollback()
        await storage.delete(clean_path) 
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A document with this filename already exists at the specified path.",
        )
    except Exception as e:
        await db.rollback()
        await storage.delete(clean_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process document: {str(e)}",
        )

    return FileUploadResponse(
        filename=file.filename,
        path=blob_url,
        ctype=file.content_type,
        size=len(content),
        metadata=metadata
    )


# ── Sync pipeline (ai-foundry OCR + classification) ──────────────────────

@router.post("/process", response_model=DocumentProcessResponse,
             summary="Process document synchronously",
             description="Upload a document, run OCR via AI Foundry to extract text, then classify it. Returns results immediately.")
def process_document(
    file: UploadFile = File(...),
    skip_classification: bool = Query(False, description="Skip classification step"),
    user: ActiveUser = None,  # type: ignore
):
    """
    Synchronous pipeline — FastAPI runs `def` endpoints in a threadpool
    automatically, so it won't block the event loop.
    """

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    ext = _get_extension(file.filename)
    if ext not in settings.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Supported: {', '.join(sorted(settings.SUPPORTED_EXTENSIONS))}"
            ),
        )

    file_bytes = file.file.read()
    file_size_mb = len(file_bytes) / (1024 * 1024)

    if file_size_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large ({file_size_mb:.1f} MB). Maximum is {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

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

    per_page_raw = ocr_result.get("per_page", [])
    per_page = [
        PageDiagnostic(
            page_number=p.get("page_number", 0),
            status=p.get("status", "unknown"),
            words_count=p.get("words_count", 0),
            avg_confidence=p.get("avg_confidence", 0.0),
        )
        for p in per_page_raw
    ]

    ocr_cost = ocr_result.get("cost_usd", 0.0)
    costs = CostBreakdown(
        ocr_cost_usd=round(ocr_cost, 6),
        classification_cost_usd=round(classification_cost, 6),
        total_cost_usd=round(ocr_cost + classification_cost, 6),
    )

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
    _history[user_id].insert(0, history_entry)

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


# ── Document listing & status ─────────────────────────────────────────────

@router.get("/", response_model=DocumentListResponse, summary="List all documents (admin)",
            description="Returns a paginated list of all documents. Supports filtering by user_id.")
async def list_all_docs(
    db: DBSession,
    current_user: AdminUser,
    skip: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records to return")] = 20,
    status: Annotated[Literal["Finished", "Failed", "Processing", "Queued"] | None, Query(description="Filter by status")] = None,
    user_id: int | None = None,
) -> DocumentListResponse:

    conditions = []
    if user_id:
        conditions.append(Documents.uploaded_by_user_id == user_id)
    if status:
        conditions.append(
            Documents.Processing_Status.any(
                (ProcessingStatus.status == status) & 
                (ProcessingStatus.stage_name == "OCR")
            )
        )

    query = select(func.count(Documents.doc_id))
    for cond in conditions:
        query = query.where(cond)
    
    total = (await db.execute(query)).scalar_one()

    query = (
        select(Documents)
        .options(
            selectinload(Documents.Processing_Status),
            selectinload(Documents.path),
        )
        .order_by(Documents.uploaded_at.desc())
        .offset(skip)
        .limit(limit)
    )

    for cond in conditions:
        query = query.where(cond)

    docs = (await db.execute(query)).scalars().all()

    return DocumentListResponse(
        total=total,
        items=[doc_to_list_item(doc) for doc in docs],
    )

@router.get("/me", response_model=DocumentListResponse, summary="List my documents",
            description="Returns a paginated list of the current user's documents.")
async def list_my_docs(
    db: DBSession,
    current_user: ActiveUser,
    skip: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records to return")] = 20,
    status: Annotated[Literal["Finished", "Failed", "Processing", "Queued"] | None, Query(description="Filter by status")] = None,
) -> DocumentListResponse:
    
    conditions = []
    conditions.append(Documents.uploaded_by_user_id == current_user.user_id)
    if status:
        conditions.append(
            Documents.Processing_Status.any(
                (ProcessingStatus.status == status) & 
                (ProcessingStatus.stage_name == "OCR")
            )
        )

    query = select(func.count(Documents.doc_id))
    for cond in conditions:
        query = query.where(cond)
    
    total = (await db.execute(query)).scalar_one()

    query = (
        select(Documents)
        .options(
            selectinload(Documents.Processing_Status),
            selectinload(Documents.path),
        )
        .order_by(Documents.uploaded_at.desc())
        .offset(skip)
        .limit(limit)
    )

    for cond in conditions:
        query = query.where(cond)

    docs = (await db.execute(query)).scalars().all()

    return DocumentListResponse(
        total=total,
        items=[doc_to_list_item(doc) for doc in docs],
    )

@router.get("/history", response_model=list[HistoryItem],
            summary="Processing history",
            description="Returns the in-memory processing history for the current user (sync pipeline).")
async def get_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: ActiveUser = None,  # type: ignore
):
    user_id = user.user_id if user else 0
    items = _history.get(user_id, [])
    return [HistoryItem(**item) for item in items[skip : skip + limit]]

@router.get("/stats", response_model=StatsResponse,
            summary="Processing statistics",
            description="Returns aggregate statistics from the current user's sync processing history.")
async def get_stats(user: ActiveUser = None):  # type: ignore
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

    categories: dict[str, int] = {}
    for i in items:
        cat = i.get("category", "Unknown")
        categories[cat] = categories.get(cat, 0) + 1

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

@router.get("/{doc_id}/status", response_model=DocumentStatusResponse, summary="Check document processing status",
            description="Returns the current OCR processing status for a document.")
async def get_doc_status(
    doc_id: int,
    db: DBSession,
    current_user: ActiveUser,
) -> DocumentStatusResponse:
    
    query = (
        select(Documents, ProcessingStatus)
        .outerjoin(
            ProcessingStatus, 
            (Documents.doc_id == ProcessingStatus.doc_id) & (ProcessingStatus.stage_name == "OCR")
        )
        .where(
            Documents.doc_id == doc_id,
            Documents.uploaded_by_user_id == current_user.user_id
        )
    )
    result = (await db.execute(query)).first()

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id {doc_id} not found.",
        )
    
    doc, ps = result

    return DocumentStatusResponse(
        doc_id=doc.doc_id,
        filename=doc.filename,
        stage_name=ps.stage_name,
        status=ps.status,
        start_time=ps.start_time,
        end_time=ps.end_time,
        error_message=ps.error_message,
    )

@router.delete("/{doc_id}", response_model=DocumentDeleteResponse, summary="Delete a document (admin)",
               description="Deletes a document's database records and its blob from storage. Blocked if the document is currently being processed. Admin only.")
async def delete_document(
    doc_id: int,
    db: DBSession,
    current_user: AdminUser,
    storage: StorageBase = Depends(get_storage),
) -> DocumentDeleteResponse:

    query = (
        select(Documents)
        .options(joinedload(Documents.path))
        .where(Documents.doc_id == doc_id)
    )
    doc = (await db.execute(query)).scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id {doc_id} not found.",
        )

    active_status_query = select(ProcessingStatus.status).where(
        ProcessingStatus.doc_id == doc_id,
        ProcessingStatus.status.in_(["Queued", "Processing"])
    )
    active_status = (await db.execute(active_status_query)).scalar_one_or_none()

    if active_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete document while it is '{active_status}'. Wait for processing to complete or fail.",
        )

    raw_path = doc.path.full_path.strip("/") if doc.path and doc.path.full_path else ""
    blob_path = f"{raw_path}/{doc.filename}" if raw_path else doc.filename

    try:
        await db.execute(delete(ProcessingStatus).where(ProcessingStatus.doc_id == doc_id))
        
        await db.delete(doc)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Delete failed. Please try again."
        )

    try:
        await storage.delete(blob_path)
    except Exception:
        pass

    return DocumentDeleteResponse(
        doc_id=doc_id,
        message="Document deleted successfully.",
    )


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()
