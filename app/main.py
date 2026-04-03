import sys
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, status, Response
from fastapi.middleware.cors import CORSMiddleware

# ── Add model directories to sys.path for direct imports ──────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

for model_dir in ("ocr-model", "Classification-model"):
    model_path = str(_PROJECT_ROOT / model_dir)
    if model_path not in sys.path:
        sys.path.insert(0, model_path)

from app.core.config import settings
from app.api.v1 import api
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Load FAISS index from disk on startup (if it exists) ──────────────
    try:
        from app.services.rag import get_store

        store = get_store()
        doc_count = len(store.list_documents())
        chunk_count = store.total_vectors
        if chunk_count > 0:
            print(
                f"[RAG] FAISS index loaded: {doc_count} documents, {chunk_count} chunks"
            )
        else:
            print("[RAG] FAISS index initialized (empty)")
    except Exception as e:
        print(f"[RAG] FAISS init skipped: {e}")

    yield

    try:
        await engine.dispose()
    except Exception:
        pass  # DB may not be available in demo mode


app = FastAPI(
    title="NassaQ Backend",
    description="Intelligent Semantic Archive Digitization System",
    docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
    redoc_url=None if settings.ENVIRONMENT == "production" else "/redoc",
    openapi_url=None if settings.ENVIRONMENT == "production" else "/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.api_router, prefix="/api/v1")


@app.get("/", status_code=status.HTTP_204_NO_CONTENT)
async def root():
    return Response(status_code=status.HTTP_204_NO_CONTENT)
