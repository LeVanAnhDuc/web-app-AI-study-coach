import pytest


async def _dang_ky(client, email: str, password: str = "mat-khau-du-dai") -> None:
    response = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_dang_nhap_dung_thi_nhan_duoc_token(client):
    await _dang_ky(client, "dung@vidu.vn")
    response = await client.post(
        "/api/auth/login",
        json={"email": "dung@vidu.vn", "password": "mat-khau-du-dai"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["expires_in"] == 900


@pytest.mark.asyncio
async def test_sai_mat_khau_bi_tu_choi(client):
    await _dang_ky(client, "saimk@vidu.vn")
    response = await client.post(
        "/api/auth/login",
        json={"email": "saimk@vidu.vn", "password": "mat-khau-sai-roi"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Email hoặc mật khẩu không đúng."


@pytest.mark.asyncio
async def test_email_khong_ton_tai_tra_cung_thong_bao(client):
    response = await client.post(
        "/api/auth/login",
        json={"email": "khongco@vidu.vn", "password": "mat-khau-du-dai"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Email hoặc mật khẩu không đúng."


@pytest.mark.asyncio
async def test_sai_mat_khau_va_email_khong_ton_tai_giong_het_nhau(client):
    # Đóng kênh rò rỉ qua thời gian phản hồi không thể kiểm bằng test đơn vị,
    # nhưng phản hồi quan sát được (status + message) của hai trường hợp phải
    # giống hệt nhau để không có cách nào phân biệt chúng từ bên ngoài.
    await _dang_ky(client, "saikhac@vidu.vn")
    sai_mat_khau = await client.post(
        "/api/auth/login",
        json={"email": "saikhac@vidu.vn", "password": "mat-khau-sai-roi"},
    )
    email_la = await client.post(
        "/api/auth/login",
        json={"email": "chuadangky@vidu.vn", "password": "mat-khau-bat-ky"},
    )
    assert sai_mat_khau.status_code == email_la.status_code == 401
    assert sai_mat_khau.json() == email_la.json()


@pytest.mark.asyncio
async def test_me_tra_ve_nguoi_dung_dang_dang_nhap(client):
    await _dang_ky(client, "me@vidu.vn")
    login = await client.post(
        "/api/auth/login",
        json={"email": "me@vidu.vn", "password": "mat-khau-du-dai"},
    )
    token = login.json()["access_token"]

    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "me@vidu.vn"


@pytest.mark.asyncio
async def test_me_khong_co_token_thi_bi_chan(client):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_token_rac_thi_bi_chan(client):
    response = await client.get(
        "/api/auth/me", headers={"Authorization": "Bearer khong-phai-token"}
    )
    assert response.status_code == 401
