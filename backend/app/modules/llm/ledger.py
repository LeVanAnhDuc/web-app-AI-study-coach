"""Sổ ghi token: bản ghi mọi lời gọi LLM đã tiêu tốn bao nhiêu token.

Đây là mặt bằng BÁO CÁO, không phải cơ chế THỰC THI hạn mức — thùng token
Redis (ratelimit.py) mới là lá chắn thực thi hạn mức theo thời gian thực, và
nó đã trừ token TRƯỚC KHI lời gọi provider được thực hiện. Vì vậy một dòng sổ
bị mất chỉ làm sai số liệu báo cáo, không làm thủng lá chắn hạn mức — đây
chính là lý do Ruling 3 (ghi thất bại không được huỷ kết quả LLM đã thành
công) không mâu thuẫn với Ruling 1 (phải ghi mọi lần thử).

GIỚI HẠN CỦA LẬP LUẬN TRÊN, ghi rõ để không ai dựa vào nó quá mức: thùng token
chỉ thực thi ngân sách theo PHÚT, không theo NGÀY (xem docstring ratelimit.py).
Nên "mất một dòng sổ không làm thủng lá chắn" đúng với hạn mức phút, và CHỈ
đúng với hạn mức phút. Với hạn mức NGÀY thì hiện chưa có lá chắn nào cả, và sổ
này là nguồn dữ liệu DUY NHẤT để một bộ ngắt theo ngày trong tương lai đọc —
tức là mỗi dòng bị mất sẽ trực tiếp làm bộ ngắt đó đếm thiếu. Ruling 3 vẫn
đúng (huỷ một câu trả lời đã trả tiền vì lỗi ghi sổ là tệ hơn), nhưng lý do
"mất một dòng là vô hại" thì không: nó chỉ vô hại HÔM NAY, khi chưa ai đọc sổ
để ra quyết định. Xem mục hoãn cạnh `PROVIDER_RPM` trong routing.py.

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


async def _rollback_khong_ne_loi(session: AsyncSession) -> None:
    """Hoàn tác, và KHÔNG BAO GIỜ để việc hoàn tác tự nó ném ra ngoài.

    Khi commit thất bại vì CSDL đã chết, `rollback()` đi lại đúng con đường
    vừa hỏng và có thể ném cùng một lỗi. Nếu để nó thoát ra, bản sửa
    `except (SQLAlchemyError, OSError)` ở trên thành vô nghĩa: câu trả lời LLM
    đã trả tiền vẫn bị phá huỷ, chỉ là bởi dòng dọn dẹp thay vì bởi dòng ghi.
    Nuốt ở ĐÚNG hai lớp đó (không phải `Exception` trần) rồi để lời gọi
    `_log.error` phía sau ghi lại đầy đủ số liệu đã mất.
    """
    try:
        await session.rollback()
    except (SQLAlchemyError, OSError):
        _log.warning(
            "rollback() sau khi ghi sổ token thất bại cũng thất bại — CSDL có thể "
            "đã chết hoàn toàn. Bỏ qua để không phá huỷ kết quả LLM đã thành công.",
            exc_info=True,
        )


async def record_usage(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    task: TaskType,
    usages: list[Usage],
    succeeded: bool,
) -> None:
    """Gộp mọi lần thử của MỘT lời gọi nghiệp vụ, của ĐÚNG MỘT provider/model,
    thành ĐÚNG MỘT dòng sổ.

    `usages` phải là usage của TỪNG lần thử (kể cả các lần thất bại schema),
    đúng như `complete_structured()` trả về — không chỉ lần cuối thành công.
    Bỏ sót các lần thử thất bại sẽ khiến số liệu báo cáo THẤP HƠN mức tiêu
    thụ thật, và thấp hơn thật là hướng nguy hiểm: nó khiến ứng dụng trông rẻ
    hơn thực tế, cho tới đúng ngày hạn mức miễn phí cạn sớm hơn số liệu dự
    báo.

    `usages` PHẢI đến từ cùng một provider/model. Nếu tầng định tuyến (router)
    rơi từ provider này xuống provider khác trong cùng một lượt xử lý — ví dụ
    Gemini rate-limit rồi rơi xuống Groq — thì đó là HAI usage thuộc về HAI
    provider khác nhau, và hàm này phải được gọi RIÊNG cho từng provider, mỗi
    lần với đúng danh sách usages của provider đó. record_usage() TỪ CHỐI
    (ValueError) một danh sách hỗn hợp thay vì tự tách thành nhiều dòng: tách
    ở đây sẽ đổi cả cardinality của hàm (một lời gọi có thể sinh ra một hoặc
    nhiều dòng, tuỳ dữ liệu) và làm `attempts` trên mỗi dòng trở nên mơ hồ
    (attempts của dòng nào?). Router — không phải hàm này — mới biết usage
    nào thuộc provider nào, nên quyết định "tách thế nào" phải nằm ở phía
    router, và thất bại phải ồn ào ngay lúc phát triển thay vì âm thầm gộp
    nhầm token của Gemini vào cột chi phí của Mistral trong dữ liệu.

    Danh sách rỗng thì không ghi gì — không có lời gọi provider nào xảy ra
    thì không có gì để ghi vào sổ.

    HỢP ĐỒNG VỀ `session`: đây PHẢI là một session DÀNH RIÊNG cho lời gọi
    record_usage() này, không dùng chung với các thay đổi khác của caller.
    Hàm tự `commit()` khi thành công và có thể `rollback()` TOÀN BỘ session
    khi ghi thất bại — nếu session này còn mang theo thay đổi khác của caller
    chưa lưu, commit() sẽ vô tình chốt luôn chúng, còn rollback() khi lỗi sẽ
    vô tình xoá mất chúng. Đây là THIẾT KẾ CÓ CHỦ Ý, không phải sơ suất: theo
    Ruling 3, một lời gọi LLM đã tiêu token thật (thùng Redis đã trừ) và đã
    có câu trả lời không được phép bị lỗi ghi sổ kéo theo thất bại — muốn vậy
    việc ghi sổ phải nằm trong một transaction ĐỘC LẬP, có thể tự thất bại
    một mình mà không kéo theo (hay bị kéo theo bởi) bất kỳ việc gì khác của
    caller. Nếu session được truyền vào còn thay đổi chưa lưu, hàm chỉ LOG
    CẢNH BÁO (không raise — raise ở đây sẽ lại huỷ một kết quả LLM đã thành
    công, đúng điều Ruling 3 cấm) để lộ ra lỗi dùng sai của caller.

    Ghi thất bại KHÔNG được ném ngoại lệ ra ngoài — CẢ khi CSDL tạm thời không
    phản hồi, CẢ khi nó chết hẳn (không lắng nghe cổng nào, tên host không phân
    giải được). Trường hợp thứ hai KHÔNG sinh ra `SQLAlchemyError` mà sinh ra
    `OSError` ở tầng socket, nên nó phải được bắt tường minh; xem chú thích tại
    khối `except` bên dưới. Tới lúc hàm này chạy, token đã bị tiêu thật (thùng Redis đã trừ
    trước khi gọi provider) và câu trả lời cho người dùng đã có sẵn — huỷ nó
    chỉ vì không ghi được một dòng thống kê là biến một lời gọi ĐÃ THÀNH CÔNG
    thành lỗi mà không giúp ích gì. Lỗi vẫn phải được LOG rõ ràng, kèm đủ số
    liệu (không phải nội dung) để sau này ĐỐI SOÁT được đã mất bao nhiêu, chứ
    không chỉ biết là "có mất".
    """
    if not usages:
        return

    providers = {u.provider for u in usages}
    models = {u.model for u in usages}
    if len(providers) > 1 or len(models) > 1:
        raise ValueError(
            f"record_usage() nhận usages từ nhiều provider/model khác nhau trong "
            f"cùng một lời gọi (providers={sorted(providers)}, models={sorted(models)}). "
            "Mỗi lời gọi record_usage() chỉ được ghi usage của ĐÚNG MỘT provider/model. "
            "Nếu router rơi xuống nhiều provider trong cùng một lượt xử lý, hãy gọi "
            "record_usage() RIÊNG cho từng provider, mỗi lần với đúng usages của "
            "provider đó."
        )

    if session.new or session.dirty:
        _log.warning(
            "record_usage() được gọi trên một session đang có thay đổi chưa lưu "
            "(session.new=%d, session.dirty=%d). Hàm này tự commit()/rollback() TOÀN "
            "BỘ session, nên các thay đổi khác của caller sẽ bị ảnh hưởng theo — "
            "session truyền vào record_usage() cần là một session DÀNH RIÊNG cho "
            "việc ghi sổ token.",
            len(session.new),
            len(session.dirty),
        )

    # Đã kiểm đồng nhất provider/model ở trên, nên lấy phần tử nào của usages
    # cũng cho cùng một giá trị — usages[0] không phải một lựa chọn tuỳ ý.
    tong_input = sum(u.input_tokens for u in usages)
    tong_output = sum(u.output_tokens for u in usages)
    so_lan_thu = len(usages)
    provider = usages[0].provider
    model = usages[0].model

    session.add(
        TokenLedger(
            user_id=user_id,
            task=task.value,
            provider=provider,
            model=model,
            input_tokens=tong_input,
            output_tokens=tong_output,
            attempts=so_lan_thu,
            succeeded=succeeded,
        )
    )
    try:
        await session.commit()
    except (SQLAlchemyError, OSError):
        # HAI lớp, không một, và KHÔNG phải Exception trần:
        #
        # - `SQLAlchemyError` là gốc của mọi lỗi do driver/CSDL BÁO VỀ (lệnh
        #   thất bại, vi phạm ràng buộc, kết nối bị đóng giữa transaction...).
        # - `OSError` là gốc của mọi lỗi ở tầng SOCKET, tức khi CSDL không
        #   BÁO GÌ CẢ vì nó không tồn tại để báo: `ConnectionRefusedError`
        #   (CSDL chết, không lắng nghe cổng), `TimeoutError` (không phản hồi),
        #   `socket.gaierror` (tên host không phân giải được) đều là lớp con
        #   của `OSError` và KHÔNG lớp nào trong số đó là `SQLAlchemyError` —
        #   chúng xảy ra TRƯỚC khi có một phiên CSDL nào để sinh ra lỗi kiểu
        #   SQLAlchemy. Thiếu `OSError` ở đây, đúng trường hợp tệ nhất (CSDL
        #   chết hẳn) là trường hợp DUY NHẤT thoát ra ngoài và phá huỷ một câu
        #   trả lời LLM đã tiêu token thật — phá đúng lời hứa của docstring
        #   phía trên.
        #
        # KHÔNG mở rộng thành `Exception`: lỗi lập trình (vd `TypeError` do gọi
        # sai kiểu) vẫn phải nổ ra bình thường để bị phát hiện ngay trong
        # test/CI. Hai lớp trên phủ trọn "hạ tầng lưu trữ không dùng được" mà
        # không phủ "mã của chúng ta viết sai".
        await _rollback_khong_ne_loi(session)
        _log.error(
            "Ghi sổ token thất bại, mất một dòng báo cáo (không ảnh hưởng hạn mức vì "
            "Redis đã trừ token trước khi gọi provider, nhưng số liệu báo cáo sẽ THẤP "
            "HƠN thực tế): task=%s provider=%s model=%s input_tokens=%d "
            "output_tokens=%d attempts=%d succeeded=%s user_id=%s",
            task.value,
            provider,
            model,
            tong_input,
            tong_output,
            so_lan_thu,
            succeeded,
            user_id,
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
