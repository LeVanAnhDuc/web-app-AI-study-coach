"""Mặt tiền duy nhất của tầng LLM.

`curriculum`, `content`, `assessment`, `tutor` CHỈ được gọi qua
`LLMService.run()` — không module nghiệp vụ nào được chạm trực tiếp tới
provider, router (routing.py), hay tầng hạ cấp JSON (degrade.py). Lớp này là
nơi hội tụ HAI trách nhiệm mà không tầng nào bên dưới tự làm:

1. Tra `REGISTRY` (Task 15) theo `TaskType` để dựng đúng `CallSpec` (system
   prompt, response_model, ngân sách token, thời hạn) — module nghiệp vụ chỉ
   cần biết TÊN tác vụ và nội dung câu hỏi, không cần biết prompt hệ thống
   hay schema JSON cụ thể của tác vụ đó.
2. Ghi sổ token (ledger.py, Task 15) sau MỖI lượt gọi router — CẢ đường
   thành công lẫn đường thất bại (xem docstring `LLMService.run`), và tách
   đúng usages theo từng nhà cung cấp trước khi ghi (xem `_ghi_so_theo_provider`)
   vì `record_usage()` từ chối một danh sách trộn nhiều provider/model.

Ranh giới KHÔNG làm ở đây: không tự retry, không tự sleep, không tự truyền
đồng hồ riêng cho thùng token — mọi việc đó đã là trách nhiệm của
`LLMRouter` (routing.py); lớp này chỉ gọi router đúng cách rồi ghi sổ kết
quả router trả về.

Về BYOK (bring your own key, khoá API riêng của người dùng — keyvault.py):
NGOÀI PHẠM VI của lớp này. Chữ ký `run()` không nhận tham số khoá/nhà cung
cấp do người dùng chỉ định, và chưa có bảng CSDL nào lưu khoá BYOK ở M0/M1
(xem docstring module keyvault.py — người tiêu thụ đầu tiên là M8). Khi M8
thêm BYOK vào facade này, mỗi khoá riêng PHẢI dùng một `TokenBucket` namespaced
theo `owner` là một định danh MỜ (vd băm khoá, xem `bucket_for_provider`),
không bao giờ dùng chung thùng "shared" — và khoá API giải mã không bao giờ
được đưa vào log, lỗi, sổ token, hay prompt.
"""

import uuid
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import redis.asyncio as aioredis
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.modules.llm.fixtures import FixtureProvider
from app.modules.llm.ledger import record_usage
from app.modules.llm.providers.base import Provider
from app.modules.llm.providers.gemini import GeminiProvider
from app.modules.llm.providers.groq import GroqProvider
from app.modules.llm.providers.mistral import MistralProvider
from app.modules.llm.registry import REGISTRY
from app.modules.llm.routing import LLMRouter
from app.modules.llm.schema_util import to_provider_schema
from app.modules.llm.types import CallSpec, LLMError, TaskType, Usage


def build_providers(settings: Settings) -> dict[str, Provider]:
    """Dựng đúng những nhà cung cấp có khoá cấu hình. Thiếu khoá thì bỏ qua,
    không nổ — thiếu một nhà cung cấp chỉ làm ngắn chuỗi dự phòng của router,
    không phải lỗi khởi động.

    Khoá của dict PHẢI khớp `Provider.name` thật của chính adapter được gán
    (xem test_service.py::test_build_providers_gan_dung_adapter_that_vao_dung_khoa)
    — `LLMRouter` tra `ROUTING`/`PROVIDER_RPM` (routing.py) bằng đúng các
    chuỗi tên này, nên một khoá gõ sai ở đây sẽ âm thầm rút ngắn hoặc đổi
    hướng chuỗi định tuyến sản xuất mà không có lỗi nào báo hiệu.
    """
    providers: dict[str, Provider] = {}

    if settings.gemini_api_key:
        providers["gemini"] = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    if settings.groq_api_key:
        providers["groq"] = GroqProvider(settings.groq_api_key, settings.groq_model)
    if settings.mistral_api_key:
        providers["mistral"] = MistralProvider(settings.mistral_api_key, settings.mistral_model)

    if settings.llm_fixture_mode != "off":
        directory = Path(settings.llm_fixture_dir)
        providers = {
            name: FixtureProvider(p, settings.llm_fixture_mode, directory)
            for name, p in providers.items()
        }
    return providers


async def _ghi_so_theo_provider(
    session: AsyncSession,
    user_id: uuid.UUID | None,
    task: TaskType,
    usages: list[Usage],
    *,
    nha_cung_cap_thanh_cong: str | None,
) -> None:
    """Tách usages PHẲNG (có thể trộn nhiều provider nếu router đã rơi xuống
    dự phòng trong lượt xử lý này) thành từng nhóm `(provider, model)` rồi
    ghi MỖI nhóm một dòng sổ riêng.

    `record_usage()` TỪ CHỐI (`ValueError`) một danh sách trộn nhiều
    provider/model trong CÙNG một lời gọi (xem docstring của nó) — bảo vệ đó
    tồn tại chính vì `LLMRouter` là nơi ĐẦU TIÊN có thể sinh ra usages từ
    nhiều nhà cung cấp trong một lượt xử lý (vd Gemini rate-limit rồi rơi
    xuống Groq). TÁCH danh sách này là trách nhiệm của tầng gọi router (xem
    nguyên tắc 5 trong docstring routing.py) — tức là facade này, không phải
    của router hay của `record_usage()`.

    `nha_cung_cap_thanh_cong` là tên nhà cung cấp đã trả lời được của lượt xử
    lý này (`None` khi CẢ chuỗi đều hỏng — `AllProvidersFailed`, không có nhà
    cung cấp nào thắng). Một nhóm khác tên đó trong CÙNG lượt xử lý chắc chắn
    đã tự thất bại trước khi router rơi xuống nhà cung cấp kế tiếp, nên dòng
    sổ của nó phải mang `succeeded=False` DÙ lượt xử lý chung cuộc có trả lời
    được hay không — gán chung một cờ `succeeded=True` cho MỌI nhóm chỉ vì
    câu trả lời cuối cùng có được sẽ xoá mất đúng tín hiệu "nhà cung cấp nào
    thực sự thất bại" mà việc đo tỉ lệ khớp schema/thành công theo từng nhà
    cung cấp cần tới (xem routing.py, nguyên tắc 4 — lý do `SchemaViolation`
    cũng được gom vào usages thay vì bị nuốt).
    """
    theo_nhom: dict[tuple[str, str], list[Usage]] = defaultdict(list)
    for usage in usages:
        theo_nhom[(usage.provider, usage.model)].append(usage)

    for (ten_provider, _), usages_cua_mot_provider in theo_nhom.items():
        await record_usage(
            session,
            user_id,
            task,
            usages_cua_mot_provider,
            succeeded=(ten_provider == nha_cung_cap_thanh_cong),
        )


class LLMService:
    """Cổng duy nhất ra tầng LLM — xem docstring module."""

    def __init__(self, providers: dict[str, Provider], redis) -> None:
        self._router = LLMRouter(providers, redis)

    async def run(
        self,
        session: AsyncSession,
        user_id: uuid.UUID | None,
        task: TaskType,
        user_prompt: str,
    ) -> BaseModel | str:
        """Chạy một tác vụ LLM nghiệp vụ và ghi sổ token, trả về đối tượng đã
        kiểm theo `REGISTRY[task].response_model`, hoặc văn bản thô nếu tác
        vụ không ép schema (hiện tại chỉ `TaskType.TUTOR_CHAT`).

        `user_prompt` là nội dung nghiệp vụ do caller (`curriculum`/
        `content`/`assessment`/`tutor`) dựng sẵn — nó chảy THẲNG vào
        `CallSpec.user`, tức là vào prompt gửi cho provider free-tier. Lớp
        này KHÔNG BAO GIỜ chèn `user_id` (hay bất kỳ định danh nào khác —
        email, tên thật) vào `CallSpec`: `user_id` ở đây CHỈ dùng làm khoá
        ngoại mờ khi ghi sổ, không bao giờ được đưa vào nội dung gửi cho
        provider — dữ liệu prompt ở free tier có thể bị dùng để huấn luyện
        mô hình của bên thứ ba.

        Ghi sổ chạy trên CẢ đường thành công lẫn đường thất bại. Khi mọi nhà
        cung cấp trong chuỗi định tuyến đều hỏng, router ném
        `AllProvidersFailed` — nhưng NGOẠI LỆ ĐÓ (và thực ra là MỌI
        `LLMError`, vì thuộc tính này khai báo ở gốc cây, xem
        `types.LLMError`) vẫn mang `usages` của mọi lần thử đã tiêu token
        thật trước khi cả chuỗi thất bại. Bỏ qua bước ghi sổ ở nhánh này sẽ
        khiến số liệu báo cáo THẤP HƠN mức tiêu thụ thật — bắt lỗi lại, ghi
        sổ, rồi `raise` lại NGUYÊN VẸN để caller vẫn thấy đúng lỗi gốc.
        """
        spec_dang_ky = REGISTRY[task]
        model_cls = spec_dang_ky.response_model

        call = CallSpec(
            task=task,
            system=spec_dang_ky.system_prompt,
            user=user_prompt,
            json_schema=to_provider_schema(model_cls) if model_cls else None,
            max_output_tokens=spec_dang_ky.max_output_tokens,
            timeout_seconds=spec_dang_ky.timeout_seconds,
        )

        try:
            if model_cls is None:
                ket_qua = await self._router.complete_text(call)
            else:
                ket_qua = await self._router.complete_structured(call, model_cls)
        except LLMError as exc:
            await _ghi_so_theo_provider(
                session, user_id, task, exc.usages, nha_cung_cap_thanh_cong=None
            )
            raise

        await _ghi_so_theo_provider(
            session, user_id, task, ket_qua.usages, nha_cung_cap_thanh_cong=ket_qua.provider
        )
        return ket_qua.value


@lru_cache
def get_llm_service() -> LLMService:
    """Dependency FastAPI: một `LLMService` DUY NHẤT cho cả tiến trình.

    `lru_cache` (không phải dựng mới ở mỗi request) vì router bên trong giữ
    một kết nối Redis dùng chung và một danh sách provider — mỗi
    `GeminiProvider`/`GroqProvider`/`MistralProvider` tự giữ một
    `httpx.AsyncClient` riêng (xem docstring các adapter); dựng lại toàn bộ
    ở mỗi request vừa lãng phí vừa rò kết nối chưa đóng.
    """
    settings = get_settings()
    return LLMService(
        build_providers(settings),
        aioredis.from_url(settings.redis_url),
    )
