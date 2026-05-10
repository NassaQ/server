from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, rag, files, docs, paths, process

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(paths.router, prefix="/paths", tags=["Virtual Paths"])
api_router.include_router(rag.router, prefix="/rag", tags=["RAG"])
api_router.include_router(files.router, prefix="/files", tags=["Files"])
api_router.include_router(docs.router, prefix="/docs", tags=["Documents"])
api_router.include_router(process.router, prefix="/documents", tags=["Document Processing"])

