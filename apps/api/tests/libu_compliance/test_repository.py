from datetime import datetime, timedelta, timezone

import pytest

from qibao_api.contracts.risk import ComplianceRecord
from qibao_api.libu_compliance.guard import AuthorizedHistorySource
from qibao_api.libu_compliance.repository import (
    ComplianceRepository,
    SourceAuthorizationError,
)


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def compliance_record(
    record_id: str,
    *,
    state: str = "authorized",
    acknowledged_at: datetime | None = NOW,
    recorded_at: datetime = NOW,
    asset: str = "a_share",
    source: str = "tencent",
) -> ComplianceRecord:
    return ComplianceRecord(
        record_id=record_id,
        asset=asset,
        source=source,
        permission_state=state,
        permission_reference=f"license:{record_id}",
        disclaimer_version="2026-07",
        user_acknowledged_at=acknowledged_at,
        recorded_at=recorded_at,
    )


def test_authorized_and_acknowledged_source_allows_collection(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("realtime_quotes", "a_share", ("tencent",))
    repository.append_record(compliance_record("permission-1"))

    assert repository.check_feature_sources("realtime_quotes", "a_share").allowed is True
    repository.require_feature_sources("realtime_quotes", "a_share")


@pytest.mark.parametrize("state", ["pending", "revoked"])
def test_non_authorized_source_blocks_new_collection(tmp_path, state: str) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("realtime_quotes", "a_share", ("tencent",))
    repository.append_record(compliance_record("permission-1", state=state))

    decision = repository.check_feature_sources("realtime_quotes", "a_share")

    assert decision.allowed is False
    assert decision.blocked_sources == ("tencent",)
    with pytest.raises(SourceAuthorizationError, match=f"tencent:{state}"):
        repository.require_feature_sources("realtime_quotes", "a_share")


def test_missing_source_authorization_blocks_collection(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("daily_bars", "a_share", ("tdx",))

    with pytest.raises(SourceAuthorizationError, match="tdx:missing"):
        repository.require_feature_sources("daily_bars", "a_share")


def test_unacknowledged_disclaimer_blocks_until_append_only_confirmation(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("realtime_quotes", "a_share", ("tencent",))
    repository.append_record(compliance_record("permission-1", acknowledged_at=None))

    with pytest.raises(SourceAuthorizationError, match="tencent:disclaimer_unacknowledged"):
        repository.require_feature_sources("realtime_quotes", "a_share")

    repository.append_record(
        compliance_record(
            "permission-2",
            acknowledged_at=NOW + timedelta(minutes=5),
            recorded_at=NOW + timedelta(minutes=5),
        )
    )

    assert repository.check_feature_sources("realtime_quotes", "a_share").allowed is True
    assert [record.record_id for record in repository.list_source_history("tencent")] == [
        "permission-1",
        "permission-2",
    ]


def test_revocation_survives_restart_and_preserves_readable_history(tmp_path) -> None:
    database = tmp_path / "compliance.db"
    repository = ComplianceRepository(database)
    repository.set_feature_sources("realtime_quotes", "a_share", ("tencent",))
    repository.append_record(compliance_record("permission-1"))
    repository.append_record(
        compliance_record(
            "permission-2",
            state="revoked",
            acknowledged_at=None,
            recorded_at=NOW + timedelta(hours=1),
        )
    )
    repository.close()

    reopened = ComplianceRepository(database)

    with pytest.raises(SourceAuthorizationError, match="tencent:revoked"):
        reopened.require_feature_sources("realtime_quotes", "a_share")
    assert [record.record_id for record in reopened.list_source_history("tencent")] == [
        "permission-1",
        "permission-2",
    ]


def test_compliance_records_are_immutable(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.append_record(compliance_record("permission-1"))

    with pytest.raises(ValueError, match="already exists"):
        repository.append_record(compliance_record("permission-1", state="revoked"))

    assert repository.list_source_history("tencent") == [compliance_record("permission-1")]


def test_unregistered_feature_fails_closed_with_explicit_reason(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")

    decision = repository.check_feature_sources("realtime_quote", "a_share")

    assert decision.allowed is False
    assert decision.blocked_reasons == ("feature_sources_unregistered",)
    with pytest.raises(SourceAuthorizationError, match="feature_sources_unregistered"):
        repository.require_feature_sources("realtime_quote", "a_share")


def test_feature_source_configuration_is_append_only_and_cannot_remove_dependency(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("realtime_quotes", "a_share", ("tencent",))
    repository.set_feature_sources("realtime_quotes", "a_share", ("backup",))

    history = repository.list_feature_source_history("realtime_quotes", "a_share")

    assert [event.source for event in history] == ["tencent", "backup"]
    assert repository.check_feature_sources("realtime_quotes", "a_share").blocked_sources == (
        "backup",
        "tencent",
    )
    with pytest.raises(Exception, match="immutable"):
        repository.connection.execute("DELETE FROM compliance_feature_source_events")


def test_source_authorization_is_isolated_by_asset(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("daily_bars", "a_share", ("vendor",))
    repository.set_feature_sources("daily_bars", "convertible_bond", ("vendor",))
    repository.append_record(
        compliance_record("bond-permission", asset="convertible_bond", source="vendor")
    )

    assert repository.check_feature_sources("daily_bars", "convertible_bond").allowed is True
    with pytest.raises(SourceAuthorizationError, match="vendor:missing"):
        repository.require_feature_sources("daily_bars", "a_share")


def test_authorized_history_guard_blocks_revoked_source_without_calling_downstream(tmp_path) -> None:
    class Source:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_daily(self, symbol: str, limit: int):
            self.calls += 1
            return [symbol, limit]

    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("daily_bars", "a_share", ("tencent",))
    repository.append_record(compliance_record("permission-1"))
    source = Source()
    guarded = AuthorizedHistorySource(source, repository, "daily_bars", "a_share")

    assert guarded.fetch_daily("600000", 10) == ["600000", 10]
    repository.append_record(
        compliance_record(
            "permission-2",
            state="revoked",
            acknowledged_at=None,
            recorded_at=NOW + timedelta(hours=1),
        )
    )

    with pytest.raises(SourceAuthorizationError, match="tencent:revoked"):
        guarded.fetch_daily("600000", 10)
    assert source.calls == 1
    assert [record.record_id for record in repository.list_source_history("tencent")] == [
        "permission-1",
        "permission-2",
    ]
