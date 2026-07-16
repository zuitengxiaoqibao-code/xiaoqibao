import hashlib
import hmac
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from qibao_api.contracts.briefing import BriefingPhase, DailyBriefing


class BriefingIntegrityError(RuntimeError):
    pass


class BriefingRepository:
    def __init__(self, database: str | Path) -> None:
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS daily_briefings (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          report_id TEXT NOT NULL UNIQUE,
          trading_date TEXT NOT NULL,
          phase TEXT NOT NULL,
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS briefing_run_events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL,
          trading_date TEXT NOT NULL,
          phase TEXT NOT NULL,
          attempt INTEGER NOT NULL,
          status TEXT NOT NULL,
          occurred_at TEXT NOT NULL,
          report_id TEXT,
          error_code TEXT
        );
        CREATE TRIGGER IF NOT EXISTS reject_update_daily_briefings
        BEFORE UPDATE ON daily_briefings
        BEGIN SELECT RAISE(ABORT, 'append-only daily briefings'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_daily_briefings
        BEFORE DELETE ON daily_briefings
        BEGIN SELECT RAISE(ABORT, 'append-only daily briefings'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_briefing_run_events
        BEFORE UPDATE ON briefing_run_events
        BEGIN SELECT RAISE(ABORT, 'append-only briefing run events'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_briefing_run_events
        BEFORE DELETE ON briefing_run_events
        BEGIN SELECT RAISE(ABORT, 'append-only briefing run events'); END;
        """)

    def begin_run(
        self, phase: BriefingPhase, trading_date: date, occurred_at: datetime
    ) -> tuple[str, int]:
        row = self.connection.execute(
            """SELECT COALESCE(MAX(attempt), 0) AS attempt
            FROM briefing_run_events WHERE phase=? AND trading_date=?""",
            (phase, trading_date.isoformat()),
        ).fetchone()
        attempt = int(row["attempt"]) + 1
        run_id = f"briefing-run-{uuid4().hex}"
        with self.connection:
            self.connection.execute(
                """INSERT INTO briefing_run_events(
                run_id,trading_date,phase,attempt,status,occurred_at
                ) VALUES(?,?,?,?,?,?)""",
                (
                    run_id,
                    trading_date.isoformat(),
                    phase,
                    attempt,
                    "started",
                    occurred_at.isoformat(),
                ),
            )
        return run_id, attempt

    def finish_run(
        self,
        run_id: str,
        *,
        trading_date: date,
        phase: BriefingPhase,
        attempt: int,
        status: str,
        occurred_at: datetime,
        report_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO briefing_run_events(
                run_id,trading_date,phase,attempt,status,occurred_at,report_id,error_code
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    trading_date.isoformat(),
                    phase,
                    attempt,
                    status,
                    occurred_at.isoformat(),
                    report_id,
                    error_code,
                ),
            )

    def append_report(self, report: DailyBriefing) -> bool:
        payload = json.dumps(
            report.model_dump(mode="json"), ensure_ascii=False,
            sort_keys=True, separators=(",", ":"),
        )
        canonical_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        row = self.connection.execute(
            "SELECT canonical_hash FROM daily_briefings WHERE report_id=?",
            (report.report_id,),
        ).fetchone()
        if row is not None:
            if not hmac.compare_digest(row["canonical_hash"], canonical_hash):
                raise BriefingIntegrityError(f"briefing id collision: {report.report_id}")
            return False
        with self.connection:
            self.connection.execute(
                """INSERT INTO daily_briefings(
                report_id,trading_date,phase,canonical_hash,payload
                ) VALUES(?,?,?,?,?)""",
                (
                    report.report_id,
                    report.trading_date.isoformat(),
                    report.phase,
                    canonical_hash,
                    payload,
                ),
            )
        return True

    def reports(
        self, *, phase: BriefingPhase | None = None, trading_date: date | None = None
    ) -> list[DailyBriefing]:
        clauses, values = [], []
        if phase is not None:
            clauses.append("phase=?")
            values.append(phase)
        if trading_date is not None:
            clauses.append("trading_date=?")
            values.append(trading_date.isoformat())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"SELECT * FROM daily_briefings{where} ORDER BY sequence", values
        ).fetchall()
        reports = []
        for row in rows:
            computed = hashlib.sha256(row["payload"].encode("utf-8")).hexdigest()
            if not hmac.compare_digest(computed, row["canonical_hash"]):
                raise BriefingIntegrityError(
                    f"briefing {row['report_id']} failed integrity check"
                )
            reports.append(DailyBriefing.model_validate_json(row["payload"]))
        return reports

    def runs(self) -> list[dict]:
        rows = self.connection.execute("""
        SELECT terminal.* FROM briefing_run_events terminal
        JOIN (
          SELECT run_id, MAX(sequence) AS sequence
          FROM briefing_run_events GROUP BY run_id
        ) latest ON terminal.sequence=latest.sequence
        ORDER BY terminal.sequence
        """).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.connection.close()
