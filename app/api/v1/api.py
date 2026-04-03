from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, documents, rag, files

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(rag.router, prefix="/rag", tags=["RAG"])
api_router.include_router(files.router, prefix="/files", tags=["Files"])
