# -*- coding: utf-8 -*-
"""F8-переиздание каталога для MCA-19 (round 10.43).

Санкция: spec §8.2 / ADR-1028-19 D13 / arch-frames §1.2.8 — Δ каталога
+9 (REGISTRY 510→519) + 4 группы (GROUPS 108→112) + вкладка mod_vision
(TAB_RULES 21→22, _TAB_BY_GROUP 106→110, TAB_NAV/CONFIG_TAB_TITLES 21→22);
delta 99→108 (inventory 411 без изменений). Секрет +1: keys.vision_api_key
(маскированные строки 41→42; истинные secret 32→33).

Шаги (прецедент `tools/_mca18_reissue_f8.py`):
  1) регенерирует TSV/meta/screen-map/widget-map (`gen_param_registry_round1025`);
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) переносит catalog-guard счётчики в тестах (510→519 / 108→112 / 106→110 /
     21→22 / delta 99→108 / секрет-счётчики);
  4) печатает текущий sha256 `web/api/routes.py` (routes НЕ меняются Wave 1 —
     проверка, что byte-freeze не задет).

Запуск: `.venv\\Scripts\\python.exe tools/_mca19_reissue_f8.py`
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
fx["counts"]["REGISTRY"] = 519
fx["counts"]["GROUPS"] = 112
fx["counts"]["TAB_BY_GROUP"] = 110
fx["counts"]["TAB_RULES"] = 22
fx["counts"]["delta"] = 108   # прирост 411 → 519 = 108 (все new, inventory 411)
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
# routes.py Wave 1 не меняется (новых endpoint'ов нет) — routes-список и
# ROUTES_SHA256_F11 остаются; фактический хеш печатается в конце для сверки.
_NOTE = (
    "; MCA-19 mca-19-image-understanding (round 10.43, ADR-1028-19 D13, "
    "санкция spec §8.2/arch-frames §1.2.8): Δ каталога +9 ParamSpec — "
    "flags_module_vision (flags.vision_enabled, тумблер владельца) / "
    "models_vision (vision_api_base_url, vision_api_type, vision_model) / "
    "keys_vision (vision_api_key — секрет, маска) / limits_vision "
    "(image_max_dimension, queue_capacity, user_rate, chat_rate); GROUPS "
    "108→112 (+4), вкладка mod_vision — TAB_RULES 21→22, _TAB_BY_GROUP "
    "106→110, TAB_NAV/CONFIG_TAB_TITLES 21→22; delta 99→108 (inventory 411 "
    "не менялся); REGISTRY 510→519. routes.py — без изменений (Wave 1), "
    "ROUTES_SHA256_F11 не переутверждался."
)
if "MCA-19 mca-19-image-understanding" not in fx.get("superseded_by", ""):
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

# ── 3) catalog-guard счётчики в тестах ──────────────────────────────────────
_REPLACEMENTS = (
    # REGISTRY-счётчики (было/стало): 510 → 519.
    (r"len\(pc\.REGISTRY\) == 510", "len(pc.REGISTRY) == 519"),
    (r"len\(REGISTRY\) == 510", "len(REGISTRY) == 519"),
    (r"len\(rows\) == 510", "len(rows) == 519"),
    (r"registry_keys\"\]\) == 510", "registry_keys\"]) == 519"),
    (r"len\(keys\) == 510", "len(keys) == 519"),
    (r"\"510\" in res\.stdout", "\"519\" in res.stdout"),
    (r"\[\"counts\"\]\[\"REGISTRY\"\] == 510",
     "[\"counts\"][\"REGISTRY\"] == 519"),
    # GROUPS 108 → 112 (+4: flags_module_vision/models_vision/keys_vision/
    # limits_vision).
    (r"\[\"counts\"\]\[\"GROUPS\"\] == 108", "[\"counts\"][\"GROUPS\"] == 112"),
    (r"len\(pc\.GROUPS\) == 108", "len(pc.GROUPS) == 112"),
    (r"len\(GROUPS\) == 108", "len(GROUPS) == 112"),
    # _TAB_BY_GROUP 106 → 110 (mod_vision + 3 группы в llm_providers).
    (r"\[\"counts\"\]\[\"TAB_BY_GROUP\"\] == 106",
     "[\"counts\"][\"TAB_BY_GROUP\"] == 110"),
    (r"\[\"counts\"\]\[\"_TAB_BY_GROUP\"\] == 106",
     "[\"counts\"][\"_TAB_BY_GROUP\"] == 110"),
    (r"len\(pc\._TAB_BY_GROUP\) == 106", "len(pc._TAB_BY_GROUP) == 110"),
    # TAB_RULES 21 → 22 (вкладка mod_vision; осознанная эволюция — прецедент
    # 19→20→21, ADR-1028-19 D16: «в существующем списке модулей»).
    (r"\[\"counts\"\]\[\"TAB_RULES\"\] == 21", "[\"counts\"][\"TAB_RULES\"] == 22"),
    (r"len\(pc\.TAB_RULES\) == 21", "len(pc.TAB_RULES) == 22"),
    (r"len\(ALL_TABS\) == 21", "len(ALL_TABS) == 22"),
    (r"len\(pc\.TAB_NAV\) == 21", "len(pc.TAB_NAV) == 22"),
    (r"len\(pc\.CONFIG_TAB_TITLES\) == 21", "len(pc.CONFIG_TAB_TITLES) == 22"),
    # delta 99 → 108 (все +9 — status=new; inventory 411 не менялся).
    (r"\[\"counts\"\]\[\"delta\"\] == 99", "[\"counts\"][\"delta\"] == 108"),
    (r"\"510\" in meta and \"411\" in meta and \"99\" in meta",
     "\"519\" in meta and \"411\" in meta and \"108\" in meta"),
    # Секреты: +1 keys.vision_api_key → маскированные строки 41→42 (F8,
    # категория keys), истинные secret 32→33.
    (r"len\(secret_rows\) == 41", "len(secret_rows) == 42"),
    (r"len\(secrets\) == 32", "len(secrets) == 33"),
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

print("ROUTES_SHA256_F11 =", '"%s"' % sha("web/api/routes.py"))
