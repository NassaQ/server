from datetime import datetime

from fastapi import Form
from pydantic import BaseModel, Field
from typing import List, Optional

class FileMetadata(BaseModel):
    """Input Schema: Metadata sent alongside the file via Form Data."""
    description: Optional[str] = None
    full_path: str = ""

    @classmethod
    def as_form(
        cls,
        description: str = Form(None),
        full_path: str = Form("")
    ):
        """Helper to inject Form fields into the Pydantic model."""
        return cls(description=description, full_path=full_path)

class FileUploadResponse(BaseModel):
    """Returns the storage path and file details to the client."""

    filename: str = Field(..., description="Original name of the uploaded file")
    path: str = Field(..., description="Absolute path (Local) or URL (Azure) to access the file")
    ctype: str = Field(..., description="MIME type of the file (e.g., image/png)")
    size: int = Field(..., description="Size of the file in bytes")
    metadata: FileMetadata

class DocumentListItem(BaseModel):
    """Single document entry in a list response."""

    doc_id: int = Field(..., description="Document ID")
    filename: str = Field(..., description="Original filename")
    path: str = Field(..., description="Virtual path (e.g. '/finance' or '/')")
    uploaded_by_user_id: int = Field(..., description="ID of the user who uploaded the document")
    uploaded_at: datetime = Field(..., description="Upload timestamp")
    status: Optional[str] = Field(None, description="OCR processing status: Queued, Processing, Finished, or Failed",)
    error_message: Optional[str] = Field(None, description="Error details if status is Failed")


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    total: int = Field(..., description="Total number of matching documents")
    items: List[DocumentListItem] = Field(..., description="List of documents for the current page")
