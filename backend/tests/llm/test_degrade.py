import pytest
from pydantic import BaseModel

from app.modules.llm.degrade import complete_structured, extract_json
from app.modules.llm.providers.gemini import GeminiProvider
from app.modules.llm.providers.groq import GroqProvider
from app.modules.llm.providers.mistral import MistralProvider
from app.modules.llm.types import CallSpec, Capability, SchemaViolation, TaskType
from tests.llm.fakes import FakeProvider


class ThuNghiem(BaseModel):
    ten: str
    tuoi: int


def _spec() -> CallSpec:
    return CallSpec(
        task=TaskType.NORMALIZE_GOAL,
        system="he thong",
        user="dau vao",
        json_schema={"type": "object"},
        max_output_tokens=128,
        timeout_seconds=10.0,
    )


def test_lay_json_tu_chuoi_thuan():
    assert extract_json('{"a": 1}') == '{"a": 1}'


def test_lay_json_trong_khoi_ma_co_nhan_ngon_ngu():
    text = 'Day la ket qua:\n```json\n{"a": 1}\n```\nHet.'
    assert extract_json(text) == '{"a": 1}'


def test_lay_json_trong_khoi_ma_khong_nhan():
    assert extract_json('```\n{"a": 1}\n```') == '{"a": 1}'


def test_lay_json_khi_co_van_ban_thua_hai_ben():
    assert extract_json('Chao ban. {"a": 1} Cam on.') == '{"a": 1}'


def test_khong_co_json_thi_tra_lai_nguyen_van():
    assert extract_json("khong co gi o day") == "khong co gi o day"


@pytest.mark.asyncio
async def test_lan_dau_dung_thi_khong_thu_lai():
    provider = FakeProvider(responses=['{"ten": "An", "tuoi": 20}'])
    ket_qua, usages = await complete_structured(provider, _spec(), ThuNghiem)
    assert ket_qua.ten == "An"
    assert len(provider.calls) == 1
    assert len(usages) == 1


@pytest.mark.asyncio
async def test_sai_schema_thi_thu_lai_va_thanh_cong():
    provider = FakeProvider(responses=['{"ten": "An"}', '{"ten": "An", "tuoi": 20}'])
    ket_qua, usages = await complete_structured(provider, _spec(), ThuNghiem)
    assert ket_qua.tuoi == 20
    assert len(provider.calls) == 2
    # Ruling 3: mỗi lần gọi provider đều tốn hạn mức, kể cả lần thất bại —
    # usages phải có một mục cho MỖI lần gọi, không chỉ lần cuối cùng thành
    # công. Bộ đếm token của Task sau sẽ cộng dồn danh sách này.
    assert len(usages) == 2


@pytest.mark.asyncio
async def test_lan_thu_lai_co_kem_thong_bao_loi_de_model_sua():
    provider = FakeProvider(responses=['{"ten": "An"}', '{"ten": "An", "tuoi": 20}'])
    await complete_structured(provider, _spec(), ThuNghiem)
    assert "tuoi" in provider.calls[1].user
    assert provider.calls[1].user != provider.calls[0].user


@pytest.mark.asyncio
async def test_het_luot_thu_lai_thi_nem_schema_violation():
    provider = FakeProvider(responses=["hong", "van hong", "hong nua"])
    with pytest.raises(SchemaViolation):
        await complete_structured(provider, _spec(), ThuNghiem, max_retries=2)
    # Chốt số lần gọi tối đa: 1 lần đầu + 2 lần thử lại = 3, không hơn.
    assert len(provider.calls) == 3


@pytest.mark.asyncio
async def test_schema_violation_mang_usage_cua_moi_lan_thu():
    # Ruling C-2 (kế hoạch): SchemaViolation phải mang usages của MỌI lần
    # thử (kể cả lần thất bại) — tầng định tuyến (Task 18) đọc usages từ
    # chính ngoại lệ này khi rơi xuống nhà cung cấp dự phòng, và sổ token
    # (Task 19) không được phép bỏ sót các lần đã tốn token thật.
    provider = FakeProvider(responses=["hong", "van hong", "hong nua"])
    with pytest.raises(SchemaViolation) as exc_info:
        await complete_structured(provider, _spec(), ThuNghiem, max_retries=2)
    assert len(exc_info.value.usages) == 3


@pytest.mark.asyncio
async def test_provider_thieu_structured_output_thi_them_chi_dan_json():
    provider = FakeProvider(capabilities=frozenset(), responses=['{"ten": "An", "tuoi": 20}'])
    await complete_structured(provider, _spec(), ThuNghiem)
    assert "JSON" in provider.calls[0].system


@pytest.mark.asyncio
async def test_provider_co_structured_output_thi_khong_them_chi_dan():
    provider = FakeProvider(
        capabilities=frozenset({Capability.STRUCTURED_OUTPUT}),
        responses=['{"ten": "An", "tuoi": 20}'],
    )
    await complete_structured(provider, _spec(), ThuNghiem)
    assert provider.calls[0].system == "he thong"


@pytest.mark.asyncio
async def test_loi_ha_tang_thi_khong_thu_lai_ma_nem_ngay():
    # Ruling 1: RateLimited/QuotaExhausted/ProviderUnavailable là lỗi HẠ TẦNG,
    # không phải "sai schema" — thử lại không giúp gì, chỉ đốt thêm hạn mức
    # miễn phí. Lớp hạ cấp phải để lỗi này thoát ra ngay lập tức, không nuốt
    # nó vào vòng lặp retry.
    from app.modules.llm.types import RateLimited

    provider = FakeProvider(errors=[RateLimited("qua tai")])
    with pytest.raises(RateLimited):
        await complete_structured(provider, _spec(), ThuNghiem)
    assert len(provider.calls) == 1


def test_gemini_that_khai_bao_structured_output():
    # Ruling 5: FakeProvider cho phép test tự bịa capabilities, nên test này
    # đọc trực tiếp từ adapter THẬT — một thay đổi vô tình ở adapter thật
    # không được phép âm thầm đổi nhánh mà không có test nào phát hiện.
    assert Capability.STRUCTURED_OUTPUT in GeminiProvider.capabilities


def test_groq_va_mistral_that_khong_khai_bao_structured_output():
    groq = GroqProvider(api_key="k", model="m")
    mistral = MistralProvider(api_key="k", model="m")
    assert Capability.STRUCTURED_OUTPUT not in groq.capabilities
    assert Capability.STRUCTURED_OUTPUT not in mistral.capabilities


@pytest.mark.asyncio
async def test_duong_di_ha_cap_voi_capability_that_cua_groq():
    # Dùng đúng bộ capabilities rỗng của Groq/Mistral thật (qua GroqProvider),
    # không phải bộ tự bịa, để khẳng định nhánh hạ cấp được kích hoạt đúng
    # với provider thật sẽ dùng trong production.
    groq = GroqProvider(api_key="k", model="m")
    fake = FakeProvider(capabilities=groq.capabilities, responses=['{"ten": "An", "tuoi": 20}'])
    await complete_structured(fake, _spec(), ThuNghiem)
    assert "JSON" in fake.calls[0].system
    await groq.aclose()
