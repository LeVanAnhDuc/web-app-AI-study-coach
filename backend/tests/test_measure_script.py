"""Test cho script đo tuân thủ JSON schema — CHỈ kiểm phần thuần tuý.

KHÔNG có test nào ở đây gọi mạng: đo lần-đầu và đo-sau-hạ-cấp được kiểm bằng
`FakeProvider` (tests/llm/fakes.py), và một test riêng dựng lại toàn bộ luồng
`chay()` qua `FixtureProvider` chế độ replay (tests/fixtures giả lập trong
tmp_path) để chứng minh script thật sự chạy được từ đầu tới cuối mà không
đụng mạng, đúng mục đích fixture record/replay được xây trong milestone này.
Phần gọi mạng thật (`--live`) chỉ chạy tay, không có trong bất kỳ test nào.
"""

import io
import json
import sys

import pytest

from app.config import get_settings
from app.modules.llm.fixtures import FixtureMissing, FixtureProvider, fixture_key
from app.modules.llm.registry import REGISTRY
from app.modules.llm.routing import PROVIDER_RPM
from app.modules.llm.schema_util import to_provider_schema
from app.modules.llm.service import build_providers
from app.modules.llm.types import (
    CallSpec,
    ProviderUnavailable,
    RateLimited,
    TaskType,
    Usage,
)
from scripts.measure_json_compliance import (
    SAMPLES,
    Ket_qua,
    ProviderGiuNhip,
    _giay_moi_luot_goi,
    chay,
    do_mot_cap_sau_ha_cap,
    do_mot_cap_tho,
    in_an_toan,
    main,
    render_report,
)
from tests.llm.fakes import FakeProvider

_GOAL_JSON = (
    '{"domain":"lap trinh web","topic":"React","level_from":"JS co ban",'
    '"level_to":"tu dung app","weekly_minutes":300,"deadline_weeks":8}'
)

# --- Dữ liệu mẫu JSON hợp lệ cho MỌI tác vụ ép schema, dùng để dựng fixture
# giả lập trong test đầu-cuối bên dưới. Không tái sử dụng ở script thật —
# script thật không tự bịa dữ liệu, nó đo dữ liệu provider trả về. ---
_QUIZ_QUESTION = (
    '{"type":"mcq","stem":"cau hoi","options":["a","b","c","d"],"answer":"a",'
    '"explanation":"giai thich","concept_tag":"react-usestate","difficulty":2}'
)
_JSON_HOP_LE_THEO_TAC_VU: dict[TaskType, str] = {
    TaskType.NORMALIZE_GOAL: _GOAL_JSON,
    TaskType.GENERATE_PLACEMENT: f'{{"questions":[{_QUIZ_QUESTION}]}}',
    TaskType.GENERATE_SYLLABUS: (
        '{"modules":[{"title":"module 1","summary":"tong quan",'
        '"lessons":[{"title":"bai 1","objectives":["hieu state"],'
        '"concept_tags":["react-usestate"],"estimated_minutes":30}]}]}'
    ),
    TaskType.GENERATE_LESSON: '{"body_md":"noi dung","sections":["Mo dau"]}',
    TaskType.GENERATE_QUIZ: f'{{"questions":[{_QUIZ_QUESTION}]}}',
    TaskType.GRADE_FREE_TEXT: ('{"score":0.8,"matched_criteria":["tieu chi 1"],"feedback":"tot"}'),
    TaskType.GENERATE_REMEDIAL_LESSON: '{"body_md":"noi dung on tap","sections":["Mo dau"]}',
}


def _spec_cho(task: TaskType) -> CallSpec:
    spec_dang_ky = REGISTRY[task]
    model_cls = spec_dang_ky.response_model
    assert model_cls is not None
    return CallSpec(
        task=task,
        system=spec_dang_ky.system_prompt,
        user=SAMPLES[task],
        json_schema=to_provider_schema(model_cls),
        max_output_tokens=spec_dang_ky.max_output_tokens,
        timeout_seconds=spec_dang_ky.timeout_seconds,
    )


# --- SAMPLES: mỗi tác vụ ép schema phải có prompt mẫu; TUTOR_CHAT thì không ---


def test_moi_tac_vu_ep_schema_deu_co_prompt_mau():
    can_do = [t for t, spec in REGISTRY.items() if spec.response_model is not None]
    for task in can_do:
        assert task in SAMPLES, task
        assert len(SAMPLES[task]) > 20, task


def test_tutor_chat_khong_can_prompt_mau():
    assert TaskType.TUTOR_CHAT not in SAMPLES


# --- Ket_qua: ba loại kết quả tách biệt (Ruling 2) ---


def test_mau_so_tuong_minh_khop_sai_loi_cong_lai_bang_so_mau():
    r = Ket_qua(
        provider="gemini",
        model="m",
        task="t",
        so_mau=10,
        khop_schema=7,
        sai_schema=2,
        loi_ha_tang=1,
        tong_giay=5.0,
    )
    assert r.khop_schema + r.sai_schema + r.loi_ha_tang == r.so_mau
    assert r.da_do == 9


def test_loi_ha_tang_khac_voi_sai_schema_trong_ti_le_dieu_kien():
    """Đây là phép thử trực tiếp cho Ruling 2: một nhà cung cấp BẬN (bị
    RateLimited) nhưng chưa từng trả sai schema khi nó THỰC SỰ trả lời phải
    có tỉ lệ khớp có điều kiện là 100% — không phải một con số thấp hơn vì bị
    tính chung với "trả lời sai". Nếu ai đó lỡ tính `khop/so_mau` làm tỉ lệ
    chính, test này sẽ đỏ vì cả hai dòng dưới sẽ ra cùng 80%, xoá mất đúng
    khác biệt mà Ruling 2 yêu cầu phải giữ.
    """
    ban_nhung_luon_dung = Ket_qua(
        provider="gemini",
        model="m",
        task="t",
        so_mau=10,
        khop_schema=8,
        sai_schema=0,
        loi_ha_tang=2,
        tong_giay=1.0,
    )
    thuc_su_hay_sai = Ket_qua(
        provider="groq",
        model="m",
        task="t",
        so_mau=10,
        khop_schema=8,
        sai_schema=2,
        loi_ha_tang=0,
        tong_giay=1.0,
    )
    assert ban_nhung_luon_dung.ti_le_khop == 100.0
    assert thuc_su_hay_sai.ti_le_khop == 80.0
    # Trên tổng mẫu (không phân biệt loại thất bại), cả hai trông giống hệt
    # nhau — đúng phép tính SAI mà Ruling 2 cảnh báo, giữ lại đây chỉ để đối
    # chiếu, KHÔNG dùng làm tỉ lệ khuyến nghị chính (xem render_report).
    assert ban_nhung_luon_dung.ti_le_khop_tong_mau == 80.0
    assert thuc_su_hay_sai.ti_le_khop_tong_mau == 80.0


def test_khong_chia_cho_khong_khi_chua_do_duoc_gi():
    r = Ket_qua(
        provider="groq",
        model="m",
        task="t",
        so_mau=0,
        khop_schema=0,
        sai_schema=0,
        loi_ha_tang=0,
        tong_giay=0.0,
    )
    assert r.ti_le_khop == 0.0
    assert r.ti_le_khop_tong_mau == 0.0
    assert r.giay_tb == 0.0


def test_do_sau_ha_cap_la_truong_rieng_khong_lam_hong_do_lan_dau():
    r = Ket_qua(
        provider="gemini",
        model="m",
        task="t",
        so_mau=10,
        khop_schema=6,
        sai_schema=4,
        loi_ha_tang=0,
        tong_giay=1.0,
    )
    assert r.khop_sau_ha_cap is None
    assert r.ti_le_khop_sau_ha_cap is None
    r2 = Ket_qua(
        provider="gemini",
        model="m",
        task="t",
        so_mau=10,
        khop_schema=6,
        sai_schema=4,
        loi_ha_tang=0,
        tong_giay=1.0,
        khop_sau_ha_cap=9,
        sai_sau_ha_cap=1,
        loi_sau_ha_cap=0,
    )
    assert r2.ti_le_khop == 60.0  # lần-đầu không đổi
    assert r2.ti_le_khop_sau_ha_cap == 90.0  # con số RIÊNG


# --- render_report: cột bắt buộc, không chia cho không, khuyến nghị đúng ---


def test_bao_cao_co_du_cot_can_thiet():
    rows = [
        Ket_qua(
            provider="gemini",
            model="gemini-2.5-flash",
            task="generate_quiz",
            so_mau=10,
            khop_schema=8,
            sai_schema=2,
            loi_ha_tang=0,
            tong_giay=30.0,
        )
    ]
    bao_cao = render_report(rows)
    assert "gemini" in bao_cao
    assert "generate_quiz" in bao_cao
    assert "80" in bao_cao
    assert "Khuyến nghị" in bao_cao
    assert "Mẫu" in bao_cao
    assert "Đo được" in bao_cao


def test_bao_cao_khong_chia_cho_khong():
    rows = [
        Ket_qua(
            provider="groq",
            model="m",
            task="generate_quiz",
            so_mau=0,
            khop_schema=0,
            sai_schema=0,
            loi_ha_tang=0,
            tong_giay=0.0,
        )
    ]
    render_report(rows)


def test_khuyen_nghi_chon_provider_khop_schema_cao_nhat():
    rows = [
        Ket_qua("gemini", "m", "generate_quiz", 10, 10, 0, 0, 20.0),
        Ket_qua("groq", "m", "generate_quiz", 10, 8, 2, 0, 8.0),
    ]
    bao_cao = render_report(rows)
    dong_khuyen_nghi = [d for d in bao_cao.splitlines() if "generate_quiz" in d and "→" in d][-1]
    assert dong_khuyen_nghi.index("gemini") < dong_khuyen_nghi.index("groq")


def test_khuyen_nghi_hien_thi_co_so_mau_de_khong_nham_mau_nho_voi_mau_lon():
    """Ruling 3: một ô có 2 mẫu không được trông giống một ô có 50 mẫu."""
    rows = [
        Ket_qua("gemini", "m", "generate_quiz", 50, 46, 4, 0, 1.0),
        Ket_qua("groq", "m", "generate_quiz", 2, 2, 0, 0, 1.0),
    ]
    bao_cao = render_report(rows)
    dong = [d for d in bao_cao.splitlines() if "generate_quiz" in d and "→" in d][-1]
    assert "n=50" in dong
    assert "n=2" in dong


def test_bao_cao_neu_model_da_do_va_ngay_do():
    rows = [
        Ket_qua("gemini", "gemini-2.5-flash", "generate_quiz", 10, 10, 0, 0, 20.0),
    ]
    bao_cao = render_report(rows)
    assert "gemini-2.5-flash" in bao_cao


def test_bao_cao_gan_ket_qua_sau_ha_cap_thanh_bang_rieng_biet():
    rows = [
        Ket_qua(
            "gemini",
            "m",
            "generate_quiz",
            10,
            6,
            4,
            0,
            20.0,
            khop_sau_ha_cap=9,
            sai_sau_ha_cap=1,
            loi_sau_ha_cap=0,
        ),
    ]
    bao_cao = render_report(rows)
    # 60% là tỉ lệ lần-đầu, 90% là tỉ lệ sau hạ cấp — cả hai phải xuất hiện,
    # KHÔNG được trộn làm một con số (Ruling 1).
    assert "60" in bao_cao
    assert "90" in bao_cao
    assert "sau" in bao_cao.lower() and "hạ cấp" in bao_cao.lower()


# --- do_mot_cap_tho: đo lần-đầu, KHÔNG qua degrade.py ---


@pytest.mark.asyncio
async def test_do_lan_dau_khong_thu_lai_khong_them_chi_dan_json():
    """FakeProvider không khai STRUCTURED_OUTPUT (giống Groq/Mistral thật).
    Nếu đo qua complete_structured, tầng hạ cấp sẽ tự thêm chỉ dẫn JSON vào
    system prompt TRƯỚC lần gọi đầu tiên. Đo trực tiếp (Ruling 1) không được
    làm vậy — system prompt provider nhận phải giống HỆT REGISTRY.
    """
    provider = FakeProvider(name="groq", responses=[_GOAL_JSON, _GOAL_JSON])
    ket_qua = await do_mot_cap_tho(provider, TaskType.NORMALIZE_GOAL, so_lan=2)
    assert len(provider.calls) == 2
    assert provider.calls[0].system == REGISTRY[TaskType.NORMALIZE_GOAL].system_prompt
    assert ket_qua.khop_schema == 2
    assert ket_qua.sai_schema == 0
    assert ket_qua.loi_ha_tang == 0
    assert ket_qua.so_mau == 2


@pytest.mark.asyncio
async def test_do_lan_dau_phan_biet_sai_schema_va_loi_ha_tang():
    provider = FakeProvider(
        name="groq",
        errors=[None, None, RateLimited("gioi han tam thoi")],
        responses=["day khong phai json khop schema", _GOAL_JSON],
    )
    ket_qua = await do_mot_cap_tho(provider, TaskType.NORMALIZE_GOAL, so_lan=3)
    assert len(provider.calls) == 3
    assert ket_qua.sai_schema == 1
    assert ket_qua.khop_schema == 1
    assert ket_qua.loi_ha_tang == 1
    assert ket_qua.so_mau == 3


@pytest.mark.asyncio
async def test_do_lan_dau_hoat_dong_qua_fixture_replay_khong_dung_mang(tmp_path):
    """Chứng minh do_mot_cap_tho ghép đúng với build_providers + FixtureProvider
    chế độ replay: không có khoá thật, không có mạng, chỉ có một fixture đã
    ghi sẵn trên đĩa."""
    task = TaskType.NORMALIZE_GOAL
    call = _spec_cho(task)
    khoa = fixture_key("gemini", "gemini-fake-model", call)
    (tmp_path / f"{khoa}.json").write_text(
        json.dumps(
            {
                "task": task.value,
                "text": _GOAL_JSON,
                "usage": {
                    "provider": "gemini",
                    "model": "gemini-fake-model",
                    "input_tokens": 5,
                    "output_tokens": 5,
                },
            }
        ),
        encoding="utf-8",
    )

    settings = get_settings().model_copy(
        update={
            "gemini_api_key": "khoa-gia",
            "groq_api_key": None,
            "mistral_api_key": None,
            "gemini_model": "gemini-fake-model",
            "llm_fixture_mode": "replay",
            "llm_fixture_dir": str(tmp_path),
        }
    )
    providers = build_providers(settings)
    try:
        ket_qua = await do_mot_cap_tho(providers["gemini"], task, so_lan=1)
    finally:
        await providers["gemini"].aclose()

    assert ket_qua.khop_schema == 1
    assert ket_qua.so_mau == 1


@pytest.mark.asyncio
async def test_do_lan_dau_khong_nuot_fixture_thieu_ma_de_no_lot_len(tmp_path):
    """FixtureMissing (app.modules.llm.fixtures) là một LLMError, nhưng KHÔNG
    được đếm vào loi_ha_tang: ở chế độ replay, fixture thiếu LUÔN LUÔN là
    lỗi thao tác (bộ fixture không đầy đủ), không phải một provider bận —
    đếm nó vào loi_ha_tang sẽ khiến một bộ fixture HỎNG trông giống hệt một
    provider bị giới hạn tần suất trong báo cáo cuối cùng. do_mot_cap_tho
    phải để nó lọt lên nguyên vẹn, không bị bắt/nuốt ở đây.
    """
    provider_thieu_fixture = FixtureProvider(
        FakeProvider(name="gemini", model="m"), mode="replay", directory=tmp_path
    )
    with pytest.raises(FixtureMissing):
        await do_mot_cap_tho(provider_thieu_fixture, TaskType.NORMALIZE_GOAL, so_lan=2)


@pytest.mark.asyncio
async def test_do_sau_ha_cap_khong_nuot_fixture_thieu_ma_de_no_lot_len(tmp_path):
    provider_thieu_fixture = FixtureProvider(
        FakeProvider(name="gemini", model="m"), mode="replay", directory=tmp_path
    )
    with pytest.raises(FixtureMissing):
        await do_mot_cap_sau_ha_cap(provider_thieu_fixture, TaskType.NORMALIZE_GOAL, so_lan=1)


# --- do_mot_cap_sau_ha_cap: con số RIÊNG, đi qua toàn bộ tầng hạ cấp ---


@pytest.mark.asyncio
async def test_do_sau_ha_cap_tinh_ca_luot_thu_lai():
    # Sai lần đầu, đúng lần hai — complete_structured tự thử lại, một "mẫu"
    # ở đây vẫn tính là MỘT lần thành công dù tốn hai lượt gọi provider.
    provider = FakeProvider(
        name="groq",
        responses=['{"domain": "x"}', _GOAL_JSON],
    )
    ket_qua = await do_mot_cap_sau_ha_cap(provider, TaskType.NORMALIZE_GOAL, so_lan=1)
    assert (ket_qua.khop, ket_qua.sai, ket_qua.loi) == (1, 0, 0)
    assert ket_qua.tong_giay >= 0.0
    assert len(provider.calls) == 2
    # Hai lượt gọi provider (FakeProvider trả 10/20 mỗi lượt) đều tính vào chi
    # phí — kể cả lượt đầu đã hỏng schema, vì nó đã tiêu token thật.
    assert ket_qua.token_vao == 20
    assert ket_qua.token_ra == 40


@pytest.mark.asyncio
async def test_do_sau_ha_cap_dem_loi_ha_tang_rieng_voi_sai_schema():
    provider = FakeProvider(name="groq", errors=[RateLimited("bi chan")])
    ket_qua = await do_mot_cap_sau_ha_cap(provider, TaskType.NORMALIZE_GOAL, so_lan=1)
    assert (ket_qua.khop, ket_qua.sai, ket_qua.loi) == (0, 0, 1)


# --- in_an_toan: không bao giờ crash vì console không hỗ trợ tiếng Việt ---


class _ConsoleGioiHanCp1252:
    """Giả lập console Windows cp1252: write() ném lỗi với ký tự có dấu."""

    def __init__(self) -> None:
        self.buffer = io.BytesIO()
        self.da_ghi_binh_thuong: list[str] = []

    def write(self, text: str) -> None:
        text.encode("cp1252")
        self.da_ghi_binh_thuong.append(text)


def test_in_an_toan_khong_nem_loi_khi_console_khong_ho_tro_tieng_viet():
    console = _ConsoleGioiHanCp1252()
    in_an_toan("chuỗi có dấu tiếng Việt", stream=console)
    assert console.buffer.getvalue() == "chuỗi có dấu tiếng Việt\n".encode()


def test_in_an_toan_di_duong_binh_thuong_khi_khong_loi():
    console = _ConsoleGioiHanCp1252()
    in_an_toan("khong dau", stream=console)
    assert console.da_ghi_binh_thuong == ["khong dau\n"]
    assert console.buffer.getvalue() == b""


# --- main(): không có --live thì không được làm gì hết, phải cảnh báo hạn mức ---


def test_main_khong_co_live_thi_thoat_va_canh_bao_han_muc(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["measure_json_compliance.py"])
    with pytest.raises(SystemExit) as loi:
        main()
    # Thoát bằng MÃ SỐ, không phải chuỗi — chuỗi cảnh báo phải đi qua
    # in_an_toan() (kiểm ở capsys), không phải nằm trong SystemExit để trình
    # thông dịch tự in (xem docstring _thoat_an_toan: cách in mặc định của
    # Python làm hỏng tiếng Việt trên console cp1252, đã quan sát trực tiếp).
    assert loi.value.code == 1
    assert "hạn mức" in capsys.readouterr().out


def test_main_voi_live_nhung_khong_co_khoa_thi_thoat_an_toan(monkeypatch, capsys):
    """Nhánh SystemExit thứ hai của main() — ném từ chay() vì thiếu khoá —
    cũng phải đi qua in_an_toan() và thoát bằng mã số, KHÔNG đụng mạng."""
    monkeypatch.setattr(sys, "argv", ["measure_json_compliance.py", "--live"])
    settings_khong_khoa = get_settings().model_copy(
        update={
            "gemini_api_key": None,
            "groq_api_key": None,
            "mistral_api_key": None,
            "llm_fixture_mode": "off",
        }
    )
    monkeypatch.setattr("scripts.measure_json_compliance.get_settings", lambda: settings_khong_khoa)
    with pytest.raises(SystemExit) as loi:
        main()
    assert loi.value.code == 1
    assert "khoá" in capsys.readouterr().out


# --- chay(): thiếu khoá thì báo lỗi rõ ràng, KHÔNG gọi mạng ---


@pytest.mark.asyncio
async def test_chay_bao_loi_ro_rang_khi_khong_co_khoa_nao():
    settings = get_settings().model_copy(
        update={
            "gemini_api_key": None,
            "groq_api_key": None,
            "mistral_api_key": None,
            "llm_fixture_mode": "off",
        }
    )
    with pytest.raises(SystemExit):
        await chay(settings, so_lan=1)


@pytest.mark.asyncio
async def test_chay_toan_bo_qua_fixture_replay_ghi_bao_cao_ra_file(tmp_path):
    """Đầu-cuối: build_providers + FixtureProvider replay cho MỌI tác vụ ép
    schema của một nhà cung cấp, không đụng mạng, rồi kiểm báo cáo được ghi
    ra đĩa đúng định dạng. Đây là bằng chứng script chạy được từ đầu tới
    cuối mà không cần khoá thật hay lượt gọi thật nào."""
    thu_muc_fixture = tmp_path / "fixtures"
    thu_muc_fixture.mkdir()
    thu_muc_bao_cao = tmp_path / "bao_cao"

    can_do = [t for t, spec in REGISTRY.items() if spec.response_model is not None]
    for task in can_do:
        call = _spec_cho(task)
        khoa = fixture_key("gemini", "gemini-fake-model", call)
        (thu_muc_fixture / f"{khoa}.json").write_text(
            json.dumps(
                {
                    "task": task.value,
                    "text": _JSON_HOP_LE_THEO_TAC_VU[task],
                    "usage": {
                        "provider": "gemini",
                        "model": "gemini-fake-model",
                        "input_tokens": 5,
                        "output_tokens": 5,
                    },
                }
            ),
            encoding="utf-8",
        )

    settings = get_settings().model_copy(
        update={
            "gemini_api_key": "khoa-gia",
            "groq_api_key": None,
            "mistral_api_key": None,
            "gemini_model": "gemini-fake-model",
            "llm_fixture_mode": "replay",
            "llm_fixture_dir": str(thu_muc_fixture),
        }
    )

    duong_dan = await chay(settings, so_lan=1, thu_muc_bao_cao=thu_muc_bao_cao)

    assert duong_dan.exists()
    noi_dung = duong_dan.read_text(encoding="utf-8")
    for task in can_do:
        assert task.value in noi_dung
    assert "Khuyến nghị" in noi_dung
    assert "gemini-fake-model" in noi_dung


@pytest.mark.asyncio
async def test_chay_that_bai_ro_rang_khi_thieu_fixture_o_che_do_replay(tmp_path, capsys):
    """Ruling 4 + review: một bộ fixture THIẾU ở chế độ replay phải làm
    chay() dừng ngay, nêu rõ provider/tác vụ, KHÔNG ghi báo cáo — trước bản
    sửa này, do_mot_cap_tho đếm FixtureMissing vào loi_ha_tang, khiến một bộ
    fixture HỎNG và một provider THẬT SỰ bị giới hạn tần suất tạo ra kết quả
    byte-giống-hệt nhau (loi_ha_tang=so_mau, cùng dòng "chưa đo được")."""
    settings = get_settings().model_copy(
        update={
            "gemini_api_key": "khoa-gia",
            "groq_api_key": None,
            "mistral_api_key": None,
            "gemini_model": "gemini-fake-model",
            "llm_fixture_mode": "replay",
            "llm_fixture_dir": str(tmp_path / "fixtures_rong"),
        }
    )
    thu_muc_bao_cao = tmp_path / "bao_cao"

    with pytest.raises(SystemExit) as loi:
        await chay(settings, so_lan=1, thu_muc_bao_cao=thu_muc_bao_cao)

    assert loi.value.code == 1
    assert not thu_muc_bao_cao.exists()
    noi_dung_in_ra = capsys.readouterr().out
    assert "fixture" in noi_dung_in_ra.lower()
    assert "gemini" in noi_dung_in_ra
    assert "normalize_goal" in noi_dung_in_ra


@pytest.mark.asyncio
async def test_chay_voi_nhieu_provider_gan_dung_hang_cho_tung_nha_cung_cap(tmp_path):
    """Bẫy đã tái diễn trong milestone này: record_usage() (Task 15) từng âm
    thầm gộp usage của nhiều provider làm một mà MỌI test một-provider vẫn
    xanh. chay() là nơi DUY NHẤT gán mỗi Ket_qua cho đúng provider/model của
    nó — dựng HAI provider, MỖI provider một model riêng và một bộ fixture
    riêng, rồi kiểm mỗi (provider × tác vụ) có ĐÚNG MỘT dòng, mang ĐÚNG model
    của chính provider đó, không lẫn tên model của provider kia.
    """
    thu_muc_fixture = tmp_path / "fixtures"
    thu_muc_fixture.mkdir()

    can_do = [t for t, spec in REGISTRY.items() if spec.response_model is not None]
    model_theo_provider = {"gemini": "gemini-fake-multi", "groq": "groq-fake-multi"}

    for ten_provider, model in model_theo_provider.items():
        for task in can_do:
            call = _spec_cho(task)
            khoa = fixture_key(ten_provider, model, call)
            (thu_muc_fixture / f"{khoa}.json").write_text(
                json.dumps(
                    {
                        "task": task.value,
                        "text": _JSON_HOP_LE_THEO_TAC_VU[task],
                        "usage": {
                            "provider": ten_provider,
                            "model": model,
                            "input_tokens": 5,
                            "output_tokens": 5,
                        },
                    }
                ),
                encoding="utf-8",
            )

    settings = get_settings().model_copy(
        update={
            "gemini_api_key": "khoa-gia-gemini",
            "groq_api_key": "khoa-gia-groq",
            "mistral_api_key": None,
            "gemini_model": model_theo_provider["gemini"],
            "groq_model": model_theo_provider["groq"],
            "llm_fixture_mode": "replay",
            "llm_fixture_dir": str(thu_muc_fixture),
        }
    )

    duong_dan = await chay(settings, so_lan=1, thu_muc_bao_cao=tmp_path / "bao_cao")
    noi_dung = duong_dan.read_text(encoding="utf-8")

    for ten_provider, model in model_theo_provider.items():
        model_cua_provider_kia = model_theo_provider[
            "groq" if ten_provider == "gemini" else "gemini"
        ]
        for task in can_do:
            dong_khop = [
                d
                for d in noi_dung.splitlines()
                if d.startswith(f"| {ten_provider} |") and f"| {task.value} |" in d
            ]
            assert len(dong_khop) == 1, (ten_provider, task, noi_dung)
            assert model in dong_khop[0]
            assert model_cua_provider_kia not in dong_khop[0]


# --- Giữ nhịp: bảo toàn mọi mẫu, không chặn mẫu nào ---


def test_nhip_suy_ra_dung_tu_provider_rpm():
    """`PROVIDER_RPM["gemini"] = 10` nghĩa là 6 giây một lượt. Ghim phép suy ra
    này để không ai đổi nó thành một hằng số cứng rồi trôi lệch khỏi bảng."""
    assert _giay_moi_luot_goi("gemini") == 60.0 / PROVIDER_RPM["gemini"]
    assert _giay_moi_luot_goi("groq") == 60.0 / PROVIDER_RPM["groq"]
    # Provider chưa khai trong bảng: đoán THẬN TRỌNG (rpm nhỏ nhất), không phải
    # đoán 0 rồi gọi không giới hạn.
    assert _giay_moi_luot_goi("provider-chua-khai") == 60.0 / min(PROVIDER_RPM.values())


@pytest.mark.asyncio
async def test_giu_nhip_nghi_giua_hai_luot_va_khong_lam_mat_mau(monkeypatch):
    """Hành vi PHẢI có: nghỉ giữa hai lượt gọi tới cùng nhà cung cấp. Hành vi
    PHẢI KHÔNG có: bỏ mất lượt nào. Đây là khác biệt cốt lõi giữa GIỮ NHỊP và
    CHẶN — thùng token sẽ TỪ CHỐI lượt thứ hai và biến nó thành "không đo
    được", tức mất đúng cái mẫu ta đang trả tiền để lấy.

    ĐÃ QUAN SÁT TRƯỚC KHI SỬA: `provider calls made: 35, bucket consultations:
    0` — không có bất kỳ khoảng nghỉ nào; `ProviderGiuNhip` chưa tồn tại nên
    test này còn không import được.
    """
    da_ngu: list[float] = []

    async def ngu_gia(giay: float) -> None:
        da_ngu.append(giay)

    monkeypatch.setattr("scripts.measure_json_compliance.asyncio.sleep", ngu_gia)

    goc = FakeProvider(name="groq", responses=[_GOAL_JSON] * 3)
    provider = ProviderGiuNhip(goc, giay_moi_luot=6.0)
    ket_qua = await do_mot_cap_tho(provider, TaskType.NORMALIZE_GOAL, so_lan=3)

    # MỌI mẫu vẫn được đo — giữ nhịp không loại bỏ mẫu nào.
    assert ket_qua.so_mau == 3
    assert ket_qua.khop_schema == 3
    assert len(goc.calls) == 3
    # Lượt đầu không nghỉ (chưa có lượt trước), hai lượt sau đều nghỉ.
    assert len(da_ngu) == 2
    assert all(0 < g <= 6.0 for g in da_ngu), da_ngu


@pytest.mark.asyncio
async def test_giu_nhip_chuyen_tiep_nguyen_ven_thuoc_tinh_dinh_danh():
    """`degrade.py` đọc `capabilities` để quyết định có tiêm chỉ dẫn JSON hay
    không, và hai vòng lặp đo đọc `name`/`model` để gán vào dòng báo cáo — bỏ
    sót một thuộc tính ở lớp bọc sẽ âm thầm đổi CÁI ĐANG ĐƯỢC ĐO."""
    goc = FakeProvider(name="mistral", model="mistral-x", capabilities=frozenset())
    provider = ProviderGiuNhip(goc, giay_moi_luot=0.0)
    assert provider.name == "mistral"
    assert provider.model == "mistral-x"
    assert provider.capabilities == goc.capabilities
    await provider.aclose()
    assert goc.closed is True


@pytest.mark.asyncio
async def test_che_do_replay_khong_giu_nhip(tmp_path, monkeypatch):
    """Chạy thử bằng fixture không tiêu hạn mức nào, nên nghỉ 6 giây giữa các
    lần ĐỌC FILE chỉ làm lượt chạy thử dài vô ích. `chay()` phải tắt giữ nhịp ở
    chế độ replay — ghim bằng cách khẳng định `asyncio.sleep` không hề được
    gọi (chính test đầu-cuối bên trên cũng sẽ đứng 35 phút nếu điều này sai)."""
    da_ngu: list[float] = []

    async def ngu_gia(giay: float) -> None:
        da_ngu.append(giay)

    monkeypatch.setattr("scripts.measure_json_compliance.asyncio.sleep", ngu_gia)

    thu_muc_fixture = tmp_path / "fixtures"
    thu_muc_fixture.mkdir()
    can_do = [t for t, spec in REGISTRY.items() if spec.response_model is not None]
    for task in can_do:
        khoa = fixture_key("gemini", "gemini-fake-model", _spec_cho(task))
        (thu_muc_fixture / f"{khoa}.json").write_text(
            json.dumps(
                {
                    "task": task.value,
                    "text": _JSON_HOP_LE_THEO_TAC_VU[task],
                    "usage": {
                        "provider": "gemini",
                        "model": "gemini-fake-model",
                        "input_tokens": 7,
                        "output_tokens": 3,
                    },
                }
            ),
            encoding="utf-8",
        )

    settings = get_settings().model_copy(
        update={
            "gemini_api_key": "khoa-gia",
            "groq_api_key": None,
            "mistral_api_key": None,
            "gemini_model": "gemini-fake-model",
            "llm_fixture_mode": "replay",
            "llm_fixture_dir": str(thu_muc_fixture),
        }
    )
    duong_dan = await chay(settings, so_lan=2, thu_muc_bao_cao=tmp_path / "bao_cao")

    assert da_ngu == []
    # Và chi phí vẫn được đếm đúng: 7 tác vụ × 2 mẫu × (7 vào, 3 ra).
    noi_dung = duong_dan.read_text(encoding="utf-8")
    assert "Chi phí lượt chạy" in noi_dung
    # Bảng chi phí có 7 cột; bảng %Khớp phía trên có 10 và cũng bắt đầu bằng
    # "| gemini |", nên lọc theo số cột để lấy đúng dòng của bảng chi phí.
    dong_gemini = [
        [x.strip() for x in d.strip("|").split("|")]
        for d in noi_dung.splitlines()
        if d.startswith("| gemini |") and len(d.strip("|").split("|")) == 7
    ]
    assert len(dong_gemini) == 1, noi_dung
    o = dong_gemini[0]
    assert o[1] == str(len(can_do) * 2)  # lượt gọi lần-đầu
    assert o[2] == str(len(can_do) * 2 * 7)  # token vào
    assert o[3] == str(len(can_do) * 2 * 3)  # token ra
    assert o[6] == str(len(can_do) * 2 * 10)  # tổng token


# --- Báo cáo chi phí: lượt hỏng ĐÃ tính tiền cũng phải được đếm ---


@pytest.mark.asyncio
async def test_do_lan_dau_cong_don_token_ke_ca_luot_hong_da_tinh_tien():
    """Một lượt `ProviderUnavailable` sau HTTP 200 (hết ngân sách output) đã bị
    tính tiền trọn vẹn và mang theo `usages` — nó phải vào mục chi phí, nếu
    không báo cáo sẽ thấp hơn thực tế đúng ở những lượt tốn nhất.

    ĐÃ QUAN SÁT TRƯỚC KHI SỬA: `Ket_qua` không có trường token nào, nên
    `ket_qua.token_ra` ném `AttributeError`.
    """
    usage_da_tinh_tien = Usage(provider="groq", model="fake-1", input_tokens=700, output_tokens=512)
    provider = FakeProvider(
        name="groq",
        errors=[ProviderUnavailable("het ngan sach", usages=[usage_da_tinh_tien]), None],
        responses=[_GOAL_JSON],
    )
    ket_qua = await do_mot_cap_tho(provider, TaskType.NORMALIZE_GOAL, so_lan=2)

    assert ket_qua.loi_ha_tang == 1
    assert ket_qua.khop_schema == 1
    # 700 + 10 (FakeProvider trả 10/20 ở lượt thành công), 512 + 20.
    assert ket_qua.token_vao == 710
    assert ket_qua.token_ra == 532


def test_bao_cao_neu_ro_chi_phi_luot_chay():
    rows = [
        Ket_qua("gemini", "m", "generate_quiz", 10, 8, 2, 0, 1.0, token_vao=100, token_ra=200),
        Ket_qua("groq", "m", "generate_quiz", 10, 8, 2, 0, 1.0, token_vao=1, token_ra=2),
    ]
    bao_cao = render_report(rows)
    assert "Chi phí lượt chạy" in bao_cao
    assert "300" in bao_cao  # tổng của gemini
    assert "303" in bao_cao  # tổng chung
