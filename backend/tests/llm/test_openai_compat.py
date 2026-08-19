import httpx
import pytest

from app.modules.llm.providers.groq import GroqProvider
from app.modules.llm.providers.mistral import MistralProvider
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


def _gan_transport(provider, handler):
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


def _ok(text: str = '{"domain":"web"}', finish_reason: str | None = "stop"):
    def handler(request: httpx.Request) -> httpx.Response:
        message: dict = {"message": {"content": text}}
        if finish_reason is not None:
            message["finish_reason"] = finish_reason
        return httpx.Response(
            200,
            json={
                "choices": [message],
                "usage": {"prompt_tokens": 12, "completion_tokens": 34},
            },
        )

    return handler


@pytest.mark.asyncio
async def test_groq_tra_ve_van_ban_va_so_token():
    provider = _gan_transport(GroqProvider(api_key="k", model="groq-test"), _ok())
    text, usage = await provider.complete(_spec())
    assert text == '{"domain":"web"}'
    assert usage.provider == "groq"
    assert usage.input_tokens == 12
    assert usage.output_tokens == 34


@pytest.mark.asyncio
async def test_mistral_tra_ve_van_ban():
    provider = _gan_transport(MistralProvider(api_key="k", model="mistral-test"), _ok())
    text, usage = await provider.complete(_spec())
    assert text == '{"domain":"web"}'
    assert usage.provider == "mistral"


def test_ten_provider_la_rieng_khong_dung_chung():
    """Ruling 3: name và Usage.provider phải là "groq"/"mistral" cụ thể, không
    phải một tên dùng chung từ lớp cơ sở — nếu không, khóa fixture (cache theo
    tên provider) của hai nhà cung cấp sẽ đụng nhau và phát lại nhầm kết quả."""
    groq = GroqProvider(api_key="k", model="m")
    mistral = MistralProvider(api_key="k", model="m")
    assert groq.name == "groq"
    assert mistral.name == "mistral"
    assert groq.name != mistral.name


@pytest.mark.asyncio
async def test_gui_bearer_token_trong_header():
    ghi_nhan = {}

    def handler(request: httpx.Request) -> httpx.Response:
        ghi_nhan["auth"] = request.headers.get("authorization")
        return _ok()(request)

    await _gan_transport(GroqProvider(api_key="khoa-abc", model="m"), handler).complete(_spec())
    assert ghi_nhan["auth"] == "Bearer khoa-abc"


@pytest.mark.asyncio
async def test_khoa_khong_lot_qua_url():
    """Ruling carry-forward 1: khoá không bao giờ lộ trong URL yêu cầu."""
    ghi_nhan = {}

    def handler(request: httpx.Request) -> httpx.Response:
        ghi_nhan["request"] = request
        return _ok()(request)

    await _gan_transport(GroqProvider(api_key=_KHOA_SENTINEL, model="m"), handler).complete(_spec())
    assert _KHOA_SENTINEL not in str(ghi_nhan["request"].url)


@pytest.mark.asyncio
async def test_co_schema_thi_bat_che_do_json_object():
    ghi_nhan = {}

    def handler(request: httpx.Request) -> httpx.Response:
        ghi_nhan["body"] = request.read().decode()
        return _ok()(request)

    await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(
        _spec(schema={"type": "object"})
    )
    assert "json_object" in ghi_nhan["body"]


@pytest.mark.asyncio
async def test_khong_co_schema_thi_khong_bat_json_object():
    ghi_nhan = {}

    def handler(request: httpx.Request) -> httpx.Response:
        ghi_nhan["body"] = request.read().decode()
        return _ok("chao ban")(request)

    await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(_spec())
    assert "json_object" not in ghi_nhan["body"]


@pytest.mark.asyncio
async def test_429_thanh_rate_limited():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "3"}, json={})

    with pytest.raises(RateLimited) as info:
        await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(_spec())
    assert info.value.retry_after == 3.0


@pytest.mark.asyncio
async def test_thong_bao_het_quota_thanh_quota_exhausted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota exceeded for today"}})

    with pytest.raises(QuotaExhausted):
        await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(_spec())


@pytest.mark.asyncio
async def test_429_khong_ro_ly_do_mac_dinh_thanh_rate_limited():
    """Ruling 1: 429 không thể phân loại được phải rơi về RateLimited (mặc định
    an toàn), không phải QuotaExhausted."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "too many requests, slow down"}})

    with pytest.raises(RateLimited):
        await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(_spec())


@pytest.mark.asyncio
async def test_co_chu_quota_nhung_khong_co_bang_chung_theo_ngay_thanh_rate_limited():
    """Ruling 1 — test ghim mặc định bất đối xứng: thân lỗi có chữ "quota"
    (như code khởi điểm trong brief chỉ xét "quota" in text) nhưng KHÔNG có
    bằng chứng theo ngày/tháng. Một cài đặt chỉ xét từ "quota" đơn thuần sẽ
    coi đây là QuotaExhausted — SAI theo ruling. Test này FAIL với cài đặt đó."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "quota exceeded, please slow down"}})

    with pytest.raises(RateLimited):
        await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(_spec())


@pytest.mark.asyncio
async def test_429_theo_phut_thanh_rate_limited():
    """Ruling 1: bằng chứng RÕ theo phút không phải là bằng chứng theo ngày."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "Rate limit reached for requests per minute (RPM)"}},
        )

    with pytest.raises(RateLimited):
        await _gan_transport(MistralProvider(api_key="k", model="m"), handler).complete(_spec())


@pytest.mark.asyncio
async def test_5xx_thanh_provider_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={})

    with pytest.raises(ProviderUnavailable):
        await _gan_transport(MistralProvider(api_key="k", model="m"), handler).complete(_spec())


@pytest.mark.asyncio
async def test_choices_rong_thanh_provider_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ProviderUnavailable):
        await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(_spec())


@pytest.mark.asyncio
async def test_finish_reason_length_gay_loi_khong_tra_json_cat_cut():
    """Carry-forward item 4: finish_reason khác "stop" (ví dụ "length" khi hết
    token) không được trả về như thể thành công — tránh việc tầng chuẩn hoá
    JSON burn retry vào lỗi sai chẩn đoán thành "sai schema"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok('{"domain": "we', finish_reason="length")(request)

    with pytest.raises(ProviderUnavailable) as info:
        await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(_spec())
    assert "length" in str(info.value)


@pytest.mark.asyncio
async def test_finish_reason_content_filter_gay_loi():
    def handler(request: httpx.Request) -> httpx.Response:
        return _ok("", finish_reason="content_filter")(request)

    with pytest.raises(ProviderUnavailable) as info:
        await _gan_transport(MistralProvider(api_key="k", model="m"), handler).complete(_spec())
    assert "content_filter" in str(info.value)


@pytest.mark.asyncio
async def test_finish_reason_stop_khong_gay_loi():
    text, _ = await _gan_transport(
        GroqProvider(api_key="k", model="m"), _ok("ok", finish_reason="stop")
    ).complete(_spec())
    assert text == "ok"


@pytest.mark.asyncio
async def test_finish_reason_vang_mat_khong_gay_loi():
    """Một số phản hồi giả lập (và có thể một số nhà cung cấp) không kèm
    finish_reason; vắng mặt không được coi là bất thường."""
    text, _ = await _gan_transport(
        GroqProvider(api_key="k", model="m"), _ok("ok", finish_reason=None)
    ).complete(_spec())
    assert text == "ok"


@pytest.mark.asyncio
async def test_200_than_khong_phai_json_thanh_provider_unavailable():
    """Carry-forward item 2: guard response.json() trên đường thành công."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json at all")

    with pytest.raises(ProviderUnavailable):
        await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(_spec())


@pytest.mark.asyncio
async def test_retry_after_dang_http_date_khong_lam_sap_provider():
    """Carry-forward item 3: Retry-After có thể là HTTP-date (RFC 7231)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"},
            json={},
        )

    with pytest.raises(RateLimited) as info:
        await _gan_transport(MistralProvider(api_key="k", model="m"), handler).complete(_spec())
    assert info.value.retry_after is None


def test_ca_hai_deu_khong_khai_bao_structured_output():
    assert Capability.STRUCTURED_OUTPUT not in GroqProvider(api_key="k", model="m").capabilities
    assert Capability.STRUCTURED_OUTPUT not in MistralProvider(api_key="k", model="m").capabilities


def test_ca_hai_deu_khong_khai_bao_streaming():
    """Ruling 2: complete() không hiện thực streaming thật, nên không khai báo
    Capability.STREAMING — một cờ định tuyến sai còn tệ hơn cờ thiếu."""
    assert Capability.STREAMING not in GroqProvider(api_key="k", model="m").capabilities
    assert Capability.STREAMING not in MistralProvider(api_key="k", model="m").capabilities


@pytest.mark.asyncio
async def test_khoa_api_khong_lot_vao_thong_bao_loi():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    provider = _gan_transport(GroqProvider(api_key="khoa-bi-mat-tuyet-doi", model="m"), handler)
    with pytest.raises(ProviderUnavailable) as info:
        await provider.complete(_spec())
    assert "khoa-bi-mat-tuyet-doi" not in str(info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code, body, headers",
    [
        (429, {"error": {"message": "too many requests, slow down"}}, {}),
        (429, {}, {}),
        (502, {}, {}),
        (400, {"error": {"message": "invalid request"}}, {}),
        (200, {"choices": []}, {}),
        (200, {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}, {}),
        # Carry-forward item 2: thân 200 không phải JSON hợp lệ.
        (200, b"not json at all", {}),
        # Carry-forward item 3: Retry-After dạng HTTP-date thay vì số giây.
        (429, {}, {"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
    ],
)
async def test_khoa_api_khong_lot_qua_moi_duong_loi(code, body, headers):
    """Carry-forward item 5: vòng quét chống lộ khoá phải phủ MỌI đường lỗi,
    kể cả các đường mới thêm cho ruling này (guard json, guard retry-after,
    guard finish_reason cắt cụt) — đây là các đường dễ bị đụng tới nhất ở các
    lần sửa sau."""
    ghi_nhan = {}

    def handler(request: httpx.Request) -> httpx.Response:
        ghi_nhan["request"] = request
        if isinstance(body, bytes):
            return httpx.Response(code, content=body, headers=headers)
        return httpx.Response(code, json=body, headers=headers)

    for cls in (GroqProvider, MistralProvider):
        provider = _gan_transport(cls(api_key=_KHOA_SENTINEL, model="m"), handler)
        with pytest.raises((RateLimited, QuotaExhausted, ProviderUnavailable)) as info:
            await provider.complete(_spec())
        assert _KHOA_SENTINEL not in str(info.value)
        assert _KHOA_SENTINEL not in str(ghi_nhan["request"].url)


# --- Mọi chỗ NÉM sau HTTP 200 đều đã bị tính tiền, nên phải mang usages (C-52) ---


@pytest.mark.asyncio
async def test_finish_reason_length_mang_theo_usage_da_tinh_tien():
    """`finish_reason="length"` nghĩa là TRỌN ngân sách output đã bị tiêu, và số
    token nằm ngay trong khối `usage` của cùng thân phản hồi.

    ĐÃ QUAN SÁT TRƯỚC KHI SỬA: ĐỎ — `exc.usages` là `[]` nên `usages[0]` ném
    `IndexError`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"domain": "we'}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 700, "completion_tokens": 512},
            },
        )

    with pytest.raises(ProviderUnavailable) as info:
        await _gan_transport(GroqProvider(api_key="k", model="groq-test"), handler).complete(
            _spec()
        )
    assert len(info.value.usages) == 1
    assert info.value.usages[0].output_tokens == 512
    assert info.value.usages[0].input_tokens == 700
    assert info.value.usages[0].provider == "groq"


@pytest.mark.asyncio
async def test_khong_co_choice_nao_van_mang_theo_usage():
    """Nhánh "phản hồi không có nội dung". ĐỎ trước khi sửa."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [], "usage": {"prompt_tokens": 55, "completion_tokens": 0}},
        )

    with pytest.raises(ProviderUnavailable) as info:
        await _gan_transport(MistralProvider(api_key="k", model="m"), handler).complete(_spec())
    assert info.value.usages[0].input_tokens == 55


@pytest.mark.asyncio
async def test_than_200_khong_phai_json_thi_khong_bia_ra_usage():
    """GHIM CHỦ ĐÍCH (bản cũ cũng xanh): thân 200 không parse được thì số token
    là KHÔNG THỂ BIẾT — ghim `usages == []` để không ai bịa ra `Usage(0, 0)`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"khong phai json")

    with pytest.raises(ProviderUnavailable) as info:
        await _gan_transport(GroqProvider(api_key="k", model="m"), handler).complete(_spec())
    assert info.value.usages == []
