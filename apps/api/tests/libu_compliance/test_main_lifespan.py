import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI

import qibao_api.main as main_module
from qibao_api.libu_compliance.guard import AuthorizedHistorySource, AuthorizedQuoteSource
from qibao_api.libu_compliance.repository import ComplianceRepository


class FakeSettings:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'qibao.db').as_posix()}"


@pytest.mark.asyncio
async def test_lifespan_injects_guarded_production_sources_and_closes_compliance(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(main_module, "Settings", lambda: FakeSettings(tmp_path))
    monkeypatch.setattr(
        main_module, "create_tdx_client", lambda: (_ for _ in ()).throw(RuntimeError("offline"))
    )
    application = FastAPI()

    async with main_module.lifespan(application):
        compliance = application.state.compliance_repository
        assert isinstance(compliance, ComplianceRepository)
        assert isinstance(application.state.pipeline.quote_source, AuthorizedQuoteSource)
        fallback = application.state.market_data_service.source
        assert fallback.sources
        assert all(isinstance(source, AuthorizedHistorySource) for source in fallback.sources)
        assert len(compliance.list_feature_source_history("realtime_quotes", "a_share")) == 1
        assert len(compliance.list_feature_source_history("paper_orders", "a_share")) == 1
        assert len(compliance.list_feature_source_history("history_sync.baidu", "a_share")) == 1
        assert len(compliance.list_feature_source_history("market_news", "a_share")) == 1
        news_repository = application.state.news_repository
        assert application.state.news_service.repository is news_repository
        briefing_repository = application.state.briefing_repository
        assert application.state.briefing_workflow.briefing_repository is briefing_repository

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        compliance.list_feature_source_history("realtime_quotes", "a_share")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        news_repository.events()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        briefing_repository.reports()


@pytest.mark.asyncio
async def test_lifespan_dependency_registration_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_module, "Settings", lambda: FakeSettings(tmp_path))
    monkeypatch.setattr(
        main_module, "create_tdx_client", lambda: (_ for _ in ()).throw(RuntimeError("offline"))
    )

    async with main_module.lifespan(FastAPI()):
        pass
    async with main_module.lifespan(FastAPI()):
        pass

    repository = ComplianceRepository(tmp_path / "compliance.sqlite3")
    assert len(repository.list_feature_source_history("realtime_quotes", "a_share")) == 1
    assert len(repository.list_feature_source_history("history_sync.baidu", "a_share")) == 1
