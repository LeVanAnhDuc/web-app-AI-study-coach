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
from app.modules.llm.fixtures import FixtureProvider, fixture_key
from app.modules.llm.registry import REGISTRY
from app.modules.llm.schema_util import to_provider_schema
from app.modules.llm.service import build_providers
from app.modules.llm.types import CallSpec, RateLimited, TaskType
from scripts.measure_json_compliance import (
    SAMPLES,
    Ket_qua,
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
async def test_do_lan_dau_dem_fixture_thieu_la_loi_ha_tang_khong_lam_no_vong_lap(tmp_path):
    """FixtureMissing (app.modules.llm.fixtures) là một LLMError, KHÔNG phải
    RateLimited/QuotaExhausted/ProviderUnavailable — trước khi bắt LLMError
    rộng, một cặp (provider × tác vụ) thiếu fixture sẽ ném lỗi lọt thẳng ra
    ngoài, làm nổ toàn bộ vòng lặp đo các cặp còn lại trong chay(). Đây là
    hành vi mong muốn: một lượt đo bị mất, không phải một crash toàn cục.
    """
    provider_thieu_fixture = FixtureProvider(
        FakeProvider(name="gemini", model="m"), mode="replay", directory=tmp_path
    )
    ket_qua = await do_mot_cap_tho(provider_thieu_fixture, TaskType.NORMALIZE_GOAL, so_lan=2)
    assert ket_qua.loi_ha_tang == 2
    assert ket_qua.khop_schema == 0
    assert ket_qua.sai_schema == 0
    assert ket_qua.so_mau == 2


# --- do_mot_cap_sau_ha_cap: con số RIÊNG, đi qua toàn bộ tầng hạ cấp ---


@pytest.mark.asyncio
async def test_do_sau_ha_cap_tinh_ca_luot_thu_lai():
    # Sai lần đầu, đúng lần hai — complete_structured tự thử lại, một "mẫu"
    # ở đây vẫn tính là MỘT lần thành công dù tốn hai lượt gọi provider.
    provider = FakeProvider(
        name="groq",
        responses=['{"domain": "x"}', _GOAL_JSON],
    )
    khop, sai, loi, giay = await do_mot_cap_sau_ha_cap(provider, TaskType.NORMALIZE_GOAL, so_lan=1)
    assert (khop, sai, loi) == (1, 0, 0)
    assert giay >= 0.0
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_do_sau_ha_cap_dem_loi_ha_tang_rieng_voi_sai_schema():
    provider = FakeProvider(name="groq", errors=[RateLimited("bi chan")])
    khop, sai, loi, _ = await do_mot_cap_sau_ha_cap(provider, TaskType.NORMALIZE_GOAL, so_lan=1)
    assert (khop, sai, loi) == (0, 0, 1)


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
