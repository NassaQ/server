from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field
from urllib.parse import quote_plus


class Settings(BaseSettings):
    ENVIRONMENT: str = "production"

    SQL_SERVER: str
    SQL_DB_NAME: str
    SQL_USER: str
    SQL_PASS: str
    SQL_DRIVER: str = "ODBC Driver 18 for SQL Server"

    SQL_CONNECT_TIMEOUT: int = 60
    SQL_MAX_RETRIES: int = 3
    SQL_RETRY_DELAY_BASE: int = 2

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

    # FAISS Vector Store
    FAISS_INDEX_DIR: str = "data/faiss"

    # RAG Pipeline
    RAG_CHUNK_SIZE: int = 400
    RAG_CHUNK_OVERLAP: int = 50
    RAG_TOP_K_RETRIEVAL: int = 20

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @computed_field
    def SQL_CONNECTION_STRING(self) -> str:
        encoded_pass = quote_plus(self.SQL_PASS)

        return (
            f"mssql+aioodbc://{self.SQL_USER}:{encoded_pass}@"
            f"{self.SQL_SERVER}/{self.SQL_DB_NAME}"
            f"?driver={quote_plus(self.SQL_DRIVER)}"
            "&TrustServerCertificate=yes"
        )


settings = Settings()  # type: ignore
