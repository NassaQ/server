from abc import ABC, abstractmethod
import os
from typing import AsyncIterator
from urllib.parse import urlparse

class StorageBase(ABC):
    @abstractmethod
    async def upload(self, file: bytes, path: str) -> str:
        """Uploads data and returns a retrieval path/ID"""
        pass
        
    @abstractmethod
    async def download(self, path: str) -> bytes:
        """Retrieves data bytes using the path"""
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

class AzureBlobStorage(StorageBase):
    def __init__(self, conn_str: str, container: str):
        from azure.storage.blob.aio import BlobServiceClient
        self.client = BlobServiceClient.from_connection_string(conn_str)
        self.container = container
    
    async def upload(self, file: bytes, name: str) -> str:
        blob_client = self.client.get_blob_client(container=self.container, blob=name)
        await blob_client.upload_blob(file, overwrite=True)

        return blob_client.url      # returns absolute path

    async def download(self, path: str) -> bytes:
        blob_name = self._get_blob_name(path)

        blob_client = self.client.get_blob_client(container=self.container, blob=blob_name)
        stream = await blob_client.download_blob()

        return await stream.readall()
    
    async def download_stream(self, path: str, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        blob_name = self._get_blob_name(path)
        blob_client = self.client.get_blob_client(container=self.container, blob=blob_name)
        
        stream = await blob_client.download_blob()
        
        async for chunk in stream.chunks():
            yield chunk
    
    def _get_blob_name(self, path: str) -> str:
        """Helper to extract blob name if a full URL is provided."""
        if path.startswith("http"):
            parsed = urlparse(path)
            return os.path.basename(parsed.path)
        return path

    async def __aexit__(self, *args):
        await self.client.close()