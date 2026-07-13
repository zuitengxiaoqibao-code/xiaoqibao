SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS compliance_records (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL UNIQUE,
    asset TEXT NOT NULL,
    source TEXT NOT NULL,
    permission_state TEXT NOT NULL,
    permission_reference TEXT NOT NULL,
    disclaimer_version TEXT NOT NULL,
    user_acknowledged_at TEXT,
    recorded_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS compliance_records_source_time
ON compliance_records(source, recorded_at, sequence);

CREATE TRIGGER IF NOT EXISTS compliance_records_no_update
BEFORE UPDATE ON compliance_records
BEGIN
    SELECT RAISE(ABORT, 'compliance records are immutable');
END;

CREATE TRIGGER IF NOT EXISTS compliance_records_no_delete
BEFORE DELETE ON compliance_records
BEGIN
    SELECT RAISE(ABORT, 'compliance records are immutable');
END;

CREATE TABLE IF NOT EXISTS compliance_feature_sources (
    feature TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY(feature, source)
);
"""
