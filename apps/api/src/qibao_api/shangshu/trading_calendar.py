from datetime import date


class StoredTradingCalendar:
    def __init__(self, bar_repository) -> None:
        self.bar_repository = bar_repository

    def is_trading_day(self, value: date) -> bool:
        return value in self.bar_repository.trade_dates(limit=1000)

    def previous_trading_day(self, value: date) -> date:
        candidates = [
            item for item in self.bar_repository.trade_dates(limit=1000) if item < value
        ]
        if not candidates:
            raise ValueError(f"no confirmed trading day exists before {value}")
        return max(candidates)
