from fastapi import Request

from qibao_api.gongbu.data_service import MarketDataService
from qibao_api.bingbu.paper_service import PaperTradingService
from qibao_api.hubu.repository import PaperRepository
from qibao_api.shangshu.pipeline import ResearchPipeline


def get_pipeline(request: Request) -> ResearchPipeline:
    return request.app.state.pipeline


def get_market_data_service(request: Request) -> MarketDataService:
    return request.app.state.market_data_service


def get_paper_repository(request: Request) -> PaperRepository:
    return request.app.state.paper_repository


def get_paper_service(request: Request) -> PaperTradingService:
    return request.app.state.paper_service
