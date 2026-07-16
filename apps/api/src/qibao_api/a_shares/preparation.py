import asyncio
import os
import time as monotonic_time
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4
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


class PreparationLockTimeout(TimeoutError):
    pass


class _FileLock:
    def __init__(
        self, path: Path, *, timeout_seconds: float, retry_seconds: float
    ) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.retry_seconds = retry_seconds
        self.handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("x+b") as created:
                created.write(b"0")
        except FileExistsError:
            pass
        except PermissionError:
            if not self.path.exists():
                raise
        self.handle = self.path.open("r+b")
        self.handle.seek(0)
        deadline = monotonic_time.monotonic() + self.timeout_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(
                        self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                    )
                return
            except (BlockingIOError, OSError):
                if monotonic_time.monotonic() >= deadline:
                    self.handle.close()
                    self.handle = None
                    raise PreparationLockTimeout(
                        f"preparation lock timed out: {self.path.name}"
                    )
                monotonic_time.sleep(self.retry_seconds)

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
        lock_timeout_seconds: float = 5.0,
        lock_retry_seconds: float = 0.01,
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
        self.lock_timeout_seconds = lock_timeout_seconds
        self.lock_retry_seconds = lock_retry_seconds
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
        try:
            async with self._file_lock(f"prepare-{symbol}.lock"):
                return await self._prepare_locked(symbol, as_of, started_at)
        except PreparationLockTimeout as error:
            reason = str(error)
            return await self._inspect(
                symbol,
                as_of,
                None,
                started_at=started_at,
                refreshed=False,
                history_error=reason,
                news_error=reason,
            )

    async def _prepare_locked(self, symbol, as_of, started_at):
        refreshed = False
        history_error = None
        try:
            async with self._file_lock(f"history-{symbol}.lock"):
                bars = self._bars(symbol, as_of, None)
                before = self._bar_version(bars)
                expected = await self._expected_trading_day(as_of)
                if not self._history_ready(bars, expected):
                    try:
                        report = await asyncio.to_thread(
                            self.market_data_service.sync_symbol, symbol
                        )
                        state = getattr(report.state, "value", report.state)
                        if state != "ready":
                            history_error = (
                                getattr(report, "message", None)
                                or "history sync failed"
                            )
                        else:
                            after = self._bars(symbol, as_of, None)
                            refreshed = self._history_write_succeeded(
                                report, before, self._bar_version(after)
                            )
                    except Exception as error:
                        history_error = str(error)
        except PreparationLockTimeout as error:
            history_error = str(error)

        news_refreshed, news_error = await self._refresh_news(symbol)
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

    @staticmethod
    def _bar_version(bars):
        return tuple(
            (
                bar.model_dump_json()
                if hasattr(bar, "model_dump_json")
                else tuple(sorted(vars(bar).items()))
            )
            for bar in bars
        )

    @staticmethod
    def _history_write_succeeded(report, before, after):
        written_rows = getattr(report, "written_rows", None)
        return (written_rows is not None and written_rows > 0) or after != before

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
        expected = await self._expected_trading_day(as_of)
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

    async def _refresh_news(self, symbol):
        errors = []
        refreshed = False
        try:
            async with self._file_lock("news-global.lock"):
                if not self._news_is_fresh(self._global_news_marker()):
                    try:
                        await self.news_service.sync()
                        self._write_news_marker(
                            self._global_news_marker(), self._now()
                        )
                        refreshed = True
                    except Exception as error_value:
                        errors.append(str(error_value))
        except PreparationLockTimeout as error_value:
            errors.append(str(error_value))
        try:
            async with self._file_lock(f"news-{symbol}.lock"):
                marker = self._symbol_news_marker(symbol)
                if not self._news_is_fresh(marker):
                    try:
                        await self.news_service.sync_symbol(symbol)
                        self._write_news_marker(marker, self._now())
                        refreshed = True
                    except Exception as error_value:
                        errors.append(str(error_value))
        except PreparationLockTimeout as error_value:
            errors.append(str(error_value))
        return refreshed, "; ".join(dict.fromkeys(errors)) or None

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
        reason = refresh_error or (
            "news_no_verified_symbol_events" if not events else None
        )
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

    async def _expected_trading_day(self, as_of):
        return await asyncio.to_thread(self._expected_trading_day_sync, as_of)

    def _expected_trading_day_sync(self, as_of):
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
        ready = self._history_ready(bars, expected) and sync_error is None
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

    def _global_news_marker(self):
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        return self.lock_dir / "news-success.txt"

    def _symbol_news_marker(self, symbol: str):
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        return self.lock_dir / f"news-{symbol}-success.txt"

    def _write_news_marker(self, marker: Path, refreshed_at: datetime) -> None:
        temporary = marker.with_name(f".{marker.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(refreshed_at.isoformat())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, marker)
        finally:
            temporary.unlink(missing_ok=True)

    def _news_is_fresh(self, marker: Path):
        try:
            refreshed_at = datetime.fromisoformat(
                marker.read_text(encoding="utf-8")
            )
            return (self._now() - refreshed_at).total_seconds() < self.news_cooldown_seconds
        except (OSError, ValueError):
            return False

    @asynccontextmanager
    async def _file_lock(self, name):
        lock = _FileLock(
            self.lock_dir / name,
            timeout_seconds=self.lock_timeout_seconds,
            retry_seconds=self.lock_retry_seconds,
        )
        acquisition = asyncio.create_task(asyncio.to_thread(lock.acquire))
        acquired = False
        try:
            await asyncio.shield(acquisition)
            acquired = True
        except asyncio.CancelledError:
            loop = asyncio.get_running_loop()

            def release_if_acquired(completed):
                if not completed.cancelled() and completed.exception() is None:
                    loop.create_task(asyncio.to_thread(lock.release))

            acquisition.add_done_callback(release_if_acquired)
            raise
        self._active_locks += 1
        try:
            yield
        finally:
            self._active_locks -= 1
            if acquired:
                await asyncio.shield(asyncio.to_thread(lock.release))

    def _now(self):
        return self._aware(self.clock()) or datetime.now(timezone.utc)

    @staticmethod
    def _aware(value):
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
