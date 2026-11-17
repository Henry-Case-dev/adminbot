# -*- coding: utf-8 -*-
"""F8-переиздание каталога для QRNG P3 — селектор/fallback (17.11.2026).

Санкция: ARCH_DECISION `plans/features/vmq-onto-01/evidence/qrng-recovery/
arch-decision-2026-11-17.md` §3 D4/D5/D6 + поручение P3 — три ГЛОБАЛЬНЫХ
PG-only параметра (`random.primary_provider`, `random.fallback_order`,
`random.fallback_enabled`), группа memory_random уже существует; GROUPS/
_TAB_BY_GROUP/TAB_RULES не меняются. REGISTRY 645→648, delta 244→247.
`keys.random_quantum_provider` скрыт (hidden) — состав REGISTRY не меняется.

Шаги (прецедент `tools/_selfdiag01_d4b_reissue_f8.py`):
  1) регенерирует TSV/meta/screen-map (`gen_param_registry_round1025`);
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) переносит catalog-guard пины в тестах (645→648, delta 244→247) и
     переутверждает SHA256 param_catalog.py;
  4) печатает sha256 param_catalog.py.

Запуск: `.venv\\Scripts\\python.exe tools/_qrng_p3_reissue_f8.py`
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

OLD_COUNT = 645
OLD_DELTA = 244


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
catalog_sha = sha("services/param_catalog.py")

_NOTE = (
    "; QRNG P3 (17.11.2026, arch D4/D5/D6): +3 PG-only ГЛОБАЛЬНЫХ параметра "
    "селектора — random.primary_provider (select ibm_quantum|anu|lfdr, "
    "default ibm_quantum), random.fallback_order (json), "
    "random.fallback_enabled (bool, default true); группа memory_random "
    "(GROUPS/_TAB_BY_GROUP/TAB_RULES без изменений). "
    "keys.random_quantum_provider скрыт (hidden; строка/значение остаются). "
    "REGISTRY 645→%d, delta 244→%d."
    % (len(pc.REGISTRY), delta)
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
if "QRNG P3" not in fx.get("_provenance_note", ""):
    fx["_provenance_note"] = fx.get("_provenance_note", "") + _NOTE
if "QRNG P3" not in fx.get("superseded_by", ""):
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
if isinstance(provenance, dict) and "QRNG P3" not in \
        str(provenance.get("note", "")):
    provenance["note"] = str(provenance.get("note", "")) + " | " + _NOTE
    cb["_provenance"] = provenance
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))

_REPLACEMENTS = (
    (r"len\(pc\.REGISTRY\) == 645",
     "len(pc.REGISTRY) == %d" % len(pc.REGISTRY)),
    (r"len\(REGISTRY\) == 645",
     "len(REGISTRY) == %d" % len(pc.REGISTRY)),
    (r"len\(rows\) == 645", "len(rows) == %d" % len(pc.REGISTRY)),
    (r"len\(keys\) == 645", "len(keys) == %d" % len(pc.REGISTRY)),
    (r"len\(tsv\) - 1 == 645", "len(tsv) - 1 == %d" % len(pc.REGISTRY)),
    (r"len\(cb\[\"registry_keys\"\]\) == 645",
     "len(cb[\"registry_keys\"]) == %d" % len(pc.REGISTRY)),
    (r"fx\[\"counts\"\]\[\"REGISTRY\"\] == 645",
     "fx[\"counts\"][\"REGISTRY\"] == %d" % len(pc.REGISTRY)),
    (r"FIXTURE\[\"counts\"\]\[\"REGISTRY\"\] == 645",
     "FIXTURE[\"counts\"][\"REGISTRY\"] == %d" % len(pc.REGISTRY)),
    (r"fx\[\"counts\"\]\[\"delta\"\] == 244",
     "fx[\"counts\"][\"delta\"] == %d" % delta),
    (r"FIXTURE\[\"counts\"\]\[\"delta\"\] == 244",
     "FIXTURE[\"counts\"][\"delta\"] == %d" % delta),
    (r"\"645\" in res\.stdout", "\"%d\" in res.stdout" % len(pc.REGISTRY)),
    (r"\"645\" in meta and \"411\" in meta and \"244\" in meta",
     "\"%d\" in meta and \"411\" in meta and \"%d\" in meta"
     % (len(pc.REGISTRY), delta)),
    # categorized-счётчик (REGISTRY без env-only/infra): 619 → 622.
    (r"== 619", "== 622"),
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
print("REGISTRY:", len(pc.REGISTRY), "delta:", delta)
