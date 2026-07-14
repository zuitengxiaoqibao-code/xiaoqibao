import hashlib
import json
import time
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from qibao_api.contracts.news import (
    AIInterpretation,
    InterpretationStatement,
    NormalizedNewsEvent,
)


class _ProviderPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statements: tuple[InterpretationStatement, ...] = Field(min_length=1)


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
        for _attempt in range(2):
            try:
                raw = await self.provider.complete(request)
                payload = _ProviderPayload.model_validate_json(raw)
                self._validate_citation_scope(payload, event)
                break
            except (ValidationError, ValueError, TypeError, RuntimeError, OSError):
                payload = None
        latency_ms = max(0, round((self.monotonic() - started) * 1000))
        if payload is None:
            return self._fallback(event, latency_ms)
        return self._build(
            event,
            payload.statements,
            provider=self.provider_name,
            model=self.model,
            latency_ms=latency_ms,
            degraded=False,
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

    def _fallback(
        self, event: NormalizedNewsEvent, latency_ms: int
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
    ) -> AIInterpretation:
        identity = json.dumps(
            {
                "event_id": event.event_id,
                "provider": provider,
                "model": model,
                "prompt_version": self.prompt_version,
                "statements": [item.model_dump(mode="json") for item in statements],
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
            statements=statements,
            citations=event.citations,
        )
