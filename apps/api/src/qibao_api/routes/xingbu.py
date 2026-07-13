from typing import Annotated

from fastapi import APIRouter, Depends

from qibao_api.dependencies import get_paper_repository
from qibao_api.hubu.repository import PaperRepository
from qibao_api.xingbu.rules import RULE_VERSION


router = APIRouter(prefix="/api/v1/xingbu", tags=["刑部"])


@router.get("/status")
def status(repository: Annotated[PaperRepository, Depends(get_paper_repository)], account_id: str = "paper-1"):
    decisions = repository.list_risk_decisions(limit=20)
    rejections = repository.list_rejected_order_decisions(limit=20)
    try:
        single_cap, total_cap = repository.get_allocation_settings(account_id)
        allocation_limits = {"max_position": str(single_cap), "max_total_exposure": str(total_cap), "source": f"account:{account_id}", "state": "available"}
    except KeyError:
        allocation_limits = {"max_position": "0.20", "max_total_exposure": "0.80", "source": "default", "state": "unavailable"}
    return {
        "rule_version": RULE_VERSION,
        "limits": {
            "max_quote_age_seconds": 180,
            **allocation_limits,
            "industry_concentration": "data_required",
            "liquidity": "data_required",
        },
        "decisions": decisions,
        "recent_rejections": rejections,
    }
