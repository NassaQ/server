"""
File storage endpoints — upload & download original files via Azure Blob Storage.

POST /upload          — Upload original file (multipart: file + document_id)
GET  /{document_id}   — Download / stream original file
"""

import logging

from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Query, status
from fastapi.responses import Response

from app.api.deps import ActiveUser
from app.schemas.files import FileUploadResponse
from app.services import file_storage

logger = logging.getLogger(__name__)

router = APIRouter()


# ── POST /upload ──────────────────────────────────────────────────────────
@router.post("/upload", response_model=FileUploadResponse)
def upload_file(
    file: UploadFile = File(...),
    document_id: str = Form(...),
    user: ActiveUser = None,  # type: ignore
):
    """
    Upload an original file to Azure Blob Storage, keyed by document_id.

    This is called by the frontend *after* a successful RAG ingest so the
    user can later "View Original".  Failures here are non-fatal — the
    frontend shows a warning but keeps the RAG ingest.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    file_bytes = file.file.read()
    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    content_type = file.content_type or "application/octet-stream"

    try:
        result = file_storage.upload(
            document_id=document_id,
            file_bytes=file_bytes,
            filename=file.filename,
            content_type=content_type,
        )
    except RuntimeError as exc:
        # AZURE_BLOB_CONTAINER_URL not configured
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("File upload failed for document_id=%s", document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File upload failed: {exc}",
        ) from exc

    return FileUploadResponse(**result)


# ── GET /{document_id} ───────────────────────────────────────────────────
@router.get("/{document_id}")
def download_file(
    document_id: str,
    token: str = Query(None, description="Optional JWT token (query param auth)"),
    user: ActiveUser = None,  # type: ignore
):
    """
    Download / stream the original file for a given document_id.

    Supports Bearer header auth (primary) or ``?token=`` query param (fallback).
    Returns the file with the correct Content-Type so browsers can render
    PDFs/images natively or trigger a download for other types.
    """
    try:
        file_bytes, content_type, original_filename = file_storage.download(document_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No stored file for document {document_id}",
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("File download failed for document_id=%s", document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File download failed: {exc}",
        ) from exc

    # Use inline disposition so browsers render PDFs/images in-tab
    return Response(
        content=file_bytes,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{original_filename}"',
        },
    )
