from fastapi import FastAPI

from app.modules.auth.router import router as auth_router

app = FastAPI(title="AI Study Coach API")
app.include_router(auth_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
