import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from qibao_api.contracts.convertible_bond import ClauseDates, ConvertibleBondContract
from qibao_api.contracts.instruments import validate_convertible_bond_code
from qibao_api.contracts.market import DataQuality
from qibao_api.convertible_bonds.models import BondClauseSnapshot, BondQuote

CHINA_TZ = timezone(timedelta(hours=8))
ClauseTransport = Callable[[str], Awaitable[dict[str, Any]]]


def _bond_market_prefix(code: str) -> str:
    validate_convertible_bond_code(code)
    return "sh" if code.startswith("11") else "sz"


def _extract_tencent_payload(body: str) -> str:
    if '="' not in body:
        raise ValueError("Tencent quote response has no payload")
    return body.split('="', 1)[1].rsplit('"', 1)[0]


class TencentBondQuoteSource:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def fetch(self, bond_code: str) -> BondQuote:
        instrument = f"{_bond_market_prefix(bond_code)}{bond_code}"
        response = await self.client.get(f"https://qt.gtimg.cn/q={instrument}")
        response.raise_for_status()
        raw = response.content
        fields = _extract_tencent_payload(raw.decode("gbk", errors="strict")).split("~")
        if len(fields) < 31:
            raise ValueError("Tencent quote payload is incomplete")
        observed_at = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(tzinfo=CHINA_TZ)
        price = Decimal(fields[3])
        suspended = price == 0
        return BondQuote(
            symbol=fields[2],
            name=fields[1],
            price=None if suspended else price,
            previous_close=Decimal(fields[4]),
            suspended=suspended,
            observed_at=observed_at,
            source="tencent",
            quality=DataQuality.UNAVAILABLE if suspended else DataQuality.FRESH,
            raw_identity=hashlib.sha256(raw).hexdigest(),
        )


def parse_eastmoney_clause_payload(
    payload: dict[str, Any], *, fetched_at: datetime
) -> BondClauseSnapshot:
    linked_stock = payload.get("linked_stock")
    if not linked_stock:
        raise ValueError("linked_stock is missing from clause payload")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    contract = ConvertibleBondContract(
        bond_code=payload["bond_code"],
        linked_stock=linked_stock,
        conversion_price=Decimal(payload["conversion_price"]),
        maturity=date.fromisoformat(payload["maturity"]),
        remaining_size=Decimal(payload["remaining_size"]),
        clause_dates=ClauseDates(
            conversion_start=date.fromisoformat(payload["conversion_start"]),
            redemption_start=_optional_date(payload.get("redemption_start")),
            put_back_start=_optional_date(payload.get("put_back_start")),
        ),
        as_of=fetched_at,
    )
    return BondClauseSnapshot(
        contract=contract,
        raw_payload=payload,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        source="eastmoney",
        fetched_at=fetched_at,
    )


def _optional_date(value: Any) -> date | None:
    return date.fromisoformat(value) if value else None


class EastmoneyClauseSource:
    def __init__(
        self,
        transport: ClauseTransport,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.transport = transport
        self.clock = clock

    async def fetch(self, bond_code: str) -> BondClauseSnapshot:
        validate_convertible_bond_code(bond_code)
        payload = await self.transport(bond_code)
        return parse_eastmoney_clause_payload(payload, fetched_at=self.clock())
