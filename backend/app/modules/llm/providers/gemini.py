"""Adapter Gemini: hiện thực Provider bằng REST API generateContent của Google.

Đây là nhà cung cấp mặc định cho mọi tác vụ cần đầu ra có cấu trúc, vì Gemini
là nhà cung cấp miễn phí duy nhất hỗ trợ ép JSON Schema gốc qua
`generationConfig.responseSchema` (không cần tự parse/sửa JSON ở tầng trên).

Lưu ý bảo mật quan trọng: khoá API được gửi qua header `x-goog-api-key`,
KHÔNG bao giờ qua query string. Query string bị proxy, log HTTP debug, và
repr của exception ghi lại nguyên văn — header thì không. Vì lý do tương tự,
không bao giờ được đưa URL yêu cầu vào bất kỳ thông báo lỗi nào.
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

_BASE = "https://generativelanguage.googleapis.com/v1beta"
_DO_DAI_THONG_BAO_LOI_TOI_DA = 200


class GeminiProvider:
    """Provider gọi Gemini qua REST, không dùng SDK chính thức để giữ phụ thuộc tối thiểu."""

    name = "gemini"
    # KHÔNG khai báo STREAMING: complete() chỉ gọi generateContent (không stream).
    # capabilities là đầu vào cho việc định tuyến (Task 18) — một cờ sai còn tệ
    # hơn một cờ thiếu, vì nó khiến tầng trên tưởng có thể stream rồi thất bại.
    # Nếu sau này có task hiện thực streaming thật, thêm cờ lại lúc đó.
    capabilities = frozenset({Capability.STRUCTURED_OUTPUT})

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient()

    async def complete(self, spec: CallSpec) -> tuple[str, Usage]:
        generation: dict = {"maxOutputTokens": spec.max_output_tokens}
        if spec.json_schema is not None:
            generation["responseMimeType"] = "application/json"
            generation["responseSchema"] = spec.json_schema

        body = {
            "systemInstruction": {"parts": [{"text": spec.system}]},
            "contents": [{"role": "user", "parts": [{"text": spec.user}]}],
            "generationConfig": generation,
        }

        try:
            response = await self._client.post(
                f"{_BASE}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self._api_key},
                json=body,
                timeout=spec.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"gemini: lỗi mạng ({type(exc).__name__})") from None

        if response.status_code == 429:
            # Google trả RESOURCE_EXHAUSTED kèm chữ "quota" cho CẢ giới hạn theo
            # phút (RPM) lẫn hết hạn mức thật theo ngày — không thể phân biệt
            # hai trường hợp chỉ bằng từ "quota". Hai hướng sai lệch ở đây BẤT
            # ĐỐI XỨNG nghiêm trọng: đoán nhầm thành RateLimited chỉ tốn một lần
            # chờ rồi router rơi xuống provider khác, Gemini vẫn được thử lại
            # sau; đoán nhầm thành QuotaExhausted khiến router bỏ hẳn Gemini cho
            # tới hết ngày — và Gemini là provider miễn phí DUY NHẤT ép được
            # JSON Schema gốc, nên mất nó là mất cả khả năng ép schema hôm đó.
            # Vì vậy mặc định LUÔN nghiêng về RateLimited; chỉ khi có bằng chứng
            # rõ ràng về "theo ngày" mới coi là QuotaExhausted. KHÔNG "dọn gọn"
            # điều kiện này về dạng đối xứng — sự bất đối xứng là chủ đích.
            if _co_bang_chung_het_han_muc_ngay(response.text):
                raise QuotaExhausted("gemini: hết hạn mức theo ngày")
            raise RateLimited(
                "gemini: bị giới hạn tần suất",
                retry_after=_doc_retry_after(response),
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(f"gemini: máy chủ trả {response.status_code}")
        if response.status_code >= 400:
            raise ProviderUnavailable(
                f"gemini: yêu cầu bị từ chối ({response.status_code}): "
                f"{_trich_thong_bao_loi(response)}"
            )

        try:
            data = response.json()
        except ValueError:
            # HTTP 200 không đảm bảo thân là JSON hợp lệ (mạng cắt giữa chừng,
            # proxy chèn nội dung...). json.JSONDecodeError là ValueError, KHÔNG
            # nằm trong cây LLMError — nếu để lọt ra ngoài, nó thoát khỏi toàn bộ
            # thiết kế fallthrough của router (Task 18) và biến thành lỗi 500
            # thay vì rơi xuống provider khác.
            #
            # CỐ Ý KHÔNG kèm `usages`: lượt này ĐÃ bị tính tiền (HTTP 200), nhưng
            # số token nằm trong chính thân phản hồi không đọc được — bịa một
            # `Usage(0, 0)` sẽ ghi vào sổ một dòng "đã gọi, tiêu 0 token", tức
            # một con số SAI trông như số đã đo; để trống là nói đúng rằng không
            # biết. Đây là omission CÓ CHỦ ĐÍCH, không phải chỗ bị bỏ quên.
            raise ProviderUnavailable("gemini: thân phản hồi không phải JSON hợp lệ") from None

        # TỪ ĐÂY TRỞ XUỐNG, lượt gọi đã được provider TÍNH TIỀN TRỌN VẸN (HTTP
        # 200 + thân JSON đọc được), kể cả khi kết quả không dùng được. Đọc usage
        # NGAY, TRƯỚC mọi chỗ ném, rồi gắn vào `LLMError.usages` (khai ở gốc cây,
        # xem types.LLMError — C-52): thiếu bước này thì một lượt `MAX_TOKENS`
        # (tiêu TRỌN ngân sách output) hay một prompt bị chặn vì SAFETY (tiêu
        # trọn token prompt) không sinh dòng nào trong sổ token, và số liệu báo
        # cáo trôi xuống dưới mức tiêu thụ thật — đúng chiều nguy hiểm mà
        # `ledger.record_usage()` đã cảnh báo. Các số này nằm sẵn trong `data`,
        # cách chỗ ném đúng một dòng.
        usage = self._doc_usage(data)

        candidates = data.get("candidates") or []
        if not candidates:
            ly_do_chan = data.get("promptFeedback", {}).get("blockReason")
            if ly_do_chan:
                raise ProviderUnavailable(
                    f"gemini: phản hồi không có nội dung (prompt bị chặn: {ly_do_chan})",
                    usages=[usage],
                )
            raise ProviderUnavailable("gemini: phản hồi không có nội dung", usages=[usage])

        candidate = candidates[0]
        # finishReason khác STOP (SAFETY, MAX_TOKENS, RECITATION, ...) nghĩa là
        # phần parts rỗng hoặc bị cắt cụt. Ném lỗi ngay thay vì trả text hỏng —
        # nếu không, tầng chuẩn hoá JSON (Task 14) sẽ tốn 2-3 lần retry vô ích
        # rồi báo sai nguyên nhân thành "sai schema".
        finish_reason = candidate.get("finishReason")
        if finish_reason is not None and finish_reason != "STOP":
            raise ProviderUnavailable(
                f"gemini: dừng sinh nội dung bất thường ({finish_reason})", usages=[usage]
            )

        # .get("content", {}) chỉ trả default khi khoá VẮNG MẶT; nếu khoá tồn
        # tại với giá trị null (Gemini có thể trả vậy khi finishReason bất
        # thường) thì .get trả về None, và .get("parts") tiếp theo sẽ ném
        # AttributeError. Dùng "or {}" để bọc cả hai trường hợp.
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)

        return text, usage

    def _doc_usage(self, data: dict) -> Usage:
        """Đọc số token từ `usageMetadata`. Tách thành hàm riêng vì cả đường
        THÀNH CÔNG và mọi đường NÉM sau HTTP 200 đều phải dùng đúng một cách
        đọc — hai bản sao sẽ trôi lệch, và một lượt đã tính tiền lại không có
        usage là đúng lớp lỗi đếm-thiếu âm thầm mà C-52 đã chống."""
        meta = data.get("usageMetadata") or {}
        return Usage(
            provider=self.name,
            model=self.model,
            input_tokens=int(meta.get("promptTokenCount", 0)),
            output_tokens=int(meta.get("candidatesTokenCount", 0)),
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _doc_retry_after(response: httpx.Response) -> float | None:
    """Đọc header Retry-After một cách an toàn.

    RFC 7231 cho phép Retry-After là một HTTP-date thay vì số giây; khi đó
    float() ném ValueError ngay TRONG lúc dựng RateLimited, gây đúng vấn đề
    "exception không nằm trong cây LLMError" mà item 1 vá ở đường 200. Trả về
    None thay vì để lỗi đó thoát ra.
    """
    gia_tri = response.headers.get("retry-after")
    if gia_tri is None:
        return None
    try:
        return float(gia_tri)
    except ValueError:
        return None


def _co_bang_chung_het_han_muc_ngay(noi_dung_loi: str) -> bool:
    """Tìm bằng chứng TÍCH CỰC rằng lỗi 429 là hết hạn mức theo ngày/tháng.

    Không có khoá Gemini thật để xác nhận hình dạng lỗi thật của Google, nên
    hàm này phải an toàn khi KHÔNG khớp gì cả — mặc định RateLimited ở nơi gọi
    chính là điểm mấu chốt của ruling này, không phải hàm này.
    """
    thap = noi_dung_loi.lower()
    # "per minute" là bằng chứng NGƯỢC LẠI — giới hạn theo phút, chắc chắn
    # không phải hết hạn mức ngày — nên loại trừ trước.
    if "per minute" in thap or "perminute" in thap:
        return False
    bang_chung_theo_ngay = ("perday", "per day", "per-day", "daily")
    return any(dau_hieu in thap for dau_hieu in bang_chung_theo_ngay)


def _trich_thong_bao_loi(response: httpx.Response) -> str:
    """Lấy message lỗi từ thân JSON của Gemini để đưa vào exception, cắt bớt độ dài.

    Nguyên nhân phổ biến của lỗi 4xx là schema mình gửi lên bị sai — lỗi của
    mình, không phải nhà cung cấp sập — nên message gốc giúp chẩn đoán nhanh.
    KHÔNG bao giờ đưa response.request.url vào đây: nếu có ngày phải quay lại
    dùng query param cho khoá API, URL sẽ mang theo khoá.
    """
    try:
        thong_bao = response.json().get("error", {}).get("message", "")
    except ValueError:
        thong_bao = response.text
    return thong_bao[:_DO_DAI_THONG_BAO_LOI_TOI_DA]
