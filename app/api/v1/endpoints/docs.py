from typing import Annotated, Literal

from fastapi import APIRouter, Query, UploadFile, status, HTTPException, File, Depends

from app.api.deps import ActiveUser, AdminUser, DocRepo, PathRepo, get_event_broker, get_storage, doc_to_list_item
from app.core.broker import BaseBroker
from app.core.storage import StorageBase
from app.models.models import Documents, ProcessingStatus
from app.schemas.docs import DocumentDeleteResponse, DocumentStatusResponse, FileUploadResponse, FileMetadata, DocumentListResponse
from app.core.config import settings

router = APIRouter()


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED, summary="Upload file to process",
             description="Accepts a file and metadata, then saves it to the configured storage and queues it for processing.")
async def upload_file(
    doc_repo: DocRepo,
    path_repo: PathRepo,
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

    new_doc = Documents(
        filename=file.filename,
        path_id=vpath.path_id,
        uploaded_by_user_id=current_user.user_id,
        mongo_doc_id="pending",
    )
    processing_status = ProcessingStatus(stage_name="OCR", status="Queued")

    try:
        await doc_repo.create_document(new_doc, processing_status)

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
            description="Returns the current OCR processing status for a document.")
async def get_doc_status(
    doc_id: int,
    doc_repo: DocRepo,
    current_user: ActiveUser,
) -> DocumentStatusResponse:
    result = await doc_repo.get_document_status(doc_id, user_id=current_user.user_id)

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
    doc_repo: DocRepo,
    current_user: AdminUser,
    storage: StorageBase = Depends(get_storage),
) -> DocumentDeleteResponse:
    doc = await doc_repo.get_document(doc_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id {doc_id} not found.",
        )

    active_status = await doc_repo.get_active_status(doc_id)
    if active_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete document while it is '{active_status}'. Wait for processing to complete or fail.",
        )

    raw_path = doc.path.full_path.strip("/") if doc.path and doc.path.full_path else ""
    blob_path = f"{raw_path}/{doc.filename}" if raw_path else doc.filename

    try:
        await doc_repo.delete_document(doc)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    try:
        await storage.delete(blob_path)
    except Exception:
        pass

    return DocumentDeleteResponse(
        doc_id=doc_id,
        message="Document deleted successfully.",
    )
