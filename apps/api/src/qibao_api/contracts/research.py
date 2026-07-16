from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from qibao_api.contracts.market import AssetKind, DataQuality


class Evidence(BaseModel):
    label: str
    value: str
    source: str
    observed_at: datetime


class ResearchCard(BaseModel):
    symbol: str
    asset: AssetKind
    action: Literal["observe", "blocked"]
    change_percent: Decimal
    quality: DataQuality
    evidence: list[Evidence]
    invalid_reasons: list[str] = Field(default_factory=list)

