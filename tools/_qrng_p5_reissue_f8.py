# -*- coding: utf-8 -*-
"""F8-reissue для QRNG P5 — IBM Quantum Platform (24.11.2026).

Основание: owner input `plans/owner_inputs/2026-11-24-qrng-ibm-p5-ui-correction.md`
+ map QAN-REC-IBM-01…03. Добавлены 5 IBM-полей (`keys.random_ibm_*`) и 6
PG-only лимитов (`random.ibm.*`); GROUPS/_TAB_BY_GROUP/TAB_RULES не меняются.
REGISTRY 648→659, delta 247→258, Settings 472→477.

Запуск: `.venv\\Scripts\\python.exe tools/_qrng_p5_reissue_f8.py`
"""
import dataclasses
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402
from services import param_catalog as pc  # noqa: E402

OLD_REGISTRY = 648
OLD_DELTA = 247
OLD_SETTINGS = 472


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
from config.settings import Settings  # noqa: E402

new_settings = len({f.name for f in dataclasses.fields(Settings)})

_NOTE = (
    "; QRNG P5 (24.11.2026, QAN-REC-IBM-01…03): +5 ключей IBM "
    "(keys.random_ibm_api_key/crn/instance/region/channel; key и CRN — "
    "раздельные secret-поля) +6 PG-only лимитов random.ibm.* "
    "(http_timeout/poll_interval/job_max_age/max_inflight/max_jobs_per_day/"
    "max_qpu_seconds_per_day); GROUPS/_TAB_BY_GROUP/TAB_RULES без изменений. "
    "REGISTRY %d→%d, delta %d→%d, Settings %d→%d."
    % (OLD_REGISTRY, new_count, OLD_DELTA, delta, OLD_SETTINGS, new_settings)
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
if "QRNG P5" not in fx.get("_provenance_note", ""):
    fx["_provenance_note"] = fx.get("_provenance_note", "") + _NOTE
if "QRNG P5" not in fx.get("superseded_by", ""):
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
cb["counts"] = {"REGISTRY": new_count, "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
provenance = cb.get("_provenance") or {}
if isinstance(provenance, dict) and "QRNG P5" not in \
        str(provenance.get("note", "")):
    provenance["note"] = str(provenance.get("note", "")) + " | " + _NOTE
    cb["_provenance"] = provenance
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))

# QRNG P4 fixture переиздаётся: keys_random/memory_random получили IBM-ключи.
qrng_path = ROOT / "tests/fixtures/qrng_p4_random_keys.json"
qrng_groups = {}
for gid in ("memory_random", "keys_random"):
    qrng_groups[gid] = sorted(
        s.pg_key for s in pc.REGISTRY.values()
        if s.group == gid and not s.hidden
        and s.pg_key != "memory.random_enabled")
qrng_data = {
    "groups": qrng_groups,
    "master": "memory.random_enabled",
    "page_keys": sorted({k for keys in qrng_groups.values() for k in keys}),
}
_write_json_crlf(qrng_path, qrng_data)
print("qrng_p4_random_keys:", len(qrng_data["page_keys"]))

_REPLACEMENTS = (
    (r"len\(pc\.REGISTRY\) == 648", "len(pc.REGISTRY) == %d" % new_count),
    (r"len\(REGISTRY\) == 648", "len(REGISTRY) == %d" % new_count),
    (r"len\(rows\) == 648", "len(rows) == %d" % new_count),
    (r"len\(keys\) == 648", "len(keys) == %d" % new_count),
    (r"len\(tsv\) - 1 == 648", "len(tsv) - 1 == %d" % new_count),
    (r"len\(cb\[\"registry_keys\"\]\) == 648",
     "len(cb[\"registry_keys\"]) == %d" % new_count),
    (r"fx\[\"counts\"\]\[\"REGISTRY\"\] == 648",
     "fx[\"counts\"][\"REGISTRY\"] == %d" % new_count),
    (r"FIXTURE\[\"counts\"\]\[\"REGISTRY\"\] == 648",
     "FIXTURE[\"counts\"][\"REGISTRY\"] == %d" % new_count),
    (r"BASELINE\[\"counts\"\]\[\"REGISTRY\"\] == 648",
     "BASELINE[\"counts\"][\"REGISTRY\"] == %d" % new_count),
    (r"fx\[\"counts\"\]\[\"delta\"\] == 247",
     "fx[\"counts\"][\"delta\"] == %d" % delta),
    (r"FIXTURE\[\"counts\"\]\[\"delta\"\] == 247",
     "FIXTURE[\"counts\"][\"delta\"] == %d" % delta),
    (r"\"648\" in res\.stdout", "\"%d\" in res.stdout" % new_count),
    (r"\"648\" in meta and \"411\" in meta and \"247\" in meta",
     "\"%d\" in meta and \"411\" in meta and \"%d\" in meta"
     % (new_count, delta)),
    (r"len\(\{f\.name for f in dataclasses\.fields\(Settings\)\}\) == 472",
     "len({f.name for f in dataclasses.fields(Settings)}) == %d"
     % new_settings),
    (r"len\(dataclasses\.fields\(Settings\)\) == 472",
     "len(dataclasses.fields(Settings)) == %d" % new_settings),
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
print("guard-файлов обновлено:", changed)
print("param_catalog sha256 =", catalog_sha)
print("REGISTRY:", new_count, "delta:", delta, "Settings:", new_settings)
