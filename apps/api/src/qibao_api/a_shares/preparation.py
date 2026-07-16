import asyncio
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict


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


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("x+b") as created:
                created.write(b"0")
        except FileExistsError:
            pass
        self.handle = self.path.open("r+b")
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)

    def release(self) -> None:
        if self.handle is None:
            return
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


class AStockPreparationService:
    def __init__(
        self,
        bar_repository,
        market_data_service,
        diagnosis_service,
        news_service,
        news_repository,
        trading_calendar,
        *,
        lock_dir: Path,
        clock: Callable[[], datetime] | None = None,
        news_cooldown_seconds: int = 300,
    ) -> None:
        self.bar_repository = bar_repository
        self.market_data_service = market_data_service
        self.diagnosis_service = diagnosis_service
        self.news_service = news_service
        self.news_repository = news_repository
        self.trading_calendar = trading_calendar
        self.lock_dir = Path(lock_dir)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.news_cooldown_seconds = news_cooldown_seconds
        self._active_locks = 0

    async def inspect(
        self, symbol: str, *, as_of: date, cutoff: datetime | None = None
    ) -> StockPreparation:
        started_at = self._now()
        return await self._inspect(
            symbol, as_of, cutoff, started_at=started_at, refreshed=False
        )

    async def prepare(
        self, symbol: str, *, as_of: date, cutoff: datetime | None = None
    ) -> StockPreparation:
        if cutoff is not None:
            return await self.inspect(symbol, as_of=as_of, cutoff=cutoff)
        started_at = self._now()
        refreshed = False
        history_error = None
        async with self._file_lock(f"history-{symbol}.lock"):
            bars = self._bars(symbol, as_of, None)
            expected = self._expected_trading_day(as_of)
            if not self._history_ready(bars, expected):
                refreshed = True
                try:
                    report = await asyncio.to_thread(
                        self.market_data_service.sync_symbol, symbol
                    )
                    state = getattr(report.state, "value", report.state)
                    if state != "ready":
                        history_error = (
                            getattr(report, "message", None) or "history sync failed"
                        )
                except Exception as error:
                    history_error = str(error)

        news_refreshed, news_error = await self._refresh_news()
        refreshed = refreshed or news_refreshed
        return await self._inspect(
            symbol,
            as_of,
            None,
            started_at=started_at,
            refreshed=refreshed,
            history_error=history_error,
            news_error=news_error,
        )

    async def _inspect(
        self,
        symbol,
        as_of,
        cutoff,
        *,
        started_at,
        refreshed,
        history_error=None,
        news_error=None,
    ):
        bars = self._bars(symbol, as_of, cutoff)
        expected = self._expected_trading_day(as_of)
        sources = [self._history_source(bars, expected, history_error)]
        sources.extend(await self._diagnosis_sources(symbol, as_of, cutoff))
        sources.append(self._news_source(symbol, as_of, cutoff, news_error))
        ordered = tuple(
            next(source for source in sources if source.name == name)
            for name in ("quote", "history", "finance", "news")
        )
        return StockPreparation(
            symbol=symbol,
            status=(
                "partial" if any(item.status == "partial" for item in ordered)
                else "ready"
            ),
            sources=ordered,
            refreshed=refreshed,
            started_at=started_at,
            completed_at=self._now(),
        )

    async def _refresh_news(self):
        error = None
        refreshed = False
        async with self._file_lock("news-global.lock"):
            if not self._news_is_fresh():
                refreshed = True
                try:
                    await self.news_service.sync()
                    self._news_marker().write_text(
                        self._now().isoformat(), encoding="utf-8"
                    )
                except Exception as error_value:
                    error = str(error_value)
        return refreshed, error

    async def _diagnosis_sources(self, symbol, as_of, cutoff):
        try:
            checks = await self.diagnosis_service.inspect_sources(
                symbol, as_of, cutoff=cutoff
            )
        except Exception as error:
            checks = {"quote": (None, str(error)), "finance": (None, str(error))}
        return [
            PreparationSource(
                name=name,
                status="ready" if value is not None and error is None else "partial",
                observed_at=self._aware(getattr(value, "observed_at", None)),
                reason=error,
            )
            for name, (value, error) in checks.items()
            if name in {"quote", "finance"}
        ]

    def _news_source(self, symbol, as_of, cutoff, refresh_error):
        try:
            events = [
                event for event in self.news_repository.events_for_symbol(
                    symbol, cutoff=cutoff
                )
                if event.normalized_at.date() <= as_of
            ]
        except Exception as error:
            events = []
            refresh_error = str(error)
        observed_at = max(
            (self._aware(event.normalized_at) for event in events), default=None
        )
        live_unfresh = cutoff is None and not self._news_is_fresh()
        reason = refresh_error or ("news_not_fresh" if live_unfresh else None)
        return PreparationSource(
            name="news",
            status="partial" if reason else "ready",
            observed_at=observed_at,
            reason=reason,
        )

    def _bars(self, symbol, as_of, cutoff):
        if cutoff is None:
            return self.bar_repository.latest_many([symbol], 120, as_of).get(symbol, [])
        return self.bar_repository.latest_many(
            [symbol], 120, as_of, cutoff=cutoff
        ).get(symbol, [])

    def _expected_trading_day(self, as_of):
        now = self._now().astimezone(ZoneInfo("Asia/Shanghai"))
        if (
            as_of == now.date()
            and self.trading_calendar.is_trading_day(as_of)
            and now.time() < time(15, 0)
        ):
            return self.trading_calendar.previous_trading_day(as_of)
        if self.trading_calendar.is_trading_day(as_of):
            return as_of
        return self.trading_calendar.previous_trading_day(as_of)

    @staticmethod
    def _history_ready(bars, expected):
        return len(bars) >= 60 and bool(bars) and bars[-1].trade_date >= expected

    def _history_source(self, bars, expected, sync_error):
        ready = self._history_ready(bars, expected)
        latest = bars[-1].trade_date if bars else None
        return PreparationSource(
            name="history",
            status="ready" if ready else "partial",
            observed_at=(
                datetime.combine(latest, time.min, tzinfo=timezone.utc)
                if latest is not None else None
            ),
            reason=(
                sync_error
                or (None if ready else "history requires 60 bars through confirmed day")
            ),
        )

    def _news_marker(self):
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        return self.lock_dir / "news-success.txt"

    def _news_is_fresh(self):
        try:
            refreshed_at = datetime.fromisoformat(
                self._news_marker().read_text(encoding="utf-8")
            )
            return (self._now() - refreshed_at).total_seconds() < self.news_cooldown_seconds
        except (OSError, ValueError):
            return False

    @asynccontextmanager
    async def _file_lock(self, name):
        lock = _FileLock(self.lock_dir / name)
        await asyncio.to_thread(lock.acquire)
        self._active_locks += 1
        try:
            yield
        finally:
            self._active_locks -= 1
            await asyncio.to_thread(lock.release)

    def _now(self):
        return self._aware(self.clock()) or datetime.now(timezone.utc)

    @staticmethod
    def _aware(value):
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
