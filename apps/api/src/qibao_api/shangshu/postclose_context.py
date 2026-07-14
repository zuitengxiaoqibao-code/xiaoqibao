from datetime import date, datetime, time, timedelta, timezone

from qibao_api.contracts.briefing import PostcloseContext
from qibao_api.contracts.market import AssetKind


CHINA_TZ = timezone(timedelta(hours=8))


class RepositoryPostcloseContextSource:
    def __init__(self, paper_repository, audit_repository) -> None:
        self.paper_repository = paper_repository
        self.audit_repository = audit_repository

    def snapshot(self, trading_date: date, now: datetime) -> PostcloseContext:
        start = datetime.combine(trading_date, time(9, 25), CHINA_TZ)
        outcomes = self.paper_repository.list_order_outcomes_between(start, now)
        terminal = [
            item for item in outcomes if item["status"] in {"filled", "rejected"}
        ]
        errors = tuple(dict.fromkeys(
            str(item["rejection_reason"])
            for item in terminal if item.get("rejection_reason")
        ))
        findings = [
            finding
            for finding in self.audit_repository.list_findings(asset=AssetKind.A_SHARE)
            if start <= finding.detected_at <= now
        ]
        return PostcloseContext(
            signal_outcome_ids=tuple(str(item["order_id"]) for item in terminal),
            error_codes=errors,
            risk_event_ids=tuple(finding.finding_id for finding in findings),
        )
