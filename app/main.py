from fastapi import FastAPI

app = FastAPI(title="NassaQ Backend")

@app.get("/")
async def root():
    return {"message": "root directory call, nothing to display here right now!"}