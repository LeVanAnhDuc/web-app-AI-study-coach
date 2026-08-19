"""Đo xem nhà cung cấp LLM free-tier nào ép được JSON schema đủ ổn định.

Đây là sản phẩm đo lường thật của M1: mọi tầng khác (adapter, hạ cấp JSON,
thùng token, két khoá, sổ token, định tuyến) chỉ là hạ tầng để chạy được
phép đo này. `ROUTING`/`PROVIDER_RPM` trong `app/modules/llm/routing.py`
hiện là PLACEHOLDER lấy verbatim từ kế hoạch — báo cáo mà script này in ra
là thứ dùng để thay chúng bằng số liệu thật.

Ruling quan trọng nhất chi phối toàn bộ file này: đo ĐÚNG khả năng NGUYÊN
BẢN của provider, không đo tầng an toàn bọc quanh nó. `do_mot_cap_tho` gọi
thẳng `provider.complete()` — ĐÚNG MỘT lần cho mỗi mẫu, dùng NGUYÊN VĂN
system prompt trong `REGISTRY`, không qua `degrade.complete_structured`
(không thử lại, không tiêm thêm chỉ dẫn JSON vào prompt cho Groq/Mistral).
Nếu đo qua `complete_structured`, thang thử lại và chỉ dẫn JSON được tiêm
thêm sẽ xoá mất đúng khác biệt giữa Gemini (ép schema gốc) và Groq/Mistral
(chỉ ép cú pháp JSON) — trong khi đó chính là câu hỏi phép đo này tồn tại để
trả lời. `do_mot_cap_sau_ha_cap` đo con số THỨ HAI, RIÊNG BIỆT (sau khi qua
toàn bộ tầng hạ cấp) — chỉ chạy khi được yêu cầu tường minh, và không bao
giờ trộn vào tỉ lệ lần-đầu.

Ba loại kết quả của một lần đo LUÔN được tách riêng, không gộp: `khop_schema`
(khớp), `sai_schema` (provider có trả lời nhưng dữ liệu sai schema), và
`loi_ha_tang` (chính provider tự lỗi — RateLimited/QuotaExhausted/
ProviderUnavailable). Loại thứ ba KHÔNG phải bằng chứng về khả năng ép
schema — nó là một lượt đo bị mất vì provider đang bận, coi nó là "sai
schema" sẽ đánh giá thấp một provider chỉ vì nó bận, càng dùng nhiều càng bị
đánh giá thấp thêm. Vì vậy `Ket_qua.ti_le_khop` (tỉ lệ khuyến nghị chính)
chia cho `da_do` (= khop_schema + sai_schema), KHÔNG chia cho `so_mau`.

GIỮ NHỊP (pacing), không phải CHẶN (gating): script này gọi provider LIÊN TIẾP
`--lan` lần cho MỖI cặp (nhà cung cấp × tác vụ) — mặc định 50 × 7 tác vụ = 350
lượt mỗi nhà cung cấp, gấp bốn nếu bật --do-ca-sau-ha-cap. Không giữ nhịp thì
toàn bộ số đó dội vào provider trong vài giây, đâm thẳng vào hạn mức theo phút
(`PROVIDER_RPM["gemini"] = 10`) và phần lớn ô trong báo cáo sẽ đọc là "chưa đo
được" SAU KHI hạn mức của ngày đã bị tiêu — kết cục tệ nhất có thể cho đúng
cái script mà cả mốc này tồn tại để tạo ra. Vì vậy `ProviderGiuNhip` NGHỈ giữa
hai lượt gọi tới cùng một nhà cung cấp, khoảng nghỉ suy ra từ `PROVIDER_RPM`.

CỐ Ý KHÔNG dùng `TokenBucket` (ratelimit.py) ở đây, dù nó tồn tại và biết đúng
những con số này. Thùng token TỪ CHỐI khi hết token, còn một lượt bị từ chối ở
đây sẽ được đếm thành "không đo được" — tức là mất đúng cái mẫu ta đang trả
tiền để lấy. Giữ nhịp BẢO TOÀN mọi mẫu, chặn thì loại bỏ mẫu. Đây là một trong
rất ít chỗ mà việc đi vòng qua thùng token là ĐÚNG, và lý do là vì mục đích ở
đây là ĐO chứ không phải PHỤC VỤ.

Giữ nhịp cũng KHÔNG mâu thuẫn với ruling "đo provider gốc, không đo tầng an
toàn" ở trên: nó chỉ thêm một khoảng nghỉ giữa các lượt, không đổi prompt,
không thử lại, không đọc/sửa câu trả lời. Cái được đo không thay đổi.

BÁO CÁO CHI PHÍ: mỗi lượt đo trả về một `Usage` mà trước đây bị bỏ đi. Nay
tổng token vào/ra được cộng dồn theo từng nhà cung cấp và ghi vào chính file
báo cáo (mục "Chi phí lượt chạy"), để người vận hành thấy lượt chạy vừa rồi tốn
bao nhiêu. CỐ Ý không ghi vào sổ token (ledger.py): đây là một script độc lập,
thêm phụ thuộc CSDL vào nó chỉ để in một con số sẽ làm nó không chạy được ở
đúng nơi người ta hay chạy nó nhất — một máy chỉ có khoá API.

Chạy thử KHÔNG tốn hạn mức (dùng fixture đã ghi sẵn, xem
app.modules.llm.fixtures — build_providers() tự bọc FixtureProvider khi
LLM_FIXTURE_MODE=replay). LƯU Ý: `build_providers()` chỉ dựng nhà cung cấp có
khoá KHÁC RỖNG, nên chế độ replay VẪN CẦN một khoá GIẢ trong môi trường (giá
trị bất kỳ, không bao giờ được gửi đi đâu vì FixtureProvider đọc từ đĩa) —
thiếu nó, script thoát với lỗi "chưa có khoá":
    GEMINI_API_KEY=khoa-gia LLM_FIXTURE_MODE=replay \
        python scripts/measure_json_compliance.py --live --lan 2
Chế độ replay KHÔNG giữ nhịp (không có gì để tiết chế), nên chạy thử vẫn nhanh.

Chạy thật (TỐN HẠN MỨC MIỄN PHÍ TRONG NGÀY — cần khoá thật trong .env):
    python scripts/measure_json_compliance.py --live --lan 50
Ở chế độ này giữ nhịp làm lượt chạy DÀI THẬT (350 lượt ở 10 rpm là khoảng 35
phút cho riêng Gemini). Đó là đánh đổi có chủ đích: một lượt chạy 35 phút cho
ra số liệu dùng được thì tốt hơn một lượt chạy 30 giây tiêu hết hạn mức ngày và
không đo được gì. `chay()` in ước lượng thời gian trước khi bắt đầu.

Không truyền --live thì script không đụng mạng gì cả — chỉ in cảnh báo rồi
thoát ngay (xem main()).
"""

import argparse
import asyncio
import dataclasses
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from pydantic import ValidationError

from app.config import Settings, get_settings
from app.modules.llm.degrade import complete_structured, extract_json
from app.modules.llm.fixtures import FixtureMissing
from app.modules.llm.providers.base import Provider
from app.modules.llm.registry import REGISTRY
from app.modules.llm.routing import PROVIDER_RPM
from app.modules.llm.schema_util import to_provider_schema
from app.modules.llm.service import build_providers
from app.modules.llm.types import CallSpec, LLMError, SchemaViolation, TaskType, Usage

# Prompt mẫu cho từng tác vụ CÓ ép schema (response_model khác None trong
# REGISTRY). TUTOR_CHAT cố ý KHÔNG có mặt ở đây — nó không ép schema, nên
# không có gì để đo "khớp schema" (xem test_tutor_chat_khong_can_prompt_mau).
# Nội dung không chứa dữ liệu người dùng thật — đây là dữ liệu tổng hợp cố
# định, dùng lại cho mọi lần đo để kết quả các lần đo có thể so sánh được.
SAMPLES: dict[TaskType, str] = {
    TaskType.NORMALIZE_GOAL: (
        "Mình muốn học React trong khoảng 8 tuần, mỗi tuần rảnh chừng 5 tiếng. "
        "Hiện tại mình biết JavaScript cơ bản, muốn tự dựng được một app nhỏ."
    ),
    TaskType.GENERATE_PLACEMENT: (
        "Chủ đề: React. Trình độ khai báo: JavaScript cơ bản. "
        "Soạn bài kiểm tra đầu vào để đo xem người học đã nắm được gì."
    ),
    TaskType.GENERATE_SYLLABUS: (
        "Chủ đề: React. Từ JavaScript cơ bản tới tự dựng được app. "
        "Ngân sách 8 tuần, mỗi tuần 300 phút, tổng 2400 phút. "
        "Người học đã vững arrow function, còn yếu closure."
    ),
    TaskType.GENERATE_LESSON: (
        "Bài: useState và vòng đời render. Mục tiêu: hiểu state là gì; "
        "biết khi nào component render lại; tránh được lỗi cập nhật state trong vòng lặp."
    ),
    TaskType.GENERATE_QUIZ: (
        "Bài: useState và vòng đời render. Mục tiêu như trên. "
        "Danh sách concept_tag được phép dùng: react-usestate, react-render-cycle."
    ),
    TaskType.GRADE_FREE_TEXT: (
        "Rubric: (1) nêu được state là dữ liệu thay đổi theo thời gian; "
        "(2) nêu được việc đổi state gây render lại; (3) có ví dụ cụ thể.\n"
        "<cau_tra_loi>State là dữ liệu của component. Khi gọi setState thì "
        "component vẽ lại.</cau_tra_loi>"
    ),
    TaskType.GENERATE_REMEDIAL_LESSON: (
        "Concept cần ôn: closure trong JavaScript. Người học sai 3 trên 5 câu, "
        "nhầm chỗ biến bị giữ lại sau khi hàm ngoài kết thúc."
    ),
}

# Ngưỡng dưới đây, một tỉ lệ % không đủ mẫu để tin — dùng để một cell 2 mẫu
# không bao giờ được đọc giống một cell 50 mẫu (xem render_report, ruling 3).
_MAU_TOI_THIEU_DANG_TIN = 10

# Dùng khi một nhà cung cấp không có mặt trong PROVIDER_RPM. Cố ý chọn giá trị
# THẤP NHẤT trong bảng hiện tại: một nhà cung cấp chưa khai hạn mức thì đoán
# THẬN TRỌNG mới đúng chiều — đoán cao sẽ tiêu hạn mức của nó trước khi ai kịp
# nhận ra là bảng còn thiếu.
_RPM_MAC_DINH = min(PROVIDER_RPM.values())


def _giay_moi_luot_goi(ten_provider: str) -> float:
    """Khoảng nghỉ TỐI THIỂU giữa hai lượt gọi tới CÙNG một nhà cung cấp, suy
    ra từ `PROVIDER_RPM` (xem docstring module: giữ nhịp, không chặn).

    `60 / rpm` là nhịp đúng bằng hạn mức, không chậm hơn — bảng `PROVIDER_RPM`
    đã tự đặt thấp hơn hạn mức công bố để chừa biên an toàn (xem chú thích của
    nó), nên nhân thêm hệ số ở đây là trừ biên hai lần và làm lượt chạy dài vô
    ích.
    """
    rpm = PROVIDER_RPM.get(ten_provider, _RPM_MAC_DINH)
    if rpm <= 0:
        return 0.0
    return 60.0 / rpm


class ProviderGiuNhip:
    """Bọc một `Provider` để NGHỈ đủ lâu trước mỗi lượt `complete()`.

    Bọc ở tầng `Provider` (không rải `asyncio.sleep` vào hai vòng lặp đo) vì
    `do_mot_cap_sau_ha_cap` gọi provider GIÁN TIẾP qua `degrade.py`, có thể tới
    ba lượt cho một "mẫu" — đếm nhịp ở vòng lặp đo sẽ bỏ sót đúng những lượt
    thử lại đó, tức là bỏ sót phần dồn dập nhất. Ở đây thì mọi lượt gọi thật,
    dù đi đường nào, cũng phải qua đúng một chỗ.

    Chuyển tiếp NGUYÊN VẸN `name`/`model`/`capabilities`: `degrade.py` đọc
    `capabilities` để quyết định có tiêm chỉ dẫn JSON hay không, và hai vòng
    lặp đo đọc `name`/`model` để gán vào dòng báo cáo — một thuộc tính bị bỏ
    sót ở đây sẽ âm thầm đổi CÁI ĐANG ĐƯỢC ĐO, không chỉ nhịp đo.
    """

    def __init__(self, goc, giay_moi_luot: float) -> None:
        self._goc = goc
        self._giay_moi_luot = giay_moi_luot
        self._moc_luot_truoc: float | None = None

    @property
    def name(self) -> str:
        return self._goc.name

    @property
    def model(self) -> str:
        return self._goc.model

    @property
    def capabilities(self):
        return self._goc.capabilities

    async def complete(self, spec: CallSpec) -> tuple[str, Usage]:
        await self._cho_du_nhip()
        return await self._goc.complete(spec)

    async def _cho_du_nhip(self) -> None:
        """Nghỉ phần CÒN LẠI của nhịp, tính từ lúc bắt đầu lượt trước.

        Trừ đi thời gian lượt trước đã tốn (thay vì nghỉ trọn `giay_moi_luot`
        sau mỗi lượt) vì một lượt gọi LLM thật mất vài giây — nghỉ trọn nhịp
        THÊM vào thời gian đó sẽ làm nhịp thực tế chậm gần gấp đôi hạn mức, và
        một lượt chạy 35 phút thành hơn một giờ mà không an toàn hơn chút nào.
        `monotonic()` (không phải `time()`) để việc đổi giờ hệ thống giữa lượt
        chạy không làm nhịp nhảy.
        """
        if self._giay_moi_luot <= 0:
            return
        if self._moc_luot_truoc is not None:
            con_lai = self._giay_moi_luot - (monotonic() - self._moc_luot_truoc)
            if con_lai > 0:
                await asyncio.sleep(con_lai)
        self._moc_luot_truoc = monotonic()

    async def aclose(self) -> None:
        await self._goc.aclose()


def _ngay_hom_nay() -> str:
    """Ngày dùng trong tên file và tiêu đề báo cáo — lấy theo UTC, không dùng
    `date.today()` (phụ thuộc múi giờ máy chạy, hai máy có thể ra hai ngày
    khác nhau cho cùng một lượt đo)."""
    return datetime.now(UTC).date().isoformat()


@dataclass
class Ket_qua:
    """Kết quả đo một cặp (nhà cung cấp × tác vụ).

    Ba trường `khop_schema`/`sai_schema`/`loi_ha_tang` TÁCH BIỆT có chủ đích
    (xem docstring module) — cộng lại đúng bằng `so_mau`. `khop_sau_ha_cap`/
    `sai_sau_ha_cap`/`loi_sau_ha_cap` là phép đo THỨ HAI, tuỳ chọn, RIÊNG với
    ba trường trên — mặc định None khi không đo, không bao giờ được suy ra
    từ (hay trộn vào) tỉ lệ lần-đầu.
    """

    provider: str
    model: str
    task: str
    so_mau: int
    khop_schema: int
    sai_schema: int
    loi_ha_tang: int
    tong_giay: float
    khop_sau_ha_cap: int | None = None
    sai_sau_ha_cap: int | None = None
    loi_sau_ha_cap: int | None = None
    # Token THẬT SỰ đã tiêu cho ô này, lấy từ `Usage` mà provider trả về (và từ
    # `LLMError.usages` trên các lượt hỏng SAU khi provider đã tính tiền — xem
    # chú thích trong hai adapter). Tách riêng lần-đầu và sau-hạ-cấp theo đúng
    # nguyên tắc của ba trường đếm ở trên: hai phép đo khác nhau, không gộp.
    token_vao: int = 0
    token_ra: int = 0
    token_vao_sau_ha_cap: int = 0
    token_ra_sau_ha_cap: int = 0

    @property
    def tong_token(self) -> int:
        """Tổng token của CẢ hai phép đo — con số "lượt chạy này tốn bao nhiêu"."""
        return self.token_vao + self.token_ra + self.token_vao_sau_ha_cap + self.token_ra_sau_ha_cap

    @property
    def da_do(self) -> int:
        """Số mẫu THỰC SỰ đo được khả năng ép schema (loại trừ lỗi hạ tầng)."""
        return self.khop_schema + self.sai_schema

    @property
    def ti_le_khop(self) -> float:
        """Tỉ lệ khớp schema TRÊN SỐ MẪU ĐÃ ĐO ĐƯỢC — đây là tỉ lệ khuyến
        nghị chính (xem docstring module, ruling 2)."""
        return 0.0 if self.da_do == 0 else self.khop_schema / self.da_do * 100

    @property
    def ti_le_khop_tong_mau(self) -> float:
        """Tỉ lệ khớp schema trên TỔNG SỐ MẪU (kể cả lượt bị mất vì lỗi hạ
        tầng) — chỉ để đối chiếu, KHÔNG dùng để xếp hạng khuyến nghị, vì nó
        đánh giá thấp một provider chỉ vì provider đó bận."""
        return 0.0 if self.so_mau == 0 else self.khop_schema / self.so_mau * 100

    @property
    def giay_tb(self) -> float:
        return 0.0 if self.so_mau == 0 else self.tong_giay / self.so_mau

    @property
    def da_do_sau_ha_cap(self) -> int | None:
        if self.khop_sau_ha_cap is None:
            return None
        return self.khop_sau_ha_cap + (self.sai_sau_ha_cap or 0)

    @property
    def ti_le_khop_sau_ha_cap(self) -> float | None:
        if self.khop_sau_ha_cap is None:
            return None
        mau = self.da_do_sau_ha_cap
        return 0.0 if not mau else self.khop_sau_ha_cap / mau * 100


def _spec_cho_tac_vu(task: TaskType) -> CallSpec:
    """Dựng CallSpec y hệt cách LLMService (Task 19) sẽ dựng cho tác vụ này —
    dùng chung một prompt hệ thống và schema với sản xuất thật, chỉ khác nội
    dung `user` (SAMPLES thay vì prompt của người dùng thật)."""
    spec_dang_ky = REGISTRY[task]
    model_cls = spec_dang_ky.response_model
    assert model_cls is not None, f"{task} không ép schema, không đo được"
    return CallSpec(
        task=task,
        system=spec_dang_ky.system_prompt,
        user=SAMPLES[task],
        json_schema=to_provider_schema(model_cls),
        max_output_tokens=spec_dang_ky.max_output_tokens,
        timeout_seconds=spec_dang_ky.timeout_seconds,
    )


async def do_mot_cap_tho(provider: Provider, task: TaskType, so_lan: int) -> Ket_qua:
    """Đo khả năng NGUYÊN BẢN của `provider` cho `task`: `so_lan` lần gọi
    ĐỘC LẬP, mỗi lần ĐÚNG MỘT lượt `provider.complete()` — không thử lại,
    không tiêm chỉ dẫn JSON (xem docstring module). `extract_json` (từ
    degrade.py) được dùng chỉ để BÓC văn bản JSON ra khỏi khối markdown nếu
    có — đây là cách DIỄN GIẢI câu trả lời đã có sẵn, áp dụng như nhau cho
    mọi provider, không phải một cách GIÚP provider trả lời đúng hơn, nên
    không vi phạm nguyên tắc "đo nguyên bản, không đo tầng an toàn".

    Bắt `LLMError` RỘNG cho lỗi hạ tầng THẬT (RateLimited/QuotaExhausted/
    ProviderUnavailable của `Provider.complete()` thật) — một lượt đo bị mất
    vì provider bận, đúng ý nghĩa `loi_ha_tang` (xem docstring module).

    `FixtureMissing` (app.modules.llm.fixtures) CỐ Ý KHÔNG bị bắt ở đây dù
    nó cũng là một `LLMError`: khi `provider` là một `FixtureProvider` ở chế
    độ replay, fixture thiếu LUÔN LUÔN là lỗi thao tác của người vận hành
    (bộ fixture không đầy đủ), KHÔNG BAO GIỜ là một kết quả đo hợp lệ để
    gộp vào `loi_ha_tang` — coi nó như provider bận sẽ tạo ra một báo cáo
    TRÔNG như đo được một phần trong khi sự thật là cả lượt chạy đã hỏng.
    Để nó lọt lên `chay()` (nơi có ngữ cảnh provider/tác vụ đang đo) để dừng
    CẢ lượt chạy ngay, thay vì âm thầm tiếp tục rồi ghi báo cáo sai."""
    model_cls = REGISTRY[task].response_model
    assert model_cls is not None
    call = _spec_cho_tac_vu(task)

    khop = sai = loi = 0
    tong_giay = 0.0
    token_vao = token_ra = 0

    for _ in range(so_lan):
        bat_dau = monotonic()
        try:
            text, usage = await provider.complete(call)
        except FixtureMissing:
            raise
        except LLMError as loi_ha_tang_that:
            loi += 1
            # Một lỗi hạ tầng vẫn có thể ĐÃ tiêu token: mọi chỗ ném SAU một
            # HTTP 200 trong hai adapter đều mang usages (finishReason
            # MAX_TOKENS/length đã tiêu TRỌN ngân sách output; prompt bị chặn
            # vẫn tiêu trọn token prompt). Bỏ qua chúng ở đây sẽ làm mục chi phí
            # của báo cáo thấp hơn thực tế đúng ở những lượt tốn nhất.
            token_vao += sum(u.input_tokens for u in loi_ha_tang_that.usages)
            token_ra += sum(u.output_tokens for u in loi_ha_tang_that.usages)
            tong_giay += monotonic() - bat_dau
            continue
        tong_giay += monotonic() - bat_dau
        token_vao += usage.input_tokens
        token_ra += usage.output_tokens

        try:
            model_cls.model_validate_json(extract_json(text))
            khop += 1
        except ValidationError:
            sai += 1

    return Ket_qua(
        provider=provider.name,
        model=provider.model,
        task=task.value,
        so_mau=so_lan,
        khop_schema=khop,
        sai_schema=sai,
        loi_ha_tang=loi,
        tong_giay=tong_giay,
        token_vao=token_vao,
        token_ra=token_ra,
    )


@dataclass
class KetQuaSauHaCap:
    """Kết quả phép đo THỨ HAI (sau tầng hạ cấp) cho một cặp.

    Là một dataclass, không phải tuple: phép đo này giờ trả về SÁU giá trị, và
    một tuple sáu phần tử ở nơi gọi (`khop, sai, loi, giay, vao, ra = ...`) chỉ
    cần đảo hai vị trí là ghi sai số liệu mà không có lỗi nào báo.
    """

    khop: int
    sai: int
    loi: int
    tong_giay: float
    token_vao: int
    token_ra: int


async def do_mot_cap_sau_ha_cap(provider: Provider, task: TaskType, so_lan: int) -> KetQuaSauHaCap:
    """Đo con số THỨ HAI, RIÊNG với `do_mot_cap_tho`: tỉ lệ thành công SAU
    KHI đi qua toàn bộ tầng hạ cấp (degrade.py — ép + kiểm + tối đa 2 lần
    thử lại, có tiêm chỉ dẫn JSON cho provider không ép schema gốc). Một
    "mẫu" ở đây là một LƯỢT XỬ LÝ hoàn chỉnh của complete_structured, có thể
    tốn nhiều hơn một lượt gọi provider bên trong nếu có thử lại — điều đó
    ĐÚNG với cách LLMService thật sự dùng tầng hạ cấp, nên đây chính là con
    số phản ánh trải nghiệm người dùng thật, KHÔNG được trộn với tỉ lệ
    lần-đầu ở `do_mot_cap_tho` (ruling 1).

    `FixtureMissing` CỐ Ý KHÔNG bị bắt vào `loi` — cùng lý do với
    `do_mot_cap_tho` (xem docstring ở đó): fixture thiếu ở chế độ replay là
    lỗi thao tác, không phải một kết quả đo, và phải lọt lên `chay()` để
    dừng cả lượt chạy."""
    model_cls = REGISTRY[task].response_model
    assert model_cls is not None
    call = _spec_cho_tac_vu(task)

    khop = sai = loi = 0
    tong_giay = 0.0
    token_vao = token_ra = 0

    def _cong_don(usages: list[Usage]) -> None:
        nonlocal token_vao, token_ra
        token_vao += sum(u.input_tokens for u in usages)
        token_ra += sum(u.output_tokens for u in usages)

    for _ in range(so_lan):
        bat_dau = monotonic()
        try:
            _gia_tri, usages = await complete_structured(provider, call, model_cls)
            khop += 1
            _cong_don(usages)
        except FixtureMissing:
            raise
        except SchemaViolation as loi_schema:
            sai += 1
            # `SchemaViolation` mang usages của MỌI lượt thử đã hỏng (C-51) —
            # một "mẫu" thất bại ở đây tốn tới ba lượt gọi thật, đúng phần đắt
            # nhất của lượt chạy. Bỏ qua nó là báo cáo chi phí thấp hơn thực tế
            # ở chỗ nó lệch nhiều nhất.
            _cong_don(loi_schema.usages)
        except LLMError as loi_ha_tang_that:
            loi += 1
            _cong_don(loi_ha_tang_that.usages)
        tong_giay += monotonic() - bat_dau

    return KetQuaSauHaCap(
        khop=khop,
        sai=sai,
        loi=loi,
        tong_giay=tong_giay,
        token_vao=token_vao,
        token_ra=token_ra,
    )


def in_an_toan(dong: str, stream=None) -> None:
    """In một dòng, không bao giờ ném UnicodeEncodeError.

    Console mặc định của Windows dùng bảng mã cp1252, không biểu diễn được
    toàn bộ tiếng Việt có dấu — một báo cáo tiếng Việt in thẳng bằng print()
    có thể làm CHÍNH SCRIPT ĐO này crash giữa chừng khi đang tốn hạn mức
    miễn phí. Thử ghi bình thường trước (giữ nguyên trải nghiệm terminal hỗ
    trợ UTF-8); chỉ khi ghi bình thường ném UnicodeEncodeError mới rơi về
    ghi thẳng byte UTF-8 (thay thế ký tự không mã hoá được) xuống bộ đệm nhị
    phân bên dưới stream.
    """
    stream = stream if stream is not None else sys.stdout
    try:
        stream.write(dong + "\n")
    except UnicodeEncodeError:
        bo_dem = getattr(stream, "buffer", None)
        if bo_dem is not None:
            bo_dem.write((dong + "\n").encode("utf-8", errors="replace"))


def _dinh_dang_ti_le(r: Ket_qua) -> str:
    return "chưa đo được" if r.da_do == 0 else f"{r.ti_le_khop:.0f}%"


def _muc_chi_phi(rows: list[Ket_qua]) -> list[str]:
    """Mục "Chi phí lượt chạy": tổng token đã tiêu, cộng dồn theo TỪNG nhà cung
    cấp.

    Đây là câu trả lời cho câu hỏi mà người vận hành sẽ hỏi ngay sau khi chạy —
    "vừa rồi tốn bao nhiêu hạn mức của hôm nay?" — và trước bản sửa này script
    không trả lời được: `Usage` mà provider trả về bị bỏ đi ngay tại chỗ nhận.
    Ghi vào FILE BÁO CÁO chứ không vào sổ token (ledger.py): script này phải
    chạy được trên một máy chỉ có khoá API, không có CSDL.

    Tách cột lần-đầu và sau-hạ-cấp theo đúng nguyên tắc của bảng %Khớp: hai
    phép đo khác nhau, và chỉ cột thứ hai thay đổi khi bật --do-ca-sau-ha-cap.
    """
    theo_provider: dict[str, list[Ket_qua]] = {}
    for r in rows:
        theo_provider.setdefault(r.provider, []).append(r)
    if not theo_provider:
        return []

    dong = [
        "",
        "## Chi phí lượt chạy",
        "",
        (
            "Token THẬT SỰ đã tiêu, gồm cả các lượt hỏng SAU khi nhà cung cấp đã "
            "tính tiền (hết ngân sách output, prompt bị chặn, sai schema ở mọi lượt "
            "thử lại). Đây là số liệu ĐO ĐƯỢC từ phản hồi của nhà cung cấp, không "
            "phải ước lượng. Cột *sau hạ cấp* chỉ khác 0 khi chạy với "
            "`--do-ca-sau-ha-cap`."
        ),
        "",
        (
            "| Nhà cung cấp | Lượt gọi (lần-đầu) | Token vào | Token ra "
            "| Token vào (sau hạ cấp) | Token ra (sau hạ cấp) | Tổng token |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    tong_chung = 0
    for ten, nhom in sorted(theo_provider.items()):
        tong_chung += sum(r.tong_token for r in nhom)
        dong.append(
            f"| {ten} | {sum(r.so_mau for r in nhom)} "
            f"| {sum(r.token_vao for r in nhom)} | {sum(r.token_ra for r in nhom)} "
            f"| {sum(r.token_vao_sau_ha_cap for r in nhom)} "
            f"| {sum(r.token_ra_sau_ha_cap for r in nhom)} "
            f"| {sum(r.tong_token for r in nhom)} |"
        )
    dong.append(f"| **tất cả** | | | | | | **{tong_chung}** |")
    return dong


def render_report(rows: list[Ket_qua]) -> str:
    """Dựng báo cáo Markdown — bảng ổn định, diff được giữa các lần chạy.

    Mỗi dòng của bảng chính là một cặp (nhà cung cấp × tác vụ) — KHÔNG gộp
    thành một số mỗi nhà cung cấp (ruling 3): providers khác nhau theo TỪNG
    tác vụ, gộp lại sẽ xoá mất đúng khác biệt cần để định tuyến theo tác vụ.
    Mẫu số của %Khớp luôn tường minh (cột *Đo được*, ruling 2) và mục
    Khuyến nghị luôn kèm `n=` để một cell 2 mẫu không trông giống cell 50
    mẫu (ruling 3).
    """
    dong = [
        f"# Đo khả năng ép JSON schema — {_ngay_hom_nay()}",
        "",
        (
            "Đo TRỰC TIẾP trên provider gốc, KHÔNG qua tầng hạ cấp (degrade.py): "
            "mỗi mẫu là ĐÚNG MỘT lần gọi, không thử lại, không thêm chỉ dẫn JSON "
            "vào prompt. Cột **%Khớp** tính trên số mẫu **Đo được** (= Khớp + Sai "
            "schema), KHÔNG tính trên **Mẫu** — một nhà cung cấp bận (bị giới hạn "
            "tần suất hoặc hết hạn mức) không phải bằng chứng nó ép schema kém, "
            "chỉ là một lượt đo bị mất."
        ),
        "",
        (
            "| Nhà cung cấp | Mô hình | Tác vụ | Mẫu | Đo được | Khớp | Sai schema"
            " | Lỗi hạ tầng | %Khớp | Giây TB |"
        ),
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(rows, key=lambda x: (x.task, -x.ti_le_khop)):
        dong.append(
            f"| {r.provider} | {r.model} | {r.task} | {r.so_mau} | {r.da_do} "
            f"| {r.khop_schema} | {r.sai_schema} | {r.loi_ha_tang} "
            f"| {_dinh_dang_ti_le(r)} | {r.giay_tb:.1f} |"
        )

    if any(r.khop_sau_ha_cap is not None for r in rows):
        dong += [
            "",
            "## Sau khi qua tầng hạ cấp (degrade.py)",
            "",
            (
                "Con số THỨ HAI, RIÊNG với bảng trên — có thử lại tối đa 2 lần và "
                "tiêm chỉ dẫn JSON. KHÔNG trộn với %Khớp lần-đầu ở trên: hai cột "
                "trả lời hai câu hỏi khác nhau (khả năng nguyên bản của provider, "
                "và khả năng của toàn bộ tầng an toàn bọc quanh nó)."
            ),
            "",
            "| Nhà cung cấp | Tác vụ | %Khớp lần-đầu | %Khớp sau hạ cấp |",
            "|---|---|---:|---:|",
        ]
        for r in sorted(rows, key=lambda x: x.task):
            if r.khop_sau_ha_cap is None:
                continue
            ti_le_sau = r.ti_le_khop_sau_ha_cap
            hien_thi_sau = "chưa đo được" if ti_le_sau is None else f"{ti_le_sau:.0f}%"
            dong.append(f"| {r.provider} | {r.task} | {_dinh_dang_ti_le(r)} | {hien_thi_sau} |")

    dong += _muc_chi_phi(rows)

    dong += ["", "## Khuyến nghị định tuyến", ""]
    theo_task: dict[str, list[Ket_qua]] = {}
    for r in rows:
        theo_task.setdefault(r.task, []).append(r)

    for task, nhom in sorted(theo_task.items()):
        xep = sorted(nhom, key=lambda x: (-x.ti_le_khop, x.giay_tb))
        chuoi = " → ".join(
            f"{r.provider} ({_dinh_dang_ti_le(r)}, n={r.so_mau})"
            + (" [mẫu nhỏ]" if r.so_mau < _MAU_TOI_THIEU_DANG_TIN else "")
            for r in xep
        )
        dong.append(f"- `{task}`: {chuoi}")

    dong += [
        "",
        (
            "**Việc phải làm sau khi đọc báo cáo này:** cập nhật `ROUTING` trong "
            "`app/modules/llm/routing.py` và bảng định tuyến ở mục 7 của spec cho "
            "khớp. Tác vụ nào không nhà cung cấp nào đạt trên 90% (trên số mẫu ĐÃ "
            "ĐO ĐƯỢC, không phải trên tổng mẫu) thì phải đơn giản hoá schema hoặc "
            "tách nhỏ tác vụ, chứ không được để nguyên rồi hy vọng."
        ),
    ]
    return "\n".join(dong)


async def chay(
    settings: Settings,
    so_lan: int,
    thu_muc_bao_cao: Path | None = None,
    do_ca_sau_ha_cap: bool = False,
) -> Path:
    """Chạy phép đo cho MỌI nhà cung cấp đã cấu hình × MỌI tác vụ ép schema,
    ghi báo cáo ra đĩa, trả về đường dẫn file đã ghi.

    `build_providers(settings)` tự bọc `FixtureProvider` khi
    `settings.llm_fixture_mode != "off"` — nghĩa là hàm này CHẠY ĐƯỢC hệt
    nhau dù đang phát lại fixture đã ghi sẵn (không đụng mạng) hay đang gọi
    provider thật, không cần script này biết fixture tồn tại. `settings` và
    `thu_muc_bao_cao` là tham số tiêm vào (không đọc `get_settings()`/đường
    dẫn cứng bên trong hàm) để test dựng được settings giả và thư mục tạm mà
    không cần khoá thật hay chạm ổ đĩa dự án.
    """
    providers = build_providers(settings)
    if not providers:
        raise SystemExit(
            "Chưa có khoá của nhà cung cấp nào. Đặt GEMINI_API_KEY, "
            "GROQ_API_KEY, hoặc MISTRAL_API_KEY trong .env. "
            "LƯU Ý cho chế độ chạy thử: LLM_FIXTURE_MODE=replay VẪN CẦN một "
            "trong ba biến đó được đặt một giá trị GIẢ khác rỗng (ví dụ "
            "GEMINI_API_KEY=khoa-gia) — build_providers() chỉ dựng nhà cung cấp "
            "có khoá khác rỗng, và ở chế độ replay khoá đó không bao giờ được "
            "gửi đi đâu vì mọi phản hồi đọc từ fixture trên đĩa."
        )

    # GIỮ NHỊP, không CHẶN (xem docstring module). Chế độ replay KHÔNG giữ nhịp:
    # không có lượt gọi mạng nào để tiết chế, và nghỉ 6 giây giữa các lần đọc
    # file sẽ làm một lượt chạy thử 350 mẫu mất 35 phút mà không bảo vệ gì cả.
    # Chế độ "record" thì CÓ gọi thật, nên vẫn phải giữ nhịp như chạy thường.
    khong_giu_nhip = settings.llm_fixture_mode == "replay"
    nhip = {ten: (0.0 if khong_giu_nhip else _giay_moi_luot_goi(ten)) for ten in providers}
    providers = {ten: ProviderGiuNhip(p, nhip[ten]) for ten, p in providers.items()}

    in_an_toan(
        "CẢNH BÁO: các lượt gọi tiếp theo tiêu hạn mức miễn phí dùng chung "
        "với người dùng thật trong ngày hôm nay (trừ khi đang ở chế độ "
        "LLM_FIXTURE_MODE=replay)."
    )

    can_do = [t for t, spec in REGISTRY.items() if spec.response_model is not None]

    if khong_giu_nhip:
        in_an_toan("Chế độ replay: KHÔNG giữ nhịp (không có lượt gọi mạng nào).")
    else:
        # In ước lượng TRƯỚC khi bắt đầu: giữ nhịp làm lượt chạy dài thật, và
        # người vận hành cần biết điều đó lúc còn kịp bấm Ctrl-C, không phải sau
        # 35 phút. Ước lượng chỉ tính thời gian NGHỈ (thời gian chờ provider trả
        # lời cộng thêm vào, nên đây là giới hạn DƯỚI) và nêu rõ như vậy.
        for ten in providers:
            so_luot = so_lan * len(can_do) * (2 if do_ca_sau_ha_cap else 1)
            phut = so_luot * nhip[ten] / 60
            in_an_toan(
                f"Giữ nhịp {ten}: {nhip[ten]:.1f}s/lượt (từ PROVIDER_RPM="
                f"{PROVIDER_RPM.get(ten, _RPM_MAC_DINH)}) — ít nhất ~{phut:.0f} phút "
                f"cho khoảng {so_luot} lượt."
            )

    rows: list[Ket_qua] = []

    for ten, provider in providers.items():
        in_an_toan(f"Đang đo {ten} (model={provider.model})…")
        for task in can_do:
            try:
                hang = await do_mot_cap_tho(provider, task, so_lan)
                if do_ca_sau_ha_cap:
                    # Bỏ qua thời gian đo-sau-hạ-cấp (`sau.tong_giay`):
                    # Ket_qua.tong_giay chỉ đo lần-đầu, trộn chung hai khoảng
                    # thời gian đo hai thứ khác nhau vào một cột sẽ làm sai
                    # giay_tb báo cáo lần-đầu. Nhưng TOKEN thì phải cộng vào —
                    # nó là chi phí thật của lượt chạy, không phải một phép đo
                    # cạnh tranh với phép đo lần-đầu.
                    sau = await do_mot_cap_sau_ha_cap(provider, task, so_lan)
                    hang = dataclasses.replace(
                        hang,
                        khop_sau_ha_cap=sau.khop,
                        sai_sau_ha_cap=sau.sai,
                        loi_sau_ha_cap=sau.loi,
                        token_vao_sau_ha_cap=sau.token_vao,
                        token_ra_sau_ha_cap=sau.token_ra,
                    )
            except FixtureMissing as loi_fixture:
                # Fixture thiếu ở chế độ replay LUÔN LUÔN là lỗi thao tác
                # (bộ fixture không đầy đủ), KHÔNG PHẢI một kết quả đo hợp lệ
                # để âm thầm đếm vào loi_ha_tang rồi tiếp tục — làm vậy sẽ ghi
                # ra một báo cáo TRÔNG như đã đo đủ trong khi lượt chạy này
                # thực ra đã hỏng, đúng thứ script này tồn tại để KHÔNG làm
                # (một con số trông có vẻ đáng tin nhưng không phải vậy). Nêu
                # rõ provider/tác vụ đang đo dở, dừng CẢ lượt chạy ngay, không
                # ghi báo cáo nào — qua in_an_toan()/_thoat_an_toan() để
                # thông điệp còn đọc được trên console Windows cp1252.
                _thoat_an_toan(
                    "Thiếu fixture khi phát lại (LLM_FIXTURE_MODE=replay), "
                    f"đang đo {ten}/{task.value}: {loi_fixture} Đây là lỗi "
                    "thao tác (bộ fixture không đầy đủ) — dừng lượt chạy, "
                    "KHÔNG ghi báo cáo. Ghi lại fixture còn thiếu (chế độ "
                    "record) rồi chạy lại."
                )
            rows.append(hang)
        await provider.aclose()

    bao_cao = render_report(rows)
    thu_muc = thu_muc_bao_cao or (Path(__file__).resolve().parents[2] / "docs" / "design")
    thu_muc.mkdir(parents=True, exist_ok=True)
    duong_dan = thu_muc / f"llm-compliance-{_ngay_hom_nay()}.md"
    duong_dan.write_text(bao_cao, encoding="utf-8")

    in_an_toan(f"Đã ghi báo cáo: {duong_dan.resolve()}")
    in_an_toan("")
    in_an_toan(bao_cao)
    return duong_dan


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Đo khả năng ép JSON schema của từng nhà cung cấp LLM free-tier"
    )
    parser.add_argument(
        "--lan", type=int, default=50, help="Số lần gọi mỗi cặp (nhà cung cấp × tác vụ)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Bắt buộc để chạy thật — xác nhận rằng bạn muốn gọi mạng thật và tiêu hạn mức miễn phí.",
    )
    parser.add_argument(
        "--do-ca-sau-ha-cap",
        action="store_true",
        help=(
            "Đo THÊM tỉ lệ thành công sau khi qua tầng hạ cấp (degrade.py) — "
            "tốn THÊM một loạt lượt gọi ngoài phép đo lần-đầu, mặc định tắt."
        ),
    )
    args = parser.parse_args()

    if not args.live:
        _thoat_an_toan(
            "Script này gọi THẬT nhà cung cấp LLM và tiêu hạn mức miễn phí "
            "dùng chung với người dùng thật trong ngày hôm nay. Thêm --live "
            "nếu bạn thực sự muốn chạy (nên thử --lan 2 trước khi chạy đủ "
            "--lan 50)."
        )

    try:
        asyncio.run(chay(get_settings(), args.lan, do_ca_sau_ha_cap=args.do_ca_sau_ha_cap))
    except SystemExit as loi:
        # chay() ném SystemExit(chuỗi) khi thiếu khoá provider — nếu để lọt
        # ra ngoài KHÔNG qua in_an_toan(), trình thông dịch Python tự in
        # thông điệp đó bằng bộ xử lý lỗi MẶC ĐỊNH của chính nó (không phải
        # in_an_toan), và trên console Windows cp1252 cách in đó thay ký tự
        # tiếng Việt bằng chuỗi \uXXXX không đọc được — đã quan sát được
        # trực tiếp khi chạy thử script này. In lại an toàn rồi thoát.
        if loi.code:
            _thoat_an_toan(str(loi.code))
        raise


def _thoat_an_toan(thong_diep: str) -> None:
    """In `thong_diep` một cách an toàn (`in_an_toan`) rồi thoát bằng
    `SystemExit` MÃ SỐ — không phải chuỗi. `raise SystemExit("chuỗi")` để lọt
    ra ngoài không bắt sẽ bị trình thông dịch Python tự in ra stderr bằng bộ
    xử lý lỗi mặc định của CHÍNH NÓ (không đi qua `in_an_toan`), và trên
    console Windows cp1252 cách in đó thay ký tự tiếng Việt bằng chuỗi
    \\uXXXX không đọc được — biến một cảnh báo cần RÕ RÀNG NGAY (ruling 5 của
    dispatch: không được để lộ gì, nhưng cũng không được để cảnh báo vô
    nghĩa) thành vô dụng."""
    in_an_toan(thong_diep)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
