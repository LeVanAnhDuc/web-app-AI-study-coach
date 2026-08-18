"""Adapter Mistral: hiện thực Provider qua API /chat/completions tương thích OpenAI.

model mặc định KHÔNG được hard-code ở đây: constructor bắt buộc truyền `model`
tường minh, vì brief của task này không nêu một model mặc định cụ thể nào —
đoán một cái tên "nghe hợp lý" mà không có khoá thật để xác nhận qua endpoint
danh sách model của Mistral còn tệ hơn là bắt caller tự khai báo.
"""

from app.modules.llm.providers.openai_compat import OpenAICompatProvider

_BASE = "https://api.mistral.ai/v1"


class MistralProvider(OpenAICompatProvider):
    """Provider gọi Mistral — miễn phí ở tier thấp, nhưng chỉ ép JSON hợp lệ
    về cú pháp (chế độ json_object), KHÔNG ép khớp schema cụ thể như Gemini.

    KHÔNG khai báo Capability.STRUCTURED_OUTPUT (cùng lý do với Groq — xem
    docstring của GroqProvider): chưa có khoá thật để xác nhận Mistral có ép
    schema thật hay không, nên nghiêng về khai báo năng lực YẾU hơn thực tế.

    Chưa xác nhận được cách Mistral diễn đạt lỗi 429 hết hạn mức theo ngày —
    lớp cơ sở dùng chung một heuristic bảo thủ (xem OpenAICompatProvider);
    nếu sau này có bằng chứng thật riêng cho Mistral, override
    _TU_KHOA_HET_HAN_MUC_NGAY/_TU_KHOA_LOAI_TRU_NGAY ở đây thay vì sửa lớp
    cơ sở dùng chung cho cả Groq.

    KHÔNG khai báo Capability.STREAMING vì complete() không hiện thực
    streaming thật.
    """

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(
            name="mistral",
            base_url=_BASE,
            api_key=api_key,
            model=model,
            capabilities=frozenset(),
        )
