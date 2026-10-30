# -*- coding: utf-8 -*-
"""EVOL §5 (W5, review-fix B1/B2, 31.10.2026): массовое переиздание
каталожных пинов legacy-тестов под санкционированную положительную Δ
каталога +2 ParamSpec / +1 GroupSpec.

Что именно добавляется (санкция: review-fix B1 — ручки владельца обязаны
быть в каталоге, иначе POST /api/config отдаёт 422 «неизвестный ключ», а
вкладка «Фактчек» их не рендерит):

  * `flags.factcheck_critique_section_enabled` — per-chat PG-only bool
    (группа flags_factcheck_delivery, вкладка mod_factcheck, default ON
    внутри включённого фактчека; НЕ мастер модуля);
  * `prompts.factcheck_critique_directive` — PG-ключ реестрового блока
    `factcheck.critique.directive` (группа prompts_factcheck);
  * +1 GroupSpec `flags_factcheck_delivery` («Подача ответа / стиль
    фактчека»), TAB_RULES — in-place.

Числа: REGISTRY 581→583, categorized 556→558, GROUPS 119→120,
_TAB_BY_GROUP 117→118, TAB_RULES 22 (без роста), delta 175→177,
TSV 581→583 строк. Settings-поля не меняются (PG-only ключи).

Прецедент: `tools/_evol031_reissue_f8.py`, `tools/_asap31_reissue_pins.py`
(контекстные замены ТОЛЬКО пин-паттернов, не произвольных чисел).
Запускать ПОСЛЕ emit-режима генератора и переиздания фикстур.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

PATTERNS = [
    # REGISTRY 581 → 583
    (re.compile(r"(len\(pc\.REGISTRY\)\s*==\s*)581\b"), r"\g<1>583"),
    (re.compile(r"(len\(REGISTRY\)\s*==\s*)581\b"), r"\g<1>583"),
    (re.compile(r"(len\(pc\.REGISTRY\)\s*==\s*FIXTURE\[.counts.\]\[.REGISTRY.\]"
                r"\s*==\s*)581\b"), r"\g<1>583"),
    (re.compile(r"(BASELINE\[.counts.\]\[.REGISTRY.\]\s*==\s*)581\b"), r"\g<1>583"),
    (re.compile(r"(len\(tsv\)\s*-\s*1\s*==\s*)581\b"), r"\g<1>583"),
    (re.compile(r"(len\(tsv\)\s*==\s*)582\b"), r"\g<1>584"),
    # GROUPS 119 → 120
    (re.compile(r"(len\(pc\.GROUPS\)\s*==\s*)119\b"), r"\g<1>120"),
    (re.compile(r"(len\(GROUPS\)\s*==\s*)119\b"), r"\g<1>120"),
    (re.compile(r"(len\(pc\.GROUPS\)\s*==\s*FIXTURE\[.counts.\]\[.GROUPS.\]"
                r"\s*==\s*)119\b"), r"\g<1>120"),
    (re.compile(r"(BASELINE\[.counts.\]\[.GROUPS.\]\s*==\s*)119\b"), r"\g<1>120"),
    # _TAB_BY_GROUP 117 → 118
    (re.compile(r"(len\(pc\._TAB_BY_GROUP\)\s*==\s*)117\b"), r"\g<1>118"),
    # categorized 556 → 558
    (re.compile(r"(len\(categorized\)\s*==\s*)556\b"), r"\g<1>558"),
    (re.compile(r"(category is not None\]\)\s*==\s*)556\b"), r"\g<1>558"),
    # delta 175 → 177
    (re.compile(r"(len\(delta\)\s*==\s*FIXTURE\[.counts.\]\[.delta.\]"
                r"\s*==\s*)175\b"), r"\g<1>177"),
    (re.compile(r"(fx\[.counts.\]\[.delta.\]\s*==\s*)175\b"), r"\g<1>177"),
    # BASELINE/фикстуры: явные счётчики (не только len(...))
    (re.compile(r"(BASELINE\[.counts.\]\[._TAB_BY_GROUP.\]\s*==\s*)117\b"),
     r"\g<1>118"),
    (re.compile(r"(fx\[.counts.\]\[.REGISTRY.\]\s*==\s*)581\b"), r"\g<1>583"),
    (re.compile(r"(fx\[.counts.\]\[.GROUPS.\]\s*==\s*)119\b"), r"\g<1>120"),
    (re.compile(r"(fx\[.counts.\]\[.TAB_BY_GROUP.\]\s*==\s*)117\b"),
     r"\g<1>118"),
    (re.compile(r"(len\(cb\[.registry_keys.\]\)\s*==\s*)581\b"), r"\g<1>583"),
    (re.compile(r"(FIXTURE\[.counts.\]\[.TAB_BY_GROUP.\]\s*==\s*)117\b"),
     r"\g<1>118"),
    (re.compile(r"(len\(rows\)\s*==\s*)581\b"), r"\g<1>583"),
    (re.compile(r"(len\(keys\)\s*==\s*)581\b"), r"\g<1>583"),
]

changed = []
for path in sorted(TESTS.rglob("test_*.py")):
    raw = path.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    original = text
    for pattern, repl in PATTERNS:
        text = pattern.sub(repl, text)
    if text != original:
        if crlf:  # сохранить исходный стиль переводов строк (min diff)
            text = text.replace("\n", "\r\n")
        path.write_bytes(text.encode("utf-8"))
        changed.append(path.name)

print("patched:", len(changed))
for name in changed:
    print(" -", name)
