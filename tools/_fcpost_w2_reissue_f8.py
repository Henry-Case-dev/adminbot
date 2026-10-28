# -*- coding: utf-8 -*-
"""Одноразовый скрипт переиздания F8-фикстур для FCPOST-W2 (round 10.48).

Прецедент: `tools/_extra_reissue_f8.py`. Санкция P0-FACTCHECK §6.3
(FC-06C, решение владельца 28.10.2026): кеш готовых Fact-check вердиктов
удалён (W1) — ОТРИЦАТЕЛЬНАЯ Δ каталога −2 мёртвых TTL-ключа
TEMPORAL_FRESHNESS_{CURRENT,HISTORICAL}_TTL_HOURS (pg_id temporal.freshness_*):
REGISTRY 587→586 (фактический каталог дерева; см. W1 incidental #1),
delta 176→175, GROUPS/_TAB_BY_GROUP/TAB_RULES без роста.

Устаревшие настройки и данные обрабатываются безопасно при обновлении
(§6.3): строка bot_settings не удаляется, читателей нет, startup не
валидирует каталог против БД; /api/config больше не отдаёт ключи
(`config_cache._REMOVED_SETTING_KEYS`), POST отвергает их (422).

Шаги (запускать ПОСЛЕ emit-режима генератора):
  python tools/gen_param_registry_round1025.py      # plans/docs артефакты
  python tools/_fcpost_w2_reissue_f8.py             # fixtures + провенанс
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
fx["counts"]["REGISTRY"] = 586
fx["counts"]["delta"] = 175
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["services/pg_db.py"] = sha("services/pg_db.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_FCPOST_NOTE = (
    "; P0-FACTCHECK post-release W2 (FC-06C §6.3, решение владельца "
    "28.10.2026): санкционированная ОТРИЦАТЕЛЬНАЯ Δ каталога −2 ParamSpec "
    "TEMPORAL_FRESHNESS_{CURRENT,HISTORICAL}_TTL_HOURS (pg_id "
    "temporal.freshness_*, кеш готовых Fact-check вердиктов удалён W1) → "
    "REGISTRY 587→586, delta 176→175; GROUPS/_TAB_BY_GROUP/TAB_RULES без "
    "роста; Settings-поля удалены вместе с гейтом "
    "MCA_TEMPORAL_FACTCHECK_CACHE_ENABLED (env-only, читателей нет). "
    "Старые БД-значения temporal.freshness_* игнорируются безопасно "
    "(config_cache._REMOVED_SETTING_KEYS: чтения нет, строка БД не "
    "трогается, startup каталог против БД не валидирует, POST /api/config "
    "— 422 «неизвестный ключ»). Фактический счётчик дерева (см. W1 "
    "incidental #1: пины 587 отставали от каталога 588).")
if "FC-06C §6.3" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _FCPOST_NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))
cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
from services import param_catalog as pc  # noqa: E402
cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid) for gid in sorted(
    g.id for g in pc.GROUPS)}
cb["tab_nav"] = {tid: pc.tab_nav(tid) for tid in sorted(cb["tab_nav"])}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
if "FC-06C §6.3" not in cb["_provenance"].get("note", ""):
    cb["_provenance"]["note"] = cb["_provenance"].get("note", "") + \
        _FCPOST_NOTE
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))
