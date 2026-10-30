# -*- coding: utf-8 -*-
"""Одноразовый скрипт переиздания F8-фикстур для EVOL §5 W5 review-fix
(B1/B2, 31.10.2026).

Прецедент: `tools/_evol031_reissue_f8.py`, `tools/_fcpost_w2_reissue_f8.py`.
Санкция: review-fix B1 — ручки владельца (тумблер раздела «Критический
разнос» и редактор его директивы) ОБЯЗАНЫ быть в каталоге, иначе
POST /api/config отдаёт 422 «неизвестный ключ», а вкладка «Фактчек»
рендерится только из каталога и показать их не может.

Положительная Δ каталога (+2 ParamSpec / +1 GroupSpec):
  * `flags.factcheck_critique_section_enabled` — per-chat PG-only bool,
    группа flags_factcheck_delivery, вкладка mod_factcheck, default ON
    внутри уже включённого фактчека (НЕ мастер модуля);
  * `prompts.factcheck_critique_directive` — PG-ключ реестрового блока
    `factcheck.critique.directive`, группа prompts_factcheck;
  * +1 GroupSpec `flags_factcheck_delivery`; TAB_RULES 22 — in-place.

Числа: REGISTRY 581→583, categorized 556→558, GROUPS 119→120,
_TAB_BY_GROUP 117→118, TAB_RULES 22 (без роста), delta 175→177,
TSV 581→583 строк. Settings-поля без изменений (PG-only ключи),
secret/hidden без изменений, DDL = 0, routes = 0.

Шаги (запускать ПОСЛЕ emit-режима генератора):
  python tools/gen_param_registry_round1025.py      # plans/docs артефакты
  python tools/_evol_w5_reissue_f8.py               # fixtures + провенанс
  python tools/gen_param_registry_round1025.py --check
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def _write_json_crlf(path: Path, data: dict) -> None:
    """Записать JSON, сохранив CRLF-стиль исходного файла (min diff)."""
    raw = path.read_bytes()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes((text + ("\r\n" if b"\r\n" in raw else "\n")).encode("utf-8"))


fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = 583
fx["counts"]["GROUPS"] = 120
fx["counts"]["TAB_BY_GROUP"] = 118
fx["counts"]["TAB_RULES"] = 22
# delta = REGISTRY − inventory-пересечение = 583 − 406 = 177 (было 175).
fx["counts"]["delta"] = 177
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["services/pg_db.py"] = sha("services/pg_db.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_W5_NOTE = (
    "; EVOL §5 W5 review-fix B1/B2 (31.10.2026, кандидат d036707a+): "
    "санкционированная положительная Δ каталога +2 ParamSpec / +1 GroupSpec — "
    "flags.factcheck_critique_section_enabled (per-chat PG-only bool, группа "
    "flags_factcheck_delivery, вкладка mod_factcheck, default ON внутри "
    "включённого фактчека; мастер модуля flags.factcheck_enabled не "
    "дублируется) и prompts.factcheck_critique_directive (PG-ключ блока "
    "реестра factcheck.critique.directive, группа prompts_factcheck) → "
    "REGISTRY 581→583, categorized 556→558, GROUPS 119→120, _TAB_BY_GROUP "
    "117→118, TAB_RULES 22 in-place, delta 175→177, TSV 581→583. "
    "Settings-поля/secret/hidden/DDL/routes без изменений.")
if "review-fix B1/B2" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _W5_NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))

cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
from services import param_catalog as pc  # noqa: E402
cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid) for gid in sorted(
    g.id for g in pc.GROUPS)}
cb["tab_nav"] = {tid: nav for tid, nav in sorted(pc.TAB_NAV.items())}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
if "review-fix B1/B2" not in cb["_provenance"].get("note", ""):
    cb["_provenance"]["note"] = cb["_provenance"].get("note", "") + _W5_NOTE
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))
