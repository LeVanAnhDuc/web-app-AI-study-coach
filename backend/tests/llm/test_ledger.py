"""Test cho sổ ghi token (Task 17).

Sáu test đầu lấy verbatim từ task-17-brief.md. Các test còn lại chứng minh
cấu trúc cho Ruling 2 (không đọc-sửa-ghi), Ruling 3 (ghi thất bại không được
làm mất kết quả LLM đã thành công, và phải quan sát được khi mất) và các mục
review sau đó: từ chối usages hỗn hợp nhiều provider/model (mục 1), cảnh báo
khi session không dành riêng (mục 3), và log lỗi phải đủ số liệu để đối soát
(mục 4).
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
@pytest.mark.parametrize(
    "loi_gia_lap",
    [
        # ConnectionRefusedError (CSDL CHẾT HẲN, không lắng nghe cổng nào) là
        # một OSError, KHÔNG phải SQLAlchemyError — trước bản sửa nó thoát khỏi
        # `except SQLAlchemyError` và phá huỷ một câu trả lời LLM đã trả tiền.
        # Đặt TRƯỚC để nó là trường hợp đầu tiên đọc thấy.
        pytest.param(ConnectionRefusedError(1225, "khong ket noi duoc tới CSDL"), id="os-error"),
        # OperationalError (CSDL còn sống nhưng lệnh thất bại) là trường hợp
        # gốc — GIỮ LẠI để cả hai lớp đều bị ghim, không phải thay thế.
        pytest.param(
            OperationalError("INSERT INTO token_ledger ...", {}, Exception("mat ket noi")),
            id="sqlalchemy-error",
        ),
    ],
)
async def test_ghi_that_bai_khong_lam_mat_ket_qua_da_thanh_cong(
    db_session, monkeypatch, caplog, loi_gia_lap
):
    """Ruling 3: CSDL tạm thời không phản hồi khi ghi sổ không được phép ném
    ngoại lệ lên trên — kết quả LLM (đã tốn token thật) không được vì lỗi ghi
    sổ mà biến từ thành công thành thất bại. Nhưng việc mất dòng phải quan sát
    được (log lỗi), không được nuốt lặng lẽ.

    ĐÃ QUAN SÁT TRƯỚC KHI SỬA: bản cũ của test này CHỈ tiêm `OperationalError`
    — đúng lớp duy nhất `except SQLAlchemyError` bắt được — nên nó không thể
    đỏ dù `record_usage()` để lọt mọi lỗi hạ tầng ở tầng socket. Trường hợp
    `os-error` mới thêm ĐỎ trước khi sửa (ConnectionRefusedError thoát nguyên
    vẹn ra khỏi `record_usage()`); trường hợp `sqlalchemy-error` vẫn xanh cả
    trước và sau, và tồn tại để bản sửa không âm thầm đánh mất lớp cũ.
    """
    monkeypatch.setattr(db_session, "commit", AsyncMock(side_effect=loi_gia_lap))
    monkeypatch.setattr(db_session, "rollback", AsyncMock())

    with caplog.at_level(logging.ERROR):
        # Không được ném ngoại lệ ra ngoài.
        await record_usage(
            db_session, uuid.uuid4(), TaskType.GENERATE_QUIZ, [_usage()], succeeded=True
        )

    loi_duoc_ghi_log = [rec for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert len(loi_duoc_ghi_log) == 1
    noi_dung = loi_duoc_ghi_log[0].getMessage().lower()
    assert "ghi" in noi_dung
    # Review mục 4: log phải đủ số liệu để đối soát mất bao nhiêu, không chỉ
    # biết "có mất". _usage() mặc định input=10, output=20, model="m",
    # attempts=1 (một phần tử usages).
    assert "input_tokens=10" in noi_dung
    assert "output_tokens=20" in noi_dung
    assert "model=m " in noi_dung
    assert "attempts=1" in noi_dung
    db_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_tu_choi_danh_sach_nhieu_provider(db_session):
    """Review mục 1 (Critical): usages hỗn hợp nhiều provider phải bị TỪ CHỐI
    bằng ValueError, không được âm thầm gộp thành một dòng theo usages[-1] —
    hành vi cũ đó gán nhầm toàn bộ token của Gemini/Groq cho Mistral trong dữ
    liệu, đúng chiều mà nhiệm vụ so sánh chi phí theo provider phải phát hiện.
    """
    hon_hop = [
        Usage(provider="gemini", model="g1", input_tokens=100, output_tokens=50),
        Usage(provider="groq", model="q1", input_tokens=200, output_tokens=100),
        Usage(provider="mistral", model="m1", input_tokens=300, output_tokens=100),
    ]
    user_id = uuid.uuid4()
    with pytest.raises(ValueError, match="nhiều provider"):
        await record_usage(db_session, user_id, TaskType.GENERATE_QUIZ, hon_hop, succeeded=True)

    dem = await db_session.scalar(
        select(func.count()).select_from(TokenLedger).where(TokenLedger.user_id == user_id)
    )
    assert dem == 0


@pytest.mark.asyncio
async def test_tu_choi_danh_sach_nhieu_model_cung_provider(db_session):
    """Cùng provider nhưng khác model cũng phải bị từ chối — model là một
    phần của cột chi phí (giá mỗi model một khác), gộp nhầm model cũng sai
    y hệt như gộp nhầm provider."""
    hon_hop = [
        Usage(provider="gemini", model="gemini-1.5-flash", input_tokens=10, output_tokens=5),
        Usage(provider="gemini", model="gemini-1.5-pro", input_tokens=20, output_tokens=10),
    ]
    with pytest.raises(ValueError):
        await record_usage(
            db_session, uuid.uuid4(), TaskType.GENERATE_QUIZ, hon_hop, succeeded=True
        )


@pytest.mark.asyncio
async def test_canh_bao_khi_session_co_thay_doi_chua_luu(db_session, caplog):
    """Review mục 3 (Important): record_usage() cần một session DÀNH RIÊNG.
    Nếu session còn mang theo thay đổi khác của caller chưa lưu, hàm phải LOG
    CẢNH BÁO (không raise — raise ở đây sẽ huỷ một kết quả LLM đã thành công,
    đúng điều Ruling 3 cấm) để lộ ra lỗi dùng sai của caller.
    """
    # Mô phỏng "thay đổi khác của caller" còn treo trên session dùng chung —
    # đúng kịch bản reviewer đã tái tạo (một User chưa commit bị commit/rollback
    # kèm theo).
    db_session.add(
        TokenLedger(
            user_id=None,
            task="mo_phong_thay_doi_khac_cua_caller",
            provider="gemini",
            model="m",
            input_tokens=0,
            output_tokens=0,
            attempts=1,
            succeeded=True,
        )
    )

    with caplog.at_level(logging.WARNING):
        await record_usage(
            db_session, uuid.uuid4(), TaskType.GENERATE_QUIZ, [_usage()], succeeded=True
        )

    canh_bao = [
        rec
        for rec in caplog.records
        if rec.levelno == logging.WARNING and "session" in rec.getMessage().lower()
    ]
    assert len(canh_bao) == 1
