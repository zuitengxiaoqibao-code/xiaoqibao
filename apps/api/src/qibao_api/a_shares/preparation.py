import asyncio
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from qibao_api.contracts.market import AssetKind


class PreparationSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: Literal["quote", "history", "finance", "news"]
    status: Literal["ready", "partial"]
    observed_at: AwareDatetime | None = None
    reason: str | None = None


class StockPreparation(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    status: Literal["ready", "partial"]
    sources: tuple[PreparationSource, ...]
    refreshed: bool
    started_at: AwareDatetime
    completed_at: AwareDatetime


class AStockPreparationService:
    def __init__(
        self,
        bar_repository,
        market_data_service,
        diagnosis_service,
        news_service,
        news_repository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.bar_repository = bar_repository
        self.market_data_service = market_data_service
        self.diagnosis_service = diagnosis_service
        self.news_service = news_service
        self.news_repository = news_repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._locks: dict[tuple[str, date, datetime | None], asyncio.Lock] = {}
        self._completed: dict[
            tuple[str, date, datetime | None], tuple[tuple[int, date | None], StockPreparation]
        ] = {}

    async def prepare(
        self, symbol: str, *, as_of: date, cutoff: datetime | None = None
    ) -> StockPreparation:
        key = (symbol, as_of, cutoff)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            bars = self._bars(symbol, as_of, cutoff)
            version = self._history_version(bars)
            cached = self._completed.get(key)
            if cached is not None and cached[0] == version:
                return cached[1].model_copy(update={"refreshed": False})

            started_at = self._now()
            live = cutoff is None
            history_reason = None
            if live and (len(bars) < 60 or not bars or bars[-1].trade_date < as_of):
                try:
                    report = await asyncio.to_thread(
                        self.market_data_service.sync_symbol, symbol
                    )
                    state = getattr(report.state, "value", report.state)
                    if state != "ready":
                        history_reason = (
                            getattr(report, "message", None) or "history sync failed"
                        )
                except Exception as error:
                    history_reason = str(error)
                bars = self._bars(symbol, as_of, None)

            sources = [self._history_source(bars, as_of, history_reason)]
            sources.extend(await self._diagnosis_sources(symbol, as_of, cutoff))
            sources.append(await self._news_source(symbol, as_of, cutoff, live))
            ordered = tuple(
                next(source for source in sources if source.name == name)
                for name in ("quote", "history", "finance", "news")
            )
            result = StockPreparation(
                symbol=symbol,
                status=(
                    "partial" if any(item.status == "partial" for item in ordered)
                    else "ready"
                ),
                sources=ordered,
                refreshed=live,
                started_at=started_at,
                completed_at=self._now(),
            )
            self._completed[key] = (self._history_version(bars), result)
            return result

    def _bars(self, symbol: str, as_of: date, cutoff: datetime | None):
        if cutoff is None:
            return self.bar_repository.latest_many([symbol], 120, as_of).get(symbol, [])
        return self.bar_repository.latest_many(
            [symbol], 120, as_of, cutoff=cutoff
        ).get(symbol, [])

    @staticmethod
    def _history_version(bars) -> tuple[int, date | None]:
        return len(bars), bars[-1].trade_date if bars else None

    @staticmethod
    def _history_source(bars, as_of: date, sync_error: str | None):
        sufficient = len(bars) >= 60 and bars[-1].trade_date >= as_of
        latest = bars[-1].trade_date if bars else None
        reason = sync_error
        if reason is None and not sufficient:
            reason = "history requires 60 bars including the latest trading day"
        return PreparationSource(
            name="history",
            status="ready" if sufficient else "partial",
            observed_at=(
                datetime.combine(latest, time.min, tzinfo=timezone.utc)
                if latest is not None else None
            ),
            reason=reason,
        )

    async def _diagnosis_sources(self, symbol, as_of, cutoff):
        results = []
        for name, method in (
            ("quote", self.diagnosis_service._market),
            ("finance", self.diagnosis_service._finance),
        ):
            try:
                snapshot, error = await method(
                    symbol, as_of, cutoff=cutoff, degrade_authorization=True
                )
            except Exception as error_value:
                snapshot, error = None, str(error_value)
            results.append(PreparationSource(
                name=name,
                status="ready" if snapshot is not None and error is None else "partial",
                observed_at=self._aware(getattr(snapshot, "observed_at", None)),
                reason=error,
            ))
        return results

    async def _news_source(self, symbol, as_of, cutoff, live):
        error = None
        if live:
            try:
                await self.news_service.sync()
            except Exception as error_value:
                error = str(error_value)
        try:
            events = [
                event for event in self.news_repository.events()
                if (AssetKind.A_SHARE, symbol) in getattr(
                    event, "affected_instruments", ()
                )
                and getattr(event, "review_state", None) == "verified"
                and event.normalized_at.date() <= as_of
                and (cutoff is None or event.normalized_at <= cutoff)
                and (cutoff is None or event.occurred_at <= cutoff)
            ]
        except Exception as error_value:
            events = []
            error = str(error_value)
        observed_at = max(
            (self._aware(event.normalized_at) for event in events), default=None
        )
        return PreparationSource(
            name="news",
            status="partial" if error is not None else "ready",
            observed_at=observed_at,
            reason=error,
        )

    def _now(self) -> datetime:
        return self._aware(self.clock()) or datetime.now(timezone.utc)

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
