import sqlite3
import json
from datetime import datetime, timezone
from decimal import Decimal
from functools import wraps
from pathlib import Path
from threading import RLock
from uuid import uuid4

from qibao_api.contracts.trading import Fill, LedgerEntry, OrderRequest, PaperAccount, Position
from qibao_api.contracts.risk import RiskDecision
from qibao_api.hubu.schema import SCHEMA


def synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class PaperRepository:
    def __init__(self, database: str | Path) -> None:
        self._lock = RLock()
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self._migrate_legacy_risk_decisions()
        self._ensure_risk_decision_triggers()

    def _ensure_risk_decision_triggers(self) -> None:
        self.connection.executescript("""
            CREATE TRIGGER IF NOT EXISTS paper_risk_decisions_no_update
            BEFORE UPDATE ON paper_risk_decisions BEGIN
                SELECT RAISE(ABORT, 'paper risk decisions are immutable');
            END;
            CREATE TRIGGER IF NOT EXISTS paper_risk_decisions_no_delete
            BEFORE DELETE ON paper_risk_decisions BEGIN
                SELECT RAISE(ABORT, 'paper risk decisions are immutable');
            END;
        """)

    def _migrate_legacy_risk_decisions(self) -> None:
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(paper_risk_decisions)")
        }
        if "approved" not in columns:
            return
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute(
                "ALTER TABLE paper_risk_decisions RENAME TO paper_risk_decisions_legacy"
            )
            self.connection.execute("""CREATE TABLE paper_risk_decisions (
                decision_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL UNIQUE REFERENCES paper_orders(order_id),
                symbol TEXT NOT NULL, asset TEXT NOT NULL, outcome TEXT NOT NULL,
                reason_code TEXT NOT NULL, evidence_json TEXT NOT NULL,
                rule_id TEXT NOT NULL, rule_version TEXT NOT NULL, decided_at TEXT NOT NULL
            )""")
            rows = self.connection.execute("""SELECT legacy.*, orders.symbol
                FROM paper_risk_decisions_legacy AS legacy
                JOIN paper_orders AS orders ON orders.order_id = legacy.order_id""").fetchall()
            for row in rows:
                reasons = json.loads(row["reasons"] or "[]")
                evidence = [f"legacy_reason:{reason}" for reason in reasons] or ["legacy_reason:none"]
                self.connection.execute(
                    "INSERT INTO paper_risk_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["decision_id"], row["order_id"], row["symbol"], "a_share",
                        "approve" if row["approved"] else "reject",
                        "legacy_risk_approved" if row["approved"] else "legacy_risk_rejected",
                        json.dumps(evidence, ensure_ascii=True), "legacy_paper_risk",
                        "legacy.0", row["created_at"],
                    ),
                )
            self.connection.execute("DROP TABLE paper_risk_decisions_legacy")
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    @synchronized
    def close(self) -> None:
        self.connection.close()

    @synchronized
    def create_account(self, account_id: str, initial_cash: Decimal) -> PaperAccount:
        now = datetime.now(timezone.utc)
        with self.connection:
            self.connection.execute(
                "INSERT INTO paper_accounts VALUES (?, ?, ?, ?)",
                (account_id, str(initial_cash), str(initial_cash), now.isoformat()),
            )
            self.connection.execute(
                "INSERT INTO paper_settings VALUES (?, ?, ?)",
                (account_id, "0.20", "0.80"),
            )
            self._post_cash(
                account_id=account_id,
                amount=initial_cash,
                balance_after=initial_cash,
                reason="deposit",
                related_order_id=None,
                related_fill_id=None,
                created_at=now,
            )
        return self.get_account(account_id)

    @synchronized
    def get_account(self, account_id: str) -> PaperAccount:
        row = self.connection.execute(
            "SELECT * FROM paper_accounts WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise KeyError(account_id)
        positions = self.list_positions(account_id)
        market_value = sum((position.market_value for position in positions), Decimal("0"))
        cash = Decimal(row["cash"])
        total_equity = cash + market_value
        exposure = market_value / total_equity if total_equity else Decimal("0")
        return PaperAccount(
            account_id=account_id,
            initial_cash=Decimal(row["initial_cash"]),
            cash=cash,
            total_equity=total_equity,
            exposure=exposure,
        )

    @synchronized
    def create_order(self, account_id: str, request: OrderRequest) -> str:
        existing = self.connection.execute(
            "SELECT order_id FROM paper_orders WHERE account_id = ? AND client_order_id = ?",
            (account_id, request.client_order_id),
        ).fetchone()
        if existing is not None:
            return str(existing["order_id"])
        order_id = f"order-{uuid4().hex}"
        with self.connection:
            self.connection.execute(
                """INSERT INTO paper_orders
                   (order_id, account_id, client_order_id, symbol, side, shares, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    order_id,
                    account_id,
                    request.client_order_id,
                    request.symbol,
                    request.side,
                    request.shares,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return order_id

    @synchronized
    def get_order(self, order_id: str) -> dict[str, object]:
        row = self.connection.execute(
            "SELECT * FROM paper_orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise KeyError(order_id)
        return dict(row)

    @synchronized
    def get_order_by_client_id(self, account_id: str, client_order_id: str) -> dict[str, object] | None:
        row = self.connection.execute(
            "SELECT * FROM paper_orders WHERE account_id = ? AND client_order_id = ?",
            (account_id, client_order_id),
        ).fetchone()
        return dict(row) if row is not None else None

    @synchronized
    def get_fill_for_order(self, order_id: str) -> Fill:
        row = self.connection.execute(
            "SELECT payload FROM paper_fills WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise KeyError(order_id)
        return Fill.model_validate_json(row["payload"])

    @synchronized
    def list_orders(self, account_id: str) -> list[dict[str, object]]:
        rows = self.connection.execute(
            "SELECT * FROM paper_orders WHERE account_id = ? ORDER BY created_at", (account_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    @synchronized
    def reject_order(self, order_id: str, reason: str) -> None:
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE paper_orders
                   SET status = 'rejected', rejection_reason = ?
                   WHERE order_id = ? AND status = 'pending'""",
                (reason, order_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("order is not pending")

    @synchronized
    def record_risk_decision(self, decision: RiskDecision) -> str:
        existing = self.connection.execute(
            "SELECT order_id FROM paper_risk_decisions WHERE order_id = ?", (decision.order_id,)
        ).fetchone()
        if existing is not None:
            saved = self.get_risk_decision_for_order(decision.order_id)
            if saved != decision:
                raise ValueError(f"conflicting risk decision for order {decision.order_id!r}")
            return saved.decision_id
        with self.connection:
            self.connection.execute(
                "INSERT INTO paper_risk_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision.decision_id, decision.order_id, decision.symbol,
                    decision.asset.value, decision.outcome, decision.reason_code,
                    json.dumps(decision.evidence, ensure_ascii=True), decision.rule_id,
                    decision.rule_version, decision.decided_at.isoformat(),
                ),
            )
        return decision.decision_id

    @synchronized
    def get_risk_decision_for_order(self, order_id: str) -> RiskDecision:
        row = self.connection.execute(
            "SELECT * FROM paper_risk_decisions WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            raise KeyError(order_id)
        return RiskDecision(
            decision_id=row["decision_id"], order_id=row["order_id"], symbol=row["symbol"],
            asset=row["asset"], outcome=row["outcome"], reason_code=row["reason_code"],
            evidence=tuple(json.loads(row["evidence_json"])), rule_id=row["rule_id"],
            rule_version=row["rule_version"], decided_at=row["decided_at"],
        )

    @synchronized
    def list_risk_decisions(self, *, limit: int = 50) -> list[RiskDecision]:
        rows = self.connection.execute(
            "SELECT order_id FROM paper_risk_decisions ORDER BY decided_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self.get_risk_decision_for_order(row["order_id"]) for row in rows]

    @synchronized
    def list_rejected_order_decisions(self, *, limit: int = 20) -> list[RiskDecision]:
        rows = self.connection.execute(
            """SELECT decisions.order_id FROM paper_orders AS orders
               JOIN paper_risk_decisions AS decisions ON decisions.order_id = orders.order_id
               WHERE orders.status = 'rejected'
               ORDER BY orders.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self.get_risk_decision_for_order(row["order_id"]) for row in rows]

    @synchronized
    def get_allocation_settings(self, account_id: str) -> tuple[Decimal, Decimal]:
        row = self.connection.execute(
            "SELECT * FROM paper_settings WHERE account_id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise KeyError(account_id)
        return Decimal(row["single_position_cap"]), Decimal(row["total_exposure_cap"])

    @synchronized
    def update_allocation_settings(
        self,
        account_id: str,
        *,
        single_position_cap: Decimal,
        total_exposure_cap: Decimal,
    ) -> None:
        if not 0 < single_position_cap <= total_exposure_cap <= 1:
            raise ValueError("allocation caps must satisfy 0 < single <= total <= 1")
        with self.connection:
            cursor = self.connection.execute(
                """UPDATE paper_settings
                   SET single_position_cap = ?, total_exposure_cap = ?
                   WHERE account_id = ?""",
                (str(single_position_cap), str(total_exposure_cap), account_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(account_id)

    @synchronized
    def apply_fill(
        self,
        account_id: str,
        fill: Fill,
        *,
        order_id: str,
        fail_before_ledger: bool = False,
    ) -> None:
        account = self.get_account(account_id)
        signed_gross = -fill.gross_amount if fill.side == "buy" else fill.gross_amount
        cash_change = signed_gross - fill.commission
        new_cash = account.cash + cash_change
        if new_cash < 0:
            raise ValueError("insufficient cash")

        with self.connection:
            self.connection.execute(
                "INSERT INTO paper_fills VALUES (?, ?, ?)",
                (fill.fill_id, order_id, fill.model_dump_json()),
            )
            self._update_position(account_id, fill)
            self.connection.execute(
                "UPDATE paper_accounts SET cash = ? WHERE account_id = ?",
                (str(new_cash), account_id),
            )
            if fail_before_ledger:
                raise RuntimeError("simulated ledger failure")
            self._post_cash(
                account_id=account_id,
                amount=cash_change,
                balance_after=new_cash,
                reason=fill.side,
                related_order_id=order_id,
                related_fill_id=fill.fill_id,
                created_at=fill.filled_at,
            )
            self.connection.execute(
                "UPDATE paper_orders SET status = 'filled' WHERE order_id = ?", (order_id,)
            )

    def _update_position(self, account_id: str, fill: Fill) -> None:
        row = self.connection.execute(
            "SELECT * FROM paper_positions WHERE account_id = ? AND symbol = ?",
            (account_id, fill.symbol),
        ).fetchone()
        old_shares = int(row["shares"]) if row else 0
        old_cost = Decimal(row["average_cost"]) if row else Decimal("0")
        share_change = fill.shares if fill.side == "buy" else -fill.shares
        new_shares = old_shares + share_change
        if new_shares < 0:
            raise ValueError("insufficient shares")
        average_cost = (
            ((old_cost * old_shares) + fill.gross_amount + fill.commission) / new_shares
            if fill.side == "buy" and new_shares
            else old_cost
        )
        if new_shares == 0:
            self.connection.execute(
                "DELETE FROM paper_positions WHERE account_id = ? AND symbol = ?",
                (account_id, fill.symbol),
            )
            return
        self.connection.execute(
            """INSERT INTO paper_positions VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(account_id, symbol) DO UPDATE SET
               shares = excluded.shares,
               average_cost = excluded.average_cost,
               market_value = excluded.market_value""",
            (account_id, fill.symbol, new_shares, str(average_cost), str(fill.price * new_shares)),
        )

    def _post_cash(
        self,
        *,
        account_id: str,
        amount: Decimal,
        balance_after: Decimal,
        reason: str,
        related_order_id: str | None,
        related_fill_id: str | None,
        created_at: datetime,
    ) -> None:
        entry_id = f"ledger-{uuid4().hex}"
        self.connection.execute(
            "INSERT INTO paper_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                account_id,
                str(amount),
                str(balance_after),
                reason,
                related_order_id,
                related_fill_id,
                created_at.isoformat(),
            ),
        )
        debit_account, credit_account = (
            ("cash", "counterparty") if amount >= 0 else ("counterparty", "cash")
        )
        value = abs(amount)
        self.connection.executemany(
            "INSERT INTO paper_journal VALUES (?, ?, ?, ?, ?)",
            [
                (f"line-{uuid4().hex}", entry_id, debit_account, str(value), "0"),
                (f"line-{uuid4().hex}", entry_id, credit_account, "0", str(value)),
            ],
        )

    @synchronized
    def list_positions(self, account_id: str) -> list[Position]:
        rows = self.connection.execute(
            "SELECT * FROM paper_positions WHERE account_id = ? ORDER BY symbol", (account_id,)
        ).fetchall()
        return [
            Position(
                symbol=row["symbol"],
                shares=row["shares"],
                average_cost=Decimal(row["average_cost"]),
                market_value=Decimal(row["market_value"]),
            )
            for row in rows
        ]

    @synchronized
    def list_ledger(self, account_id: str) -> list[LedgerEntry]:
        rows = self.connection.execute(
            "SELECT * FROM paper_ledger WHERE account_id = ? ORDER BY created_at, rowid",
            (account_id,),
        ).fetchall()
        return [
            LedgerEntry(
                entry_id=row["entry_id"],
                account_id=row["account_id"],
                amount=Decimal(row["amount"]),
                balance_after=Decimal(row["balance_after"]),
                reason=row["reason"],
                related_order_id=row["related_order_id"],
                related_fill_id=row["related_fill_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
