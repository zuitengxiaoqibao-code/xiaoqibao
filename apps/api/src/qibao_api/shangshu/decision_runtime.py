import hashlib
import inspect
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
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
    def __init__(
        self, audit_repository, candidate_service, *, news_repository=None,
        classification_repository=None, fund_flow_repository=None, trading_calendar=None,
    ) -> None:
        self.audit_repository = audit_repository
        self.candidate_service = candidate_service
        self.news_repository = news_repository
        self.classification_repository = classification_repository
        self.fund_flow_repository = fund_flow_repository
        self.trading_calendar = trading_calendar

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
        hot_topics, industries = self._news_labels(trading_date, cutoff)
        classified_industries = self._candidate_industries(entries, trading_date, cutoff)
        industries = tuple(dict.fromkeys((*industries, *classified_industries)))
        flow_counts = self._candidate_fund_flow(entries, trading_date, cutoff)
        if (
            not severe
            and flow_counts["outflow"] >= 2
            and flow_counts["outflow"] > flow_counts["inflow"]
        ):
            market_state = "weak"
        summary_parts = [
            "候选因子宽度",
            f"已核验热点 {len(hot_topics)} 个" if hot_topics else "暂无已核验热点",
            f"行业 {len(industries)} 个" if industries else "暂无行业归因",
            f"资金流入/流出 {flow_counts['inflow']}/{flow_counts['outflow']}"
            if flow_counts["available"] else "暂无候选资金流快照",
        ]
        risk_reasons = [item.finding_type for item in findings]
        if flow_counts["outflow"] > flow_counts["inflow"]:
            risk_reasons.append("候选资金流偏流出")
        if not risk_reasons and not scores:
            risk_reasons.append("market_factor_evidence_unavailable")
        content = {
            "date": trading_date.isoformat(), "candidate": board.model_dump(mode="json"),
            "findings": [item.model_dump(mode="json") for item in findings],
            "hot_topics": hot_topics, "industries": industries, "fund_flow": flow_counts,
        }
        return MarketRiskInputSnapshot(
            snapshot_id=_identity("risk", content), captured_at=cutoff,
            available=bool(scores), market_state=market_state,
            version="factor-breadth-news-flow-risk-v2",
            summary="；".join(summary_parts) if scores else "市场因子证据不可用",
            risks=tuple(dict.fromkeys(risk_reasons)),
            hot_topics=hot_topics, industries=industries,
            fund_flow_inflow_count=flow_counts["inflow"],
            fund_flow_outflow_count=flow_counts["outflow"],
            fund_flow_available_count=flow_counts["available"],
        )

    def _news_labels(self, trading_date, cutoff):
        if self.news_repository is None:
            return (), ()
        if self.trading_calendar is not None:
            previous = self.trading_calendar.previous_trading_day(trading_date)
            window_start = datetime.combine(previous, time(15), CHINA_TZ)
        else:
            window_start = cutoff - timedelta(hours=24)
        try:
            events = tuple(
                item for item in self.news_repository.effective_events(cutoff=cutoff)
                if item.review_state == "verified"
                and window_start <= item.occurred_at <= cutoff
                and item.normalized_at <= cutoff
            )
        except Exception:
            return (), ()
        topics = Counter(theme for item in events for theme in item.themes if theme)
        industries = Counter(industry for item in events for industry in item.industries if industry)
        return (
            tuple(label for label, _ in topics.most_common(5)),
            tuple(label for label, _ in industries.most_common(5)),
        )

    def _candidate_industries(self, entries, trading_date, cutoff):
        if self.classification_repository is None:
            return ()
        values = []
        for item in entries:
            symbol = getattr(item, "symbol", None)
            if not symbol:
                continue
            try:
                snapshot = self.classification_repository.latest(
                    symbol, trading_date, cutoff=cutoff,
                )
            except Exception:
                continue
            if snapshot is not None and getattr(snapshot, "industry", None):
                values.append(snapshot.industry)
        return tuple(dict.fromkeys(values))

    def _candidate_fund_flow(self, entries, trading_date, cutoff):
        counts = {"inflow": 0, "outflow": 0, "available": 0}
        if self.fund_flow_repository is None:
            return counts
        seen_symbols = set()
        for item in entries:
            symbol = getattr(item, "symbol", None)
            if not symbol or symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            try:
                snapshot = self.fund_flow_repository.latest(
                    symbol, trading_date, cutoff=cutoff,
                )
            except Exception:
                continue
            direction = getattr(snapshot, "flow_direction", None) if snapshot else None
            if direction in {"inflow", "outflow", "balanced"}:
                if direction != "balanced":
                    counts[direction] += 1
                counts["available"] += 1
        return counts

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
    STRONG_MOVE = Decimal("2")

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
                summary=self._quote_summary(quote),
                observed_at=quote.observed_at,
            )
            related_events = tuple(
                item for item in context.evidence_input
                if self._event_matches(item, current.symbol)
                and context.window_start <= item.normalized_at <= context.window_end
            )
            news_supporting = ()
            news_contrary = tuple(
                self._event_evidence(item) for item in related_events
                if self._risk_event(item)
            )
            action, conclusion, observation_state, confidence = self._signal_for_quote(quote)
            risks = tuple(dict.fromkeys((
                *current.risks,
                *getattr(context.risk_input, "risks", ()),
                *getattr(context.compliance_input, "risks", ()),
                *(("风险新闻",) if news_contrary else ()),
            ))) or ("盘中变化仍需后续行情确认",)
            advice.append(current.model_copy(update={
                "supporting_evidence": tuple(dict.fromkeys((
                    *current.supporting_evidence, evidence, *news_supporting,
                ))),
                "contrary_evidence": news_contrary,
                "action": action, "observation_state": observation_state,
                "conclusion": conclusion, "confidence": confidence,
                "risks": risks, "risk_decision_id": None,
                "quantitative_result": {
                    "price": quote.price, "change_percent": quote.change_percent,
                    "membership": current.quantitative_result.get("membership"),
                },
                "plain_language_explanation": (
                    f"最新价 {quote.price}，盘中涨跌 {quote.change_percent}%。"
                    f"当前建议是{conclusion}，不是立即交易指令。"
                ),
            }))
        inputs = (
            context.candidate_factor_input, context.risk_input,
            context.compliance_input, context.evidence_input,
        )
        quote_ready = bool(context.quotes) and all(
            getattr(item, "quality", "ready") == "ready"
            and 0 <= (context.now - item.observed_at).total_seconds() <= 180
            for item in context.quotes
        )
        compliance_allowed = getattr(context.compliance_input, "allowed", True)
        available = all(getattr(item, "available", True) for item in inputs)
        available = available and quote_ready and compliance_allowed
        if not quote_ready or not compliance_allowed:
            advice = []
        market_state = self._market_state(context.quotes)
        return IntradayEvaluationResult(
            advice=tuple(advice), gates={},
            source_content={
                "input_ids": [getattr(item, "snapshot_id", None) for item in inputs],
                "quote_ids": [item.source_snapshot_id for item in context.quotes],
            },
            market_state=market_state, data_quality="ready" if available else "blocked",
            status="ready" if available else "blocked",
            candidate_snapshot_id=getattr(context.candidate_factor_input.board, "snapshot_id", None),
            news_event_ids=tuple(getattr(item, "event_id", "") for item in context.evidence_input),
            risk_event_ids=(),
        )

    @classmethod
    def _signal_for_quote(cls, quote):
        change = Decimal(str(quote.change_percent))
        if change >= cls.STRONG_MOVE:
            return "observe", "盘中走强，等待放量确认", "strengthening", Decimal("0.72")
        if change <= -cls.STRONG_MOVE:
            return "wait", "盘中走弱，等待止跌确认", "weakening", Decimal("0.28")
        if change > 0:
            return "observe", "小幅走强，继续观察量价配合", "watching", Decimal("0.58")
        if change < 0:
            return "wait", "小幅走弱，暂不追涨", "waiting", Decimal("0.42")
        return "observe", "横盘整理，等待方向确认", "watching", Decimal("0.5")

    @classmethod
    def _market_state(cls, quotes):
        if not quotes:
            return "insufficient_data"
        changes = [Decimal(str(item.change_percent)) for item in quotes]
        average = sum(changes, Decimal("0")) / Decimal(len(changes))
        positive = sum(value >= cls.STRONG_MOVE for value in changes)
        negative = sum(value <= -cls.STRONG_MOVE for value in changes)
        if average >= cls.STRONG_MOVE or positive > negative * 2:
            return "strong"
        if average <= -cls.STRONG_MOVE or negative > positive * 2:
            return "weak"
        return "range"

    @staticmethod
    def _quote_summary(quote):
        return f"盘中行情：最新价 {quote.price}，涨跌 {quote.change_percent}%（{quote.source}）"

    @staticmethod
    def _event_matches(event, symbol):
        for asset, event_symbol in getattr(event, "affected_instruments", ()):
            asset_value = getattr(asset, "value", asset)
            if asset_value == AssetKind.A_SHARE.value and event_symbol == symbol:
                return True
        return False

    @staticmethod
    def _risk_event(event):
        return "risk" in event.event_type or "风险事件" in event.themes

    @staticmethod
    def _event_evidence(event):
        citations = getattr(event, "citations", ())
        publisher = citations[0].publisher if citations else "verified-news"
        return EvidenceReference(
            evidence_id=f"news-{event.event_id}", source=publisher,
            snapshot_id=event.event_id, summary=event.headline,
            observed_at=event.normalized_at,
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
                    summary=(
                        f"候选因子：评分 {entry.score}，5日涨跌 "
                        f"{entry.factor_snapshot.return_5d:.2%}，趋势距MA20 "
                        f"{entry.factor_snapshot.distance_ma20:.2%}"
                    ),
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
                    conclusion="盘中恢复观察，等待当前行情与候选因子继续确认",
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
