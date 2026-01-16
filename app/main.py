from fastapi import FastAPI, status, Response
from app.api.v1 import api

app = FastAPI(title="NassaQ Backend")

app.include_router(api.api_router, prefix='/api/v1')

@app.get("/", status_code=status.HTTP_204_NO_CONTENT)
async def root():
    return Response(status_code=status.HTTP_204_NO_CONTENT)