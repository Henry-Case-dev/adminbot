"""DDL / pin check for release 2.58.269 (S6-U1 schema v49 -> v50).

Migration body is parsed with `ast` so the docstring (which mentions the
rollback SQL) does not count as executed DDL/DML.
"""
import ast
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
OUT = Path(__file__).with_name("ddl-check.txt")
BASE = "e46aa0696"
CAND = "fa3cb0391f53728d1b64961b34d49cf8eee9174e"


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=check).stdout


lines = []
changed = [f for f in git("diff", "--name-only", BASE).split() if f]
ddl_files = [f for f in changed
             if f == "services/database.py" or f.startswith("migrations")]
lines.append(f"migrations_or_db_py_changed={ddl_files or '(none)'}")

db_src = (ROOT / "services/database.py").read_text(encoding="utf-8")
consts = sorted({int(v) for v in re.findall(r"_SCHEMA_VERSION_[A-Z0-9_]+ = (\d+)", db_src)})
lines.append(f"max_schema_constant={max(consts)} constants={len(consts)}")
lines.append(f"run_link_constant_present={'_SCHEMA_VERSION_FACTCHECK_RUN_LINK = 50' in db_src}")
lines.append(f"migration_step_present={'factcheck_run_link_v50' in db_src}")

# constants used by the migration (ADD COLUMN declarations + index DDL)
const_map = {}
for node in ast.parse(db_src).body:
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        try:
            val = ast.literal_eval(node.value)
        except Exception:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Name):
                const_map[t.id] = val

tree = ast.parse(db_src)
funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
mig = funcs["_migrate_factcheck_run_link_v50"]
doc_value = (mig.body[0].value.value
             if mig.body and isinstance(mig.body[0], ast.Expr)
             and isinstance(mig.body[0].value, ast.Constant)
             and isinstance(mig.body[0].value.value, str) else "")
mig_code = "\n".join(ast.unparse(st) for st in mig.body[1:])
mig_lines = [ln.strip() for ln in mig_code.splitlines() if ln.strip()]

lines.append("migration_body_string_literals:")
lits = [n.value for n in ast.walk(mig) if isinstance(n, ast.Constant)
        and isinstance(n.value, str) and n.value.strip()]
for s in lits:
    lines.append("  " + s.replace("\n", " ")[:160])

lines.append("migration_referenced_constants:")
for name in ("_FACTCHECK_RUN_LINK_COLUMNS", "_FACTCHECK_EVIDENCE_LINK_COLUMNS",
             "_MCA_FACTCHECK_RUN_CORRELATION_INDEX_DDL"):
    lines.append(f"  {name}={const_map.get(name, '(unresolved)')}")

ddl_stmts = [s for s in lits if s.startswith(("ALTER TABLE", "CREATE INDEX",
                                              "CREATE TABLE", "PRAGMA user_version"))
             or s.startswith("ADD COLUMN")]
lines.append(f"migration_ddl_statements={len(ddl_stmts)}")
for s in ddl_stmts:
    lines.append("  " + s[:160])

dml = [ln for ln in mig_lines
       if re.match(r"(await self\.db\.execute|await conn|.*\bUPDATE\b|\bDELETE\b|\bDROP\b)", ln)
       and ("execute" in ln or ln.startswith(("UPDATE", "DELETE", "DROP")))]
dml = [ln for ln in dml
       if not ln.startswith(("if ", "cols =", "for ", "await self._table_exists",
                             "await self._table_columns"))]
lines.append("migration_body_executed_statements_mentioning_dml:")
for ln in dml:
    lines.append("  " + ln[:160])
lines.append(f"legacy_rows_untouched_no_update_delete={'UPDATE' not in mig_code.upper() and 'DELETE' not in mig_code.upper()}")
lines.append(f"rollback_sql_documented_in_docstring={'PRAGMA user_version = 49' in doc_value}")

# --- runtime writer changes (NOT migration): append-only + extended columns --
diff = git("diff", "-U0", BASE, CAND, "--", "services/database.py")
added = [ln[1:].strip() for ln in diff.splitlines()
         if ln.startswith("+") and not ln.startswith("+++")]
runtime_dml = [ln for ln in added if re.match(r'"(UPDATE|INSERT|DELETE|DROP)', ln)]
lines.append("runtime_dml_added_lines (outside migration):")
for ln in runtime_dml:
    lines.append("  + " + ln[:150])
lines.append("stage_trace_update_present=%s" % any(
    "UPDATE mca_factcheck_runs SET stage_trace" in ln for ln in runtime_dml))
lines.append("insert_column_lists_extended=%s" % (
    any("INSERT INTO mca_factcheck_runs (run_id, correlation_id" in ln for ln in runtime_dml)
    and any("INSERT INTO mca_factcheck_evidence (run_id, evidence_id" in ln
            for ln in runtime_dml)))
lines.append("backfill_statements=%s" % ([ln for ln in runtime_dml
                                          if re.search(r"UPDATE[^;]*WHERE[^;]*IS NULL", ln)]
                                         or "(none)"))
lines.append("schema_migrations_rows_only_added_no_delete=%s" % (
    "DELETE FROM schema_migrations" not in db_src))

# --- pins -------------------------------------------------------------------
for rel in ("web/api/routes.py", "web/app.js"):
    sha = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
    lines.append(f"{rel}_sha256={sha}")
routes_sha = hashlib.sha256((ROOT / "web/api/routes.py").read_bytes()).hexdigest()
lines.append("routes_pin_b8f63355=%s" % routes_sha.startswith(
    "b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a"))
lines.append(f"routes_or_appjs_in_diff={[f for f in changed if f in ('web/api/routes.py', 'web/app.js')] or '(none)'}")

lines.append("rollback_sql_v50_to_v49:")
lines.append("  DROP INDEX IF EXISTS idx_mca_factcheck_runs_correlation;")
lines.append("  ALTER TABLE mca_factcheck_runs DROP COLUMN correlation_id;")
lines.append("  ALTER TABLE mca_factcheck_evidence DROP COLUMN evidence_id;")
lines.append("  ALTER TABLE mca_factcheck_evidence DROP COLUMN opened;")
lines.append("  ALTER TABLE mca_factcheck_evidence DROP COLUMN strength;")
lines.append("  PRAGMA user_version = 49;")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
