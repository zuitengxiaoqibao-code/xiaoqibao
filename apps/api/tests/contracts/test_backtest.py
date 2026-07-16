from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.contracts.backtest import BacktestRequest


def test_backtest_requires_fast_window_below_slow_window() -> None:
    with pytest.raises(ValidationError, match="fast_window"):
        BacktestRequest(fast_window=20, slow_window=10)


def test_backtest_requires_positive_initial_cash() -> None:
    with pytest.raises(ValidationError):
        BacktestRequest(initial_cash=Decimal("0"))
