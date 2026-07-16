import asyncio
import hashlib
import hmac
import json
import sqlite3
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from qibao_api.contracts.instruments import validate_a_share_code


EASTMONEY_FUND_FLOW_DAILY_URL = (
    "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
)
EASTMONEY_FUND_FLOW_MINUTE_URL = (
    "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
CHINA_TZ = ZoneInfo("Asia/Shanghai")


class FundFlowHttpResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status_code: int
    body: bytes


FundFlowTransport = Callable[
    [str, dict[str, str], dict[str, str]],
    Awaitable[FundFlowHttpResponse],
]


class FundFlowSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(pattern=r"^fund-flow-[0-9a-f]{24}$")
    symbol: str = Field(pattern=r"^\d{6}$")
    observed_at: AwareDatetime
    latest_trade_date: date
    latest_main_net: Decimal
    latest_super_net: Decimal
    latest_large_net: Decimal
    main_net_5d: Decimal
    main_net_20d: Decimal
    intraday_main_net: Decimal | None = None
    daily_sample_count: int = Field(ge=1, le=120)
    intraday_sample_count: int = Field(ge=0)
    flow_direction: Literal["inflow", "outflow", "balanced"]
    source: str = "eastmoney-fund-flow"
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_snapshot: bytes = Field(min_length=1)


class FundFlowIntegrityError(RuntimeError):
    pass


def _required_decimal(value: Any, field: str) -> Decimal:
    if value in (None, "", "-"):
        raise ValueError(f"Eastmoney fund-flow {field} is missing")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"Eastmoney fund-flow {field} is invalid") from error
    if not parsed.is_finite():
        raise ValueError(f"Eastmoney fund-flow {field} is not finite")
    return parsed


class EastmoneyFundFlowSource:
    def __init__(
        self,
        transport: FundFlowTransport | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        clock=lambda: datetime.now(timezone.utc),
        monotonic=time.monotonic,
        sleep=asyncio.sleep,
        minimum_interval: float = 1.0,
    ) -> None:
        self.transport = transport
        self.client = client
        self.clock = clock
        self.monotonic = monotonic
        self.sleep = sleep
        self.minimum_interval = minimum_interval
        self._last_request_at: float | None = None
        self._request_lock = asyncio.Lock()

    async def fetch(self, symbol: str) -> FundFlowSnapshot:
        symbol = validate_a_share_code(symbol)
        secid = f"{1 if symbol.startswith('6') else 0}.{symbol}"
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://quote.eastmoney.com/",
            "Origin": "https://quote.eastmoney.com",
        }
        async with self._request_lock:
            daily = await self._fetch_json(
                EASTMONEY_FUND_FLOW_DAILY_URL,
                {
                    "secid": secid,
                    "fields1": "f1,f2,f3,f7",
                    "fields2": (
                        "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,"
                        "f62,f63,f64,f65"
                    ),
                    "lmt": "120",
                },
                headers,
            )
            minute = await self._fetch_json(
                EASTMONEY_FUND_FLOW_MINUTE_URL,
                {
                    "secid": secid,
                    "klt": "1",
                    "fields1": "f1,f2,f3,f7",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57",
                },
                headers,
            )
        return self._parse(symbol, daily, minute)

    async def _fetch_json(
        self,
        url: str,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        response: FundFlowHttpResponse | None = None
        for attempt in range(2):
            try:
                await self._wait_for_rate_limit()
                response = await self._request(url, params, headers)
            except (OSError, httpx.TransportError):
                if attempt == 1:
                    raise
                continue
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt == 1:
                raise OSError(f"Eastmoney fund-flow status {response.status_code}")
        assert response is not None
        if response.status_code != 200:
            raise OSError(f"Eastmoney fund-flow status {response.status_code}")
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Eastmoney fund-flow response is not valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("Eastmoney fund-flow response is not an object")
        return payload

    async def _wait_for_rate_limit(self) -> None:
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = self.minimum_interval - (now - self._last_request_at)
            if remaining > 0:
                await self.sleep(remaining)
                now = self.monotonic()
        self._last_request_at = now

    async def _request(
        self,
        url: str,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> FundFlowHttpResponse:
        if self.transport is not None:
            return await self.transport(url, params, headers)
        if self.client is not None:
            result = await self.client.get(url, params=params, headers=headers)
            return FundFlowHttpResponse(
                status_code=result.status_code, body=result.content
            )
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.get(url, params=params, headers=headers)
            return FundFlowHttpResponse(
                status_code=result.status_code, body=result.content
            )

    def _parse(
        self,
        symbol: str,
        daily_payload: dict[str, Any],
        minute_payload: dict[str, Any],
    ) -> FundFlowSnapshot:
        daily_rows = self._rows(symbol, daily_payload, "daily")
        if not daily_rows:
            raise ValueError("Eastmoney daily fund-flow series is empty")
        parsed_daily = []
        for row in daily_rows:
            parts = row.split(",")
            if len(parts) < 6:
                raise ValueError("Eastmoney daily fund-flow row is incomplete")
            try:
                trade_date = date.fromisoformat(parts[0])
            except ValueError as error:
                raise ValueError("Eastmoney daily fund-flow date is invalid") from error
            parsed_daily.append(
                (
                    trade_date,
                    _required_decimal(parts[1], "daily main net"),
                    _required_decimal(parts[4], "daily large net"),
                    _required_decimal(parts[5], "daily super net"),
                )
            )
        parsed_daily.sort(key=lambda item: item[0])
        dates = [item[0] for item in parsed_daily]
        if len(dates) != len(set(dates)):
            raise ValueError("Eastmoney daily fund-flow dates are duplicated")

        minute_rows = self._rows(symbol, minute_payload, "minute")
        intraday_values = []
        for row in minute_rows:
            parts = row.split(",")
            if len(parts) < 6 or not parts[0].strip():
                raise ValueError("Eastmoney minute fund-flow row is incomplete")
            intraday_values.append(
                _required_decimal(parts[1], "minute main net")
            )

        latest = parsed_daily[-1]
        main_net_5d = sum(
            (item[1] for item in parsed_daily[-5:]), start=Decimal("0")
        )
        main_net_20d = sum(
            (item[1] for item in parsed_daily[-20:]), start=Decimal("0")
        )
        direction: Literal["inflow", "outflow", "balanced"] = (
            "inflow" if main_net_5d > 0 else
            "outflow" if main_net_5d < 0 else
            "balanced"
        )
        semantic = {
            "daily_sample_count": len(parsed_daily),
            "flow_direction": direction,
            "intraday_main_net": (
                str(sum(intraday_values, start=Decimal("0")))
                if intraday_values else None
            ),
            "intraday_sample_count": len(intraday_values),
            "latest_large_net": str(latest[2]),
            "latest_main_net": str(latest[1]),
            "latest_super_net": str(latest[3]),
            "latest_trade_date": latest[0].isoformat(),
            "main_net_20d": str(main_net_20d),
            "main_net_5d": str(main_net_5d),
            "symbol": symbol,
        }
        semantic_bytes = json.dumps(
            semantic, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        content_hash = hashlib.sha256(semantic_bytes).hexdigest()
        raw_snapshot = json.dumps(
            {"daily": daily_payload, "minute": minute_payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        observed_at = self.clock()
        identity_hash = hashlib.sha256(
            (
                content_hash
                + observed_at.astimezone(timezone.utc).isoformat()
            ).encode("utf-8")
        ).hexdigest()
        return FundFlowSnapshot(
            snapshot_id=f"fund-flow-{identity_hash[:24]}",
            symbol=symbol,
            observed_at=observed_at,
            latest_trade_date=latest[0],
            latest_main_net=latest[1],
            latest_large_net=latest[2],
            latest_super_net=latest[3],
            main_net_5d=main_net_5d,
            main_net_20d=main_net_20d,
            intraday_main_net=(
                sum(intraday_values, start=Decimal("0"))
                if intraday_values else None
            ),
            daily_sample_count=len(parsed_daily),
            intraday_sample_count=len(intraday_values),
            flow_direction=direction,
            content_hash=content_hash,
            raw_snapshot=raw_snapshot,
        )

    @staticmethod
    def _rows(
        symbol: str, payload: dict[str, Any], series: str
    ) -> list[str]:
        data = payload.get("data")
        if not isinstance(data, dict) or str(data.get("code") or "") != symbol:
            raise ValueError(f"Eastmoney {series} fund-flow symbol mismatch")
        rows = data.get("klines") or []
        if not isinstance(rows, list) or any(not isinstance(row, str) for row in rows):
            raise ValueError(f"Eastmoney {series} fund-flow series is invalid")
        return rows


class FundFlowRepository:
    def __init__(self, database: str | Path) -> None:
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS fund_flow_snapshots (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          snapshot_id TEXT NOT NULL UNIQUE,
          symbol TEXT NOT NULL,
          observed_at TEXT NOT NULL,
          latest_trade_date TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL,
          raw_snapshot BLOB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_fund_flow_symbol_observed
        ON fund_flow_snapshots(symbol, observed_at, sequence);
        CREATE TRIGGER IF NOT EXISTS reject_update_fund_flow_snapshots
        BEFORE UPDATE ON fund_flow_snapshots
        BEGIN SELECT RAISE(ABORT, 'append-only fund-flow snapshots'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_fund_flow_snapshots
        BEFORE DELETE ON fund_flow_snapshots
        BEGIN SELECT RAISE(ABORT, 'append-only fund-flow snapshots'); END;
        """)

    def append(self, snapshot: FundFlowSnapshot) -> str:
        payload = json.dumps(
            snapshot.model_dump(mode="json", exclude={"raw_snapshot"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical_hash = hashlib.sha256(
            payload.encode("utf-8") + b"\0" + snapshot.raw_snapshot
        ).hexdigest()
        with self._lock, self.connection:
            existing = self.connection.execute(
                "SELECT canonical_hash FROM fund_flow_snapshots WHERE snapshot_id=?",
                (snapshot.snapshot_id,),
            ).fetchone()
            if existing is not None:
                if not hmac.compare_digest(existing["canonical_hash"], canonical_hash):
                    raise FundFlowIntegrityError(
                        f"fund-flow id collision: {snapshot.snapshot_id}"
                    )
                return snapshot.snapshot_id
            self.connection.execute(
                """INSERT INTO fund_flow_snapshots(
                snapshot_id,symbol,observed_at,latest_trade_date,content_hash,
                canonical_hash,payload,raw_snapshot
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.symbol,
                    snapshot.observed_at.astimezone(timezone.utc).isoformat(),
                    snapshot.latest_trade_date.isoformat(),
                    snapshot.content_hash,
                    canonical_hash,
                    payload,
                    snapshot.raw_snapshot,
                ),
            )
        return snapshot.snapshot_id

    def latest(
        self,
        symbol: str,
        as_of: date,
        *,
        cutoff: datetime | None = None,
    ) -> FundFlowSnapshot | None:
        symbol = validate_a_share_code(symbol)
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM fund_flow_snapshots WHERE symbol=? "
                "ORDER BY observed_at DESC, sequence DESC",
                (symbol,),
            ).fetchall()
        normalized_cutoff = cutoff.astimezone(timezone.utc) if cutoff else None
        for row in rows:
            snapshot = self._verified(row)
            observed_at = snapshot.observed_at.astimezone(timezone.utc)
            if observed_at.astimezone(CHINA_TZ).date() > as_of:
                continue
            if snapshot.latest_trade_date > as_of:
                continue
            if normalized_cutoff is not None and observed_at > normalized_cutoff:
                continue
            return snapshot
        return None

    def verify_all(self) -> int:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM fund_flow_snapshots ORDER BY sequence"
            ).fetchall()
            for row in rows:
                self._verified(row)
        return len(rows)

    def _verified(self, row: sqlite3.Row) -> FundFlowSnapshot:
        canonical_hash = hashlib.sha256(
            row["payload"].encode("utf-8") + b"\0" + row["raw_snapshot"]
        ).hexdigest()
        if not hmac.compare_digest(canonical_hash, row["canonical_hash"]):
            raise FundFlowIntegrityError(
                f"fund-flow {row['snapshot_id']} failed integrity check"
            )
        payload = json.loads(row["payload"])
        payload["raw_snapshot"] = row["raw_snapshot"]
        snapshot = FundFlowSnapshot.model_validate(payload)
        if not hmac.compare_digest(snapshot.content_hash, row["content_hash"]):
            raise FundFlowIntegrityError(
                f"fund-flow {row['snapshot_id']} content hash differs"
            )
        return snapshot

    def count(self) -> int:
        with self._lock:
            return int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM fund_flow_snapshots"
                ).fetchone()[0]
            )

    def close(self) -> None:
        with self._lock:
            self.connection.close()


class FundFlowService:
    def __init__(
        self,
        source: EastmoneyFundFlowSource,
        repository: FundFlowRepository,
    ) -> None:
        self.source = source
        self.repository = repository

    async def sync_symbol(self, symbol: str) -> FundFlowSnapshot:
        snapshot = await self.source.fetch(symbol)
        self.repository.append(snapshot)
        return snapshot
