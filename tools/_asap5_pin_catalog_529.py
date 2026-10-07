# -*- coding: utf-8 -*-
"""ASAP 5 (T-5256): канон-пины каталога 523→529 в тестах — БЕЗ перевода
строк (байт-сохраняющая замена; фикс после newline-чанга)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPLS = [
    (r"len\(pc\.REGISTRY\) == 523", "len(pc.REGISTRY) == 529"),
    (r"len\(REGISTRY\) == 523", "len(REGISTRY) == 529"),
    (r'REGISTRY"\] == 523', 'REGISTRY"] == 529'),
    (r"len\(rows\) == 523", "len(rows) == 529"),
    (r'registry_keys"\]\) == 523', 'registry_keys"]) == 529'),
    (r"len\(keys\) == 523", "len(keys) == 529"),
    (r'"523" in meta', '"529" in meta'),
    (r'FIXTURE\["counts"\]\["delta"\] == 112',
     'FIXTURE["counts"]["delta"] == 118'),
]
changed = []
for path in sorted((ROOT / "tests").glob("*.py")):
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    new = text
    for pat, repl in REPLS:
        new = re.sub(pat, repl, new)
    if new != text:
        # нормализуем ТОЛЬКО найденные подстроки: пишем в исходном стиле
        # концов строк (у Repo-нормы LF; если файл CRLF — сохраняем CRLF)
        nl = "\r\n" if "\r\n" in text else "\n"
        body = new.replace("\r\n", "\n")
        if nl == "\r\n":
            body = body.replace("\n", "\r\n")
        path.write_bytes(body.encode("utf-8"))
        changed.append(path.name)
print("changed %d files:" % len(changed))
for name in changed:
    print("  ", name)
