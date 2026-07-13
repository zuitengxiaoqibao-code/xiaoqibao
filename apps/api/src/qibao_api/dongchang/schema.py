SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS audit_findings (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_id TEXT NOT NULL UNIQUE,
    asset TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    input_snapshot_ids_json TEXT NOT NULL,
    owner_department TEXT NOT NULL,
    resolution_state TEXT NOT NULL,
    detected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS audit_findings_asset_time
ON audit_findings(asset, detected_at, sequence);

CREATE TRIGGER IF NOT EXISTS audit_findings_no_update
BEFORE UPDATE ON audit_findings
BEGIN
    SELECT RAISE(ABORT, 'audit findings are immutable');
END;

CREATE TRIGGER IF NOT EXISTS audit_findings_no_delete
BEFORE DELETE ON audit_findings
BEGIN
    SELECT RAISE(ABORT, 'audit findings are immutable');
END;
"""
