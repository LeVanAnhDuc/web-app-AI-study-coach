"""Adapter Groq: hiện thực Provider qua API /chat/completions tương thích OpenAI.

model mặc định KHÔNG được hard-code ở đây: constructor bắt buộc truyền `model`
tường minh, vì brief của task này không nêu một model mặc định cụ thể nào —
đoán một cái tên "nghe hợp lý" mà không có khoá thật để xác nhận qua endpoint
danh sách model của Groq còn tệ hơn là bắt caller tự khai báo.
"""

from app.modules.llm.providers.openai_compat import OpenAICompatProvider

_BASE = "https://api.groq.com/openai/v1"


class GroqProvider(OpenAICompatProvider):
    """Provider gọi Groq — nhanh, miễn phí, nhưng chỉ ép JSON hợp lệ về cú
    pháp (chế độ json_object), KHÔNG ép khớp schema cụ thể như Gemini.

    KHÔNG khai báo Capability.STRUCTURED_OUTPUT: một số model Groq có hỗ trợ
    response_format kiểu json_schema thật, nhưng không có khoá API thật để
    xác nhận model nào hỗ trợ và hỗ trợ tới mức nào. Khai báo THIẾU một năng
    lực chỉ khiến tầng hạ cấp (Task 14) làm thêm việc thừa (vẫn validate,
    vẫn retry) — vô hại. Khai báo THỪA một năng lực khiến lớp bảo vệ đó bị bỏ
    qua và JSON sai schema chảy thẳng vào ứng dụng — vì vậy khi chưa xác minh
    được, luôn nghiêng về khai báo yếu hơn thực tế.

    KHÔNG khai báo Capability.STREAMING vì complete() không hiện thực
    streaming thật — một cờ định tuyến sai còn tệ hơn cờ thiếu.
    """

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(
            name="groq",
            base_url=_BASE,
            api_key=api_key,
            model=model,
            capabilities=frozenset(),
        )
