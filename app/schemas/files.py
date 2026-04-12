"""
Pydantic schemas for the file storage endpoints.
"""

from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    """Response from ``POST /files/upload``."""

    document_id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str  # "uploaded"
