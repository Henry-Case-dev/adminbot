# -*- coding: utf-8 -*-
"""F8-переиздание каталога для MCA-20 (round 10.44).

Санкция: spec §7.2 / ADR-1028-20 D13 / arch-frames §1.2.9 — Δ каталога
+4 ParamSpec/+1 GroupSpec (REGISTRY 519→523, GROUPS 112→113,
_TAB_BY_GROUP 110→111, TAB_RULES 22 in-place); delta 108→112
(inventory 411 без изменений). Секретов нет (маскированные 42, истинные
33 — без изменений). Settings 450→454 (4 поля TEMPORAL_*; ClassVar-KS
полей не добавляют). Routes +2 (переутверждение ROUTES_SHA256_F11 —
L-F11S-1, прецедент mca-19 Wave 2).

Шаги (прецедент `tools/_mca19_reissue_f8.py` +
`tools/_mca19_wave2_bump_pins.py` для routes-репина):
  1) регенерирует TSV/meta/screen-map/widget-map (`gen_param_registry_round1025`);
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`
     (counts + sha256 param_catalog.py + routes +2 + sha256 routes.py);
  3) переносит catalog-guard/Settings-счётчики в тестах
     (519→523 / 112→113 / 110→111 / delta 108→112 / 450→454 /
     ROUTES_SHA256_F11).

Запуск: `.venv\\Scripts\\python.exe tools/_mca20_reissue_f8.py`
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


# ── 1) регенерация F8 (TSV/meta/screen-map/widget-map) ─────────────────────
rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")

# ── 2) fixtures ─────────────────────────────────────────────────────────────
fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = 523
fx["counts"]["GROUPS"] = 113
fx["counts"]["TAB_BY_GROUP"] = 111
fx["counts"]["TAB_RULES"] = 22
fx["counts"]["delta"] = 112   # прирост 411 → 523 = 112 (все new, inventory 411)
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
# MCA-20: routes.py +2 endpoint'а («Аналитика») — routes-набор и hash
# переутверждаются осознанно (L-F11S-1; прецедент mca-19 Wave 2).
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
_routes = sorted(set(fx.get("routes", [])) | {
    "/factcheck/temporal/runs", "/factcheck/temporal/runs/{run_id}"})
fx["routes"] = _routes
_NOTE = (
    "; MCA-20 mca-20-temporal-factcheck (round 10.44, ADR-1028-20 D13, "
    "санкция spec §7.2/arch-frames §1.2.9): Δ каталога +4 ParamSpec/+1 "
    "GroupSpec temporal_factcheck (категория temporal, вкладка "
    "mod_factcheck IN-PLACE): temporal.default_mode (enum "
    "contextual|current|historical_truth|knowable_at_time, default "
    "contextual) / temporal.freshness_current_ttl_hours (6) / "
    "temporal.freshness_historical_ttl_hours (720) / temporal.tool_enabled "
    "(ON); GROUPS 112→113, _TAB_BY_GROUP 110→111, TAB_RULES 22 in-place; "
    "delta 108→112 (inventory 411 не менялся); REGISTRY 519→523; Settings "
    "450→454 (TEMPORAL_*; ClassVar-KS не в счёте). routes +2: "
    "GET /api/factcheck/temporal/runs, GET /api/factcheck/temporal/runs/"
    "{run_id} — ROUTES_SHA256_F11 переутверждён осознанно (L-F11S-1)."
)
if "MCA-20 mca-20-temporal-factcheck" not in fx.get("superseded_by", ""):
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

# ── 3) catalog-guard/Settings счётчики в тестах ─────────────────────────────
_REPLACEMENTS = (
    # Settings: 450 → 454 (+4 instance-поля TEMPORAL_*; ClassVar не в счёте).
    (r"fields\(Settings\)\}\) == 450", "fields(Settings)}) == 454"),
    # REGISTRY 519 → 523.
    (r"len\(pc\.REGISTRY\) == 519", "len(pc.REGISTRY) == 523"),
    (r"len\(REGISTRY\) == 519", "len(REGISTRY) == 523"),
    (r"len\(rows\) == 519", "len(rows) == 523"),
    (r"registry_keys\"\]\) == 519", "registry_keys\"]) == 523"),
    (r"len\(keys\) == 519", "len(keys) == 523"),
    (r"\[\"counts\"\]\[\"REGISTRY\"\] == 519",
     "[\"counts\"][\"REGISTRY\"] == 523"),
    # GROUPS 112 → 113 (+1: temporal_factcheck).
    (r"\[\"counts\"\]\[\"GROUPS\"\] == 112", "[\"counts\"][\"GROUPS\"] == 113"),
    (r"len\(pc\.GROUPS\) == 112", "len(pc.GROUPS) == 113"),
    (r"len\(GROUPS\) == 112", "len(GROUPS) == 113"),
    # _TAB_BY_GROUP 110 → 111 (группа temporal_factcheck на mod_factcheck).
    (r"\[\"counts\"\]\[\"TAB_BY_GROUP\"\] == 110",
     "[\"counts\"][\"TAB_BY_GROUP\"] == 111"),
    (r"\[\"counts\"\]\[\"_TAB_BY_GROUP\"\] == 110",
     "[\"counts\"][\"_TAB_BY_GROUP\"] == 111"),
    (r"len\(pc\._TAB_BY_GROUP\) == 110", "len(pc._TAB_BY_GROUP) == 111"),
    # TAB_RULES 22 — in-place, счётчики не трогаем.
    # delta 108 → 112 (все +4 — status=new; inventory 411 не менялся).
    (r"\[\"counts\"\]\[\"delta\"\] == 108", "[\"counts\"][\"delta\"] == 112"),
    (r"\"519\" in meta and \"411\" in meta and \"108\" in meta",
     "\"523\" in meta and \"411\" in meta and \"112\" in meta"),
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

# ── 4) ROUTES_SHA256_F11 (тест-константа) ───────────────────────────────────
# Прецедент mca-19 (tools/_mca19_wave2_bump_pins.py): hex-константа в
# test_round1025_f8_registry.py обновляется этим же тулом.
pin_path = ROOT / "tests/test_round1025_f8_registry.py"
new_hash = sha("web/api/routes.py")
text = pin_path.read_text(encoding="utf-8")
new = re.sub(
    r'ROUTES_SHA256_F11 = \(\s*"[0-9a-f]{64}"\s*\)',
    f'ROUTES_SHA256_F11 = (\n    "{new_hash}")',
    text, count=1)
if new == text:
    if new_hash in text and "MCA-20 (round 10.44" in text:
        print("ROUTES_SHA256_F11 already pinned:", new_hash)
    else:
        raise SystemExit("ROUTES_SHA256_F11 pin not found/updated")
else:
    marker = ("# MCA-20 (round 10.44, ADR-1028-20 D11/D13): routes +2 в "
              "СУЩЕСТВУЮЩЕМ экране «Аналитика»:\n"
              "# GET /api/factcheck/temporal/runs и GET .../runs/{run_id} "
              "(виджет «Временной фактчек»,\n"
              "# RBAC global admin — прецедент /api/random/test). Хэш "
              "переутверждён осознанно (L-F11S-1);\n"
              "# routes-набор f8_baseline переиздан "
              "(tools/_mca20_reissue_f8.py).\n")
    if "MCA-20 (round 10.44" not in new:
        new = new.replace("ROUTES_SHA256_F11 = (", marker +
                          "ROUTES_SHA256_F11 = (", 1)
    pin_path.write_text(new, encoding="utf-8")
    print("ROUTES_SHA256_F11 updated:", new_hash)
print("ROUTES_SHA256_F11 =", '"%s"' % new_hash)
