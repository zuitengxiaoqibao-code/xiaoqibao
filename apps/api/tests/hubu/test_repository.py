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
    second = repository.record_risk_decision(decision)

    assert first == second == "risk-1"
    assert repository.get_risk_decision_for_order(order_id) == decision
    with pytest.raises(ValueError, match="conflicting risk decision"):
        repository.record_risk_decision(
            decision.model_copy(update={"decision_id": "risk-conflict", "reason_code": "different"})
        )


def test_risk_decisions_are_immutable(tmp_path) -> None:
    import sqlite3
    repository = PaperRepository(tmp_path / "paper.sqlite3")
    repository.create_account("paper-1", Decimal("100000"))
    order_id = repository.create_order("paper-1", OrderRequest(client_order_id="immutable", symbol="600000", side="buy", shares=100))
    from datetime import datetime, timezone
    from qibao_api.contracts.market import AssetKind
    from qibao_api.contracts.risk import RiskDecision
    decision = RiskDecision(
        decision_id="risk-immutable", order_id=order_id, symbol="600000",
        asset=AssetKind.A_SHARE, outcome="reject", reason_code="risk_unavailable",
        evidence=("exception_type:RuntimeError",), rule_id="system_availability",
        rule_version="availability.1", decided_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )
    repository.record_risk_decision(decision)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        repository.connection.execute("UPDATE paper_risk_decisions SET outcome = 'approve'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        repository.connection.execute("DELETE FROM paper_risk_decisions")


def test_legacy_risk_schema_migrates_transactionally_and_accepts_new_decisions(tmp_path) -> None:
    import sqlite3
    database = tmp_path / "paper.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE paper_accounts (account_id TEXT PRIMARY KEY, initial_cash TEXT, cash TEXT, created_at TEXT);
        CREATE TABLE paper_orders (order_id TEXT PRIMARY KEY, account_id TEXT, client_order_id TEXT, symbol TEXT, side TEXT, shares INTEGER, status TEXT, rejection_reason TEXT, created_at TEXT, UNIQUE(account_id, client_order_id));
        CREATE TABLE paper_risk_decisions (decision_id TEXT PRIMARY KEY, order_id TEXT UNIQUE, approved INTEGER, reasons TEXT, created_at TEXT);
        INSERT INTO paper_accounts VALUES ('paper-1', '100000', '100000', '2026-07-13T00:00:00+00:00');
        INSERT INTO paper_orders VALUES ('order-old', 'paper-1', 'old', '600000', 'buy', 100, 'rejected', 'risk_rejected', '2026-07-13T01:00:00+00:00');
        INSERT INTO paper_risk_decisions VALUES ('risk-old', 'order-old', 0, '["legacy_limit"]', '2026-07-13T01:00:01+00:00');
    """)
    connection.close()

    repository = PaperRepository(database)
    migrated = repository.get_risk_decision_for_order("order-old")
    assert migrated.outcome == "reject"
    assert migrated.reason_code == "legacy_risk_rejected"
    assert "legacy_reason:legacy_limit" in migrated.evidence
    repository.close()

    reopened = PaperRepository(database)
    order_id = reopened.create_order("paper-1", OrderRequest(client_order_id="new", symbol="000001", side="buy", shares=100))
    decision = migrated.model_copy(update={"decision_id": "risk-new", "order_id": order_id, "symbol": "000001"})
    assert reopened.record_risk_decision(decision) == "risk-new"
    reopened.close()
