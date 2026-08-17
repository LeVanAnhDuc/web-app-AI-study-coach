import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select

from app.db import engine
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
async def test_smoke_hai_request_dong_thoi_thuong_chi_mot_thanh_cong(client):
    # SMOKE TEST, KHÔNG PHẢI BẰNG CHỨNG TÍNH NGUYÊN TỬ: bắn hai request /refresh thật sự
    # đồng thời (asyncio.gather) cùng dùng một refresh token vào Postgres thật, rồi đếm
    # số lượng 200/401 thay vì giả định thứ tự thắng. Trên Postgres cục bộ chạy nhanh,
    # cửa sổ giữa lúc đọc và lúc ghi rất hẹp, nên nếu cài đặt bị lùi về kiểu đọc-rồi-ghi
    # (check-then-write), test này chỉ bắt được lỗi một cách NGẪU NHIÊN — đo thực đạt
    # khoảng 1/5 lần chạy, không phải mọi lần. Một lần chạy xanh ở đây KHÔNG chứng minh
    # gì về tính nguyên tử; chốt chặn xác định cho việc đó là
    # test_cau_lenh_thu_hoi_la_mot_update_nguyen_tu_co_du_dieu_kien bên dưới, test này
    # chỉ để phát hiện sớm nếu cơ chế đồng thời hỏng hoàn toàn.
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
async def test_cau_lenh_thu_hoi_la_mot_update_nguyen_tu_co_du_dieu_kien(client):
    # CHỐT CHẶN XÁC ĐỊNH cho tính nguyên tử của Correction 1 — không phụ thuộc thời gian
    # hay may rủi lịch trình như test smoke phía trên. Thay vì quan sát hành vi (có thể
    # không lộ ra do race hẹp), test này bắt chính câu lệnh SQL thật được gửi tới Postgres
    # qua sự kiện before_cursor_execute của engine, rồi kiểm tra ĐÚNG HÌNH DẠNG câu lệnh
    # mà Correction 1 yêu cầu: một UPDATE refresh_tokens duy nhất mang đủ cả ba điều kiện
    # (token_hash, revoked_at IS NULL, expires_at) và có RETURNING. Một cài đặt kiểu
    # đọc-rồi-ghi (SELECT rồi UPDATE chỉ khóa theo khóa chính, không RETURNING) sẽ làm
    # test này thất bại MỌI LẦN, không phải ngẫu nhiên.
    tokens = await _dang_nhap(client, "rf9@vidu.vn")

    cau_lenh_da_chay: list[str] = []

    def _ghi_lai_cau_lenh(conn, cursor, statement, parameters, context, executemany):
        cau_lenh_da_chay.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _ghi_lai_cau_lenh)
    try:
        response = await client.post(
            "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _ghi_lai_cau_lenh)

    assert response.status_code == 200

    cau_update = [
        s for s in cau_lenh_da_chay if "update" in s.lower() and "refresh_tokens" in s.lower()
    ]
    assert len(cau_update) == 1, (
        f"kỳ vọng đúng 1 câu UPDATE refresh_tokens, thấy {len(cau_update)}: {cau_lenh_da_chay}"
    )

    # Chuẩn hóa: hạ chữ thường + gộp khoảng trắng, để không phụ thuộc cách SQLAlchemy
    # xuống dòng/thụt lề câu lệnh (không phụ thuộc định dạng bề mặt).
    chuan_hoa = " ".join(cau_update[0].split()).lower()
    assert "token_hash" in chuan_hoa
    assert "revoked_at is null" in chuan_hoa
    assert "expires_at >" in chuan_hoa
    assert "returning" in chuan_hoa


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
