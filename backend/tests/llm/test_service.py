import uuid

import fakeredis.aioredis
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.modules.llm.ledger import TokenLedger
from app.modules.llm.providers.gemini import GeminiProvider
from app.modules.llm.providers.groq import GroqProvider
from app.modules.llm.providers.mistral import MistralProvider
from app.modules.llm.registry import NormalizedGoal
from app.modules.llm.routing import PROVIDER_RPM
from app.modules.llm.service import LLMService, build_providers
from app.modules.llm.types import AllProvidersFailed, TaskType
from tests.llm.fakes import FakeProvider

_GOAL_JSON = (
    '{"domain":"lap trinh web","topic":"React","level_from":"JS co ban",'
    '"level_to":"tu dung app","weekly_minutes":300,"deadline_weeks":8}'
)


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis()


# --- Test thuộc brief (Bước 1) ---


@pytest.mark.asyncio
async def test_tra_ve_dung_model_da_dang_ky(db_session, redis):
    service = LLMService({"gemini": FakeProvider(name="gemini", responses=[_GOAL_JSON])}, redis)
    ket_qua = await service.run(
        db_session, uuid.uuid4(), TaskType.NORMALIZE_GOAL, "hoc React 8 tuan"
    )
    assert isinstance(ket_qua, NormalizedGoal)
    assert ket_qua.topic == "React"
    assert ket_qua.weekly_minutes == 300


@pytest.mark.asyncio
async def test_dung_prompt_he_thong_tu_registry(db_session, redis):
    provider = FakeProvider(name="gemini", responses=[_GOAL_JSON])
    service = LLMService({"gemini": provider}, redis)
    await service.run(db_session, uuid.uuid4(), TaskType.NORMALIZE_GOAL, "hoc React")
    assert "bộ máy nội dung" in provider.calls[0].system


@pytest.mark.asyncio
async def test_ghi_so_khi_thanh_cong(db_session, redis):
    user_id = uuid.uuid4()
    service = LLMService({"gemini": FakeProvider(name="gemini", responses=[_GOAL_JSON])}, redis)
    await service.run(db_session, user_id, TaskType.NORMALIZE_GOAL, "hoc React")

    row = await db_session.scalar(select(TokenLedger).where(TokenLedger.user_id == user_id))
    assert row is not None
    assert row.succeeded is True
    assert row.task == "normalize_goal"


@pytest.mark.asyncio
async def test_ghi_so_ca_khi_that_bai(db_session, redis):
    user_id = uuid.uuid4()
    provider = FakeProvider(name="gemini", responses=["hong", "van hong", "hong nua"])
    service = LLMService({"gemini": provider}, redis)

    with pytest.raises(AllProvidersFailed):
        await service.run(db_session, user_id, TaskType.NORMALIZE_GOAL, "hoc React")

    row = await db_session.scalar(select(TokenLedger).where(TokenLedger.user_id == user_id))
    assert row is not None
    assert row.succeeded is False


@pytest.mark.asyncio
async def test_khong_ep_schema_thi_tra_ve_van_ban(db_session, redis):
    service = LLMService({"groq": FakeProvider(name="groq", responses=["Chao ban nhe"])}, redis)
    ket_qua = await service.run(db_session, uuid.uuid4(), TaskType.TUTOR_CHAT, "closure la gi")
    assert ket_qua == "Chao ban nhe"


@pytest.mark.asyncio
async def test_khong_co_provider_nao_thi_bao_loi_ro_rang(db_session, redis):
    service = LLMService({}, redis)
    with pytest.raises(AllProvidersFailed):
        await service.run(db_session, uuid.uuid4(), TaskType.NORMALIZE_GOAL, "hoc React")


@pytest.mark.asyncio
async def test_dinh_danh_nguoi_dung_khong_lot_vao_prompt(db_session, redis):
    user_id = uuid.uuid4()
    provider = FakeProvider(name="gemini", responses=[_GOAL_JSON])
    service = LLMService({"gemini": provider}, redis)
    await service.run(db_session, user_id, TaskType.NORMALIZE_GOAL, "hoc React")

    goi = provider.calls[0]
    assert str(user_id) not in goi.system
    assert str(user_id) not in goi.user


# --- Test bổ sung: Ruling 1 — tách usage theo provider trước khi ghi sổ ---


@pytest.mark.asyncio
async def test_tach_usage_theo_provider_khi_roi_xuong_du_phong(db_session, redis):
    """record_usage() từ chối (ValueError) một danh sách usages trộn nhiều
    provider/model. Router có thể rơi từ nhà cung cấp này sang nhà cung cấp
    khác trong CÙNG một lượt xử lý (ở đây: mistral sai schema đủ số lần cho
    phép rồi rơi xuống gemini, đúng thứ tự thật của ROUTING[NORMALIZE_GOAL])
    — nếu LLMService không tự tách usages theo (provider, model) trước khi
    gọi record_usage(), dòng dưới đây sẽ NỔ NGAY bằng ValueError thay vì ghi
    được hai dòng sổ.

    Dùng SchemaViolation (không phải RateLimited) để mistral thất bại: mỗi
    lần thử sai schema vẫn là một lần provider ĐÃ TRẢ LỜI và ĐÃ tốn token
    thật (xem docstring degrade.py) nên SchemaViolation mang usages thật của
    ba lần thử đó — RateLimited ngay lần đầu (chưa từng có phản hồi nào)
    không mang usages nào để mà trộn, nên không phải là bẫy đúng cho test
    này.

    Cờ succeeded của mỗi dòng phải phản ánh ĐÚNG nhà cung cấp đó, không phải
    một cờ chung "cả lượt xử lý có trả lời hay không": mistral tự thất bại
    (SchemaViolation) nên dòng của nó phải succeeded=False dù gemini phía
    sau trả lời thành công.
    """
    user_id = uuid.uuid4()
    mistral = FakeProvider(name="mistral", responses=["hong", "van hong", "hong nua"])
    gemini = FakeProvider(name="gemini", responses=[_GOAL_JSON])
    service = LLMService({"mistral": mistral, "gemini": gemini}, redis)

    ket_qua = await service.run(db_session, user_id, TaskType.NORMALIZE_GOAL, "hoc React")
    assert isinstance(ket_qua, NormalizedGoal)

    rows = (
        await db_session.scalars(select(TokenLedger).where(TokenLedger.user_id == user_id))
    ).all()
    theo_provider = {row.provider: row.succeeded for row in rows}
    assert theo_provider == {"mistral": False, "gemini": True}


# --- Test bổ sung: bẫy — tác vụ không ép schema vẫn phải đi qua thùng token ---


@pytest.mark.asyncio
async def test_tac_vu_khong_schema_van_di_qua_thung_token(db_session, redis):
    """Bẫy: một cách hiện thực ngây thơ cho nhánh 'không ép schema' (TUTOR_CHAT
    — REGISTRY không có response_model) là gọi thẳng provider.complete(), bỏ
    qua hoàn toàn thùng token của router — tháo bỏ đúng lá chắn hạn mức
    free-tier mà Task 17/18 dựng lên, chỉ riêng cho tác vụ hội thoại.

    Chuỗi định tuyến thật của TUTOR_CHAT là ("groq", "gemini", "mistral"); chỉ
    đăng ký "gemini" (rpm=10, xem PROVIDER_RPM) để router bỏ qua "groq" (chưa
    đăng ký) và luôn thử "gemini" trước. Gọi đúng PROVIDER_RPM["gemini"] lần
    phải thành công (làm cạn thùng); lần kế tiếp phải bị thùng chặn, và vì
    không có provider dự phòng nào khác được đăng ký, phải nổi lên
    AllProvidersFailed. Nếu tầng dịch vụ bỏ qua thùng, lần vượt hạn mức vẫn sẽ
    thành công lặng lẽ và assert cuối cùng sẽ không bao giờ nổ ra.
    """
    user_id = uuid.uuid4()
    provider = FakeProvider(name="gemini")  # responses rỗng -> luôn trả "{}"
    service = LLMService({"gemini": provider}, redis)

    for _ in range(PROVIDER_RPM["gemini"]):
        ket_qua = await service.run(db_session, user_id, TaskType.TUTOR_CHAT, "hoc React")
        assert ket_qua == "{}"

    with pytest.raises(AllProvidersFailed):
        await service.run(db_session, user_id, TaskType.TUTOR_CHAT, "hoc React")


# --- Test bổ sung: bẫy — build_providers phải khớp adapter THẬT, không phải suy đoán ---


def test_build_providers_gan_dung_adapter_that_vao_dung_khoa():
    """FakeProvider tự nhận tên/capabilities từ tham số constructor của bài
    test, nên mọi test dùng FakeProvider ở trên KHÔNG bắt được một lỗi gõ sai
    trong build_providers (vd gán nhầm GroqProvider vào khoá "mistral") — mọi
    test đó vẫn xanh dù việc định tuyến sản xuất thật đã bị đổi hướng lặng lẽ.
    Test này dựng provider bằng chính build_providers() rồi đối chiếu với các
    lớp adapter THẬT, cùng khuôn với test_routing.py::
    test_ten_provider_trong_bang_dinh_tuyen_khop_voi_adapter_that.
    """
    settings = get_settings().model_copy(
        update={
            "gemini_api_key": "khoa-gia-gemini",
            "groq_api_key": "khoa-gia-groq",
            "mistral_api_key": "khoa-gia-mistral",
            "llm_fixture_mode": "off",
        }
    )
    providers = build_providers(settings)

    assert isinstance(providers["gemini"], GeminiProvider)
    assert isinstance(providers["groq"], GroqProvider)
    assert isinstance(providers["mistral"], MistralProvider)
    for ten_khoa, provider in providers.items():
        assert provider.name == ten_khoa


def test_build_providers_bo_qua_nha_cung_cap_thieu_khoa():
    settings = get_settings().model_copy(
        update={
            "gemini_api_key": "khoa-gia-gemini",
            "groq_api_key": None,
            "mistral_api_key": None,
            "llm_fixture_mode": "off",
        }
    )
    providers = build_providers(settings)
    assert set(providers.keys()) == {"gemini"}
