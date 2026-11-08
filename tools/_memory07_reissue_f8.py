# -*- coding: utf-8 -*-
"""F8-переиздание каталога для MEMORY-07 волн 3-4 (08.11.2026).

Δ каталога: +1 PG-only ParamSpec категории `flags`
(`flags.memory_communities_enabled`, группа `flags_memory`, вкладка
`memory_rag`, per-chat): REGISTRY 597→598, GROUPS/_TAB_BY_GROUP/TAB_RULES
без роста (in-place), delta 191→192 (inventory 411 не менялся),
categorized 572→573, flags 106→107. Settings-полей нет (PG-only),
DDL = 0, новых routes нет.

Шаги (прецедент `tools/_meme_p2_reissue_f8.py`):
  1) регенерирует TSV/meta/screen-map/widget-map;
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) переносит catalog-guard-счётчики и sha256-пины в тестах.
Запуск:
  python tools/_memory07_reissue_f8.py
  python tools/gen_param_registry_round1025.py --check
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
    raw = path.read_bytes()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes((text + ("\r\n" if b"\r\n" in raw else "\n"))
                     .encode("utf-8"))


# ── 1) регенерация F8 (TSV/meta/screen-map/widget-map) ─────────────────────
if gen.run_emit() != 0:
    raise SystemExit("EMIT FAILED")

# ── 2) fixtures ─────────────────────────────────────────────────────────────
fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = 598
fx["counts"]["GROUPS"] = 121
fx["counts"]["TAB_BY_GROUP"] = 119
fx["counts"]["_TAB_BY_GROUP"] = 119
fx["counts"]["TAB_RULES"] = 22
fx["counts"]["delta"] = 192      # 598 - 406 (inventory 411, delta-набор 406)
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["services/pg_db.py"] = sha("services/pg_db.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_NOTE = (
    "; MEMORY-07 волны 3-4 (08.11.2026, EPIC-MEMORY-COGNITIVE-02 C-6 §5.2): "
    "Δ каталога +1 PG-only ParamSpec категории flags — "
    "flags.memory_communities_enabled (группа flags_memory, вкладка "
    "memory_rag, per-chat, заводской дефолт OFF; env-аварийная ось "
    "MCA_MEMORY_COMMUNITIES_ENABLED в каталоге не дублируется): REGISTRY "
    "597→598, GROUPS/_TAB_BY_GROUP/TAB_RULES 121/119/22 без роста (in-place), "
    "categorized 572→573, delta 191→192. Settings/DDL = 0, новых routes нет.")
if "MEMORY-07 волны 3-4" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"])

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

# ── 3) catalog-guard/счётчики в тестах ─────────────────────────────────────
_REPLACEMENTS = (
    # TSV-строки (+header): 598 → 599 (сначала, чтобы не поймать шаг ниже).
    (r"len\(tsv\) == 598", "len(tsv) == 599"),
    # REGISTRY 597 → 598 (+1 ключ сообществ).
    (r"len\(pc\.REGISTRY\) == 597", "len(pc.REGISTRY) == 598"),
    (r"len\(REGISTRY\) == 597", "len(REGISTRY) == 598"),
    (r"len\(rows\) == 597", "len(rows) == 598"),
    (r"len\(keys\) == 597", "len(keys) == 598"),
    (r"len\(tsv\) - 1 == 597", "len(tsv) - 1 == 598"),
    (r"len\(cb\[\"registry_keys\"\]\) == 597",
     "len(cb[\"registry_keys\"]) == 598"),
    (r'(== FIXTURE\["counts"\]\["REGISTRY"\] == )597', r"\g<1>598"),
    (r"\[\"counts\"\]\[\"REGISTRY\"\] == 597",
     "[\"counts\"][\"REGISTRY\"] == 598"),
    # categorized 572 → 573 (ключ категории flags).
    (r"len\(categorized\) == 572", "len(categorized) == 573"),
    (r"len\(items\) == len\(categorized\) == 572",
     "len(items) == len(categorized) == 573"),
    (r'"flags": 106', '"flags": 107'),
    # delta 191 → 192.
    (r'(== FIXTURE\["counts"\]\["delta"\] == )191', r"\g<1>192"),
    (r"\[\"counts\"\]\[\"delta\"\] == 191", "[\"counts\"][\"delta\"] == 192"),
    (r'"597" in meta and "411" in meta and "191" in meta',
     '"598" in meta and "411" in meta and "192" in meta'),
    (r'"597" in res\.stdout', '"598" in res.stdout'),
)
changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    text = path.read_text(encoding="utf-8")
    new = text
    for pat, repl in _REPLACEMENTS:
        new = re.sub(pat, repl, new)
    if new != text:
        # newline="\n": файлы репозитория с LF; иначе Windows перепишет CRLF.
        path.write_text(new, encoding="utf-8", newline="\n")
        changed += 1
print("guard-файлы обновлены:", changed)

# ── 4) byte-freeze sha256-пины (param_catalog.py, routes.py) ───────────────
_PIN_FILE = ROOT / "tests/test_round1025_f8_registry.py"
pin = _PIN_FILE.read_text(encoding="utf-8")
new_pin = re.sub(
    r'(PARAM_CATALOG_SHA256_FOLLOWUP = \(\r?\n?\s*")[0-9a-f]{64}(")',
    r"\g<1>" + sha("services/param_catalog.py") + r"\g<2>", pin)
new_pin = re.sub(
    r'(ROUTES_SHA256_F11 = \(\r?\n?(?:\s*#[^\n]*\r?\n)*\s*")[0-9a-f]{64}(")',
    r"\g<1>" + sha("web/api/routes.py") + r"\g<2>", new_pin)
if new_pin != pin:
    _PIN_FILE.write_text(new_pin, encoding="utf-8", newline="\n")
    print("hash-пины обновлены (param_catalog, routes)")
_pin_now = _PIN_FILE.read_text(encoding="utf-8")
for const, rel in (("PARAM_CATALOG_SHA256_FOLLOWUP",
                    "services/param_catalog.py"),
                   ("ROUTES_SHA256_F11", "web/api/routes.py")):
    block = _pin_now.split(const, 1)[1]
    digest = re.search(r"([0-9a-f]{64})", block)
    if digest is None or digest.group(1) != sha(rel):
        raise SystemExit(f"PIN MISMATCH: {const} != sha256({rel})")
print("hash-пины совпадают с файлами")

# ── 5) двойная проверка эмита ──────────────────────────────────────────────
if gen.run_check() != 0:
    raise SystemExit("CHECK FAILED")
print("OK: F8 переиздан и проверен")
