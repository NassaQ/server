from typing import Annotated, Literal

from fastapi import APIRouter, Query, UploadFile, status, HTTPException, File, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import ActiveUser, AdminUser, DBSession, get_event_broker, get_storage, doc_to_list_item
from app.core.broker import BaseBroker
from app.core.storage import StorageBase
from app.models.models import Documents, VirtualPaths, ProcessingStatus
from app.schemas.docs import FileUploadResponse, FileMetadata, DocumentListResponse
from app.core.config import settings

router = APIRouter()

@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED, summary="Upload file to process",
             description="Accepts a file and metadata, then saves it to the configured storage (until now)")
async def upload_file(
    db: DBSession,
    current_user: ActiveUser,
    file: UploadFile = File(..., description="The actual file to be uploaded"),
    metadata: FileMetadata = Depends(FileMetadata.as_form),
    storage: StorageBase = Depends(get_storage),
    broker: BaseBroker = Depends(get_event_broker)
) -> FileUploadResponse:
    """
    Uploads a file to the configured storage backend (Azure or Local).
    Returns the absolute path or URL.
    """

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

    if len(content) > settings.MAX_SIZE_UPLOAD:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large, Max Limit is set to {settings.MAX_SIZE_UPLOAD // 1048576} MB",
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
        await broker.publish("ocr_queue", message_payload)
        
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


