import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from qibao_api.contracts.convertible_bond import ClauseDates, ConvertibleBondContract
from qibao_api.contracts.instruments import validate_convertible_bond_code
from qibao_api.contracts.market import DataQuality
from qibao_api.convertible_bonds.models import BondClauseSnapshot, BondQuote

CHINA_TZ = timezone(timedelta(hours=8))
EASTMONEY_ENDPOINT = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_REPORT = "RPT_BOND_CB_LIST"


@dataclass(frozen=True)
class RawHttpResponse:
    status_code: int
    body: bytes


ClauseTransport = Callable[[str, dict[str, str]], Awaitable[RawHttpResponse]]


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
        if fields[2] != bond_code:
            raise ValueError("Tencent payload code does not match requested bond")
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
    raw_payload: bytes,
    *,
    requested_bond_code: str,
    fetched_at: datetime,
) -> BondClauseSnapshot:
    try:
        response = json.loads(raw_payload.decode("utf-8"))
        rows = response["result"]["data"]
        provider = rows[0]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("Eastmoney clause response is incomplete") from exc

    code = _required(provider, "SECURITY_CODE")
    if code != requested_bond_code:
        raise ValueError("Eastmoney SECURITY_CODE does not match requested bond")

    # Provider-to-domain mapping is deliberately explicit so upstream field changes fail closed.
    contract = ConvertibleBondContract(
        bond_code=code,
        linked_stock=_required(provider, "CONVERT_STOCK_CODE"),
        conversion_price=Decimal(_required(provider, "CONVERT_PRICE")),
        maturity=_provider_date(_required(provider, "MATURITY_DATE")),
        remaining_size=Decimal(_required(provider, "REMAIN_SIZE")),
        clause_dates=ClauseDates(
            conversion_start=_provider_date(_required(provider, "CONVERT_START_DATE")),
            redemption_start=_optional_provider_date(provider.get("REDEEM_START_DATE")),
            put_back_start=_optional_provider_date(provider.get("PUTBACK_START_DATE")),
        ),
        as_of=fetched_at,
    )
    immutable_raw = bytes(raw_payload)
    return BondClauseSnapshot(
        contract=contract,
        raw_payload=immutable_raw,
        content_hash=hashlib.sha256(immutable_raw).hexdigest(),
        source="eastmoney",
        fetched_at=fetched_at,
    )


def _required(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if value is None or value == "":
        raise ValueError(f"Eastmoney field {field} is missing")
    return str(value)


def _provider_date(value: str) -> date:
    return date.fromisoformat(value.split(" ", 1)[0])


def _optional_provider_date(value: Any) -> date | None:
    return _provider_date(str(value)) if value else None


class EastmoneyClauseSource:
    def __init__(
        self,
        transport: ClauseTransport | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.transport = transport
        self.client = client
        self.clock = clock

    async def fetch(self, bond_code: str) -> BondClauseSnapshot:
        validate_convertible_bond_code(bond_code)
        params = {
            "reportName": EASTMONEY_REPORT,
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{bond_code}")',
            "pageNumber": "1",
            "pageSize": "1",
        }
        response = await self._request(params)
        if response.status_code != 200:
            raise ValueError(f"Eastmoney clause request returned status {response.status_code}")
        return parse_eastmoney_clause_payload(
            response.body,
            requested_bond_code=bond_code,
            fetched_at=self.clock(),
        )

    async def _request(self, params: dict[str, str]) -> RawHttpResponse:
        if self.transport is not None:
            return await self.transport(EASTMONEY_ENDPOINT, params)
        if self.client is not None:
            response = await self.client.get(EASTMONEY_ENDPOINT, params=params)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.get(EASTMONEY_ENDPOINT, params=params)
        return RawHttpResponse(status_code=response.status_code, body=response.content)
