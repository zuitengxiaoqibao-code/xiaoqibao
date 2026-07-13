from datetime import date
from decimal import Decimal

from qibao_api.contracts.bars import DailyBar, DataSourceState
from qibao_api.gongbu.data_service import FallbackHistorySource, MarketDataService


def make_bar(source: str = "baidu") -> DailyBar:
    return DailyBar(
        symbol="600000", trade_date=date(2026, 7, 13), open=Decimal("9.04"),
        high=Decimal("9.21"), low=Decimal("9.01"), close=Decimal("9.19"),
        volume=75761962, amount=Decimal("693325381"), source=source,
    )


class FailingSource:
    def fetch_daily(self, symbol: str, limit: int):
        raise TimeoutError("primary timeout")


class StaticSource:
    def fetch_daily(self, symbol: str, limit: int):
        return [make_bar()]


class RecordingRepository:
    def __init__(self, tmp_path) -> None:
        self.rows = []
        self.path = tmp_path / "600000.parquet"

    def upsert(self, bars) -> None:
        self.rows.extend(bars)

    def export_parquet(self, symbol: str):
        self.path.touch()
        return self.path


def test_fallback_uses_backup_after_primary_failure() -> None:
    bars = FallbackHistorySource([FailingSource(), StaticSource()]).fetch_daily("600000", 20)
    assert bars[0].source == "baidu"


def test_sync_report_uses_actual_source(tmp_path) -> None:
    report = MarketDataService(StaticSource(), RecordingRepository(tmp_path)).sync_symbol("600000", 20)
    assert report.state == DataSourceState.READY
    assert report.source == "baidu"
    assert report.written_rows == 1


def test_sync_report_exposes_source_failure(tmp_path) -> None:
    report = MarketDataService(FailingSource(), RecordingRepository(tmp_path)).sync_symbol("600000", 20)
    assert report.state == DataSourceState.ERROR
    assert report.written_rows == 0
    assert "primary timeout" in report.message
