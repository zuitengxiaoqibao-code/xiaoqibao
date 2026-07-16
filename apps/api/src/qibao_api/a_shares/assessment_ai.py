import json
import re
from collections.abc import Callable
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

from qibao_api.a_shares.assessment import StockAssessment
from qibao_api.contracts.decision import EvidenceReference
from qibao_api.settings_repository import AISettings, AISettingsRepository


AIStatus = Literal["ready", "unconfigured", "timeout", "http_error", "invalid"]


class AssessmentAIExplanation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plain_language: str
    news_impact: str
    hotspot_attribution: str
    uncertainty: str
    contrary_view: str
    evidence_ids: tuple[str, ...]


class AssessmentAIResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: AIStatus
    assessment: StockAssessment
    explanation: AssessmentAIExplanation | None


class OpenAICompatibleAssessmentGateway:
    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        client: httpx.AsyncClient | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        timeout: float = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        self._client = client
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=self.timeout)
        )
        self._owns_client = client is None

    def __repr__(self) -> str:
        return (
            "OpenAICompatibleAssessmentGateway("
            f"base_url={self.base_url!r}, model={self.model!r})"
        )

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def explain(
        self,
        assessment: StockAssessment,
        evidence: tuple[EvidenceReference, ...],
    ) -> AssessmentAIResult:
        if not self.base_url or not self._api_key or not self.model:
            return self._result("unconfigured", assessment)
        allowed = {item.evidence_id for item in evidence}
        try:
            response = await self._client_or_create().post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=self._request(assessment, evidence),
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            return self._result("timeout", assessment)
        except httpx.HTTPError:
            return self._result("http_error", assessment)
        try:
            envelope = response.json()
            content = envelope["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("chat completion content must be a JSON string")
            explanation = AssessmentAIExplanation.model_validate_json(content)
            required = {
                item.evidence_id for item in (
                    *assessment.supporting_evidence, *assessment.contrary_evidence
                )
            }
            if set(explanation.evidence_ids) != required or not required.issubset(allowed):
                raise ValueError("AI evidence must exactly cover the assessment evidence")
            text = " ".join((
                explanation.plain_language, explanation.news_impact,
                explanation.hotspot_attribution, explanation.uncertainty,
                explanation.contrary_view,
            ))
            if re.search(
                r"(?:\b(?:buy|sell|position|stop[ -]?loss)\b|买入|卖出|仓位|止损|止盈|\d+(?:\.\d+)?\s*(?:元|%))",
                text, re.IGNORECASE,
            ):
                raise ValueError("AI explanation contains a trading instruction")
        except (ValueError, TypeError, KeyError, IndexError):
            return self._result("invalid", assessment)
        return AssessmentAIResult(
            status="ready", assessment=assessment, explanation=explanation
        )

    def _request(
        self,
        assessment: StockAssessment,
        evidence: tuple[EvidenceReference, ...],
    ) -> dict:
        prompt = {
            "assessment": {
                "assessment_id": assessment.assessment_id,
                "symbol": assessment.symbol,
                "action": assessment.action,
                "conclusion": assessment.conclusion,
                "risks": assessment.risks,
                "invalidation_conditions": assessment.invalidation_conditions,
                "generated_at": assessment.generated_at.isoformat(),
            },
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "allowed_evidence_ids": [item.evidence_id for item in evidence],
        }
        return {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return one strict JSON object matching the supplied schema. "
                        "Explain only; never change the deterministic action, confidence, "
                        "or supporting evidence. Cite only allowed evidence IDs."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        }

    @staticmethod
    def _result(status: AIStatus, assessment: StockAssessment) -> AssessmentAIResult:
        return AssessmentAIResult(
            status=status, assessment=assessment, explanation=None
        )


class ReloadableAssessmentGateway:
    def __init__(
        self,
        repository: AISettingsRepository,
        *,
        fallback: AISettings | None = None,
        client: httpx.AsyncClient | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        timeout: float = 10,
    ) -> None:
        self._repository = repository
        self._fallback = fallback
        self._client = client
        self._client_factory = client_factory
        self._timeout = timeout

    def __repr__(self) -> str:
        return "ReloadableAssessmentGateway()"

    async def explain(
        self,
        assessment: StockAssessment,
        evidence: tuple[EvidenceReference, ...],
    ) -> AssessmentAIResult:
        current = self._repository.load()
        if not isinstance(current, AISettings):
            current = self._fallback if current.reason == "missing" else None
        if current is None:
            return OpenAICompatibleAssessmentGateway._result("unconfigured", assessment)
        gateway = OpenAICompatibleAssessmentGateway(
            base_url=current.base_url,
            api_key=current.api_key,
            model=current.model,
            client=self._client,
            client_factory=self._client_factory,
            timeout=self._timeout,
        )
        try:
            return await gateway.explain(assessment, evidence)
        finally:
            await gateway.aclose()
