from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

from qibao_api.bingbu.paper_broker import PaperBroker
from qibao_api.contracts.market import AssetKind, DataQuality, Quote
from qibao_api.contracts.trading import OrderRequest
from qibao_api.hubu.repository import PaperRepository


def test_concurrent_retry_only_fills_order_once(tmp_path) -> None:
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    broker = PaperBroker(repository)
    request = OrderRequest(
        client_order_id="same-client-order",
        symbol="600000",
        side="buy",
        shares=100,
    )
    market_quote = Quote(
        symbol="600000",
        asset=AssetKind.A_SHARE,
        name="浦发银行",
        price=Decimal("10"),
        previous_close=Decimal("10"),
        observed_at=datetime(2026, 7, 13, 10, 30),
        source="tencent",
        quality=DataQuality.FRESH,
    )

    def submit():
        return broker.submit(
            account_id="paper-1",
            request=request,
            quote=market_quote,
            risk_decision_id="risk-1",
            risk_approved=True,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))

    assert all(result.status == "filled" for result in results)
    assert repository.get_account("paper-1").cash == Decimal("98994.5000")
    assert repository.list_positions("paper-1")[0].shares == 100
