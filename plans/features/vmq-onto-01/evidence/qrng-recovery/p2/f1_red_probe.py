"""QRNG P2 F1 — поведенческий пробник `int`-bomb на `length` ответа.

Запуск из корня worktree проверяемой ревизии:
`python plans/features/vmq-onto-01/evidence/qrng-recovery/p2/f1_red_probe.py`

HTTP инъецируется; сети нет. На базе `ba1619bc` ожидается сырой `ValueError`
из `int(text)` (CPython int-max-str-digits=4300) и `breaker fails=0`; на
исправленном кандидате — `LfdrError("validation_failed")` и `fails=1`.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from services import mca_random_source as mrs          # noqa: E402

BOMB = "9" * 4301


def _http():
    async def http_get(url, headers, params, timeout):
        return mrs._HttpResponse(
            status=200, headers={},
            text=json.dumps({"length": BOMB, "qrn": "aabb"}))
    return http_get


async def main() -> dict:
    out: dict = {"has_lfdr_client": hasattr(mrs, "LfdrClient")}
    if not out["has_lfdr_client"]:
        return out
    client = mrs.LfdrClient(http_get=_http(), min_interval=0.0)
    out["breaker_fails_before"] = client.status()["fails"]
    try:
        await client.fetch(length=2)
        out["outcome"] = "NO_ERROR"
    except mrs.AnuError as exc:
        out["outcome"] = "AnuError"
        out["error_type"] = type(exc).__name__
        out["code"] = exc.code
        out["sent"] = exc.sent
        out["reason"] = exc.reason
    except BaseException as exc:      # намеренно ловим всё для диагностики
        out["outcome"] = "RAW_EXCEPTION"
        out["error_type"] = type(exc).__name__
        out["message"] = str(exc)[:120]
    out["breaker_fails_after"] = client.status()["fails"]
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
