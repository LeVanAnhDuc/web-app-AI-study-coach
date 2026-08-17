import asyncio
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
async def test_hai_request_dong_thoi_dung_chung_token_chi_mot_thanh_cong(client):
    # Test này tồn tại để chứng minh việc thu hồi là NGUYÊN TỬ ở tầng CSDL: bắn hai
    # request /refresh thật sự đồng thời (asyncio.gather) cùng dùng một refresh token
    # vào cùng một Postgres. Nếu revoke bị lùi lại thành kiểu đọc-rồi-ghi (check rồi mới
    # UPDATE) như bản nháp ban đầu của task, cả hai coroutine có thể cùng đọc thấy token
    # chưa bị thu hồi và cùng thành công — test này sẽ thất bại (2 status 200 thay vì
    # đúng một 200 và một 401). Đừng nhầm với test tuần tự phía trên: test đó chỉ chứng
    # minh việc dùng lại token cũ bị chặn, không chứng minh gì về tính nguyên tử.
    tokens = await _dang_nhap(client, "rf5@vidu.vn")
    original = tokens["refresh_token"]

    responses = await asyncio.gather(
        client.post("/api/auth/refresh", json={"refresh_token": original}),
        client.post("/api/auth/refresh", json={"refresh_token": original}),
        return_exceptions=False,
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 401]

    thanh_cong = next(r for r in responses if r.status_code == 200)
    that_bai = next(r for r in responses if r.status_code == 401)
    assert that_bai.json()["detail"] == "Phiên đăng nhập đã hết hiệu lực. Đăng nhập lại nhé."
    assert thanh_cong.json()["refresh_token"] != original


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
