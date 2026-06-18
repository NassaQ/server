"""
Document processing endpoints — synchronous OCR + classification workflow.
Mounted at /api/v1/documents/...
"""

import logging
import os as _os
import time
import uuid

from fastapi import APIRouter, File, Query, UploadFile, HTTPException, status, Depends
from sqlalchemy import select

from app.api.deps import ActiveUser, DBSession, LogRepo
from app.db.cosmos import cosmos
from app.models.models import Documents, ProcessingStatus, OcrResult, VirtualPaths
from app.services import file_storage
from app.services.ocr_client import get_ocr_client
from app.services.classifier import get_classifier

logger = logging.getLogger(__name__)
from app.schemas.process import (
    ProcessResponse,
    PageDiagnosticSchema,
    ClassificationInfoSchema,
    CostBreakdownSchema,
    HistoryItemSchema,
    StatsResponseSchema,
)

router = APIRouter()


@router.post("/process", response_model=ProcessResponse, summary="Process a document")
async def process_document(
    db: DBSession,
    log_repo: LogRepo,
    current_user: ActiveUser,
    file: UploadFile = File(...),
    skip_classification: bool = False,
):
    """Upload a file for synchronous OCR text extraction and AI classification.

    Steps:
    1. OCR via Azure Document Intelligence
    2. Classification via Azure OpenAI GPT-4.1-mini
    3. Returns combined result
    """
    # Validate file extension
    allowed_exts = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".docx", ".xlsx", ".pptx"}
    ext = "." + (file.filename or "").split(".")[-1].lower() if file.filename else ""
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(allowed_exts))}",
        )

    # Read file
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 50 MB.",
        )

    # Upload original file to blob storage (for "View Original")
    document_id = str(uuid.uuid4())
    try:
        file_storage.upload(
            document_id=document_id,
            file_bytes=content,
            filename=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
        )
    except Exception as exc:
        logger.warning("Failed to upload original file to blob storage: %s", exc)

    # Step 1: OCR
    ocr_client = get_ocr_client()
    ocr_result = ocr_client.process_bytes(content, filename=file.filename or "upload")

    if not ocr_result.success:
        return ProcessResponse(
            success=False,
            error=ocr_result.error or "OCR processing failed",
            filename=file.filename or "",
        )

    # Step 2: Classification
    classification = None
    class_cost = 0.0
    if not skip_classification and ocr_result.cleaned_text:
        try:
            classifier = get_classifier()
            class_result = classifier.classify(ocr_result.cleaned_text)
            classification = ClassificationInfoSchema(
                domain=class_result.domain,
                category=class_result.category,
                confidence=class_result.confidence,
                reasoning=class_result.reasoning,
                tokens_used=class_result.tokens_used,
                cost_usd=class_result.cost_usd,
                error=class_result.error,
            )
            class_cost = class_result.cost_usd if not class_result.error else 0.0
        except Exception as e:
            classification = ClassificationInfoSchema(
                domain="Error",
                category="Error",
                confidence=0.0,
                reasoning="",
                error=str(e),
            )

    # Build response
    total_cost = round(ocr_result.cost_usd + class_cost, 6)
    response = ProcessResponse(
        success=True,
        filename=file.filename or "upload",
        document_id=document_id,
        extracted_text=ocr_result.text,
        cleaned_text=ocr_result.cleaned_text,
        primary_language=ocr_result.primary_language,
        tables_markdown=ocr_result.tables_markdown,
        page_count=ocr_result.page_count,
        word_count=ocr_result.word_count,
        avg_confidence=ocr_result.avg_confidence,
        ocr_elapsed_seconds=ocr_result.elapsed_seconds,
        chunks_used=ocr_result.chunks_used,
        quality=ocr_result.quality,
        per_page=[PageDiagnosticSchema(**p) for p in ocr_result.per_page],
        classification=classification,
        costs=CostBreakdownSchema(
            ocr_cost_usd=ocr_result.cost_usd,
            classification_cost_usd=class_cost,
            total_cost_usd=total_cost,
        ),
    )

    # ── Persist to SQL Server + Cosmos DB ─────────────────────────────────
    try:
        # 1. Find or create root virtual path
        root_path = (
            await db.execute(select(VirtualPaths).where(VirtualPaths.full_path == "/"))
        ).scalar_one_or_none()
        if not root_path:
            root_path = VirtualPaths(full_path="/", depth=0)
            db.add(root_path)
            await db.flush()

        # 2. Create Documents record
        _, ext = _os.path.splitext(file.filename or "upload")
        new_doc = Documents(
            filename=file.filename or "upload",
            path_id=root_path.path_id,
            uploaded_by_user_id=current_user.user_id,
            mongo_doc_id=document_id,
            file_size=len(content),
            content_type=file.content_type,
            file_type=ext.lower() if ext else None,
        )
        db.add(new_doc)
        await db.flush()

        # 3. Create ProcessingStatus records
        ocr_status = class_status_text = "Finished"
        if not ocr_result.success:
            ocr_status = "Failed"
        if classification and classification.error:
            class_status_text = "Failed"

        for stage_name, status_text in [
            ("OCR", ocr_status),
            ("Classification", class_status_text),
            ("Vectorization", "Finished"),
        ]:
            ps = ProcessingStatus(
                doc_id=new_doc.doc_id,
                stage_name=stage_name,
                status=status_text,
            )
            db.add(ps)

        # 4. Create OcrResult record
        domain = classification.domain if classification else None
        category = classification.category if classification else None
        class_conf = classification.confidence if classification else None
        class_err_cost = classification.cost_usd if classification and not classification.error else None
        ocr_result_record = OcrResult(
            doc_id=new_doc.doc_id,
            page_count=ocr_result.page_count,
            word_count=ocr_result.word_count,
            avg_confidence=ocr_result.avg_confidence,
            primary_language=ocr_result.primary_language,
            domain=domain,
            category=category,
            classification_confidence=class_conf,
            cost_usd_ocr=ocr_result.cost_usd,
            cost_usd_classification=class_err_cost,
        )
        db.add(ocr_result_record)
        await db.commit()

        # 5. Save to Cosmos DB (for cross-service visibility)
        if cosmos.connected:
            try:
                cosmos_doc = {
                    "doc_id": new_doc.doc_id,
                    "document_id": document_id,
                    "filename": file.filename or "upload",
                    "file_type": ext.lower() if ext else None,
                    "page_count": ocr_result.page_count,
                    "word_count": ocr_result.word_count,
                    "avg_confidence": ocr_result.avg_confidence,
                    "primary_language": ocr_result.primary_language,
                    "domain": domain,
                    "category": category,
                    "classification_confidence": class_conf,
                    "cost_usd_ocr": ocr_result.cost_usd,
                    "cost_usd_classification": class_err_cost or 0.0,
                    "cleaned_text": ocr_result.cleaned_text[:50000] if ocr_result.cleaned_text else "",
                    "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                await cosmos._collection.insert_one(cosmos_doc)
            except Exception:
                pass  # Cosmos save is non-critical

        # 6. Write audit log
        await log_repo.write_log(
            action_type="process_document",
            user_id=current_user.user_id,
            entity_id=new_doc.doc_id,
            details=f"Processed {file.filename}: OCR={ocr_result.page_count}p, class={category or 'N/A'}",
        )
    except Exception as e:
        await db.rollback()
        # Non-fatal: error during persistence doesn't break the response

    return response


@router.get("/history", response_model=list[HistoryItemSchema], summary="Get processing history")
async def list_history(
    db: DBSession,
    current_user: ActiveUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
):
    """Return processing history for the current user — always from DB."""
    query = (
        select(Documents, OcrResult)
        .outerjoin(OcrResult, Documents.doc_id == OcrResult.doc_id)
        .where(Documents.uploaded_by_user_id == current_user.user_id)
        .order_by(Documents.uploaded_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = (await db.execute(query)).all()
    items = []
    for doc, ocr in rows:
        items.append(HistoryItemSchema(
            id=str(doc.mongo_doc_id) if doc.mongo_doc_id else str(uuid.uuid4()),
            doc_id=doc.doc_id,
            document_id=str(doc.mongo_doc_id) if doc.mongo_doc_id else "",
            filename=doc.filename,
            domain=(ocr.domain if ocr and ocr.domain else ""),
            category=(ocr.category if ocr and ocr.category else "Unknown"),
            confidence=(ocr.classification_confidence if ocr and ocr.classification_confidence is not None else 0.0),
            page_count=ocr.page_count if ocr else 0,
            word_count=ocr.word_count if ocr else 0,
            primary_language=ocr.primary_language if ocr else "unknown",
            ocr_cost_usd=(ocr.cost_usd_ocr if ocr and ocr.cost_usd_ocr is not None else 0.0),
            classification_cost_usd=(ocr.cost_usd_classification if ocr and ocr.cost_usd_classification is not None else 0.0),
            total_cost_usd=((ocr.cost_usd_ocr or 0.0) + (ocr.cost_usd_classification or 0.0)) if ocr else 0.0,
            processed_at=ocr.processed_at.strftime("%Y-%m-%dT%H:%M:%SZ") if ocr and ocr.processed_at else doc.uploaded_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            elapsed_seconds=0.0,
        ))
    return items


@router.get("/stats", response_model=StatsResponseSchema, summary="Get processing stats")
async def get_stats(
    db: DBSession,
    current_user: ActiveUser,
):
    """Return aggregate statistics for the current user — always from DB."""
    query = (
        select(OcrResult)
        .join(Documents, Documents.doc_id == OcrResult.doc_id)
        .where(Documents.uploaded_by_user_id == current_user.user_id)
    )
    rows = (await db.execute(query)).scalars().all()

    if not rows:
        return StatsResponseSchema(
            total_documents=0,
            total_pages=0,
            total_words=0,
            total_cost_usd=0.0,
            avg_confidence=0.0,
            avg_processing_time=0.0,
            domains={},
            categories={},
            languages={},
        )

    total_docs = len(set(r.doc_id for r in rows))
    total_pages = sum(r.page_count for r in rows)
    total_words = sum(r.word_count for r in rows)
    total_cost = sum(r.cost_usd_ocr + (r.cost_usd_classification or 0.0) for r in rows)

    confidences = [r.classification_confidence for r in rows if r.classification_confidence and r.classification_confidence > 0]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    domains: dict[str, int] = {}
    categories: dict[str, int] = {}
    languages: dict[str, int] = {}
    for r in rows:
        if r.domain:
            domains[r.domain] = domains.get(r.domain, 0) + 1
        if r.category:
            categories[r.category] = categories.get(r.category, 0) + 1
        if r.primary_language:
            languages[r.primary_language] = languages.get(r.primary_language, 0) + 1

    return StatsResponseSchema(
        total_documents=total_docs,
        total_pages=total_pages,
        total_words=total_words,
        total_cost_usd=round(total_cost, 6),
        avg_confidence=round(avg_conf, 4),
        avg_processing_time=0.0,
        domains=domains,
        categories=categories,
        languages=languages,
    )
