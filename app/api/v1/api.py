from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, docs

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(docs.router, prefix="/docs", tags=["Documents"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])