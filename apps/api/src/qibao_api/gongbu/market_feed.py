from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from qibao_api.contracts.instruments import AShareCode, validate_a_share_code


class MarketFeedSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: AShareCode
    price: Decimal = Field(gt=0)
    change: Decimal
    change_percent: Decimal
    volume: Decimal = Field(ge=0)
    source: str = Field(min_length=1)
    observed_at: AwareDatetime
    fetched_at: AwareDatetime
    quality: Literal["ready", "partial", "blocked"]
    source_snapshot_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_times(self) -> "MarketFeedSnapshot":
        if self.observed_at > self.fetched_at:
            raise ValueError("observation cannot be after fetch time")
        return self


class MarketFeedPort(Protocol):
    capabilities: frozenset[str]

    def snapshot(self, symbol: str) -> MarketFeedSnapshot: ...
    def snapshot_many(self, symbols: tuple[str, ...]) -> tuple[MarketFeedSnapshot, ...]: ...
    def subscribe(self, symbols: tuple[str, ...]): ...


class PollingMarketFeed:
    capabilities = frozenset({"snapshot", "snapshot_many"})

    def __init__(
        self,
        fetch_many: Callable[[tuple[str, ...]], tuple[MarketFeedSnapshot, ...]],
    ) -> None:
        self._fetch_many = fetch_many

    def snapshot(self, symbol: str, *, cutoff: datetime | None = None) -> MarketFeedSnapshot:
        return self.snapshot_many((symbol,), cutoff=cutoff)[0]

    def snapshot_many(
        self, symbols: tuple[str, ...], *, cutoff: datetime | None = None,
    ) -> tuple[MarketFeedSnapshot, ...]:
        if len(symbols) != len(set(symbols)):
            raise ValueError("requested symbols must be unique")
        requested = tuple(validate_a_share_code(symbol) for symbol in symbols)
        responses = tuple(self._fetch_many(requested))
        response_symbols = tuple(item.symbol for item in responses)
        if len(response_symbols) != len(set(response_symbols)):
            raise ValueError("duplicate symbols in market feed response")
        if set(response_symbols) != set(requested) or len(responses) != len(requested):
            raise ValueError("market feed response symbols do not match request")
        if len({item.observed_at for item in responses}) > 1:
            raise ValueError("market feed batch has mixed cutoff timestamps")
        if cutoff is not None and any(
            item.observed_at > cutoff or item.fetched_at > cutoff for item in responses
        ):
            raise ValueError("market feed response contains a future timestamp")
        by_symbol = {item.symbol: item for item in responses}
        return tuple(by_symbol[symbol] for symbol in requested)

    def subscribe(self, symbols: tuple[str, ...]):
        raise NotImplementedError("polling feed does not support subscriptions")
