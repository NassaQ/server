from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field
from urllib.parse import quote_plus


def _quote(s: str) -> str:
    return quote_plus(s)


class Settings(BaseSettings):
    ENVIRONMENT: str = "production"

    SQL_SERVER: str
    SQL_DB_NAME: str
    SQL_USER: str
    SQL_PASS: str
    SQL_DRIVER: str = "ODBC Driver 18 for SQL Server"

    # JWT configs
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int
    JWT_ALGORITHM: str
    JWT_SECRET_KEY: str

    # Azure OpenAI (Classification + RAG Generation)
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_DEPLOYMENT_NAME: str = "gpt-4.1-mini"
    AZURE_OPENAI_API_VERSION: str = "2024-12-01-preview"

    # Azure OpenAI Embedding (RAG)
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = "text-embedding-3-small"
    EMBEDDING_DIMENSIONS: int = 1536

    # Cohere Rerank (via Azure AI Foundry)
    COHERE_RERANK_ENDPOINT: str = ""
    COHERE_RERANK_API_KEY: str = ""
    COHERE_RERANK_MODEL: str = "Cohere-rerank-v4.0-fast"

    # Azure Blob Storage (original file storage)
    AZURE_BLOB_CONTAINER_URL: str = ""
    BLOB_STORAGE_TYPE: str = "azure"
    BLOB_CONNECTION_STR: str = ""
    BLOB_STORAGE_CONTAINER_NAME: str = ""

    # Message Broker
    MESSAGE_BROKER_URL: str = ""
    OCR_QUEUE_NAME: str = "ocr_queue"
    AI_FOUNDRY_QUEUE_NAME: str = "ai_foundry_queue"
    PROCESSING_BACKEND: str = "ocr_api"  # "ocr_api" or "ai_foundry"

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Upload constraints
    MAX_UPLOAD_SIZE_MB: int = 50

    # Azure AI Search (Vector Store)
    AZURE_SEARCH_ENDPOINT: str = ""
    AZURE_SEARCH_API_KEY: str = ""
    AZURE_SEARCH_INDEX_NAME: str = "nassaq-chunks"

    # Azure Cosmos DB (MongoDB API) — for OCR result cleanup
    MONGO_USER: str = ""
    MONGO_PASS: str = ""
    MONGO_HOST: str = ""
    MONGO_DB_NAME: str = "nassaq"
    COSMOS_OCR_COLLECTION: str = "ocr_results"

    # RAG Pipeline
    RAG_CHUNK_SIZE: int = 400
    RAG_CHUNK_OVERLAP: int = 50
    RAG_TOP_K_RETRIEVAL: int = 20

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @computed_field
    def SQL_CONNECTION_STRING(self) -> str:
        encoded_pass = _quote(self.SQL_PASS)

        return (
            f"mssql+aioodbc://{self.SQL_USER}:{encoded_pass}@"
            f"{self.SQL_SERVER}/{self.SQL_DB_NAME}"
            f"?driver={_quote(self.SQL_DRIVER)}"
            "&TrustServerCertificate=yes&LoginTimeout=60"
        )

    @computed_field
    def MONGO_CONNECTION_STR(self) -> str:
        if not self.MONGO_USER or not self.MONGO_HOST:
            return ""
        encoded_pass = _quote(self.MONGO_PASS)
        return (
            f"mongodb+srv://{self.MONGO_USER}:{encoded_pass}@{self.MONGO_HOST}"
            f"/?tls=true&authMechanism=SCRAM-SHA-256"
            f"&retrywrites=false&maxIdleTimeMS=120000"
        )


settings = Settings()  # type: ignore
