import pytest
from pydantic import BaseModel

from app.modules.llm.degrade import complete_structured, extract_json
from app.modules.llm.providers.gemini import GeminiProvider
from app.modules.llm.providers.groq import GroqProvider
from app.modules.llm.providers.mistral import MistralProvider
from app.modules.llm.types import (
    CallSpec,
    Capability,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    SchemaViolation,
    TaskType,
    Usage,
)
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
    provider = FakeProvider(errors=[RateLimited("qua tai")])
    with pytest.raises(RateLimited):
        await complete_structured(provider, _spec(), ThuNghiem)
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_loi_ha_tang_giua_chung_khong_bi_thu_lai_nhung_van_mang_usage_da_tich_luy():
    # Phát hiện của review Task 18: nếu lần thử thứ nhất sai schema (đã tốn
    # token thật, usages có 1 mục) rồi lần thử thứ hai mới gặp lỗi hạ tầng,
    # ngoại lệ hạ tầng đó phải mang theo usage của lần thứ nhất — mất nó sẽ
    # khiến sổ token (Task 19) đánh giá THẤP HƠN mức tiêu thụ thật, đúng lỗi
    # mà việc gắn usages vào SchemaViolation đã xử lý cho nhánh "hết lượt".
    #
    # Chốt HAI điều cùng lúc: (1) usages của lần 1 không bị mất (hành vi MỚI
    # của vòng sửa này); (2) lỗi hạ tầng vẫn KHÔNG bị thử lại — đúng 2 lần
    # gọi (lần 1 sai schema, lần 2 raise), không có lần 3 — nếu ai đó lỡ biến
    # khối except mới thành một vòng retry, assert số lần gọi sẽ đỏ ngay.
    provider = FakeProvider(responses=["hong"], errors=[None, RateLimited("qua tai")])
    with pytest.raises(RateLimited) as exc_info:
        await complete_structured(provider, _spec(), ThuNghiem)
    assert len(provider.calls) == 2
    assert len(exc_info.value.usages) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lop_loi",
    [RateLimited, QuotaExhausted, ProviderUnavailable],
)
async def test_usage_gan_tai_cho_nem_cua_adapter_khong_bi_ghi_de(lop_loi):
    """Ngoại lệ hạ tầng có thể ĐÃ MANG usages do CHÍNH ADAPTER gắn tại chỗ ném:
    mọi chỗ ném sau một HTTP 200 (finishReason MAX_TOKENS/length, prompt bị
    chặn, không có candidate) đều đã bị nhà cung cấp tính tiền trọn vẹn và đều
    kèm `usages=[usage]`. Một phép GÁN THẲNG ở đây (`exc.usages = usages`) sẽ
    xoá đúng phần đó và thay bằng bộ tích luỹ của các lần thử TRƯỚC — bộ tích
    luỹ vốn RỖNG ở lần thử đầu tiên, mà lần thử đầu tiên chính là trường hợp
    hay gặp nhất.

    Ghim CẢ HAI nửa cùng lúc: usage của lần thử trước (đã sai schema, đã tốn
    token) VÀ usage mà adapter tự gắn — theo đúng thứ tự `usages + exc.usages`.

    ĐÃ QUAN SÁT TRƯỚC KHI SỬA: ĐỎ trên cả ba lớp lỗi —
    `assert 1 == 2` (chỉ còn lại usage của lần thử trước, phần adapter gắn bị
    xoá). Test cũ ở trên không thể đỏ vì nó ném `RateLimited("qua tai")` KHÔNG
    kèm usages, nên phép gán ghi `[usage lần 1]` lên `[]` và trông như đúng.
    """
    usage_adapter_gan = Usage(provider="fake", model="fake-1", input_tokens=800, output_tokens=512)
    provider = FakeProvider(
        responses=["hong"],
        errors=[None, lop_loi("het ngan sach", usages=[usage_adapter_gan])],
    )

    with pytest.raises(lop_loi) as exc_info:
        await complete_structured(provider, _spec(), ThuNghiem)

    # Vẫn KHÔNG thử lại lỗi hạ tầng: đúng 2 lượt gọi, không có lượt 3.
    assert len(provider.calls) == 2
    usages = exc_info.value.usages
    assert len(usages) == 2, usages
    # Thứ tự: usage tích luỹ của router/degrade đi TRƯỚC, phần ngoại lệ tự mang
    # đi SAU — giống routing.py, để không có gì bị bỏ hay bị đếm hai lần.
    assert usages[0].output_tokens == 20  # lần thử 1 (FakeProvider trả 10/20)
    assert usages[1] is usage_adapter_gan
    assert sum(u.output_tokens for u in usages) == 532


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
