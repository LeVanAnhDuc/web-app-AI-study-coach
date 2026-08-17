from fastapi import FastAPI

app = FastAPI(title="AI Study Coach API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
