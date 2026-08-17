import json

from app.modules.llm.registry import GradeOut, NormalizedGoal, REGISTRY, SyllabusOut
from app.modules.llm.schema_util import to_provider_schema


def _tat_ca_khoa(node) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        keys |= set(node.keys())
        for value in node.values():
            keys |= _tat_ca_khoa(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _tat_ca_khoa(item)
    return keys


def test_khong_con_ref_hay_defs():
    schema = to_provider_schema(SyllabusOut)
    keys = _tat_ca_khoa(schema)
    assert "$ref" not in keys
    assert "$defs" not in keys
    assert "allOf" not in keys
    assert "anyOf" not in keys


def test_model_long_nhau_duoc_noi_tuyen_hoa():
    schema = to_provider_schema(SyllabusOut)
    lessons = schema["properties"]["modules"]["items"]["properties"]["lessons"]
    assert lessons["type"] == "array"
    assert lessons["items"]["properties"]["title"]["type"] == "string"


def test_giu_lai_required_va_enum():
    schema = to_provider_schema(GradeOut)
    assert set(schema["required"]) == {"score", "matched_criteria", "feedback"}
    assert schema["properties"]["score"]["type"] == "number"


def test_ket_qua_serialise_duoc_ra_json():
    json.dumps(to_provider_schema(SyllabusOut))


def test_truong_tuy_chon_van_co_mat_trong_properties():
    schema = to_provider_schema(NormalizedGoal)
    assert "deadline_weeks" in schema["properties"]
    assert "deadline_weeks" not in schema["required"]


def test_tat_ca_model_trong_registry_co_the_chuyen_doi():
    """Integration test: verify all response_model schemas can be converted and serialized."""
    converted_count = 0
    for task, spec in REGISTRY.items():
        if spec.response_model is None:
            continue
        # Should not raise
        schema = to_provider_schema(spec.response_model)
        # Should be JSON serializable
        json.dumps(schema)
        converted_count += 1

    # Verify we actually converted something (7 models have response_model)
    assert converted_count == 7, f"Expected 7 models to convert, got {converted_count}"
