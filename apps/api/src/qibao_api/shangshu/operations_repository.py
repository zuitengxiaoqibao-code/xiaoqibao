import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path


class OperationsRepository:
    def __init__(self, database: str | Path) -> None:
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS scheduler_state_events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          paused INTEGER NOT NULL,
          occurred_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scheduled_job_events (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          job_key TEXT NOT NULL,
          phase TEXT NOT NULL,
          trading_date TEXT NOT NULL,
          slot TEXT NOT NULL,
          trigger TEXT NOT NULL,
          attempt INTEGER NOT NULL,
          status TEXT NOT NULL,
          occurred_at TEXT NOT NULL,
          report_id TEXT,
          error_code TEXT,
          UNIQUE(job_key, attempt, status)
        );
        CREATE TRIGGER IF NOT EXISTS reject_update_scheduler_state
        BEFORE UPDATE ON scheduler_state_events
        BEGIN SELECT RAISE(ABORT, 'append-only scheduler state'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_scheduler_state
        BEFORE DELETE ON scheduler_state_events
        BEGIN SELECT RAISE(ABORT, 'append-only scheduler state'); END;
        CREATE TRIGGER IF NOT EXISTS reject_update_job_events
        BEFORE UPDATE ON scheduled_job_events
        BEGIN SELECT RAISE(ABORT, 'append-only job attempts'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_job_events
        BEFORE DELETE ON scheduled_job_events
        BEGIN SELECT RAISE(ABORT, 'append-only job attempts'); END;
        """)
        legacy = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scheduled_job_attempts'"
        ).fetchone()
        if legacy is not None:
            with self.connection:
                self.connection.execute("""
                INSERT OR IGNORE INTO scheduled_job_events(
                  job_key,phase,trading_date,slot,trigger,attempt,status,occurred_at,
                  report_id,error_code
                ) SELECT job_key,phase,trading_date,slot,trigger,attempt,status,
                  occurred_at,report_id,error_code FROM scheduled_job_attempts
                """)

    def set_paused(self, paused: bool, occurred_at: datetime) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO scheduler_state_events(paused,occurred_at) VALUES(?,?)",
                (int(paused), occurred_at.isoformat()),
            )

    def paused(self) -> bool:
        with self._lock:
            row = self.connection.execute(
                "SELECT paused FROM scheduler_state_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return bool(row["paused"]) if row is not None else False

    def append_attempt(
        self,
        *,
        job_key: str,
        phase: str,
        trading_date: date,
        slot: str,
        trigger: str,
        attempt: int,
        status: str,
        occurred_at: datetime,
        report_id: str | None = None,
        error_code: str | None = None,
    ) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """INSERT INTO scheduled_job_events(
                job_key,phase,trading_date,slot,trigger,attempt,status,occurred_at,
                report_id,error_code) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (job_key, phase, trading_date.isoformat(), slot, trigger, attempt,
                 status, occurred_at.isoformat(), report_id, error_code),
            )

    def attempts_for(self, job_key: str) -> list[dict]:
        with self._lock:
            rows = self.connection.execute(
                """SELECT * FROM scheduled_job_events WHERE job_key=?
                ORDER BY attempt, sequence""",
                (job_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    def jobs(self) -> list[dict]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM scheduled_job_events ORDER BY sequence"
            ).fetchall()
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(row["job_key"], []).append(row)
        jobs = []
        for attempts in grouped.values():
            latest = dict(attempts[-1])
            latest["attempts"] = max(item["attempt"] for item in attempts)
            jobs.append(latest)
        return jobs

    def close(self) -> None:
        with self._lock:
            self.connection.close()
