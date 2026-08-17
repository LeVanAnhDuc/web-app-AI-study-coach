import pytest
from pydantic import BaseModel

from app.modules.llm.registry import (
    REGISTRY,
    GradeOut,
    LessonRef,
    NormalizedGoal,
    QuizQuestion,
)
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


def test_weekly_minutes_bi_gioi_han_15_2400():
    with pytest.raises(ValueError):
        NormalizedGoal(
            domain="math",
            topic="algebra",
            level_from="A1",
            level_to="A2",
            weekly_minutes=14,
            deadline_weeks=None,
        )
    with pytest.raises(ValueError):
        NormalizedGoal(
            domain="math",
            topic="algebra",
            level_from="A1",
            level_to="A2",
            weekly_minutes=2401,
            deadline_weeks=None,
        )
    goal = NormalizedGoal(
        domain="math",
        topic="algebra",
        level_from="A1",
        level_to="A2",
        weekly_minutes=30,
        deadline_weeks=None,
    )
    assert goal.weekly_minutes == 30


def test_deadline_weeks_bi_gioi_han_1_104():
    with pytest.raises(ValueError):
        NormalizedGoal(
            domain="math",
            topic="algebra",
            level_from="A1",
            level_to="A2",
            weekly_minutes=30,
            deadline_weeks=0,
        )
    with pytest.raises(ValueError):
        NormalizedGoal(
            domain="math",
            topic="algebra",
            level_from="A1",
            level_to="A2",
            weekly_minutes=30,
            deadline_weeks=105,
        )
    goal = NormalizedGoal(
        domain="math",
        topic="algebra",
        level_from="A1",
        level_to="A2",
        weekly_minutes=30,
        deadline_weeks=12,
    )
    assert goal.deadline_weeks == 12


def test_difficulty_bi_gioi_han_1_5():
    with pytest.raises(ValueError):
        QuizQuestion(
            type="mcq",
            stem="q",
            options=["a", "b"],
            answer="a",
            explanation="e",
            concept_tag="c",
            difficulty=0,
        )
    with pytest.raises(ValueError):
        QuizQuestion(
            type="mcq",
            stem="q",
            options=["a", "b"],
            answer="a",
            explanation="e",
            concept_tag="c",
            difficulty=6,
        )
    q = QuizQuestion(
        type="mcq",
        stem="q",
        options=["a", "b"],
        answer="a",
        explanation="e",
        concept_tag="c",
        difficulty=3,
    )
    assert q.difficulty == 3


def test_estimated_minutes_bi_gioi_han_5_180():
    with pytest.raises(ValueError):
        LessonRef(title="t", objectives=["o"], concept_tags=["c"], estimated_minutes=4)
    with pytest.raises(ValueError):
        LessonRef(title="t", objectives=["o"], concept_tags=["c"], estimated_minutes=181)
    lesson = LessonRef(title="t", objectives=["o"], concept_tags=["c"], estimated_minutes=45)
    assert lesson.estimated_minutes == 45


def test_khong_co_ten_hang_so_khong_interpolate_trong_prompt():
    # Kiểm tra rằng không có tên hằng số module bị mất prefix `f` trong prompt
    # (Nếu quên `f` prefix, tên hằng sẽ xuất hiện như {CONSTANT_NAME} trong prompt)
    import app.modules.llm.registry as registry_module

    # Lấy danh sách tên hằng số riêng (bắt đầu với underscore)
    private_constants = {
        name
        for name in dir(registry_module)
        if name.startswith("_")
        and not name.startswith("__")
        and isinstance(getattr(registry_module, name), str)
    }

    # Kiểm tra mỗi prompt không chứa tên hằng số (điều đó sẽ chỉ ra missing `f` prefix)
    for task, spec in REGISTRY.items():
        for const_name in private_constants:
            assert const_name not in spec.system_prompt, (
                f"Prompt của {task.value} chứa tên hằng số '{const_name}' (có thể lỗi prefix `f`)"
            )
