import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from qibao_api.a_shares.assessment import StockAssessment
from qibao_api.a_shares.assessment_ai import OpenAICompatibleAssessmentGateway
from qibao_api.contracts.decision import EvidenceReference


NOW = datetime(2026, 7, 15, 6, tzinfo=UTC)
SECRET = "sk-secret-must-never-leak"


def evidence(evidence_id: str = "evidence-1") -> EvidenceReference:
    return EvidenceReference(
        evidence_id=evidence_id,
        source="fixture",
        snapshot_id="snapshot-1",
        summary="frozen evidence",
        observed_at=NOW,
    )


def assessment() -> StockAssessment:
    item = evidence()
    return StockAssessment(
        assessment_id="assessment-1",
        symbol="600000",
        action="observe",
        conclusion="keep observing",
        confidence=Decimal("0.75"),
        supporting_evidence=(item,),
        contrary_evidence=(),
        risks=("risk",),
        invalidation_conditions=("condition",),
        simulation_eligible=True,
        authorized_simulation_advice_id="advice-1",
        authorized_simulation_plan_id="plan-1",
        generated_at=NOW,
    )


def response_payload(**updates):
    payload = {
        "plain_language": "The deterministic result remains unchanged.",
        "news_impact": "No verified incremental impact.",
        "hotspot_attribution": "No verified hotspot attribution.",
        "uncertainty": "Conditions can change after the cutoff.",
        "contrary_view": "Watch for contrary evidence.",
        "evidence_ids": ["evidence-1"],
    }
    payload.update(updates)
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def gateway(handler=None, **updates):
    client = None
    if handler is not None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    values = {
        "base_url": "https://provider.example/v1",
        "api_key": SECRET,
        "model": "provider-model",
        "client": client,
    }
    values.update(updates)
    return OpenAICompatibleAssessmentGateway(**values)


@pytest.mark.asyncio
async def test_unconfigured_ai_preserves_deterministic_assessment() -> None:
    result = await gateway(api_key=None).explain(assessment(), (evidence(),))

    assert result.status == "unconfigured"
    assert result.explanation is None
    assert result.assessment == assessment()


@pytest.mark.asyncio
async def test_sends_strict_json_request_and_accepts_frozen_evidence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://provider.example/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        body = json.loads(request.content)
        assert body["model"] == "provider-model"
        assert body["response_format"] == {"type": "json_object"}
        prompt = json.loads(body["messages"][1]["content"])
        assert prompt["assessment"]["action"] == "observe"
        assert prompt["allowed_evidence_ids"] == ["evidence-1"]
        assert prompt["evidence"][0]["summary"] == "frozen evidence"
        assert SECRET not in request.content.decode()
        return httpx.Response(200, json=response_payload())

    ai = gateway(handler)
    result = await ai.explain(assessment(), (evidence(),))
    await ai.aclose()

    assert result.status == "ready"
    assert result.explanation is not None
    assert result.explanation.evidence_ids == ("evidence-1",)
    assert result.assessment.action == "observe"
    assert result.assessment.confidence == Decimal("0.75")
    assert result.assessment.simulation_eligible is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "status"),
    [
        (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=request)), "timeout"),
        (lambda request: httpx.Response(503, text="provider failed"), "http_error"),
        (lambda request: httpx.Response(200, json={"not": "chat completions"}), "invalid"),
        (lambda request: httpx.Response(200, json=response_payload(extra="forbidden")), "invalid"),
        (
            lambda request: httpx.Response(
                200, json=response_payload(evidence_ids=["invented"])
            ),
            "invalid",
        ),
    ],
)
async def test_provider_failures_degrade_without_mutating_assessment(handler, status) -> None:
    ai = gateway(handler)
    original = assessment()
    result = await ai.explain(original, (evidence(),))
    await ai.aclose()

    assert result.status == status
    assert result.explanation is None
    assert result.assessment == original
    assert SECRET not in result.model_dump_json()
    assert SECRET not in repr(ai)
