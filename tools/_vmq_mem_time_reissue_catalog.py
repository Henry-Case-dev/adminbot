# -*- coding: utf-8 -*-
"""VMQ-MEM-TIME: переиздание F8-артефактов каталога (прецедент
`tools/_asap5_w2_reissue_f8.py`).

Δ каталога: +5 ParamSpec `limits.graph_hist_*` /
`limits.graph_mmr_fetch_k_historical` (+5 Settings-полей), группа
`limits_graph` IN-PLACE, GROUPS/TAB_BY_GROUP/TAB_RULES без изменений:
REGISTRY 638→643, delta 237→242 (inventory 411 не менялся).

Шаги:
  1) регенерация TSV/meta/screen-map/widget-map (`gen_param_registry_round1025`);
  2) fixtures `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) пины счётчиков/хэша каталога в тестах.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402

print("delta rows:", len([r for r in gen.build_rows() if r["status"] == "new"]))


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

from services import param_catalog as pc  # noqa: E402

fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = len(pc.REGISTRY)
fx["counts"]["GROUPS"] = len(pc.GROUPS)
fx["counts"]["TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["_TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["TAB_RULES"] = len(pc.TAB_RULES)
fx["counts"]["delta"] = len([r for r in gen.build_rows()
                            if r["status"] == "new"])
if isinstance(fx.get("sha256"), dict):
    fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
else:
    fx["sha256"] = sha("services/param_catalog.py")
blob = "\n".join((ROOT / p).read_text(encoding="utf-8")
                 for p in fx["artifacts"])
fx["sha256_artifacts"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
_NOTE = (
    "; VMQ-MEM-TIME (10.11.2026): санкционированная Δ каталога +5 ParamSpec "
    "limits.graph_hist_fresh_tiebreak / limits.graph_hist_horizon_days / "
    "limits.graph_hist_rel_floor / limits.graph_hist_max_share / "
    "limits.graph_mmr_fetch_k_historical (группа limits_graph IN-PLACE, "
    "per-chat overrides работают; сохранённые настройки не сбрасываются): "
    "REGISTRY 638→643, delta 237→242 (inventory 411 не менялся); GROUPS/"
    "_TAB_BY_GROUP/TAB_RULES/routes без изменений."
)
fx["superseded_by"] = fx.get("superseded_by", "") + _NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline:", fx["counts"])

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
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]), cb["counts"])

_REG = (r"len\(pc\.REGISTRY\) == 638", "len(pc.REGISTRY) == 643")
_REPLACEMENTS = (
    (r"len\(rows\) == 638", "len(rows) == 643"),
    (r"len\(keys\) == 638", "len(keys) == 643"),
    (r"\[\"counts\"\]\[\"delta\"\] == 237",
     "[\"counts\"][\"delta\"] == 242"),
    (r"\"638\" in meta and \"411\" in meta and \"237\" in meta",
     "\"643\" in meta and \"411\" in meta and \"242\" in meta"),
    (r"PARAM_CATALOG_SHA256_FOLLOWUP = \(\n    \"[0-9a-f]{64}\"\)",
     "PARAM_CATALOG_SHA256_FOLLOWUP = (\n    \"%s\")" % sha("services/param_catalog.py")),
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
        print("pins:", path.name)
print("files changed:", changed)
