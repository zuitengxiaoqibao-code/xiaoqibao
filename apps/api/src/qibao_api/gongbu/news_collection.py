import asyncio
import hashlib
import html
import json
import re
import time
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict

from qibao_api.contracts.news import NewsArticle
from qibao_api.contracts.instruments import validate_a_share_code


EASTMONEY_GLOBAL_NEWS_URL = (
    "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
)
EASTMONEY_STOCK_NEWS_URL = "https://search-api-web.eastmoney.com/search/jsonp"
CHINA_TZ = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


@dataclass(frozen=True)
class NewsHttpResponse:
    status_code: int
    body: bytes


NewsTransport = Callable[
    [str, dict[str, str], dict[str, str]], Awaitable[NewsHttpResponse]
]


class NewsCluster(BaseModel):
    model_config = ConfigDict(frozen=True)

    primary_article_id: str
    article_ids: tuple[str, ...]
    source_urls: tuple[str, ...]


class EastmoneyGlobalNewsSource:
    def __init__(
        self,
        transport: NewsTransport | None = None,
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

    async def fetch(self, page_size: int = 50) -> list[NewsArticle]:
        params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(page_size),
            "req_trace": str(uuid.uuid4()),
        }
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://kuaixun.eastmoney.com/",
        }
        response: NewsHttpResponse | None = None
        for attempt in range(2):
            try:
                async with self._request_lock:
                    await self._wait_for_rate_limit()
                    response = await self._request(params, headers)
            except (OSError, httpx.TransportError):
                if attempt == 1:
                    raise
                continue
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt == 1:
                raise OSError(f"Eastmoney news status {response.status_code}")
        assert response is not None
        if response.status_code != 200:
            raise OSError(f"Eastmoney news status {response.status_code}")
        return self._parse(response.body)

    async def _wait_for_rate_limit(self) -> None:
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = self.minimum_interval - (now - self._last_request_at)
            if remaining > 0:
                await self.sleep(remaining)
                now = self.monotonic()
        self._last_request_at = now

    async def _request(
        self, params: dict[str, str], headers: dict[str, str]
    ) -> NewsHttpResponse:
        if self.transport is not None:
            return await self.transport(EASTMONEY_GLOBAL_NEWS_URL, params, headers)
        if self.client is not None:
            result = await self.client.get(
                EASTMONEY_GLOBAL_NEWS_URL, params=params, headers=headers
            )
            return NewsHttpResponse(result.status_code, result.content)
        async with httpx.AsyncClient(timeout=10) as client:
            result = await client.get(
                EASTMONEY_GLOBAL_NEWS_URL, params=params, headers=headers
            )
            return NewsHttpResponse(result.status_code, result.content)

    def _parse(self, raw: bytes) -> list[NewsArticle]:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Eastmoney news response is not valid JSON") from error
        rows = (payload.get("data") or {}).get("fastNewsList") or []
        fetched_at = self.clock()
        articles: list[NewsArticle] = []
        for row in rows:
            row_raw = json.dumps(
                row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            title = str(row.get("title") or row.get("summary") or "").strip()
            summary = str(row.get("summary") or "").strip() or None
            published_at = _parse_eastmoney_time(row.get("showTime"))
            source_url = str(row.get("url") or "").strip()
            semantic_payload = json.dumps(
                {
                    "published_at": published_at.isoformat(),
                    "summary": summary,
                    "title": title,
                    "url": source_url,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            content_hash = hashlib.sha256(semantic_payload).hexdigest()
            provider_code = str(row.get("code") or "").strip()
            article_id = (
                f"{provider_code}-{content_hash[:16]}"
                if provider_code
                else content_hash[:24]
            )
            url = source_url or f"{EASTMONEY_GLOBAL_NEWS_URL}#{article_id}"
            articles.append(
                NewsArticle(
                    article_id=article_id,
                    canonical_url=url,
                    publisher="东方财富",
                    title=title,
                    summary=summary,
                    published_at=published_at,
                    fetched_at=fetched_at,
                    content_hash=content_hash,
                    raw_snapshot=row_raw,
                    source_verified=url.startswith("https://") and bool(title),
                )
            )
        return articles


class EastmoneyStockNewsSource:
    def __init__(
        self,
        transport: NewsTransport | None = None,
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

    async def fetch(self, symbol: str, page_size: int = 20) -> list[NewsArticle]:
        symbol = validate_a_share_code(symbol)
        if not 1 <= page_size <= 50:
            raise ValueError("page_size must be between 1 and 50")
        callback = "jQuery_news"
        query = {
            "uid": "",
            "keyword": symbol,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": page_size,
                    "preTag": "",
                    "postTag": "",
                }
            },
        }
        params = {
            "cb": callback,
            "param": json.dumps(query, ensure_ascii=False, separators=(",", ":")),
        }
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://so.eastmoney.com/",
        }
        response: NewsHttpResponse | None = None
        for attempt in range(2):
            try:
                async with self._request_lock:
                    await self._wait_for_rate_limit()
                    response = await self._request(params, headers)
            except (OSError, httpx.TransportError):
                if attempt == 1:
                    raise
                continue
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt == 1:
                raise OSError(f"Eastmoney stock news status {response.status_code}")
        assert response is not None
        if response.status_code != 200:
            raise OSError(f"Eastmoney stock news status {response.status_code}")
        return self._parse(response.body, callback)

    async def _wait_for_rate_limit(self) -> None:
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = self.minimum_interval - (now - self._last_request_at)
            if remaining > 0:
                await self.sleep(remaining)
                now = self.monotonic()
        self._last_request_at = now

    async def _request(
        self, params: dict[str, str], headers: dict[str, str]
    ) -> NewsHttpResponse:
        if self.transport is not None:
            return await self.transport(EASTMONEY_STOCK_NEWS_URL, params, headers)
        if self.client is not None:
            result = await self.client.get(
                EASTMONEY_STOCK_NEWS_URL, params=params, headers=headers
            )
            return NewsHttpResponse(result.status_code, result.content)
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.get(
                EASTMONEY_STOCK_NEWS_URL, params=params, headers=headers
            )
            return NewsHttpResponse(result.status_code, result.content)

    def _parse(self, raw: bytes, callback: str) -> list[NewsArticle]:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Eastmoney stock news response is not valid JSONP") from error
        prefix = f"{callback}("
        if not text.startswith(prefix) or not text.endswith(")"):
            raise ValueError("Eastmoney stock news response is not valid JSONP")
        try:
            payload = json.loads(text[len(prefix):-1])
        except json.JSONDecodeError as error:
            raise ValueError("Eastmoney stock news response is not valid JSONP") from error
        if payload.get("code") != 0:
            raise OSError(str(payload.get("msg") or "Eastmoney stock news request failed"))
        rows = (payload.get("result") or {}).get("cmsArticleWebOld") or []
        if not rows and int(payload.get("hitsTotal") or 0) > 0:
            raise OSError("Eastmoney stock news response is missing article rows")
        fetched_at = self.clock()
        articles = []
        for row in rows:
            row_raw = json.dumps(
                row, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            title = _plain_text(row.get("title"))
            summary = _plain_text(row.get("content")) or None
            published_at = _parse_eastmoney_time(row.get("date"))
            source_url = str(row.get("url") or "").strip()
            provider_code = str(row.get("code") or "").strip()
            publisher = _plain_text(row.get("mediaName")) or "东方财富"
            semantic_payload = json.dumps(
                {
                    "published_at": published_at.isoformat(),
                    "publisher": publisher,
                    "summary": summary,
                    "title": title,
                    "url": source_url,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            content_hash = hashlib.sha256(semantic_payload).hexdigest()
            article_id = (
                f"{provider_code}-{content_hash[:16]}"
                if provider_code else content_hash[:24]
            )
            url = source_url or f"{EASTMONEY_STOCK_NEWS_URL}#{article_id}"
            host = (urlparse(url).hostname or "").lower()
            articles.append(NewsArticle(
                article_id=article_id,
                canonical_url=url,
                publisher=publisher,
                title=title,
                summary=summary,
                published_at=published_at,
                fetched_at=fetched_at,
                content_hash=content_hash,
                raw_snapshot=row_raw,
                source_verified=(
                    bool(title)
                    and (host == "eastmoney.com" or host.endswith(".eastmoney.com"))
                ),
            ))
        return articles


def _plain_text(value: object) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_eastmoney_time(value: object) -> datetime:
    if not value:
        raise ValueError("Eastmoney news item is missing showTime")
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=CHINA_TZ) if parsed.tzinfo is None else parsed


def _normalized_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).lower()
    normalized = re.sub(r"^(?:转载|快讯|突发)[:：\s-]*", "", normalized)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized)


def _near_duplicate(left: NewsArticle, right: NewsArticle) -> bool:
    left_title = _normalized_title(left.title)
    right_title = _normalized_title(right.title)
    return bool(left_title and right_title) and SequenceMatcher(
        None, left_title, right_title
    ).ratio() >= 0.9


def deduplicate_articles(articles: list[NewsArticle]) -> list[NewsCluster]:
    parents = list(range(len(articles)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(articles)):
        for right in range(left + 1, len(articles)):
            if (
                articles[left].canonical_url == articles[right].canonical_url
                or articles[left].content_hash == articles[right].content_hash
                or _near_duplicate(articles[left], articles[right])
            ):
                union(left, right)

    groups: dict[int, list[NewsArticle]] = {}
    for index, article in enumerate(articles):
        groups.setdefault(find(index), []).append(article)
    return [
        NewsCluster(
            primary_article_id=items[0].article_id,
            article_ids=tuple(item.article_id for item in items),
            source_urls=tuple(dict.fromkeys(item.canonical_url for item in items)),
        )
        for items in groups.values()
    ]
