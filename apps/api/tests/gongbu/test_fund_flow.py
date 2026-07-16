import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from qibao_api.gongbu.fund_flow import (
    EASTMONEY_FUND_FLOW_DAILY_URL,
    EASTMONEY_FUND_FLOW_MINUTE_URL,
    EastmoneyFundFlowSource,
    FundFlowHttpResponse,
    FundFlowIntegrityError,
    FundFlowRepository,
    FundFlowService,
)


UTC = timezone.utc
OBSERVED = datetime(2026, 7, 17, 2, 0, tzinfo=UTC)


def response(payload: dict, status_code: int = 200) -> FundFlowHttpResponse:
    return FundFlowHttpResponse(
        status_code=status_code,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def daily_payload(symbol: str = "600519", *, count: int = 20) -> dict:
    start = date(2026, 6, 1)
    rows = []
    for index in range(1, count + 1):
        trade_date = start + timedelta(days=index)
        rows.append(
            f"{trade_date.isoformat()},{index * 100000000},"
            f"{index * 10000000},{index * 20000000},"
            f"{index * 30000000},{index * 40000000}"
        )
    return {"data": {"code": symbol, "klines": rows}}


def minute_payload(symbol: str = "600519") -> dict:
    return {
        "data": {
            "code": symbol,
            "klines": [
                "09:31,100000000,10000000,20000000,30000000,40000000",
                "09:32,-25000000,-1000000,-2000000,-3000000,-4000000",
            ],
        }
    }


@pytest.mark.asyncio
async def test_source_fetches_daily_and_minute_fund_flow_serially() -> None:
    calls = []
    replies = {
        EASTMONEY_FUND_FLOW_DAILY_URL: response(daily_payload()),
        EASTMONEY_FUND_FLOW_MINUTE_URL: response(minute_payload()),
    }
    monotonic_values = iter((0.0, 0.0, 1.0))
    sleeps = []

    async def transport(url, params, headers):
        calls.append((url, params, headers))
        return replies[url]

    async def sleep(seconds):
        sleeps.append(seconds)

    source = EastmoneyFundFlowSource(
        transport=transport,
        clock=lambda: OBSERVED,
        monotonic=lambda: next(monotonic_values),
        sleep=sleep,
        minimum_interval=1.0,
    )

    snapshot = await source.fetch("600519")

    assert [call[0] for call in calls] == [
        EASTMONEY_FUND_FLOW_DAILY_URL,
        EASTMONEY_FUND_FLOW_MINUTE_URL,
    ]
    assert all(call[1]["secid"] == "1.600519" for call in calls)
    assert calls[0][1]["lmt"] == "120"
    assert calls[1][1]["klt"] == "1"
    assert sleeps == [1.0]
    assert snapshot.symbol == "600519"
    assert snapshot.latest_trade_date == date(2026, 6, 21)
    assert snapshot.latest_main_net == Decimal("2000000000")
    assert snapshot.latest_large_net == Decimal("600000000")
    assert snapshot.latest_super_net == Decimal("800000000")
    assert snapshot.main_net_5d == Decimal("9000000000")
    assert snapshot.main_net_20d == Decimal("21000000000")
    assert snapshot.intraday_main_net == Decimal("75000000")
    assert snapshot.daily_sample_count == 20
    assert snapshot.intraday_sample_count == 2
    assert snapshot.flow_direction == "inflow"
    assert len(snapshot.content_hash) == 64
    assert json.loads(snapshot.raw_snapshot) == {
        "daily": daily_payload(),
        "minute": minute_payload(),
    }


@pytest.mark.asyncio
async def test_source_retries_one_transient_response() -> None:
    calls = []
    replies = [
        FundFlowHttpResponse(status_code=503, body=b"unavailable"),
        response(daily_payload()),
        response(minute_payload()),
    ]

    async def transport(url, _params, _headers):
        calls.append(url)
        return replies.pop(0)

    snapshot = await EastmoneyFundFlowSource(
        transport=transport, minimum_interval=0
    ).fetch("600519")

    assert snapshot.daily_sample_count == 20
    assert calls == [
        EASTMONEY_FUND_FLOW_DAILY_URL,
        EASTMONEY_FUND_FLOW_DAILY_URL,
        EASTMONEY_FUND_FLOW_MINUTE_URL,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "daily,minute",
    [
        ({"data": {"code": "600519", "klines": []}}, minute_payload()),
        (daily_payload("000001"), minute_payload()),
        (
            {"data": {"code": "600519", "klines": [
                "2026-07-16,-,1,2,3,4"
            ]}},
            minute_payload(),
        ),
        (
            daily_payload(),
            {"data": {"code": "000001", "klines": []}},
        ),
    ],
)
async def test_source_rejects_empty_mismatched_or_missing_values(
    daily, minute
) -> None:
    replies = [response(daily), response(minute)]

    async def transport(_url, _params, _headers):
        return replies.pop(0)

    with pytest.raises(ValueError):
        await EastmoneyFundFlowSource(
            transport=transport, minimum_interval=0
        ).fetch("600519")


@pytest.mark.asyncio
async def test_empty_minute_series_remains_missing_instead_of_zero() -> None:
    replies = [
        response(daily_payload()),
        response({"data": {"code": "600519", "klines": []}}),
    ]

    async def transport(_url, _params, _headers):
        return replies.pop(0)

    snapshot = await EastmoneyFundFlowSource(
        transport=transport, clock=lambda: OBSERVED, minimum_interval=0
    ).fetch("600519")

    assert snapshot.intraday_main_net is None
    assert snapshot.intraday_sample_count == 0


@pytest.mark.asyncio
async def test_content_hash_is_stable_but_observations_have_unique_ids() -> None:
    payloads = [
        response(daily_payload()), response(minute_payload()),
        response(daily_payload()), response(minute_payload()),
    ]

    async def transport(_url, _params, _headers):
        return payloads.pop(0)

    first = await EastmoneyFundFlowSource(
        transport=transport, clock=lambda: OBSERVED, minimum_interval=0
    ).fetch("600519")
    second = await EastmoneyFundFlowSource(
        transport=transport,
        clock=lambda: OBSERVED + timedelta(minutes=5),
        minimum_interval=0,
    ).fetch("600519")

    assert first.snapshot_id != second.snapshot_id
    assert first.content_hash == second.content_hash


@pytest.mark.asyncio
async def test_repository_is_append_only_integrity_checked_and_cutoff_bounded(
    tmp_path,
) -> None:
    payloads = [response(daily_payload()), response(minute_payload())]

    async def transport(_url, _params, _headers):
        return payloads.pop(0)

    first = await EastmoneyFundFlowSource(
        transport=transport, clock=lambda: OBSERVED, minimum_interval=0
    ).fetch("600519")
    second = first.model_copy(update={
        "snapshot_id": "fund-flow-" + "b" * 24,
        "observed_at": OBSERVED + timedelta(days=1),
    })
    repository = FundFlowRepository(tmp_path / "fund-flow.sqlite3")

    repository.append(first)
    repository.append(second)
    repository.append(second)

    assert repository.count() == 2
    assert repository.latest("600519", date(2026, 7, 17)) == first
    assert repository.latest("600519", date(2026, 7, 18)) == second
    assert repository.latest(
        "600519",
        date(2026, 7, 18),
        cutoff=OBSERVED + timedelta(hours=1),
    ) == first
    assert repository.verify_all() == 2
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repository.connection.execute(
            "UPDATE fund_flow_snapshots SET symbol='000001'"
        )

    repository.connection.execute("DROP TRIGGER reject_update_fund_flow_snapshots")
    repository.connection.execute(
        "UPDATE fund_flow_snapshots SET raw_snapshot=? WHERE snapshot_id=?",
        (b"tampered", first.snapshot_id),
    )
    with pytest.raises(FundFlowIntegrityError, match="integrity"):
        repository.verify_all()
    repository.close()


@pytest.mark.asyncio
async def test_service_persists_source_snapshot(tmp_path) -> None:
    payloads = [response(daily_payload()), response(minute_payload())]

    async def transport(_url, _params, _headers):
        return payloads.pop(0)

    source = EastmoneyFundFlowSource(
        transport=transport, clock=lambda: OBSERVED, minimum_interval=0
    )
    repository = FundFlowRepository(tmp_path / "fund-flow.sqlite3")

    snapshot = await FundFlowService(source, repository).sync_symbol("600519")

    assert repository.latest("600519", date(2026, 7, 17)) == snapshot
    repository.close()
