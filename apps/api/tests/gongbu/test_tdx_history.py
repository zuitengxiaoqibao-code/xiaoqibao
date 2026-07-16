from datetime import date

import pandas as pd
import pytest

from qibao_api.gongbu.tdx_history import DataSourceUnavailable, TdxHistorySource


class FakeClient:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def bars(self, **kwargs) -> pd.DataFrame:
        assert kwargs == {"symbol": "600000", "frequency": 9, "start": 0, "offset": 20}
        return self.frame


def test_history_source_converts_rows_to_sorted_daily_bars() -> None:
    frame = pd.DataFrame(
        [
            {"open": 9.1, "high": 9.8, "low": 9.0, "close": 9.5, "vol": 1000, "amount": 9500, "datetime": "2026-07-13"},
            {"open": 8.8, "high": 9.2, "low": 8.7, "close": 9.0, "vol": 900, "amount": 8100, "datetime": "2026-07-12"},
        ]
    )

    bars = TdxHistorySource(FakeClient(frame)).fetch_daily("600000", 20)

    assert [bar.trade_date for bar in bars] == [date(2026, 7, 12), date(2026, 7, 13)]
    assert bars[0].source == "mootdx"


def test_history_source_rejects_empty_result() -> None:
    with pytest.raises(DataSourceUnavailable, match="no daily bars"):
        TdxHistorySource(FakeClient(pd.DataFrame())).fetch_daily("600000", 20)
