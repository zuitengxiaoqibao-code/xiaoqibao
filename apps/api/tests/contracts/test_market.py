from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from qibao_api.contracts.market import AssetKind, DataQuality, Quote


def test_quote_rejects_negative_price() -> None:
    with pytest.raises(ValidationError):
        Quote(
            symbol="600000",
            asset=AssetKind.A_SHARE,
            name="浦发银行",
            price=Decimal("-1"),
            previous_close=Decimal("10"),
            observed_at=datetime(2026, 7, 13, 10, 30),
            source="tencent",
            quality=DataQuality.FRESH,
        )
