from datetime import datetime
from decimal import Decimal

from qibao_api.contracts.market import AssetKind, DataQuality, Quote
from qibao_api.zhongshu.daily_research import build_market_snapshot


def test_fresh_quote_produces_observation_card() -> None:
    quote = Quote(
        symbol="600000",
        asset=AssetKind.A_SHARE,
        name="浦发银行",
        price=Decimal("10.25"),
        previous_close=Decimal("10.10"),
        observed_at=datetime(2026, 7, 13, 10, 30),
        source="tencent",
        quality=DataQuality.FRESH,
    )

    card = build_market_snapshot(quote)

    assert card.action == "observe"
    assert card.change_percent == Decimal("1.49")
    assert card.evidence[0].source == "tencent"

