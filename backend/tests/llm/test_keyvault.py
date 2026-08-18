import base64
import os

import pytest

from app.config import MasterKeyMissing, get_settings
from app.modules.llm.keyvault import (
    DecryptionFailed,
    decrypt_key,
    encrypt_key,
    generate_master_key,
    last4,
)

# Mọi ngoại lệ có thể ném ra từ các nhánh thất bại được test dưới đây — dùng để
# bắt CÓ CHỦ ĐÍCH thay vì `except Exception` chung chung (Ruling 4 đang là chủ đề
# kiểm tra, nên bản thân test cũng nên tường minh về việc nó bắt gì).
_LOI_KEYVAULT = (DecryptionFailed, MasterKeyMissing)

# Câu thần chú duy nhất dùng xuyên suốt file này để dò rò rỉ bí mật (Ruling 4):
# nếu chuỗi này xuất hiện trong bất kỳ thông điệp lỗi nào, coi như module đã lộ
# bản rõ/khoá gốc ra ngoài.
_SENTINEL = "CANARY-nguoi-dung-that-khong-duoc-lo-XYZ789"


@pytest.fixture(autouse=True)
def khoa_goc(monkeypatch):
    monkeypatch.setenv("LLM_KEY_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_ma_hoa_roi_giai_ma_ra_dung_ban_goc():
    goc = "sk-khoa-that-cua-nguoi-dung-123456"
    assert decrypt_key(encrypt_key(goc)) == goc


def test_ban_ma_khong_chua_ban_ro():
    goc = "sk-khoa-that-cua-nguoi-dung-123456"
    assert goc not in encrypt_key(goc)


def test_hai_lan_ma_hoa_cung_khoa_ra_hai_ban_ma_khac_nhau():
    # Ruling 1 — bài kiểm tra chịu trách nhiệm chính: nếu nonce bị cố định (hard-code)
    # thay vì sinh mới bằng os.urandom mỗi lần gọi, hai lần mã hoá CÙNG bản rõ sẽ ra
    # CÙNG một khối byte, và test này sẽ đỏ. Một test round-trip đơn thuần (ở trên)
    # không thể phát hiện lỗi này vì giải mã vẫn ra đúng bản gốc dù nonce bị tái sử
    # dụng — rủi ro chỉ lộ ra khi so sánh HAI lần mã hoá với nhau.
    goc = "sk-giong-nhau"
    a = encrypt_key(goc)
    b = encrypt_key(goc)
    assert a != b
    # Không chỉ khác toàn bộ chuỗi — 12 byte nonce đầu (base64 hoá ra ký tự đầu)
    # cũng phải khác nhau, để chắc chắn phần khác biệt không chỉ nằm ở đệm cuối.
    assert base64.b64decode(a)[:12] != base64.b64decode(b)[:12]


def test_ban_ma_bi_sua_thi_giai_ma_that_bai():
    blob = encrypt_key("sk-abc-def-ghi")
    hong = blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB")
    with pytest.raises(DecryptionFailed):
        decrypt_key(hong)


def test_last4_chi_lay_bon_ky_tu_cuoi():
    assert last4("sk-abcdefgh1234") == "1234"


def test_khoa_qua_ngan_van_lay_duoc_last4():
    assert last4("ab") == "ab"


def test_thieu_khoa_goc_thi_bao_loi_ro_rang(monkeypatch):
    monkeypatch.setenv("LLM_KEY_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(MasterKeyMissing):
        encrypt_key("sk-gi-do")


def test_sinh_khoa_goc_dung_32_byte():
    assert len(base64.b64decode(generate_master_key())) == 32


# ---------------------------------------------------------------------------
# Ruling 3 — khoá gốc sai hình dạng phải báo lỗi NGAY LÚC get_settings() dựng
# Settings, không đợi tới lần encrypt_key/decrypt_key đầu tiên.
# ---------------------------------------------------------------------------


def test_khoa_goc_sai_do_dai_bao_loi_ngay_luc_dung_settings(monkeypatch):
    # 16 byte, không phải 32 — hình dạng sai nhưng vẫn giải mã base64 được.
    khoa_sai = base64.b64encode(os.urandom(16)).decode()
    monkeypatch.setenv("LLM_KEY_ENCRYPTION_KEY", khoa_sai)
    get_settings.cache_clear()
    # Lỗi phải nổ ra ngay ở get_settings(), TRƯỚC KHI có bất kỳ lệnh gọi
    # encrypt_key/decrypt_key nào — đây chính là "construction", không phải
    # "first use".
    with pytest.raises(MasterKeyMissing) as loi:
        get_settings()
    assert "32 byte" in str(loi.value)
    assert khoa_sai not in str(loi.value)


def test_khoa_goc_khong_giai_ma_duoc_base64_bao_loi_ngay_luc_dung_settings(monkeypatch):
    khoa_sai = "***khong-phai-base64-hop-le***"
    monkeypatch.setenv("LLM_KEY_ENCRYPTION_KEY", khoa_sai)
    get_settings.cache_clear()
    with pytest.raises(MasterKeyMissing) as loi:
        get_settings()
    assert khoa_sai not in str(loi.value)


# ---------------------------------------------------------------------------
# Ruling 4 — không lệ liệu/bản rõ trong bất kỳ thông điệp lỗi nào, trên MỌI
# nhánh thất bại.
# ---------------------------------------------------------------------------


def test_khong_nhanh_that_bai_nao_lo_ban_ro_hoac_khoa_goc(monkeypatch):
    thong_diep = []

    blob_that = encrypt_key(_SENTINEL)

    # Nhánh 1: bản mã bị sửa.
    raw = bytearray(base64.b64decode(blob_that))
    raw[-1] ^= 0xFF
    blob_hong = base64.b64encode(bytes(raw)).decode()
    try:
        decrypt_key(blob_hong)
    except _LOI_KEYVAULT as exc:
        thong_diep.append(str(exc))

    # Nhánh 2: sai khoá gốc khi giải mã.
    monkeypatch.setenv("LLM_KEY_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    get_settings.cache_clear()
    try:
        decrypt_key(blob_that)
    except _LOI_KEYVAULT as exc:
        thong_diep.append(str(exc))

    # Nhánh 3: thiếu khoá gốc lúc mã hoá.
    monkeypatch.setenv("LLM_KEY_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    try:
        encrypt_key(_SENTINEL)
    except _LOI_KEYVAULT as exc:
        thong_diep.append(str(exc))

    # Nhánh 4: khoá gốc sai độ dài lúc dựng Settings.
    monkeypatch.setenv("LLM_KEY_ENCRYPTION_KEY", base64.b64encode(os.urandom(10)).decode())
    get_settings.cache_clear()
    try:
        get_settings()
    except _LOI_KEYVAULT as exc:
        thong_diep.append(str(exc))

    # Nhánh 5: blob rác không phải base64 hợp lệ.
    try:
        monkeypatch.setenv("LLM_KEY_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
        get_settings.cache_clear()
        decrypt_key("***khong-phai-blob-hop-le***")
    except _LOI_KEYVAULT as exc:
        thong_diep.append(str(exc))

    assert len(thong_diep) == 5, "phải thu đủ 5 nhánh thất bại để kiểm tra"
    for msg in thong_diep:
        assert _SENTINEL not in msg


# ---------------------------------------------------------------------------
# Ruling 5 — giả mạo từng trường một phải bị phát hiện độc lập.
# ---------------------------------------------------------------------------


def _tach_blob(blob: str) -> tuple[bytes, bytes, bytes]:
    """Tách blob thành (nonce, thân bản mã, tag). Thư viện cryptography gộp tag
    16 byte cuối vào ngay sau bản mã, không lưu tách rời — xem docstring keyvault.
    """
    raw = base64.b64decode(blob)
    nonce, phan_con_lai = raw[:12], raw[12:]
    than_ban_ma, tag = phan_con_lai[:-16], phan_con_lai[-16:]
    return nonce, than_ban_ma, tag


def _ghep_lai(nonce: bytes, than_ban_ma: bytes, tag: bytes) -> str:
    return base64.b64encode(nonce + than_ban_ma + tag).decode()


def test_gia_mao_nonce_thi_giai_ma_that_bai():
    blob = encrypt_key("sk-du-lieu-can-bao-ve")
    nonce, than_ban_ma, tag = _tach_blob(blob)
    nonce_hong = bytes([nonce[0] ^ 0xFF]) + nonce[1:]
    with pytest.raises(DecryptionFailed):
        decrypt_key(_ghep_lai(nonce_hong, than_ban_ma, tag))


def test_gia_mao_than_ban_ma_thi_giai_ma_that_bai():
    blob = encrypt_key("sk-du-lieu-can-bao-ve")
    nonce, than_ban_ma, tag = _tach_blob(blob)
    than_hong = bytes([than_ban_ma[0] ^ 0xFF]) + than_ban_ma[1:]
    with pytest.raises(DecryptionFailed):
        decrypt_key(_ghep_lai(nonce, than_hong, tag))


def test_gia_mao_tag_thi_giai_ma_that_bai():
    blob = encrypt_key("sk-du-lieu-can-bao-ve")
    nonce, than_ban_ma, tag = _tach_blob(blob)
    tag_hong = bytes([tag[0] ^ 0xFF]) + tag[1:]
    with pytest.raises(DecryptionFailed):
        decrypt_key(_ghep_lai(nonce, than_ban_ma, tag_hong))


def test_sai_khoa_goc_thi_giai_ma_that_bai(monkeypatch):
    blob = encrypt_key("sk-du-lieu-can-bao-ve")
    monkeypatch.setenv("LLM_KEY_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    get_settings.cache_clear()
    with pytest.raises(DecryptionFailed):
        decrypt_key(blob)
