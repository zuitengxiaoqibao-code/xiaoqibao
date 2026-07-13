from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from sqlalchemy import create_engine

from qibao_api.gongbu.tencent_quotes import TencentQuoteSource
from qibao_api.routes.health import router as health_router
from qibao_api.routes.research import router as research_router
from qibao_api.settings import Settings
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.storage.database import create_schema
from qibao_api.storage.quote_repository import QuoteRepository
from qibao_api.xingbu.gate import RiskGate


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url)
    create_schema(engine)
    async with httpx.AsyncClient(timeout=10) as client:
        application.state.pipeline = ResearchPipeline(
            TencentQuoteSource(client),
            QuoteRepository(engine),
            RiskGate(),
        )
        yield
    engine.dispose()


app = FastAPI(title="小七宝量化决策台", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(research_router)
