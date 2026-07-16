from datetime import date, datetime, time, timedelta, timezone

from qibao_api.contracts.briefing import PostcloseContext
from qibao_api.contracts.market import AssetKind


CHINA_TZ = timezone(timedelta(hours=8))


class RepositoryPostcloseContextSource:
    def __init__(self, decision_repository, audit_repository) -> None:
        self.decision_repository = decision_repository
        self.audit_repository = audit_repository

    def snapshot(self, trading_date: date, now: datetime) -> PostcloseContext:
        start = datetime.combine(trading_date, time(9, 25), CHINA_TZ)
        cutoff = min(now.astimezone(CHINA_TZ), datetime.combine(trading_date, time(15), CHINA_TZ))
        decisions = tuple(
            advice
            for phase in ("premarket", "intraday", "postclose")
            for cycle in self.decision_repository.cycles(trading_date, phase)
            if cycle.snapshot.generated_at <= cutoff
            for advice in cycle.advice
            if advice.created_at <= cutoff
        )
        findings = [
            finding
            for finding in self.audit_repository.list_findings(asset=AssetKind.A_SHARE)
            if start <= finding.detected_at <= cutoff
        ]
        return PostcloseContext(
            signal_outcome_ids=tuple(item.advice_id for item in decisions),
            error_codes=(),
            risk_event_ids=tuple(finding.finding_id for finding in findings),
        )
