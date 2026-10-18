# -*- coding: utf-8 -*-
"""F8-переиздание каталога для CFG-02B (частотный лимит генераций).

Санкция: `plans/features/cfg/requirements-map.json` слайс CFG-02B
(§02B.1/§02B.2/§02B.3, ADR-1031-1) — Δ каталога **+4 ParamSpec** в
СУЩЕСТВУЮЩУЮ группу `limits_images`: `limits.image_freq_limit_enabled`
(bool, заводской OFF), `limits.image_freq_limit_burst` (int),
`limits.image_freq_limit_cooldown_seconds` (int),
`limits.image_freq_limit_mode` (str + select per_user|per_chat).
GROUPS/_TAB_BY_GROUP/TAB_RULES/routes — без изменений; delta 164 → 168;
REGISTRY 575 → 579; Settings-полей 454 → 458; categorized 550 → 554.
Прецедент процедуры — `tools/_soul1_w5_reissue_f8.py`.

Шаги:
  1) регенерирует TSV/meta/screen-map (`gen_param_registry_round1025`);
  2) обновляет `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`
     (counts + sha256 param_catalog.py + provenance note);
  3) переносит catalog-guard счётчики в тестах и их fixtures
     (REGISTRY 575→579, delta 164→168, Settings 454→458, categorized
     550→554, F8-TSV 576→580);
  4) переутверждает `PARAM_CATALOG_SHA256_FOLLOWUP` (L-F11S-1);
  5) переутверждает `FACTORY_SET_SHA256_12` (зарегистрирован новый
     редактируемый текст `message.image_failure.freq_limited`);
  6) сверяет `ROUTES_SHA256_F11` (routes.py НЕ менялся).

Запуск: `py -3 tools/_cfg02b_reissue_f8.py [--check]`
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402

CHECK_ONLY = "--check" in sys.argv

NEW_REGISTRY = 579
NEW_DELTA = 168
NEW_SETTINGS_FIELDS = 458
NEW_CATEGORIZED = 554
NEW_TSV_ROWS = 580


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


def _write_text_like(path: Path, text: str) -> None:
    raw = path.read_bytes()
    if b"\r\n" in raw:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


from services import param_catalog as pc  # noqa: E402
from services import prompt_registry as pr  # noqa: E402
from config.settings import Settings  # noqa: E402

if CHECK_ONLY:
    print("live REGISTRY:", len(pc.REGISTRY), "-> pin", NEW_REGISTRY)
    print("live Settings fields:",
          len(__import__("dataclasses").fields(Settings)),
          "-> pin", NEW_SETTINGS_FIELDS)
    print("live fingerprint:", pr.factory_set_fingerprint(), "| const:",
          pr.FACTORY_SET_SHA256_12)
    print("param_catalog sha256:", sha("services/param_catalog.py"))
    raise SystemExit(0)

# ── 1) регенерация F8-артефактов ───────────────────────────────────────────
rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")
print("F8 artifacts regenerated")

# ── 2) fixtures ────────────────────────────────────────────────────────────
fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = len(pc.REGISTRY)
fx["counts"]["GROUPS"] = len(pc.GROUPS)
fx["counts"]["TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["TAB_RULES"] = len(pc.TAB_RULES)
fx["counts"]["delta"] = NEW_DELTA
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
_note = (
    "; CFG-02B (19.10.2026, санкция requirements-map слайс CFG-02B, "
    "ADR-1031-1): Δ каталога +4 ParamSpec в СУЩЕСТВУЮЩУЮ группу limits_images — "
    "limits.image_freq_limit_enabled (bool, Factory OFF), "
    "limits.image_freq_limit_burst (int), "
    "limits.image_freq_limit_cooldown_seconds (int), "
    "limits.image_freq_limit_mode (str, select per_user|per_chat); "
    "REGISTRY 575→579; Settings 454→458; categorized 550→554; delta 164→168 "
    "(inventory 411 без изменений); GROUPS/_TAB_BY_GROUP/TAB_RULES/routes — "
    "in-place (без новых endpoint'ов)."
)
if "CFG-02B" not in fx.get("superseded_by", ""):
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
    (re.compile(r"len\(pc\.REGISTRY\) == 575\b"),
     "len(pc.REGISTRY) == %d" % NEW_REGISTRY),
    (re.compile(r"len\(REGISTRY\) == 575\b"),
     "len(REGISTRY) == %d" % NEW_REGISTRY),
    (re.compile(r'\["counts"\]\["REGISTRY"\] == 575\b'),
     '["counts"]["REGISTRY"] == %d' % NEW_REGISTRY),
    (re.compile(r"len\(cb\[\"registry_keys\"\]\) == 575\b"),
     "len(cb[\"registry_keys\"]) == %d" % NEW_REGISTRY),
    (re.compile(r"len\(keys\) == 575\b"), "len(keys) == %d" % NEW_REGISTRY),
    (re.compile(r"len\(rows\) == 575\b"), "len(rows) == %d" % NEW_REGISTRY),
    (re.compile(r'\["counts"\]\["delta"\] == 164\b'),
     '["counts"]["delta"] == %d' % NEW_DELTA),
    (re.compile(r'len\(delta\) == FIXTURE\["counts"\]\["delta"\] == 164\b'),
     'len(delta) == FIXTURE["counts"]["delta"] == %d' % NEW_DELTA),
    # Settings-поля: формы `len({f.name for f in dataclasses.fields(Settings)})`
    # и `len(dataclasses.fields(Settings))` / `len(fields)`.
    (re.compile(r"dataclasses\.fields\(Settings\)\}\) == 454\b"),
     "dataclasses.fields(Settings)}) == %d" % NEW_SETTINGS_FIELDS),
    (re.compile(r"len\(dataclasses\.fields\(Settings\)\) == 454\b"),
     "len(dataclasses.fields(Settings)) == %d" % NEW_SETTINGS_FIELDS),
    (re.compile(r"len\(fields\) == 454\b"),
     "len(fields) == %d" % NEW_SETTINGS_FIELDS),
    (re.compile(r"== 454(\s*#)"), r"== %d\1" % NEW_SETTINGS_FIELDS),
    # categorized-срез (specs с category).
    (re.compile(r"len\(categorized\) == 550\b"),
     "len(categorized) == %d" % NEW_CATEGORIZED),
    (re.compile(r"len\(items\) == len\(categorized\) == 550\b"),
     "len(items) == len(categorized) == %d" % NEW_CATEGORIZED),
    (re.compile(r'\["counts"\]\["categorized"\] == 550\b'),
     '["counts"]["categorized"] == %d' % NEW_CATEGORIZED),
    (re.compile(r'"categorized": 550\b'), '"categorized": %d'
     % NEW_CATEGORIZED),
    (re.compile(r"if s\.category is not None\]\) == 550\b"),
     "if s.category is not None]) == %d" % NEW_CATEGORIZED),
    # F8 TSV с заголовком: 576 → 580.
    (re.compile(r"len\(tsv\) == 576\b"),
     "len(tsv) == %d" % NEW_TSV_ROWS),
)

changed: list[str] = []
for path in sorted((ROOT / "tests").rglob("*.py")):
    if "__pycache__" in str(path):
        continue
    text = path.read_text(encoding="utf-8")
    new = text
    for pattern, repl in _REPLACEMENTS:
        new = pattern.sub(repl, new)
    new = new.replace('"575" in meta and "411" in meta and "164" in meta',
                      '"%d" in meta and "411" in meta and "%d" in meta'
                      % (NEW_REGISTRY, NEW_DELTA))
    new = new.replace("== 575          # 510 → 519 (+9)",
                      "== %d          # 510 → 519 (+9)" % NEW_REGISTRY)
    if new != text:
        path.write_text(new, encoding="utf-8", newline="")
        changed.append(str(path.relative_to(ROOT)))

for path in sorted((ROOT / "tests").rglob("*.json")):
    if "__pycache__" in str(path):
        continue
    text = path.read_text(encoding="utf-8")
    new = re.sub(r'"REGISTRY": 575\b', '"REGISTRY": %d' % NEW_REGISTRY, text)
    new = re.sub(r'"delta": 164\b', '"delta": %d' % NEW_DELTA, new)
    if new != text:
        path.write_text(new, encoding="utf-8", newline="")
        changed.append(str(path.relative_to(ROOT)))

print("re-pinned files:", len(changed))
for item in changed:
    print("   ", item)

# ── 4) переутверждение PARAM_CATALOG_SHA256_FOLLOWUP (L-F11S-1) ────────────
f8_test = ROOT / "tests/test_round1025_f8_registry.py"
text = f8_test.read_text(encoding="utf-8")
new_hash = sha("services/param_catalog.py")
new_text, n = re.subn(
    r'(PARAM_CATALOG_SHA256_FOLLOWUP = \(\n    ")[0-9a-f]{64}("\))',
    r"\g<1>%s\g<2>" % new_hash, text)
if n != 1:
    raise SystemExit("PARAM_CATALOG_SHA256_FOLLOWUP не найден однозначно")
# NOTE-санкция (прецедент L-F11S-1): почему хэш переутверждён.
if "CFG-02B" not in new_text:
    note = (
        "# CFG-02B (19.10.2026, санкция requirements-map слайс CFG-02B,\n"
        "# ADR-1031-1): Δ каталога +4 ParamSpec группы limits_images\n"
        "# (limits.image_freq_limit_*) — Settings 454→458, REGISTRY 575→579,\n"
        "# delta 164→168; GROUPS/TAB-маппинги/routes не менялись.\n"
        "# Хэш переутверждён осознанно (L-F11S-1); исторический fixture\n"
        "# f8_baseline.json обновлён этим же инструментом.\n"
    )
    new_text = new_text.replace(
        "PARAM_CATALOG_SHA256_FOLLOWUP = (",
        note + "PARAM_CATALOG_SHA256_FOLLOWUP = (", 1)
    new_text, n2 = re.subn(
        r'(PARAM_CATALOG_SHA256_FOLLOWUP = \(\n    ")[0-9a-f]{64}("\))',
        r"\g<1>%s\g<2>" % new_hash, new_text)
_write_text_like(f8_test, new_text)
print("PARAM_CATALOG_SHA256_FOLLOWUP ->", new_hash)

# ── 5) переутверждение FACTORY_SET_SHA256_12 (новый речевой блок) ──────────
pr_path = ROOT / "services/prompt_registry.py"
pr_text = pr_path.read_text(encoding="utf-8")
new_fp = pr.factory_set_fingerprint()
pr_new, n = re.subn(r'(FACTORY_SET_SHA256_12 = ")[0-9a-f]{12}(")',
                    r"\g<1>%s\g<2>" % new_fp, pr_text)
if n != 1:
    raise SystemExit("FACTORY_SET_SHA256_12 не найден однозначно")
# Идемпотентная NOTE-приписка: если константу переутверждает ДРУГОЙ лейн
# (напр. INIT-ARCH), приписка CFG-02B не добавляется повторно; маркер — сама
# строка бампа, не слово «CFG-02B» (оно есть и в блоке реестра — прежняя
# эвристика пропускала приписку молча).
if 'Бамп CFG-02B (19.10.2026' not in pr_new:
    pr_new = pr_new.replace(
        'FACTORY_SET_SHA256_12 = "%s"' % new_fp,
        '#: Бамп CFG-02B (19.10.2026, §02B.6, ADR-1031-1): зарегистрирован\n'
        '#: редактируемый текст отказа `message.image_failure.freq_limited`\n'
        '#: (короткая пауза частотного лимита) — было `%s`, стало `%s`.\n'
        'FACTORY_SET_SHA256_12 = "%s"'
        % (pr.FACTORY_SET_SHA256_12, new_fp, new_fp), 1)
_write_text_like(pr_path, pr_new)
print("FACTORY_SET_SHA256_12 ->", new_fp)

# ── 6) ROUTES_SHA256_F11 должен остаться прежним (routes.py не менялся) ────
routes_text = (ROOT / "web/api/routes.py").read_bytes()
print("routes sha:", hashlib.sha256(routes_text).hexdigest())
print("CHECK OK")
