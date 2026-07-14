import base64
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
CB_LIST_REPORT = "RPT_BOND_CB_LIST"
BS_INFO_REPORT = "RPT_BOND_BS_INFO"
EASTMONEY_PARSER_VERSION = "eastmoney-dual-v1"


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


def pack_raw_reports(reports: dict[str, bytes]) -> bytes:
    payload = {
        report: base64.b64encode(body).decode("ascii") for report, body in sorted(reports.items())
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")


def unpack_raw_reports(raw_payload: bytes) -> dict[str, bytes]:
    try:
        payload = json.loads(raw_payload.decode("ascii"))
        return {report: base64.b64decode(body, validate=True) for report, body in payload.items()}
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError("Eastmoney raw report bundle is invalid") from exc


def parse_eastmoney_clause_payloads(
    reports: dict[str, bytes],
    *,
    requested_bond_code: str,
    fetched_at: datetime,
) -> BondClauseSnapshot:
    if set(reports) != {CB_LIST_REPORT, BS_INFO_REPORT}:
        raise ValueError("Eastmoney clause snapshot requires both reports")
    cb_row = _provider_row(reports[CB_LIST_REPORT], CB_LIST_REPORT)
    bs_row = _provider_row(reports[BS_INFO_REPORT], BS_INFO_REPORT)
    cb_code = _required(cb_row, "SECURITY_CODE")
    bs_code = _required(bs_row, "SECURITY_CODE")
    if cb_code != requested_bond_code or bs_code != requested_bond_code:
        raise ValueError("Eastmoney SECURITY_CODE does not match requested bond")

    contract = ConvertibleBondContract(
        bond_code=cb_code,
        linked_stock=_required(cb_row, "CONVERT_STOCK_CODE"),
        conversion_price=Decimal(_required(cb_row, "TRANSFER_VALUE")),
        maturity=_provider_date(_required(bs_row, "HONOUR_DATE")),
        remaining_size=Decimal(_required(bs_row, "BOND_BALANCE")),
        clause_dates=ClauseDates(
            conversion_start=_provider_date(_required(cb_row, "TRANSFER_START_DATE")),
            redemption_start=None,
            put_back_start=None,
        ),
        as_of=fetched_at,
    )
    raw_payload = pack_raw_reports(reports)
    return BondClauseSnapshot(
        contract=contract,
        raw_payload=raw_payload,
        content_hash=hashlib.sha256(raw_payload).hexdigest(),
        source="eastmoney",
        fetched_at=fetched_at,
        parser_version=EASTMONEY_PARSER_VERSION,
    )


def parse_eastmoney_clause_bundle(
    raw_payload: bytes, *, requested_bond_code: str, fetched_at: datetime
) -> BondClauseSnapshot:
    return parse_eastmoney_clause_payloads(
        unpack_raw_reports(raw_payload),
        requested_bond_code=requested_bond_code,
        fetched_at=fetched_at,
    )


def _provider_row(raw_payload: bytes, report: str) -> dict[str, Any]:
    try:
        response = json.loads(raw_payload.decode("utf-8"))
        rows = response["result"]["data"]
        return rows[0]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Eastmoney {report} response is incomplete") from exc


def _required(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if value is None or value == "":
        raise ValueError(f"Eastmoney field {field} is missing")
    return str(value)


def _provider_date(value: str) -> date:
    return date.fromisoformat(value.split(" ", 1)[0])


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
        reports: dict[str, bytes] = {}
        for report in (CB_LIST_REPORT, BS_INFO_REPORT):
            params = {
                "reportName": report,
                "columns": "ALL",
                "filter": f'(SECURITY_CODE="{bond_code}")',
                "pageNumber": "1",
                "pageSize": "1",
            }
            response = await self._request(params)
            if response.status_code != 200:
                raise ValueError(
                    f"Eastmoney {report} request returned status {response.status_code}"
                )
            reports[report] = response.body
        return parse_eastmoney_clause_payloads(
            reports,
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
