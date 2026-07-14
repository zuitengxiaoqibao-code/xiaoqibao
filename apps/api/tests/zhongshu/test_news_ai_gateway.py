import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from qibao_api.contracts.news import EvidenceCitation, NormalizedNewsEvent
from qibao_api.zhongshu.news_ai import NewsAIGateway


NOW = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)
SECRET = "sk-secret-must-never-leak"


def event() -> NormalizedNewsEvent:
    return NormalizedNewsEvent(
        event_id="event-1", event_type="market_news", headline="政策支持先进制造",
        occurred_at=NOW, normalized_at=NOW,
        affected_instruments=(), industries=("高端制造",), themes=("政策支持",),
        citations=(EvidenceCitation(
            citation_id="citation-1", article_id="news-1",
            canonical_url="https://news.example/1", publisher="测试来源",
            published_at=NOW, quoted_text="政策支持先进制造", content_hash="a" * 64,
        ),),
        association_confidence=Decimal("0.60"), review_state="pending",
    )


class Provider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def complete(self, _request: dict) -> str:
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_gateway_accepts_schema_valid_evidence_bound_json() -> None:
    provider = Provider([json.dumps({"statements": [
        {"statement_id": "s1", "kind": "fact", "text": "政策已经发布。",
         "citation_ids": ["citation-1"]},
        {"statement_id": "s2", "kind": "interpretation",
         "text": "可能改善行业预期，但不是买入信号。", "citation_ids": []},
    ]}, ensure_ascii=False)])
    gateway = NewsAIGateway(
        provider, provider_name="cloud", model="model-1", prompt_version="news-v1",
        clock=lambda: NOW, monotonic=iter([1.0, 1.125]).__next__,
    )

    result = await gateway.interpret(event())

    assert result.provider == "cloud"
    assert result.model == "model-1"
    assert result.latency_ms == 125
    assert result.degraded is False
    assert result.statements[0].citation_ids == ("citation-1",)
    assert result.provider_attempts == 1
    assert result.invalid_output_count == 0


@pytest.mark.asyncio
async def test_gateway_retries_invalid_json_once_then_accepts_valid_output() -> None:
    provider = Provider(["not-json", json.dumps({"statements": [{
        "statement_id": "s1", "kind": "fact", "text": "政策已经发布。",
        "citation_ids": ["citation-1"],
    }]}, ensure_ascii=False)])
    gateway = NewsAIGateway(provider, provider_name="local", model="model-2",
                            prompt_version="news-v1", clock=lambda: NOW)

    result = await gateway.interpret(event())

    assert provider.calls == 2
    assert result.degraded is False
    assert result.provider_attempts == 2
    assert result.invalid_output_count == 1


@pytest.mark.asyncio
async def test_gateway_degrades_deterministically_without_leaking_provider_errors() -> None:
    provider = Provider([RuntimeError(f"authorization failed: {SECRET}"), "still invalid"])
    gateway = NewsAIGateway(
        provider, provider_name="cloud", model="model-1", prompt_version="news-v1",
        clock=lambda: NOW, api_key=SECRET,
    )

    result = await gateway.interpret(event())
    serialized = result.model_dump_json()

    assert provider.calls == 2
    assert result.provider == "deterministic"
    assert result.model == "evidence-summary-v1"
    assert result.degraded is True
    assert result.statements[0].citation_ids == ("citation-1",)
    assert SECRET not in serialized
    assert SECRET not in repr(gateway)
    assert result.provider_attempts == 2
    assert result.provider_error_count == 1
    assert result.invalid_output_count == 1
