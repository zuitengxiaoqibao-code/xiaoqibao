from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Literal

from qibao_api.a_shares.models import (
    CandidateBoard,
    CandidateEntry,
    CandidateExclusion,
    FactorSnapshot,
)


MINIMUM_AVERAGE_AMOUNT = Decimal("10000000")


def _quantile(values: Sequence[Decimal], probability: Decimal) -> Decimal:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * probability
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def _winsorized(
    snapshots: Sequence[FactorSnapshot],
    value: Callable[[FactorSnapshot], Decimal],
) -> dict[str, Decimal]:
    raw = [value(item) for item in snapshots]
    lower = _quantile(raw, Decimal("0.05"))
    upper = _quantile(raw, Decimal("0.95"))
    return {
        item.symbol: max(lower, min(upper, value(item)))
        for item in snapshots
    }


def _percentiles(
    snapshots: Sequence[FactorSnapshot],
    value: Callable[[FactorSnapshot], Decimal],
) -> dict[str, Decimal]:
    winsorized = _winsorized(snapshots, value)
    ordered = sorted((winsorized[item.symbol], item.symbol) for item in snapshots)
    if len(ordered) == 1:
        return {ordered[0][1]: Decimal("0.5")}
    positions: dict[Decimal, list[int]] = {}
    for index, (metric, _) in enumerate(ordered):
        positions.setdefault(metric, []).append(index)
    result = {}
    denominator = Decimal(len(ordered) - 1)
    for metric, symbol in ordered:
        indexes = positions[metric]
        middle_rank = Decimal(sum(indexes)) / Decimal(len(indexes))
        result[symbol] = middle_rank / denominator
    return result


def rank_candidates(
    snapshots: Sequence[FactorSnapshot],
    horizon: Literal["short_term", "swing"],
    limit: int = 20,
) -> list[CandidateEntry]:
    if horizon not in {"short_term", "swing"}:
        raise ValueError("horizon must be short_term or swing")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    if not snapshots:
        return []
    return_5d = _percentiles(snapshots, lambda item: item.return_5d)
    return_20d = _percentiles(snapshots, lambda item: item.return_20d)
    volume = _percentiles(snapshots, lambda item: item.volume_ratio_5_20)
    trend = _percentiles(snapshots, lambda item: item.distance_ma20)
    liquidity = _percentiles(snapshots, lambda item: item.liquidity_amount_20d)
    volatility = _percentiles(snapshots, lambda item: item.volatility_20d)
    drawdown_risk = _percentiles(snapshots, lambda item: -item.drawdown_60d)
    entries = []
    for item in snapshots:
        if horizon == "short_term":
            breakdown = {
                "momentum": return_5d[item.symbol] * Decimal("30"),
                "volume": volume[item.symbol] * Decimal("25"),
                "trend": trend[item.symbol] * Decimal("20"),
                "liquidity": liquidity[item.symbol] * Decimal("15"),
                "risk_penalty": -(volatility[item.symbol] * Decimal("10")),
            }
        else:
            breakdown = {
                "momentum": return_20d[item.symbol] * Decimal("25"),
                "trend": trend[item.symbol] * Decimal("30"),
                "liquidity": liquidity[item.symbol] * Decimal("15"),
                "volatility_penalty": -(volatility[item.symbol] * Decimal("10")),
                "drawdown_penalty": -(drawdown_risk[item.symbol] * Decimal("20")),
            }
        score = sum(breakdown.values(), start=Decimal("0"))
        entries.append(CandidateEntry(
            symbol=item.symbol,
            horizon=horizon,
            score=score,
            score_breakdown=breakdown,
            factor_snapshot=item,
        ))
    return sorted(entries, key=lambda entry: (-entry.score, entry.symbol))[:limit]


def build_candidate_board(
    snapshots: Sequence[FactorSnapshot],
    limit: int = 20,
) -> CandidateBoard:
    if not snapshots:
        raise ValueError("at least one factor snapshot is required")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    as_of = snapshots[0].as_of
    if any(item.as_of != as_of for item in snapshots):
        raise ValueError("all factor snapshots must share one as_of date")
    eligible = [
        item for item in snapshots
        if item.liquidity_amount_20d >= MINIMUM_AVERAGE_AMOUNT
    ]
    exclusions = [
        CandidateExclusion(
            symbol=item.symbol,
            reason_code="insufficient_liquidity",
            observed_value=item.liquidity_amount_20d,
            threshold=MINIMUM_AVERAGE_AMOUNT,
        )
        for item in snapshots
        if item.liquidity_amount_20d < MINIMUM_AVERAGE_AMOUNT
    ]
    short_term = rank_candidates(eligible, "short_term", limit)
    swing = rank_candidates(eligible, "swing", limit)
    return CandidateBoard(
        as_of=as_of,
        short_term=short_term,
        swing=swing,
        exclusions=sorted(exclusions, key=lambda item: item.symbol),
    )
