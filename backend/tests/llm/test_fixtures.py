import pytest

from app.modules.llm.fixtures import FixtureMissing, FixtureProvider, fixture_key
from app.modules.llm.types import CallSpec, ProviderUnavailable, TaskType
from tests.llm.fakes import FakeProvider


def _spec(user: str = "xin chao") -> CallSpec:
    return CallSpec(
        task=TaskType.NORMALIZE_GOAL,
        system="he thong",
        user=user,
        json_schema={"type": "object"},
        max_output_tokens=128,
        timeout_seconds=10.0,
    )


def test_khoa_on_dinh_giua_cac_lan_goi():
    assert fixture_key("gemini", "m1", _spec()) == fixture_key("gemini", "m1", _spec())


def test_khoa_doi_khi_prompt_doi():
    assert fixture_key("gemini", "m1", _spec("a")) != fixture_key("gemini", "m1", _spec("b"))


def test_khoa_doi_khi_model_doi():
    assert fixture_key("gemini", "m1", _spec()) != fixture_key("gemini", "m2", _spec())


@pytest.mark.asyncio
async def test_che_do_off_goi_thang_provider_ben_trong(tmp_path):
    inner = FakeProvider(responses=["ket qua"])
    wrapped = FixtureProvider(inner, mode="off", directory=tmp_path)
    text, _ = await wrapped.complete(_spec())
    assert text == "ket qua"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_che_do_record_ghi_ra_dia(tmp_path):
    inner = FakeProvider(responses=["ket qua"])
    wrapped = FixtureProvider(inner, mode="record", directory=tmp_path)
    text, _ = await wrapped.complete(_spec())
    assert text == "ket qua"
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_che_do_replay_khong_goi_provider_ben_trong(tmp_path):
    ghi = FakeProvider(responses=["ket qua"])
    await FixtureProvider(ghi, mode="record", directory=tmp_path).complete(_spec())

    phat = FakeProvider(responses=["khong duoc dung toi"])
    wrapped = FixtureProvider(phat, mode="replay", directory=tmp_path)
    text, usage = await wrapped.complete(_spec())

    assert text == "ket qua"
    assert phat.calls == []
    assert usage.provider == "fake"


@pytest.mark.asyncio
async def test_replay_thieu_fixture_thi_bao_loi_ro_rang(tmp_path):
    wrapped = FixtureProvider(FakeProvider(), mode="replay", directory=tmp_path)
    with pytest.raises(FixtureMissing):
        await wrapped.complete(_spec())


@pytest.mark.asyncio
async def test_record_khong_ghi_gi_khi_provider_ben_trong_loi(tmp_path):
    inner = FakeProvider(errors=[ProviderUnavailable("mang loi")])
    wrapped = FixtureProvider(inner, mode="record", directory=tmp_path)

    with pytest.raises(ProviderUnavailable):
        await wrapped.complete(_spec())

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_phat_lai_giu_nguyen_usage_qua_vong_ghi_doc(tmp_path):
    inner = FakeProvider(name="gemini", model="m1")
    ghi = FixtureProvider(inner, mode="record", directory=tmp_path)
    _, usage_goc = await ghi.complete(_spec())

    phat = FixtureProvider(
        FakeProvider(name="gemini", model="m1"), mode="replay", directory=tmp_path
    )
    _, usage_phat_lai = await phat.complete(_spec())

    assert usage_phat_lai == usage_goc
    assert usage_phat_lai.provider == usage_goc.provider
    assert usage_phat_lai.model == usage_goc.model
    assert usage_phat_lai.input_tokens == usage_goc.input_tokens
    assert usage_phat_lai.output_tokens == usage_goc.output_tokens
