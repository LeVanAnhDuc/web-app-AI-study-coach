import pytest
from pydantic import BaseModel

from app.modules.llm.registry import REGISTRY, GradeOut
from app.modules.llm.types import TaskType


def test_moi_tac_vu_deu_co_dang_ky():
    assert set(REGISTRY.keys()) == set(TaskType)


def test_tac_vu_sinh_json_deu_khai_bao_model_dau_ra():
    can_json = {
        TaskType.NORMALIZE_GOAL,
        TaskType.GENERATE_PLACEMENT,
        TaskType.GENERATE_SYLLABUS,
        TaskType.GENERATE_LESSON,
        TaskType.GENERATE_QUIZ,
        TaskType.GRADE_FREE_TEXT,
        TaskType.GENERATE_REMEDIAL_LESSON,
    }
    for task in can_json:
        assert REGISTRY[task].response_model is not None, task


def test_tutor_chat_khong_ep_schema():
    assert REGISTRY[TaskType.TUTOR_CHAT].response_model is None


def test_moi_prompt_he_thong_deu_khong_rong():
    for task, spec in REGISTRY.items():
        assert spec.system_prompt.strip(), task


def test_diem_cham_tu_luan_bi_gioi_han_trong_khoang_0_1():
    with pytest.raises(ValueError):
        GradeOut(score=1.4, matched_criteria=["a"], feedback="x")
    with pytest.raises(ValueError):
        GradeOut(score=-0.1, matched_criteria=["a"], feedback="x")
    assert GradeOut(score=0.75, matched_criteria=["a"], feedback="x").score == 0.75


def test_model_dau_ra_deu_la_pydantic():
    for spec in REGISTRY.values():
        if spec.response_model is not None:
            assert issubclass(spec.response_model, BaseModel)
