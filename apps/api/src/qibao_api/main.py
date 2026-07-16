import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from sqlalchemy import create_engine

from qibao_api.a_shares.diagnosis import AShareDiagnosisService
from qibao_api.a_shares.cockpit import StockDecisionCockpitService
from qibao_api.a_shares.assessment_ai import ReloadableAssessmentGateway
from qibao_api.a_shares.fundamentals import TdxFinanceSource
from qibao_api.a_shares.instrument_directory import AShareInstrument, AShareInstrumentDirectory
from qibao_api.a_shares.repository import AShareResearchRepository
from qibao_api.a_shares.preparation import AStockPreparationService
from qibao_api.gongbu.baidu_history import BaiduHistorySource
from qibao_api.gongbu.data_service import FallbackHistorySource, MarketDataService
from qibao_api.gongbu.tdx_client import create_tdx_client
from qibao_api.gongbu.tdx_history import TdxHistorySource
from qibao_api.gongbu.tencent_quotes import TencentQuoteSource, market_prefix
from qibao_api.convertible_bonds.adapters import EastmoneyBondValuationSource, EastmoneyClauseSource, TencentBondQuoteSource
from qibao_api.convertible_bonds.repository import BondClauseRepository
from qibao_api.convertible_bonds.service import ConvertibleBondService
from qibao_api.convertible_bonds.diagnosis_repository import BondDiagnosisRepository
from qibao_api.gongbu.news_collection import (
    EastmoneyGlobalNewsSource,
    EastmoneyStockNewsSource,
)
from qibao_api.gongbu.news_ingestion import NewsIngestionService
from qibao_api.gongbu.news_linking import DeterministicNewsLinker
from qibao_api.gongbu.news_repository import NewsRepository
from qibao_api.gongbu.fund_flow import (
    EastmoneyFundFlowSource,
    FundFlowRepository,
    FundFlowService,
)
from qibao_api.gongbu.stock_classification import (
    EastmoneyStockClassificationSource,
    StockClassificationRepository,
    StockClassificationService,
)
from qibao_api.libu_compliance.guard import (
    AuthorizedClassificationSource,
    AuthorizedFinanceSource,
    AuthorizedFundFlowSource,
    AuthorizedHistorySource,
    AuthorizedQuoteSource,
)
from qibao_api.libu_compliance.repository import ComplianceRepository
from qibao_api.routes.backtest import router as backtest_router
from qibao_api.routes.data import router as data_router
from qibao_api.routes.health import router as health_router
from qibao_api.routes.research import router as research_router
from qibao_api.routes.settings import router as settings_router
from qibao_api.settings import Settings
from qibao_api.settings_repository import AISettingsRepository, EffectiveAISettingsResolver
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.storage.database import create_schema
from qibao_api.storage.bar_repository import BarRepository
from qibao_api.storage.quote_repository import QuoteRepository
from qibao_api.xingbu.gate import RiskGate
from qibao_api.dongchang.repository import AuditFindingRepository
from qibao_api.routes.xingbu import router as xingbu_router
from qibao_api.routes.libu import router as libu_router
from qibao_api.routes.dongchang import router as dongchang_router
from qibao_api.routes.convertible_bonds import router as convertible_bonds_router
from qibao_api.routes.news import router as news_router
from qibao_api.zhongshu.news_ai import NewsAIGateway, UnavailableNewsAIProvider
from qibao_api.shangshu.briefing_repository import BriefingRepository
from qibao_api.shangshu.daily_briefing import DailyBriefingWorkflow
from qibao_api.shangshu.trading_calendar import (
    ExchangeCalendarsTradingDaySchedule,
    StoredTradingCalendar,
    TencentIndexTradingDaySignal,
)
from qibao_api.routes.briefings import router as briefings_router
from qibao_api.shangshu.postclose_context import RepositoryPostcloseContextSource
from qibao_api.shangshu.operations_repository import OperationsRepository
from qibao_api.shangshu.scheduler import DailyBriefingScheduler
from qibao_api.gongbu.backup_service import BackupService
from qibao_api.routes.operations import router as operations_router
from qibao_api.routes.decisions import router as decisions_router
from qibao_api.shangshu.decision_repository import DecisionRepository
from qibao_api.shangshu.decision_runtime import (
    CandidateFactorInputSource,
    DecisionSymbolSource,
    DecisionPhaseRunner,
    DeterministicIntradayEvaluator,
    RepositoryCandidateFactorSource,
    RepositoryComplianceSource,
    RepositoryEvidenceSource,
    RepositoryMarketOutcomeSource,
    RepositoryRiskSource,
    TencentPollingMarketFeed,
)
from qibao_api.shangshu.intraday_monitor import IntradayMonitor, PollStateRepository
from qibao_api.zhongshu.decision_ai import DecisionAIGateway
from qibao_api.zhongshu.premarket_decision import PremarketDecisionService
from qibao_api.zhongshu.postclose_review import PostcloseReviewService


logger = logging.getLogger(__name__)


async def _scheduler_loop(
    scheduler, write_gate: asyncio.Lock, interval_seconds: int
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with write_gate:
                now = datetime.now(timezone.utc)
                await asyncio.to_thread(_runtime_tick, scheduler, now)
        except Exception:
            logger.exception("scheduled briefing tick failed")


def _runtime_tick(scheduler, now: datetime) -> None:
    scheduler.tick(now)
    scheduler.tick_intraday(now)


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    write_gate = asyncio.Lock()
    application.state.write_gate = write_gate
    ai_settings_repository = AISettingsRepository(settings.data_dir)
    application.state.ai_settings_repository = ai_settings_repository
    effective_ai_settings = EffectiveAISettingsResolver(
        ai_settings_repository,
        fallback=getattr(settings, "initial_ai_settings", None),
    )
    application.state.effective_ai_settings = effective_ai_settings
    engine = create_engine(settings.database_url)
    create_schema(engine)
    compliance = ComplianceRepository(settings.data_dir / "compliance.sqlite3")
    audit_repository = AuditFindingRepository(settings.data_dir / "audit.sqlite3")
    application.state.audit_repository = audit_repository
    application.state.compliance_repository = compliance
    compliance.set_feature_sources("realtime_quotes", "a_share", ("tencent",))
    compliance.set_feature_sources("a_share_finance", "a_share", ("mootdx",))
    compliance.set_feature_sources("history_sync.mootdx", "a_share", ("mootdx",))
    compliance.set_feature_sources("history_sync.baidu", "a_share", ("baidu",))
    compliance.set_feature_sources("bond_quotes", "convertible_bond", ("tencent",))
    compliance.set_feature_sources("bond_clauses", "convertible_bond", ("eastmoney",))
    compliance.set_feature_sources("bond_valuations", "convertible_bond", ("eastmoney",))
    compliance.set_feature_sources("market_news", "a_share", ("eastmoney",))
    compliance.set_feature_sources(
        "stock_classification", "a_share", ("eastmoney",)
    )
    compliance.set_feature_sources("stock_fund_flow", "a_share", ("eastmoney",))
    bond_repository = BondClauseRepository(engine)
    bond_repository.initialize()
    diagnosis_repository = BondDiagnosisRepository(settings.data_dir / "bond-diagnoses.sqlite3")
    news_repository = NewsRepository(settings.data_dir / "news.sqlite3")
    application.state.news_repository = news_repository
    stock_classification_repository = StockClassificationRepository(
        settings.data_dir / "stock-classifications.sqlite3"
    )
    application.state.stock_classification_repository = (
        stock_classification_repository
    )
    fund_flow_repository = FundFlowRepository(
        settings.data_dir / "fund-flow.sqlite3"
    )
    application.state.fund_flow_repository = fund_flow_repository
    a_share_research_repository = AShareResearchRepository(
        settings.data_dir / "a-share-research.sqlite3"
    )
    application.state.a_share_research_repository = a_share_research_repository
    briefing_repository = BriefingRepository(settings.data_dir / "briefings.sqlite3")
    application.state.briefing_repository = briefing_repository
    decision_repository = DecisionRepository(
        getattr(settings, "decision_database_path", settings.data_dir / "decisions.sqlite3")
    )
    application.state.decision_repository = decision_repository
    async with httpx.AsyncClient(timeout=10) as client:
        application.state.a_share_quote_source = TencentQuoteSource(client)
        with httpx.Client(timeout=10) as history_client:
            history_sources = []
            try:
                tdx_source = TdxHistorySource(create_tdx_client())
                history_sources.append(
                    AuthorizedHistorySource(
                        tdx_source,
                        compliance,
                        "history_sync.mootdx",
                        "a_share",
                    )
                )
            except Exception:
                pass
            history_sources.append(
                AuthorizedHistorySource(
                    BaiduHistorySource(history_client),
                    compliance,
                    "history_sync.baidu",
                    "a_share",
                )
            )
            bar_repository = BarRepository(
                settings.data_dir / "market.duckdb",
                settings.data_dir / "parquet" / "a-shares",
            )
            trading_calendar = StoredTradingCalendar(
                bar_repository,
                live_signal=TencentIndexTradingDaySignal(history_client),
                schedule=ExchangeCalendarsTradingDaySchedule(),
            )
            application.state.bar_repository = bar_repository
            application.state.market_data_service = MarketDataService(
                FallbackHistorySource(history_sources),
                bar_repository,
            )
            application.state.pipeline = ResearchPipeline(
                AuthorizedQuoteSource(
                    TencentQuoteSource(client),
                    compliance,
                    ("realtime_quotes",),
                    "a_share",
                ),
                QuoteRepository(engine),
                RiskGate(),
            )
            application.state.a_share_diagnosis_service = AShareDiagnosisService(
                bar_repository,
                AuthorizedQuoteSource(
                    TencentQuoteSource(client),
                    compliance,
                    ("realtime_quotes",),
                    "a_share",
                ),
                AuthorizedFinanceSource(
                    TdxFinanceSource(), compliance, "a_share_finance", "a_share"
                ),
                news_repository,
                a_share_research_repository,
                classification_repository=stock_classification_repository,
                fund_flow_repository=fund_flow_repository,
            )
            application.state.bond_repository = bond_repository
            application.state.bond_service = ConvertibleBondService(
                TencentBondQuoteSource(client), EastmoneyClauseSource(client=client),
                TencentQuoteSource(client), bond_repository, compliance,
                diagnosis_repository,
                EastmoneyBondValuationSource(client=client),
            )
            application.state.news_service = NewsIngestionService(
                EastmoneyGlobalNewsSource(client=client),
                news_repository,
                DeterministicNewsLinker(
                    instrument_aliases={},
                    industry_keywords={},
                    theme_keywords={
                        "政策支持": ("支持政策", "专项政策", "政策支持"),
                        "业绩变化": ("业绩预增", "业绩预减", "业绩快报"),
                        "并购重组": ("并购", "重组", "资产收购"),
                        "股份回购": ("股份回购", "回购方案"),
                        "风险事件": ("立案调查", "风险提示", "退市风险"),
                    },
                ),
                compliance,
                NewsAIGateway(
                    UnavailableNewsAIProvider(),
                    provider_name="unconfigured",
                    model="none",
                    prompt_version="news-v1",
                ),
                stock_source=EastmoneyStockNewsSource(client=client),
            )
            application.state.stock_classification_service = (
                StockClassificationService(
                    AuthorizedClassificationSource(
                        EastmoneyStockClassificationSource(client=client),
                        compliance,
                        "stock_classification",
                        "a_share",
                    ),
                    stock_classification_repository,
                )
            )
            application.state.fund_flow_service = FundFlowService(
                AuthorizedFundFlowSource(
                    EastmoneyFundFlowSource(client=client),
                    compliance,
                    "stock_fund_flow",
                    "a_share",
                ),
                fund_flow_repository,
            )
            application.state.a_share_preparation_service = AStockPreparationService(
                bar_repository,
                application.state.market_data_service,
                application.state.a_share_diagnosis_service,
                application.state.news_service,
                news_repository,
                trading_calendar,
                classification_service=(
                    application.state.stock_classification_service
                ),
                fund_flow_service=application.state.fund_flow_service,
                lock_dir=settings.data_dir / "preparation-locks",
            )
            application.state.briefing_workflow = DailyBriefingWorkflow(
                news_repository,
                briefing_repository,
                trading_calendar,
                RepositoryPostcloseContextSource(decision_repository, audit_repository),
            )
            application.state.decision_calendar = trading_calendar
            operations_repository = OperationsRepository(
                settings.data_dir / "operations.sqlite3"
            )
            application.state.operations_repository = operations_repository
            decision_candidate_source = RepositoryCandidateFactorSource(
                application.state.a_share_diagnosis_service
            )
            decision_compliance_source = RepositoryComplianceSource(compliance)
            decision_risk_source = RepositoryRiskSource(
                audit_repository, application.state.a_share_diagnosis_service,
                news_repository=news_repository,
                classification_repository=stock_classification_repository,
                fund_flow_repository=fund_flow_repository,
                trading_calendar=trading_calendar,
            )
            decision_evidence_source = RepositoryEvidenceSource(news_repository)
            decision_market_feed = TencentPollingMarketFeed(history_client, compliance)
            decision_evaluator = DeterministicIntradayEvaluator()
            poll_state_repository = PollStateRepository(
                settings.data_dir / "intraday-poll.sqlite3"
            )
            application.state.poll_state_repository = poll_state_repository
            premarket_decision = PremarketDecisionService(
                candidate_service=decision_candidate_source,
                news_repository=news_repository,
                compliance_checker=decision_compliance_source,
                market_risk_summary=decision_risk_source,
                ai_gateway=DecisionAIGateway(
                    UnavailableNewsAIProvider(), provider_name="unconfigured",
                    model="none", prompt_version="decision-v1",
                ),
                decision_repository=decision_repository,
                trading_calendar=application.state.decision_calendar,
                clock=lambda: datetime.now(timezone.utc),
            )
            decision_symbols = DecisionSymbolSource(
                decision_repository,
                decision_candidate_source,
            )

            intraday_monitor = IntradayMonitor(
                feed=decision_market_feed,
                calendar=application.state.decision_calendar,
                state_repository=poll_state_repository,
                focus_symbols=decision_symbols,
                universe_symbols=decision_symbols,
                decision_repository=decision_repository,
                evaluator=decision_evaluator,
                candidate_factor_port=CandidateFactorInputSource(decision_candidate_source),
                risk_port=decision_risk_source,
                compliance_port=decision_compliance_source,
                evidence_port=decision_evidence_source,
            )
            decision_outcome_source = RepositoryMarketOutcomeSource(
                decision_repository, bar_repository
            )
            postclose_review = PostcloseReviewService(
                decision_repository=decision_repository,
                market_outcome_source=decision_outcome_source,
                audit_repository=audit_repository,
            )
            decision_phase_runner = DecisionPhaseRunner(
                repository=decision_repository, premarket=premarket_decision,
                intraday_monitor=intraday_monitor, postclose=postclose_review,
            )
            application.state.decision_candidate_source = decision_candidate_source
            application.state.decision_compliance_source = decision_compliance_source
            application.state.decision_risk_source = decision_risk_source
            application.state.decision_evidence_source = decision_evidence_source
            application.state.decision_market_feed = decision_market_feed
            application.state.decision_evaluator = decision_evaluator
            application.state.decision_outcome_source = decision_outcome_source
            application.state.intraday_monitor = intraday_monitor
            application.state.decision_phase_runner = decision_phase_runner
            application.state.scheduler = DailyBriefingScheduler(
                application.state.briefing_workflow,
                trading_calendar,
                operations_repository,
                decision_workflow=decision_phase_runner,
                intraday_monitor=intraday_monitor,
            )
            application.state.backup_service = BackupService(
                settings.data_dir, bar_repository
            )
            scheduler_task = None
            a_share_instrument_directory = AShareInstrumentDirectory(
                settings.data_dir / "a-share-instruments.sqlite3"
            )
            try:
                application.state.a_share_instrument_directory = a_share_instrument_directory
                application.state.a_share_cockpit_service = StockDecisionCockpitService(
                    a_share_instrument_directory,
                    application.state.a_share_diagnosis_service,
                    decision_repository,
                    preparation_service=application.state.a_share_preparation_service,
                    trading_calendar=trading_calendar,
                    operations_repository=operations_repository,
                    assessor_ai=ReloadableAssessmentGateway(
                        effective_ai_settings,
                        client=client,
                    ),
                )
                observed_at = datetime.now(timezone.utc)
                for symbol in bar_repository.symbols_with_history(1, observed_at.date()):
                    if a_share_instrument_directory.resolve(symbol) is None:
                        a_share_instrument_directory.observe(
                            AShareInstrument(
                                symbol=symbol,
                                name=symbol,
                                exchange=market_prefix(symbol),
                                observed_at=observed_at,
                                quote_quality="unavailable",
                            )
                        )
                scheduler_task = (
                    asyncio.create_task(_scheduler_loop(
                        application.state.scheduler,
                        write_gate,
                        settings.scheduler_interval_seconds,
                    ))
                    if getattr(settings, "scheduler_enabled", False) else None
                )
                yield
            finally:
                if scheduler_task is not None:
                    scheduler_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await scheduler_task
                bond_repository.close()
                diagnosis_repository.close()
                news_repository.close()
                stock_classification_repository.close()
                fund_flow_repository.close()
                briefing_repository.close()
                compliance.close()
                audit_repository.close()
                operations_repository.close()
                a_share_research_repository.close()
                a_share_instrument_directory.close()
                poll_state_repository.close()
                decision_repository.close()
    engine.dispose()


app = FastAPI(title="小七宝量化决策台", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def serialize_runtime_access(request: Request, call_next):
    write_gate = getattr(request.app.state, "write_gate", None)
    if write_gate is None:
        return await call_next(request)
    path = request.url.path
    if request.method == "GET" and (
        path == "/api/v1/a-shares/candidates"
        or (path.startswith("/api/v1/a-shares/") and path.endswith(("/diagnosis", "/cockpit")))
    ):
        return await call_next(request)
    async with write_gate:
        return await call_next(request)
app.include_router(health_router)
app.include_router(research_router)
app.include_router(data_router)
app.include_router(backtest_router)
app.include_router(xingbu_router)
app.include_router(libu_router)
app.include_router(dongchang_router)
app.include_router(convertible_bonds_router)
app.include_router(news_router)
app.include_router(briefings_router)
app.include_router(operations_router)
app.include_router(decisions_router)
app.include_router(settings_router)
