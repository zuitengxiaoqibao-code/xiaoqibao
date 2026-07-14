import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from qibao_api.contracts.market import AssetKind, DataQuality
from qibao_api.convertible_bonds.adapters import (
    CB_LIST_REPORT,
    BS_INFO_REPORT,
    EastmoneyClauseSource,
    RawHttpResponse,
    TencentBondQuoteSource,
    unpack_raw_reports,
    ClauseDataUnavailable,
)


# Field shape captured from Eastmoney on 2026-07-14; values are anonymized.
def eastmoney_capture(report: str, *, code: str = "113065", price: str = "12.34") -> bytes:
    if report == CB_LIST_REPORT:
        row = {
            "SECURITY_CODE": code,
            "CONVERT_STOCK_CODE": "600001",
            "TRANSFER_VALUE": price,
            "TRANSFER_START_DATE": "2023-03-01 00:00:00",
            "REDEEM_CLAUSE": "anonymized redemption clause",
            "RESALE_CLAUSE": "anonymized resale clause",
        }
    elif report == BS_INFO_REPORT:
        row = {
            "SECURITY_CODE": code,
            "HONOUR_DATE": "2028-09-15 00:00:00",
            "BOND_BALANCE": "18.765432",
            "CLAUSE_CONTENT": "anonymized supplementary clause text",
            "EXPIRE_DATE": "2028-09-15 00:00:00",
        }
    else:
        raise AssertionError(report)
    return json.dumps({"result": {"data": [row]}}, separators=(",", ":")).encode()


def tencent_body(*, code: str = "113065", price: str = "121.50") -> bytes:
    fields = [""] * 31
    fields[1] = "\u6d4b\u8bd5\u8f6c\u503a"
    fields[2] = code
    fields[3] = price
    fields[4] = "120.00"
    fields[30] = "20260714103000"
    return ('v_sh113065="' + "~".join(fields) + '";').encode("gbk")


@pytest.mark.asyncio
async def test_tencent_quote_metadata_suspension_and_code_validation() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=tencent_body())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        quote = await TencentBondQuoteSource(client).fetch("113065")
    assert quote.asset is AssetKind.CONVERTIBLE_BOND
    assert quote.price == Decimal("121.50")
    assert quote.observed_at == datetime(2026, 7, 14, 10, 30, tzinfo=timezone(timedelta(hours=8)))
    assert quote.quality is DataQuality.FRESH

    async def mismatch(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=tencent_body(code="113066"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(mismatch)) as client:
        with pytest.raises(ValueError, match="does not match requested bond"):
            await TencentBondQuoteSource(client).fetch("113065")


@pytest.mark.asyncio
async def test_tencent_marks_zero_price_suspended_and_rejects_short_payload() -> None:
    async def suspended(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=tencent_body(price="0"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(suspended)) as client:
        quote = await TencentBondQuoteSource(client).fetch("113065")
    assert quote.price is None
    assert quote.suspended is True

    async def short(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'v_sh113065="too~short";')

    async with httpx.AsyncClient(transport=httpx.MockTransport(short)) as client:
        with pytest.raises(ValueError, match="incomplete"):
            await TencentBondQuoteSource(client).fetch("113065")


@pytest.mark.asyncio
async def test_eastmoney_fetches_two_reports_and_maps_only_observed_fields() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    async def transport(url: str, params: dict[str, str]) -> RawHttpResponse:
        seen.append((url, params))
        return RawHttpResponse(200, eastmoney_capture(params["reportName"]))

    observed = datetime(2026, 7, 14, tzinfo=timezone.utc)
    snapshot = await EastmoneyClauseSource(transport=transport, clock=lambda: observed).fetch(
        "113065"
    )

    assert [params["reportName"] for _, params in seen] == [CB_LIST_REPORT, BS_INFO_REPORT]
    assert all(params["filter"] == '(SECURITY_CODE="113065")' for _, params in seen)
    assert snapshot.contract.linked_stock == "600001"
    assert snapshot.contract.conversion_price == Decimal("12.34")
    assert snapshot.contract.clause_dates.conversion_start == date(2023, 3, 1)
    assert snapshot.contract.maturity == date(2028, 9, 15)
    assert snapshot.contract.remaining_size == Decimal("18.765432")
    assert snapshot.contract.clause_dates.redemption_start is None
    assert snapshot.contract.clause_dates.put_back_start is None
    raw = unpack_raw_reports(snapshot.raw_payload)
    assert raw[CB_LIST_REPORT] == eastmoney_capture(CB_LIST_REPORT)
    assert raw[BS_INFO_REPORT] == eastmoney_capture(BS_INFO_REPORT)
    assert b"REDEEM_CLAUSE" in raw[CB_LIST_REPORT]
    assert b"CLAUSE_CONTENT" in raw[BS_INFO_REPORT]


@pytest.mark.asyncio
async def test_eastmoney_rejects_status_missing_fields_and_code_mismatch() -> None:
    async def status(_: str, __: dict[str, str]) -> RawHttpResponse:
        return RawHttpResponse(503, b"unavailable")

    with pytest.raises(ValueError, match="status 503"):
        await EastmoneyClauseSource(transport=status).fetch("113065")

    async def mismatch(_: str, params: dict[str, str]) -> RawHttpResponse:
        return RawHttpResponse(200, eastmoney_capture(params["reportName"], code="113066"))

    with pytest.raises(ValueError, match="does not match requested bond"):
        await EastmoneyClauseSource(transport=mismatch).fetch("113065")

    async def missing(_: str, params: dict[str, str]) -> RawHttpResponse:
        raw = json.loads(eastmoney_capture(params["reportName"]))
        if params["reportName"] == CB_LIST_REPORT:
            del raw["result"]["data"][0]["CONVERT_STOCK_CODE"]
        return RawHttpResponse(200, json.dumps(raw).encode())

    with pytest.raises(ValueError, match="CONVERT_STOCK_CODE"):
        await EastmoneyClauseSource(transport=missing).fetch("113065")


@pytest.mark.asyncio
async def test_eastmoney_empty_rows_raise_typed_unavailable() -> None:
    async def empty(_: str, __: dict[str, str]) -> RawHttpResponse:
        return RawHttpResponse(200, b'{"result":{"data":[]}}')
    with pytest.raises(ClauseDataUnavailable):
        await EastmoneyClauseSource(transport=empty).fetch("113065")


def test_strong_redemption_requires_status_and_dated_evidence() -> None:
    reports = {
        CB_LIST_REPORT: eastmoney_capture(CB_LIST_REPORT),
        BS_INFO_REPORT: eastmoney_capture(BS_INFO_REPORT),
    }
    ordinary = json.loads(reports[CB_LIST_REPORT])
    ordinary["result"]["data"][0]["IS_REDEEM"] = "0"
    reports[CB_LIST_REPORT] = json.dumps(ordinary).encode()
    from qibao_api.convertible_bonds.adapters import parse_eastmoney_clause_payloads
    snapshot = parse_eastmoney_clause_payloads(reports, requested_bond_code="113065", fetched_at=datetime(2026, 7, 14, tzinfo=timezone.utc))
    assert snapshot.strong_redemption.state == "unknown"
    assert snapshot.strong_redemption.clause_present is True
    assert snapshot.strong_redemption.evidence_fields == {}

    announced = json.loads(reports[CB_LIST_REPORT])
    row = announced["result"]["data"][0]
    row.update({"IS_REDEEM": "1", "NOTICE_DATE_SH": "2026-07-10", "EXECUTE_START_DATE": "2026-07-20", "EXECUTE_REASON_SH": "提前赎回"})
    reports[CB_LIST_REPORT] = json.dumps(announced).encode()
    snapshot = parse_eastmoney_clause_payloads(reports, requested_bond_code="113065", fetched_at=datetime(2026, 7, 14, tzinfo=timezone.utc))
    assert snapshot.strong_redemption.state == "announced"
    assert snapshot.strong_redemption.evidence_fields["NOTICE_DATE_SH"] == "2026-07-10"
