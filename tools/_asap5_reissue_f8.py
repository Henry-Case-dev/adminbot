# -*- coding: utf-8 -*-
"""Переиздание F8-артефактов для ASAP 5 (asap5-final-fixes, T-5256).

Методика: `tools/_mca18_reissue_f8.py`. Санкция ADR-1028-25 §5 / T-5239:
Δ каталога = +6 ParamSpec — PG-only профили embeddings
`models.embedding_fallback{1,2}_{base_url,model,quota_group}` (группа
models_embeddings). REGISTRY 523→529; GROUPS 113 (0); `_TAB_BY_GROUP` 111
(0); TAB_RULES 22 in-place; delta 112→118 (6 новых строк inventory vs
baseline 10.14, status=new); Settings без изменений (PG-only, прецедент
_SUMMARY_HYBRID_PG_ONLY); secret — нет; routes.py не менялся —
`ROUTES_SHA256_F11` не переутверждается (byte-freeze цел).

Шаги:
  1) переиздание TSV/meta/screen-map генератором `gen_param_registry_round1025`;
  2) обновление `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) синхронизация канон-пинов каталога в тестах (523→529 / 112→118).

Запуск: `.venv\\Scripts\\python.exe tools/_asap5_reissue_f8.py`
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
    """Аккуратный JSON с сохранением CRLF-стиля исходного файла (min diff)."""
    raw = path.read_bytes()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes((text + ("\r\n" if b"\r\n" in raw else "\n"))
                     .encode("utf-8"))


# Шаг 1) артефакты F8 (TSV/meta/screen-map) -------------------------------
rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")

# Шаг 2) fixtures ----------------------------------------------------------
fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = 529
fx["counts"]["delta"] = 118
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_NOTE = (
    "; ASAP-5 asap5-final-fixes (ADR-1028-25 §5, T-5256): Δ каталога +6 "
    "ParamSpec — PG-only профили embeddings models.embedding_fallback{1,2}_"
    "{base_url,model,quota_group} (группа models_embeddings). REGISTRY "
    "523→529, GROUPS 113 (0), _TAB_BY_GROUP 111 (0), TAB_RULES 22 in-place, "
    "delta 112→118; Settings без изменений (PG-only, прецедент "
    "_SUMMARY_HYBRID_PG_ONLY); secret — нет. routes.py не менялся — "
    "ROUTES_SHA256_F11 не переутверждается."
)
if "ASAP-5 asap5-final-fixes" not in fx.get("superseded_by", ""):
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
cb["tab_nav"] = {tid: pc.tab_nav(tid) for tid in sorted(cb["tab_nav"])}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))

# Шаг 3) канон-пины каталога в тестах (523→529 / 112→118) ------------------
_REPLACEMENTS = (
    (r"len\(pc\.REGISTRY\) == 523", "len(pc.REGISTRY) == 529"),
    (r"len\(REGISTRY\) == 523", "len(REGISTRY) == 529"),
    (r'REGISTRY"\] == 523', 'REGISTRY"] == 529'),
    (r"len\(rows\) == 523", "len(rows) == 529"),
    (r'registry_keys"\]\) == 523', 'registry_keys"]) == 529'),
    (r"len\(keys\) == 523", "len(keys) == 529"),
    (r'"523" in meta', '"529" in meta'),
    (r'FIXTURE\["counts"\]\["delta"\] == 112',
     'FIXTURE["counts"]["delta"] == 118'),
    (r"FIXTURE\[\"counts\"\]\[\"delta\"\] == 112",
     'FIXTURE["counts"]["delta"] == 118'),
)
changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    text = path.read_text(encoding="utf-8")
    new = text
    for pat, repl in _REPLACEMENTS:
        new = re.sub(pat, repl, new)
    if new != text:
        path.write_text(new, encoding="utf-8", newline="")
        changed += 1
print("test pins synced in %d files" % changed)
