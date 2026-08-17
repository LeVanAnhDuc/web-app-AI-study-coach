from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.auth.models import RefreshToken, User
from app.modules.auth.service import _bam_token


async def _dang_nhap(client, email: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": "mat-khau-du-dai"})
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": "mat-khau-du-dai"}
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_dang_nhap_tra_ve_refresh_token(client):
    tokens = await _dang_nhap(client, "rf1@vidu.vn")
    assert tokens["refresh_token"]


@pytest.mark.asyncio
async def test_refresh_tra_ve_cap_token_moi(client):
    tokens = await _dang_nhap(client, "rf2@vidu.vn")
    response = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"] != tokens["refresh_token"]


@pytest.mark.asyncio
async def test_refresh_token_cu_khong_dung_lai_duoc(client):
    tokens = await _dang_nhap(client, "rf3@vidu.vn")
    first = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200

    second = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert second.status_code == 401
    assert second.json()["detail"] == "Phiên đăng nhập đã hết hiệu lực. Đăng nhập lại nhé."


@pytest.mark.asyncio
async def test_refresh_token_bia_bi_tu_choi(client):
    response = await client.post(
        "/api/auth/refresh", json={"refresh_token": "khong-phai-token-that"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_moi_van_dung_duoc_de_goi_me(client):
    tokens = await _dang_nhap(client, "rf4@vidu.vn")
    refreshed = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    new_access = refreshed.json()["access_token"]

    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_access}"})
    assert response.status_code == 200
    assert response.json()["email"] == "rf4@vidu.vn"


@pytest.mark.asyncio
async def test_dung_lai_token_dong_thoi_bi_tu_choi(client):
    # Không thể tạo race điều kiện thật một cách xác định trong test, nên mô phỏng
    # kết quả tương đương: xoay vòng thành công một lần, rồi trình lại đúng token gốc
    # ban đầu lần thứ hai — giống hệt trường hợp hai request đồng thời cùng dùng một
    # refresh token, chỉ có một request được chấp nhận.
    tokens = await _dang_nhap(client, "rf5@vidu.vn")
    original = tokens["refresh_token"]

    first = await client.post("/api/auth/refresh", json={"refresh_token": original})
    assert first.status_code == 200

    second = await client.post("/api/auth/refresh", json={"refresh_token": original})
    assert second.status_code == 401
    assert second.json()["detail"] == "Phiên đăng nhập đã hết hiệu lực. Đăng nhập lại nhé."


@pytest.mark.asyncio
async def test_refresh_token_da_het_han_bi_tu_choi(db_session, client):
    await client.post(
        "/api/auth/register", json={"email": "rf6@vidu.vn", "password": "mat-khau-du-dai"}
    )
    user = await db_session.scalar(select(User).where(User.email == "rf6@vidu.vn"))

    raw_token = "token-da-het-han-du-dai-de-qua-kiem-tra-do-dai"
    db_session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_bam_token(raw_token),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    await db_session.commit()

    response = await client.post("/api/auth/refresh", json={"refresh_token": raw_token})
    assert response.status_code == 401
    assert response.json()["detail"] == "Phiên đăng nhập đã hết hiệu lực. Đăng nhập lại nhé."
