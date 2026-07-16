from fastapi import APIRouter
from qibao_api.xingbu.rules import RULE_VERSION


router = APIRouter(prefix="/api/v1/xingbu", tags=["刑部"])


@router.get("/status")
def status():
    return {
        "rule_version": RULE_VERSION,
        "limits": {
            "max_quote_age_seconds": 180,
            "industry_concentration": "data_required",
            "liquidity": "data_required",
        },
        "decisions": [],
        "recent_rejections": [],
    }
