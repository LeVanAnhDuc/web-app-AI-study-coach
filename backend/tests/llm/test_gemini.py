import json

import httpx
import pytest

from app.modules.llm.providers.gemini import GeminiProvider
from app.modules.llm.types import (
    CallSpec,
    Capability,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    TaskType,
)

_KHOA_SENTINEL = "SENTINEL-KEY-DO-NOT-LEAK"


def _spec(schema: dict | None = None) -> CallSpec:
    return CallSpec(
        task=TaskType.NORMALIZE_GOAL,
        system="ban la bo may noi dung",
        user="hoc React trong 8 tuan",
        json_schema=schema,
        max_output_tokens=256,
        timeout_seconds=10.0,
    )


def _provider(handler, api_key: str = "khoa-gia") -> GeminiProvider:
    provider = GeminiProvider(api_key=api_key, model="gemini-test")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


@pytest.mark.asyncio
async def test_tra_ve_van_ban_va_so_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"domain":"web"}'}]}}],
                "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 22},
            },
        )

    text, usage = await _provider(handler).complete(_spec())
    assert text == '{"domain":"web"}'
    assert usage.input_tokens == 11
    assert usage.output_tokens == 22
    assert usage.provider == "gemini"


@pytest.mark.asyncio
async def test_khoa_api_gui_qua_header_khong_qua_query_string():
    """Ruling 1: khoá API phải nằm trong header x-goog-api-key, không lộ trong URL."""
    ghi_nhan = {}

    def handler(request: httpx.Request) -> httpx.Response:
        ghi_nhan["request"] = request
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    await _provider(handler, api_key=_KHOA_SENTINEL).complete(_spec())
    request = ghi_nhan["request"]
    assert request.headers.get("x-goog-api-key") == _KHOA_SENTINEL
    assert _KHOA_SENTINEL not in str(request.url)
    assert "key" not in request.url.params


@pytest.mark.asyncio
async def test_co_schema_thi_gui_response_schema_va_mime_json():
    ghi_nhan = {}

    def handler(request: httpx.Request) -> httpx.Response:
        ghi_nhan["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    await _provider(handler).complete(_spec(schema={"type": "object"}))
    assert "responseSchema" in ghi_nhan["body"]
    assert "application/json" in ghi_nhan["body"]

    body = json.loads(ghi_nhan["body"])
    assert body["generationConfig"]["responseSchema"] == {"type": "object"}
    assert body["generationConfig"]["responseMimeType"] == "application/json"


@pytest.mark.asyncio
async def test_khong_co_schema_thi_khong_gui_response_schema():
    ghi_nhan = {}

    def handler(request: httpx.Request) -> httpx.Response:
        ghi_nhan["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "chao ban"}]}}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    await _provider(handler).complete(_spec())
    assert "responseSchema" not in ghi_nhan["body"]

    body = json.loads(ghi_nhan["body"])
    assert "responseSchema" not in body["generationConfig"]
    assert "responseMimeType" not in body["generationConfig"]


@pytest.mark.asyncio
async def test_429_thanh_rate_limited_co_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "7"}, json={})

    with pytest.raises(RateLimited) as info:
        await _provider(handler).complete(_spec())
    assert info.value.retry_after == 7.0


@pytest.mark.asyncio
async def test_het_quota_theo_ngay_thanh_quota_exhausted():
    """Ruling 2: chỉ có bằng chứng RÕ RÀNG về giới hạn theo ngày mới coi là hết hạn mức."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": (
                        "Quota exceeded for quota metric "
                        "'generate_content_free_tier_requests', limit "
                        "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'"
                    )
                }
            },
        )

    with pytest.raises(QuotaExhausted):
        await _provider(handler).complete(_spec())


@pytest.mark.asyncio
async def test_429_theo_phut_thanh_rate_limited():
    """Ruling 2: giới hạn theo phút chỉ là tạm thời, không phải hết hạn mức ngày."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": (
                        "Quota exceeded for quota metric "
                        "'generate_content_free_tier_requests', limit "
                        "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'"
                    )
                }
            },
        )

    with pytest.raises(RateLimited):
        await _provider(handler).complete(_spec())


@pytest.mark.asyncio
async def test_429_khong_phan_loai_duoc_mac_dinh_thanh_rate_limited():
    """Ruling 2: đây là test ghim mặc định bất đối xứng — thân lỗi có chữ "quota"
    (như mọi 429 của Google) nhưng KHÔNG có bằng chứng theo ngày/theo phút. Code
    cũ (chỉ xét "quota" in text) sẽ coi đây là QuotaExhausted — SAI theo ruling
    mới. Test này phải FAIL với code cũ."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "Quota exceeded for quota metric, please retry later"}},
        )

    with pytest.raises(RateLimited):
        await _provider(handler).complete(_spec())


@pytest.mark.asyncio
async def test_5xx_thanh_provider_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    with pytest.raises(ProviderUnavailable):
        await _provider(handler).complete(_spec())


@pytest.mark.asyncio
async def test_phan_hoi_khong_co_candidate_thanh_provider_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    with pytest.raises(ProviderUnavailable):
        await _provider(handler).complete(_spec())


@pytest.mark.asyncio
async def test_khong_co_candidate_kem_ly_do_chan_prompt():
    """Ruling 3: promptFeedback.blockReason phải xuất hiện trong thông báo lỗi."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"candidates": [], "promptFeedback": {"blockReason": "OTHER"}},
        )

    with pytest.raises(ProviderUnavailable) as info:
        await _provider(handler).complete(_spec())
    assert "OTHER" in str(info.value)


@pytest.mark.asyncio
async def test_finish_reason_safety_gay_loi_ngay():
    """Ruling 2: chặn an toàn phải báo lỗi ngay, không trả text rỗng cho tầng trên retry."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": []}, "finishReason": "SAFETY"},
                ],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 0},
            },
        )

    with pytest.raises(ProviderUnavailable) as info:
        await _provider(handler).complete(_spec())
    assert "SAFETY" in str(info.value)


@pytest.mark.asyncio
async def test_finish_reason_max_tokens_gay_loi_khong_tra_json_cat_cut():
    """Ruling 2: JSON bị cắt cụt vì hết token không được trả về như thể hợp lệ."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": '{"domain": "we'}]},
                        "finishReason": "MAX_TOKENS",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 5},
            },
        )

    with pytest.raises(ProviderUnavailable) as info:
        await _provider(handler).complete(_spec())
    assert "MAX_TOKENS" in str(info.value)


@pytest.mark.asyncio
async def test_finish_reason_stop_khong_gay_loi():
    """finishReason STOP là bình thường, không được kích hoạt logic lỗi."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
            },
        )

    text, _ = await _provider(handler).complete(_spec())
    assert text == "ok"


@pytest.mark.asyncio
async def test_400_dua_thong_bao_loi_cua_provider_vao_exception():
    """Ruling 4: lỗi 400 thường do schema ta gửi sai; đưa message của Gemini vào."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "message": 'Invalid JSON payload received. Unknown name "foo"',
                    "status": "INVALID_ARGUMENT",
                }
            },
        )

    with pytest.raises(ProviderUnavailable) as info:
        await _provider(handler).complete(_spec())
    assert "Invalid JSON payload received" in str(info.value)


def test_khai_bao_dung_nang_luc():
    provider = GeminiProvider(api_key="k", model="m")
    assert Capability.STRUCTURED_OUTPUT in provider.capabilities
    # Ruling 3: complete() chỉ gọi generateContent (không stream), nên KHÔNG
    # được khai báo STREAMING — một cờ sai còn tệ hơn cờ thiếu.
    assert Capability.STREAMING not in provider.capabilities


@pytest.mark.asyncio
async def test_200_than_khong_phai_json_thanh_provider_unavailable():
    """Item 1: response.json() trên đường 200 phải được bọc, không để ValueError
    (không nằm trong cây LLMError) thoát ra ngoài và phá vỡ fallthrough của router."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    with pytest.raises(ProviderUnavailable):
        await _provider(handler).complete(_spec())


@pytest.mark.asyncio
async def test_retry_after_dang_http_date_khong_lam_sap_provider():
    """Item 4: Retry-After có thể là HTTP-date (RFC 7231), không phải luôn là số giây."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"},
            json={},
        )

    with pytest.raises(RateLimited) as info:
        await _provider(handler).complete(_spec())
    assert info.value.retry_after is None


@pytest.mark.asyncio
async def test_content_null_khong_gay_attribute_error():
    """Item 5: content có thể tồn tại với giá trị null, không chỉ vắng mặt."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": None, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 0},
            },
        )

    text, _ = await _provider(handler).complete(_spec())
    assert text == ""


@pytest.mark.asyncio
async def test_thieu_usage_metadata_thi_token_bang_khong():
    """Item 6: ghim hành vi mặc định 0 khi thiếu usageMetadata, tránh số liệu sai
    lặng lẽ chảy vào sổ ghi token (Usage ledger) ở task sau."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    text, usage = await _provider(handler).complete(_spec())
    assert text == "ok"
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


@pytest.mark.asyncio
async def test_khoa_api_khong_lot_vao_thong_bao_loi():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    provider = GeminiProvider(api_key="khoa-bi-mat-tuyet-doi", model="m")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderUnavailable) as info:
        await provider.complete(_spec())
    assert "khoa-bi-mat-tuyet-doi" not in str(info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code, body, headers",
    [
        (429, {"error": {"message": "Quota exceeded for quota metric"}}, {}),
        (429, {}, {}),
        (503, {}, {}),
        (400, {"error": {"message": "Invalid JSON payload received"}}, {}),
        (200, {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}, {}),
        (
            200,
            {
                "candidates": [
                    {"content": {"parts": []}, "finishReason": "SAFETY"},
                ]
            },
            {},
        ),
        # Item 1 (fix round 1): thân 200 không phải JSON hợp lệ.
        (200, b"not json at all", {}),
        # Item 4 (fix round 1): Retry-After dạng HTTP-date thay vì số giây.
        (429, {}, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
    ],
)
async def test_khoa_api_khong_lot_qua_moi_duong_loi(code, body, headers):
    """Ruling 1 & 5 xác nhận qua nhiều test: khoá không lộ trong exception hay URL
    trên mọi đường lỗi, kể cả hai đường lỗi mới thêm ở fix round 1 (thân 200
    không phải JSON, Retry-After dạng HTTP-date) — hai đường dễ bị đụng tới
    nhất ở các lần sửa sau, nên phải nằm trong vòng quét tự động này thay vì
    chỉ dựa vào đọc code."""
    ghi_nhan = {}

    def handler(request: httpx.Request) -> httpx.Response:
        ghi_nhan["request"] = request
        if isinstance(body, bytes):
            return httpx.Response(code, content=body, headers=headers)
        return httpx.Response(code, json=body, headers=headers)

    provider = _provider(handler, api_key=_KHOA_SENTINEL)
    with pytest.raises((RateLimited, QuotaExhausted, ProviderUnavailable)) as info:
        await provider.complete(_spec())
    assert _KHOA_SENTINEL not in str(info.value)
    assert _KHOA_SENTINEL not in str(ghi_nhan["request"].url)
