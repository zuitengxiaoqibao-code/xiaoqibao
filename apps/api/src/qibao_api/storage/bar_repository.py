from pathlib import Path
import shutil
import threading
from datetime import date, datetime, timezone

import duckdb

from qibao_api.contracts.bars import DailyBar
from qibao_api.contracts.instruments import validate_a_share_code


class BarRepository:
    def __init__(self, database_path: Path, parquet_dir: Path) -> None:
        self.database_path = database_path
        self.parquet_dir = parquet_dir
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._create_schema()

    def _connect(self):
        return duckdb.connect(str(self.database_path))

    def _create_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_bars (
                    symbol VARCHAR NOT NULL,
                    trade_date DATE NOT NULL,
                    open DECIMAL(18, 4) NOT NULL,
                    high DECIMAL(18, 4) NOT NULL,
                    low DECIMAL(18, 4) NOT NULL,
                    close DECIMAL(18, 4) NOT NULL,
                    volume BIGINT NOT NULL,
                    amount DECIMAL(24, 4) NOT NULL,
                    source VARCHAR NOT NULL,
                    ingested_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                    observation_id VARCHAR NOT NULL DEFAULT (uuid()::VARCHAR)
                )
                """
            )
            columns = connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'daily_bars'"
            ).fetchall()
            if "observation_id" not in {row[0] for row in columns}:
                connection.execute("ALTER TABLE daily_bars RENAME TO daily_bars_legacy")
                connection.execute(
                    """CREATE TABLE daily_bars (
                        symbol VARCHAR NOT NULL, trade_date DATE NOT NULL,
                        open DECIMAL(18, 4) NOT NULL, high DECIMAL(18, 4) NOT NULL,
                        low DECIMAL(18, 4) NOT NULL, close DECIMAL(18, 4) NOT NULL,
                        volume BIGINT NOT NULL, amount DECIMAL(24, 4) NOT NULL,
                        source VARCHAR NOT NULL,
                        ingested_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                        observation_id VARCHAR NOT NULL DEFAULT (uuid()::VARCHAR)
                    )"""
                )
                connection.execute(
                    """INSERT INTO daily_bars
                    (symbol, trade_date, open, high, low, close, volume, amount, source, ingested_at)
                    SELECT symbol, trade_date, open, high, low, close, volume, amount, source,
                           ingested_at FROM daily_bars_legacy"""
                )
                connection.execute("DROP TABLE daily_bars_legacy")

    def upsert(self, bars: list[DailyBar]) -> None:
        rows = [
            (
                bar.symbol,
                bar.trade_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                bar.amount,
                bar.source,
            )
            for bar in bars
        ]
        if not rows:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO daily_bars
                    (symbol, trade_date, open, high, low, close, volume, amount, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def latest(
        self, symbol: str, limit: int = 250, *, cutoff: datetime | None = None,
    ) -> list[DailyBar]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, trade_date, open, high, low, close, volume, amount, source
                FROM daily_bars
                WHERE symbol = ? AND (? IS NULL OR ingested_at <= ?)
                QUALIFY row_number() OVER (
                    PARTITION BY symbol, trade_date
                    ORDER BY ingested_at DESC, observation_id DESC
                ) = 1
                ORDER BY trade_date DESC LIMIT ?
                """,
                [symbol, _database_cutoff(cutoff), _database_cutoff(cutoff), limit],
            ).fetchall()
        return [
            DailyBar(
                symbol=row[0], trade_date=row[1], open=row[2], high=row[3], low=row[4],
                close=row[5], volume=row[6], amount=row[7], source=row[8],
            )
            for row in rows
        ]

    def trade_dates(self, limit: int = 1000) -> list:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """SELECT DISTINCT trade_date FROM daily_bars
                ORDER BY trade_date DESC LIMIT ?""",
                [limit],
            ).fetchall()
        return [row[0] for row in rows]

    def symbols_with_history(
        self, minimum_bars: int, as_of: date, *, cutoff: datetime | None = None,
    ) -> list[str]:
        if minimum_bars < 1:
            raise ValueError("minimum_bars must be positive")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol
                FROM daily_bars
                WHERE trade_date <= ? AND (? IS NULL OR ingested_at <= ?)
                GROUP BY symbol
                HAVING count(DISTINCT trade_date) >= ?
                ORDER BY symbol
                """,
                [as_of, _database_cutoff(cutoff), _database_cutoff(cutoff), minimum_bars],
            ).fetchall()
        symbols = []
        for row in rows:
            try:
                symbols.append(validate_a_share_code(row[0]))
            except ValueError:
                continue
        return symbols

    def latest_many(
        self,
        symbols: list[str],
        limit: int,
        as_of: date,
        *,
        cutoff: datetime | None = None,
    ) -> dict[str, list[DailyBar]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        validated = [validate_a_share_code(symbol) for symbol in symbols]
        if len(set(validated)) != len(validated):
            raise ValueError("A-share symbols must be unique")
        if not validated:
            return {}
        placeholders = ", ".join("?" for _ in validated)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT symbol, trade_date, open, high, low, close, volume, amount, source
                FROM (
                    SELECT *, row_number() OVER (
                        PARTITION BY symbol ORDER BY trade_date DESC
                    ) AS row_number
                    FROM daily_bars
                    WHERE symbol IN ({placeholders}) AND trade_date <= ?
                        AND (? IS NULL OR ingested_at <= ?)
                    QUALIFY row_number() OVER (
                        PARTITION BY symbol, trade_date
                        ORDER BY ingested_at DESC, observation_id DESC
                    ) = 1
                ) ranked
                WHERE row_number <= ?
                ORDER BY symbol, trade_date
                """,
                [
                    *validated, as_of, _database_cutoff(cutoff),
                    _database_cutoff(cutoff), limit,
                ],
            ).fetchall()
        result = {symbol: [] for symbol in validated}
        for row in rows:
            result[row[0]].append(DailyBar(
                symbol=row[0], trade_date=row[1], open=row[2], high=row[3], low=row[4],
                close=row[5], volume=row[6], amount=row[7], source=row[8],
            ))
        return result

    def export_parquet(self, symbol: str) -> Path:
        if not symbol.isdigit() or len(symbol) != 6:
            raise ValueError("symbol must be six digits")
        path = self.parquet_dir / f"{symbol}.parquet"
        escaped_path = path.as_posix().replace("'", "''")
        with self._lock, self._connect() as connection:
            connection.execute(
                f"""
                COPY (
                    SELECT * FROM daily_bars
                    WHERE symbol = '{symbol}' ORDER BY trade_date
                ) TO '{escaped_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
        return path

    def backup_to(self, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("CHECKPOINT")
            finally:
                connection.close()
            shutil.copy2(self.database_path, target_dir / self.database_path.name)
            if self.parquet_dir.is_dir():
                shutil.copytree(
                    self.parquet_dir,
                    target_dir / "parquet" / self.parquet_dir.name,
                    dirs_exist_ok=True,
                )


def _database_cutoff(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cutoff must include a timezone")
    return value.astimezone(timezone.utc).replace(tzinfo=None)
