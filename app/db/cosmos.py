from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings


class CosmosClient:
    """Async MongoDB client for Azure Cosmos DB (MongoDB API).

    Used by the server only for cleanup operations (delete by doc_id).
    The ai-foundry worker has its own full-featured CosmosClient.
    """

    def __init__(self):
        self._client: AsyncIOMotorClient | None = None
        self._collection = None

    async def connect(self):
        conn_str = settings.MONGO_CONNECTION_STR
        if not conn_str:
            return
        self._client = AsyncIOMotorClient(conn_str)
        db = self._client[settings.MONGO_DB_NAME]
        self._collection = db[settings.COSMOS_OCR_COLLECTION]
        print(f"[Cosmos] Connected: {settings.MONGO_DB_NAME}/{settings.COSMOS_OCR_COLLECTION}")

    async def find_by_doc_id(self, doc_id: int) -> dict | None:
        """Find an OCR result document by its SQL doc_id. Returns None if not found."""
        if self._collection is None:
            return None
        return await self._collection.find_one({"doc_id": doc_id})

    async def upsert_ocr_result(self, doc: dict) -> bool:
        """Insert or replace an OCR result document keyed by doc_id. Returns True if inserted."""
        if self._collection is None:
            return False
        result = await self._collection.replace_one(
            {"doc_id": doc["doc_id"]},
            doc,
            upsert=True,
        )
        return result.upserted_id is not None or result.modified_count > 0

    async def delete_by_doc_id(self, doc_id: int) -> bool:
        """Delete an OCR result document by its SQL doc_id. Returns True if deleted."""
        if self._collection is None:
            return False
        result = await self._collection.delete_one({"doc_id": doc_id})
        return result.deleted_count > 0

    @property
    def connected(self) -> bool:
        return self._collection is not None

    async def close(self):
        if self._client:
            self._client.close()
            self._client = None
            self._collection = None


cosmos = CosmosClient()
