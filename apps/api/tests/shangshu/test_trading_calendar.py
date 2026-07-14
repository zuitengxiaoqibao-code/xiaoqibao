from datetime import date

import pytest

from qibao_api.shangshu.trading_calendar import StoredTradingCalendar


class Bars:
    def trade_dates(self, limit=1000):
        return [date(2026, 7, 14), date(2026, 7, 11), date(2026, 7, 10)]


def test_calendar_uses_confirmed_local_market_dates() -> None:
    calendar = StoredTradingCalendar(Bars())

    assert calendar.is_trading_day(date(2026, 7, 14)) is True
    assert calendar.is_trading_day(date(2026, 7, 13)) is False
    assert calendar.previous_trading_day(date(2026, 7, 14)) == date(2026, 7, 11)


def test_calendar_fails_when_prior_market_data_is_missing() -> None:
    calendar = StoredTradingCalendar(type("Empty", (), {"trade_dates": lambda self, limit=1000: []})())

    with pytest.raises(ValueError, match="confirmed trading day"):
        calendar.previous_trading_day(date(2026, 7, 14))
