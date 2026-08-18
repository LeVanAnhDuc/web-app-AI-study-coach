import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_SO_BYTE_KHOA_AES_256 = 32


class MasterKeyMissing(Exception):
    """Không có khoá gốc AES-GCM dùng được để mã hoá/giải mã khoá BYOK của người dùng.

    Bao gồm cả hai tình huống: chưa đặt `LLM_KEY_ENCRYPTION_KEY` (giá trị rỗng — một
    trạng thái hợp lệ khi tính năng BYOK chưa được bật), và đã đặt nhưng sai hình
    dạng (không giải mã được base64, hoặc không đúng 32 byte). Gộp chung một lớp vì
    hệ quả với người gọi là như nhau: không có khoá gốc nào dùng được lúc này.

    Định nghĩa ở đây (không phải trong `app.modules.llm.keyvault`) để tránh vòng
    lặp import: `get_settings()` cần tự ném lỗi này ngay lúc dựng `Settings` (xem
    dưới), còn `keyvault.py` vốn đã phải `import app.config` để lấy `get_settings`.
    `keyvault.py` import lại tên này từ đây để thoả giao diện
    `app.modules.llm.keyvault.MasterKeyMissing`.
    """


def _kiem_tra_hinh_dang_khoa_goc(gia_tri: str) -> None:
    """Chặn khoá gốc sai hình dạng NGAY lúc dựng Settings, không đợi tới lần
    encrypt_key/decrypt_key đầu tiên (Ruling 3 của Task 16).

    Bỏ qua khi rỗng: chưa cấu hình là một trạng thái hợp lệ ở M0/M1 (chưa có
    người dùng BYOK nào) — MasterKeyMissing cho trường hợp đó chỉ nổ ra khi
    keyvault thực sự cần khoá.

    CỐ Ý không dùng `pydantic.field_validator`: khi validator ném ValueError,
    Pydantic bọc nó thành ValidationError và CHÈN NGUYÊN VĂN giá trị đầu vào sai
    vào `str(exc)` (đã kiểm chứng bằng thực nghiệm) — tức là sẽ làm lộ khoá gốc
    (dù sai hình dạng, vẫn là dữ liệu bí mật) ra traceback/log đầu tiên gặp phải.
    Viết tay bằng code thường để tự kiểm soát toàn bộ nội dung thông điệp lỗi.
    """
    try:
        khoa = base64.b64decode(gia_tri, validate=True)
    except binascii.Error:
        raise MasterKeyMissing("LLM_KEY_ENCRYPTION_KEY không giải mã được base64.") from None
    if len(khoa) != _SO_BYTE_KHOA_AES_256:
        raise MasterKeyMissing(
            f"LLM_KEY_ENCRYPTION_KEY phải là {_SO_BYTE_KHOA_AES_256} byte sau khi "
            f"giải mã base64, nhận được {len(khoa)} byte."
        ) from None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    jwt_secret: str
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 30

    llm_key_encryption_key: str = ""
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    mistral_api_key: str | None = None

    gemini_model: str = "gemini-2.5-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    mistral_model: str = "mistral-large-latest"

    llm_fixture_mode: Literal["off", "record", "replay"] = "off"
    llm_fixture_dir: str = "tests/fixtures/llm"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.llm_key_encryption_key:
        _kiem_tra_hinh_dang_khoa_goc(settings.llm_key_encryption_key)
    return settings
