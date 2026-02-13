from fastapi import APIRouter, UploadFile, status, HTTPException, File, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import ActiveUser, DBSession, get_storage
from app.core.storage import StorageBase
from app.models.models import Documents, VirtualPaths
from app.schemas.docs import FileUploadResponse, FileMetadata
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
) -> FileUploadResponse:
    """
    Uploads a file to the configured storage backend (Azure or Local).
    Returns the absolute path or URL.
    """

    path = metadata.full_path.strip("/") if metadata.full_path else ""
    clean_path = f"{path}/{file.filename}" if path else file.filename

    if not path:
        path = "/"

    query = select(VirtualPaths).where(VirtualPaths.full_path == path)
    path = (await db.execute(query)).scalar_one_or_none()

    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provided path doesn't exist."
        )

    try:
        if file.size and file.size > settings.MAX_SIZE_UPLOAD:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE, 
                detail=f"File too large, Max Limit is set to {settings.MAX_SIZE_UPLOAD // 1048576} MB"
            )

        content = await file.read()
        
        if len(content) > settings.MAX_SIZE_UPLOAD:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE, 
                detail=f"File too large, Max Limit is set to {settings.MAX_SIZE_UPLOAD // 1048576} MB"
            )

        result_path = await storage.upload(content, clean_path)

        new_doc = Documents(
            filename=file.filename,
            path_id=path.path_id,
            uploaded_by_user_id=current_user.user_id,
            mongo_doc_id="pending",
        )

        try:
            db.add(new_doc)
            await db.commit()
        
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Receiving doc failed. Please try again."
            )


        return FileUploadResponse(
            filename=file.filename,
            path=result_path,
            ctype=file.content_type,
            size=len(content),
            metadata=metadata
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Storage Error: {str(e)}"
        )