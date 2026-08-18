"""Test cho sổ ghi token (Task 17).

Sáu test đầu lấy verbatim từ task-17-brief.md. Ba test cuối chứng minh cấu
trúc cho Ruling 2 (không đọc-sửa-ghi) và Ruling 3 (ghi thất bại không được
làm mất kết quả LLM đã thành công, và phải quan sát được khi mất).
"""

import logging
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

from app.db import engine
from app.modules.llm.ledger import TokenLedger, record_usage, usage_summary
from app.modules.llm.types import TaskType, Usage


def _usage(inp: int = 10, out: int = 20) -> Usage:
    return Usage(provider="gemini", model="m", input_tokens=inp, output_tokens=out)


@pytest.mark.asyncio
async def test_ghi_mot_lan_goi_thanh_cong(db_session):
    user_id = uuid.uuid4()
    await record_usage(db_session, user_id, TaskType.GENERATE_QUIZ, [_usage()], succeeded=True)

    row = await db_session.scalar(select(TokenLedger).where(TokenLedger.user_id == user_id))
    assert row.task == "generate_quiz"
    assert row.provider == "gemini"
    assert row.input_tokens == 10
    assert row.output_tokens == 20
    assert row.attempts == 1
    assert row.succeeded is True


@pytest.mark.asyncio
async def test_nhieu_lan_thu_duoc_gop_thanh_mot_dong(db_session):
    user_id = uuid.uuid4()
    await record_usage(
        db_session,
        user_id,
        TaskType.GENERATE_SYLLABUS,
        [_usage(5, 5), _usage(6, 7)],
        succeeded=True,
    )

    row = await db_session.scalar(select(TokenLedger).where(TokenLedger.user_id == user_id))
    assert row.attempts == 2
    assert row.input_tokens == 11
    assert row.output_tokens == 12


@pytest.mark.asyncio
async def test_lan_goi_that_bai_van_duoc_ghi(db_session):
    user_id = uuid.uuid4()
    await record_usage(db_session, user_id, TaskType.GENERATE_QUIZ, [_usage()], succeeded=False)
    row = await db_session.scalar(select(TokenLedger).where(TokenLedger.user_id == user_id))
    assert row.succeeded is False


@pytest.mark.asyncio
async def test_khong_ghi_gi_khi_danh_sach_usage_rong(db_session):
    user_id = uuid.uuid4()
    await record_usage(db_session, user_id, TaskType.TUTOR_CHAT, [], succeeded=False)
    dem = await db_session.scalar(
        select(func.count()).select_from(TokenLedger).where(TokenLedger.user_id == user_id)
    )
    assert dem == 0


@pytest.mark.asyncio
async def test_ghi_duoc_lan_goi_khong_gan_voi_nguoi_dung(db_session):
    await record_usage(db_session, None, TaskType.GENERATE_LESSON, [_usage()], succeeded=True)
    row = await db_session.scalar(select(TokenLedger).where(TokenLedger.task == "generate_lesson"))
    assert row.user_id is None


@pytest.mark.asyncio
async def test_tong_hop_theo_nguoi_dung(db_session):
    user_id = uuid.uuid4()
    await record_usage(db_session, user_id, TaskType.GENERATE_QUIZ, [_usage(3, 4)], True)
    await record_usage(db_session, user_id, TaskType.GENERATE_LESSON, [_usage(5, 6)], True)

    tong = await usage_summary(db_session, user_id)
    assert tong["input_tokens"] == 8
    assert tong["output_tokens"] == 10
    assert tong["calls"] == 2


@pytest.mark.asyncio
async def test_ghi_khong_doc_truoc_khi_ghi(db_session):
    """Ruling 2: chứng minh CẤU TRÚC (không phải bằng race timing) rằng
    record_usage() chỉ phát ra INSERT, không có SELECT nào đi trước nó — tức
    là không có cặp đọc-rồi-ghi nào có thể bị hai tiến trình đâm vào nhau.

    Bắt sự kiện before_cursor_execute ở tầng engine để thấy đúng câu SQL thật
    được gửi xuống driver, không suy luận từ mã nguồn (mã nguồn có thể đổi mà
    hành vi SQL thật lại khác).
    """
    cau_lenh: list[str] = []

    def _bat_su_kien(conn, cursor, statement, parameters, context, executemany):
        tu_dau = statement.strip().split(None, 1)[0].upper()
        cau_lenh.append(tu_dau)

    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _bat_su_kien)
    try:
        await record_usage(
            db_session, uuid.uuid4(), TaskType.GENERATE_QUIZ, [_usage()], succeeded=True
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", _bat_su_kien)

    assert "SELECT" not in cau_lenh, f"phát hiện SELECT trong record_usage(): {cau_lenh}"
    assert cau_lenh.count("INSERT") == 1, f"kỳ vọng đúng 1 INSERT, thấy: {cau_lenh}"


@pytest.mark.asyncio
async def test_ghi_that_bai_khong_lam_mat_ket_qua_da_thanh_cong(db_session, monkeypatch, caplog):
    """Ruling 3: CSDL tạm thời không phản hồi khi ghi sổ không được phép ném
    ngoại lệ lên trên — kết quả LLM (đã tốn token thật) không được vì lỗi ghi
    sổ mà biến từ thành công thành thất bại. Nhưng việc mất dòng phải quan sát
    được (log lỗi), không được nuốt lặng lẽ.
    """
    loi_gia_lap = OperationalError("INSERT INTO token_ledger ...", {}, Exception("mat ket noi"))
    monkeypatch.setattr(db_session, "commit", AsyncMock(side_effect=loi_gia_lap))
    monkeypatch.setattr(db_session, "rollback", AsyncMock())

    with caplog.at_level(logging.ERROR):
        # Không được ném ngoại lệ ra ngoài.
        await record_usage(
            db_session, uuid.uuid4(), TaskType.GENERATE_QUIZ, [_usage()], succeeded=True
        )

    loi_duoc_ghi_log = [rec for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert len(loi_duoc_ghi_log) == 1
    assert "ghi" in loi_duoc_ghi_log[0].getMessage().lower()
    db_session.rollback.assert_awaited_once()
