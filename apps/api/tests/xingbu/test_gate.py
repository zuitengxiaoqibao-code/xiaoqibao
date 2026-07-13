from decimal import Decimal

from qibao_api.contracts.market import AssetKind, DataQuality
from qibao_api.contracts.research import ResearchCard
from qibao_api.xingbu.gate import RiskGate


def test_stale_quote_is_blocked() -> None:
    card = ResearchCard(
        symbol="600000",
        asset=AssetKind.A_SHARE,
        action="observe",
        change_percent=Decimal("1.49"),
        quality=DataQuality.STALE,
        evidence=[],
    )

    reviewed = RiskGate().review(card)

    assert reviewed.action == "blocked"
    assert "数据已过期或质量异常" in reviewed.invalid_reasons


def test_fresh_card_passes_without_mutation() -> None:
    card = ResearchCard(
        symbol="600000",
        asset=AssetKind.A_SHARE,
        action="observe",
        change_percent=Decimal("1.49"),
        quality=DataQuality.FRESH,
        evidence=[],
    )

    assert RiskGate().review(card) == card
