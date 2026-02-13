from fastapi import Form
from pydantic import BaseModel, Field
from typing import Optional

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