# -*- coding: utf-8 -*-
"""F8-переиздание каталога для SELF-DIAG-01 D1 (09.11.2026).

Санкция: brief SELF-DIAG-01 D1 (requirements-map SD1-D1-08/09/14/17) —
адресное удаление Better Stack ИЗ ЧЕКАПА: 5 checkup-only SQL-ключей
(CHECKUP_BETTERSTACK_SQL_*) и старый CHECKUP_JOURNALCTL_CMD; вместо них
2 env-only инфра-ключа нового локального backend'а (CHECKUP_LOG_WINDOW_LINES,
CHECKUP_LOG_UNIT). Группы models_checkup/keys_betterstack (карточки
«Диагностики») удалены целиком.

Δ каталога: REGISTRY 599→595, GROUPS 121→119, _TAB_BY_GROUP 119→117,
TAB_RULES 22 in-place, delta 193→194 (удалённые ключи были baseline-ом,
два новых — status=new), secret-строки 43→41.

Шаги (прецедент `tools/_mca19_reissue_f8.py`):
  1) регенерирует TSV/meta/screen-map (`gen_param_registry_round1025`);
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) переносит catalog-guard счётчики в тестах (599/121/119/471 → 595/119/117/467);
  4) печатает sha256 файлов инвариантов (routes/pg_db НЕ меняются).

Запуск: `.venv\\Scripts\\python.exe tools/_selfdiag01_d1_reissue_f8.py`
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def _write_json_crlf(path: Path, data: dict) -> None:
    """Записать JSON, сохранив CRLF-конвенции исходного файла (min diff)."""
    raw = path.read_bytes()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes((text + ("\r\n" if b"\r\n" in raw else "\n"))
                     .encode("utf-8"))


# ── 1) регенерация F8 (TSV/meta/screen-map) ────────────────────────────────
rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")
rows = gen.build_rows()
delta = sum(1 for r in rows if r["status"] == "new")
secret_rows = sum(1 for r in rows if r["secret"] == "true")

# ── 2) fixtures ────────────────────────────────────────────────────────────
fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = 595
fx["counts"]["GROUPS"] = 119
fx["counts"]["TAB_BY_GROUP"] = 117
fx["counts"]["TAB_RULES"] = 22
fx["counts"]["_TAB_BY_GROUP"] = 117
fx["counts"]["delta"] = delta
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
_NOTE = (
    "; SELF-DIAG-01 D1 (09.11.2026, requirements-map SD1-D1-08/09/14/17): "
    "адресное удаление Better Stack ИЗ ЧЕКАПНОГО пути — −5 checkup-only "
    "ParamSpec (CHECKUP_BETTERSTACK_SQL_HOST/USER/PASSWORD/TABLE/QUERY) и "
    "CHECKUP_JOURNALCTL_CMD (shell-команда с устаревшим unit), +2 env-only "
    "ключа локального backend'а (CHECKUP_LOG_WINDOW_LINES/CHECKUP_LOG_UNIT); "
    "группы models_checkup/keys_betterstack (карточки «Диагностики») удалены. "
    "REGISTRY 599→595, GROUPS 121→119, _TAB_BY_GROUP 119→117, TAB_RULES 22 "
    "in-place, delta 193→%d, secret-строки 43→%d. Глобальный "
    "services/betterstack_handler.py (observability ingest) НЕ затронут; "
    "routes.py и pg_db.py без изменений." % (delta, secret_rows)
)
if "SELF-DIAG-01 D1" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))

cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
from services import param_catalog as pc  # noqa: E402

cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid)
                   for gid in sorted(g.id for g in pc.GROUPS)}
cb["tab_nav"] = {tid: pc.tab_nav(tid)
                 for tid in sorted(set(cb["tab_nav"]) | set(pc.TAB_NAV))}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))

# ── 3) catalog-guard счётчики в тестах ─────────────────────────────────────
_REPLACEMENTS = (
    (r"len\(pc\.REGISTRY\) == 599", "len(pc.REGISTRY) == 595"),
    (r"len\(REGISTRY\) == 599", "len(REGISTRY) == 595"),
    (r"len\(rows\) == 599", "len(rows) == 595"),
    (r"len\(keys\) == 599", "len(keys) == 595"),
    (r"len\(cb\[\"registry_keys\"\]\) == 599", "len(cb[\"registry_keys\"]) == 595"),
    (r"\[\"counts\"\]\[\"REGISTRY\"\] == 599",
     "[\"counts\"][\"REGISTRY\"] == 595"),
    (r"\[\"counts\"\]\[\"GROUPS\"\] == 121",
     "[\"counts\"][\"GROUPS\"] == 119"),
    (r"len\(pc\.GROUPS\) == 121", "len(pc.GROUPS) == 119"),
    (r"len\(GROUPS\) == 121", "len(GROUPS) == 119"),
    (r"\[\"counts\"\]\[\"TAB_BY_GROUP\"\] == 119",
     "[\"counts\"][\"TAB_BY_GROUP\"] == 117"),
    (r"\[\"counts\"\]\[\"_TAB_BY_GROUP\"\] == 119",
     "[\"counts\"][\"_TAB_BY_GROUP\"] == 117"),
    (r"len\(pc\._TAB_BY_GROUP\) == 119", "len(pc._TAB_BY_GROUP) == 117"),
    (r"\[\"counts\"\]\[\"delta\"\] == 193", "[\"counts\"][\"delta\"] == %d" % delta),
    (r"len\(fields\) == 471", "len(fields) == 467"),
    (r"len\(api_only\) == 25", "len(api_only) == 26"),
    (r"\"599\" in meta and \"411\" in meta and \"193\" in meta",
     "\"595\" in meta and \"411\" in meta and \"%d\" in meta" % delta),
    (r"len\(\{f\.name for f in dataclasses\.fields\(Settings\)\}\) == 471",
     "len({f.name for f in dataclasses.fields(Settings)}) == 467"),
    (r"len\(dataclasses\.fields\(Settings\)\) == 471",
     "len(dataclasses.fields(Settings)) == 467"),
    (r"len\(secret_rows\) == 43", "len(secret_rows) == %d" % secret_rows),
    (r"len\(tsv\) - 1 == 599", "len(tsv) - 1 == 595"),
)
changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    text = path.read_text(encoding="utf-8")
    new = text
    for pat, repl in _REPLACEMENTS:
        new = re.sub(pat, repl, new)
    if new != text:
        path.write_text(new, encoding="utf-8")
        changed += 1
print("guard-файлы обновлены:", changed)

# ── 4) инварианты: sha256 файлов, которые НЕ должны меняться ──────────────
print("routes.py  sha256 =", sha("web/api/routes.py"))
print("pg_db.py   sha256 =", sha("services/pg_db.py"))
print("param_catalog sha256 =", sha("services/param_catalog.py"))
