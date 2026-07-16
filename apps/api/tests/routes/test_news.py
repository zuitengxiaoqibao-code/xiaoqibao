from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qibao_api.contracts.news import (
    AIInterpretation,
    EvidenceCitation,
    InterpretationStatement,
    NormalizedNewsEvent,
)
from qibao_api.dependencies import get_news_repository, get_news_service
from qibao_api.routes.news import router
from qibao_api.libu_compliance.repository import SourceAuthorizationError


NOW = datetime(2026, 7, 14, 1, 0, tzinfo=UTC)


class Service:
    async def sync(self):
        return {"fetched": 3, "inserted": 2, "clusters": 2, "events": 2}


class Repository:
    saved_corrections = []

    def articles(self):
        return [object()]

    def clusters(self):
        return [{"cluster": object()}]

    def events(self):
        return [NormalizedNewsEvent(
            event_id="event-news-1", event_type="market_news", headline="政策发布",
            occurred_at=NOW, normalized_at=NOW, affected_instruments=(),
            industries=(), themes=("政策支持",),
            citations=(EvidenceCitation(
                citation_id="citation-news-1", article_id="news-1",
                canonical_url="https://news.example/1", publisher="测试来源",
                published_at=NOW, quoted_text="政策发布", content_hash="a" * 64,
            ),),
            association_confidence=Decimal("0.60"), review_state="pending",
        )]

    def interpretations(self):
        citation = self.events()[0].citations[0]
        return [AIInterpretation(
            interpretation_id="interpretation-1", event_id="event-news-1",
            generated_at=NOW, provider="deterministic", model="evidence-summary-v1",
            prompt_version="news-v1", latency_ms=2, degraded=True,
            statements=(InterpretationStatement(
                statement_id="s1", kind="fact", text="政策发布",
                citation_ids=(citation.citation_id,),
            ),), citations=(citation,),
        )]

    def append_correction(self, correction):
        self.saved_corrections.append(correction)
        return True

    def corrections(self):
        return list(self.saved_corrections)


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_news_service] = lambda: Service()
    app.dependency_overrides[get_news_repository] = lambda: Repository()
    return TestClient(app)


def test_news_sync_and_event_routes_expose_auditable_results() -> None:
    with client() as test_client:
        synced = test_client.post("/api/v1/news/sync")
        events = test_client.get("/api/v1/news/events")
        interpretations = test_client.get("/api/v1/news/interpretations")

    assert synced.status_code == 200
    assert synced.json()["inserted"] == 2
    assert events.status_code == 200
    assert events.json()[0]["citations"][0]["article_id"] == "news-1"
    assert interpretations.status_code == 200
    assert interpretations.json()[0]["degraded"] is True


def test_news_sync_maps_missing_authorization_to_clear_403() -> None:
    class Unauthorized:
        async def sync(self):
            raise SourceAuthorizationError("eastmoney")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_news_service] = lambda: Unauthorized()

    response = TestClient(app).post("/api/v1/news/sync")

    assert response.status_code == 403
    assert response.json()["detail"] == "A 股新闻数据源尚未授权：eastmoney"


def test_news_quality_and_human_correction_routes() -> None:
    Repository.saved_corrections = []
    with client() as test_client:
        corrected = test_client.post("/api/v1/news/corrections", json={
            "event_id": "event-news-1", "reason": "人工确认事件分类",
            "review_state": "verified", "industries": ["高端制造"],
        })
        quality = test_client.get("/api/v1/news/quality")

    assert corrected.status_code == 200
    assert corrected.json()["correction_id"].startswith("correction-")
    assert quality.status_code == 200
    assert quality.json()["human_correction_rate"] == "1.0000"
