from fastapi import FastAPI
from app.api.v1 import api

app = FastAPI(title="NassaQ Backend")

app.include_router(api.api_router, prefix='/api/v1')

@app.get("/")
async def root():
    return {"message": "root directory call, nothing to display here right now!"}