from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    NORMALIZE_GOAL = "normalize_goal"
    GENERATE_PLACEMENT = "generate_placement"
    GENERATE_SYLLABUS = "generate_syllabus"
    GENERATE_LESSON = "generate_lesson"
    GENERATE_QUIZ = "generate_quiz"
    GRADE_FREE_TEXT = "grade_free_text"
    TUTOR_CHAT = "tutor_chat"
    GENERATE_REMEDIAL_LESSON = "generate_remedial_lesson"


class Capability(str, Enum):
    STRUCTURED_OUTPUT = "structured_output"
    STREAMING = "streaming"
    PROMPT_CACHE = "prompt_cache"


@dataclass(frozen=True)
class CallSpec:
    task: TaskType
    system: str
    user: str
    json_schema: dict | None
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True)
class Usage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMError(Exception):
    """Gốc của mọi lỗi phát sinh khi gọi nhà cung cấp LLM.

    `usages` khai báo Ở GỐC CÂY, không phải gắn động (`exc.usages = ...`)
    trên riêng từng lớp con: tầng hạ cấp (degrade.py) và tầng định tuyến
    (routing.py) đều cần đọc usage của các lần gọi ĐÃ THỰC SỰ tiêu token
    thật trước khi một lỗi xảy ra giữa chừng (ví dụ lần 1 gọi thành công về
    mặt mạng nhưng sai schema, lần 2 mới gặp RateLimited) — nếu mỗi lớp con
    tự quyết định có khai báo thuộc tính này hay không, một điểm ném lỗi
    mới trong tương lai có thể quên gắn nó, và `getattr(exc, "usages", [])`
    sẽ âm thầm trả về danh sách rỗng thay vì báo lỗi. Khai báo ở đây khiến
    MỌI `LLMError` (kể cả các lớp chưa từng liên quan tới một lần gọi
    provider nào, ví dụ `RateLimiterUnavailable`) đều có thuộc tính này với
    một kiểu rõ ràng, mặc định là danh sách rỗng khi không có gì để mang.
    """

    def __init__(self, message: str = "", usages: list["Usage"] | None = None) -> None:
        super().__init__(message)
        self.usages: list[Usage] = usages if usages is not None else []


class RateLimited(LLMError):
    """Nhà cung cấp trả 429. Nên rơi xuống nhà cung cấp dự phòng."""

    def __init__(
        self,
        message: str = "",
        retry_after: float | None = None,
        usages: list["Usage"] | None = None,
    ) -> None:
        super().__init__(message, usages)
        self.retry_after = retry_after


class QuotaExhausted(LLMError):
    """Hết hạn mức miễn phí trong ngày hoặc trong tháng."""


class ProviderUnavailable(LLMError):
    """Lỗi mạng, timeout, hoặc nhà cung cấp trả 5xx."""


class SchemaViolation(LLMError):
    """Đã retry đủ số lần mà đầu ra vẫn không khớp schema."""


class AllProvidersFailed(LLMError):
    """Mọi nhà cung cấp trong chuỗi định tuyến (Task 18) đều hỏng cho tác vụ này.

    `usages` (kế thừa từ `LLMError`, xem docstring ở đó) gom usage của MỌI
    lần gọi đã thực hiện trước khi cả chuỗi thất bại — kể cả các nhà cung
    cấp dự phòng đã tự thử và tự hỏng. Mỗi lần gọi một nhà cung cấp tốn
    token thật trong hạn mức miễn phí dù kết quả cuối cùng là thất bại; bỏ
    sót các lần thử đó khi không có kết quả trả về cho người dùng sẽ khiến
    sổ token (Task 19) đánh giá THẤP HƠN mức tiêu thụ thật, đúng hướng nguy
    hiểm mà `ledger.record_usage()` đã cảnh báo.
    """
