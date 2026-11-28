"""Release 2.58.267 static checks: DDL, seeds, routes pin, product identity."""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
RAW = Path(__file__).parent
BASE = "cd2245fdb"
CAND = "718fe0a824522d68aa58605fc2b8ef1711e62534"
PRODUCT = [
    "services/factcheck_renderer.py",
    "services/factcheck_orchestrator.py",
    "services/search_aggregator.py",
    "tests/test_fc_trust_render.py",
]


def git(*args):
    return subprocess.run(('git',) + args, cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()


# 1. product identity (index blob == candidate blob)
lines = []
for rel in PRODUCT:
    idx = git("ls-files", "-s", "--", rel).split()[1]
    cand = git("rev-parse", f"{CAND}:{rel}")
    base = git("rev-parse", "--verify", f"{BASE}:{rel}") if subprocess.run(
        ["git", "cat-file", "-e", f"{BASE}:{rel}"], cwd=ROOT).returncode == 0 else "(absent)"
    lines.append(f"{rel} idx={idx} cand={cand} match={idx == cand} base={base}")
(RAW / "identity.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

# 2. other product changes must be zero outside the 4 files (bump-only files excluded)
BUMP_SET = set(git("show", "--name-only", "--format=", "9ffa54954").splitlines())
diff_names = git("diff", "--name-only", BASE).splitlines()
outside = [n for n in diff_names if n not in PRODUCT and n not in BUMP_SET]
bump_touched = [n for n in diff_names if n in BUMP_SET]
non_version_bump = []
for rel in bump_touched:
    d = git("diff", "-U0", BASE, "--", rel).splitlines()
    rem = [l[1:] for l in d if l.startswith("-") and not l.startswith("---")]
    add = [l[1:] for l in d if l.startswith("+") and not l.startswith("+++")]
    if not all(r.replace("2.58.266", "2.58.267") in set(add) for r in rem):
        non_version_bump.append(rel)
(RAW / "product-delta.txt").write_text(
    "product_files_changed=" + str(len(PRODUCT)) + "\n"
    + "expected:\n" + "\n".join(PRODUCT) + "\n"
    + "--- changed outside listed product files and bump set:\n"
    + ("\n".join(outside) if outside else "(none)") + "\n"
    + f"bump_touched_files={len(bump_touched)}\n"
    + "non_version_bump_files=" + (",".join(non_version_bump) if non_version_bump else "(none)") + "\n"
    + "--- full stat base..HEAD (tracked):\n"
    + git("diff", "--stat", BASE) + "\n", encoding="utf-8")

# 3. DDL / schema constant
migrations = git("diff", "--name-only", BASE, "--", "migrations", "services/database.py", "services/pg_db.py")
schema_consts = []
for p in (ROOT / "services").rglob("*.py"):
    text = p.read_text(encoding="utf-8", errors="replace")
    for ln in text.splitlines():
        if "SCHEMA_VERSION" in ln and "=" in ln and ln.lstrip().startswith("SCHEMA_VERSION"):
            schema_consts.append(f"{p.relative_to(ROOT)}: {ln.strip()}")
ddl_lines = git("diff", "-U0", BASE, "--", "services", "config", "web", "handlers").splitlines()
ddl_hits = [ln for ln in ddl_lines if ln.startswith("+") and any(
    kw in ln.upper() for kw in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE INDEX", "ADD COLUMN"))]
(RAW / "ddl-check.txt").write_text(
    "migrations_or_db_py_changed=" + (migrations or "(none)") + "\n"
    + "schema_constants:\n" + "\n".join(schema_consts) + "\n"
    + f"ddl_delta_lines={len(ddl_hits)}\n"
    + ("\n".join(ddl_hits) if ddl_hits else "(no DDL statements in diff)") + "\n", encoding="utf-8")

# 4. seeds / param catalog
catalog_changed = git("diff", "--name-only", BASE, "--", "services/param_catalog.py")
catalog_blob = git("rev-parse", "HEAD:services/param_catalog.py")
catalog_base = git("rev-parse", f"{BASE}:services/param_catalog.py")
new_limits = [ln for ln in git("diff", "-U0", BASE, "--", "services/param_catalog.py").splitlines()
              if ln.startswith("+") and "factcheck" in ln]
(RAW / "seed-factcheck.txt").write_text(
    f"param_catalog_changed={(catalog_changed or '(none)')}\n"
    f"param_catalog_blob_head={catalog_blob}\n"
    f"param_catalog_blob_base={catalog_base}\n"
    f"same={catalog_blob == catalog_base}\n"
    f"new_factcheck_limits={len(new_limits)}\n", encoding="utf-8")

# 5. routes pin
routes = ROOT / "web/api/routes.py"
digest = hashlib.sha256(routes.read_bytes()).hexdigest()
pin_src = ""
for cand in ("tests/test_webapp_f11_round1025.py", "tests/test_round1025_f8_registry.py"):
    p = ROOT / cand
    if p.exists():
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if "b8f6335" in ln or "ROUTES_SHA256" in ln:
                pin_src += f"{cand}: {ln.strip()}\n"
(RAW / "routes-pin.txt").write_text(
    f"routes_sha256_head={digest}\n"
    f"routes_blob_head={git('rev-parse', 'HEAD:web/api/routes.py')}\n"
    f"routes_blob_base={git('rev-parse', f'{BASE}:web/api/routes.py')}\n"
    f"routes_changed={git('diff', '--name-only', BASE, '--', 'web/api/routes.py') or '(none)'}\n"
    f"pin_matches_b8f63355={digest.startswith('b8f63355')}\n"
    f"--- pin source lines:\n{pin_src}", encoding="utf-8")

print("identity:\n" + "\n".join(lines))
print("outside_product:", outside or "(none)")
print("migrations_changed:", migrations or "(none)")
print("ddl_delta_lines:", len(ddl_hits))
print("catalog_same:", catalog_blob == catalog_base, "new_limits:", len(new_limits))
print("routes_sha256:", digest, "pin_ok:", digest.startswith("b8f63355"))
