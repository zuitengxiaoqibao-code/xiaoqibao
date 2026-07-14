from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class BondStrategyExecutionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enable_t0: bool = False


class BondBacktestExecutionPolicy(BaseModel):
    """Execution constraint contract; this is not a backtest engine."""

    model_config = ConfigDict(frozen=True)

    settlement: Literal["T+0", "T+1"]

    @classmethod
    def for_request(cls, request: BondStrategyExecutionRequest) -> "BondBacktestExecutionPolicy":
        return cls(settlement="T+0" if request.enable_t0 else "T+1")

    def can_sell(self, *, acquired_on: date, sell_on: date) -> bool:
        minimum = acquired_on.toordinal() + (0 if self.settlement == "T+0" else 1)
        return sell_on.toordinal() >= minimum
