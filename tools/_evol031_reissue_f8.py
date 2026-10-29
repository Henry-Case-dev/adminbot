# -*- coding: utf-8 -*-
"""Одноразовый скрипт переиздания F8-фикстур для EVOL-031 (W1, 30.10.2026).

Прецедент: `tools/_fcpost_w2_reissue_f8.py`. Санкция EVOL-031 (решение
владельца, plans/current_task.md; W1-отчёт
plans/features/evol/audit/w1-evol031.md): Exact Match Cache готовых
LLM-ответов выведен из эксплуатации — ОТРИЦАТЕЛЬНАЯ Δ каталога −5 ParamSpec
(SMART_CACHE_ENABLED/SMART_CACHE_TTL_SECONDS/SMART_CACHE_MAX_ROWS/
CHAT_DEDUP_ENABLED/CHAT_DEDUP_TTL_SECONDS; pg_id flags.smart_cache_enabled,
limits.smart_cache_ttl_seconds, limits.smart_cache_max_rows,
flags.chat_dedup_enabled, limits.chat_dedup_ttl_seconds):
REGISTRY 586→581, delta 175→170, GROUPS 121→119, _TAB_BY_GROUP 119→117,
TAB_RULES 23→22 (вкладка smart_cache удалена; legacy-маршрут
#/ai/smart-cache алиасится на витрину «ИИ» — реплея нет).

Устаревшие настройки и данные обрабатываются безопасно: Settings-поля
СОХРАЕНЫ как no-op (аддитивно, legacy-тесты/старые .env не ломаются),
кодом не читаются; PG/hot-значения удалённых ключей — игнорируемые
orphans; строки таблицы smart_cache (технические маркеры MCA-22/CFG-06)
не тронуты, деструктивной миграции нет.

Шаги (запускать ПОСЛЕ emit-режима генератора):
  python tools/gen_param_registry_round1025.py      # plans/docs артефакты
  python tools/_evol031_reissue_f8.py               # fixtures + провенанс
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
fx["counts"]["REGISTRY"] = 581
fx["counts"]["GROUPS"] = 119
fx["counts"]["TAB_BY_GROUP"] = 117
fx["counts"]["TAB_RULES"] = 22
# delta = REGISTRY − inventory.tsv = 581 − 406(пересечение) = 175: 5 снятых
# ключей — исторические (Epic 51, ДО инвентаря round1014), в delta-набор
# (`status=new`) не входили → delta-множество не изменилось (175).
fx["counts"]["delta"] = 175
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["services/pg_db.py"] = sha("services/pg_db.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_EVOL031_NOTE = (
    "; EVOL-031 (30.10.2026, commit 28d55bd1, W1-отчёт "
    "plans/features/evol/audit/w1-evol031.md): санкционированная "
    "ОТРИЦАТЕЛЬНАЯ Δ каталога −5 ParamSpec Exact Match Cache / direct_dedup "
    "(flags.smart_cache_enabled, limits.smart_cache_ttl_seconds, "
    "limits.smart_cache_max_rows, flags.chat_dedup_enabled, "
    "limits.chat_dedup_ttl_seconds; replay готовых LLM-ответов удалён) → "
    "REGISTRY 586→581, delta 175 (без изменений: снятые ключи — исторические, "
    "до инвентаря round1014), GROUPS 121→119, _TAB_BY_GROUP "
    "119→117, TAB_RULES 23→22 (вкладка smart_cache удалена, legacy-маршрут "
    "#/ai/smart-cache алиасится на «ИИ»). Settings-поля СОХРАЕНЫ no-op "
    "(аддитивно), PG/hot-значения удалённых ключей — игнорируемые orphans; "
    "таблица smart_cache сохранена (технические маркеры MCA-22/CFG-06), "
    "деструктивной миграции нет.")
if "EVOL-031" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _EVOL031_NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))
cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
from services import param_catalog as pc  # noqa: E402
cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid) for gid in sorted(
    g.id for g in pc.GROUPS)}
# EVOL-031: вкладка smart_cache удалена — tab_nav пересобирается С ЖИВОГО
# каталога (иначе остался бы None-хвост удалённой вкладки).
cb["tab_nav"] = {tid: nav for tid, nav in sorted(pc.TAB_NAV.items())}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
if "EVOL-031" not in cb["_provenance"].get("note", ""):
    cb["_provenance"]["note"] = cb["_provenance"].get("note", "") + \
        _EVOL031_NOTE
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))
