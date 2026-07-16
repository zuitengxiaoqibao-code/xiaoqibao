import json
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict

from qibao_api.a_shares.assessment import StockAssessment
from qibao_api.contracts.decision import EvidenceReference


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
        timeout: float = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.model = model
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    def __repr__(self) -> str:
        return (
            "OpenAICompatibleAssessmentGateway("
            f"base_url={self.base_url!r}, model={self.model!r})"
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def explain(
        self,
        assessment: StockAssessment,
        evidence: tuple[EvidenceReference, ...],
    ) -> AssessmentAIResult:
        if not self.base_url or not self._api_key or not self.model:
            return self._result("unconfigured", assessment)
        allowed = {item.evidence_id for item in evidence}
        try:
            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=self._request(assessment, evidence),
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
            if not set(explanation.evidence_ids).issubset(allowed):
                raise ValueError("AI evidence is outside the frozen input")
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
                        "or simulation eligibility. Cite only allowed evidence IDs."
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
