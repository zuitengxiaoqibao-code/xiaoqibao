import hashlib
import inspect
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict

from qibao_api.contracts.decision import AdviceCard, EvidenceReference
from qibao_api.a_shares.models import CandidateBoard
from qibao_api.contracts.market import AssetKind
from qibao_api.gongbu.market_feed import MarketFeedSnapshot
from qibao_api.gongbu.tencent_quotes import market_prefix, parse_tencent_snapshot
from qibao_api.shangshu.intraday_monitor import IntradayEvaluationResult
from qibao_api.zhongshu.premarket_decision import (
    CandidateInputSnapshot,
    ComplianceInputSnapshot,
    MarketRiskInputSnapshot,
)


CHINA_TZ = timezone(timedelta(hours=8))


class CutoffCandidateService(Protocol):
    def candidates(
        self, as_of: date, *, cutoff: datetime | None = None,
    ) -> CandidateBoard: ...


def _identity(prefix: str, value: Any) -> str:
    payload = json.dumps(value, default=str, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


class RepositoryCandidateFactorSource:
    def __init__(
        self, candidate_service: CutoffCandidateService,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.candidate_service = candidate_service
        self.clock = clock

    def candidates(
        self, as_of: date, cutoff: datetime | None = None,
    ) -> CandidateInputSnapshot:
        method = self.candidate_service.candidates
        if cutoff is None:
            board = method(as_of)
        else:
            signature = inspect.signature(method)
            try:
                cutoff_parameter = signature.parameters["cutoff"]
                signature.bind(as_of, cutoff=cutoff)
                if cutoff_parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                    raise TypeError("cutoff must accept keyword calls")
            except (KeyError, TypeError) as error:
                raise RuntimeError(
                    "candidate service cannot provide a cutoff snapshot"
                ) from error
            board = method(as_of, cutoff=cutoff)
        return CandidateInputSnapshot(
            board=board,
            captured_at=cutoff or self.clock(),
            history_available=(
                bool(board.short_term or board.swing)
                or any(
                    item.reason_code == "insufficient_liquidity"
                    for item in board.exclusions
                )
            ),
        )


class RepositoryComplianceSource:
    def __init__(self, repository) -> None:
        self.repository = repository

    def check(self, trading_date: date, cutoff: datetime) -> ComplianceInputSnapshot:
        checks = tuple(
            self.repository.check_feature_sources(feature, AssetKind.A_SHARE)
            for feature in ("realtime_quotes", "market_news")
        )
        reasons = tuple(reason for check in checks for reason in check.blocked_reasons)
        content = {"date": trading_date.isoformat(), "checks": [check.__dict__ for check in checks]}
        return ComplianceInputSnapshot(
            snapshot_id=_identity("compliance", content), captured_at=cutoff,
            available=all(check.blocked_reasons != ("feature_sources_unregistered",) for check in checks),
            allowed=all(check.allowed for check in checks), version="compliance-runtime-v1",
            risks=reasons,
        )

    def snapshot(self, *, now: datetime, cutoff: datetime):
        return self.check(now.astimezone(CHINA_TZ).date(), cutoff)


class RepositoryRiskSource:
    def __init__(self, audit_repository, candidate_service) -> None:
        self.audit_repository = audit_repository
        self.candidate_service = candidate_service

    def summarize(self, trading_date: date, cutoff: datetime) -> MarketRiskInputSnapshot:
        board = self.candidate_service.candidates(trading_date, cutoff=cutoff)
        entries = tuple((*board.short_term, *board.swing))
        findings = tuple(
            item for item in self.audit_repository.list_findings(asset=AssetKind.A_SHARE)
            if item.detected_at <= cutoff and item.resolution_state in {"open", "investigating"}
        )
        severe = any(item.severity in {"high", "critical"} for item in findings)
        scores = tuple(Decimal(str(item.score)) for item in entries)
        average = sum(scores, Decimal()) / len(scores) if scores else None
        factor_state = (
            "strong" if average is not None and average >= Decimal("8")
            else "weak" if average is not None and average <= Decimal("-8")
            else "range" if average is not None else "insufficient_data"
        )
        market_state = "weak" if severe else factor_state
        content = {
            "date": trading_date.isoformat(), "candidate": board.model_dump(mode="json"),
            "findings": [item.model_dump(mode="json") for item in findings],
        }
        return MarketRiskInputSnapshot(
            snapshot_id=_identity("risk", content), captured_at=cutoff,
            available=bool(scores), market_state=market_state,
            version="factor-breadth-audit-risk-v1",
            summary="candidate factor breadth with open audit overlays" if scores else "market factor evidence unavailable",
            risks=tuple(item.finding_type for item in findings) or (
                () if scores else ("market_factor_evidence_unavailable",)
            ),
        )

    def snapshot(self, *, now: datetime, cutoff: datetime):
        return self.summarize(now.astimezone(CHINA_TZ).date(), cutoff)


class RepositoryEvidenceSource:
    def __init__(self, news_repository) -> None:
        self.news_repository = news_repository

    def snapshot(self, *, now: datetime, cutoff: datetime):
        return tuple(
            item for item in self.news_repository.effective_events(cutoff=cutoff)
            if item.review_state == "verified"
            and item.occurred_at <= cutoff and item.normalized_at <= cutoff
        )


class CandidateFactorInputSource:
    def __init__(self, candidate_source) -> None:
        self.candidate_source = candidate_source

    def snapshot(self, *, now: datetime, cutoff: datetime):
        return self.candidate_source.candidates(
            now.astimezone(CHINA_TZ).date(), cutoff=cutoff
        )


class DecisionSymbolSource:
    def __init__(self, repository, candidate_source) -> None:
        self.repository = repository
        self.candidate_source = candidate_source

    def __call__(self, now: datetime) -> tuple[str, ...]:
        trading_date = now.astimezone(CHINA_TZ).date()
        symbols = {}
        for phase in ("premarket", "intraday"):
            for cycle in self.repository.cycles(trading_date, phase):
                symbols.update({item.symbol: None for item in cycle.advice})
        try:
            candidates = self.candidate_source.candidates(trading_date)
        except Exception:
            if not symbols:
                raise
        else:
            symbols.update({
                item.symbol: None
                for item in (*candidates.board.short_term, *candidates.board.swing)
            })
        return tuple(symbols)


class TencentPollingMarketFeed:
    capabilities = frozenset({"snapshot", "snapshot_many"})

    def __init__(self, client: httpx.Client, compliance_repository) -> None:
        self.client = client
        self.compliance_repository = compliance_repository

    def snapshot_many(self, symbols: tuple[str, ...], *, cutoff: datetime | None = None):
        self.compliance_repository.require_feature_sources("realtime_quotes", AssetKind.A_SHARE)
        if len(symbols) != len(set(symbols)):
            raise ValueError("requested symbols must be unique")
        snapshots = []
        for symbol in symbols:
            response = self.client.get(f"https://qt.gtimg.cn/q={market_prefix(symbol)}{symbol}")
            response.raise_for_status()
            raw = response.content.decode("gbk", errors="strict")
            if '="' not in raw:
                raise ValueError("Tencent quote response has no payload")
            payload = raw.split('="', 1)[1].rsplit('"', 1)[0]
            item = parse_tencent_snapshot(payload, "tencent")
            if item.volume is None:
                raise ValueError("Tencent quote payload has no volume")
            observed_at = item.observed_at.replace(tzinfo=CHINA_TZ)
            fetched_at = datetime.now(timezone.utc)
            if cutoff is not None and observed_at > cutoff:
                raise ValueError("Tencent observation is after decision cutoff")
            change = item.price - item.previous_close
            snapshots.append(MarketFeedSnapshot(
                symbol=item.symbol, price=item.price, change=change,
                change_percent=change / item.previous_close * Decimal("100"), volume=item.volume,
                source="tencent", observed_at=observed_at, fetched_at=fetched_at,
                quality="ready", source_snapshot_id=_identity("tencent", payload),
            ))
        return tuple(snapshots)

    def snapshot(self, symbol: str, *, cutoff: datetime | None = None):
        return self.snapshot_many((symbol,), cutoff=cutoff)[0]


class DeterministicIntradayEvaluator:
    def evaluate(self, context) -> IntradayEvaluationResult:
        by_symbol = {item.symbol: item for item in context.quotes}
        advice = []
        candidate_keys = {
            (item.symbol, horizon)
            for horizon, entries in (
                ("intraday", context.candidate_factor_input.board.short_term),
                ("swing", context.candidate_factor_input.board.swing),
            )
            for item in entries
        }
        current_advice = list(context.current_advice)
        if context.candidate_factor_input.history_available:
            current_advice = [
                item for item in current_advice
                if (item.symbol, item.horizon) in candidate_keys
            ]
        current_keys = {(item.symbol, item.horizon) for item in current_advice}
        current_advice.extend(
            item for item in self._seed_advice(context, by_symbol)
            if (item.symbol, item.horizon) not in current_keys
        )
        for current in current_advice:
            quote = by_symbol.get(current.symbol)
            if quote is None:
                continue
            evidence = EvidenceReference(
                evidence_id=quote.source_snapshot_id, source=quote.source,
                snapshot_id=quote.source_snapshot_id,
                summary="normalized Tencent quote observed during the decision window",
                observed_at=quote.observed_at,
            )
            advice.append(current.model_copy(update={
                "supporting_evidence": (evidence,), "contrary_evidence": (),
                "action": "observe", "risk_decision_id": None,
                "quantitative_result": {
                    "price": quote.price, "change_percent": quote.change_percent,
                    "membership": current.quantitative_result.get("membership"),
                },
                "plain_language_explanation": None,
            }))
        inputs = (
            context.candidate_factor_input, context.risk_input,
            context.compliance_input, context.evidence_input,
        )
        available = all(getattr(item, "available", True) for item in inputs)
        return IntradayEvaluationResult(
            advice=tuple(advice), gates={},
            source_content={
                "input_ids": [getattr(item, "snapshot_id", None) for item in inputs],
                "quote_ids": [item.source_snapshot_id for item in context.quotes],
            },
            market_state="insufficient_data", data_quality="partial" if available else "blocked",
            status="partial" if available else "blocked",
            candidate_snapshot_id=getattr(context.candidate_factor_input.board, "snapshot_id", None),
            news_event_ids=tuple(getattr(item, "event_id", "") for item in context.evidence_input),
            risk_event_ids=(),
        )

    @staticmethod
    def _seed_advice(context, by_symbol) -> tuple[AdviceCard, ...]:
        candidate_input = context.candidate_factor_input
        results = []
        for horizon, entries in (
            ("intraday", candidate_input.board.short_term),
            ("swing", candidate_input.board.swing),
        ):
            for entry in entries:
                quote = by_symbol.get(entry.symbol)
                if quote is None:
                    continue
                factor = EvidenceReference(
                    evidence_id=(
                        f"factor-{candidate_input.board.snapshot_id}-{entry.horizon}-{entry.symbol}"
                    ),
                    source=entry.factor_snapshot.source,
                    snapshot_id=candidate_input.board.snapshot_id or "candidate-board",
                    summary=f"intraday candidate factor {entry.factor_snapshot.factor_version}",
                    observed_at=candidate_input.captured_at,
                )
                results.append(AdviceCard(
                    advice_id=f"intraday-recovery-{horizon}-{entry.symbol}",
                    snapshot_id="intraday-recovery",
                    asset=AssetKind.A_SHARE,
                    symbol=entry.symbol,
                    horizon=horizon,
                    observation_state="watching",
                    action="observe",
                    conclusion="盘中恢复观察：等待当前行情与候选因子继续确认",
                    confidence=Decimal("0.5"),
                    supporting_evidence=(factor,),
                    contrary_evidence=(),
                    risks=tuple(dict.fromkeys((
                        "premarket_snapshot_unavailable",
                        *getattr(context.risk_input, "risks", ()),
                        *getattr(context.compliance_input, "risks", ()),
                    ))),
                    invalidation_conditions=(
                        "candidate_membership_changed",
                        "live_quote_became_unavailable",
                    ),
                    quantitative_result={
                        "candidate_score": entry.score,
                        "membership": entry.horizon,
                    },
                    strategy_version=(
                        f"intraday-recovery-v1/{entry.factor_snapshot.factor_version}"
                    ),
                    created_at=context.now,
                ))
        return tuple(results)


class RuntimeMarketOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome_id: str
    advice_id: str
    available: bool = False
    observed_at: AwareDatetime
    source_snapshot_id: str
    open: Decimal
    close: Decimal
    withdrawal_reason: str = "direction cannot be inferred from an observation-only advice"


class RepositoryMarketOutcomeSource:
    def __init__(self, decision_repository, bar_repository) -> None:
        self.decision_repository = decision_repository
        self.bar_repository = bar_repository

    def list_market_outcomes(self, advice_ids, window_start, close):
        known = {
            item.advice_id: item
            for phase in ("premarket", "intraday")
            for cycle in self.decision_repository.cycles(window_start.date(), phase)
            for item in cycle.advice
        }
        outcomes = []
        for advice_id in advice_ids:
            advice = known.get(advice_id)
            if advice is None:
                continue
            bars = self.bar_repository.latest_many(
                [advice.symbol], 1, window_start.date()
            ).get(advice.symbol, [])
            if not bars or bars[-1].trade_date != window_start.date():
                continue
            bar = bars[-1]
            content = bar.model_dump(mode="json")
            outcomes.append(RuntimeMarketOutcome(
                outcome_id=_identity("outcome", {"advice_id": advice_id, "bar": content}),
                advice_id=advice_id, observed_at=close,
                source_snapshot_id=_identity("daily-bar", content),
                open=bar.open, close=bar.close,
            ))
        return tuple(outcomes)


class DecisionPhaseRunner:
    def __init__(self, *, repository, premarket, intraday_monitor, postclose) -> None:
        self.repository = repository
        self.premarket = premarket
        self.intraday_monitor = intraday_monitor
        self.postclose = postclose

    def run(self, phase: str, trading_date: date, *, now: datetime):
        if phase == "premarket":
            return self.premarket.run(trading_date, now)
        if phase == "intraday":
            result = self.intraday_monitor.check(now)
            return result.aggregate or self.repository.latest(trading_date, "intraday")
        if phase == "postclose":
            return self.postclose.run(trading_date, now).aggregate
        raise ValueError(f"unsupported decision phase: {phase}")
