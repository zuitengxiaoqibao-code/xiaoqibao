from datetime import datetime, timedelta, timezone

import pytest

from qibao_api.contracts.risk import ComplianceRecord
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
) -> ComplianceRecord:
    return ComplianceRecord(
        record_id=record_id,
        asset="a_share",
        source="tencent",
        permission_state=state,
        permission_reference=f"license:{record_id}",
        disclaimer_version="2026-07",
        user_acknowledged_at=acknowledged_at,
        recorded_at=recorded_at,
    )


def test_authorized_and_acknowledged_source_allows_collection(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("realtime_quotes", ("tencent",))
    repository.append_record(compliance_record("permission-1"))

    assert repository.check_feature_sources("realtime_quotes").allowed is True
    repository.require_feature_sources("realtime_quotes")


@pytest.mark.parametrize("state", ["pending", "revoked"])
def test_non_authorized_source_blocks_new_collection(tmp_path, state: str) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("realtime_quotes", ("tencent",))
    repository.append_record(compliance_record("permission-1", state=state))

    decision = repository.check_feature_sources("realtime_quotes")

    assert decision.allowed is False
    assert decision.blocked_sources == ("tencent",)
    with pytest.raises(SourceAuthorizationError, match=f"tencent:{state}"):
        repository.require_feature_sources("realtime_quotes")


def test_missing_source_authorization_blocks_collection(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("daily_bars", ("tdx",))

    with pytest.raises(SourceAuthorizationError, match="tdx:missing"):
        repository.require_feature_sources("daily_bars")


def test_unacknowledged_disclaimer_blocks_until_append_only_confirmation(tmp_path) -> None:
    repository = ComplianceRepository(tmp_path / "compliance.db")
    repository.set_feature_sources("realtime_quotes", ("tencent",))
    repository.append_record(compliance_record("permission-1", acknowledged_at=None))

    with pytest.raises(SourceAuthorizationError, match="tencent:disclaimer_unacknowledged"):
        repository.require_feature_sources("realtime_quotes")

    repository.append_record(
        compliance_record(
            "permission-2",
            acknowledged_at=NOW + timedelta(minutes=5),
            recorded_at=NOW + timedelta(minutes=5),
        )
    )

    assert repository.check_feature_sources("realtime_quotes").allowed is True
    assert [record.record_id for record in repository.list_source_history("tencent")] == [
        "permission-1",
        "permission-2",
    ]


def test_revocation_survives_restart_and_preserves_readable_history(tmp_path) -> None:
    database = tmp_path / "compliance.db"
    repository = ComplianceRepository(database)
    repository.set_feature_sources("realtime_quotes", ("tencent",))
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
        reopened.require_feature_sources("realtime_quotes")
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
