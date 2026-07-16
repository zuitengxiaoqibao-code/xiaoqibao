from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from qibao_api.contracts.briefing import DailyBriefing, BriefingSections
from qibao_api.contracts.market import AssetKind


NOW = datetime(2026, 7, 14, 1, 30, tzinfo=UTC)


def test_daily_briefing_is_frozen_and_asset_aware() -> None:
    report = DailyBriefing(
        report_id="briefing-1", trading_date=date(2026, 7, 14), phase="premarket",
        generated_at=NOW, window_start=datetime(2026, 7, 13, 7, 0, tzinfo=UTC),
        window_end=datetime(2026, 7, 14, 1, 25, tzinfo=UTC),
        event_ids=("event-1",), interpretation_ids=("interpretation-1",),
        input_snapshot_hash="a" * 64,
        sections=BriefingSections(
            policy_event_ids=("event-1",), risk_event_ids=(),
            watchlist=((AssetKind.A_SHARE, "600000"),),
        ),
    )

    with pytest.raises(ValidationError):
        report.phase = "postclose"


def test_daily_briefing_rejects_invalid_windows_and_duplicate_inputs() -> None:
    values = dict(
        report_id="briefing-1", trading_date=date(2026, 7, 14), phase="premarket",
        generated_at=NOW, window_start=NOW, window_end=NOW,
        event_ids=("event-1", "event-1"), interpretation_ids=(),
        input_snapshot_hash="a" * 64, sections=BriefingSections(),
    )

    with pytest.raises(ValidationError):
        DailyBriefing(**values)
