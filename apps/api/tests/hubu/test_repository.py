from datetime import datetime
from decimal import Decimal

import pytest

from qibao_api.contracts.trading import Fill, OrderRequest
from qibao_api.hubu.repository import PaperRepository


def make_fill(fill_id: str = "fill-1") -> Fill:
    return Fill(
        fill_id=fill_id,
        order_id="order-1",
        symbol="600000",
        side="buy",
        shares=100,
        price=Decimal("10"),
        gross_amount=Decimal("1000"),
        commission=Decimal("5"),
        slippage=Decimal("0"),
        quote_source="tencent",
        quote_observed_at=datetime(2026, 7, 13, 10, 30),
        risk_decision_id="risk-1",
        filled_at=datetime(2026, 7, 13, 10, 30, 1),
    )


def test_repository_recovers_account_order_and_ledger_after_restart(tmp_path) -> None:
    database = tmp_path / "paper.sqlite3"
    repository = PaperRepository(database)
    repository.create_account("paper-1", Decimal("100000"))
    order_id = repository.create_order(
        "paper-1",
        OrderRequest(
            client_order_id="client-1",
            symbol="600000",
            side="buy",
            shares=100,
        ),
    )
    repository.apply_fill("paper-1", make_fill(), order_id=order_id)
    repository.close()

    recovered = PaperRepository(database)
    account = recovered.get_account("paper-1")

    assert account.cash == Decimal("98995")
    assert recovered.list_positions("paper-1")[0].shares == 100
    assert sum(entry.amount for entry in recovered.list_ledger("paper-1")) == Decimal("98995")


def test_client_order_id_is_idempotent(tmp_path) -> None:
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    request = OrderRequest(
        client_order_id="same-request",
        symbol="600000",
        side="buy",
        shares=100,
    )

    first = repository.create_order("paper-1", request)
    second = repository.create_order("paper-1", request)

    assert first == second
    assert len(repository.list_orders("paper-1")) == 1


def test_fill_rolls_back_cash_and_position_when_ledger_write_fails(tmp_path) -> None:
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    order_id = repository.create_order(
        "paper-1",
        OrderRequest(
            client_order_id="client-1",
            symbol="600000",
            side="buy",
            shares=100,
        ),
    )

    with pytest.raises(RuntimeError, match="simulated ledger failure"):
        repository.apply_fill(
            "paper-1",
            make_fill(),
            order_id=order_id,
            fail_before_ledger=True,
        )

    assert repository.get_account("paper-1").cash == Decimal("100000")
    assert repository.list_positions("paper-1") == []
    assert repository.get_order(order_id)["status"] == "pending"


def test_allocation_settings_are_stored_per_account(tmp_path) -> None:
    database = tmp_path / "paper.sqlite3"
    repository = PaperRepository(database)
    repository.create_account("paper-1", Decimal("100000"))
    repository.update_allocation_settings(
        "paper-1",
        single_position_cap=Decimal("0.15"),
        total_exposure_cap=Decimal("0.70"),
    )
    repository.close()

    recovered = PaperRepository(database)

    assert recovered.get_allocation_settings("paper-1") == (
        Decimal("0.15"),
        Decimal("0.70"),
    )


def test_risk_decision_is_idempotent_for_same_order(tmp_path) -> None:
    from datetime import datetime, timezone
    from qibao_api.contracts.market import AssetKind
    from qibao_api.contracts.risk import RiskDecision
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    order_id = repository.create_order(
        "paper-1",
        OrderRequest(
            client_order_id="client-risk",
            symbol="600000",
            side="buy",
            shares=100,
        ),
    )

    decision = RiskDecision(
        decision_id="risk-1", order_id=order_id, symbol="600000",
        asset=AssetKind.A_SHARE, outcome="observe_only",
        reason_code="industry_liquidity_data_missing", evidence=("order:client-risk",),
        rule_id="complete_order_review", rule_version="2026-07-13.1",
        decided_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )
    first = repository.record_risk_decision(decision)
    second = repository.record_risk_decision(decision.model_copy(update={"decision_id": "risk-2"}))

    assert first == second == "risk-1"
    assert repository.get_risk_decision_for_order(order_id) == decision
