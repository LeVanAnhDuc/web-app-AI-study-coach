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
    capabilities = frozenset({Capability.STRUCTURED_OUTPUT, Capability.STREAMING})

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
            noi_dung = response.text.lower()
            if "quota" in noi_dung:
                raise QuotaExhausted("gemini: hết hạn mức")
            retry_after = response.headers.get("retry-after")
            raise RateLimited(
                "gemini: bị giới hạn tần suất",
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(f"gemini: máy chủ trả {response.status_code}")
        if response.status_code >= 400:
            raise ProviderUnavailable(
                f"gemini: yêu cầu bị từ chối ({response.status_code}): "
                f"{_trich_thong_bao_loi(response)}"
            )

        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            ly_do_chan = data.get("promptFeedback", {}).get("blockReason")
            if ly_do_chan:
                raise ProviderUnavailable(
                    f"gemini: phản hồi không có nội dung (prompt bị chặn: {ly_do_chan})"
                )
            raise ProviderUnavailable("gemini: phản hồi không có nội dung")

        candidate = candidates[0]
        # finishReason khác STOP (SAFETY, MAX_TOKENS, RECITATION, ...) nghĩa là
        # phần parts rỗng hoặc bị cắt cụt. Ném lỗi ngay thay vì trả text hỏng —
        # nếu không, tầng chuẩn hoá JSON (Task 14) sẽ tốn 2-3 lần retry vô ích
        # rồi báo sai nguyên nhân thành "sai schema".
        finish_reason = candidate.get("finishReason")
        if finish_reason is not None and finish_reason != "STOP":
            raise ProviderUnavailable(f"gemini: dừng sinh nội dung bất thường ({finish_reason})")

        parts = candidate.get("content", {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)

        meta = data.get("usageMetadata", {})
        return text, Usage(
            provider=self.name,
            model=self.model,
            input_tokens=int(meta.get("promptTokenCount", 0)),
            output_tokens=int(meta.get("candidatesTokenCount", 0)),
        )

    async def aclose(self) -> None:
        await self._client.aclose()


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
