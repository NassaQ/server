from abc import ABC, abstractmethod
from typing import Any, AsyncIterator
from urllib.parse import unquote, urlparse
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient

class StorageBase(ABC):
    @abstractmethod
    async def upload(self, data: bytes, path: str) -> str:
        """Uploads data and returns the remote identifier."""
        pass

    @abstractmethod
    async def download(self, path: str) -> bytes:
        """Retrieves data bytes using the identifier."""
        pass

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Deletes a single file."""
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Checks if a file exists."""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

class AzureBlobStorage(StorageBase):
    def __init__(self, conn_str: str, container: str):
        self.client = BlobServiceClient.from_connection_string(conn_str)
        self.container = container

    async def __aexit__(self, *args):
        await self.client.close()

    def _extract_name(self, path: str) -> str:
        """Parses the blob name from a URL or returns the raw path."""

        if path.startswith("http"):
            parsed = urlparse(path)
            path_parts = parsed.path.lstrip("/").split("/", 1)
            return unquote(path_parts[1]) if len(path_parts) > 1 else unquote(path_parts[0])
        return path

    def _get_blob(self, path: str):
        """Helper to create a blob client for a specific path."""

        name = self._extract_name(path)
        return self.client.get_blob_client(container=self.container, blob=name)

    async def upload(self, file: bytes, path: str) -> str:
        """Uploads bytes to the specified path and returns the absolute URL."""

        blob = self._get_blob(path)
        await blob.upload_blob(file, overwrite=True)
        return blob.url

    async def download(self, path: str) -> bytes:
        """Downloads the full content of a blob identified by path or URL."""

        blob = self._get_blob(path)
        stream = await blob.download_blob()
        return await stream.readall()

    async def download_stream(self, path: str) -> AsyncIterator[bytes]:
        """Yields the blob content in chunks."""

        blob = self._get_blob(path)
        stream = await blob.download_blob()
        async for chunk in stream.chunks():
            yield chunk

    async def delete(self, path: str) -> None:
        """Deletes a single specific blob."""

        blob = self._get_blob(path)
        try:
            await blob.delete_blob()
        except ResourceNotFoundError:
            pass

    async def delete_dir(self, path: str) -> None:
        """Deletes all blobs located under the specified virtual directory prefix."""

        container = self.client.get_container_client(self.container)
        prefix = path.strip("/") + "/"
        
        async for blob in container.list_blobs(name_starts_with=prefix):
            await container.delete_blob(blob.name)
    
    async def find(self, query: str, prefix: str = "") -> list[str]:
        """
        Returns a list of blob names that contain the query string.
        Optionally limits the search scope to a specific prefix folder.
        """
        
        container = self.client.get_container_client(self.container)
        search_prefix = prefix.strip("/") + "/" if prefix else ""
        
        matches = []
        async for blob in container.list_blobs(name_starts_with=search_prefix):
            if query in blob.name:
                matches.append(blob.name)
        return matches

    async def exists(self, path: str) -> bool:
        """Checks if a blob exists at the given path."""
        
        blob = self._get_blob(path)
        return await blob.exists()

    async def properties(self, path: str) -> dict[str, Any]:
        """Retrieves system properties (size, content_type, last_modified) for the blob."""

        blob = self._get_blob(path)
        return await blob.get_blob_properties()

    async def list(self, path: str = "") -> list[str]:
        """Lists all blob names located under the specified prefix."""

        container = self.client.get_container_client(self.container)
        prefix = path.strip("/") + "/" if path else ""
        
        return [blob.name async for blob in container.list_blobs(name_starts_with=prefix)]