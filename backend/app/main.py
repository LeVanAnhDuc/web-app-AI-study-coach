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


def _an_khoa_nhay_cam(gia_tri: object) -> object:
    """Đi ĐỆ QUY vào một giá trị `input` và thay giá trị của MỌI khoá có tên
    nằm trong `SENSITIVE_FIELD_NAMES`, ở bất kỳ độ sâu nào.

    Cần thiết vì `loc[-1]` chỉ nêu được tên trường khi lỗi xảy ra ĐÚNG TẠI
    trường đó. Một lỗi ở cấp cao hơn (thân request, hay một phần tử mảng) mang
    theo cả một object trong `input`, và mật khẩu nằm BÊN TRONG object đó —
    `loc[-1]` lúc ấy là "body" hoặc một chỉ số mảng, không phải "password".
    """
    if isinstance(gia_tri, dict):
        return {
            khoa: (
                REDACTED_INPUT_MARKER
                if khoa in SENSITIVE_FIELD_NAMES
                else _an_khoa_nhay_cam(gia_tri_con)
            )
            for khoa, gia_tri_con in gia_tri.items()
        }
    if isinstance(gia_tri, list | tuple):
        return [_an_khoa_nhay_cam(phan_tu) for phan_tu in gia_tri]
    return gia_tri


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Trả 422 với hình dạng `{"detail": [...]}` NGUYÊN VẸN (frontend chốt kiểu
    trên `detail` là mảng — xem C-22), nhưng đã ẩn mọi giá trị nhạy cảm trong
    trường `input` của từng phần tử.

    Redact theo BA lớp, vì mỗi lớp bắt một hình dạng lỗi khác nhau:

    1. `len(loc) <= 1` — lỗi ở CẤP THÂN request (`loc == ["body"]`, ví dụ
       `model_attributes_type` khi client gửi mảng hay chuỗi thay vì object).
       Ở đây `input` là TOÀN BỘ thân request và KHÔNG có tên trường nào để
       khớp, nên phải ẩn trọn gói: một thân dạng chuỗi (`"MatKhau..."`) không
       có khoá nào để bước 3 tìm ra.
    2. `loc[-1]` nằm trong `SENSITIVE_FIELD_NAMES` — lỗi đúng tại trường nhạy
       cảm (bản vá gốc của C-12).
    3. Còn lại: đi đệ quy vào `input` (xem `_an_khoa_nhay_cam`) để một object
       lồng vẫn bị ẩn đúng khoá, thay vì rò cả object chỉ vì lỗi được báo ở
       cấp cha. Các trường KHÔNG nhạy cảm vẫn giữ nguyên `input` để 422 còn
       dùng được khi gỡ lỗi tích hợp (ruling gốc của C-12).
    """
    errors = []
    for error in exc.errors():
        error = dict(error)
        loc = error.get("loc") or ()
        if "input" in error:
            if len(loc) <= 1 or loc[-1] in SENSITIVE_FIELD_NAMES:
                error["input"] = REDACTED_INPUT_MARKER
            else:
                error["input"] = _an_khoa_nhay_cam(error["input"])
        errors.append(error)
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errors}))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
