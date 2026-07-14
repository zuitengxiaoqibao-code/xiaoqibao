from qibao_api.convertible_bonds.diagnosis_repository import BondDiagnosisRepository
from qibao_api.convertible_bonds.diagnosis_repository import DataIntegrityError


def test_diagnoses_are_append_only_canonical_and_latest_survives_reopen(tmp_path):
    database = tmp_path / "diagnoses.sqlite3"
    first = BondDiagnosisRepository(database)
    first.append("113065", {"metric_inputs": {"bond_price": "120"}, "metrics": {"conversion_premium": "0.2"}})
    second_id = first.append("113065", {"metric_inputs": {"bond_price": "121"}, "metrics": {"conversion_premium": "0.21"}})
    with first.connection:
        import pytest
        with pytest.raises(Exception, match="append-only"):
            first.connection.execute("UPDATE bond_diagnoses SET bond_code='123001'")
    first.close()
    reopened = BondDiagnosisRepository(database)
    latest = reopened.latest_by_bond()
    assert latest[0]["diagnosis_id"] == second_id
    assert latest[0]["canonical_hash"]
    assert latest[0]["payload"]["metric_inputs"]["bond_price"] == "121"


def test_repository_detects_payload_tampering_even_if_database_was_modified_directly(tmp_path):
    import pytest
    repository = BondDiagnosisRepository(tmp_path / "tampered.sqlite3")
    repository.append("113065", {"metric_inputs": {"bond_price": "121"}})
    repository.connection.execute("DROP TRIGGER reject_update_bond_diagnoses")
    repository.connection.execute("UPDATE bond_diagnoses SET payload='{}'")
    repository.connection.commit()
    with pytest.raises(DataIntegrityError):
        repository.latest_by_bond()
