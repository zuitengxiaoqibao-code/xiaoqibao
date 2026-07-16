import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI

import qibao_api.main as main_module
from qibao_api.libu_compliance.guard import AuthorizedHistorySource, AuthorizedQuoteSource
from qibao_api.libu_compliance.repository import ComplianceRepository
from qibao_api.shangshu.decision_repository import DecisionRepository
from qibao_api.shangshu.decision_runtime import (
    DecisionPhaseRunner,
    DeterministicIntradayEvaluator,
    RepositoryCandidateFactorSource,
    RepositoryComplianceSource,
    RepositoryEvidenceSource,
    RepositoryMarketOutcomeSource,
    RepositoryRiskSource,
    TencentPollingMarketFeed,
)


class FakeSettings:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'qibao.db').as_posix()}"


def test_runtime_tick_runs_fixed_slots_and_layered_intraday_once_serially() -> None:
    calls = []
    scheduler = type("Scheduler", (), {
        "tick": lambda _self, now: calls.append(("fixed", now)),
        "tick_intraday": lambda _self, now: calls.append(("layered", now)),
    })()
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)

    main_module._runtime_tick(scheduler, now)

    assert calls == [("fixed", now), ("layered", now)]


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
        assert compliance.list_feature_source_history("paper_orders", "a_share") == []
        assert len(compliance.list_feature_source_history("history_sync.baidu", "a_share")) == 1
        assert len(compliance.list_feature_source_history("market_news", "a_share")) == 1
        news_repository = application.state.news_repository
        assert application.state.news_service.repository is news_repository
        briefing_repository = application.state.briefing_repository
        assert application.state.briefing_workflow.briefing_repository is briefing_repository
        decision_repository = application.state.decision_repository
        assert isinstance(decision_repository, DecisionRepository)
        assert application.state.decision_phase_runner.repository is decision_repository
        assert isinstance(application.state.decision_phase_runner, DecisionPhaseRunner)
        assert isinstance(application.state.decision_candidate_source, RepositoryCandidateFactorSource)
        assert isinstance(application.state.decision_compliance_source, RepositoryComplianceSource)
        assert isinstance(application.state.decision_risk_source, RepositoryRiskSource)
        assert isinstance(application.state.decision_evidence_source, RepositoryEvidenceSource)
        assert isinstance(application.state.decision_market_feed, TencentPollingMarketFeed)
        assert isinstance(application.state.decision_evaluator, DeterministicIntradayEvaluator)
        assert isinstance(application.state.decision_outcome_source, RepositoryMarketOutcomeSource)
        assert application.state.scheduler.decision_workflow is application.state.decision_phase_runner
        assert application.state.scheduler.intraday_monitor is application.state.intraday_monitor

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        compliance.list_feature_source_history("realtime_quotes", "a_share")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        news_repository.events()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        briefing_repository.reports()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        decision_repository.cycles()


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


@pytest.mark.asyncio
async def test_lifespan_closes_instrument_directory_when_seed_fails(
    tmp_path, monkeypatch
) -> None:
    closed = []

    class Directory:
        def __init__(self, _path) -> None:
            pass

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(main_module, "Settings", lambda: FakeSettings(tmp_path))
    monkeypatch.setattr(main_module, "AShareInstrumentDirectory", Directory)
    monkeypatch.setattr(
        main_module, "create_tdx_client", lambda: (_ for _ in ()).throw(RuntimeError("offline"))
    )
    monkeypatch.setattr(
        main_module.BarRepository,
        "symbols_with_history",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("seed failed")),
    )

    with pytest.raises(RuntimeError, match="seed failed"):
        async with main_module.lifespan(FastAPI()):
            pass

    assert closed == [True]
