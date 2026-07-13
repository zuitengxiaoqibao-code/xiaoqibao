from typing import Annotated

from fastapi import APIRouter, Depends

from qibao_api.dependencies import get_paper_repository
from qibao_api.hubu.repository import PaperRepository
from qibao_api.xingbu.rules import RULE_VERSION


router = APIRouter(prefix="/api/v1/xingbu", tags=["刑部"])


@router.get("/status")
def status(repository: Annotated[PaperRepository, Depends(get_paper_repository)]):
    decisions = repository.list_risk_decisions(limit=20)
    return {
        "rule_version": RULE_VERSION,
        "limits": {
            "max_quote_age_seconds": 180,
            "max_position": "0.20",
            "max_total_exposure": "0.80",
            "industry_concentration": "data_required",
            "liquidity": "data_required",
        },
        "decisions": decisions,
        "recent_rejections": [item for item in decisions if item.outcome == "reject"],
    }
