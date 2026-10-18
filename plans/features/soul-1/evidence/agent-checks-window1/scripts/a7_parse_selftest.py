# -*- coding: utf-8 -*-
"""A7 self-test: разбор остатка из отказной фразы (как в прод-пробе)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from services.smartmodule_phrases import CHAT_COOLDOWN_PHRASES  # noqa: E402
from services.smartmodule_throttling import format_remaining_time  # noqa: E402


def parse(phrase, rem_db):
    prefixes = [p.split("{remaining_time}")[0] for p in CHAT_COOLDOWN_PHRASES]
    shape_ok = any(phrase.startswith(pfx) for pfx in prefixes)
    m = re.search(r"(\d+ мин(?: \d+ сек)?|\d+ сек)", phrase)
    seg = m.group(0) if m else ""
    try:
        if "мин" in seg:
            mp = re.match(r"(\d+) мин(?: (\d+) сек)?$", seg)
            ps = int(mp.group(1)) * 60 + int(mp.group(2) or 0)
        else:
            ps = int(re.match(r"(\d+) сек$", seg).group(1))
    except Exception:  # noqa: BLE001
        ps = -1
    delta = abs(ps - rem_db) if rem_db is not None and ps >= 0 else None
    return shape_ok, seg, delta


ok = True
for rem in (179.6, 297.4, 45.2, 4.6, 60.0, 0.9):
    fmt = format_remaining_time(rem)
    for p in CHAT_COOLDOWN_PHRASES:
        phrase = p.replace("{remaining_time}", fmt)
        shape_ok, seg, delta = parse(phrase, rem)
        good = shape_ok and delta is not None and delta <= 2.0
        ok = ok and good
        if not good:
            print("BAD", rem, fmt, repr(phrase), shape_ok, seg, delta)
print("A7 parse self-test all good =", ok)
