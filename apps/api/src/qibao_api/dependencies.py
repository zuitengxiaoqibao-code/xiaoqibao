from fastapi import Request

from qibao_api.gongbu.data_service import MarketDataService
from qibao_api.shangshu.pipeline import ResearchPipeline


def get_pipeline(request: Request) -> ResearchPipeline:
    return request.app.state.pipeline


def get_market_data_service(request: Request) -> MarketDataService:
    return request.app.state.market_data_service

