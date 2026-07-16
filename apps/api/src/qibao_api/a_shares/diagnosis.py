import asyncio
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qibao_api.a_shares.candidates import build_candidate_board
from qibao_api.a_shares.factors import InsufficientHistoryError, build_factor_snapshot
from qibao_api.a_shares.fundamentals import FundamentalSnapshot
from qibao_api.a_shares.models import (
    CandidateBoard,
    CandidateExclusion,
    FACTOR_VERSION,
)
from qibao_api.contracts.bars import DailyBar
from qibao_api.contracts.market import AssetKind
from qibao_api.contracts.news import NormalizedNewsEvent
from qibao_api.gongbu.tencent_quotes import TencentMarketSnapshot
from qibao_api.libu_compliance.repository import SourceAuthorizationError


SECTION_NAMES = {
    "market", "price_volume", "trend", "valuation", "fundamentals",
    "events", "industry", "risk",
}


class DiagnosisUnavailableError(RuntimeError):
    pass


class DiagnosisSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "unavailable"]
    observed_at: datetime | date | None = None
    source: str
    metrics: dict[str, Decimal | int | str | None] = Field(default_factory=dict)
    evidence_ids: tuple[str, ...] = ()
    explanation: str


class AShareDiagnosis(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: Literal["a_share"] = "a_share"
    snapshot_id: str | None = None
    input_snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    symbol: str = Field(pattern=r"^\d{6}$")
    as_of: date
    action: Literal["observe", "blocked"]
    overall_status: Literal["ready", "partial"]
    sections: dict[str, DiagnosisSection]
    missing_data: list[str] = Field(default_factory=list)
    factor_version: Literal["a-share-factors-v1"] = FACTOR_VERSION

    @model_validator(mode="after")
    def require_all_sections(self) -> "AShareDiagnosis":
        if set(self.sections) != SECTION_NAMES:
            raise ValueError("diagnosis must contain all required sections")
        return self


class BarRepositoryPort(Protocol):
    def symbols_with_history(
        self, minimum_bars: int, as_of: date, *, cutoff: datetime | None = None,
    ) -> list[str]: ...
    def latest_many(
        self, symbols: list[str], limit: int, as_of: date,
        *, cutoff: datetime | None = None,
    ) -> dict[str, list[DailyBar]]: ...


class MarketSourcePort(Protocol):
    async def fetch_snapshot(self, symbol: str) -> TencentMarketSnapshot: ...


class FinanceSourcePort(Protocol):
    def fetch(self, symbol: str) -> FundamentalSnapshot: ...


class NewsRepositoryPort(Protocol):
    def events(self) -> list[NormalizedNewsEvent]: ...


class ResearchSnapshotRepositoryPort(Protocol):
    def append_candidate_board(
        self, board: CandidateBoard, input_payload: dict | None = None
    ) -> str: ...
    def get_candidate_board(self, snapshot_id: str) -> CandidateBoard: ...
    def append_diagnosis(
        self, diagnosis: AShareDiagnosis, input_payload: dict | None = None
    ) -> str: ...
    def get_diagnosis(self, snapshot_id: str) -> AShareDiagnosis: ...


def _unavailable(source: str, explanation: str) -> DiagnosisSection:
    return DiagnosisSection(status="unavailable", source=source, explanation=explanation)


class AShareDiagnosisService:
    def __init__(
        self,
        bar_repository: BarRepositoryPort,
        market_source: MarketSourcePort,
        finance_source: FinanceSourcePort,
        news_repository: NewsRepositoryPort,
        research_repository: ResearchSnapshotRepositoryPort | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.bar_repository = bar_repository
        self.market_source = market_source
        self.finance_source = finance_source
        self.news_repository = news_repository
        self.research_repository = research_repository
        self.clock = clock

    async def inspect_sources(
        self, symbol: str, as_of: date, *, cutoff: datetime | None = None
    ) -> dict[str, tuple[object | None, str | None]]:
        market = await self._market(
            symbol, as_of, cutoff=cutoff, degrade_authorization=True
        )
        finance = await self._finance(
            symbol, as_of, cutoff=cutoff, degrade_authorization=True
        )
        return {"quote": market, "finance": finance}

    def candidates(
        self, as_of: date, limit: int = 20, *, cutoff: datetime | None = None,
    ) -> CandidateBoard:
        if cutoff is None:
            symbols = self.bar_repository.symbols_with_history(60, as_of)
            histories = self.bar_repository.latest_many(symbols, 60, as_of)
        else:
            symbols = self.bar_repository.symbols_with_history(60, as_of, cutoff=cutoff)
            histories = self.bar_repository.latest_many(
                symbols, 60, as_of, cutoff=cutoff,
            )
        snapshots = []
        exclusions = []
        for symbol in symbols:
            try:
                snapshots.append(build_factor_snapshot(histories.get(symbol, []), as_of))
            except (InsufficientHistoryError, ValueError) as error:
                exclusions.append(CandidateExclusion(
                    symbol=symbol, reason_code="invalid_history", detail=str(error)
                ))
        if not snapshots:
            board = CandidateBoard(
                as_of=as_of, short_term=[], swing=[], exclusions=exclusions
            )
        else:
            board = build_candidate_board(snapshots, limit)
            board = board.model_copy(update={
                "exclusions": sorted(
                    [*exclusions, *board.exclusions], key=lambda item: item.symbol
                )
            })
        if self.research_repository is None:
            return board
        input_payload = {
            "as_of": as_of.isoformat(),
            "factor_version": FACTOR_VERSION,
            "histories": {
                symbol: [bar.model_dump(mode="json") for bar in histories.get(symbol, [])]
                for symbol in symbols
            },
        }
        snapshot_id = self.research_repository.append_candidate_board(
            board, input_payload=input_payload
        )
        return self.research_repository.get_candidate_board(snapshot_id)

    async def diagnose(
        self, symbol: str, as_of: date, *, persist: bool = True,
        cutoff: datetime | None = None,
    ) -> AShareDiagnosis:
        bars = (
            self.bar_repository.latest_many([symbol], 120, as_of, cutoff=cutoff)
            if cutoff is not None
            else self.bar_repository.latest_many([symbol], 120, as_of)
        ).get(symbol, [])
        market, market_error = await self._market(
            symbol, as_of, cutoff=cutoff, degrade_authorization=not persist
        )
        if not bars and market is None and persist:
            raise DiagnosisUnavailableError(
                f"market and local history are unavailable: {market_error}"
            )
        finance, finance_error = await self._finance(
            symbol, as_of, cutoff=cutoff, degrade_authorization=not persist
        )
        events, news_error = self._events(symbol, as_of, cutoff=cutoff)
        sections = self._sections(
            symbol, as_of, bars, market, market_error, finance, finance_error,
            events, news_error,
        )
        missing = [name for name, section in sections.items() if section.status == "unavailable"]
        diagnosis = AShareDiagnosis(
            symbol=symbol,
            as_of=as_of,
            action="observe",
            overall_status="partial" if missing else "ready",
            sections=sections,
            missing_data=missing,
        )
        if self.research_repository is None or not persist:
            return diagnosis
        input_payload = {
            "symbol": symbol,
            "as_of": as_of.isoformat(),
            "bars": [bar.model_dump(mode="json") for bar in bars],
            "market": market.model_dump(mode="json") if market is not None else None,
            "market_error": market_error,
            "finance": finance.model_dump(mode="json") if finance is not None else None,
            "finance_error": finance_error,
            "events": [event.model_dump(mode="json") for event in events],
            "news_error": news_error,
            "factor_version": FACTOR_VERSION,
        }
        snapshot_id = self.research_repository.append_diagnosis(
            diagnosis, input_payload=input_payload
        )
        return self.research_repository.get_diagnosis(snapshot_id)

    async def _market(
        self, symbol: str, as_of: date, *, cutoff: datetime | None = None,
        degrade_authorization: bool = False,
    ) -> tuple[TencentMarketSnapshot | None, str | None]:
        try:
            snapshot = await self.market_source.fetch_snapshot(symbol)
            if snapshot.symbol != symbol:
                return None, "market snapshot symbol differs from requested symbol"
            if snapshot.observed_at.date() > as_of:
                return None, "market snapshot is later than diagnosis as_of"
            if cutoff is not None and snapshot.observed_at > cutoff:
                return None, "market snapshot is later than diagnosis cutoff"
            return snapshot, None
        except SourceAuthorizationError as error:
            if not degrade_authorization:
                raise
            return None, str(error)
        except Exception as error:
            return None, str(error)

    async def _finance(
        self, symbol: str, as_of: date, *, cutoff: datetime | None = None,
        degrade_authorization: bool = False,
    ) -> tuple[FundamentalSnapshot | None, str | None]:
        try:
            snapshot = await asyncio.to_thread(self.finance_source.fetch, symbol)
            if snapshot.symbol != symbol:
                return None, "finance snapshot symbol differs from requested symbol"
            if snapshot.observed_at.date() > as_of:
                return None, "finance snapshot is later than diagnosis as_of"
            if cutoff is not None and snapshot.observed_at > cutoff:
                return None, "finance snapshot is later than diagnosis cutoff"
            if snapshot.report_period is not None and snapshot.report_period > as_of:
                return None, "finance report period is later than diagnosis as_of"
            return snapshot, None
        except SourceAuthorizationError as error:
            if not degrade_authorization:
                raise
            return None, str(error)
        except Exception as error:
            return None, str(error)

    def _events(
        self, symbol: str, as_of: date, *, cutoff: datetime | None = None,
    ) -> tuple[list[NormalizedNewsEvent], str | None]:
        try:
            events = [
                event for event in self.news_repository.events()
                if (AssetKind.A_SHARE, symbol) in event.affected_instruments
                and event.normalized_at.date() <= as_of
                and (cutoff is None or event.normalized_at <= cutoff)
                and (cutoff is None or event.occurred_at <= cutoff)
                and event.review_state == "verified"
            ]
            return events, None
        except Exception as error:
            return [], str(error)

    def _sections(
        self,
        symbol: str,
        as_of: date,
        bars: list[DailyBar],
        market: TencentMarketSnapshot | None,
        market_error: str | None,
        finance: FundamentalSnapshot | None,
        finance_error: str | None,
        events: list[NormalizedNewsEvent],
        news_error: str | None,
    ) -> dict[str, DiagnosisSection]:
        sections: dict[str, DiagnosisSection] = {}
        sections["market"] = self._market_section(market, market_error)
        sections["valuation"] = self._valuation_section(market, market_error)
        sections.update(self._bar_sections(symbol, bars, as_of))
        sections["fundamentals"] = self._fundamental_section(finance, finance_error)
        sections.update(self._event_sections(events, news_error))
        risk_missing = [name for name, section in sections.items() if section.status == "unavailable"]
        sections["risk"] = DiagnosisSection(
            status="ready",
            observed_at=as_of,
            source="qibao-risk-v1",
            metrics={"missing_section_count": len(risk_missing), "symbol": symbol},
            explanation=(
                "存在缺失数据，仅保留观察结论。" if risk_missing
                else "诊断数据完整，仍不构成买卖建议。"
            ),
        )
        return sections

    @staticmethod
    def _market_section(
        market: TencentMarketSnapshot | None, error: str | None
    ) -> DiagnosisSection:
        if market is None:
            return _unavailable("tencent", f"实时行情不可用：{error}")
        change = market.price / market.previous_close - Decimal("1")
        return DiagnosisSection(
            status="ready", observed_at=market.observed_at, source=market.source,
            metrics={
                "name": market.name, "price": market.price,
                "change_percent": change * Decimal("100"),
                "turnover_rate": market.turnover_rate,
            },
            explanation="展示腾讯行情的当前价格、涨跌和换手率。",
        )

    @staticmethod
    def _valuation_section(
        market: TencentMarketSnapshot | None, error: str | None
    ) -> DiagnosisSection:
        if market is None:
            return _unavailable("tencent", f"估值行情不可用：{error}")
        metrics = {
            "pe_ttm": market.pe_ttm, "pb": market.pb,
            "market_cap_yi": market.market_cap_yi,
        }
        status = "ready" if any(value is not None for value in metrics.values()) else "unavailable"
        return DiagnosisSection(
            status=status, observed_at=market.observed_at, source=market.source,
            metrics=metrics,
            explanation=(
                "估值仅展示来源原值，不对缺失字段进行推算。"
                if status == "ready" else "腾讯未返回可用估值字段。"
            ),
        )

    @staticmethod
    def _bar_sections(
        symbol: str, bars: list[DailyBar], as_of: date
    ) -> dict[str, DiagnosisSection]:
        eligible = sorted(
            (bar for bar in bars if bar.trade_date <= as_of),
            key=lambda bar: bar.trade_date,
        )
        if len(eligible) < 20:
            unavailable = _unavailable("local-daily-bars", "本地日线不足 20 根。")
            return {"price_volume": unavailable, "trend": unavailable}
        if {bar.symbol for bar in eligible} != {symbol}:
            unavailable = _unavailable("local-daily-bars", "本地日线股票代码不一致。")
            return {"price_volume": unavailable, "trend": unavailable}
        if len({bar.trade_date for bar in eligible}) != len(eligible):
            unavailable = _unavailable("local-daily-bars", "本地日线包含重复交易日。")
            return {"price_volume": unavailable, "trend": unavailable}
        if len({bar.source for bar in eligible}) != 1:
            unavailable = _unavailable("local-daily-bars", "本地日线来源不一致。")
            return {"price_volume": unavailable, "trend": unavailable}
        latest = eligible[-1]
        average_amount = sum(
            (bar.amount for bar in eligible[-20:]), start=Decimal("0")
        ) / Decimal("20")
        average_volume = sum(
            (Decimal(bar.volume) for bar in eligible[-20:]), start=Decimal("0")
        ) / Decimal("20")
        volume_ratio = (
            Decimal(latest.volume) / average_volume if average_volume > 0 else None
        )
        price_volume = DiagnosisSection(
            status="ready", observed_at=latest.trade_date, source=latest.source,
            metrics={
                "close": latest.close,
                "return_5d": latest.close / eligible[-6].close - Decimal("1"),
                "average_amount_20d": average_amount,
                "volume_ratio": volume_ratio,
            },
            explanation="量价指标来自本地已冻结日线。",
        )
        try:
            factor = build_factor_snapshot(eligible, as_of)
        except (InsufficientHistoryError, ValueError) as error:
            trend = _unavailable("local-daily-bars", f"趋势计算不可用：{error}")
        else:
            trend = DiagnosisSection(
                status="ready", observed_at=as_of, source=factor.source,
                metrics={
                    "distance_ma20": factor.distance_ma20,
                    "return_20d": factor.return_20d,
                    "volatility_20d": factor.volatility_20d,
                    "drawdown_60d": factor.drawdown_60d,
                },
                explanation="趋势和风险指标只使用诊断日期及之前的日线。",
            )
        return {"price_volume": price_volume, "trend": trend}

    @staticmethod
    def _fundamental_section(
        finance: FundamentalSnapshot | None, error: str | None
    ) -> DiagnosisSection:
        if finance is None:
            return _unavailable("mootdx-finance", f"基本面数据不可用：{error}")
        financial_values = [
            finance.eps, finance.roe, finance.net_profit, finance.revenue,
            finance.book_value_per_share, finance.total_shares,
        ]
        if not any(value is not None for value in financial_values):
            return _unavailable("mootdx-finance", "通达信未返回可用基本面字段。")
        return DiagnosisSection(
            status="ready", observed_at=finance.observed_at, source=finance.source,
            metrics={
                "report_period": (
                    finance.report_period.isoformat()
                    if finance.report_period is not None else None
                ),
                "industry": finance.industry,
                "eps": finance.eps, "roe": finance.roe,
                "net_profit": finance.net_profit, "revenue": finance.revenue,
                "book_value_per_share": finance.book_value_per_share,
                "total_shares": finance.total_shares,
            },
            explanation="基本面字段来自通达信财务快照，缺失字段保持为空。",
        )

    @staticmethod
    def _event_sections(
        events: list[NormalizedNewsEvent], error: str | None
    ) -> dict[str, DiagnosisSection]:
        if error is not None:
            unavailable = _unavailable("news-repository", f"事件数据不可用：{error}")
            return {"events": unavailable, "industry": unavailable}
        event_ids = tuple(event.event_id for event in events)
        adverse_event_count = sum(
            1 for event in events
            if "risk" in event.event_type or "风险事件" in event.themes
        )
        industries = sorted({industry for event in events for industry in event.industries})
        observed_at = max((event.normalized_at for event in events), default=None)
        events_section = DiagnosisSection(
            status="ready", observed_at=observed_at, source="frozen-news-events",
            metrics={
                "event_count": len(events),
                "adverse_event_count": adverse_event_count,
            }, evidence_ids=event_ids,
            explanation="只展示冻结事件中明确关联该股票的记录。",
        )
        industry_section = DiagnosisSection(
            status="ready", observed_at=observed_at, source="frozen-news-events",
            metrics={"industries": "、".join(industries)}, evidence_ids=event_ids,
            explanation=(
                "行业标签来自已核验事件。" if industries else "当前没有已核验行业标签。"
            ),
        )
        return {"events": events_section, "industry": industry_section}
