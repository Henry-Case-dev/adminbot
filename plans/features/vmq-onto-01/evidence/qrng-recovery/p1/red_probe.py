"""QRNG P1 — поведенческий RED/GREEN-пробник (base `34c25d09` vs P1).

Запуск: `python plans/features/vmq-onto-01/evidence/qrng-recovery/p1/red_probe.py`
(скрипт копируется в worktree базы; пишет JSON одним объектом в stdout).

Проверяет ТОЛЬКО публичное поведение (без pytest-фикстур):
  A. draft-проверка: сколько строк появляется в `mca_random_batches`;
  B. ротация ключа A→B: фактический источник следующего draw и расход партии A.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from services import mca_random_source as mrs          # noqa: E402
from services.database import DatabaseService         # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def ok_uint16(length: int):
    return (200, {},
            '{"success": true, "type": "uint16", "length": %d, "data": %s}'
            % (length, list(range(length))))


async def _count_rows(db) -> int:
    cur = await db.db.execute("SELECT COUNT(*) AS c FROM mca_random_batches")
    return int((await cur.fetchone())["c"])


async def _reserved_upto(db) -> list:
    cur = await db.db.execute(
        "SELECT reserved_upto, length FROM mca_random_batches "
        "ORDER BY created_at, batch_id")
    return [dict(r) for r in await cur.fetchall()]


async def main() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="qrng_p1_probe_"))
    cfg: dict = {mrs.SETTING_BATCH_LENGTH: 8}
    mem: dict = {}
    mrs._hot_setting = lambda key, default: cfg.get(key, default)

    async def _mem(key, chat_id, default):
        return mem.get(key, default)

    mrs._read_memory_setting = _mem
    out: dict = {"base": mrs.__file__}

    # A. draft-проверка не должна зачислять партию.
    db = DatabaseService(str(tmp / "a.db"))
    await db.initialize()
    try:
        cfg[mrs.SETTING_KEY] = "key-stored"
        responses = [ok_uint16(8)]
        client = mrs.AnuClient(
            http_get=_http(responses), min_interval=0.0, clock=FakeClock())
        svc = mrs.RandomSourceService(db, client=client, auto_refill=False)
        result = await svc.test_connection(draft_key="draft-only")
        out["draft"] = {
            "healthy": result.get("healthy"),
            "deposited": result.get("deposited"),
            "batch_rows": await _count_rows(db),
        }
    finally:
        await db.close()

    # B. ротация ключа A→B: партии A не расходуются, effective — по контракту.
    db = DatabaseService(str(tmp / "b.db"))
    await db.initialize()
    try:
        cfg[mrs.SETTING_KEY] = "key-A"
        responses = [ok_uint16(8)]
        client = mrs.AnuClient(
            http_get=_http(responses), min_interval=0.0, clock=FakeClock())
        svc = mrs.RandomSourceService(db, client=client, auto_refill=False)
        activation = await svc.activate()
        before = await _reserved_upto(db)
        cfg[mrs.SETTING_KEY] = "key-B"
        state = await svc.anu_state()
        draw = await svc.draw_index(5, chat_id=1, purpose="probe")
        out["rotation"] = {
            "activated": activation.get("activated"),
            "state_after_rotation": state,
            "reserved_before": before,
            "draw_source": draw.source,
            "draw_provider_id": getattr(draw, "provider_id", None),
            "draw_deferred": draw.deferred,
            "reserved_after": await _reserved_upto(db),
        }
    finally:
        await db.close()
    return out


def _http(responses):
    async def http_get(url, headers, params, timeout):
        status, hdrs, text = responses.pop(0)
        return mrs._HttpResponse(status=status, headers=hdrs, text=text)

    return http_get


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
