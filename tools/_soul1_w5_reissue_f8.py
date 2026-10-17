# -*- coding: utf-8 -*-
"""F8-переиздание каталога для SOUL-1 W5 (инициатива: диагностика/мягкие цели).

Санкция: task §19 SOUL-18.4 (owner-controlled мягкие цели наблюдения и
активности) — Δ каталога **+3 ParamSpec** в СУЩЕСТВУЮЩИЕ группы
`limits_intent` (2) и `flags_intent` (1): `initiative.soft_target_replies_
per_day`, `initiative.observation_target_interval_seconds`,
`flags.initiative_diagnostics_publish_enabled`. GROUPS/_TAB_BY_GROUP/
TAB_RULES/Settings/routes — без изменений; delta 161 → 164; REGISTRY 572 →
575. Прецедент процедуры — `tools/_mca20_reissue_f8.py` (+ bulk re-pin
`d9b7f389`).

Шаги:
  1) регенерирует TSV/meta/screen-map (`gen_param_registry_round1025`);
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`
     (counts + sha256 param_catalog.py + provenance note);
  3) переносит catalog-guard счётчики в тестах и их fixtures
     (REGISTRY 572→575, delta 161→164).

Запуск: `py -3 tools/_soul1_w5_reissue_f8.py`
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


def _write_json_like(path: Path, data: dict) -> None:
    """Записать JSON, сохранив CRLF-конвенции исходного файла (min diff)."""
    raw = path.read_bytes()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes((text + ("\r\n" if b"\r\n" in raw else "\n"))
                     .encode("utf-8"))


NEW_REGISTRY = 575
NEW_DELTA = 164

# ── 1) регенерация F8-артефактов ───────────────────────────────────────────
rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")

# ── 2) fixtures ────────────────────────────────────────────────────────────
from services import param_catalog as pc  # noqa: E402

fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = NEW_REGISTRY
fx["counts"]["GROUPS"] = len(pc.GROUPS)
fx["counts"]["TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["TAB_RULES"] = len(pc.TAB_RULES)
fx["counts"]["delta"] = NEW_DELTA
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
_note = (
    "; SOUL-1 W5 initiative-diag (17.10.2026, санкция task §19 SOUL-18.4): "
    "Δ каталога +3 ParamSpec в СУЩЕСТВУЮЩИЕ группы limits_intent (2) и "
    "flags_intent (1) — initiative.soft_target_replies_per_day, "
    "initiative.observation_target_interval_seconds, "
    "flags.initiative_diagnostics_publish_enabled (все default OFF/0 → "
    "поведенческий паритет); REGISTRY 572→575; delta 161→164 (inventory 411 "
    "без изменений); GROUPS/_TAB_BY_GROUP/TAB_RULES/Settings/routes — "
    "in-place (без новых endpoint'ов)."
)
if "SOUL-1 W5 initiative-diag" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _note
_write_json_like(fx_path, fx)
print("f8_baseline:", fx["counts"])

cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid)
                   for gid in sorted(g.id for g in pc.GROUPS)}
cb["tab_nav"] = {tid: pc.tab_nav(tid)
                 for tid in sorted(set(cb["tab_nav"]) | set(pc.TAB_NAV))}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
_write_json_like(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))

# ── 3) перенос счётчиков в тестах и их fixtures ────────────────────────────
_REPLACEMENTS = (
    (re.compile(r"len\(pc\.REGISTRY\) == 572\b"),
     "len(pc.REGISTRY) == %d" % NEW_REGISTRY),
    (re.compile(r"len\(REGISTRY\) == 572\b"),
     "len(REGISTRY) == %d" % NEW_REGISTRY),
    (re.compile(r'\["counts"\]\["REGISTRY"\] == 572\b'),
     '["counts"]["REGISTRY"] == %d' % NEW_REGISTRY),
    (re.compile(r"len\(cb\[\"registry_keys\"\]\) == 572\b"),
     "len(cb[\"registry_keys\"]) == %d" % NEW_REGISTRY),
    (re.compile(r"len\(keys\) == 572\b"),
     "len(keys) == %d" % NEW_REGISTRY),
    (re.compile(r"len\(rows\) == 572\b"),
     "len(rows) == %d" % NEW_REGISTRY),
    (re.compile(r'\["counts"\]\["delta"\] == 161\b'),
     '["counts"]["delta"] == %d' % NEW_DELTA),
    (re.compile(r'len\(delta\) == FIXTURE\["counts"\]\["delta"\] == 161\b'),
     'len(delta) == FIXTURE["counts"]["delta"] == %d' % NEW_DELTA),
    # categorized-срез (specs с category): 547 → 550 (+3 PG-only).
    (re.compile(r"len\(categorized\) == 547\b"),
     "len(categorized) == 550"),
    (re.compile(r"len\(items\) == len\(categorized\) == 547\b"),
     "len(items) == len(categorized) == 550"),
    (re.compile(r'\["counts"\]\["categorized"\] == 547\b'),
     '["counts"]["categorized"] == 550'),
    (re.compile(r'"categorized": 547\b'), '"categorized": 550'),
    # Многострочная форма среза «specs с category» (перенос строки перед
    # `if s.category is not None]) == 547`).
    (re.compile(r"if s\.category is not None\]\) == 547\b"),
     "if s.category is not None]) == 550"),
    # F8 TSV с заголовком: 573 (572+1) → 576 (575+1).
    (re.compile(r"len\(tsv\) == 573\b"), "len(tsv) == 576"),
    # mca_events.REASON_CODES: 290 → 301 (+11 кодов инициативного молчания/
    # отказов/проверки: раньше причинa молчания молча выбрасывалась).
    (re.compile(r"len\(mca_events\.REASON_CODES\) == 290\b"),
     "len(mca_events.REASON_CODES) == 301"),
)

changed: list[str] = []
for path in sorted((ROOT / "tests").rglob("*.py")):
    if "__pycache__" in str(path):
        continue
    text = path.read_text(encoding="utf-8")
    new = text
    for pattern, repl in _REPLACEMENTS:
        new = pattern.sub(repl, new)
    # meta-пин F8 (572/411/161) — числа в одном assert.
    new = new.replace('"572" in meta and "411" in meta and "161" in meta',
                      '"%d" in meta and "411" in meta and "%d" in meta'
                      % (NEW_REGISTRY, NEW_DELTA))
    if new != text:
        path.write_text(new, encoding="utf-8", newline="")
        changed.append(str(path.relative_to(ROOT)))

for path in sorted((ROOT / "tests").rglob("*.json")):
    if "__pycache__" in str(path):
        continue
    text = path.read_text(encoding="utf-8")
    new = re.sub(r'"REGISTRY": 572\b', '"REGISTRY": %d' % NEW_REGISTRY, text)
    new = re.sub(r'"delta": 161\b', '"delta": %d' % NEW_DELTA, new)
    if new != text:
        path.write_text(new, encoding="utf-8", newline="")
        changed.append(str(path.relative_to(ROOT)))

print("re-pinned files:", len(changed))
for item in changed:
    print("   ", item)
