# -*- coding: utf-8 -*-
"""Одноразовый скрипт F8-переиздания для MCA-10a (round 10.37).

Прецеденты: `tools/_extra_reissue_f8.py`, `tools/_asap31_reissue_f8.py`.
Санкция spec §13.2 / ADR-1028-14 D12: Δ каталога ≠ 0 — REGISTRY 489→502
(+13), GROUPS 105→107 (+2: memory_random/keys_random), `_TAB_BY_GROUP`
103→105 (+2), TAB_RULES 21 in-place, delta 78→91, Settings 426→439 (+13),
secret-строки в артефактах 32→41 (см. evidence: семантика
`_is_secret = secret or category==keys`; санкционные «32→33» считают только
истинный секрет api_key — фактическая цифра артефакта объяснена).

Делает:
  1) переиздаёт TSV/meta/screen-map генератором `gen_param_registry_round1025`;
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) синхронно бампает catalog-guard'ы в тестах (489→502/105→107/103→105);
  4) печатает `ROUTES_SHA256_F11` (переутверждение L-F11S-1).

Запуск: `.venv\\Scripts\\python.exe tools/_mca10a_reissue_f8.py`
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
fx["counts"]["REGISTRY"] = 502
fx["counts"]["GROUPS"] = 107
fx["counts"]["TAB_BY_GROUP"] = 105
fx["counts"]["delta"] = 91
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_NOTE = (
    "; MCA-10a mca-10a-random-source-anu (round 10.37, ADR-1028-14 D8/D12, "
    "санкция spec §13.2): Δ каталога +13 ParamSpec / +2 GroupSpec. "
    "memory.random_source, memory.random_fallback_to_pseudorandom, "
    "memory.random_exploration_probability, "
    "memory.random_sleep_exploration_probability (группа memory_random, "
    "вкладка mod_sleep, per-chat) + keys.random_quantum_provider/endpoint/"
    "api_key(secret)/plan/batch_length/data_type/request_timeout_seconds/"
    "refill_low_watermark/buffer_max_values (группа keys_random, вкладка "
    "llm_providers). REGISTRY 489→502, GROUPS 105→107, _TAB_BY_GROUP "
    "103→105, TAB_RULES 21 in-place, delta 78→91, Settings 426→439; "
    "secret-строки артефакта 32→41 (belt-and-suspenders `category==keys` "
    "считает все 9 keys-полей; истинный `secret=True` — только api_key). "
    "routes +1: POST /api/random/test; `ROUTES_SHA256_F11` переутверждён "
    "осознанно (L-F11S-1)."
)
if "MCA-10a mca-10a-random-source-anu" not in fx.get("superseded_by", ""):
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
    (r"len\(pc\.REGISTRY\) == 489", "len(pc.REGISTRY) == 502"),
    (r"len\(pc\.GROUPS\) == 105", "len(pc.GROUPS) == 107"),
    (r"len\(pc\._TAB_BY_GROUP\) == 103", "len(pc._TAB_BY_GROUP) == 105"),
    (r"len\(GROUPS\) == 105", "len(GROUPS) == 107"),
    (r"len\(REGISTRY\) == 488", "len(REGISTRY) == 502"),
    (r'BASELINE\["counts"\]\["REGISTRY"\] == 489',
     'BASELINE["counts"]["REGISTRY"] == 502'),
    (r'BASELINE\["counts"\]\["GROUPS"\] == 105',
     'BASELINE["counts"]["GROUPS"] == 107'),
    (r'BASELINE\["counts"\]\["_TAB_BY_GROUP"\] == 103',
     'BASELINE["counts"]["_TAB_BY_GROUP"] == 105'),
    # Settings-fields guard (dataclass-поля; +13 instance-полей MCA-10a).
    (r"fields\(Settings\)\}\) == 426", "fields(Settings)}) == 439"),
    # categorized-счётчик (category is not None): +13 → 477.
    (r"== 464\b", "== 477"),
    # Settings-fields guard (форма `settings.__class__`/`fields(Settings)`).
    (r"== 426\b", "== 439"),
    # Истинные секреты каталога (`ParamSpec.secret=True`): +1 (api_key) → 32.
    (r"pc_secret_names\(\)\) == 31", "pc_secret_names()) == 32"),
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
