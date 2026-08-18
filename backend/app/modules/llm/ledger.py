"""Sổ ghi token: bản ghi mọi lời gọi LLM đã tiêu tốn bao nhiêu token.

Đây là mặt bằng BÁO CÁO, không phải cơ chế THỰC THI hạn mức — thùng token
Redis (ratelimit.py) mới là lá chắn thực thi hạn mức theo thời gian thực, và
nó đã trừ token TRƯỚC KHI lời gọi provider được thực hiện. Vì vậy một dòng sổ
bị mất chỉ làm sai số liệu báo cáo, không làm thủng lá chắn hạn mức — đây
chính là lý do Ruling 3 (ghi thất bại không được huỷ kết quả LLM đã thành
công) không mâu thuẫn với Ruling 1 (phải ghi mọi lần thử).

Không dùng đọc-sửa-ghi (SELECT tổng rồi UPDATE lại) để cộng dồn: hai lời gọi
record_usage() chạy đồng thời có thể cùng đọc một tổng cũ rồi cùng ghi đè,
làm mất một trong hai lần cộng — đúng lớp lỗi đã gặp hai lần trong dự án này
(xoay refresh token, và bộ giới hạn hạn mức). Ở đây chọn CHÈN-CHỈ-THÊM (mỗi
lời gọi provider sinh đúng MỘT dòng mới, không đọc dòng cũ): usage_summary()
CỘNG DỒN LÚC ĐỌC bằng SUM() của CSDL, không có trạng thái nào bị đọc-rồi-ghi
ở phía Python, nên không có cửa sổ đua nào để hai lời gọi cùng lúc giẫm lên
nhau.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.modules.llm.types import TaskType, Usage

_log = logging.getLogger(__name__)


class TokenLedger(Base):
    """Một dòng = một lời gọi LLM nghiệp vụ (đã gộp mọi lần thử lại).

    CHỈ lưu số đếm và siêu dữ liệu định tuyến (provider, model, task) — TUYỆT
    ĐỐI không lưu nội dung prompt/response hay bất kỳ định danh cá nhân nào
    (email, tên...). Lý do kép: (1) các provider free-tier có thể dùng dữ
    liệu prompt để huấn luyện mô hình của họ, nên quy tắc của dự án là định
    danh không bao giờ được đưa vào prompt — sổ này copy nội dung đó vào CSDL
    của chính mình sẽ tái tạo lại đúng rủi ro rò rỉ ấy; (2) nội dung
    prompt/response phình vô hạn theo thời gian, còn số đếm thì không.
    `user_id` là khoá ngoại MỜ (chỉ là UUID), không phải nội dung, nên được
    phép có mặt.
    """

    __tablename__ = "token_ledger"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), index=True, nullable=True
    )
    task: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # timezone=True: cột PostgreSQL kiểu TIMESTAMPTZ, lưu UTC bên trong. Cột
    # naive sẽ âm thầm mang nghĩa "giờ địa phương của tiến trình vừa ghi" —
    # tổng hợp theo ngày/tháng (mục đích chính của sổ này) sẽ sai lệch theo
    # múi giờ triển khai, và test chạy trên một múi giờ duy nhất sẽ không bao
    # giờ phát hiện ra sai số đó.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )


async def record_usage(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    task: TaskType,
    usages: list[Usage],
    succeeded: bool,
) -> None:
    """Gộp mọi lần thử của MỘT lời gọi nghiệp vụ thành ĐÚNG MỘT dòng sổ.

    `usages` phải là usage của TỪNG lần thử (kể cả các lần thất bại schema),
    đúng như `complete_structured()` trả về — không chỉ lần cuối thành công.
    Bỏ sót các lần thử thất bại sẽ khiến số liệu báo cáo THẤP HƠN mức tiêu
    thụ thật, và thấp hơn thật là hướng nguy hiểm: nó khiến ứng dụng trông rẻ
    hơn thực tế, cho tới đúng ngày hạn mức miễn phí cạn sớm hơn số liệu dự
    báo.

    Danh sách rỗng thì không ghi gì — không có lời gọi provider nào xảy ra
    thì không có gì để ghi vào sổ.

    Ghi thất bại (CSDL tạm thời không phản hồi) KHÔNG được ném ngoại lệ ra
    ngoài: tới lúc hàm này chạy, token đã bị tiêu thật (thùng Redis đã trừ
    trước khi gọi provider) và câu trả lời cho người dùng đã có sẵn — huỷ nó
    chỉ vì không ghi được một dòng thống kê là biến một lời gọi ĐÃ THÀNH CÔNG
    thành lỗi mà không giúp ích gì. Lỗi vẫn phải được LOG rõ ràng (không nuốt
    lặng lẽ) để có thể theo dõi tần suất mất dòng.
    """
    if not usages:
        return

    session.add(
        TokenLedger(
            user_id=user_id,
            task=task.value,
            provider=usages[-1].provider,
            model=usages[-1].model,
            input_tokens=sum(u.input_tokens for u in usages),
            output_tokens=sum(u.output_tokens for u in usages),
            attempts=len(usages),
            succeeded=succeeded,
        )
    )
    try:
        await session.commit()
    except SQLAlchemyError:
        # Bắt đúng SQLAlchemyError (gốc của mọi lỗi từ driver/CSDL: mất kết
        # nối, timeout, vi phạm ràng buộc...), không bắt Exception trần —
        # lỗi lập trình (ví dụ TypeError do gọi sai kiểu) vẫn phải nổ ra bình
        # thường để bị phát hiện ngay trong test/CI, chỉ lỗi THẬT SỰ đến từ
        # CSDL mới được coi là "chấp nhận mất một dòng báo cáo".
        await session.rollback()
        _log.error(
            "Ghi sổ token thất bại, bỏ qua dòng này (task=%s, provider=%s): "
            "CSDL không phản hồi hoặc từ chối ghi.",
            task.value,
            usages[-1].provider,
            exc_info=True,
        )


async def usage_summary(session: AsyncSession, user_id: uuid.UUID | None) -> dict[str, int]:
    """Cộng dồn LÚC ĐỌC bằng SUM()/COUNT() của CSDL — không có tổng nào được
    giữ và cập nhật ở phía Python, nên không có trạng thái nào có thể bị hai
    tiến trình đọc-rồi-ghi đè lên nhau."""
    hang = (
        await session.execute(
            select(
                func.coalesce(func.sum(TokenLedger.input_tokens), 0),
                func.coalesce(func.sum(TokenLedger.output_tokens), 0),
                func.count(),
            ).where(TokenLedger.user_id == user_id)
        )
    ).one()
    return {"input_tokens": hang[0], "output_tokens": hang[1], "calls": hang[2]}
