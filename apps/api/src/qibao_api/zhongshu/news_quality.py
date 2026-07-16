from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field


class NewsQualityMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    article_count: int = Field(ge=0)
    cluster_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    interpretation_count: int = Field(ge=0)
    correction_count: int = Field(ge=0)
    citation_coverage: Decimal = Field(ge=0, le=1)
    duplicate_rate: Decimal = Field(ge=0, le=1)
    invalid_json_rate: Decimal = Field(ge=0, le=1)
    provider_error_rate: Decimal = Field(ge=0, le=1)
    human_correction_rate: Decimal = Field(ge=0, le=1)


class NewsQualityService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def metrics(self) -> NewsQualityMetrics:
        articles = self.repository.articles()
        clusters = self.repository.clusters()
        events = self.repository.events()
        interpretations = self.repository.interpretations()
        corrections = self.repository.corrections()
        statements = [
            statement
            for interpretation in interpretations
            for statement in interpretation.statements
        ]
        compliant = sum(
            statement.kind == "interpretation" or bool(statement.citation_ids)
            for statement in statements
        )
        attempts = sum(item.provider_attempts for item in interpretations)
        invalid = sum(item.invalid_output_count for item in interpretations)
        provider_errors = sum(item.provider_error_count for item in interpretations)
        human_corrected_events = {
            item.event_id for item in corrections if item.origin == "human"
        }
        return NewsQualityMetrics(
            article_count=len(articles),
            cluster_count=len(clusters),
            event_count=len(events),
            interpretation_count=len(interpretations),
            correction_count=len(corrections),
            citation_coverage=_rate(compliant, len(statements), empty=Decimal("1")),
            duplicate_rate=_rate(len(articles) - len(clusters), len(articles)),
            invalid_json_rate=_rate(invalid, attempts),
            provider_error_rate=_rate(provider_errors, attempts),
            human_correction_rate=_rate(len(human_corrected_events), len(events)),
        )


def _rate(numerator: int, denominator: int, *, empty: Decimal = Decimal("0")) -> Decimal:
    if denominator == 0:
        return empty.quantize(Decimal("0.0001"))
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
