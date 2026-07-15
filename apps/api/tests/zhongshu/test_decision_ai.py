import json
from datetime import datetime, timedelta, timezone

import pytest

from qibao_api.zhongshu.decision_ai import (
    DecisionAIEvidence, DecisionAIGateway, DecisionAIRequest,
)


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 7, 15, 9, 20, tzinfo=TZ)


class Provider:
    def __init__(self, response: str | Exception) -> None:
        self.response = response
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def request() -> DecisionAIRequest:
    return DecisionAIRequest(
        generated_at=NOW,
        evidence=(DecisionAIEvidence(evidence_id="ev-1", summary="公司公告事项已核验"),),
        deterministic_conclusions=("仅观察，不生成交易计划",),
    )


def numeric_request() -> DecisionAIRequest:
    return DecisionAIRequest(
        generated_at=NOW,
        evidence=(DecisionAIEvidence(evidence_id="ev-1", summary="已核验数值为 10"),),
        deterministic_conclusions=("仅观察",),
    )


def gateway(response: str | Exception, *, api_key: str | None = None):
    provider = Provider(response)
    return DecisionAIGateway(
        provider, provider_name="test-provider", model="model-v1",
        prompt_version="decision-prompt-v1", clock=lambda: NOW, api_key=api_key,
    ), provider


def valid_payload() -> str:
    return json.dumps({
        "summary": "已有核验信息支持继续观察。",
        "statements": [{
            "kind": "fact", "text": "公司公告事项已核验", "evidence_ids": ["ev-1"],
        }],
    }, ensure_ascii=False)


def test_valid_explanation_preserves_metadata_without_credentials() -> None:
    subject, provider = gateway(valid_payload(), api_key="top-secret")
    result = subject.explain(request())

    assert result.status == "ready"
    assert result.provider == "test-provider"
    assert result.model == "model-v1"
    assert result.prompt_version == "decision-prompt-v1"
    assert result.generated_at == NOW
    assert result.evidence_ids == ("ev-1",)
    assert result.invalid_output_count == result.provider_error_count == 0
    assert "top-secret" not in repr(subject)
    assert "top-secret" not in json.dumps(provider.requests, ensure_ascii=False)


@pytest.mark.parametrize("payload", [
    {"summary": "说明", "statements": [{"kind": "fact", "text": "事实", "evidence_ids": []}]},
    {"summary": "说明", "statements": [{"kind": "fact", "text": "事实", "evidence_ids": ["other"]}]},
    {"summary": "建议买入价 10.50 元", "statements": []},
    {"summary": "市场上涨 12.3%", "statements": []},
])
def test_rejects_unsupported_or_numeric_plan_output(payload: dict) -> None:
    subject, _ = gateway(json.dumps(payload, ensure_ascii=False))
    result = subject.explain(request())
    assert result.status == "unavailable"
    assert result.explanation is None
    assert result.statements == ()
    assert result.invalid_output_count == 1
    assert result.provider_error_count == 0


def test_invalid_json_and_provider_error_have_distinct_counters() -> None:
    invalid, _ = gateway("not-json")
    failed, _ = gateway(OSError("offline"))
    assert invalid.explain(request()).invalid_output_count == 1
    result = failed.explain(request())
    assert result.provider_error_count == 1
    assert result.invalid_output_count == 0


def test_rejects_number_even_when_same_token_exists_in_evidence() -> None:
    subject, _ = gateway(json.dumps({
        "summary": "已核验数值为 10",
        "statements": [{"kind": "fact", "text": "数值 10", "evidence_ids": ["ev-1"]}],
    }, ensure_ascii=False))
    assert subject.explain(numeric_request()).status == "unavailable"


@pytest.mark.parametrize("text", ["增长10%", "上涨12.3%", "回撤-3.5%"])
def test_rejects_ascii_numbers_adjacent_to_chinese_text(text: str) -> None:
    subject, _ = gateway(json.dumps({"summary": text, "statements": []}, ensure_ascii=False))
    assert subject.explain(request()).status == "unavailable"


@pytest.mark.parametrize("text", [
    "Set the price", "Define a target", "Increase the weight", "Change the allocation",
    "给出价格", "设定目标", "调整权重", "分配资金", "市场点位",
])
def test_rejects_plan_and_market_semantics_in_both_languages(text: str) -> None:
    subject, _ = gateway(json.dumps({"summary": text, "statements": []}, ensure_ascii=False))
    assert subject.explain(request()).status == "unavailable"
