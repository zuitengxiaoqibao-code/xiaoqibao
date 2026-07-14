from datetime import date
from decimal import Decimal

from qibao_api.a_shares.candidates import build_candidate_board
from qibao_api.a_shares.models import FactorSnapshot


AS_OF = date(2026, 7, 14)


def snapshot(
    symbol: str,
    *,
    return_5d: str,
    return_20d: str,
    distance_ma20: str,
    volume_ratio: str,
    volatility: str,
    drawdown: str,
    liquidity: str = "50000000",
) -> FactorSnapshot:
    return FactorSnapshot(
        symbol=symbol,
        as_of=AS_OF,
        close=Decimal("10"),
        return_5d=Decimal(return_5d),
        return_20d=Decimal(return_20d),
        distance_ma20=Decimal(distance_ma20),
        volume_ratio_5_20=Decimal(volume_ratio),
        volatility_20d=Decimal(volatility),
        drawdown_60d=Decimal(drawdown),
        liquidity_amount_20d=Decimal(liquidity),
        source="fixture",
    )


def test_short_term_and_swing_boards_rank_differently() -> None:
    momentum = snapshot(
        "600001", return_5d="0.18", return_20d="0.10", distance_ma20="0.08",
        volume_ratio="2.2", volatility="0.06", drawdown="-0.22",
    )
    stable_trend = snapshot(
        "600002", return_5d="0.05", return_20d="0.28", distance_ma20="0.16",
        volume_ratio="1.1", volatility="0.015", drawdown="-0.03",
    )
    neutral = snapshot(
        "600003", return_5d="0.02", return_20d="0.03", distance_ma20="0.01",
        volume_ratio="1.0", volatility="0.03", drawdown="-0.08",
    )

    board = build_candidate_board([momentum, stable_trend, neutral], limit=10)

    assert board.short_term[0].symbol == "600001"
    assert board.swing[0].symbol == "600002"
    assert set(board.short_term[0].score_breakdown) == {
        "momentum", "volume", "trend", "liquidity", "risk_penalty"
    }
    assert board.short_term[0].score == sum(
        board.short_term[0].score_breakdown.values(), start=Decimal("0")
    )
    assert board.swing[0].score == sum(
        board.swing[0].score_breakdown.values(), start=Decimal("0")
    )
    assert board.short_term[0].score_breakdown["risk_penalty"] <= 0
    assert board.factor_version == "a-share-factors-v1"
    assert board.as_of == AS_OF


def test_candidate_board_excludes_insufficient_liquidity() -> None:
    illiquid = snapshot(
        "600004", return_5d="0.20", return_20d="0.30", distance_ma20="0.10",
        volume_ratio="3", volatility="0.02", drawdown="-0.01", liquidity="9999999",
    )

    board = build_candidate_board([illiquid], limit=10)

    assert board.short_term == []
    assert board.swing == []
    assert board.exclusions[0].symbol == "600004"
    assert board.exclusions[0].reason_code == "insufficient_liquidity"


def test_candidate_board_breaks_equal_scores_by_symbol() -> None:
    first = snapshot(
        "000001", return_5d="0.1", return_20d="0.1", distance_ma20="0.1",
        volume_ratio="1.2", volatility="0.02", drawdown="-0.04",
    )
    second = first.model_copy(update={"symbol": "600001"})

    board = build_candidate_board([second, first], limit=10)

    assert [item.symbol for item in board.short_term] == ["000001", "600001"]
    assert [item.symbol for item in board.swing] == ["000001", "600001"]
