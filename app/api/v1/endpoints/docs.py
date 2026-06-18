import asyncio
from typing import Annotated, Literal
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Query, UploadFile, status, HTTPException, File, Depends
from sqlalchemy import select, update as sql_update

from app.api.deps import ActiveUser, AdminUser, DocRepo, LogRepo, OcrResultRepo, PathRepo, get_event_broker, get_storage, doc_to_list_item
from app.core.broker import BaseBroker
from app.core.storage import StorageBase
from app.db.cosmos import cosmos
from app.db.session import get_db, AsyncSessionLocal
import logging
from app.models.models import Documents, ProcessingStatus, OcrResult

logger = logging.getLogger(__name__)
from app.schemas.docs import DocumentDeleteResponse, DocumentStatusResponse, FileUploadResponse, FileMetadata, DocumentListResponse, StageStatus, OcrResultResponse, MoveDocumentRequest, MoveDocumentResponse
from app.core.config import settings
from app.services import rag
from app.services import file_storage

router = APIRouter()


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED, summary="Upload file to process",
    description="Accepts a file and metadata, then saves it to the configured storage and queues it for processing.")
async def upload_file(
    doc_repo: DocRepo,
    path_repo: PathRepo,
    log_repo: LogRepo,
    current_user: ActiveUser,
    file: UploadFile = File(..., description="The actual file to be uploaded"),
    metadata: FileMetadata = Depends(FileMetadata.as_form),
    storage: StorageBase = Depends(get_storage),
    broker: BaseBroker = Depends(get_event_broker)
) -> FileUploadResponse:
    raw_path = metadata.full_path.strip("/") if metadata.full_path else ""
    lookup_path = raw_path if raw_path else "/"

    vpath = await path_repo.get_path_by_full_path(lookup_path)
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

    import os as _os
    _, ext = _os.splitext(file.filename)

    new_doc = Documents(
        filename=file.filename,
        path_id=vpath.path_id,
        uploaded_by_user_id=current_user.user_id,
        mongo_doc_id="pending",
        file_size=len(content),
        content_type=file.content_type,
        file_type=ext.lower() if ext else None,
    )
    processing_statuses = [
        ProcessingStatus(stage_name="OCR", status="Queued"),
        ProcessingStatus(stage_name="Classification", status="Queued"),
        ProcessingStatus(stage_name="Vectorization", status="Queued"),
    ]

    try:
        await doc_repo.create_document(new_doc, processing_statuses)

        message_payload = {
            "doc_id": new_doc.doc_id,
            "file_path": blob_url,
            "filename": new_doc.filename,
            "user_id": current_user.user_id,
        }
        queue_name = (
            settings.AI_FOUNDRY_QUEUE_NAME
            if settings.PROCESSING_BACKEND == "ai_foundry"
            else settings.OCR_QUEUE_NAME
        )
        await broker.publish(queue_name, message_payload)

        await doc_repo.commit_and_refresh(new_doc)

    except ValueError as e:
        await storage.delete(clean_path)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as e:
        await doc_repo.rollback()
        await storage.delete(clean_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process document: {str(e)}",
        )

    await log_repo.write_log(
        action_type="document_upload",
        user_id=current_user.user_id,
        entity_id=new_doc.doc_id,
        details=f"Uploaded {file.filename} to {lookup_path}",
    )

    return FileUploadResponse(
        filename=file.filename,
        path=blob_url,
        ctype=file.content_type,
        size=len(content),
        metadata=metadata
    )


@router.get("/", response_model=DocumentListResponse, summary="List all documents (admin)",
    description="Returns a paginated list of all documents. Supports filtering by user_id.")
async def list_all_docs(
    doc_repo: DocRepo,
    current_user: AdminUser,
    skip: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records to return")] = 20,
    status: Annotated[Literal["Finished", "Failed", "Processing", "Queued"] | None, Query(description="Filter by status")] = None,
    user_id: int | None = None,
) -> DocumentListResponse:
    total, docs = await doc_repo.get_documents(
        skip=skip, limit=limit, status_filter=status, user_id=user_id
    )
    return DocumentListResponse(
        total=total,
        items=[doc_to_list_item(doc) for doc in docs],
    )


@router.get("/me", response_model=DocumentListResponse, summary="List my documents",
    description="Returns a paginated list of the current user's documents.")
async def list_my_docs(
    doc_repo: DocRepo,
    current_user: ActiveUser,
    skip: Annotated[int, Query(ge=0, description="Number of records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records to return")] = 20,
    status: Annotated[Literal["Finished", "Failed", "Processing", "Queued"] | None, Query(description="Filter by status")] = None,
) -> DocumentListResponse:
    total, docs = await doc_repo.get_documents(
        skip=skip, limit=limit, status_filter=status, user_id=current_user.user_id
    )
    return DocumentListResponse(
        total=total,
        items=[doc_to_list_item(doc) for doc in docs],
    )


@router.get("/{doc_id}/status", response_model=DocumentStatusResponse, summary="Check document processing status",
    description="Returns the processing status for all stages of a document.")
async def get_doc_status(
    doc_id: int,
    doc_repo: DocRepo,
    current_user: ActiveUser,
) -> DocumentStatusResponse:
    results = await doc_repo.get_document_status(doc_id, user_id=current_user.user_id)

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id {doc_id} not found.",
        )

    doc = results[0][0]
    stages = []
    seen_stages = set()
    for row_doc, ps in results:
        if ps and ps.stage_name not in seen_stages:
            stages.append(StageStatus(
                stage_name=ps.stage_name,
                status=ps.status,
                start_time=ps.start_time,
                end_time=ps.end_time,
                error_message=ps.error_message,
            ))
            seen_stages.add(ps.stage_name)

    return DocumentStatusResponse(
        doc_id=doc.doc_id,
        filename=doc.filename,
        stages=stages,
    )


@router.get("/{doc_id}/ocr-result", response_model=OcrResultResponse, summary="Get OCR result details",
    description="Returns OCR processing details for a document including page count, word count, confidence, and cost.")
async def get_doc_ocr_result(
    doc_id: int,
    doc_repo: DocRepo,
    ocr_result_repo: OcrResultRepo,
    current_user: ActiveUser,
) -> OcrResultResponse:
    doc = await doc_repo.get_document(doc_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id {doc_id} not found.",
        )

    if doc.uploaded_by_user_id != current_user.user_id and current_user.role_id != 99:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this document's OCR results.",
        )

    ocr_result = await ocr_result_repo.get_by_doc_id(doc_id)
    if not ocr_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OCR result not found for document {doc_id}. Processing may not be complete yet.",
        )

    return OcrResultResponse(
        result_id=ocr_result.result_id,
        doc_id=ocr_result.doc_id,
        page_count=ocr_result.page_count,
        word_count=ocr_result.word_count,
        avg_confidence=ocr_result.avg_confidence,
        primary_language=ocr_result.primary_language,
        domain=ocr_result.domain,
        category=ocr_result.category,
        classification_confidence=ocr_result.classification_confidence,
        cost_usd_ocr=ocr_result.cost_usd_ocr,
        cost_usd_classification=ocr_result.cost_usd_classification,
        processed_at=ocr_result.processed_at,
    )


@router.delete("/{doc_id}", response_model=DocumentDeleteResponse, summary="Delete a document",
    description="Deletes a document's database records, blob, MongoDB document, and vector store entries. Blocked if the document is currently being processed. Document owners and admins can delete.")
async def delete_document(
    doc_id: int,
    doc_repo: DocRepo,
    log_repo: LogRepo,
    current_user: ActiveUser,
) -> DocumentDeleteResponse:
    doc = await doc_repo.get_document(doc_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id {doc_id} not found.",
        )

    # Allow if user is an admin OR the document owner
    is_admin = current_user.role_id == 99
    is_owner = doc.uploaded_by_user_id == current_user.user_id
    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this document.",
        )

    active_status = await doc_repo.get_active_status(doc_id)
    if active_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete document while it is '{active_status}'. Wait for processing to complete or fail.",
        )

    mongo_doc_id = doc.mongo_doc_id

    try:
        await doc_repo.delete_document(doc)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # ── Delete blob from file_storage (UUID-keyed) ─────────────────
    if mongo_doc_id and mongo_doc_id != "pending":
        try:
            await asyncio.to_thread(file_storage.delete, mongo_doc_id)
        except Exception:
            pass

        try:
            await asyncio.to_thread(rag.remove_document, mongo_doc_id)
        except Exception:
            pass

    if cosmos.connected:
        try:
            await cosmos.delete_by_doc_id(doc_id)
        except Exception:
            pass

    await log_repo.write_log(
        action_type="document_delete",
        user_id=current_user.user_id,
        entity_id=doc_id,
        details=f"Deleted document {doc.filename}",
    )

    return DocumentDeleteResponse(
        doc_id=doc_id,
        message="Document deleted successfully.",
    )


@router.patch("/{doc_id}/move", response_model=MoveDocumentResponse, summary="Move a document to a different category folder",
    description="Reorganises a document into a new category folder: updates Cosmos DB & SQL metadata.")
async def move_document(
    doc_id: int,
    body: MoveDocumentRequest,
    doc_repo: DocRepo,
    log_repo: LogRepo,
    current_user: ActiveUser,
):
    """
    Move a document to a new classification folder.

    Since files are stored keyed by UUID (not by path), no blob copy
    is needed — we only update the domain and category metadata in Cosmos DB and
    the SQL Ocr_Results table.

    Steps:
      1. Look up the document in SQL.
      2. Update ``domain`` and ``category`` in the SQL ``Ocr_Results`` table.
      3. Update Cosmos DB domain and category.
      4. Log the action.
    """
    # ── 1. Fetch document ──────────────────────────────────────────────
    doc = await doc_repo.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    filename = doc.filename
    new_domain = body.new_domain.strip()
    new_category = body.new_category.strip()

    # ── 2. Update SQL Ocr_Results domain & category ───────────────────
    try:
        async with AsyncSessionLocal() as session:
            stmt = (
                sql_update(OcrResult)
                .where(OcrResult.doc_id == doc_id)
                .values(domain=new_domain, category=new_category)
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as exc:
        logger.error(f"Failed to update Ocr_Results for doc_id={doc_id}: {exc}")

    # ── 3. Update Cosmos DB domain & category ──────────────────────────
    if doc.mongo_doc_id and doc.mongo_doc_id != "pending":
        try:
            cosmos_doc = cosmos.find_by_doc_id(doc_id)
            if cosmos_doc:
                if cosmos_doc.get("classification"):
                    cosmos_doc["classification"]["domain"] = new_domain
                    cosmos_doc["classification"]["category"] = new_category
                else:
                    cosmos_doc["classification"] = {"domain": new_domain, "category": new_category}
                await cosmos.upsert_ocr_result(cosmos_doc)
        except Exception as exc:
            logger.error(f"Failed to update Cosmos DB for doc_id={doc_id}: {exc}")

    # ── 4. Log ────────────────────────────────────────────────────────
    await log_repo.write_log(
        action_type="document_move",
        user_id=current_user.user_id,
        entity_id=doc_id,
        details=f"Moved {filename} to domain '{new_domain}' category '{new_category}'",
    )

    return MoveDocumentResponse(
        doc_id=doc_id,
        filename=filename,
        old_path="",
        new_path="",
        new_domain=new_domain,
        new_category=new_category,
        message=f"Document moved to {new_domain} > {new_category}",
    )
