from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class DailyBar(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)
    amount: Decimal = Field(ge=0)
    source: str

    @model_validator(mode="after")
    def validate_range(self) -> "DailyBar":
        if self.high < self.low:
            raise ValueError("daily high cannot be lower than daily low")
        if not self.low <= self.open <= self.high:
            raise ValueError("open is outside the daily range")
        if not self.low <= self.close <= self.high:
            raise ValueError("close is outside the daily range")
        return self


class DataSourceState(StrEnum):
    READY = "ready"
    ERROR = "error"
    EMPTY = "empty"


class SyncReport(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    state: DataSourceState
    written_rows: int = Field(ge=0)
    source: str
    parquet_path: str | None = None
    started_at: datetime
    finished_at: datetime
    message: str

    @model_validator(mode="after")
    def validate_ready_report(self) -> "SyncReport":
        if self.state is DataSourceState.READY:
            if self.written_rows == 0:
                raise ValueError("ready sync report must contain rows")
            if not self.parquet_path:
                raise ValueError("ready sync report must include parquet path")
        return self
