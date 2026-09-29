# -*- coding: utf-8 -*-
"""Одноразовый скрипт bump 2.58.36 → 2.58.37 (ASAP-3.1, блок N)."""
import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 1. config/settings.py: APP_VERSION = "2.58.36" → "2.58.37" + новый преамбул-текст.
settings_path = ROOT / "config" / "settings.py"
text = settings_path.read_text(encoding="utf-8")
old_line = 'APP_VERSION = "2.58.36"'
assert old_line in text, "APP_VERSION 2.58.36 не найден"
new_prefix = ('APP_VERSION = "2.58.37"   # ASAP-3.1 `mca-asap31-auto-budgets-'
              'capacity-react` round1028 (П0 владельца, current_task.md '
              '«# ASAP-3.1» §1–§146, spec CC419781 + ADR-1028-3 D1–D8): '
              'corrective acceptance addendum после ASAP-3. ')
text = text.replace(old_line, new_prefix, 1)
settings_path.write_text(text, encoding="utf-8")
print("settings.py bumped")

# 2. Пины тестов: APP_VERSION == "2.58.36" → "2.58.37".
pins = [
    "tests/test_decision_making_round1026.py",
    "tests/test_image_context_memory_round1026.py",
    "tests/test_round1025_f8_registry.py",
    "tests/test_summary_deploy_round1026.py",
    "tests/test_summary_fact_package.py",
    "tests/test_summary_logging_runid.py",
    "tests/test_summary_publish_integration_round1026.py",
]
for rel in pins:
    p = ROOT / rel
    if not p.exists():
        print("skip (нет файла):", rel)
        continue
    t = p.read_text(encoding="utf-8")
    if '"2.58.36"' in t:
        t = t.replace('"2.58.36"', '"2.58.37"')
        p.write_text(t, encoding="utf-8")
        print("pinned:", rel)
    else:
        print("no pin:", rel)

# 3. test_scope_selector_round1025.py пинит исходник settings — обновить
#    ожидание строки APP_VERSION.
scope = ROOT / "tests" / "test_scope_selector_round1025.py"
t = scope.read_text(encoding="utf-8")
if "'APP_VERSION = \"2.58.36\"'" in t:
    t = t.replace("'APP_VERSION = \"2.58.36\"'",
                  "'APP_VERSION = \"2.58.37\"'")
    scope.write_text(t, encoding="utf-8")
    print("pinned:", scope.name)
elif '"2.58.36"' in t:
    t = t.replace('"2.58.36"', '"2.58.37"')
    scope.write_text(t, encoding="utf-8")
    print("pinned (loose):", scope.name)
else:
    print("no pin in scope selector")
