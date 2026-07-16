import hashlib
import json
import time
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from decimal import Decimal
from typing import Literal

from qibao_api.contracts.news import (
    AIInterpretation,
    InterpretationStatement,
    NormalizedNewsEvent,
)


class _ProviderPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statements: tuple[InterpretationStatement, ...] = Field(min_length=1)
    impact_direction: Literal["positive", "negative", "neutral", "uncertain"] = "uncertain"
    confidence: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    contrary_citation_ids: tuple[str, ...] = ()


class UnavailableNewsAIProvider:
    async def complete(self, _request: dict) -> str:
        raise OSError("news AI provider is not configured")


class NewsAIGateway:
    def __init__(
        self,
        provider,
        *,
        provider_name: str,
        model: str,
        prompt_version: str,
        clock=lambda: datetime.now(timezone.utc),
        monotonic=time.monotonic,
        api_key: str | None = None,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.prompt_version = prompt_version
        self.clock = clock
        self.monotonic = monotonic
        self._api_key = api_key

    def __repr__(self) -> str:
        return (
            f"NewsAIGateway(provider_name={self.provider_name!r}, "
            f"model={self.model!r}, prompt_version={self.prompt_version!r})"
        )

    async def interpret(self, event: NormalizedNewsEvent) -> AIInterpretation:
        started = self.monotonic()
        payload = None
        request = self._request(event)
        provider_attempts = 0
        invalid_output_count = 0
        provider_error_count = 0
        for _attempt in range(2):
            provider_attempts += 1
            try:
                raw = await self.provider.complete(request)
            except Exception:
                provider_error_count += 1
                continue
            try:
                payload = _ProviderPayload.model_validate_json(raw)
                self._validate_citation_scope(payload, event)
                break
            except (ValidationError, ValueError, TypeError):
                invalid_output_count += 1
                payload = None
        latency_ms = max(0, round((self.monotonic() - started) * 1000))
        if payload is None:
            return self._fallback(
                event, latency_ms, provider_attempts,
                invalid_output_count, provider_error_count,
            )
        return self._build(
            event,
            payload.statements,
            provider=self.provider_name,
            model=self.model,
            latency_ms=latency_ms,
            degraded=False,
            impact_direction=payload.impact_direction,
            confidence=payload.confidence,
            contrary_citation_ids=payload.contrary_citation_ids,
            provider_attempts=provider_attempts,
            invalid_output_count=invalid_output_count,
            provider_error_count=provider_error_count,
        )

    def _request(self, event: NormalizedNewsEvent) -> dict:
        return {
            "prompt_version": self.prompt_version,
            "event": event.model_dump(mode="json"),
            "allowed_citation_ids": [
                citation.citation_id for citation in event.citations
            ],
            "response_schema": _ProviderPayload.model_json_schema(),
            "instructions": (
                "Return JSON only. Facts require citation_ids. "
                "Uncited analysis must use kind=interpretation."
            ),
        }

    @staticmethod
    def _validate_citation_scope(
        payload: _ProviderPayload, event: NormalizedNewsEvent
    ) -> None:
        allowed = {citation.citation_id for citation in event.citations}
        referenced = {
            citation_id
            for statement in payload.statements
            for citation_id in statement.citation_ids
        }
        if not referenced.issubset(allowed):
            raise ValueError("provider referenced citations outside the frozen event")
        if not set(payload.contrary_citation_ids).issubset(allowed):
            raise ValueError("provider referenced contrary evidence outside the frozen event")

    def _fallback(
        self, event: NormalizedNewsEvent, latency_ms: int,
        provider_attempts: int, invalid_output_count: int, provider_error_count: int,
    ) -> AIInterpretation:
        primary_citation = event.citations[0]
        statements = (
            InterpretationStatement(
                statement_id="deterministic-fact-1",
                kind="fact",
                text=event.headline,
                citation_ids=(primary_citation.citation_id,),
            ),
            InterpretationStatement(
                statement_id="deterministic-note-1",
                kind="interpretation",
                text="模型暂不可用，仅保留已核验新闻事实，不生成交易结论。",
            ),
        )
        return self._build(
            event,
            statements,
            provider="deterministic",
            model="evidence-summary-v1",
            latency_ms=latency_ms,
            degraded=True,
            impact_direction="uncertain",
            confidence=Decimal("0"),
            contrary_citation_ids=(),
            provider_attempts=provider_attempts,
            invalid_output_count=invalid_output_count,
            provider_error_count=provider_error_count,
        )

    def _build(
        self,
        event: NormalizedNewsEvent,
        statements: tuple[InterpretationStatement, ...],
        *,
        provider: str,
        model: str,
        latency_ms: int,
        degraded: bool,
        impact_direction: str,
        confidence: Decimal,
        contrary_citation_ids: tuple[str, ...],
        provider_attempts: int,
        invalid_output_count: int,
        provider_error_count: int,
    ) -> AIInterpretation:
        identity = json.dumps(
            {
                "event_id": event.event_id,
                "provider": provider,
                "model": model,
                "prompt_version": self.prompt_version,
                "statements": [item.model_dump(mode="json") for item in statements],
                "impact_direction": impact_direction,
                "confidence": str(confidence),
                "contrary_citation_ids": contrary_citation_ids,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        interpretation_id = f"interpretation-{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
        return AIInterpretation(
            interpretation_id=interpretation_id,
            event_id=event.event_id,
            generated_at=self.clock(),
            provider=provider,
            model=model,
            prompt_version=self.prompt_version,
            latency_ms=latency_ms,
            degraded=degraded,
            impact_direction=impact_direction,
            confidence=confidence,
            contrary_citation_ids=contrary_citation_ids,
            provider_attempts=provider_attempts,
            invalid_output_count=invalid_output_count,
            provider_error_count=provider_error_count,
            statements=statements,
            citations=event.citations,
        )
