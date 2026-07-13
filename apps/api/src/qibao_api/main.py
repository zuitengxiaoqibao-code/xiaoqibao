from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine

from qibao_api.gongbu.baidu_history import BaiduHistorySource
from qibao_api.gongbu.data_service import FallbackHistorySource, MarketDataService
from qibao_api.gongbu.tdx_client import create_tdx_client
from qibao_api.gongbu.tdx_history import TdxHistorySource
from qibao_api.gongbu.tencent_quotes import TencentQuoteSource
from qibao_api.bingbu.paper_broker import PaperBroker
from qibao_api.bingbu.paper_service import PaperTradingService
from qibao_api.hubu.repository import PaperRepository
from qibao_api.libu_compliance.guard import AuthorizedHistorySource, AuthorizedQuoteSource
from qibao_api.libu_compliance.repository import ComplianceRepository
from qibao_api.routes.backtest import router as backtest_router
from qibao_api.routes.data import router as data_router
from qibao_api.routes.health import router as health_router
from qibao_api.routes.research import router as research_router
from qibao_api.routes.paper import router as paper_router
from qibao_api.settings import Settings
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.storage.database import create_schema
from qibao_api.storage.bar_repository import BarRepository
from qibao_api.storage.quote_repository import QuoteRepository
from qibao_api.xingbu.gate import RiskGate
from qibao_api.dongchang.repository import AuditFindingRepository
from qibao_api.routes.xingbu import router as xingbu_router
from qibao_api.routes.libu import router as libu_router
from qibao_api.routes.dongchang import router as dongchang_router


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url)
    create_schema(engine)
    compliance = ComplianceRepository(settings.data_dir / "compliance.sqlite3")
    audit_repository = AuditFindingRepository(settings.data_dir / "audit.sqlite3")
    application.state.audit_repository = audit_repository
    application.state.compliance_repository = compliance
    compliance.set_feature_sources("realtime_quotes", "a_share", ("tencent",))
    compliance.set_feature_sources("paper_orders", "a_share", ("tencent",))
    compliance.set_feature_sources("history_sync.mootdx", "a_share", ("mootdx",))
    compliance.set_feature_sources("history_sync.baidu", "a_share", ("baidu",))
    async with httpx.AsyncClient(timeout=10) as client:
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
            application.state.market_data_service = MarketDataService(
                FallbackHistorySource(history_sources),
                bar_repository,
            )
            application.state.pipeline = ResearchPipeline(
                AuthorizedQuoteSource(
                    TencentQuoteSource(client),
                    compliance,
                    ("realtime_quotes", "paper_orders"),
                    "a_share",
                ),
                QuoteRepository(engine),
                RiskGate(),
            )
            paper_repository = PaperRepository(settings.data_dir / "paper.sqlite3")
            application.state.paper_repository = paper_repository
            application.state.paper_service = PaperTradingService(
                application.state.pipeline,
                PaperBroker(paper_repository),
            )
            try:
                yield
            finally:
                paper_repository.close()
                compliance.close()
                audit_repository.close()
    engine.dispose()


app = FastAPI(title="小七宝量化决策台", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(research_router)
app.include_router(data_router)
app.include_router(backtest_router)
app.include_router(paper_router)
app.include_router(xingbu_router)
app.include_router(libu_router)
app.include_router(dongchang_router)
