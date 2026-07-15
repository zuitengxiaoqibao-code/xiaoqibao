import re
from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator


class DecisionAIProvider(Protocol):
    def complete(self, request: dict[str, object]) -> str: ...


class DecisionAIEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class DecisionAIRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: AwareDatetime
    evidence: tuple[DecisionAIEvidence, ...]
    deterministic_conclusions: tuple[str, ...]

    @model_validator(mode="after")
    def unique_evidence(self) -> "DecisionAIRequest":
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique")
        return self


class DecisionAIStatement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["fact", "interpretation"]
    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def facts_require_evidence(self) -> "DecisionAIStatement":
        if self.kind == "fact" and not self.evidence_ids:
            raise ValueError("fact statements require evidence")
        return self


class _ProviderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    statements: tuple[DecisionAIStatement, ...]


class DecisionAIResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "unavailable"]
    explanation: str | None
    statements: tuple[DecisionAIStatement, ...]
    provider: str
    model: str
    prompt_version: str
    generated_at: AwareDatetime
    evidence_ids: tuple[str, ...]
    invalid_output_count: int = Field(ge=0)
    provider_error_count: int = Field(ge=0)


_PLAN_LANGUAGE = re.compile(
    r"(?:buy|sell|entry|exit|stop[- ]?loss|take[- ]?profit|position|score|"
    r"买入|卖出|止损|止盈|仓位|评分|目标价|买入价|卖出价)", re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:\.\d+)?%?")


class DecisionAIGateway:
    def __init__(
        self, provider: DecisionAIProvider, *, provider_name: str, model: str,
        prompt_version: str, clock=lambda: datetime.now(timezone.utc), api_key: str | None = None,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.prompt_version = prompt_version
        self.clock = clock
        self._api_key = api_key

    def __repr__(self) -> str:
        return (
            f"DecisionAIGateway(provider_name={self.provider_name!r}, "
            f"model={self.model!r}, prompt_version={self.prompt_version!r})"
        )

    def explain(self, request: DecisionAIRequest) -> DecisionAIResult:
        evidence_ids = tuple(item.evidence_id for item in request.evidence)
        try:
            raw = self.provider.complete(self._request(request))
        except Exception:
            return self._unavailable(request, provider_errors=1)
        try:
            payload = _ProviderOutput.model_validate_json(raw)
            self._validate(payload, request)
        except (ValidationError, ValueError, TypeError):
            return self._unavailable(request, invalid=1)
        return DecisionAIResult(
            status="ready", explanation=payload.summary, statements=payload.statements,
            provider=self.provider_name, model=self.model, prompt_version=self.prompt_version,
            generated_at=self.clock(), evidence_ids=evidence_ids,
            invalid_output_count=0, provider_error_count=0,
        )

    def _request(self, request: DecisionAIRequest) -> dict[str, object]:
        return {
            "prompt_version": self.prompt_version,
            "evidence": [item.model_dump(mode="json") for item in request.evidence],
            "deterministic_conclusions": list(request.deterministic_conclusions),
            "allowed_evidence_ids": [item.evidence_id for item in request.evidence],
            "response_schema": _ProviderOutput.model_json_schema(),
            "instructions": (
                "Return JSON only. Explain frozen conclusions without adding or changing numbers, "
                "prices, scores, positions, or trade plans. Facts require evidence_ids."
            ),
        }

    @staticmethod
    def _validate(payload: _ProviderOutput, request: DecisionAIRequest) -> None:
        allowed = {item.evidence_id for item in request.evidence}
        referenced = {item for statement in payload.statements for item in statement.evidence_ids}
        if not referenced.issubset(allowed):
            raise ValueError("evidence outside frozen request")
        text = " ".join([payload.summary, *(item.text for item in payload.statements)])
        if _PLAN_LANGUAGE.search(text):
            raise ValueError("provider attempted to create a numeric decision")
        allowed_numbers = {
            match.group() for value in (
                *(item.summary for item in request.evidence), *request.deterministic_conclusions,
            ) for match in _NUMBER.finditer(value)
        }
        if any(match.group() not in allowed_numbers for match in _NUMBER.finditer(text)):
            raise ValueError("provider introduced an unsupported numeric fact")

    def _unavailable(
        self, request: DecisionAIRequest, *, invalid: int = 0, provider_errors: int = 0,
    ) -> DecisionAIResult:
        return DecisionAIResult(
            status="unavailable", explanation=None, statements=(), provider=self.provider_name,
            model=self.model, prompt_version=self.prompt_version, generated_at=self.clock(),
            evidence_ids=tuple(item.evidence_id for item in request.evidence),
            invalid_output_count=invalid, provider_error_count=provider_errors,
        )
