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
    Pydantic bọc nó thành ValidationError và CHÈN giá trị đầu vào sai vào
    `str(exc)` (đã kiểm chứng bằng thực nghiệm — verbatim tới khoảng 44 ký tự,
    dài hơn thì Pydantic cắt bằng dấu ba chấm ở giữa quá ~50 ký tự). Chú ý: cắt
    bớt đó vẫn để lộ phần đầu VÀ phần cuối của giá trị — là một rò rỉ MỘT PHẦN,
    không phải một cách khắc phục, và không nên dựa vào nó để coi là an toàn (một
    khoá gốc sai hình dạng nhưng ngắn, như trong test của chính module này, vẫn
    lộ NGUYÊN VĂN vì chưa chạm ngưỡng cắt). Viết tay bằng code thường để tự kiểm
    soát toàn bộ nội dung thông điệp lỗi, không phụ thuộc hành vi cắt chuỗi của
    một thư viện ngoài.
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
    # HOÃN, kèm CẢNH BÁO VỀ CÁCH LÀM: chưa có kiểm độ dài tối thiểu cho
    # `jwt_secret` (nên là >= 32 byte). Khi thêm, PHẢI viết bằng mã kiểm THƯỜNG
    # trong `get_settings()` — TUYỆT ĐỐI KHÔNG dùng `Field(min_length=32)` hay
    # `field_validator`.
    #
    # Lý do đã kiểm chứng bằng thực nghiệm: `ValidationError` của pydantic DỘI
    # NGUYÊN VĂN giá trị vi phạm vào `str(exc)`, nên một validator độ dài sẽ ghi
    # chính `jwt_secret` vào thông báo lỗi — và thông báo đó đi vào log khởi
    # động, vào stderr của container, vào công cụ theo dõi lỗi. Đây đúng cùng
    # một dạng lỗ với việc FastAPI serialise `input` vào thân 422 (xem
    # `_an_khoa_nhay_cam` trong app/main.py): cùng một bài học ở hai thư viện,
    # nên phát biểu thành nguyên tắc — KHÔNG BAO GIỜ kiểm một giá trị bí mật
    # bằng validator của pydantic/FastAPI.
    #
    # Tiền lệ ĐÚNG đã có sẵn trong file này: `_kiem_tra_hinh_dang_khoa_goc()`
    # kiểm `llm_key_encryption_key` bằng mã thường và tự soạn thông báo (chỉ nêu
    # SỐ BYTE, không nêu giá trị). Sao theo đúng hình dạng đó.
    #
    # Điều đáng giữ lại của câu chuyện này: chính việc HOÃN validator đã tình cờ
    # tránh được lỗ rò — cách hiển nhiên nhất để "làm cho xong" ở đây lại là
    # cách tạo ra lỗ. Nếu không ghi lại, người làm sau sẽ chọn đúng cách hiển
    # nhiên đó.
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
