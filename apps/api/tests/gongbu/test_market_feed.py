from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.gongbu.market_feed import MarketFeedSnapshot, PollingMarketFeed


NOW = datetime(2026, 7, 14, 2, 30, tzinfo=UTC)


def quote(symbol: str, *, observed_at=NOW, source_snapshot_id=None):
    return MarketFeedSnapshot(
        symbol=symbol, price=Decimal("10.25"), change=Decimal("0.15"),
        change_percent=Decimal("1.49"), volume=Decimal("1200"), source="test",
        observed_at=observed_at, fetched_at=max(NOW, observed_at),
        quality="ready", source_snapshot_id=source_snapshot_id or f"q-{symbol}",
    )


def test_polling_feed_capabilities_and_subscribe() -> None:
    feed = PollingMarketFeed(lambda symbols: tuple(quote(symbol) for symbol in symbols))
    assert feed.capabilities == frozenset({"snapshot", "snapshot_many"})
    with pytest.raises(NotImplementedError):
        feed.subscribe(("000001",))


@pytest.mark.parametrize("responses", [
    (quote("000001"), quote("000001", source_snapshot_id="duplicate")),
    (quote("000001"),),
    (quote("000001"), quote("600000"), quote("300001")),
    (quote("000001"), quote("300001", observed_at=NOW + timedelta(seconds=1))),
])
def test_batch_rejects_contamination_missing_extra_and_mixed_cutoffs(responses) -> None:
    feed = PollingMarketFeed(lambda _symbols: responses)
    with pytest.raises(ValueError):
        feed.snapshot_many(("000001", "300001"))


def test_snapshot_rejects_non_a_share_and_future_timestamps() -> None:
    with pytest.raises(ValidationError):
        quote("123001")
    feed = PollingMarketFeed(lambda _symbols: (quote("000001", observed_at=NOW + timedelta(seconds=1)),))
    with pytest.raises(ValueError, match="future"):
        feed.snapshot_many(("000001",), cutoff=NOW)
