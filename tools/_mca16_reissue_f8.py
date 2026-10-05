# -*- coding: utf-8 -*-
"""Одноразовый скрипт F8-переиздания для MCA-16 (round 10.39).

Прецедент: `tools/_mca10a_reissue_f8.py`. Санкция spec §12.2 /
ADR-1028-15 D12: Δ каталога ≠ 0 — REGISTRY 502→504 (+2), GROUPS 107→108
(+1: memory_experience), `_TAB_BY_GROUP` 105→106 (+1), TAB_RULES 21
in-place (вкладка memory_rag), delta 91→93, Settings 439→441 (+2
instance-поля), secret — без изменений; routes.py не менялся →
`ROUTES_SHA256_F11` без изменений.

Делает:
  1) переиздаёт TSV/meta/screen-map генератором `gen_param_registry_round1025`;
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) синхронно бампает catalog-guard'ы в тестах (502→504/107→108/105→106/
     439→441/477→479/delta 91→93);
  4) печатает `ROUTES_SHA256_F11` (должен совпасть с пин-константой).

Запуск: `.venv\\Scripts\\python.exe tools/_mca16_reissue_f8.py`
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
    """Записать JSON, сохранив CRLF-стиль исходного файла (min diff)."""
    raw = path.read_bytes()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes((text + ("\r\n" if b"\r\n" in raw else "\n"))
                     .encode("utf-8"))


# ── 1) артефакты F8 (TSV/meta/screen-map) ───────────────────────────────────
rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")

# ── 2) fixtures ─────────────────────────────────────────────────────────────
fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = 504
fx["counts"]["GROUPS"] = 108
fx["counts"]["TAB_BY_GROUP"] = 106
fx["counts"]["delta"] = 93
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_NOTE = (
    "; MCA-16 mca-16-experience-lessons (round 10.39, ADR-1028-15 D12, "
    "санкция spec §12.2): Δ каталога +2 ParamSpec / +1 GroupSpec. "
    "memory.experience_learning_enabled + memory.experience_review_cadence "
    "(группа memory_experience, вкладка memory_rag, per-chat). REGISTRY "
    "502→504, GROUPS 107→108, _TAB_BY_GROUP 105→106, TAB_RULES 21 in-place, "
    "delta 91→93, Settings 439→441; secret — без изменений. routes.py НЕ "
    "менялся → `ROUTES_SHA256_F11` без изменений."
)
if "MCA-16 mca-16-experience-lessons" not in fx.get("superseded_by", ""):
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

# ── 3) catalog-guard'ы в тестах ─────────────────────────────────────────────
_REPLACEMENTS = (
    (r"len\(pc\.REGISTRY\) == 502", "len(pc.REGISTRY) == 504"),
    (r"len\(pc\.GROUPS\) == 107", "len(pc.GROUPS) == 108"),
    (r"len\(pc\._TAB_BY_GROUP\) == 105", "len(pc._TAB_BY_GROUP) == 106"),
    (r"len\(GROUPS\) == 107", "len(GROUPS) == 108"),
    (r"len\(REGISTRY\) == 502", "len(REGISTRY) == 504"),
    (r'BASELINE\["counts"\]\["REGISTRY"\] == 502',
     'BASELINE["counts"]["REGISTRY"] == 504'),
    (r'BASELINE\["counts"\]\["GROUPS"\] == 107',
     'BASELINE["counts"]["GROUPS"] == 108'),
    (r'BASELINE\["counts"\]\["_TAB_BY_GROUP"\] == 105',
     'BASELINE["counts"]["_TAB_BY_GROUP"] == 106'),
    (r'FIXTURE\["counts"\]\["REGISTRY"\] == 502',
     'FIXTURE["counts"]["REGISTRY"] == 504'),
    (r'FIXTURE\["counts"\]\["GROUPS"\] == 107',
     'FIXTURE["counts"]["GROUPS"] == 108'),
    (r'FIXTURE\["counts"\]\["TAB_BY_GROUP"\] == 105',
     'FIXTURE["counts"]["TAB_BY_GROUP"] == 106'),
    (r'FIXTURE\["counts"\]\["delta"\] == 91',
     'FIXTURE["counts"]["delta"] == 93'),
    (r"len\(rows\) == 502", "len(rows) == 504"),
    (r"len\(keys\) == 502", "len(keys) == 504"),
    # Settings-fields guard (dataclass-поля; +2 instance-поля MCA-16).
    (r"fields\(Settings\)\}\) == 439", "fields(Settings)}) == 441"),
    (r"fields\(Settings\)\) == 439", "fields(Settings)) == 441"),
    (r"len\(fields\) == 439", "len(fields) == 441"),
    # Прочие формы Settings-счётчика (settings.__class__ и пр.).
    (r"== 439\b", "== 441"),
    # categorized-счётчик (category is not None): +2 → 479.
    (r"== 477\b", "== 479"),
    # Счётчик по категориям: memory 38→40 (+2 MCA-16).
    (r'"memory": 38', '"memory": 40'),
    # Meta-provenance: переиздание после Δ +2 (504/93).
    (r'"502" in meta and "411" in meta and "91" in meta',
     '"504" in meta and "411" in meta and "93" in meta'),
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
print("guard-файлов обновлено:", changed)

print("ROUTES_SHA256_F11 =", '"%s"' % sha("web/api/routes.py"))
