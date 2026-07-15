from datetime import datetime, timezone

from fastapi import Request

from qibao_api.gongbu.data_service import MarketDataService
from qibao_api.bingbu.paper_service import PaperTradingService
from qibao_api.hubu.repository import PaperRepository
from qibao_api.shangshu.pipeline import ResearchPipeline
from qibao_api.libu_compliance.repository import ComplianceRepository
from qibao_api.dongchang.repository import AuditFindingRepository


def get_pipeline(request: Request) -> ResearchPipeline:
    return request.app.state.pipeline


def get_market_data_service(request: Request) -> MarketDataService:
    return request.app.state.market_data_service


def get_paper_repository(request: Request) -> PaperRepository:
    return request.app.state.paper_repository


def get_paper_service(request: Request) -> PaperTradingService:
    return request.app.state.paper_service


def get_compliance_repository(request: Request) -> ComplianceRepository:
    return request.app.state.compliance_repository


def get_audit_repository(request: Request) -> AuditFindingRepository:
    return request.app.state.audit_repository


def get_bond_service(request: Request):
    return request.app.state.bond_service


def get_news_service(request: Request):
    return request.app.state.news_service


def get_news_repository(request: Request):
    return request.app.state.news_repository


def get_briefing_workflow(request: Request):
    return request.app.state.briefing_workflow


def get_briefing_repository(request: Request):
    return request.app.state.briefing_repository


def get_scheduler(request: Request):
    return request.app.state.scheduler


def get_backup_service(request: Request):
    return request.app.state.backup_service


def get_a_share_diagnosis_service(request: Request):
    return request.app.state.a_share_diagnosis_service


def get_decision_repository(request: Request):
    return request.app.state.decision_repository


def get_decision_calendar(request: Request):
    return request.app.state.decision_calendar


def get_server_time() -> datetime:
    return datetime.now(timezone.utc)
