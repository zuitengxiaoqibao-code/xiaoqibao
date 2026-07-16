from datetime import datetime, timedelta

from qibao_api.contracts.market import DataQuality
from qibao_api.gongbu.quality import assess_observed_at


def test_old_quote_is_stale() -> None:
    now = datetime(2026, 7, 13, 10, 40)

    quality = assess_observed_at(
        now - timedelta(minutes=10),
        now,
        timedelta(minutes=3),
    )

    assert quality == DataQuality.STALE


def test_recent_quote_is_fresh() -> None:
    now = datetime(2026, 7, 13, 10, 40)

    quality = assess_observed_at(
        now - timedelta(minutes=1),
        now,
        timedelta(minutes=3),
    )

    assert quality == DataQuality.FRESH
