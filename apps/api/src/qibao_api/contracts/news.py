from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from qibao_api.contracts.instruments import (
    validate_a_share_code,
    validate_convertible_bond_code,
)
from qibao_api.contracts.market import AssetKind


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
WebUrl = Annotated[str, StringConstraints(pattern=r"^https?://[^\s]+$")]


class NewsArticle(BaseModel):
    model_config = ConfigDict(frozen=True)

    article_id: NonBlank
    canonical_url: WebUrl
    publisher: NonBlank
    title: NonBlank
    summary: str | None = None
    published_at: AwareDatetime
    fetched_at: AwareDatetime
    content_hash: Sha256
    raw_snapshot: bytes = Field(min_length=1)
    source_verified: bool = False

    @model_validator(mode="after")
    def require_fetch_after_publication(self) -> "NewsArticle":
        if self.fetched_at < self.published_at:
            raise ValueError("fetched_at cannot precede published_at")
        return self


class EvidenceCitation(BaseModel):
    model_config = ConfigDict(frozen=True)

    citation_id: NonBlank
    article_id: NonBlank
    canonical_url: WebUrl
    publisher: NonBlank
    published_at: AwareDatetime
    quoted_text: NonBlank
    content_hash: Sha256


class NormalizedNewsEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: NonBlank
    event_type: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    headline: NonBlank
    occurred_at: AwareDatetime
    normalized_at: AwareDatetime
    affected_instruments: tuple[tuple[AssetKind, str], ...] = ()
    industries: tuple[NonBlank, ...] = ()
    themes: tuple[NonBlank, ...] = ()
    citations: tuple[EvidenceCitation, ...] = Field(min_length=1)
    association_confidence: Decimal = Field(ge=0, le=1)
    review_state: Literal["pending", "verified", "rejected"]

    @field_validator("affected_instruments")
    @classmethod
    def validate_instruments(
        cls, values: tuple[tuple[AssetKind, str], ...]
    ) -> tuple[tuple[AssetKind, str], ...]:
        for asset, symbol in values:
            if asset is AssetKind.A_SHARE:
                validate_a_share_code(symbol)
            else:
                validate_convertible_bond_code(symbol)
        if len(set(values)) != len(values):
            raise ValueError("affected instruments must be unique")
        return values

    @model_validator(mode="after")
    def validate_event_timeline(self) -> "NormalizedNewsEvent":
        if self.normalized_at < self.occurred_at:
            raise ValueError("normalized_at cannot precede occurred_at")
        if any(citation.published_at > self.normalized_at for citation in self.citations):
            raise ValueError("event cannot cite news published after normalization")
        return self


class InterpretationStatement(BaseModel):
    model_config = ConfigDict(frozen=True)

    statement_id: NonBlank
    kind: Literal["fact", "interpretation"]
    text: NonBlank
    citation_ids: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def require_fact_citations(self) -> "InterpretationStatement":
        if self.kind == "fact" and not self.citation_ids:
            raise ValueError("fact statements require at least one citation")
        if len(set(self.citation_ids)) != len(self.citation_ids):
            raise ValueError("statement citations must be unique")
        return self


class AIInterpretation(BaseModel):
    model_config = ConfigDict(frozen=True)

    interpretation_id: NonBlank
    event_id: NonBlank
    generated_at: AwareDatetime
    provider: NonBlank
    model: NonBlank
    prompt_version: NonBlank
    latency_ms: int = Field(default=0, ge=0)
    degraded: bool = False
    impact_direction: Literal["positive", "negative", "neutral", "uncertain"] = "uncertain"
    confidence: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    contrary_citation_ids: tuple[NonBlank, ...] = ()
    provider_attempts: int = Field(default=0, ge=0)
    invalid_output_count: int = Field(default=0, ge=0)
    provider_error_count: int = Field(default=0, ge=0)
    statements: tuple[InterpretationStatement, ...] = Field(min_length=1)
    citations: tuple[EvidenceCitation, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_graph(self) -> "AIInterpretation":
        citation_ids = [citation.citation_id for citation in self.citations]
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("interpretation citations must be unique")
        statement_ids = [statement.statement_id for statement in self.statements]
        if len(set(statement_ids)) != len(statement_ids):
            raise ValueError("statement ids must be unique")
        known_citations = set(citation_ids)
        referenced = {
            citation_id
            for statement in self.statements
            for citation_id in statement.citation_ids
        }
        if not referenced.issubset(known_citations):
            raise ValueError("statements reference unknown citations")
        if any(citation.published_at > self.generated_at for citation in self.citations):
            raise ValueError("interpretation cannot cite future news")
        if not set(self.contrary_citation_ids).issubset(known_citations):
            raise ValueError("contrary evidence references unknown citations")
        if len(set(self.contrary_citation_ids)) != len(self.contrary_citation_ids):
            raise ValueError("contrary evidence citations must be unique")
        if self.invalid_output_count + self.provider_error_count > self.provider_attempts:
            raise ValueError("provider failure counts cannot exceed attempts")
        return self


class NewsCorrection(BaseModel):
    model_config = ConfigDict(frozen=True)

    correction_id: NonBlank
    event_id: NonBlank
    corrected_at: AwareDatetime
    reason: NonBlank
    review_state: Literal["pending", "verified", "rejected"]
    origin: Literal["human", "system"] = "human"
    affected_instruments: tuple[tuple[AssetKind, str], ...] = ()
    industries: tuple[NonBlank, ...] = ()
    themes: tuple[NonBlank, ...] = ()
    association_confidence: Decimal | None = Field(default=None, ge=0, le=1)

    @field_validator("affected_instruments")
    @classmethod
    def validate_corrected_instruments(
        cls, values: tuple[tuple[AssetKind, str], ...]
    ) -> tuple[tuple[AssetKind, str], ...]:
        for asset, symbol in values:
            if asset is AssetKind.A_SHARE:
                validate_a_share_code(symbol)
            else:
                validate_convertible_bond_code(symbol)
        if len(set(values)) != len(values):
            raise ValueError("corrected instruments must be unique")
        return values
