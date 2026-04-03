"""
Azure Blob Storage service for original file storage.

Stores uploaded files keyed by document_id so they can be retrieved
later via "View Original" in the frontend.

Blob name  = document_id (UUID)
Metadata   = original_filename, content_type
"""

from __future__ import annotations

import logging
from typing import Optional

from azure.storage.blob import ContainerClient, ContentSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Singleton container client
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------


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

    logger.info(
        "[UPLOAD START] doc=%s, file=%s, size=%d, type=%s",
        document_id,
        filename,
        len(file_bytes),
        content_type,
    )

    blob.upload_blob(
        file_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
        metadata={
            "original_filename": filename,
            "content_type": content_type,
        },
    )

    # Verify the blob actually exists after upload
    verified = blob.exists()
    logger.info(
        "[UPLOAD DONE] doc=%s, verified_exists=%s",
        document_id,
        verified,
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

    logger.info("[DOWNLOAD START] doc=%s", document_id)

    # Quick existence check first
    if not blob.exists():
        logger.warning("[DOWNLOAD] Blob does NOT exist: %s", document_id)
        raise FileNotFoundError(f"No stored file for document_id={document_id}")

    try:
        stream = blob.download_blob()
        props = blob.get_blob_properties()
    except Exception as exc:
        logger.exception("[DOWNLOAD] Azure error for doc=%s", document_id)
        if "BlobNotFound" in str(exc) or "ResourceNotFound" in str(exc):
            raise FileNotFoundError(
                f"No stored file for document_id={document_id}"
            ) from exc
        raise

    file_bytes = stream.readall()

    # Retrieve metadata we stored during upload
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
        logger.info("Deleted blob %s", document_id)
        return True
    except Exception as exc:
        if "BlobNotFound" in str(exc) or "ResourceNotFound" in str(exc):
            logger.debug("Blob %s not found — nothing to delete", document_id)
            return False
        raise


def exists(document_id: str) -> bool:
    """Check whether a blob exists for the given document_id."""
    container = _get_container()
    blob = container.get_blob_client(document_id)
    return blob.exists()
