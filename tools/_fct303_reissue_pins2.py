# -*- coding: utf-8 -*-
"""Второй проход F8-reissue для FCT-303: categorized 633→642.

Счётчик `categorized` (ParamSpec с category) растёт на те же +9 PG-only
ключей `limits.factcheck_*`; REGISTRY-пины уже обновлены первым проходом
(`tools/_fct303_reissue_f8.py`). Запуск идемпотентен.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import param_catalog as pc  # noqa: E402

categorized = len([s for s in pc.REGISTRY.values() if s.category is not None])
print("categorized:", categorized)
assert categorized == 642

changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    new = re.sub(r"== 633\b", "== %d" % categorized, text)
    if new != text:
        path.write_bytes(new.encode("utf-8"))
        changed += 1
        print("categorized pin updated:", path.name)
print("files updated:", changed)
