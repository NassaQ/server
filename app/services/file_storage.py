"""
Azure Blob Storage service for original file storage.

Stores uploaded files keyed by document_id so they can be retrieved
later via "View Original" in the frontend.

Blob name  = document_id (UUID)
Metadata   = original_filename, content_type
"""

from __future__ import annotations

from typing import Optional

from azure.storage.blob import ContainerClient, ContentSettings

from app.core.config import settings

_container_client: Optional[ContainerClient] = None


def _get_container() -> ContainerClient:
    """Return (and lazily create) the ContainerClient singleton."""
    global _container_client
    if _container_client is None:
        url = settings.AZURE_BLOB_CONTAINER_URL
        if not url:
            raise RuntimeError(
                "AZURE_BLOB_CONTAINER_URL is not configured. "
                "Set it in .env to enable original-file storage."
            )
        _container_client = ContainerClient.from_container_url(url)
    return _container_client


def _sanitize_meta(value: str) -> str:
    """
    Strip characters that can't be encoded in Latin-1 (ISO-8859-1).

    Azure Blob Storage metadata values are stored as HTTP headers,
    which must be Latin-1 encodable.  This silently drops characters
    outside that range (e.g. Arabic, CJK, emoji).
    """
    return value.encode("latin-1", "ignore").decode("latin-1")


def upload(
    document_id: str,
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> dict:
    """
    Upload a file to Azure Blob Storage.

    Returns a dict with upload metadata on success.
    Raises on failure so callers can handle gracefully.
    """
    container = _get_container()
    blob = container.get_blob_client(document_id)

    blob.upload_blob(
        file_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
        metadata={
            "original_filename": _sanitize_meta(filename),
            "content_type": _sanitize_meta(content_type),
        },
    )

    return {
        "document_id": document_id,
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(file_bytes),
        "status": "uploaded",
    }


def download(document_id: str) -> tuple[bytes, str, str]:
    """
    Download a file from Azure Blob Storage.

    Returns ``(file_bytes, content_type, original_filename)``.
    Raises ``FileNotFoundError`` if the blob does not exist.
    """
    container = _get_container()
    blob = container.get_blob_client(document_id)

    if not blob.exists():
        raise FileNotFoundError(f"No stored file for document_id={document_id}")

    try:
        stream = blob.download_blob()
        props = blob.get_blob_properties()
    except Exception as exc:
        if "BlobNotFound" in str(exc) or "ResourceNotFound" in str(exc):
            raise FileNotFoundError(
                f"No stored file for document_id={document_id}"
            ) from exc
        raise

    file_bytes = stream.readall()

    meta = props.metadata or {}
    content_type = meta.get("content_type", "application/octet-stream")
    original_filename = meta.get("original_filename", document_id)

    return file_bytes, content_type, original_filename


def delete(document_id: str) -> bool:
    """
    Delete a blob by document_id.  Returns True if deleted, False if
    the blob did not exist.  Does NOT raise on "not found".
    """
    container = _get_container()
    blob = container.get_blob_client(document_id)

    try:
        blob.delete_blob()
        return True
    except Exception as exc:
        if "BlobNotFound" in str(exc) or "ResourceNotFound" in str(exc):
            return False
        raise


def exists(document_id: str) -> bool:
    """Check whether a blob exists for the given document_id."""
    container = _get_container()
    blob = container.get_blob_client(document_id)
    return blob.exists()
