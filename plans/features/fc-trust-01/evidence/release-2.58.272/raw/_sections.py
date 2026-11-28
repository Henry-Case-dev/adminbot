"""Builds the compact deploy-* evidence slices from the raw run logs.

Every derived line is copied verbatim from a named raw file (selectors are the
grep prefixes documented in the header of each output). The raw logs stay in
place; nothing is reconstructed or re-typed.
"""
from pathlib import Path

RAW = Path(__file__).parent
RUN1 = (RAW / "deploy-run.txt").read_text(encoding="utf-8", errors="replace").splitlines()
RUN2 = (RAW / "deploy-run2.txt").read_text(encoding="utf-8", errors="replace").splitlines()
RUN3 = (RAW / "deploy-run3.txt").read_text(encoding="utf-8", errors="replace").splitlines()
RUN4 = (RAW / "deploy-run4.txt").read_text(encoding="utf-8", errors="replace").splitlines()


def pick(lines, prefixes):
    out = []
    for line in lines:
        if any(line.startswith(p) for p in prefixes):
            out.append(line)
    return out


def write(name, header, body):
    (RAW / name).write_text("\n".join([header] + body) + "\n", encoding="utf-8")


write(
    "deploy-identity.txt",
    "# verbatim slices: run1 (PRE/POST_CHECKOUT/MANIFEST/RESTART/health/unit) "
    "+ run2 (VERSION/ENV/UNIT) + run3 (GIT STATE/FACTORY) + run4 (FINAL STATE)",
    pick(RUN1, ["PRE_", "PY=", "REMOTE_SHA=", "NEW_HEAD=", "POST_CHECKOUT_DIRTY_TRACKED=",
                "MANIFEST=", "RESTART_MARK=", "LOCAL_HEALTHZ", "PUBLIC_HEALTHZ", "UNIT=",
                "[release-manifest]"])
    + pick(RUN2, ["PY=", "PY_VERSION=", "VER_", "FRESH_EFFECTIVE=", "ENV_", "UNIT="])
    + pick(RUN3, ["HEAD=", "REF=", "DIRTY_TRACKED=", "WORKTREES=", "FACTORY_LITERAL="])
    + pick(RUN4, ["HEAD=", "DIRTY_TRACKED=", "MANIFEST=", "UNIT=", "HEALTHZ="]),
)

write(
    "deploy-db.txt",
    "# verbatim slices: run1 (SQLITE pre/post, QUICK_CHECK) + run2 (PG SETTINGS) + run4 (MD5 probes)",
    pick(RUN1, ["SQLITE_USER_VERSION=", "QUICK_CHECK=", "USER_VERSION_AFTER="])
    + pick(RUN2, ["SETTINGS_", "PROMPTS_KEYS=", "HOT_FLAG="])
    + pick(RUN4, ["ROWS=", "MD5_", "TARGET="]),
)

write(
    "deploy-journal.txt",
    "# verbatim slice: run2 journal window since the restart mark (2026-11-28T08:14:35Z)",
    pick(RUN2, ["JOURNAL_", "NOW=", "Nov 28"]),
)

write(
    "deploy-disk.txt",
    "# verbatim slice: run1 + run2 disk audit / cleanup --apply",
    pick(RUN1, ["/dev/vda1"])
    + pick(RUN2, ["/dev/vda1", "  total_bytes=", "  log_retention_days=", "  top:",
                  "  forecast", "disk cleanup:"]),
)

write(
    "deploy-rollback.txt",
    "# verbatim slice: run1 rollback dry-run to 3a78484b9 (effect=rollback)",
    pick(RUN1, ["RB_VERSION=", "RB_RC=", "RB_WORKTREE_LEFT="])
    + [ln for ln in RUN1 if ln.startswith('{  "deployed_at"')],
)

write(
    "deploy-health.txt",
    "# verbatim slice: run1/run2/run4 health, unit, public endpoint",
    pick(RUN1, ["LOCAL_HEALTHZ", "PUBLIC_HEALTHZ", "UNIT=", "AGG", "BODY_HAS", "HTTP_CODE", "{\"detail\""])
    + pick(RUN2, ["UNIT=", "BOTPROCS=", "HEALTHZ=", "AGG_HTTP=", "APPJS_HTTP=", "APPJS_REMOTE_BYTES="])
    + pick(RUN4, ["HEALTHZ=", "UNIT=", "DF="]),
)

write(
    "deploy-file-identity.txt",
    "# verbatim slice: run1 sha256 of deployed files (compare assembly.md); plus sizes",
    [ln for ln in RUN1 if any(f in ln for f in (
        "web/api/routes.py", "web/app.js", "web/index.html", "config/settings.py",
        "services/factcheck_orchestrator.py", "services/factcheck_prompts.py"))
     and not ln.lstrip().startswith("File ")]
    + pick(RUN1, ["APPJS_BYTES="]),
)

write(
    "deploy-hygiene.txt",
    "# verbatim slice: run3/run4 orphan-process and /tmp audit",
    pick(RUN3, ["PYTEST_PROCS=", "TMP_WT=", "TMP_FILES_MINE=", "PPID1_PYTEST=", "UNTRACKED_TOP="])
    + pick(RUN4, ["TMP_AUDIT_COUNT=", "TMP_DIRS=", "REMOVING ", "TMP_AFTER=", "TMP_WORKTREES"]),
)

print("sections written")
for p in sorted(RAW.glob("deploy-*.txt")):
    print(f"{p.name} {p.stat().st_size}B")
