# -*- coding: utf-8 -*-
"""Одноразовый скрипт переиздания F8-фикстур для EXTRA (round1028).

Прецедент: `tools/_asap31_reissue_f8.py`. Санкция spec §13 / ADR-1028-4 D11:
Δ каталога +4 → REGISTRY 484→488, Settings 424→427, categorized 459→463,
GROUPS/_TAB_BY_GROUP/TAB_RULES без роста, delta 73→77.
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
fx["counts"]["REGISTRY"] = 488
fx["counts"]["delta"] = 77
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["services/pg_db.py"] = sha("services/pg_db.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_EXTRA_NOTE = (
    "; EXTRA extra-cover-style-pipeline (round1028, ADR-1028-4 D1/D11, "
    "санкция spec §13): Δ каталога +4 ParamSpec "
    "(models.image_style_base_url, models.image_style_model, "
    "keys.image_style_api_key, prompts.summary_cover_style_id) → REGISTRY "
    "484→488, Settings 424→427, categorized 459→463; GROUPS/_TAB_BY_GROUP/"
    "TAB_RULES без роста (105/103/21); delta 73→77. PG Δ DDL ≠ 0 (5 таблиц "
    "cover_style_*), SQLite Δ DDL = 0.")
if "EXTRA extra-cover-style-pipeline" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _EXTRA_NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))
cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
from services import param_catalog as pc  # noqa: E402
cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid) for gid in sorted(pc.GROUPS and
                                                            [g.id for g in pc.GROUPS])}
cb["tab_nav"] = {tid: pc.tab_nav(tid) for tid in sorted(cb["tab_nav"])}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))
print("ROUTES_SHA256_F11 =", '"%s"' % sha("web/api/routes.py"))
