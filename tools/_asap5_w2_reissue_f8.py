# -*- coding: utf-8 -*-
"""F8-переиздание каталога для ASAP5 W2 (§22, REQ-ADMIN-TYPES, 27.10.2026).

Δ каталога: +5 ParamSpec (flags.vision_media_*)/+1 GroupSpec
(flags_vision_media_types, вкладка mod_vision IN-PLACE): REGISTRY 582→587,
GROUPS 120→121, _TAB_BY_GROUP 118→119, TAB_RULES 23 in-place; delta
171→176 (inventory 411 не менялся). Settings 461→466 (5 instance-полей
VISION_MEDIA_*). Routes БЕЗ изменений (ROUTES_SHA256_F11 не трогается).

Шаги (прецедент `tools/_mca20_reissue_f8.py`):
  1) регенерирует TSV/meta/screen-map/widget-map (`gen_param_registry_round1025`);
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) переносит catalog-guard/Settings-счётчики в тестах
     (582→587 / 120→121 / 118→119 / delta 171→176 / 461→466 / 557→562).
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
fx["counts"]["REGISTRY"] = 587
fx["counts"]["GROUPS"] = 121
fx["counts"]["TAB_BY_GROUP"] = 119
fx["counts"]["TAB_RULES"] = 23
fx["counts"]["delta"] = 176   # прирост 411 → 587 = 176 (inventory 411)
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
_NOTE = (
    "; ASAP5 W2 image-admin (27.10.2026, REQ-ADMIN-TYPES, ТЗ ASAP 5 §22): "
    "Δ каталога +5 ParamSpec/+1 GroupSpec flags_vision_media_types "
    "(категория flags, вкладка mod_vision IN-PLACE; отдельного GIF-модуля/"
    "панели стикеров/второго Vision-раздела нет): flags.vision_media_photo_"
    "docs / flags.vision_media_static_stickers / flags.vision_media_gif_"
    "animations / flags.vision_media_animated_stickers / flags.vision_media_"
    "video_previews (default ON; главный тумблер Vision приоритетен; "
    "enqueue-гейт авто-разбора, канонический реестр не сужается); GROUPS "
    "120→121, _TAB_BY_GROUP 118→119, TAB_RULES 23 in-place; delta 171→176 "
    "(inventory 411 не менялся); REGISTRY 582→587; Settings 461→466 "
    "(VISION_MEDIA_*). routes без изменений."
)
if "ASAP5 W2 image-admin" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"])

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
    # Settings: 461 → 466 (+5 instance-поля VISION_MEDIA_*).
    (r"fields\(Settings\)\}\) == 461", "fields(Settings)}) == 466"),
    (r"assert len\(fields\) == 461", "assert len(fields) == 466"),
    (r"\n?== 461   # \+4 TEMPORAL_\* \(mca-20, ADR-1028-20 D13\); CFG-06 v2",
     "== 466   # +4 TEMPORAL_* (mca-20, ADR-1028-20 D13); CFG-06 v2"),
    # REGISTRY 582 → 587.
    (r"len\(pc\.REGISTRY\) == 582", "len(pc.REGISTRY) == 587"),
    (r"len\(REGISTRY\) == 582", "len(REGISTRY) == 587"),
    (r"len\(rows\) == 582", "len(rows) == 587"),
    (r"len\(tsv\) - 1 == 582", "len(tsv) - 1 == 587"),
    (r"registry_keys\"\]\) == 582", "registry_keys\"]) == 587"),
    (r"len\(cb\[\"registry_keys\"\]\) == 582",
     "len(cb[\"registry_keys\"]) == 587"),
    (r"\[\"counts\"\]\[\"REGISTRY\"\] == 582",
     "[\"counts\"][\"REGISTRY\"] == 587"),
    (r"BASELINE\[\"counts\"\]\[\"REGISTRY\"\] == 582",
     "BASELINE[\"counts\"][\"REGISTRY\"] == 587"),
    # GROUPS 120 → 121 (+1: flags_vision_media_types).
    (r"\[\"counts\"\]\[\"GROUPS\"\] == 120", "[\"counts\"][\"GROUPS\"] == 121"),
    (r"len\(pc\.GROUPS\) == 120", "len(pc.GROUPS) == 121"),
    (r"len\(GROUPS\) == 120", "len(GROUPS) == 121"),
    # _TAB_BY_GROUP 118 → 119 (группа на mod_vision).
    (r"\[\"counts\"\]\[\"TAB_BY_GROUP\"\] == 118",
     "[\"counts\"][\"TAB_BY_GROUP\"] == 119"),
    (r"\[\"counts\"\]\[\"_TAB_BY_GROUP\"\] == 118",
     "[\"counts\"][\"_TAB_BY_GROUP\"] == 119"),
    (r"len\(pc\._TAB_BY_GROUP\) == 118", "len(pc._TAB_BY_GROUP) == 119"),
    (r"GROUPS\)\s*== 118", "GROUPS) == 119"),
    # categorized / per-category flags count.
    (r"len\(categorized\) == 557", "len(categorized) == 562"),
    (r"len\(items\) == len\(categorized\) == 557",
     "len(items) == len(categorized) == 562"),
    (r"\"flags\": 102(?!,)", "\"flags\": 107"),
    # delta 171 → 176 (inventory 411 не менялся).
    (r"\[\"counts\"\]\[\"delta\"\] == 171", "[\"counts\"][\"delta\"] == 176"),
    (r"\"582\" in meta and \"411\" in meta and \"171\" in meta",
     "\"587\" in meta and \"411\" in meta and \"176\" in meta"),
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

# ── 4) хвост канона в тестах, пинящих [-1]/[-2]/[-3] ────────────────────────
pin = ROOT / "tests/test_mca19_block_g_round1043.py"
text = pin.read_text(encoding="utf-8")
new = text.replace(
    "assert len(tool_schemas.TOOL_CALLING_TOOLS) == 14",
    "assert len(tool_schemas.TOOL_CALLING_TOOLS) == 15")
new = new.replace(
    "    assert tool_schemas.TOOL_CALLING_TOOLS[-1] is \\\n"
    "        tool_schemas.TOOL_FACT_CHECK\n"
    "    assert tool_schemas.TOOL_CALLING_TOOLS[-2] is \\\n"
    "        tool_schemas.TOOL_RECOGNIZE_IMAGE",
    "    assert tool_schemas.TOOL_CALLING_TOOLS[-2] is \\\n"
    "        tool_schemas.TOOL_FACT_CHECK\n"
    "    assert tool_schemas.TOOL_CALLING_TOOLS[-3] is \\\n"
    "        tool_schemas.TOOL_RECOGNIZE_IMAGE\n"
    "    assert tool_schemas.TOOL_CALLING_TOOLS[-1] is \\\n"
    "        tool_schemas.TOOL_EDIT_IMAGE")
if new != text:
    pin.write_text(new, encoding="utf-8")
    print("block_g canon updated")

pin2 = ROOT / "tests/test_memory_lookup_round1026.py"
t2 = pin2.read_text(encoding="utf-8")
n2 = t2.replace(
    "assert TOOL_CALLING_TOOLS[-3] is TOOL_GET_USER_CONTEXT",
    "assert TOOL_CALLING_TOOLS[-4] is TOOL_GET_USER_CONTEXT")
if n2 != t2:
    pin2.write_text(n2, encoding="utf-8")
    print("memory_lookup tail updated")
