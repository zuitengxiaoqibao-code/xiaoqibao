from datetime import date, datetime

import pytest

from qibao_api.shangshu.trading_calendar import (
    ExchangeCalendarsTradingDaySchedule,
    StoredTradingCalendar,
    TencentIndexTradingDaySignal,
)


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


def test_calendar_accepts_today_when_live_index_confirms_open_market() -> None:
    signal = type("Signal", (), {"confirmed_date": lambda self: date(2026, 7, 15)})()
    calendar = StoredTradingCalendar(Bars(), live_signal=signal)

    assert calendar.is_trading_day(date(2026, 7, 15)) is True
    assert calendar.previous_trading_day(date(2026, 7, 15)) == date(2026, 7, 14)


def test_calendar_fails_closed_when_live_signal_is_unavailable() -> None:
    signal = type("Signal", (), {"confirmed_date": lambda self: None})()

    assert StoredTradingCalendar(Bars(), live_signal=signal).is_trading_day(
        date(2026, 7, 15)
    ) is False


def test_exchange_calendar_confirms_premarket_session_and_national_day() -> None:
    schedule = ExchangeCalendarsTradingDaySchedule()

    assert schedule.is_trading_day(date(2026, 7, 17)) is True
    assert schedule.is_trading_day(date(2026, 10, 1)) is False
    assert schedule.is_trading_day(date(2027, 1, 4)) is None


class Response:
    content = (
        'v_sh000001="1~上证指数~000001~3500.00~3490.00~3501.00~123~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~20260715130630~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0";'
    ).encode("gbk")

    def raise_for_status(self) -> None:
        return None


class Client:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, _url):
        self.calls += 1
        return Response()


def test_tencent_index_signal_confirms_payload_date_and_caches() -> None:
    client = Client()
    signal = TencentIndexTradingDaySignal(
        client,
        clock=lambda: datetime(2026, 7, 15, 13, 6, 45),
        cache_seconds=60,
    )

    assert signal.confirmed_date() == date(2026, 7, 15)
    assert signal.confirmed_date() == date(2026, 7, 15)
    assert client.calls == 1
