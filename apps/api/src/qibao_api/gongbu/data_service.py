from datetime import datetime
from typing import Protocol

from qibao_api.contracts.bars import DailyBar, DataSourceState, SyncReport
from qibao_api.gongbu.tdx_history import DataSourceUnavailable


class HistorySource(Protocol):
    def fetch_daily(self, symbol: str, limit: int) -> list[DailyBar]: ...


class BarStore(Protocol):
    def upsert(self, bars: list[DailyBar]) -> None: ...
    def export_parquet(self, symbol: str): ...


class FallbackHistorySource:
    def __init__(self, sources: list[HistorySource]) -> None:
        self.sources = sources

    def fetch_daily(self, symbol: str, limit: int = 250) -> list[DailyBar]:
        errors: list[str] = []
        for source in self.sources:
            try:
                bars = source.fetch_daily(symbol, limit)
                if bars:
                    return bars
            except Exception as error:
                errors.append(f"{source.__class__.__name__}: {error}")
        raise DataSourceUnavailable("; ".join(errors) or "no history sources configured")


class MarketDataService:
    def __init__(self, source: HistorySource, repository: BarStore) -> None:
        self.source = source
        self.repository = repository

    def sync_symbol(self, symbol: str, limit: int = 250) -> SyncReport:
        started_at = datetime.now()
        try:
            bars = self.source.fetch_daily(symbol, limit)
            self.repository.upsert(bars)
            parquet_path = self.repository.export_parquet(symbol)
            return SyncReport(
                symbol=symbol,
                state=DataSourceState.READY,
                written_rows=len(bars),
                source=bars[0].source,
                parquet_path=str(parquet_path),
                started_at=started_at,
                finished_at=datetime.now(),
                message="同步完成",
            )
        except Exception as error:
            return SyncReport(
                symbol=symbol,
                state=DataSourceState.ERROR,
                written_rows=0,
                source="history-fallback",
                started_at=started_at,
                finished_at=datetime.now(),
                message=str(error),
            )
