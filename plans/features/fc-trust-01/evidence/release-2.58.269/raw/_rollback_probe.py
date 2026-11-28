"""Local dry-run of the documented v50 -> v49 rollback SQL (probe DB, not prod)."""
import os
import sqlite3
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

db = os.path.join(tempfile.mkdtemp(prefix="fct_v50_probe_"), "probe.db")
c = sqlite3.connect(db)
c.executescript(
    """
    CREATE TABLE mca_factcheck_runs (
        run_id TEXT PRIMARY KEY, access_scope TEXT, stage_trace TEXT,
        updated_at INTEGER);
    CREATE TABLE mca_factcheck_evidence (
        run_id TEXT, claim_part TEXT, url TEXT, relation TEXT,
        source_kind TEXT);
    ALTER TABLE mca_factcheck_runs ADD COLUMN correlation_id TEXT;
    CREATE INDEX IF NOT EXISTS idx_mca_factcheck_runs_correlation
        ON mca_factcheck_runs(correlation_id);
    ALTER TABLE mca_factcheck_evidence ADD COLUMN evidence_id TEXT;
    ALTER TABLE mca_factcheck_evidence ADD COLUMN opened INTEGER;
    ALTER TABLE mca_factcheck_evidence ADD COLUMN strength TEXT;
    PRAGMA user_version = 50;
    INSERT INTO mca_factcheck_runs (run_id, correlation_id, stage_trace)
        VALUES ('r1', 'c1', '[{"stage":"retrieve","outcome":"success"}]');
    INSERT INTO mca_factcheck_evidence
        (run_id, evidence_id, url, relation, opened, strength)
        VALUES ('r1', 'ev-1', 'u', 'supports', 1, 'strong');
    """
)
print("sqlite_version=%s" % sqlite3.sqlite_version)
print("before_user_version=%d" % c.execute("PRAGMA user_version").fetchone()[0])
print("before_runs_cols=%s" % [r[1] for r in c.execute("PRAGMA table_info(mca_factcheck_runs)")])
print("before_evidence_cols=%s" % [r[1] for r in c.execute("PRAGMA table_info(mca_factcheck_evidence)")])
print("before_indexes=%s" % [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_mca_factcheck%'")])

ROLLBACK = """
DROP INDEX IF EXISTS idx_mca_factcheck_runs_correlation;
ALTER TABLE mca_factcheck_runs DROP COLUMN correlation_id;
ALTER TABLE mca_factcheck_evidence DROP COLUMN evidence_id;
ALTER TABLE mca_factcheck_evidence DROP COLUMN opened;
ALTER TABLE mca_factcheck_evidence DROP COLUMN strength;
PRAGMA user_version = 49;
"""
c.executescript(ROLLBACK)
print("after_user_version=%d" % c.execute("PRAGMA user_version").fetchone()[0])
print("after_runs_cols=%s" % [r[1] for r in c.execute("PRAGMA table_info(mca_factcheck_runs)")])
print("after_evidence_cols=%s" % [r[1] for r in c.execute("PRAGMA table_info(mca_factcheck_evidence)")])
print("after_indexes=%s" % [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_mca_factcheck%'")])
print("legacy_select_runs=%s" % c.execute(
    "SELECT run_id, access_scope, stage_trace FROM mca_factcheck_runs").fetchall())
print("legacy_select_evidence=%s" % c.execute(
    "SELECT run_id, claim_part, url, relation, source_kind FROM mca_factcheck_evidence").fetchall())
print("integrity_check=%s" % c.execute("PRAGMA integrity_check").fetchone()[0])
print("quick_check=%s" % c.execute("PRAGMA quick_check").fetchone()[0])
c.close()
os.remove(db)
print("temp_probe_removed=%s" % (not os.path.exists(db)))
print("temp_dir=%s" % os.path.dirname(db))
