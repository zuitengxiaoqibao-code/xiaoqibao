from decimal import Decimal

from qibao_api.contracts.market import Quote
from qibao_api.contracts.research import Evidence, ResearchCard


def build_market_snapshot(quote: Quote) -> ResearchCard:
    change = (quote.price / quote.previous_close - Decimal("1")) * Decimal("100")
    return ResearchCard(
        symbol=quote.symbol,
        asset=quote.asset,
        action="observe",
        change_percent=change.quantize(Decimal("0.01")),
        quality=quote.quality,
        evidence=[
            Evidence(
                label="最新价",
                value=str(quote.price),
                source=quote.source,
                observed_at=quote.observed_at,
            )
        ],
    )

