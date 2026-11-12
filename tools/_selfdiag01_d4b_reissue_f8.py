# -*- coding: utf-8 -*-
"""F8-переиздание каталога для SELF-DIAG-01 D4-B (13.11.2026).

Санкция: brief D4-B (contract §2.4/§3; requirements-map SD1-D4-01/03/04/13,
SD1-SEM-04) — одна PG-only owner-настройка `flags.self_diag_repo_origin`
(канонический repo identity, non-secret): REGISTRY 643→644, delta 242→243;
GROUPS/_TAB_BY_GROUP/TAB_RULES не меняются (группа flags_service уже есть).

Шаги (прецедент `tools/_selfdiag01_d1_reissue_f8.py`):
  1) регенерирует TSV/meta/screen-map (`gen_param_registry_round1025`);
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) переносит catalog-guard пины в `test_round1025_f8_registry.py`
     (643→644, delta 242→243) и переутверждает SHA256 param_catalog.py;
  4) печатает sha256 param_catalog.py.

Запуск: `.venv\\Scripts\\python.exe tools/_selfdiag01_d4b_reissue_f8.py`
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402
from services import param_catalog as pc  # noqa: E402


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


rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")
rows = gen.build_rows()
delta = sum(1 for r in rows if r["status"] == "new")
secret_rows = sum(1 for r in rows if r["secret"] == "true")
catalog_sha = sha("services/param_catalog.py")

_NOTE = (
    "; SELF-DIAG-01 D4-B (13.11.2026, contract §2.4/§3): +1 PG-only "
    "non-secret owner-настройка flags.self_diag_repo_origin (канонический "
    "repo identity SELF-DIAG, owner/name; userinfo/токены вырезаются). "
    "REGISTRY 643→644, delta 242→%d, GROUPS/_TAB_BY_GROUP/TAB_RULES без "
    "изменений (flags_service уже существует); Settings-полей/секретов/"
    "routes/pg_db без изменений." % delta
)

fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = len(pc.REGISTRY)
fx["counts"]["GROUPS"] = len(pc.GROUPS)
fx["counts"]["TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["_TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["TAB_RULES"] = len(pc.TAB_RULES)
fx["counts"]["delta"] = delta
fx["sha256"] = catalog_sha
if "SELF-DIAG-01 D4-B" not in fx.get("_provenance_note", ""):
    fx["_provenance_note"] = fx.get("_provenance_note", "") + _NOTE
if "SELF-DIAG-01 D4-B" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))

cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid)
                   for gid in sorted(g.id for g in pc.GROUPS)}
cb["tab_nav"] = {tid: pc.tab_nav(tid)
                 for tid in sorted(set(cb["tab_nav"]) | set(pc.TAB_NAV))}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
provenance = cb.get("_provenance") or {}
if isinstance(provenance, dict) and "SELF-DIAG-01 D4-B" not in \
        str(provenance.get("note", "")):
    provenance["note"] = str(provenance.get("note", "")) + " | " + _NOTE
    cb["_provenance"] = provenance
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))

_REPLACEMENTS = (
    (r"len\(rows\) == 643", "len(rows) == %d" % len(pc.REGISTRY)),
    (r"len\(keys\) == 643", "len(keys) == %d" % len(pc.REGISTRY)),
    (r"FIXTURE\[\"counts\"\]\[\"delta\"\] == 242",
     "FIXTURE[\"counts\"][\"delta\"] == %d" % delta),
    (r"\"643\" in meta and \"411\" in meta and \"242\" in meta",
     "\"%d\" in meta and \"411\" in meta and \"%d\" in meta"
     % (len(pc.REGISTRY), delta)),
    (r"len\(tsv\) - 1 == 643", "len(tsv) - 1 == %d" % len(pc.REGISTRY)),
    (r"(PARAM_CATALOG_SHA256_FOLLOWUP = \(\s*\")[0-9a-f]{64}(\")",
     r"\g<1>%s\g<2>" % catalog_sha),
)
changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    new = text
    for pat, repl in _REPLACEMENTS:
        new = re.sub(pat, repl, new)
    if new != text:
        path.write_bytes(new.encode("utf-8"))
        changed += 1
print("guard-файлы обновлены:", changed)
print("param_catalog sha256 =", catalog_sha)
print("secret-строки:", secret_rows)
