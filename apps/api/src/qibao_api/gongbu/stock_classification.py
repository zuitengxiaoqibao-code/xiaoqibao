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
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from qibao_api.contracts.instruments import validate_a_share_code


EASTMONEY_STOCK_INFO_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_STOCK_BLOCKS_URL = "https://push2.eastmoney.com/api/qt/slist/get"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
CHINA_TZ = ZoneInfo("Asia/Shanghai")


class ClassificationHttpResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status_code: int
    body: bytes


ClassificationTransport = Callable[
    [str, dict[str, str], dict[str, str]],
    Awaitable[ClassificationHttpResponse],
]


class StockBoard(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(pattern=r"^BK\d{4}$")
    name: str = Field(min_length=1, max_length=80)
    change_percent: Decimal | None = None
    lead_stock: str | None = Field(default=None, max_length=80)


class StockClassificationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    classification_id: str = Field(pattern=r"^stock-classification-[0-9a-f]{24}$")
    symbol: str = Field(pattern=r"^\d{6}$")
    observed_at: AwareDatetime
    industry: str = Field(min_length=1, max_length=80)
    boards: tuple[StockBoard, ...] = Field(min_length=1)
    source: str = "eastmoney-stock-classification"
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_snapshot: bytes


class StockClassificationIntegrityError(RuntimeError):
    pass


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _nonblank(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


class EastmoneyStockClassificationSource:
    def __init__(
        self,
        transport: ClassificationTransport | None = None,
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

    async def fetch(self, symbol: str) -> StockClassificationSnapshot:
        symbol = validate_a_share_code(symbol)
        secid = f"{1 if symbol.startswith('6') else 0}.{symbol}"
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://quote.eastmoney.com/",
        }
        async with self._request_lock:
            info_raw = await self._fetch_json(
                EASTMONEY_STOCK_INFO_URL,
                {
                    "fltt": "2",
                    "invt": "2",
                    "fields": "f57,f127",
                    "secid": secid,
                },
                headers,
            )
            blocks_raw = await self._fetch_json(
                EASTMONEY_STOCK_BLOCKS_URL,
                {
                    "fltt": "2",
                    "invt": "2",
                    "secid": secid,
                    "spt": "3",
                    "pi": "0",
                    "pz": "200",
                    "po": "1",
                    "fields": "f12,f14,f3,f128",
                },
                headers,
            )
        return self._parse(symbol, info_raw, blocks_raw)

    async def _fetch_json(
        self,
        url: str,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        response: ClassificationHttpResponse | None = None
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
                raise OSError(
                    f"Eastmoney classification status {response.status_code}"
                )
        assert response is not None
        if response.status_code != 200:
            raise OSError(f"Eastmoney classification status {response.status_code}")
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError(
                "Eastmoney classification response is not valid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise ValueError("Eastmoney classification response is not an object")
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
    ) -> ClassificationHttpResponse:
        if self.transport is not None:
            return await self.transport(url, params, headers)
        if self.client is not None:
            result = await self.client.get(url, params=params, headers=headers)
            return ClassificationHttpResponse(
                status_code=result.status_code, body=result.content
            )
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.get(url, params=params, headers=headers)
            return ClassificationHttpResponse(
                status_code=result.status_code, body=result.content
            )

    def _parse(
        self,
        symbol: str,
        info_payload: dict[str, Any],
        blocks_payload: dict[str, Any],
    ) -> StockClassificationSnapshot:
        info = info_payload.get("data") or {}
        if not isinstance(info, dict) or str(info.get("f57") or "") != symbol:
            raise ValueError("Eastmoney classification symbol mismatch")
        industry = _nonblank(info.get("f127"))
        if industry is None:
            raise ValueError("Eastmoney classification industry is empty")

        diff = (blocks_payload.get("data") or {}).get("diff") or []
        rows = list(diff.values()) if isinstance(diff, dict) else diff
        if not isinstance(rows, list):
            raise ValueError("Eastmoney classification board list is invalid")
        boards = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Eastmoney classification board row is invalid")
            code = _nonblank(row.get("f12"))
            name = _nonblank(row.get("f14"))
            if code is None or name is None:
                raise ValueError("Eastmoney classification board is incomplete")
            boards.append(
                StockBoard(
                    code=code,
                    name=name,
                    change_percent=_decimal_or_none(row.get("f3")),
                    lead_stock=_nonblank(row.get("f128")),
                )
            )
        if not boards:
            raise ValueError("Eastmoney classification board list is empty")

        semantic = {
            "boards": [board.model_dump(mode="json") for board in boards],
            "industry": industry,
            "symbol": symbol,
        }
        semantic_bytes = json.dumps(
            semantic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        content_hash = hashlib.sha256(semantic_bytes).hexdigest()
        raw_snapshot = json.dumps(
            {"blocks": blocks_payload, "info": info_payload},
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
        return StockClassificationSnapshot(
            classification_id=f"stock-classification-{identity_hash[:24]}",
            symbol=symbol,
            observed_at=observed_at,
            industry=industry,
            boards=tuple(boards),
            content_hash=content_hash,
            raw_snapshot=raw_snapshot,
        )


class StockClassificationRepository:
    def __init__(self, database: str | Path) -> None:
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS stock_classifications (
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          classification_id TEXT NOT NULL UNIQUE,
          symbol TEXT NOT NULL,
          observed_at TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          canonical_hash TEXT NOT NULL,
          payload TEXT NOT NULL,
          raw_snapshot BLOB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_stock_classifications_symbol
        ON stock_classifications(symbol, sequence);
        CREATE TRIGGER IF NOT EXISTS reject_update_stock_classifications
        BEFORE UPDATE ON stock_classifications
        BEGIN SELECT RAISE(ABORT, 'append-only stock classifications'); END;
        CREATE TRIGGER IF NOT EXISTS reject_delete_stock_classifications
        BEFORE DELETE ON stock_classifications
        BEGIN SELECT RAISE(ABORT, 'append-only stock classifications'); END;
        """)

    def append(self, snapshot: StockClassificationSnapshot) -> str:
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
                "SELECT canonical_hash FROM stock_classifications "
                "WHERE classification_id=?",
                (snapshot.classification_id,),
            ).fetchone()
            if existing is not None:
                if not hmac.compare_digest(existing["canonical_hash"], canonical_hash):
                    raise StockClassificationIntegrityError(
                        f"classification id collision: {snapshot.classification_id}"
                    )
                return snapshot.classification_id
            self.connection.execute(
                """INSERT INTO stock_classifications(
                classification_id,symbol,observed_at,content_hash,canonical_hash,
                payload,raw_snapshot
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    snapshot.classification_id,
                    snapshot.symbol,
                    snapshot.observed_at.astimezone(timezone.utc).isoformat(),
                    snapshot.content_hash,
                    canonical_hash,
                    payload,
                    snapshot.raw_snapshot,
                ),
            )
        return snapshot.classification_id

    def latest(
        self,
        symbol: str,
        as_of: date,
        *,
        cutoff: datetime | None = None,
    ) -> StockClassificationSnapshot | None:
        symbol = validate_a_share_code(symbol)
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM stock_classifications WHERE symbol=? "
                "ORDER BY observed_at DESC, sequence DESC",
                (symbol,),
            ).fetchall()
        normalized_cutoff = cutoff.astimezone(timezone.utc) if cutoff else None
        for row in rows:
            snapshot = self._verified(row)
            observed_at = snapshot.observed_at.astimezone(timezone.utc)
            if observed_at.astimezone(CHINA_TZ).date() > as_of:
                continue
            if normalized_cutoff is not None and observed_at > normalized_cutoff:
                continue
            return snapshot
        return None

    def _verified(self, row: sqlite3.Row) -> StockClassificationSnapshot:
        canonical_hash = hashlib.sha256(
            row["payload"].encode("utf-8") + b"\0" + row["raw_snapshot"]
        ).hexdigest()
        if not hmac.compare_digest(canonical_hash, row["canonical_hash"]):
            raise StockClassificationIntegrityError(
                f"classification {row['classification_id']} failed integrity check"
            )
        payload = json.loads(row["payload"])
        payload["raw_snapshot"] = row["raw_snapshot"]
        snapshot = StockClassificationSnapshot.model_validate(payload)
        if not hmac.compare_digest(snapshot.content_hash, row["content_hash"]):
            raise StockClassificationIntegrityError(
                f"classification {row['classification_id']} content hash differs"
            )
        return snapshot

    def count(self) -> int:
        with self._lock:
            return int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM stock_classifications"
                ).fetchone()[0]
            )

    def close(self) -> None:
        with self._lock:
            self.connection.close()


class StockClassificationService:
    def __init__(
        self,
        source: EastmoneyStockClassificationSource,
        repository: StockClassificationRepository,
    ) -> None:
        self.source = source
        self.repository = repository

    async def sync_symbol(self, symbol: str) -> StockClassificationSnapshot:
        snapshot = await self.source.fetch(symbol)
        self.repository.append(snapshot)
        return snapshot
