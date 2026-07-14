from qibao_api.convertible_bonds.diagnosis_repository import BondDiagnosisRepository


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
