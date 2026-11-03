"""Осознанное переиздание F11-пина `ROUTES_SHA256_F11` для релиза 2.58.152.

Причина санкции (L-F11S-1, прецеденты tools/_meme_p4_reissue_f8.py,
tools/_mca20_reissue_f8.py): reviewed-слайс P0.5-CEILING-AUTO (кандидат
97390ee4, hotfix 2.58.152) меняет ТЕЛО существующих обработчиков
`GET/POST /api/initiative/meme-settings` в `web/api/routes.py`:

* потолок длины мема читается в трёх состояниях (поля нет в теле = не менять;
  пусто/`null`/исторический `0` = авто = снять чатовое переопределение;
  положительное целое = фиксированный потолок; мусор/дробь/отрицательное =
  точная 422 у конкретного поля);
* витрина мемов отдаёт `events`/`event_names` цепочки публикации
  (`image_ready` → реально доставлено `publication_sent`).

Новых `@router`-маршрутов нет: routes-инвентарь `f8_baseline.json` не
меняется, RBAC/маскировка/DDL не менялись. Поэтому переиздаётся ТОЛЬКО
байтовый baseline-хэш (константа в тестах), сама проверка не ослабляется.

Пин живёт в двух местах (копия обязана совпадать с каноном):
  * tests/test_round1025_f8_registry.py — КАНОН;
  * tests/test_mca23_planned_vs_actual.py — копия.
Сателлиты (test_mca17c_invariants_round1047, test_asap7_cover_preview,
test_mca10b_*, test_mca12_stories_round1046, test_unified_image_request_round1026)
импортируют канон и правки не требуют.

Исторический fixture tests/fixtures/round1025/f8_baseline.json не меняется
(L-F9S-4).

Использование:
    py -3 tools/_pins_258152_reissue_routes.py --check   # только сверка
    py -3 tools/_pins_258152_reissue_routes.py           # переиздать литералы
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES = ROOT / "web" / "api" / "routes.py"

PIN_FILES = (
    ROOT / "tests" / "test_round1025_f8_registry.py",   # канон
    ROOT / "tests" / "test_mca23_planned_vs_actual.py",  # копия
)

# `ROUTES_SHA256_F11 = (\n ... комментарии ... \n    "<64 hex>")`
PIN_RE = re.compile(r'(")([0-9a-f]{64})("\))')


def actual_hash() -> str:
    return hashlib.sha256(ROUTES.read_bytes()).hexdigest()


def pin_hash(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index("ROUTES_SHA256_F11 = (")
    block = text[start:start + 20000]
    match = PIN_RE.search(block)
    if not match:
        raise SystemExit("FAIL: pin literal not found in %s" % path)
    return match.group(2)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    expected = actual_hash()
    print("web/api/routes.py sha256 =", expected)
    failed = False
    for path in PIN_FILES:
        current = pin_hash(path)
        state = "OK" if current == expected else "STALE"
        print("  %-46s %s %s" % (path.name, current, state))
        if current == expected:
            continue
        failed = True
        if check:
            continue
        text = path.read_text(encoding="utf-8")
        start = text.index("ROUTES_SHA256_F11 = (")
        block = text[start:start + 20000]
        match = PIN_RE.search(block)
        new_block = block[:match.start(2)] + expected + block[match.end(2):]
        path.write_text(text[:start] + new_block + text[start + 20000:],
                        encoding="utf-8", newline="")
        print("      -> rewritten to", expected)
    if check and failed:
        print("CHECK FAIL")
        return 1
    print("CHECK OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
