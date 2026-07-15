import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from qibao_api.contracts.instruments import AShareCode
from qibao_api.gongbu.tencent_quotes import market_prefix


NON_EQUITY_IDENTIFIERS = frozenset({"000300"})


class AShareInstrument(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: AShareCode
    name: str = Field(min_length=1)
    exchange: Literal["sh", "sz", "bj"]
    observed_at: AwareDatetime
    quote_quality: Literal["ready", "stale", "unavailable"]

    @field_validator("observed_at")
    @classmethod
    def normalize_observed_at(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def exchange_matches_symbol(self) -> "AShareInstrument":
        if self.symbol in NON_EQUITY_IDENTIFIERS:
            raise ValueError("symbol must identify an A-share equity, not an index")
        if self.exchange != market_prefix(self.symbol):
            raise ValueError("exchange must match A-share symbol")
        return self


class AShareInstrumentDirectory:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS a_share_instrument_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                exchange TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                quote_quality TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_a_share_instrument_latest
            ON a_share_instrument_observations(symbol, observed_at DESC, id DESC)
            """
        )
        self._connection.commit()

    def observe(self, instrument: AShareInstrument) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO a_share_instrument_observations
                    (symbol, name, exchange, observed_at, quote_quality)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    instrument.symbol,
                    instrument.name,
                    instrument.exchange,
                    instrument.observed_at.isoformat(),
                    instrument.quote_quality,
                ),
            )
            self._connection.commit()

    def resolve(self, symbol: str) -> AShareInstrument | None:
        return self.resolve_at(symbol, None)

    def resolve_at(
        self, symbol: str, cutoff: datetime | None
    ) -> AShareInstrument | None:
        normalized_cutoff = cutoff.astimezone(timezone.utc).isoformat() if cutoff else None
        with self._lock:
            row = self._connection.execute(
                """
                SELECT symbol, name, exchange, observed_at, quote_quality
                FROM a_share_instrument_observations
                WHERE symbol = ? AND (? IS NULL OR observed_at <= ?)
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
                """,
                (symbol, normalized_cutoff, normalized_cutoff),
            ).fetchone()
        return self._instrument(row) if row is not None else None

    def search(self, query: str, limit: int = 10) -> tuple[AShareInstrument, ...]:
        normalized = query.strip().casefold()
        if not normalized:
            raise ValueError("query must not be empty")
        if limit < 1:
            raise ValueError("limit must be positive")
        matches = [
            item
            for item in self._all_rows()
            if normalized in item.symbol or normalized in item.name.casefold()
        ]
        return tuple(
            sorted(
                matches,
                key=lambda item: (
                    item.symbol != normalized,
                    not item.name.casefold().startswith(normalized),
                    item.symbol,
                ),
            )[:limit]
        )

    def _all_rows(self) -> tuple[AShareInstrument, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT symbol, name, exchange, observed_at, quote_quality
                FROM (
                    SELECT *, row_number() OVER (
                        PARTITION BY symbol ORDER BY observed_at DESC, id DESC
                    ) AS row_number
                    FROM a_share_instrument_observations
                ) latest
                WHERE row_number = 1
                """
            ).fetchall()
        return tuple(self._instrument(row) for row in rows)

    @staticmethod
    def _instrument(row) -> AShareInstrument:
        return AShareInstrument(
            symbol=row[0],
            name=row[1],
            exchange=row[2],
            observed_at=datetime.fromisoformat(row[3]),
            quote_quality=row[4],
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
