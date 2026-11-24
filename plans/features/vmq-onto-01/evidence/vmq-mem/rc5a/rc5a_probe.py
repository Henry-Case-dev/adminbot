"""VMQ-MEM RC5a read-only snapshot probe (existing rows only).

No writes, no rewrites: counts existing world_knowledge/subject_ref rows on
snapshot-2.58.225.db. New-write behavior is covered by the unit test.
"""
import json
import os
import sqlite3

SNAP = r"C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\snapshot-2.58.225.db"
OUT = os.path.join(os.path.dirname(__file__), "rc5a-snapshot.json")
CHAT = -1002661910336
LEHA_REF = 15612


def _count(c, sql, params=()):
    row = c.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def main():
    uri = "file:" + SNAP.replace("\\", "/") + "?mode=ro&immutable=1"
    c = sqlite3.connect(uri, uri=True)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    try:
        total_confirmed = _count(
            c, "SELECT COUNT(*) FROM graph_facts WHERE chat_id=? "
               "AND status='confirmed'", (CHAT,))
        subject_ref = _count(
            c, "SELECT COUNT(*) FROM graph_facts WHERE chat_id=? "
               "AND status='confirmed' AND subject_ref_id IS NOT NULL", (CHAT,))
        subject_world = _count(
            c, "SELECT COUNT(*) FROM graph_facts WHERE chat_id=? "
               "AND status='confirmed' AND subject_ref_id IS NOT NULL "
               "AND (COALESCE(attribution_method,'')='world_knowledge' "
               "OR COALESCE(assertion_kind,'')='world_knowledge')", (CHAT,))
        leha_subject = _count(
            c, "SELECT COUNT(*) FROM graph_facts WHERE chat_id=? "
               "AND status='confirmed' AND subject_ref_id=?", (CHAT, LEHA_REF))
        leha_world = _count(
            c, "SELECT COUNT(*) FROM graph_facts WHERE chat_id=? "
               "AND status='confirmed' AND subject_ref_id=? "
               "AND (COALESCE(attribution_method,'')='world_knowledge' "
               "OR COALESCE(assertion_kind,'')='world_knowledge')",
            (CHAT, LEHA_REF))
        result = {
            "artifact_kind": "vmq_mem_rc5a_snapshot_probe",
            "snapshot": SNAP,
            "snapshot_sha256_expected": "b907d4c1e24321fffa48e3719974fd2293b1b1ff721ad21661446d22033e06e7",
            "mode": "mode=ro&immutable=1; PRAGMA query_only=ON",
            "chat_id": CHAT,
            "existing_rows": {
                "confirmed": total_confirmed,
                "subject_ref_confirmed": subject_ref,
                "subject_ref_world_knowledge": subject_world,
                "leha_ref_confirmed": leha_subject,
                "leha_ref_world_knowledge": leha_world,
            },
            "untouched": {
                "subject_ref_world_unchanged": subject_world == 6810,
                "leha_world_unchanged": leha_world == 598,
                "no_rewrite_path": True,
            },
        }
    finally:
        c.close()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=True, indent=1)
    print(json.dumps(result, ensure_ascii=True, indent=1))


if __name__ == "__main__":
    main()
