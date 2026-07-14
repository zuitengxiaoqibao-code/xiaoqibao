from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine

from qibao_api.gongbu.baidu_history import BaiduHistorySource
from qibao_api.gongbu.data_service import FallbackHistorySource, MarketDataService
from qibao_api.gongbu.tdx_client import create_tdx_client
from qibao_api.gongbu.tdx_history import TdxHistorySource
from qibao_api.gongbu.tencent_quotes import TencentQuoteSource
from qibao_api.convertible_bonds.adapters import EastmoneyBondValuationSource, EastmoneyClauseSource, TencentBondQuoteSource
from qibao_api.convertible_bonds.repository import BondClauseRepository
from qibao_api.convertible_bonds.service import ConvertibleBondService
from qibao_api.convertible_bonds.diagnosis_repository import BondDiagnosisRepository
from qibao_api.gongbu.news_collection import EastmoneyGlobalNewsSource
from qibao_api.gongbu.news_ingestion import NewsIngestionService
from qibao_api.gongbu.news_linking import DeterministicNewsLinker
from qibao_api.gongbu.news_repository import NewsRepository
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
from qibao_api.routes.convertible_bonds import router as convertible_bonds_router
from qibao_api.routes.news import router as news_router
from qibao_api.zhongshu.news_ai import NewsAIGateway, UnavailableNewsAIProvider


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
    compliance.set_feature_sources("bond_quotes", "convertible_bond", ("tencent",))
    compliance.set_feature_sources("bond_clauses", "convertible_bond", ("eastmoney",))
    compliance.set_feature_sources("bond_valuations", "convertible_bond", ("eastmoney",))
    compliance.set_feature_sources("market_news", "a_share", ("eastmoney",))
    bond_repository = BondClauseRepository(engine)
    bond_repository.initialize()
    diagnosis_repository = BondDiagnosisRepository(settings.data_dir / "bond-diagnoses.sqlite3")
    news_repository = NewsRepository(settings.data_dir / "news.sqlite3")
    application.state.news_repository = news_repository
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
                    industry_keywords={
                        "半导体": ("半导体", "芯片"),
                        "人工智能": ("人工智能", "AI算力", "大模型"),
                        "新能源": ("新能源", "光伏", "锂电"),
                        "医药生物": ("创新药", "医疗器械", "医药"),
                        "高端制造": ("先进制造", "工业母机", "机器人"),
                    },
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
                bond_repository.close()
                diagnosis_repository.close()
                news_repository.close()
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
app.include_router(convertible_bonds_router)
app.include_router(news_router)
