import json
import sqlite3
from datetime import date, datetime, timezone

import pytest

from qibao_api.gongbu.stock_classification import (
    EASTMONEY_STOCK_BLOCKS_URL,
    EASTMONEY_STOCK_INFO_URL,
    ClassificationHttpResponse,
    EastmoneyStockClassificationSource,
    StockClassificationIntegrityError,
    StockClassificationRepository,
    StockClassificationService,
)


UTC = timezone.utc


def response(payload: dict) -> ClassificationHttpResponse:
    return ClassificationHttpResponse(
        status_code=200,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


@pytest.mark.asyncio
async def test_source_fetches_verified_industry_and_board_labels_serially() -> None:
    calls = []
    replies = {
        EASTMONEY_STOCK_INFO_URL: response({
            "data": {"f57": "600519", "f127": "食品饮料"}
        }),
        EASTMONEY_STOCK_BLOCKS_URL: response({
            "data": {"diff": {
                "0": {"f12": "BK0477", "f14": "酿酒行业", "f3": 1.25,
                      "f128": "贵州茅台"},
                "1": {"f12": "BK0896", "f14": "白酒概念", "f3": -0.2,
                      "f128": "五粮液"},
            }}
        }),
    }

    async def transport(url, params, headers):
        calls.append((url, params, headers))
        return replies[url]

    source = EastmoneyStockClassificationSource(
        transport=transport,
        clock=lambda: datetime(2026, 7, 16, 12, tzinfo=UTC),
        minimum_interval=0,
    )

    snapshot = await source.fetch("600519")

    assert [call[0] for call in calls] == [
        EASTMONEY_STOCK_INFO_URL,
        EASTMONEY_STOCK_BLOCKS_URL,
    ]
    assert all(call[1]["secid"] == "1.600519" for call in calls)
    assert snapshot.symbol == "600519"
    assert snapshot.industry == "食品饮料"
    assert [board.name for board in snapshot.boards] == ["酿酒行业", "白酒概念"]
    assert [board.code for board in snapshot.boards] == ["BK0477", "BK0896"]
    assert len(snapshot.content_hash) == 64
    assert snapshot.raw_snapshot


@pytest.mark.asyncio
async def test_content_hash_is_stable_but_each_observation_has_its_own_id() -> None:
    replies = [
        response({"data": {"f57": "600519", "f127": "食品饮料"}}),
        response({"data": {"diff": [
            {"f12": "BK0477", "f14": "酿酒行业", "f3": 1.25, "f128": "贵州茅台"}
        ]}}),
    ]

    async def transport(_url, _params, _headers):
        return replies.pop(0)

    first = await EastmoneyStockClassificationSource(
        transport=transport,
        clock=lambda: datetime(2026, 7, 16, 12, tzinfo=UTC),
        minimum_interval=0,
    ).fetch("600519")

    replies.extend([
        response({"data": {"f57": "600519", "f127": "食品饮料"}}),
        response({"data": {"diff": [
            {"f12": "BK0477", "f14": "酿酒行业", "f3": 1.25, "f128": "贵州茅台"}
        ]}}),
    ])
    second = await EastmoneyStockClassificationSource(
        transport=transport,
        clock=lambda: datetime(2026, 7, 17, 12, tzinfo=UTC),
        minimum_interval=0,
    ).fetch("600519")

    assert first.classification_id != second.classification_id
    assert first.content_hash == second.content_hash
    assert first.observed_at != second.observed_at


@pytest.mark.asyncio
async def test_repository_preserves_repeated_unchanged_observations(tmp_path) -> None:
    replies = [
        response({"data": {"f57": "600519", "f127": "食品饮料"}}),
        response({"data": {"diff": [
            {"f12": "BK0477", "f14": "酿酒行业", "f3": 1.25,
             "f128": "贵州茅台"}
        ]}}),
    ]

    async def transport(_url, _params, _headers):
        return replies.pop(0)

    first = await EastmoneyStockClassificationSource(
        transport=transport,
        clock=lambda: datetime(2026, 7, 15, 8, tzinfo=UTC),
        minimum_interval=0,
    ).fetch("600519")
    replies.extend([
        response({"data": {"f57": "600519", "f127": "食品饮料"}}),
        response({"data": {"diff": [
            {"f12": "BK0477", "f14": "酿酒行业", "f3": 1.25,
             "f128": "贵州茅台"}
        ]}}),
    ])
    second = await EastmoneyStockClassificationSource(
        transport=transport,
        clock=lambda: datetime(2026, 7, 16, 8, tzinfo=UTC),
        minimum_interval=0,
    ).fetch("600519")
    repository = StockClassificationRepository(tmp_path / "classification.sqlite3")

    repository.append(first)
    repository.append(second)

    assert repository.count() == 2
    assert repository.latest("600519", date(2026, 7, 15)) == first
    assert repository.latest("600519", date(2026, 7, 16)) == second


@pytest.mark.asyncio
async def test_repository_latest_prefers_observation_time_over_append_order(
    tmp_path,
) -> None:
    replies = [
        response({"data": {"f57": "600519", "f127": "食品饮料"}}),
        response({"data": {"diff": [
            {"f12": "BK0477", "f14": "酿酒行业", "f3": 1.25,
             "f128": "贵州茅台"}
        ]}}),
    ]

    async def transport(_url, _params, _headers):
        return replies.pop(0)

    newer = await EastmoneyStockClassificationSource(
        transport=transport,
        clock=lambda: datetime(2026, 7, 16, 8, tzinfo=UTC),
        minimum_interval=0,
    ).fetch("600519")
    older = newer.model_copy(update={
        "classification_id": "stock-classification-" + "c" * 24,
        "observed_at": datetime(2026, 7, 15, 8, tzinfo=UTC),
    })
    repository = StockClassificationRepository(tmp_path / "classification.sqlite3")

    repository.append(newer)
    repository.append(older)

    assert repository.latest("600519", date(2026, 7, 16)) == newer


@pytest.mark.asyncio
async def test_repository_rejects_same_id_with_changed_canonical_record(
    tmp_path,
) -> None:
    replies = [
        response({"data": {"f57": "600519", "f127": "食品饮料"}}),
        response({"data": {"diff": [
            {"f12": "BK0477", "f14": "酿酒行业", "f3": 1.25,
             "f128": "贵州茅台"}
        ]}}),
    ]

    async def transport(_url, _params, _headers):
        return replies.pop(0)

    snapshot = await EastmoneyStockClassificationSource(
        transport=transport,
        clock=lambda: datetime(2026, 7, 16, 8, tzinfo=UTC),
        minimum_interval=0,
    ).fetch("600519")
    repository = StockClassificationRepository(tmp_path / "classification.sqlite3")
    repository.append(snapshot)

    changed_records = (
        snapshot.model_copy(update={"raw_snapshot": b'{"changed":true}'}),
        snapshot.model_copy(update={
            "observed_at": datetime(2026, 7, 16, 9, tzinfo=UTC)
        }),
        snapshot.model_copy(update={"industry": "白酒"}),
    )
    for changed in changed_records:
        with pytest.raises(
            StockClassificationIntegrityError,
            match="classification id collision",
        ):
            repository.append(changed)

    repository.append(snapshot)
    assert repository.count() == 1


@pytest.mark.asyncio
async def test_repository_as_of_uses_beijing_calendar_date(tmp_path) -> None:
    replies = [
        response({"data": {"f57": "600519", "f127": "食品饮料"}}),
        response({"data": {"diff": [
            {"f12": "BK0477", "f14": "酿酒行业", "f3": 1.25,
             "f128": "贵州茅台"}
        ]}}),
    ]

    async def transport(_url, _params, _headers):
        return replies.pop(0)

    snapshot = await EastmoneyStockClassificationSource(
        transport=transport,
        clock=lambda: datetime(2026, 7, 16, 16, 30, tzinfo=UTC),
        minimum_interval=0,
    ).fetch("600519")
    repository = StockClassificationRepository(tmp_path / "classification.sqlite3")
    repository.append(snapshot)

    assert repository.latest("600519", date(2026, 7, 16)) is None
    assert repository.latest("600519", date(2026, 7, 17)) == snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "info_payload,blocks_payload",
    [
        ({"data": {"f57": "000001", "f127": "银行"}}, {"data": {"diff": []}}),
        ({"data": {"f57": "600519", "f127": ""}}, {"data": {"diff": []}}),
        (
            {"data": {"f57": "600519", "f127": "食品饮料"}},
            {"data": {"diff": [{"f12": "NOT-BK", "f14": "错误标签"}]}},
        ),
    ],
)
async def test_source_rejects_mismatched_empty_or_malformed_data(
    info_payload, blocks_payload
) -> None:
    replies = [response(info_payload), response(blocks_payload)]

    async def transport(_url, _params, _headers):
        return replies.pop(0)

    source = EastmoneyStockClassificationSource(
        transport=transport, minimum_interval=0
    )

    with pytest.raises(ValueError):
        await source.fetch("600519")


@pytest.mark.asyncio
async def test_source_retries_one_transient_response() -> None:
    calls = []
    replies = [
        ClassificationHttpResponse(status_code=503, body=b"unavailable"),
        response({"data": {"f57": "600519", "f127": "食品饮料"}}),
        response({"data": {"diff": [
            {"f12": "BK0477", "f14": "酿酒行业", "f3": 0, "f128": "贵州茅台"}
        ]}}),
    ]

    async def transport(url, _params, _headers):
        calls.append(url)
        return replies.pop(0)

    snapshot = await EastmoneyStockClassificationSource(
        transport=transport, minimum_interval=0
    ).fetch("600519")

    assert snapshot.industry == "食品饮料"
    assert calls == [
        EASTMONEY_STOCK_INFO_URL,
        EASTMONEY_STOCK_INFO_URL,
        EASTMONEY_STOCK_BLOCKS_URL,
    ]


@pytest.mark.asyncio
async def test_service_persists_snapshot_and_repository_respects_cutoff(tmp_path) -> None:
    observed = [
        datetime(2026, 7, 15, 8, tzinfo=UTC),
        datetime(2026, 7, 16, 8, tzinfo=UTC),
    ]
    industry = ["食品饮料", "白酒"]

    class Source:
        async def fetch(self, symbol):
            replies = [
                response({"data": {"f57": symbol, "f127": industry.pop(0)}}),
                response({"data": {"diff": [
                    {"f12": "BK0477", "f14": "酿酒行业", "f3": 0,
                     "f128": "贵州茅台"}
                ]}}),
            ]

            async def transport(_url, _params, _headers):
                return replies.pop(0)

            return await EastmoneyStockClassificationSource(
                transport=transport, clock=lambda: observed.pop(0), minimum_interval=0
            ).fetch(symbol)

    repository = StockClassificationRepository(tmp_path / "classification.sqlite3")
    service = StockClassificationService(Source(), repository)

    first = await service.sync_symbol("600519")
    second = await service.sync_symbol("600519")

    assert repository.latest("600519", date(2026, 7, 15)).classification_id == first.classification_id
    assert repository.latest("600519", date(2026, 7, 16)).classification_id == second.classification_id
    assert repository.latest(
        "600519",
        date(2026, 7, 16),
        cutoff=datetime(2026, 7, 15, 12, tzinfo=UTC),
    ).classification_id == first.classification_id
    repository.append(second)
    assert repository.count() == 2

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repository.connection.execute(
            "UPDATE stock_classifications SET symbol='000001'"
        )

    repository.close()
