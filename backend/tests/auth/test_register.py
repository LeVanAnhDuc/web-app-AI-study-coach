import pytest
from sqlalchemy.ext.asyncio import AsyncSession


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
