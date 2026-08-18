"""Bộ định tuyến LLM: chọn nhà cung cấp theo tác vụ, rơi xuống dự phòng khi hỏng.

Đây là điểm hội tụ của mọi tầng bên dưới (adapter, hạ cấp JSON, thùng token,
sổ ghi token): mỗi quyết định thiết kế ở các tầng đó chỉ có ý nghĩa nếu tầng
này dùng đúng cách. Bảy nguyên tắc chi phối vòng lặp bên dưới:

1. `RateLimiterUnavailable` (thùng token Redis chết) KHÔNG được coi là tín
   hiệu rơi xuống dự phòng — nó không nằm trong `_DUOC_PHEP_ROI_XUONG`, nên
   nó tự thoát khỏi vòng lặp `for` và khỏi cả hàm này. Redis dùng CHUNG cho
   mọi nhà cung cấp; khi nó chết, thùng của nhà cung cấp kế tiếp cũng chết y
   hệt trong cùng một lượt gọi. Rơi xuống dự phòng ở đây sẽ gọi TỪNG nhà
   cung cấp một cách KHÔNG QUA KIỂM SOÁT hạn mức — đúng cơn dồn dập mà
   thùng token sinh ra để chặn.
2. Rơi xuống dự phòng khi gặp `RateLimited`, `QuotaExhausted`,
   `ProviderUnavailable`, `SchemaViolation`, hoặc khi thùng token NỘI BỘ từ
   chối cấp token — bốn lỗi trên nghĩa là "nhà cung cấp này không phục vụ
   được NGAY BÂY GIỜ, có thể nhà cung cấp khác phục vụ được"; một lần thùng
   từ chối còn không phải lỗi — thùng tách theo TỪNG nhà cung cấp, hết ở
   nhà cung cấp này không nói gì về nhà cung cấp kế tiếp.
3. KHÔNG BAO GIỜ sleep theo `RateLimited.retry_after`. Mục đích duy nhất của
   việc có nhiều nhà cung cấp dự phòng là đi tiếp NGAY, không phải chờ một
   nhà cung cấp hồi phục — chờ vài giây để "tôn trọng" retry_after tốn đúng
   độ trễ mà việc có dự phòng sinh ra để tránh. Giá trị này chỉ được GHI LẠI
   (vào thông điệp lỗi tổng hợp) để một bộ lập lịch tương lai có thể đọc.
4. `SchemaViolation` cũng rơi xuống dự phòng — Gemini ép schema gốc, Groq và
   Mistral thì không, nên khả năng trả JSON khớp schema của ba nhà cung cấp
   là KHÁC NHAU thật sự, không phải may rủi thuần tuý. Mỗi lần thử (kể cả
   lần hỏng) đều được ghi lại trong usages, vì Task sau đo tỉ lệ khớp schema
   theo từng nhà cung cấp — nuốt mất một lần thử hỏng là mất một điểm dữ
   liệu đúng ở chỗ phép đo đó cần nhất.
5. usages trả về là danh sách PHẲNG, nhưng MỖI phần tử tự mang tên nhà cung
   cấp của chính nó (`Usage.provider`) — không có gì bị gộp nhầm giữa các
   nhà cung cấp. `record_usage()` (sổ token) từ chối một danh sách trộn
   nhiều nhà cung cấp; việc TÁCH danh sách này theo `u.provider` trước khi
   ghi sổ là việc của tầng gọi hàm này (ngoài phạm vi Task 18 — xem "Tiêu
   thụ" trong yêu cầu, không liệt kê `ledger.record_usage`), không phải của
   `LLMRouter`.
6. Thùng token được hỏi TRƯỚC lời gọi nhà cung cấp (không sau) — nó thực thi
   ngân sách theo thời gian thực, phải chặn trước khi tốn một lượt gọi thật.
   KHÔNG BAO GIỜ truyền `now_override_for_tests` cho `try_acquire()` — tham
   số đó chỉ dành cho test của chính `ratelimit.py`; nếu tầng này truyền
   đồng hồ riêng của tiến trình vào, nhiều tiến trình ứng dụng chạy song
   song sẽ mỗi tiến trình tự thấy thùng hồi token ở một thời điểm khác
   nhau, nhân hiệu lực sức chứa lên theo số tiến trình.
7. Khi CẢ chuỗi định tuyến đều hỏng, `AllProvidersFailed` phải nêu rõ TỪNG
   nhà cung cấp đã thử và lý do — một dòng log phải đủ để hiểu vì sao CẢ
   chuỗi thất bại, không chỉ biết "đã thất bại". Thông điệp không chứa khoá
   API, URL yêu cầu, hay nội dung prompt — các lớp lỗi hạ tầng đã tự đảm bảo
   `str(exc)` của chúng không mang bí mật (xem docstring từng adapter).
"""

from dataclasses import dataclass, field

from pydantic import BaseModel

from app.modules.llm.degrade import complete_structured as _hoan_tat_co_cau_truc
from app.modules.llm.providers.base import Provider
from app.modules.llm.ratelimit import bucket_for_provider
from app.modules.llm.types import (
    AllProvidersFailed,
    CallSpec,
    LLMError,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    SchemaViolation,
    TaskType,
    Usage,
)

# Chuỗi định tuyến theo tác vụ. Đây là bảng DỰ KIẾN, lấy verbatim từ mã mẫu
# của brief Task 18 (kế hoạch), KHÔNG phải bảng do tôi tự suy ra bằng đo đạc.
# Task 20 đo bằng số liệu thật rồi sửa lại bảng này cho khớp — người đọc sau
# không cần đọc report Task 18 mới hiểu được hình dạng bảng nhờ chú thích
# từng dòng dưới đây.
ROUTING: dict[TaskType, tuple[str, ...]] = {
    # Mặc định: Gemini trước — nhà cung cấp free tier DUY NHẤT ép được JSON
    # Schema gốc (responseSchema), nên có khả năng cao nhất trả JSON khớp
    # schema ngay lần gọi đầu; mỗi lần rơi xuống dự phòng tốn thêm một lượt
    # gọi free tier thật.
    #
    # NORMALIZE_GOAL: mistral trước, KHÔNG theo mặc định Gemini-trước. Đây là
    # thứ tự lấy verbatim từ brief — tôi KHÔNG xác nhận được lý do gốc của
    # người viết kế hoạch. Giả thuyết CHƯA KIỂM CHỨNG của tôi: NormalizedGoal
    # là schema phẳng, ít trường (domain/topic/level_from/level_to/
    # weekly_minutes/deadline_weeks), nên rủi ro Groq/Mistral trả sai cấu
    # trúc thấp hơn hẳn so với GENERATE_SYLLABUS/LESSON/QUIZ (mảng lồng
    # nhau) — và NORMALIZE_GOAL chạy ở BƯỚC ĐẦU của mọi phiên học, tần suất
    # gọi cao, nên có thể có chủ đích chừa hạn mức Gemini (RPM thấp nhất,
    # xem PROVIDER_RPM) cho các tác vụ sinh nội dung phức tạp hơn phía sau.
    # Task 20 nên xác nhận hoặc bác bỏ giả thuyết này bằng số liệu thật.
    TaskType.NORMALIZE_GOAL: ("mistral", "gemini", "groq"),
    TaskType.GENERATE_PLACEMENT: ("gemini", "mistral", "groq"),
    TaskType.GENERATE_SYLLABUS: ("gemini", "mistral", "groq"),
    TaskType.GENERATE_LESSON: ("gemini", "mistral", "groq"),
    TaskType.GENERATE_QUIZ: ("gemini", "mistral", "groq"),
    # GRADE_FREE_TEXT: mistral trước, cùng tình trạng CHƯA XÁC NHẬN như
    # NORMALIZE_GOAL — lấy verbatim từ brief. GradeOut cũng là schema phẳng
    # (score/matched_criteria/feedback), nên cùng giả thuyết "schema đơn
    # giản, rủi ro thấp" có thể áp dụng, nhưng tôi KHÔNG có bằng chứng người
    # viết kế hoạch nghĩ vậy — nêu ra để Task 20 kiểm chứng, không phải để
    # khẳng định.
    TaskType.GRADE_FREE_TEXT: ("mistral", "groq", "gemini"),
    # TUTOR_CHAT: groq trước — tác vụ DUY NHẤT không ép schema (REGISTRY:
    # response_model=None, xem test_registry.py), nên lợi thế ép schema gốc
    # của Gemini không áp dụng; Groq ưu tiên vì tốc độ suy luận (mục tiêu là
    # hội thoại phản hồi nhanh, không phải JSON chính xác).
    TaskType.TUTOR_CHAT: ("groq", "gemini", "mistral"),
    TaskType.GENERATE_REMEDIAL_LESSON: ("gemini", "mistral", "groq"),
}

# Hạn mức request mỗi phút, đặt thấp hơn hạn mức công bố để chừa biên an
# toàn. CẢNH BÁO TRUNG THỰC: ba con số này lấy verbatim từ brief/kế hoạch,
# tôi CHƯA đối chiếu với trang tài liệu free tier hiện hành của Gemini/Groq/
# Mistral — coi đây là PLACEHOLDER, không phải số đã kiểm chứng. Spec dự án
# (mục rủi ro R-3) tự nhận hạn mức free tier "thay đổi thường xuyên và có
# thể bị siết không báo trước", nên bất kỳ con số cứng nào ở đây cũng cần
# một task riêng đối chiếu định kỳ, không chỉ kiểm một lần rồi tin mãi.
PROVIDER_RPM: dict[str, int] = {"gemini": 10, "groq": 25, "mistral": 25}

# Nguyên tắc 1 và 2: CHỈ bốn lớp này được coi là "nhà cung cấp đã từ chối,
# thử nhà cung cấp kế tiếp". Cố ý KHÔNG có RateLimiterUnavailable — nó là
# LLMError nhưng KHÔNG nằm trong tuple này nên tự thoát khỏi try/except bên
# dưới, không bị vòng lặp nuốt.
_DUOC_PHEP_ROI_XUONG: tuple[type[LLMError], ...] = (
    RateLimited,
    QuotaExhausted,
    ProviderUnavailable,
    SchemaViolation,
)


@dataclass
class RoutedResult:
    """Kết quả một lời gọi đã định tuyến thành công.

    `usages` chứa usage của MỌI lần thử đã thực hiện trong lượt định tuyến
    này, kể cả các nhà cung cấp đã hỏng trước khi tới nhà cung cấp thành
    công — mỗi phần tử tự mang `provider` của chính nó (xem nguyên tắc 5).
    """

    value: BaseModel
    usages: list[Usage] = field(default_factory=list)
    provider: str = ""


def _mo_ta_that_bai(exc: LLMError) -> str:
    """Mô tả một lần một nhà cung cấp thất bại, để gộp vào thông điệp lỗi
    tổng hợp (nguyên tắc 7).

    Chỉ nối tên lớp và `str(exc)` — không tự bịa thêm chi tiết nào khác, vì
    các lớp lỗi hạ tầng (RateLimited/QuotaExhausted/ProviderUnavailable/
    SchemaViolation) đã tự đảm bảo thông điệp của chúng không mang khoá API,
    URL yêu cầu, hay nội dung prompt (xem docstring từng adapter).

    Với `RateLimited`, kèm thêm `retry_after` nếu nhà cung cấp có báo —
    nguyên tắc 3 cấm dùng giá trị này để sleep/chờ, nhưng KHÔNG cấm ghi lại
    nó để một bộ lập lịch trong tương lai có thể đọc.
    """
    mo_ta = f"{type(exc).__name__}: {exc}"
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        mo_ta += f" (retry_after={retry_after}s)"
    return mo_ta


def _dinh_dang_loi_tong_hop(task: TaskType, da_thu: dict[str, str]) -> str:
    """Gộp lý do thất bại của TỪNG nhà cung cấp đã thử thành MỘT thông điệp
    (nguyên tắc 7) — để một dòng log giải thích được cả chuỗi thất bại."""
    if not da_thu:
        chi_tiet = "(không có nhà cung cấp nào trong chuỗi được đăng ký)"
    else:
        chi_tiet = "; ".join(f"{ten}: {ly_do}" for ten, ly_do in da_thu.items())
    return f"Không nhà cung cấp nào phục vụ được tác vụ {task.value}. Chi tiết: {chi_tiet}"


class LLMRouter:
    """Chọn nhà cung cấp theo tác vụ, rơi xuống dự phòng khi cái trước hỏng."""

    def __init__(
        self,
        providers: dict[str, Provider],
        redis,
        rpm: dict[str, int] | None = None,
        routing: dict[TaskType, tuple[str, ...]] | None = None,
    ) -> None:
        self._providers = providers
        self._rpm = rpm or PROVIDER_RPM
        self._routing = routing or ROUTING
        # Mỗi nhà cung cấp ĐÃ ĐĂNG KÝ có một thùng token riêng (nguyên tắc
        # 6): thùng tách theo `bucket_for_provider`, key namespaced theo tên
        # nhà cung cấp, nên hết token ở một nhà cung cấp không đụng tới nhà
        # cung cấp khác (xem docstring `bucket_for_provider`, Ruling 4).
        self._buckets = {
            ten: bucket_for_provider(redis, ten, self._rpm.get(ten, 10)) for ten in providers
        }

    def _chain(self, task: TaskType) -> tuple[str, ...]:
        return self._routing[task]

    async def complete_structured(self, spec: CallSpec, model_cls: type[BaseModel]) -> RoutedResult:
        usages: list[Usage] = []
        da_thu: dict[str, str] = {}

        for ten in self._chain(spec.task):
            provider = self._providers.get(ten)
            if provider is None:
                # Có tên trong chuỗi định tuyến nhưng chưa được cấu hình
                # (ví dụ chưa có khoá API) — bỏ qua, không tính là một lần
                # thất bại của nhà cung cấp (nó chưa từng được thử).
                continue

            bucket = self._buckets[ten]
            # Nguyên tắc 6: hỏi thùng TRƯỚC khi gọi nhà cung cấp, không
            # truyền now_override_for_tests — sản xuất luôn dùng đồng hồ của
            # máy chủ Redis (xem docstring TokenBucket.try_acquire).
            # RateLimiterUnavailable từ đây (Redis chết) KHÔNG bị bắt ở bất
            # kỳ đâu trong hàm này — nó tự thoát ra ngoài (nguyên tắc 1).
            if not await bucket.try_acquire():
                # Nguyên tắc 2: hết token trong thùng NỘI BỘ không phải một
                # LLMError — thùng tách theo từng nhà cung cấp, hết ở đây
                # không nói gì về nhà cung cấp kế tiếp.
                da_thu[ten] = "đã chạm hạn mức phía chúng ta (thùng token nội bộ)"
                continue

            try:
                gia_tri, usages_lan_nay = await _hoan_tat_co_cau_truc(provider, spec, model_cls)
            except _DUOC_PHEP_ROI_XUONG as exc:
                # Nguyên tắc 4/5: gom usages của lần thử hỏng này (mọi
                # LLMError đều có sẵn thuộc tính usages — khai báo ở gốc cây
                # types.LLMError, không phải gắn động — nên đọc thẳng, không
                # cần getattr với giá trị mặc định) trước khi rơi xuống nhà
                # cung cấp kế tiếp — không được mất.
                usages.extend(exc.usages)
                da_thu[ten] = _mo_ta_that_bai(exc)
                continue

            usages.extend(usages_lan_nay)
            return RoutedResult(value=gia_tri, usages=usages, provider=ten)

        raise AllProvidersFailed(_dinh_dang_loi_tong_hop(spec.task, da_thu), usages=usages)
