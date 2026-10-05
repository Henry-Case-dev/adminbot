# -*- coding: utf-8 -*-
"""Одноразовый скрипт F8-переиздания для MCA-10b (round 10.41).

Прецеденты: `tools/_mca10a_reissue_f8.py`, `tools/_extra_reissue_f8.py`.
Санкция spec §13.2 / ADR-1028-17 D16: Δ каталога ≠ 0 — REGISTRY 504→510
(+6 PG-only bool `memory.random_uses_*` в существующей группе memory_random),
GROUPS 108 (0), `_TAB_BY_GROUP` 106 (0), TAB_RULES 21 in-place, Settings
без роста (PG-only, Settings-полей нет), secret-счётчик без изменений,
delta 93→99 (по выводу генератора, не вручную — errata-урок 10a).

Делает:
  1) переиздаёт TSV/meta/screen-map генератором `gen_param_registry_round1025`;
  2) ЧИТАЕТ производные счётчики из вывода тула (meta.md), не вручную;
  3) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  4) синхронно бампает catalog-guard'ы в тестах (504→510 / 479→485 / 93→99);
  5) печатает `ROUTES_SHA256_F11` (Δ routes = 0 — hash не меняется).

Запуск: `.venv\\Scripts\\python.exe tools/_mca10b_reissue_f8.py`
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

# ── 2) производные счётчики — из вывода тула (meta.md), не вручную ──────────
meta = (ROOT / "plans/docs/param-registry-round1025.meta.md").read_text(
    encoding="utf-8")
m_counts = re.search(
    r"REGISTRY \*\*(\d+)\*\* / GROUPS \*\*(\d+)\*\* / `_TAB_BY_GROUP` "
    r"\*\*(\d+)\*\* / TAB_RULES \*\*(\d+)\*\*", meta)
m_delta = re.search(r"Дельта 411 → (\d+) = (\d+)", meta)
if not m_counts or not m_delta:
    raise SystemExit("META PARSE FAILED — счётчики тула не распознаны")
N_REGISTRY, N_GROUPS, N_TABS, N_RULES = map(int, m_counts.groups())
N_ROWS, N_DELTA = int(m_delta.group(1)), int(m_delta.group(2))
print("counters from tool output: REGISTRY=%d GROUPS=%d TABS=%d RULES=%d "
      "rows=%d delta=%d" % (N_REGISTRY, N_GROUPS, N_TABS, N_RULES, N_ROWS,
                            N_DELTA))

# ── 3) fixtures ─────────────────────────────────────────────────────────────
fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = N_REGISTRY
fx["counts"]["GROUPS"] = N_GROUPS
fx["counts"]["TAB_BY_GROUP"] = N_TABS
fx["counts"]["delta"] = N_DELTA
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_NOTE = (
    "; MCA-10b mca-10b-random-applications (round 10.41, ADR-1028-17 D16, "
    "санкция spec §13.2): Δ каталога +6 ParamSpec / +0 GroupSpec — PG-only "
    "bool memory.random_uses_{conversation_variant, memory_recall, "
    "archive_sample, belief_review, association_pair, ui_visualization} "
    "(группа memory_random существующая, вкладка mod_sleep, per-chat; "
    "все default true при первом релизе; Settings-полей нет — рантайм читает "
    "pg-ключи через worker_settings; kill-switch MCA_RANDOM_USES_ENABLED в "
    "каталог НЕ входит, env-only). REGISTRY %d→%d, GROUPS %d (0), "
    "_TAB_BY_GROUP %d (0), TAB_RULES %d in-place, delta %d→%d, Settings "
    "441 (0); secret-счётчик без изменений. routes без изменений "
    "(Δ routes = 0); `ROUTES_SHA256_F11` не переутверждается."
    % (504, N_REGISTRY, N_GROUPS, N_TABS, N_RULES, 93, N_DELTA)
)
if "MCA-10b mca-10b-random-applications" not in fx.get("superseded_by", ""):
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

# ── 4) catalog-guard'ы в тестах (счётчики — из вывода тула) ─────────────────
_REPLACEMENTS = (
    (r"len\(pc\.REGISTRY\) == 504", "len(pc.REGISTRY) == %d" % N_REGISTRY),
    (r"len\(REGISTRY\) == 504", "len(REGISTRY) == %d" % N_REGISTRY),
    (r'BASELINE\["counts"\]\["REGISTRY"\] == 504',
     'BASELINE["counts"]["REGISTRY"] == %d' % N_REGISTRY),
    (r'FIXTURE\["counts"\]\["REGISTRY"\] == 504',
     'FIXTURE["counts"]["REGISTRY"] == %d' % N_REGISTRY),
    (r"len\(rows\) == 504", "len(rows) == %d" % N_ROWS),
    (r"len\(keys\) == 504", "len(keys) == %d" % N_ROWS),
    # per-category счётчик каталога (test_param_catalog): memory 40 → 46.
    (r'"content": 5, "memory": 40\}', '"content": 5, "memory": %d}' % 46),
    (r'FIXTURE\["counts"\]\["delta"\] == 93',
     'FIXTURE["counts"]["delta"] == %d' % N_DELTA),
    ('"504" in meta and "411" in meta and "93" in meta',
     '"%d" in meta and "411" in meta and "%d" in meta'
     % (N_REGISTRY, N_DELTA)),
    # categorized-счётчик (category is not None): +6 PG-only memory → 485.
    (r"== 479\b", "== %d" % (479 + 6)),
)
changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8")
    new = text
    for pat, repl in _REPLACEMENTS:
        new = re.sub(pat, repl, new)
    if new != text:
        # Сохранить исходный стиль переводов строк (LF/CRLF) — min diff.
        out = new.replace("\r\n", "\n").encode("utf-8")
        if crlf:
            out = out.replace(b"\n", b"\r\n")
        path.write_bytes(out)
        changed += 1
print("guard-файлов обновлено:", changed)

# ── 5) Δ routes = 0: hash не меняется (переутверждение не требуется) ────────
print("ROUTES_SHA256_F11 =", '"%s"' % sha("web/api/routes.py"))
