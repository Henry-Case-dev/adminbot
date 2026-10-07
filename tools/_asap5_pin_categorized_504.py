# -*- coding: utf-8 -*-
"""ASAP 5 (T-5256): categorized-пин каталога 498→504 (+6 categorized,
PG-only профили embeddings) — байт-сохраняющая замена (без newline-чанга).
`MAX_PARAGRAPHS_HARD == 498` (summary-константа) НЕ трогается."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = "len(categorized) == 498"
NEW = "len(categorized) == 504"
OLD2 = "if s.category is not None]) == 498"
NEW2 = "if s.category is not None]) == 504"
changed = []
for path in sorted((ROOT / "tests").glob("*.py")):
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    new = text.replace(OLD, NEW).replace(OLD2, NEW2)
    if new != text:
        nl = "\r\n" if "\r\n" in text else "\n"
        body = new.replace("\r\n", "\n")
        if nl == "\r\n":
            body = body.replace("\n", "\r\n")
        path.write_bytes(body.encode("utf-8"))
        changed.append(path.name)
print("changed %d files:" % len(changed))
for name in changed:
    print("  ", name)
