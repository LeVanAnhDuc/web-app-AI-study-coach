import pytest


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
