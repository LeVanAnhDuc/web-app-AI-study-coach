import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import REDACTED_INPUT_MARKER, _an_khoa_nhay_cam


@pytest.mark.asyncio
async def test_dang_ky_thanh_cong(client):
    response = await client.post(
        "/api/auth/register",
        json={"email": "chi@vidu.vn", "password": "mat-khau-du-dai"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "chi@vidu.vn"
    assert "id" in body
    assert "password" not in body
    assert "password_hash" not in body


@pytest.mark.asyncio
async def test_dang_ky_trung_email_bi_tu_choi(client):
    payload = {"email": "trung@vidu.vn", "password": "mat-khau-du-dai"}
    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/auth/register", json=payload)
    assert second.status_code == 409
    assert second.json()["detail"] == "Email này đã được đăng ký."


@pytest.mark.asyncio
async def test_email_duoc_chuan_hoa_ve_chu_thuong(client):
    response = await client.post(
        "/api/auth/register",
        json={"email": "HOA@ViDu.VN", "password": "mat-khau-du-dai"},
    )
    assert response.status_code == 201
    assert response.json()["email"] == "hoa@vidu.vn"


@pytest.mark.asyncio
async def test_mat_khau_qua_ngan_bi_tu_choi(client):
    response = await client.post(
        "/api/auth/register",
        json={"email": "ngan@vidu.vn", "password": "ngan"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_mat_khau_qua_dai_bi_tu_choi(client):
    response = await client.post(
        "/api/auth/register",
        json={"email": "dai@vidu.vn", "password": "a" * 129},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_mat_khau_khong_bi_lo_trong_loi_422(client):
    mat_khau_nhay_cam = "shortpw"
    response = await client.post(
        "/api/auth/register",
        json={"email": "checkloi@vidu.vn", "password": mat_khau_nhay_cam},
    )
    assert response.status_code == 422
    assert mat_khau_nhay_cam not in response.text


@pytest.mark.asyncio
async def test_loi_validate_thong_thuong_van_hien_input(client):
    email_khong_hop_le = "khong-phai-email"
    response = await client.post(
        "/api/auth/register",
        json={"email": email_khong_hop_le, "password": "mat-khau-du-dai"},
    )
    assert response.status_code == 422
    body = response.json()
    loi_email = next(e for e in body["detail"] if e["loc"][-1] == "email")
    assert loi_email["input"] == email_khong_hop_le


@pytest.mark.asyncio
async def test_dang_ky_dua_theo_race_condition_tra_ve_409(client, monkeypatch):
    payload = {"email": "dua@vidu.vn", "password": "mat-khau-du-dai"}
    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == 201

    async def gia_lap_khong_tim_thay(self, *args, **kwargs):
        return None

    monkeypatch.setattr(AsyncSession, "scalar", gia_lap_khong_tim_thay)

    second = await client.post("/api/auth/register", json=payload)
    assert second.status_code == 409
    assert second.json()["detail"] == "Email này đã được đăng ký."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "duong_dan", ["/api/auth/register", "/api/auth/login", "/api/auth/refresh"]
)
async def test_mat_khau_khong_bi_lo_khi_than_request_sai_kieu(client, duong_dan):
    """C-12 lần thứ hai, qua một đường mà bản vá gốc không xét tới.

    Khi thân request sai KIỂU (mảng hoặc chuỗi thay vì object), pydantic báo
    `loc == ["body"]` — KHÔNG có tên trường nào ở `loc[-1]` — và đặt TOÀN BỘ
    thân request vào `input`. Bản vá gốc chỉ redact khi `loc[-1]` nằm trong
    `SENSITIVE_FIELD_NAMES`, nên nó không chạm tới lỗi cấp thân: mật khẩu dạng
    rõ quay lại trình duyệt (và BFF chuyển tiếp thân này nguyên văn).

    ĐÃ QUAN SÁT TRƯỚC KHI SỬA: test này ĐỎ trên cả ba đường (`assert
    mat_khau_nhay_cam not in response.text` thất bại), trong khi
    `test_mat_khau_khong_bi_lo_trong_loi_422` vẫn XANH — vì test đó gửi một
    thân ĐÚNG KIỂU, tức đúng cái đầu vào duy nhất mà handler xử lý đúng. Đó là
    lý do bộ test cũ chứng nhận điều ngược lại với hành vi thật của mã.
    """
    mat_khau_nhay_cam = "SieuMatKhauCuaToi2026!"
    than_mang = [{"email": "mang@vidu.vn", "password": mat_khau_nhay_cam}]

    for than in (than_mang, mat_khau_nhay_cam):
        response = await client.post(duong_dan, json=than)
        assert response.status_code == 422
        assert mat_khau_nhay_cam not in response.text
        # Ràng buộc C-22: frontend chốt kiểu trên `detail`, phải giữ nguyên mảng.
        assert isinstance(response.json()["detail"], list)


@pytest.mark.asyncio
async def test_refresh_token_khong_bi_lo_khi_than_request_sai_kieu(client):
    """Cùng lỗ với test trên nhưng cho `refresh_token` — trường nhạy cảm của
    `/refresh`. Cũng ĐỎ trước khi sửa."""
    token_nhay_cam = "refresh-token-rat-dac-biet-2026"
    response = await client.post("/api/auth/refresh", json=[{"refresh_token": token_nhay_cam}])
    assert response.status_code == 422
    assert token_nhay_cam not in response.text


def test_an_khoa_nhay_cam_di_de_quy_va_giu_lai_truong_thuong():
    """GHIM HƯỚNG TỚI TƯƠNG LAI (không phải test phân biệt hồi quy): các schema
    auth hiện tại đều PHẲNG, nên nhánh đệ quy chưa có đường đi tới từ HTTP.
    Ghim ở đây để một schema LỒNG trong mốc sau không âm thầm rò mật khẩu qua
    `input` của lỗi báo ở cấp cha, và để việc redact không lan sang trường
    thường (ruling gốc C-12: 422 phải còn dùng được khi gỡ lỗi)."""
    ket_qua = _an_khoa_nhay_cam(
        {
            "email": "vidu@vidu.vn",
            "password": "mat-khau-that",
            "ho_so": {"api_key": "khoa-that", "ten": "Chi"},
            "danh_sach": [{"secret": "bi-mat", "ghi_chu": "thuong"}],
        }
    )
    assert ket_qua == {
        "email": "vidu@vidu.vn",
        "password": REDACTED_INPUT_MARKER,
        "ho_so": {"api_key": REDACTED_INPUT_MARKER, "ten": "Chi"},
        "danh_sach": [{"secret": REDACTED_INPUT_MARKER, "ghi_chu": "thuong"}],
    }
