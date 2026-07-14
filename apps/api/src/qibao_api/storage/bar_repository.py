from pathlib import Path

import duckdb

from qibao_api.contracts.bars import DailyBar


class BarRepository:
    def __init__(self, database_path: Path, parquet_dir: Path) -> None:
        self.database_path = database_path
        self.parquet_dir = parquet_dir
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def _connect(self):
        return duckdb.connect(str(self.database_path))

    def _create_schema(self) -> None:
        with self._connect() as connection:
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
                    PRIMARY KEY (symbol, trade_date)
                )
                """
            )

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
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO daily_bars
                    (symbol, trade_date, open, high, low, close, volume, amount, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def latest(self, symbol: str, limit: int = 250) -> list[DailyBar]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, trade_date, open, high, low, close, volume, amount, source
                FROM daily_bars WHERE symbol = ? ORDER BY trade_date DESC LIMIT ?
                """,
                [symbol, limit],
            ).fetchall()
        return [
            DailyBar(
                symbol=row[0], trade_date=row[1], open=row[2], high=row[3], low=row[4],
                close=row[5], volume=row[6], amount=row[7], source=row[8],
            )
            for row in rows
        ]

    def trade_dates(self, limit: int = 1000) -> list:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT DISTINCT trade_date FROM daily_bars
                ORDER BY trade_date DESC LIMIT ?""",
                [limit],
            ).fetchall()
        return [row[0] for row in rows]

    def export_parquet(self, symbol: str) -> Path:
        if not symbol.isdigit() or len(symbol) != 6:
            raise ValueError("symbol must be six digits")
        path = self.parquet_dir / f"{symbol}.parquet"
        escaped_path = path.as_posix().replace("'", "''")
        with self._connect() as connection:
            connection.execute(
                f"""
                COPY (
                    SELECT * FROM daily_bars
                    WHERE symbol = '{symbol}' ORDER BY trade_date
                ) TO '{escaped_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
        return path
