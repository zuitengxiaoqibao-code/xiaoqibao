SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS audit_snapshots (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL UNIQUE,
    asset TEXT NOT NULL,
    symbol TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    evidence_link TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    content_hash TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS audit_snapshots_no_update
BEFORE UPDATE ON audit_snapshots
BEGIN
    SELECT RAISE(ABORT, 'audit snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS audit_snapshots_no_delete
BEFORE DELETE ON audit_snapshots
BEGIN
    SELECT RAISE(ABORT, 'audit snapshots are immutable');
END;

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

CREATE TABLE IF NOT EXISTS audit_finding_snapshots (
    finding_id TEXT NOT NULL REFERENCES audit_findings(finding_id),
    snapshot_id TEXT NOT NULL REFERENCES audit_snapshots(snapshot_id),
    position INTEGER NOT NULL,
    PRIMARY KEY (finding_id, snapshot_id)
);

CREATE TRIGGER IF NOT EXISTS audit_finding_snapshots_no_update
BEFORE UPDATE ON audit_finding_snapshots
BEGIN
    SELECT RAISE(ABORT, 'audit finding snapshot links are immutable');
END;

CREATE TRIGGER IF NOT EXISTS audit_finding_snapshots_no_delete
BEFORE DELETE ON audit_finding_snapshots
BEGIN
    SELECT RAISE(ABORT, 'audit finding snapshot links are immutable');
END;
"""
