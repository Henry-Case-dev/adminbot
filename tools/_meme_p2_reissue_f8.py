# -*- coding: utf-8 -*-
"""F8-переиздание каталога для MEME-PIPELINE-REFactor-01 P2 (03.11.2026).

Δ каталога: +2 PG-only ParamSpec категории `prompts` +1 GroupSpec
(`prompts_initiative_meme`, вкладка `prompts` — catch-all `(CATEGORY_PROMPTS,
None)`, IN-PLACE): REGISTRY 595→597, GROUPS 120→121, _TAB_BY_GROUP 118→119,
TAB_RULES 22 in-place; delta 189→191 (inventory 411 не менялся).
Settings-полей нет (PG-only ключи), DDL = 0, новых routes нет
(ROUTES-набор не меняется, но sha256 файла — да: правка существующих
эндпоинтов).

Ключи:
  * `prompts.meme_joke`  — редактируемый промпт этапа B («прикол»);
  * `prompts.meme_image` — редактируемый шаблон промпта картинки (этап C),
    который до этой полосы был объявлен код-каноном без `pg_key`
    (`ui="catalog_pending"`) и потому фактически не редактировался.

Шаги (прецедент `tools/_evol_w5_reissue_f8.py`):
  1) регенерирует TSV/meta/screen-map/widget-map (`gen_param_registry_round1025`);
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) переносит catalog-guard-счётчики и хэши в тестах.
Запуск:
  python tools/_meme_p2_reissue_f8.py
  python tools/gen_param_registry_round1025.py --check
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
fx["counts"]["REGISTRY"] = 597
fx["counts"]["GROUPS"] = 121
fx["counts"]["TAB_BY_GROUP"] = 119
fx["counts"]["_TAB_BY_GROUP"] = 119
fx["counts"]["TAB_RULES"] = 22
fx["counts"]["delta"] = 191      # 597 - 406 (inventory 411, delta-набор 406)
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["services/pg_db.py"] = sha("services/pg_db.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_NOTE = (
    "; MEME-PIPELINE-REFactor-01 P2 (03.11.2026): Δ каталога +2 PG-only "
    "ParamSpec категории prompts (prompts.meme_joke — промпт этапа B "
    "«прикол»; prompts.meme_image — шаблон промпта картинки, до полосы "
    "объявлен код-каноном без pg_key и потому не редактировался) и "
    "+1 GroupSpec prompts_initiative_meme (вкладка prompts, IN-PLACE): "
    "REGISTRY 595→597, GROUPS 120→121, _TAB_BY_GROUP 118→119, TAB_RULES 22 "
    "in-place, delta 189→191. Settings/DDL = 0, новых routes нет. "
    "web/api/routes.py: витрина мемов считает L/T/J через resolve_meme_budget "
    "от эффективного шаблона + валидация `{joke}` на всех путях записи.")
if "MEME-PIPELINE-REFactor-01 P2" not in fx.get("superseded_by", ""):
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

# ── 3) catalog-guard/хэши в тестах ─────────────────────────────────────────
_REPLACEMENTS = (
    # REGISTRY 595 → 597 (+2 промпт-ключа мемов).
    (r"len\(pc\.REGISTRY\) == 595", "len(pc.REGISTRY) == 597"),
    (r"len\(REGISTRY\) == 595", "len(REGISTRY) == 597"),
    (r"len\(rows\) == 595", "len(rows) == 597"),
    (r"len\(keys\) == 595", "len(keys) == 597"),
    (r"len\(tsv\) - 1 == 595", "len(tsv) - 1 == 597"),
    (r"len\(cb\[\"registry_keys\"\]\) == 595",
     "len(cb[\"registry_keys\"]) == 597"),
    (r"\[\"counts\"\]\[\"REGISTRY\"\] == 595",
     "[\"counts\"][\"REGISTRY\"] == 597"),
    (r"\"595\" in res\.stdout", "\"597\" in res.stdout"),
    # GROUPS 120 → 121 (+1: prompts_initiative_meme).
    (r"len\(pc\.GROUPS\) == 120", "len(pc.GROUPS) == 121"),
    (r"len\(GROUPS\) == 120", "len(GROUPS) == 121"),
    (r"\[\"counts\"\]\[\"GROUPS\"\] == 120", "[\"counts\"][\"GROUPS\"] == 121"),
    # _TAB_BY_GROUP 118 → 119 (группа на вкладке prompts).
    (r"len\(pc\._TAB_BY_GROUP\) == 118", "len(pc._TAB_BY_GROUP) == 119"),
    (r"\[\"counts\"\]\[\"TAB_BY_GROUP\"\] == 118",
     "[\"counts\"][\"TAB_BY_GROUP\"] == 119"),
    (r"\[\"counts\"\]\[\"_TAB_BY_GROUP\"\] == 118",
     "[\"counts\"][\"_TAB_BY_GROUP\"] == 119"),
    # delta 189 → 191.
    (r"\[\"counts\"\]\[\"delta\"\] == 189", "[\"counts\"][\"delta\"] == 191"),
    (r"\"595\" in meta and \"411\" in meta and \"189\" in meta",
     "\"597\" in meta and \"411\" in meta and \"191\" in meta"),
    # TSV-строки (+header) и categorized-набор: 596→598, 570→572.
    (r"len\(tsv\) == 596", "len(tsv) == 598"),
    (r"len\(categorized\) == 570", "len(categorized) == 572"),
    (r"len\(items\) == len\(categorized\) == 570",
     "len(items) == len(categorized) == 572"),
    # prompts-набор категории: 26→28.
    (r"assert len\(prompts\) == 26", "assert len(prompts) == 28"),
    (r"\{\"prompts\": 26, \"models\"", "{\"prompts\": 28, \"models\""),
)
changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    text = path.read_text(encoding="utf-8")
    new = text
    for pat, repl in _REPLACEMENTS:
        new = re.sub(pat, repl, new)
    if new != text:
        # newline="\n": файлы репозитория хранятся с LF; без этого Windows
        # text-mode переписал бы весь файл в CRLF (дифф на весь файл).
        path.write_text(new, encoding="utf-8", newline="\n")
        changed += 1
print("guard-файлы обновлены:", changed)

# ── 4) byte-freeze хэши: param_catalog.py и web/api/routes.py ──────────────
_PIN_FILE = ROOT / "tests/test_round1025_f8_registry.py"
pin = _PIN_FILE.read_text(encoding="utf-8")
new_pin = re.sub(
    r'(PARAM_CATALOG_SHA256_FOLLOWUP = \(\r?\n?\s*")[0-9a-f]{64}(")',
    r"\g<1>" + sha("services/param_catalog.py") + r"\g<2>", pin)
new_pin = re.sub(
    r'(ROUTES_SHA256_F11 = \(\r?\n?(?:\s*#[^\n]*\r?\n)*\s*")[0-9a-f]{64}(")',
    r"\g<1>" + sha("web/api/routes.py") + r"\g<2>", new_pin)
if new_pin != pin:
    _PIN_FILE.write_text(new_pin, encoding="utf-8", newline="\n")
    print("hash-пины обновлены (param_catalog, routes)")
# Проверка (а не «должно было измениться»): пины обязаны совпасть с файлами.
_pin_now = _PIN_FILE.read_text(encoding="utf-8")
for const, rel in (("PARAM_CATALOG_SHA256_FOLLOWUP",
                    "services/param_catalog.py"),
                   ("ROUTES_SHA256_F11", "web/api/routes.py")):
    block = _pin_now.split(const, 1)[1]
    digest = re.search(r"([0-9a-f]{64})", block)
    if digest is None or digest.group(1) != sha(rel):
        raise SystemExit(f"PIN MISMATCH: {const} != sha256({rel})")
print("hash-пины совпадают с файлами")

# ── 5) двойная проверка эмита ──────────────────────────────────────────────
if gen.run_check() != 0:
    raise SystemExit("CHECK FAILED")
print("OK: F8 переиздан и проверен")
