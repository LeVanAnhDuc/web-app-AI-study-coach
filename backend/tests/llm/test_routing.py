import inspect

import fakeredis.aioredis
import pytest
import redis.exceptions as redis_exceptions
from pydantic import BaseModel

import app.modules.llm.routing as routing_module
from app.modules.llm.providers.gemini import GeminiProvider
from app.modules.llm.providers.groq import GroqProvider
from app.modules.llm.providers.mistral import MistralProvider
from app.modules.llm.ratelimit import RateLimiterUnavailable, TokenBucket
from app.modules.llm.routing import PROVIDER_RPM, ROUTING, LLMRouter
from app.modules.llm.types import (
    AllProvidersFailed,
    CallSpec,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    TaskType,
)
from tests.llm.fakes import FakeProvider


class ThuNghiem(BaseModel):
    ten: str


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis()


def _spec(task: TaskType = TaskType.NORMALIZE_GOAL) -> CallSpec:
    return CallSpec(
        task=task,
        system="he thong",
        user="dau vao",
        json_schema={"type": "object"},
        max_output_tokens=128,
        timeout_seconds=10.0,
    )


# --- Test thuộc brief (Bước 2) ---


def test_moi_tac_vu_deu_co_chuoi_dinh_tuyen():
    assert set(ROUTING.keys()) == set(TaskType)
    for task, chuoi in ROUTING.items():
        assert len(chuoi) >= 1, task


@pytest.mark.asyncio
async def test_dung_nha_cung_cap_dau_tien_khi_no_chay_tot(redis):
    a = FakeProvider(name="a", responses=['{"ten": "An"}'])
    b = FakeProvider(name="b", responses=['{"ten": "Binh"}'])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    ket_qua = await router.complete_structured(_spec(), ThuNghiem)
    assert ket_qua.value.ten == "An"
    assert ket_qua.provider == "a"
    assert b.calls == []


@pytest.mark.asyncio
async def test_roi_xuong_du_phong_khi_bi_gioi_han_tan_suat(redis):
    a = FakeProvider(name="a", errors=[RateLimited("het luot")])
    b = FakeProvider(name="b", responses=['{"ten": "Binh"}'])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    ket_qua = await router.complete_structured(_spec(), ThuNghiem)
    assert ket_qua.provider == "b"
    assert ket_qua.value.ten == "Binh"


@pytest.mark.asyncio
async def test_roi_xuong_du_phong_khi_het_quota(redis):
    a = FakeProvider(name="a", errors=[QuotaExhausted("het quota")])
    b = FakeProvider(name="b", responses=['{"ten": "Binh"}'])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    assert (await router.complete_structured(_spec(), ThuNghiem)).provider == "b"


@pytest.mark.asyncio
async def test_roi_xuong_du_phong_khi_khong_ep_duoc_schema(redis):
    a = FakeProvider(name="a", responses=["hong", "van hong", "hong nua"])
    b = FakeProvider(name="b", responses=['{"ten": "Binh"}'])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    ket_qua = await router.complete_structured(_spec(), ThuNghiem)
    assert ket_qua.provider == "b"
    assert len(a.calls) == 3


@pytest.mark.asyncio
async def test_roi_xuong_du_phong_khi_provider_khong_kha_dung(redis):
    # ProviderUnavailable (lỗi mạng/timeout/5xx) nằm trong _DUOC_PHEP_ROI_XUONG
    # cùng RateLimited/QuotaExhausted/SchemaViolation, nhưng ba lớp kia đã có
    # test fallthrough riêng còn lớp này thì chưa — bổ sung để không có lỗ
    # hổng phủ trên đúng bốn lớp mà Ruling 2 nêu tên.
    a = FakeProvider(name="a", errors=[ProviderUnavailable("mat mang")])
    b = FakeProvider(name="b", responses=['{"ten": "Binh"}'])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    ket_qua = await router.complete_structured(_spec(), ThuNghiem)
    assert ket_qua.provider == "b"
    assert ket_qua.value.ten == "Binh"


@pytest.mark.asyncio
async def test_gom_du_usage_cua_moi_nha_cung_cap_da_thu(redis):
    a = FakeProvider(name="a", errors=[RateLimited("x")])
    b = FakeProvider(name="b", responses=["hong", '{"ten": "Binh"}'])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    ket_qua = await router.complete_structured(_spec(), ThuNghiem)
    assert len(ket_qua.usages) == 2


@pytest.mark.asyncio
async def test_moi_nha_cung_cap_deu_hong_thi_nem_all_providers_failed(redis):
    a = FakeProvider(name="a", errors=[RateLimited("x")])
    b = FakeProvider(name="b", errors=[QuotaExhausted("y")])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    with pytest.raises(AllProvidersFailed):
        await router.complete_structured(_spec(), ThuNghiem)


@pytest.mark.asyncio
async def test_bo_qua_nha_cung_cap_chua_duoc_dang_ky(redis):
    b = FakeProvider(name="b", responses=['{"ten": "Binh"}'])
    router = LLMRouter({"b": b}, redis)
    router._chain = lambda task: ("khong-ton-tai", "b")

    assert (await router.complete_structured(_spec(), ThuNghiem)).provider == "b"


@pytest.mark.asyncio
async def test_het_token_trong_thung_thi_chuyen_sang_nha_cung_cap_sau(redis):
    a = FakeProvider(name="a", responses=['{"ten": "An"}'])
    b = FakeProvider(name="b", responses=['{"ten": "Binh"}'])
    router = LLMRouter({"a": a, "b": b}, redis, rpm={"a": 1, "b": 60})
    router._chain = lambda task: ("a", "b")

    dau = await router.complete_structured(_spec(), ThuNghiem)
    sau = await router.complete_structured(_spec(), ThuNghiem)

    assert dau.provider == "a"
    assert sau.provider == "b"
    assert len(a.calls) == 1


# --- Test bổ sung: Ruling 1 — RateLimiterUnavailable KHÔNG rơi xuống dự phòng ---


class _RedisMatKetNoi:
    """Đồ giả lập Redis không kết nối được, dùng để kiểm hành vi fail-closed
    của bộ giới hạn mà không cần dựng hạ tầng mạng thật (cùng khuôn với
    `tests/llm/test_ratelimit.py::_RedisMatKetNoi`)."""

    def register_script(self, script: str):
        async def _vo_luon(*args, **kwargs):
            raise redis_exceptions.ConnectionError("giả lập mất kết nối Redis")

        return _vo_luon


@pytest.mark.asyncio
async def test_loi_bo_gioi_han_khong_kha_dung_thi_khong_roi_xuong_du_phong():
    # Ruling 1: RateLimiterUnavailable là lỗi của bộ giới hạn DÙNG CHUNG, không
    # phải lỗi riêng của nhà cung cấp "a" — nó phải NỔI LÊN NGAY, không được
    # bắt và không được kích hoạt rơi xuống "b" (vì "b" cũng dùng chung Redis
    # vừa chết, rơi xuống chỉ là một lượt gọi KHÔNG QUA KIỂM SOÁT hạn mức).
    a = FakeProvider(name="a", responses=['{"ten": "An"}'])
    b = FakeProvider(name="b", responses=['{"ten": "Binh"}'])
    router = LLMRouter({"a": a, "b": b}, _RedisMatKetNoi())
    router._chain = lambda task: ("a", "b")

    with pytest.raises(RateLimiterUnavailable):
        await router.complete_structured(_spec(), ThuNghiem)
    assert a.calls == []
    assert b.calls == []


# --- Test bổ sung: Ruling 3 — không bao giờ sleep theo retry_after ---


def test_khong_sleep_trong_ma_nguon_dinh_tuyen():
    """Kiểm cấu trúc mã nguồn: nếu ai đó thêm time.sleep()/asyncio.sleep() để
    "tôn trọng" retry_after, bài test này đỏ ngay lập tức. Đây là một chốt
    tất định (đọc mã nguồn), không phải một phép đo thời gian có thể chập
    chờn theo tải máy."""
    nguon = inspect.getsource(routing_module)
    assert "sleep(" not in nguon


@pytest.mark.asyncio
async def test_retry_after_khong_lam_cham_viec_roi_xuong_du_phong_nhung_van_duoc_ghi_lai(redis):
    a = FakeProvider(name="a", errors=[RateLimited("cho 5 giay", retry_after=5.0)])
    b = FakeProvider(name="b", errors=[QuotaExhausted("het")])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    with pytest.raises(AllProvidersFailed) as exc_info:
        await router.complete_structured(_spec(), ThuNghiem)
    # retry_after được GHI LẠI trong thông điệp lỗi tổng hợp (để một bộ lập
    # lịch tương lai đọc được), không phải bị bỏ qua âm thầm.
    assert "retry_after=5.0" in str(exc_info.value)


# --- Test bổ sung: Ruling 6 — không truyền đồng hồ riêng cho thùng token ---


@pytest.mark.asyncio
async def test_khong_truyen_dong_ho_rieng_cho_thung_token(monkeypatch, redis):
    goc = TokenBucket.try_acquire
    ghi_nhan: list[dict] = []

    async def theo_doi(self, *args, **kwargs):
        ghi_nhan.append(kwargs)
        return await goc(self, *args, **kwargs)

    monkeypatch.setattr(TokenBucket, "try_acquire", theo_doi)

    a = FakeProvider(name="a", responses=['{"ten": "An"}'])
    router = LLMRouter({"a": a}, redis)
    router._chain = lambda task: ("a",)

    await router.complete_structured(_spec(), ThuNghiem)

    assert ghi_nhan == [{}], (
        "try_acquire() không được nhận now_override_for_tests từ tầng định tuyến"
    )


# --- Test bổ sung: Ruling 7 — thông điệp lỗi tổng hợp nêu tên + lý do từng nhà cung cấp ---


@pytest.mark.asyncio
async def test_loi_tong_hop_neu_ten_va_ly_do_tung_nha_cung_cap(redis):
    a = FakeProvider(name="a", errors=[RateLimited("qua tai")])
    b = FakeProvider(name="b", errors=[QuotaExhausted("het thang")])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    with pytest.raises(AllProvidersFailed) as exc_info:
        await router.complete_structured(_spec(), ThuNghiem)

    thong_bao = str(exc_info.value)
    assert "a" in thong_bao and "RateLimited" in thong_bao
    assert "b" in thong_bao and "QuotaExhausted" in thong_bao


@pytest.mark.asyncio
async def test_khong_provider_nao_duoc_dang_ky_thi_nem_all_providers_failed(redis):
    router = LLMRouter({}, redis)
    router._chain = lambda task: ("khong-ton-tai-1", "khong-ton-tai-2")

    with pytest.raises(AllProvidersFailed):
        await router.complete_structured(_spec(), ThuNghiem)


# --- Test bổ sung: C-4 (kế hoạch) — AllProvidersFailed mang usages của mọi lần thử ---


@pytest.mark.asyncio
async def test_all_providers_failed_mang_usage_cua_moi_lan_thu(redis):
    a = FakeProvider(name="a", responses=["hong", "van hong", "hong nua"])
    b = FakeProvider(name="b", responses=["hong", "van hong", "hong nua"])
    router = LLMRouter({"a": a, "b": b}, redis)
    router._chain = lambda task: ("a", "b")

    with pytest.raises(AllProvidersFailed) as exc_info:
        await router.complete_structured(_spec(), ThuNghiem)

    # Mỗi provider tự thử 3 lần (mặc định max_retries=2 ở tầng hạ cấp)
    # trước khi ném SchemaViolation -> tổng 6 usage, không mất lần nào.
    assert len(exc_info.value.usages) == 6


# --- Bẫy: tên/rpm không được lấy theo trực giác, phải khớp adapter THẬT ---


@pytest.mark.asyncio
async def test_ten_provider_trong_bang_dinh_tuyen_khop_voi_adapter_that():
    # ROUTING/PROVIDER_RPM dùng chuỗi tên "gemini"/"groq"/"mistral" cứng —
    # FakeProvider cho phép test tự đặt tên bất kỳ ("a", "b"...) nên các test
    # phía trên KHÔNG bắt được một lỗi gõ tên (vd "gemeni") lặng lẽ khiến một
    # nhà cung cấp biến mất khỏi mọi chuỗi dự phòng. Test này đọc tên THẬT từ
    # chính lớp adapter, cùng khuôn với test_degrade.py::
    # test_gemini_that_khai_bao_structured_output.
    groq = GroqProvider(api_key="k", model="m")
    mistral = MistralProvider(api_key="k", model="m")
    ten_that = {GeminiProvider.name, groq.name, mistral.name}

    try:
        for task, chuoi in ROUTING.items():
            for ten in chuoi:
                assert ten in ten_that, f"{task}: '{ten}' không khớp tên adapter thật nào"
    finally:
        await groq.aclose()
        await mistral.aclose()


@pytest.mark.asyncio
async def test_provider_rpm_chi_khai_bao_dung_ten_adapter_that():
    groq = GroqProvider(api_key="k", model="m")
    mistral = MistralProvider(api_key="k", model="m")
    ten_that = {GeminiProvider.name, groq.name, mistral.name}

    try:
        assert set(PROVIDER_RPM.keys()) == ten_that
    finally:
        await groq.aclose()
        await mistral.aclose()
