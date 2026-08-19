"""Lớp cơ sở cho các nhà cung cấp nói được dạng /chat/completions kiểu OpenAI.

Groq và Mistral đều expose một API tương thích với chat-completions của
OpenAI, nhưng KHÔNG giống hệt nhau: cách diễn đạt lỗi 429 (theo phút/theo
ngày), cấu trúc thân lỗi 4xx, và mức độ ép schema thật đều có thể khác nhau
giữa hai bên. Lớp cơ sở này chỉ chứa phần THẬT SỰ chung (dựng request, đọc
choices/usage, phân loại theo mã trạng thái HTTP); phần có khả năng khác nhau
được để làm thuộc tính lớp con có thể override thay vì giả định ngầm.

Lưu ý bảo mật: khoá API được gửi qua header Authorization: Bearer, KHÔNG bao
giờ qua query string hay bất kỳ thông báo lỗi nào. Lỗi mạng dùng
type(exc).__name__ thay vì str(exc), vì repr của exception httpx có thể mang
theo URL yêu cầu.
"""

import httpx

from app.modules.llm.types import (
    CallSpec,
    Capability,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    Usage,
)

_DO_DAI_THONG_BAO_LOI_TOI_DA = 200


class OpenAICompatProvider:
    """Lớp cơ sở cho mọi nhà cung cấp nói được dạng /chat/completions."""

    # Bằng chứng TÍCH CỰC rằng một lỗi 429 là hết hạn mức theo ngày/tháng
    # (không phải giới hạn tạm thời theo phút/giây). CHƯA CÓ khoá thật của
    # Groq lẫn Mistral để xác nhận cách hai bên diễn đạt việc này — đây là suy
    # đoán bảo thủ dùng chung, không phải hình dạng lỗi đã xác nhận. Lớp con
    # có thể override hai tuple này khi có bằng chứng thật (xem ruling 4:
    # không được giả định ngầm hai nhà cung cấp diễn đạt giống nhau).
    _TU_KHOA_HET_HAN_MUC_NGAY: tuple[str, ...] = (
        "per day",
        "perday",
        "per-day",
        "daily",
        "today",
        "per month",
        "permonth",
        "per-month",
        "monthly",
    )
    # Bằng chứng NGƯỢC LẠI — giới hạn theo phút/giây, chắc chắn không phải hết
    # hạn mức ngày — loại trừ trước để tránh khớp nhầm (vd. "quota" xuất hiện
    # trong cả hai loại thông báo).
    _TU_KHOA_LOAI_TRU_NGAY: tuple[str, ...] = (
        "per minute",
        "perminute",
        "rpm",
        "per second",
        "tps",
    )

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        capabilities: frozenset[Capability],
    ) -> None:
        self.name = name
        self.model = model
        self.capabilities = capabilities
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient()

    async def complete(self, spec: CallSpec) -> tuple[str, Usage]:
        body: dict = {
            "model": self.model,
            "max_tokens": spec.max_output_tokens,
            "messages": [
                {"role": "system", "content": spec.system},
                {"role": "user", "content": spec.user},
            ],
        }
        if spec.json_schema is not None:
            # response_format=json_object là "chế độ JSON": chỉ ép JSON hợp
            # lệ về mặt cú pháp, KHÔNG ép khớp schema cụ thể — yếu hơn hẳn
            # responseSchema của Gemini. Vì vậy KHÔNG khai báo
            # Capability.STRUCTURED_OUTPUT (xem docstring của self.capabilities
            # ở groq.py/mistral.py).
            body["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"authorization": f"Bearer {self._api_key}"},
                json=body,
                timeout=spec.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.name}: lỗi mạng ({type(exc).__name__})") from None

        if response.status_code == 429:
            thong_bao_loi = _trich_thong_bao_loi(response)
            if self._la_het_han_muc_ngay(thong_bao_loi):
                raise QuotaExhausted(f"{self.name}: hết hạn mức")
            # Bất đối xứng CHỦ ĐÍCH (giống ruling ở Gemini): đoán nhầm thành
            # RateLimited chỉ tốn một lần chờ rồi được thử lại; đoán nhầm
            # thành QuotaExhausted khiến router bỏ hẳn provider này cho tới
            # hết cả cửa sổ hạn mức. Vì vậy mặc định LUÔN là RateLimited khi
            # không có bằng chứng theo ngày — nhánh này nằm NGAY TẠI ĐÂY
            # (không giấu trong hàm phụ) để một lần sửa _la_het_han_muc_ngay
            # sau này không thể vô tình đảo ngược nhánh nào là nhánh an toàn.
            raise RateLimited(
                f"{self.name}: bị giới hạn tần suất",
                retry_after=_doc_retry_after(response),
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(f"{self.name}: máy chủ trả {response.status_code}")
        if response.status_code >= 400:
            raise ProviderUnavailable(
                f"{self.name}: yêu cầu bị từ chối ({response.status_code}): "
                f"{_trich_thong_bao_loi(response)}"
            )

        try:
            data = response.json()
        except ValueError:
            # HTTP 200 không đảm bảo thân là JSON hợp lệ. json.JSONDecodeError
            # là ValueError, KHÔNG nằm trong cây LLMError — nếu lọt ra ngoài,
            # nó thoát khỏi fallthrough của router (Task 18) và biến thành
            # lỗi 500 thay vì rơi xuống provider dự phòng.
            #
            # CỐ Ý KHÔNG kèm `usages`: lượt này ĐÃ bị tính tiền (HTTP 200) nhưng
            # số token nằm trong chính thân không đọc được — bịa một
            # `Usage(0, 0)` sẽ ghi vào sổ một con số SAI trông như đã đo, còn để
            # trống là nói đúng rằng không biết. Omission CÓ CHỦ ĐÍCH.
            raise ProviderUnavailable(
                f"{self.name}: thân phản hồi không phải JSON hợp lệ"
            ) from None

        # TỪ ĐÂY TRỞ XUỐNG lượt gọi đã bị TÍNH TIỀN TRỌN VẸN (HTTP 200 + thân
        # JSON đọc được), kể cả khi kết quả không dùng được. Đọc usage NGAY,
        # TRƯỚC mọi chỗ ném, rồi gắn vào `LLMError.usages` (C-52): thiếu bước
        # này thì một lượt `finish_reason="length"` — đã tiêu TRỌN ngân sách
        # output — không sinh dòng nào trong sổ token, và số liệu báo cáo trôi
        # xuống dưới mức tiêu thụ thật.
        usage = self._doc_usage(data)

        choices = data.get("choices") or []
        if not choices:
            raise ProviderUnavailable(f"{self.name}: phản hồi không có nội dung", usages=[usage])

        choice = choices[0]
        # finish_reason khác "stop" (vd. "length" khi hết token, hoặc
        # "content_filter") nghĩa là nội dung bị cắt cụt hoặc bị chặn. Ném lỗi
        # ngay thay vì trả JSON hỏng — nếu không, tầng chuẩn hoá JSON (Task 14)
        # sẽ tốn 2-3 lần retry vô ích rồi báo sai nguyên nhân thành "sai
        # schema". finish_reason vắng mặt (một số phản hồi giả lập hoặc một
        # số biến thể API không kèm) không được coi là bất thường.
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and finish_reason != "stop":
            raise ProviderUnavailable(
                f"{self.name}: dừng sinh nội dung bất thường ({finish_reason})", usages=[usage]
            )

        text = (choice.get("message") or {}).get("content") or ""
        return text, usage

    def _doc_usage(self, data: dict) -> Usage:
        """Đọc số token từ khối `usage`. Tách thành hàm riêng vì cả đường THÀNH
        CÔNG và mọi đường NÉM sau HTTP 200 đều phải dùng đúng một cách đọc —
        hai bản sao sẽ trôi lệch, và một lượt đã tính tiền lại không có usage là
        đúng lớp lỗi đếm-thiếu âm thầm mà C-52 đã chống."""
        khoi = data.get("usage") or {}
        return Usage(
            provider=self.name,
            model=self.model,
            input_tokens=int(khoi.get("prompt_tokens", 0)),
            output_tokens=int(khoi.get("completion_tokens", 0)),
        )

    def _la_het_han_muc_ngay(self, thong_bao_loi: str) -> bool:
        """Tìm bằng chứng TÍCH CỰC rằng lỗi 429 là hết hạn mức theo ngày/tháng.

        Chưa có khoá thật của Groq/Mistral để xác nhận hình dạng lỗi thật của
        hai bên, nên hàm này phải an toàn khi KHÔNG khớp gì cả — mặc định
        RateLimited ở nơi gọi (complete()) mới là điểm mấu chốt của ruling
        này, không phải hàm này.
        """
        thap = thong_bao_loi.lower()
        if any(tu in thap for tu in self._TU_KHOA_LOAI_TRU_NGAY):
            return False
        return any(tu in thap for tu in self._TU_KHOA_HET_HAN_MUC_NGAY)

    async def aclose(self) -> None:
        await self._client.aclose()


def _doc_retry_after(response: httpx.Response) -> float | None:
    """Đọc header Retry-After một cách an toàn.

    RFC 7231 cho phép Retry-After là một HTTP-date thay vì số giây; khi đó
    float() ném ValueError ngay TRONG lúc dựng RateLimited. Trả về None thay
    vì để lỗi đó thoát ra ngoài cây LLMError.
    """
    gia_tri = response.headers.get("retry-after")
    if gia_tri is None:
        return None
    try:
        return float(gia_tri)
    except ValueError:
        return None


def _trich_thong_bao_loi(response: httpx.Response) -> str:
    """Lấy message lỗi từ thân phản hồi để đưa vào exception, cắt bớt độ dài.

    Hình dạng lỗi "chuẩn" kiểu OpenAI là {"error": {"message": "..."}}, nhưng
    một số API tương thích trả {"error": "..."} (chuỗi thẳng) hoặc
    {"message": "..."} ở cấp cao nhất — CHƯA xác nhận được Groq/Mistral dùng
    dạng nào trong từng trường hợp lỗi, nên thử lần lượt các dạng phổ biến
    rồi mới rơi về response.text thô. KHÔNG bao giờ đưa response.request.url
    vào đây: nếu có ngày phải đổi cách truyền khoá, URL có thể mang theo nó.
    """
    try:
        data = response.json()
    except ValueError:
        return response.text[:_DO_DAI_THONG_BAO_LOI_TOI_DA]

    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        thong_bao = error.get("message", "")
    elif isinstance(error, str):
        thong_bao = error
    elif isinstance(data, dict) and isinstance(data.get("message"), str):
        thong_bao = data["message"]
    else:
        thong_bao = response.text
    return thong_bao[:_DO_DAI_THONG_BAO_LOI_TOI_DA]
