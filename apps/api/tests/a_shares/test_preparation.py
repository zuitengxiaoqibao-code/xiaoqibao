from datetime import datetime, timezone

from qibao_api.a_shares.preparation import PreparationSource, StockPreparation


def test_preparation_result_keeps_typed_source_state():
    now = datetime(2026, 7, 16, 3, tzinfo=timezone.utc)
    result = StockPreparation(
        symbol="600519",
        status="partial",
        sources=(
            PreparationSource(
                name="history", status="partial", reason="history offline"
            ),
        ),
        refreshed=True,
        started_at=now,
        completed_at=now,
    )

    assert result.sources[0].reason == "history offline"
