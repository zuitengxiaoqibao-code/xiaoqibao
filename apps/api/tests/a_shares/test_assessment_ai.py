import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from qibao_api.a_shares.assessment import StockAssessment
from qibao_api.a_shares.assessment_ai import (
    OpenAICompatibleAssessmentGateway,
    ReloadableAssessmentGateway,
)
from qibao_api.contracts.decision import EvidenceReference
from qibao_api.settings_repository import AISettings, AISettingsRepository


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
        generated_at=NOW,
    )


def assessment_with_contrary() -> StockAssessment:
    return assessment().model_copy(update={"contrary_evidence": (evidence("evidence-2"),)})


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
    created = 0

    def client_factory():
        nonlocal created
        created += 1
        return httpx.AsyncClient()

    result = await gateway(api_key=None, client_factory=client_factory).explain(
        assessment(), (evidence(),)
    )

    assert result.status == "unconfigured"
    assert result.explanation is None
    assert result.assessment == assessment()
    assert created == 0


@pytest.mark.asyncio
async def test_lazily_created_client_is_closed_by_gateway() -> None:
    created: list[httpx.AsyncClient] = []

    def client_factory() -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response_payload())
            )
        )
        created.append(client)
        return client

    ai = gateway(client_factory=client_factory)
    assert created == []

    result = await ai.explain(assessment(), (evidence(),))
    assert result.status == "ready"
    assert created[0].is_closed is False

    await ai.aclose()
    assert created[0].is_closed is True


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
        assert request.extensions["timeout"] == {
            "connect": 2.5, "read": 2.5, "write": 2.5, "pool": 2.5
        }
        return httpx.Response(200, json=response_payload())

    ai = gateway(handler, timeout=2.5)
    result = await ai.explain(assessment(), (evidence(),))
    await ai.aclose()

    assert result.status == "ready"
    assert result.explanation is not None
    assert result.explanation.evidence_ids == ("evidence-1",)
    assert result.assessment.action == "observe"
    assert result.assessment.confidence == Decimal("0.75")
    assert "simulation_eligible" not in result.assessment.model_dump(mode="json")


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


@pytest.mark.asyncio
async def test_ready_requires_every_assessment_evidence_reference() -> None:
    ai = gateway(lambda request: httpx.Response(200, json=response_payload()))
    original = assessment_with_contrary()

    result = await ai.explain(original, (*original.supporting_evidence, *original.contrary_evidence))
    await ai.aclose()

    assert result.status == "invalid"
    assert result.explanation is None


@pytest.mark.asyncio
@pytest.mark.parametrize("instruction", ["buy at 10.50", "仓位控制在20%", "跌破9元止损", "建议卖出"])
async def test_rejects_free_text_trading_instructions(instruction: str) -> None:
    ai = gateway(lambda request: httpx.Response(
        200, json=response_payload(plain_language=instruction)
    ))

    result = await ai.explain(assessment(), (evidence(),))
    await ai.aclose()

    assert result.status == "invalid"


@pytest.mark.asyncio
async def test_reloadable_gateway_reads_new_local_settings_without_restart(tmp_path) -> None:
    repository = AISettingsRepository(tmp_path)
    seen_models = []

    def client_factory():
        def handler(request: httpx.Request) -> httpx.Response:
            seen_models.append(json.loads(request.content)["model"])
            return httpx.Response(200, json=response_payload())

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    ai = ReloadableAssessmentGateway(repository, client_factory=client_factory)
    assert (await ai.explain(assessment(), (evidence(),))).status == "unconfigured"

    repository.save(AISettings(
        base_url="https://provider.example/v1", model="first", api_key=SECRET
    ))
    assert (await ai.explain(assessment(), (evidence(),))).status == "ready"
    repository.save(AISettings(
        base_url="https://provider.example/v1", model="second", api_key=SECRET
    ))
    assert (await ai.explain(assessment(), (evidence(),))).status == "ready"

    assert seen_models == ["first", "second"]


@pytest.mark.asyncio
async def test_reloadable_gateway_uses_environment_fallback_until_local_is_saved(tmp_path) -> None:
    repository = AISettingsRepository(tmp_path)
    fallback = AISettings(
        base_url="https://provider.example/v1", model="environment", api_key=SECRET
    )
    seen_models = []

    def client_factory():
        def handler(request: httpx.Request) -> httpx.Response:
            seen_models.append(json.loads(request.content)["model"])
            return httpx.Response(200, json=response_payload())

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    ai = ReloadableAssessmentGateway(
        repository, fallback=fallback, client_factory=client_factory
    )
    assert (await ai.explain(assessment(), (evidence(),))).status == "ready"
    repository.save(AISettings(
        base_url="https://provider.example/v1", model="local", api_key=SECRET
    ))
    assert (await ai.explain(assessment(), (evidence(),))).status == "ready"

    assert seen_models == ["environment", "local"]
