import dataclasses

import pytest

from app.modules.llm.types import (
    AllProvidersFailed,
    CallSpec,
    Capability,
    LLMError,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    SchemaViolation,
    TaskType,
    Usage,
)


def test_capability_co_ba_thanh_vien_dung():
    expected = {
        "STRUCTURED_OUTPUT",
        "STREAMING",
        "PROMPT_CACHE",
    }
    assert {c.name for c in Capability} == expected


def test_capability_gia_tri_chuoi_dung():
    assert Capability.STRUCTURED_OUTPUT.value == "structured_output"
    assert Capability.STREAMING.value == "streaming"
    assert Capability.PROMPT_CACHE.value == "prompt_cache"


def test_rate_limited_la_loi_llm():
    assert issubclass(RateLimited, LLMError)


def test_quota_exhausted_la_loi_llm():
    assert issubclass(QuotaExhausted, LLMError)


def test_provider_unavailable_la_loi_llm():
    assert issubclass(ProviderUnavailable, LLMError)


def test_schema_violation_la_loi_llm():
    assert issubclass(SchemaViolation, LLMError)


def test_llm_error_la_exception():
    assert issubclass(LLMError, Exception)


def test_rate_limited_luu_tru_retry_after():
    ex = RateLimited("test message", retry_after=5.0)
    assert ex.retry_after == 5.0
    assert str(ex) == "test message"


def test_rate_limited_retry_after_mac_dinh_none():
    ex = RateLimited("test message")
    assert ex.retry_after is None


def test_rate_limited_retry_after_co_the_la_none():
    ex = RateLimited("test", retry_after=None)
    assert ex.retry_after is None


def test_llm_error_mac_dinh_usages_rong():
    # usages khai báo Ở GỐC CÂY (LLMError), không phải gắn động trên từng
    # lớp con — nên MỌI lớp con, kể cả lớp chưa từng liên quan tới một lần
    # gọi provider (vd RateLimiterUnavailable), đều có sẵn thuộc tính này.
    assert LLMError("loi chung").usages == []
    assert QuotaExhausted("het quota").usages == []
    assert ProviderUnavailable("mat mang").usages == []
    assert SchemaViolation("sai schema").usages == []
    assert AllProvidersFailed("het nha cung cap").usages == []


def test_llm_error_luu_duoc_usages_qua_moi_lop_con():
    usage = Usage(provider="a", model="m", input_tokens=1, output_tokens=2)
    assert RateLimited("x", usages=[usage]).usages == [usage]
    assert QuotaExhausted("x", usages=[usage]).usages == [usage]
    assert ProviderUnavailable("x", usages=[usage]).usages == [usage]
    assert SchemaViolation("x", usages=[usage]).usages == [usage]
    assert AllProvidersFailed("x", usages=[usage]).usages == [usage]


def test_call_spec_bi_dong():
    spec = CallSpec(
        task=TaskType.NORMALIZE_GOAL,
        system="test",
        user="test",
        json_schema=None,
        max_output_tokens=100,
        timeout_seconds=30.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.system = "new"


def test_usage_bi_dong():
    usage = Usage(provider="openai", model="gpt-4", input_tokens=100, output_tokens=50)
    with pytest.raises(dataclasses.FrozenInstanceError):
        usage.input_tokens = 200
