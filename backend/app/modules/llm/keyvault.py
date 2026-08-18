"""Két khoá API BYOK của người dùng, mã hoá tại chỗ bằng AES-256-GCM.

BYOK (bring your own key): người dùng dán khoá API thật của họ (OpenAI, Gemini,
...) vào ứng dụng để ứng dụng gọi hộ nhà cung cấp bằng chính khoá đó. Đây là
thông tin xác thực của bên thứ ba, thuộc về một người thật, có thể phát sinh chi
phí thật trên tài khoản của họ nếu rò rỉ — module này là hàng rào duy nhất giữa
khoá đó nằm dạng bản rõ trong CSDL hay không.

Ràng buộc cứng của toàn dự án cho khoá BYOK, áp dụng xuyên suốt module này:
mã hoá tại chỗ, WRITE-ONLY qua API (không endpoint nào trả nó ra), không bao giờ
vào log, không bao giờ vào prompt, không bao giờ vào thông điệp lỗi.

Định dạng blob lưu trữ (chuỗi base64 của):
    nonce (12 byte) || bản mã (độ dài bản rõ byte) || tag xác thực (16 byte cuối)

Thư viện `cryptography` gộp tag ngay sau bản mã trong cùng một buffer trả về từ
AESGCM.encrypt(), không tách riêng — nên "bản mã" và "tag" ở đây là hai phần của
CÙNG một chuỗi byte liền nhau, không phải hai cột riêng trong CSDL.

Về AAD (associated data) — Ruling 2: LẼ RA nên buộc mỗi bản mã vào chủ nhân của
nó (id người dùng + provider) để một bản ghi bị di chuyển sang hàng của người
dùng khác (do SQL injection, credential vận hành bị đánh cắp, admin có ác ý...)
sẽ giải mã thất bại thay vì âm thầm thành công. Module này CỐ Ý KHÔNG làm vậy:
chữ ký bắt buộc của `encrypt_key(plaintext) -> str` và `decrypt_key(blob) -> str`
không nhận bất kỳ tham số ngữ cảnh nào (không id người dùng, không provider), và
chưa có bảng CSDL nào lưu khoá BYOK ở M0/M1 — người tiêu thụ module này chỉ xuất
hiện ở M8 (xem progress.md, mục C-3). Nói cách khác: không có "ngữ cảnh" nào tồn
tại ở tầng này để buộc vào AAD — việc buộc AAD theo id người dùng/provider PHẢI
làm ở M8, khi giao diện hai hàm này được mở rộng để nhận ngữ cảnh đó từ tầng gọi
(vd repository lưu khoá BYOK, biết id người dùng và provider của hàng đang thao
tác). Ghi rõ ở đây để không ai nhầm im lặng bỏ qua với "đã cân nhắc và không cần".
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Re-export để thoả giao diện app.modules.llm.keyvault.MasterKeyMissing — định
# nghĩa thật nằm ở app.config vì get_settings() cần tự ném lỗi này lúc dựng
# Settings (Ruling 3); xem docstring của MasterKeyMissing để biết lý do đầy đủ.
from app.config import MasterKeyMissing, get_settings

__all__ = [
    "DecryptionFailed",
    "MasterKeyMissing",
    "decrypt_key",
    "encrypt_key",
    "generate_master_key",
    "last4",
]

_SO_BYTE_NONCE = 12  # 96 bit — kích thước nonce chuẩn khuyến nghị cho AES-GCM


class DecryptionFailed(Exception):
    """Xác thực bản mã thất bại: bản mã/nonce/tag bị sửa, hoặc sai khoá gốc.

    Thông điệp CỐ Ý là một câu cố định, không chèn bất kỳ phần nào của blob, khoá
    gốc, hay bản rõ (Ruling 4). Nguyên nhân gốc — InvalidTag từ thư viện
    cryptography (thông điệp rỗng, đã kiểm chứng bằng thực nghiệm) hoặc lỗi giải
    mã base64 (chỉ nêu lý do hình thức, vd "Incorrect padding", không nêu nội
    dung) — bị nuốt bằng `raise ... from None`: cả hai không tự mang dữ liệu nhạy
    cảm trong trường hợp thông thường, nhưng nuốt hẳn tránh mọi rủi ro rò rỉ qua
    traceback mặc định nếu hành vi thư viện đổi khác trong tương lai.
    """


def generate_master_key() -> str:
    """Sinh khoá gốc AES-256 mới, mã hoá base64. Chạy một lần, dán kết quả vào
    biến môi trường LLM_KEY_ENCRYPTION_KEY. KHÔNG dùng lệnh này để sinh khoá cho
    từng người dùng — đây là khoá gốc DUY NHẤT của cả hệ thống, dùng để mã hoá
    khoá BYOK của mọi người dùng.
    """
    return base64.b64encode(os.urandom(32)).decode("ascii")


def _khoa_aes() -> AESGCM:
    """Dựng đối tượng AESGCM từ khoá gốc đã cấu hình.

    Việc kiểm tra HÌNH DẠNG khoá gốc (giải mã base64 được không, đúng 32 byte
    không) đã chạy sớm ở app.config.get_settings() — vì get_settings() dùng
    lru_cache và được gọi ngay từ lúc app khởi động (app.db tạo engine ngay lúc
    import), lỗi hình dạng nổ ra lúc khởi động, không đợi tới lần một người dùng
    thật lưu khoá BYOK đầu tiên của họ (đúng tinh thần Ruling 3: construction,
    không phải first use).

    Ở đây chỉ còn lại trường hợp "chưa cấu hình" (chuỗi rỗng) — một trạng thái
    hợp lệ khi tính năng BYOK chưa bật — nên mới kiểm tra và ném MasterKeyMissing
    tại đây, đúng lúc có ai đó THỰC SỰ cần dùng khoá.
    """
    raw = get_settings().llm_key_encryption_key
    if not raw:
        raise MasterKeyMissing(
            "Chưa đặt LLM_KEY_ENCRYPTION_KEY. Sinh một khoá bằng "
            "keyvault.generate_master_key() rồi dán vào biến môi trường."
        )
    return AESGCM(base64.b64decode(raw))


def encrypt_key(plaintext: str) -> str:
    """Mã hoá một khoá API BYOK dạng bản rõ, trả về blob base64 để lưu CSDL."""
    # Nonce MỚI, ngẫu nhiên thật (os.urandom), sinh lại cho MỌI lệnh gọi — không
    # bao giờ suy ra từ id người dùng, tên provider, băm của bản rõ, hay một bộ
    # đếm giữ trong bộ nhớ. Tái sử dụng CÙNG cặp (khoá, nonce) trong AES-GCM không
    # chỉ làm yếu mà PHÁ VỠ hoàn toàn tính bảo mật: lộ XOR của hai bản rõ và cho
    # phép giả mạo bản mã tuỳ ý dưới cùng khoá đó (Ruling 1).
    nonce = os.urandom(_SO_BYTE_NONCE)
    ban_ma = _khoa_aes().encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ban_ma).decode("ascii")


def decrypt_key(blob: str) -> str:
    """Giải mã một blob do encrypt_key() sinh ra, trả lại bản rõ ban đầu.

    Ném DecryptionFailed nếu blob không phải base64 hợp lệ, quá ngắn để chứa
    nonce/tag, đã bị sửa (dù chỉ một byte), hoặc khoá gốc hiện tại không phải
    khoá đã dùng để mã hoá — GCM xác thực nên mọi trường hợp trên đều thất bại
    rõ ràng thay vì âm thầm trả về rác (Ruling 5).
    """
    try:
        raw = base64.b64decode(blob, validate=True)
        nonce, ban_ma = raw[:_SO_BYTE_NONCE], raw[_SO_BYTE_NONCE:]
        ban_ro = _khoa_aes().decrypt(nonce, ban_ma, None)
    except MasterKeyMissing:
        raise
    except (InvalidTag, ValueError):
        raise DecryptionFailed(
            "Xác thực bản mã thất bại: bản mã đã bị sửa hoặc khoá gốc không đúng."
        ) from None
    return ban_ro.decode("utf-8")


def last4(plaintext: str) -> str:
    """Trả về 4 ký tự cuối của một khoá API — mảnh hiển thị được, không bí mật,
    dùng để người dùng nhận ra "đây có phải khoá mình vừa dán không" mà không
    phải hiện lại toàn bộ khoá (vốn bị cấm — write-only qua API).
    """
    return plaintext[-4:]
