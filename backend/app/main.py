from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.modules.auth.router import router as auth_router

app = FastAPI(title="AI Study Coach API")
app.include_router(auth_router)

# Tên trường có thể mang dữ liệu nhạy cảm — giá trị "input" của các lỗi validate trên
# những trường này bị thay bằng một chuỗi cố định để không lộ mật khẩu/token ra ngoài.
SENSITIVE_FIELD_NAMES = {
    "password",
    "password_hash",
    "refresh_token",
    "access_token",
    "api_key",
    "secret",
}
REDACTED_INPUT_MARKER = "[đã ẩn vì lý do bảo mật]"


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = []
    for error in exc.errors():
        error = dict(error)
        loc = error.get("loc") or ()
        if loc and loc[-1] in SENSITIVE_FIELD_NAMES:
            error["input"] = REDACTED_INPUT_MARKER
        errors.append(error)
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errors}))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
