from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class AssetKind(StrEnum):
    A_SHARE = "a_share"
    CONVERTIBLE_BOND = "convertible_bond"


class DataQuality(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    CONFLICTED = "conflicted"
    UNAVAILABLE = "unavailable"


class Quote(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    asset: AssetKind
    name: str
    price: Decimal = Field(gt=0)
    previous_close: Decimal = Field(gt=0)
    observed_at: datetime
    source: str
    quality: DataQuality

