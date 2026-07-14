import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone

from qibao_api.contracts.briefing import (
    BriefingPhase,
    BriefingSections,
    DailyBriefing,
    PostcloseContext,
)


CHINA_TZ = timezone(timedelta(hours=8))


class DailyBriefingWorkflow:
    def __init__(
        self, news_repository, briefing_repository, trading_calendar,
        postclose_context_source=None,
        *, clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.news_repository = news_repository
        self.briefing_repository = briefing_repository
        self.trading_calendar = trading_calendar
        self.postclose_context_source = postclose_context_source
        self.clock = clock

    def run(
        self, phase: BriefingPhase, trading_date: date, *, now: datetime | None = None
    ) -> DailyBriefing:
        now = now or self.clock()
        if not self.trading_calendar.is_trading_day(trading_date):
            raise ValueError(f"{trading_date} is not a confirmed trading day")
        run_id, attempt = self.briefing_repository.begin_run(phase, trading_date, now)
        try:
            report = self._build(phase, trading_date, now)
            self.briefing_repository.append_report(report)
        except Exception as error:
            self.briefing_repository.finish_run(
                run_id, trading_date=trading_date, phase=phase, attempt=attempt,
                status="failed", occurred_at=now,
                error_code=_error_code(error),
            )
            raise
        self.briefing_repository.finish_run(
            run_id, trading_date=trading_date, phase=phase, attempt=attempt,
            status="completed", occurred_at=now, report_id=report.report_id,
        )
        return report

    def _build(
        self, phase: BriefingPhase, trading_date: date, now: datetime
    ) -> DailyBriefing:
        window_start, window_end = self._window(phase, trading_date, now)
        events = [
            event for event in self.news_repository.events()
            if window_start <= event.occurred_at <= window_end
            and event.normalized_at <= now
        ]
        if phase == "intraday":
            emitted = {
                event_id
                for report in self.briefing_repository.reports(
                    phase="intraday", trading_date=trading_date
                )
                for event_id in report.event_ids
            }
            events = [event for event in events if event.event_id not in emitted]
        event_ids = tuple(event.event_id for event in events)
        interpretations = [
            item for item in self.news_repository.interpretations()
            if item.event_id in event_ids and item.generated_at <= now
        ]
        postclose = (
            self.postclose_context_source.snapshot(trading_date, now)
            if phase == "postclose" and self.postclose_context_source is not None
            else PostcloseContext()
        )
        snapshot_payload = {
            "events": [event.model_dump(mode="json") for event in events],
            "interpretations": [
                item.model_dump(mode="json") for item in interpretations
            ],
            "postclose_context": postclose.model_dump(mode="json"),
        }
        snapshot_json = json.dumps(
            snapshot_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        identity = (
            f"{trading_date.isoformat()}|{phase}|{window_end.isoformat()}|{snapshot_hash}"
        )
        report_id = f"briefing-{hashlib.sha256(identity.encode()).hexdigest()[:24]}"
        policy_ids = tuple(
            event.event_id for event in events
            if "policy" in event.event_type or "政策支持" in event.themes
        )
        news_risk_ids = tuple(
            event.event_id for event in events
            if "risk" in event.event_type or "风险事件" in event.themes
        )
        risk_ids = tuple(dict.fromkeys((*news_risk_ids, *postclose.risk_event_ids)))
        watchlist = tuple(dict.fromkeys(
            instrument
            for event in events if event.review_state == "verified"
            for instrument in event.affected_instruments
        ))
        return DailyBriefing(
            report_id=report_id,
            trading_date=trading_date,
            phase=phase,
            generated_at=now,
            window_start=window_start,
            window_end=window_end,
            event_ids=event_ids,
            interpretation_ids=tuple(
                item.interpretation_id for item in interpretations
            ),
            input_snapshot_hash=snapshot_hash,
            sections=BriefingSections(
                policy_event_ids=policy_ids,
                risk_event_ids=risk_ids,
                watchlist=watchlist,
                signal_outcome_ids=postclose.signal_outcome_ids,
                error_codes=postclose.error_codes,
                next_day_observations=(
                    tuple(f"次日继续观察 {asset.value}:{symbol}" for asset, symbol in watchlist)
                    if phase == "postclose" else ()
                ),
            ),
        )

    def _window(
        self, phase: BriefingPhase, trading_date: date, now: datetime
    ) -> tuple[datetime, datetime]:
        market_open = datetime.combine(trading_date, time(9, 25), CHINA_TZ)
        market_close = datetime.combine(trading_date, time(15, 0), CHINA_TZ)
        if phase == "premarket":
            previous = self.trading_calendar.previous_trading_day(trading_date)
            start = datetime.combine(previous, time(15, 0), CHINA_TZ)
            end = min(now, market_open)
        elif phase == "intraday":
            start = market_open
            end = min(now, market_close)
        else:
            start = market_open
            scheduled_end = datetime.combine(trading_date, time(15, 30), CHINA_TZ)
            end = min(now, scheduled_end)
        if end <= start:
            raise ValueError(f"{phase} briefing window has not opened")
        return start, end


def _error_code(error: Exception) -> str:
    name = error.__class__.__name__
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
