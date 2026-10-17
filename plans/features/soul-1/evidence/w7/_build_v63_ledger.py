"""W7 / SOUL-13.0-13.3/13.5: ledger живых гейтов v6.3 + baseline-запись.

Только ЧТЕНИЕ соседних артефактов v6.3 (карта НЕ редактируется) → пишет
два JSON в plans/features/soul-1/evidence/w7/.

Запуск: .venv/Scripts/python.exe <scratch>/w7/build_v63_ledger.py
"""
import hashlib
import io
import json
import os
import subprocess
import sys

REPO = r"C:\Code\Python\adminbot"
V63 = os.path.join(REPO, "plans", "features", "asap8-v6-3-live-correction")
OUT = os.path.join(REPO, "plans", "features", "soul-1", "evidence", "w7")

# Шесть названных в §14 клауз — сопоставление с req_id карты v6.3 (руками,
# по слайсу/смыслу; строки не переименовываются).
SOURCE_CATEGORIES = {
    "live_windows_android": ["U07-SYM-DESKTOP", "U07-SYM-ANDROID",
                             "U07-LAUNCHMODE", "U07.1a", "U07.1e", "U07.3b",
                             "U07.3c", "REQ-U07", "REQ-U07-3", "B10-R18",
                             "U07-PLATFORMS"],
    "initiative_send": ["REQ-B01", "B01.4", "REQ-B01-DOD", "B10-R04",
                        "B10-R06", "REQ-B11-E2E", "REQ-B10"],
    "experience_load_lag": ["REQ-B02", "B02.3", "REQ-B02-DOD", "B10-R13",
                            "REQ-B03-DOD", "B10-R12"],
    "cover_style_edited_publish": ["B04.5", "B10-R02", "REQ-B04",
                                   "REQ-B04-DOD", "B10-R03"],
    "supergroup_migration": ["REQ-B09", "B10-R10", "REQ-B09-BODY"],
    "observ_24_48h": ["B10-R01", "B10-R05", "B10-R07", "B10-R08", "B10-R09",
                      "B10-R11", "B10-R14", "B10-R15", "B10-R16", "B10-R17",
                      "B10-R19", "FINAL.2", "FINAL.4"],
    "live_probes_v01_v07": ["V01", "V02", "V03", "V04", "V05", "V06", "V07"],
    "git_evidence_b12": ["B12.1", "B12.2", "B12.3", "B12.4", "B12.5",
                         "B12.6", "REQ-B12", "REQ-B11", "REQ-EVIDENCE-SELF"],
}


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=REPO, capture_output=True,
                          text=True).stdout.strip()


def load_rows(path):
    with io.open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    rows = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("req_id") and node.get("status"):
                rows.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return data, rows


def main():
    os.makedirs(OUT, exist_ok=True)
    map_path = os.path.join(V63, "requirements-map.json")
    data, rows = load_rows(map_path)
    statuses = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1

    open_rows = [r for r in rows if r["status"] != "VERIFIED"]
    ledger = {
        "generated_by": "W7-BUILD (soul-1 slice W7, SOUL-13.0/13.1/13.3)",
        "source_map": "plans/features/asap8-v6-3-live-correction/requirements-map.json",
        "source_map_sha256": sha256(map_path),
        "source_map_candidate_commit": data.get("candidate_commit"),
        "source_map_deployed_commit": data.get("deployed_commit"),
        "source_map_working_tree": git("status", "--porcelain", "--",
                                       "plans/features/asap8-v6-3-live-correction/requirements-map.json") or "clean",
        "note": ("Карта v6.3 НЕ редактировалась этим лейном (соседский "
                 "незакоммиченный файл). Ни одна строка не переименована в "
                 "'closed': статусы приведены как есть, включая "
                 "BLOCKED_REAL_HUMAN_GATE."),
        "status_counts": statuses,
        "open_rows_total": len(open_rows),
        "open_rows": [{
            "req_id": r["req_id"],
            "status": r["status"],
            "slice": r.get("slice"),
            "live_required": r.get("live_required"),
            "live_when": r.get("live_when"),
            "reason": r.get("reason") or "",
            "evidence_count": len(r.get("evidence") or []),
        } for r in sorted(open_rows, key=lambda r: str(r["req_id"]))],
        "required_v63_gate_ledger_note": (
            "§14 говорит про '14 pending-гейтов'; это состояние привязки "
            "225c3c2b (13 READY_FOR_LIVE / 14 BLOCKED_REAL_HUMAN_GATE). "
            "Текущее НЕЗАКОММИЧЕННОЕ состояние карты — см. status_counts."),
        "source_clause_categories": SOURCE_CATEGORIES,
        "category_status": {},
    }
    by_id = {r["req_id"]: r for r in rows}
    for cat, ids in SOURCE_CATEGORIES.items():
        ledger["category_status"][cat] = [{
            "req_id": i,
            "status": by_id[i]["status"] if i in by_id else "ABSENT_FROM_MAP",
        } for i in ids]
    with io.open(os.path.join(OUT, "v63-live-gates-ledger.json"), "w",
                 encoding="utf-8", newline="\n") as fh:
        json.dump(ledger, fh, ensure_ascii=False, indent=2)

    # ── baseline-запись ASAP8 v6.3 (SOUL-13.0/13.1) ─────────────────────────
    artifacts = ["release-reconciliation.md", "final-audit-current-task.md",
                 "live-canary.md", "requirements-map.md", "review-ledger.md",
                 "v63-final-coverage-report-2026-10-16.md",
                 "verification-report-2026-10-16.md", "map-reconciliation-2026-10-16.md"]
    files = {}
    for name in artifacts:
        p = os.path.join(V63, name)
        rel = "plans/features/asap8-v6-3-live-correction/" + name
        tracked = bool(git("ls-files", "--error-unmatch", rel))
        files[name] = {
            "path": rel,
            "exists": os.path.exists(p),
            "tracked": tracked,
            "blob_HEAD": git("rev-parse", "HEAD:" + rel) if tracked else None,
            "sha256_worktree": sha256(p) if os.path.exists(p) else None,
            "dirty": bool(git("status", "--porcelain", "--", rel)),
        }
    baseline = {
        "generated_by": "W7-BUILD (soul-1 slice W7, SOUL-13.0/13.1/13.5)",
        "head": git("rev-parse", "HEAD"),
        "origin_master": git("rev-parse", "origin/master"),
        "git_evidence_commit_225c3c2b": {
            "sha": git("rev-parse", "225c3c2b"),
            "subject": git("log", "-1", "--format=%s", "225c3c2b"),
            "parent": git("log", "-1", "--format=%P", "225c3c2b"),
            "files": git("show", "--stat", "--format=", "225c3c2b").splitlines(),
            "ancestor_of_origin_master": subprocess.run(
                ["git", "merge-base", "--is-ancestor", "225c3c2b",
                 "origin/master"], cwd=REPO).returncode == 0,
            "ancestor_of_local_master": subprocess.run(
                ["git", "merge-base", "--is-ancestor", "225c3c2b",
                 "master"], cwd=REPO).returncode == 0,
        },
        "deploy_chain_from_v63_artifacts": {
            "v63_canary_deployed": "c2775a54258512a3e20c97341d3e8a6738b1a33b",
            "v63_canary_version": "2.58.79",
            "pre_deploy_sha_b9ea4907": "b9ea4907ffa52e7b2974e9511113e03350820a6e",
            "later_release_25881": "6d4b9a7d645dcd0e7bd6c63b1e3ce2d367b58221",
            "later_release_25883": "448cc81a9eab590ea6de599f478220dd00abd3d1",
            "repo_app_version_now": None,
        },
        "artifacts": files,
    }
    try:
        src = io.open(os.path.join(REPO, "config", "settings.py"),
                      encoding="utf-8").read()
        i = src.find('APP_VERSION = "')
        baseline["deploy_chain_from_v63_artifacts"]["repo_app_version_now"] = \
            src[i + len('APP_VERSION = "'):].split('"')[0]
    except Exception:  # noqa: BLE001
        pass
    with io.open(os.path.join(OUT, "v63-baseline-record.json"), "w",
                 encoding="utf-8", newline="\n") as fh:
        json.dump(baseline, fh, ensure_ascii=False, indent=2)

    print("status_counts:", statuses)
    print("open_rows:", len(open_rows))
    print("ledger ->", os.path.join(OUT, "v63-live-gates-ledger.json"))
    print("baseline ->", os.path.join(OUT, "v63-baseline-record.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
