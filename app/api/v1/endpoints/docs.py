import os
from fastapi import APIRouter, UploadFile, status, HTTPException, File, Form, Depends

from app.api.deps import get_storage
from app.core.storage import StorageBase
from app.schemas.docs import FileUploadResponse, FileMetadata

router = APIRouter()

@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED, summary="upload file to process",
             description="Accepts a file and metadata, then saves it to the configured storage (until now)")
async def upload_file(
    file: UploadFile = File(..., description="The actual file to be uploaded"),
    metadata: FileMetadata = Depends(FileMetadata.as_form),
    storage: StorageBase = Depends(get_storage)
) -> FileUploadResponse:
    """
    Uploads a file to the configured storage backend (Azure or Local).
    Returns the absolute path or URL.
    """

    try:
        content = await file.read()
        path = os.path.join(metadata.folder, file.filename)
        
        result_path = await storage.upload(content, path)
        
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
            detail=str(e)
        )