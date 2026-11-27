# -*- coding: utf-8 -*-
"""F8-reissue для FCT-303 (S3, 28.11.2026) — ресурсные лимиты retrieval.

Основание: FC-TRUST-01 FCT-303 (S3). В существующий каталог
(`limits_factcheck`) зарегистрированы 9 ключей `limits.factcheck_*`, которые
планировщик уже читал (chat → global → default): заводские значения — код-канон
`services.factcheck_planner.FACTCHECK_*`, поэтому `_seed_settings_into` сидит
их в bot_settings и владелец видит их в админке. GROUPS/_TAB_BY_GROUP/
TAB_RULES/DDL не меняются.

REGISTRY 659→668, delta 258→267.

Запуск: `.venv\\Scripts\\python.exe tools/_fct303_reissue_f8.py`
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

OLD_REGISTRY = 659
OLD_DELTA = 258


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def _write_json_crlf(path: Path, data: dict) -> None:
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
catalog_sha = sha("services/param_catalog.py")
new_count = len(pc.REGISTRY)

_NOTE = (
    "; FCT-303 (28.11.2026, FC-TRUST-01 S3): +9 PG-only ключей ресурсного "
    "контракта retrieval-контура фактчека (limits.factcheck_retrieval_seconds,"
    "_max, refine_calls, max_queries_total, search_text_chars, page_size, "
    "claim_portion, primary_fetches, excerpt_chars) в существующей группе "
    "limits_factcheck; заводские значения — код-канон "
    "services.factcheck_planner.FACTCHECK_* (сид через code_source). "
    "GROUPS/_TAB_BY_GROUP/TAB_RULES/DDL без изменений. REGISTRY %d→%d, "
    "delta %d→%d."
    % (OLD_REGISTRY, new_count, OLD_DELTA, delta)
)

fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = new_count
fx["counts"]["GROUPS"] = len(pc.GROUPS)
fx["counts"]["TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["_TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["TAB_RULES"] = len(pc.TAB_RULES)
fx["counts"]["delta"] = delta
fx["sha256"] = catalog_sha
if "FCT-303" not in str(fx.get("superseded_by", "")):
    fx["superseded_by"] = str(fx.get("superseded_by", "")) + _NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))

cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid)
                   for gid in sorted(g.id for g in pc.GROUPS)}
cb["counts"] = {"REGISTRY": new_count, "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
provenance = cb.get("_provenance") or {}
if isinstance(provenance, dict) and "FCT-303" not in \
        str(provenance.get("note", "")):
    provenance["note"] = str(provenance.get("note", "")) + " | " + _NOTE
    cb["_provenance"] = provenance
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))

_REPLACEMENTS = (
    (r"len\(pc\.REGISTRY\) == %d" % OLD_REGISTRY,
     "len(pc.REGISTRY) == %d" % new_count),
    (r"len\(REGISTRY\) == %d" % OLD_REGISTRY,
     "len(REGISTRY) == %d" % new_count),
    (r"len\(rows\) == %d" % OLD_REGISTRY, "len(rows) == %d" % new_count),
    (r"len\(keys\) == %d" % OLD_REGISTRY, "len(keys) == %d" % new_count),
    (r"len\(tsv\) - 1 == %d" % OLD_REGISTRY,
     "len(tsv) - 1 == %d" % new_count),
    (r'len\(cb\["registry_keys"\]\) == %d' % OLD_REGISTRY,
     'len(cb["registry_keys"]) == %d' % new_count),
    (r'fx\["counts"\]\["REGISTRY"\] == %d' % OLD_REGISTRY,
     'fx["counts"]["REGISTRY"] == %d' % new_count),
    (r'FIXTURE\["counts"\]\["REGISTRY"\] == %d' % OLD_REGISTRY,
     'FIXTURE["counts"]["REGISTRY"] == %d' % new_count),
    (r'BASELINE\["counts"\]\["REGISTRY"\] == %d' % OLD_REGISTRY,
     'BASELINE["counts"]["REGISTRY"] == %d' % new_count),
    (r'"%d" in res\.stdout' % OLD_REGISTRY,
     '"%d" in res.stdout' % new_count),
    (r'"%d" in meta and "411" in meta and "%d" in meta'
     % (OLD_REGISTRY, OLD_DELTA),
     '"%d" in meta and "411" in meta and "%d" in meta'
     % (new_count, delta)),
    (r'fx\["counts"\]\["delta"\] == %d' % OLD_DELTA,
     'fx["counts"]["delta"] == %d' % delta),
    (r'FIXTURE\["counts"\]\["delta"\] == %d' % OLD_DELTA,
     'FIXTURE["counts"]["delta"] == %d' % delta),
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
        print("pins updated:", path.name)
print("test files updated:", changed)
print("REGISTRY:", new_count, "delta:", delta, "sha:", catalog_sha)
