from contextlib import asynccontextmanager
from fastapi import FastAPI, status, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import get_broker
from app.core.config import settings
from app.api.v1 import api
from app.db.session import engine

broker = get_broker()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.connect()
    app.state.broker = broker

    yield
    await broker.close()
    await engine.dispose()

app = FastAPI(
    title="NassaQ Backend",
    docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
    redoc_url=None if settings.ENVIRONMENT == "production" else "/redoc",
    openapi_url=None if settings.ENVIRONMENT == "production" else "/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.api_router, prefix='/api/v1')

@app.get("/", status_code=status.HTTP_204_NO_CONTENT)
async def root():
    return Response(status_code=status.HTTP_204_NO_CONTENT)