# -*- coding: utf-8 -*-
"""Read-only снимок состояния синтетики/настроек (прод venv, окно-2).

Печатает: профили A/B (PG), строки throttle_state (SQLite) по A/B (все scope),
ревизию style.policy (PG), строки image_reservation (PG) по A, последние
mca_events по A/B (SQLite), глобальные лимиты.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SYNTH_A = -1009900000201
SYNTH_B = -1009900000202


async def main() -> int:
    from services.config_cache import ConfigCache
    from services.hot_config import set_config_cache
    from services.database import DatabaseService
    from config.settings import settings

    cache = ConfigCache()
    await cache.init()
    set_config_cache(cache)
    db = DatabaseService(settings.DB_PATH)
    await db.initialize_existing()

    pool = cache.pg.pool
    async with pool.acquire() as conn:
        for cid in (SYNTH_A, SYNTH_B):
            rows = await conn.fetch(
                "SELECT chat_id, updated_at, chat_params FROM chat_profiles "
                "WHERE chat_id=$1", cid)
            print("STATE profile_rows_%s=%d" % (cid, len(rows)))
            for r in rows:
                cp = r["chat_params"] or {}
                print("STATE profile_%s overrides=%s gates=%s"
                      % (cid, json.dumps(cp.get("overrides") or {},
                                         ensure_ascii=False),
                         json.dumps(cp.get("gates") or {})))
        row = await conn.fetchrow(
            "SELECT value FROM bot_settings WHERE key='style.policy'")
        val = row["value"] if row else None
        if isinstance(val, str):
            val = json.loads(val)
        print("STATE style.policy present=%s revision=%s rules=%s soft=%s"
              % (bool(row), (val or {}).get("revision"),
                 len((val or {}).get("rules") or []),
                 len((val or {}).get("soft_instructions") or [])))
        rrows = await conn.fetch(
            "SELECT reservation_key, status, error_code, delivery_failed, day "
            "FROM image_reservation WHERE chat_id=$1 ORDER BY created_at DESC "
            "LIMIT 8", SYNTH_A)
        print("STATE image_reservation_rows_%s=%d" % (SYNTH_A, len(rrows)))
        for r in rrows:
            print("STATE reservation %s" % json.dumps(
                {k: str(v) for k, v in dict(r).items()}, ensure_ascii=False))
        brows = await conn.fetch(
            "SELECT day, scope, metric, used FROM worker_budget "
            "WHERE metric='image_calls' ORDER BY day DESC LIMIT 8")
        print("STATE budget %s" % json.dumps(
            [{k: str(v) for k, v in dict(r).items()} for r in brows],
            ensure_ascii=False))

    cursor = await db.db.execute(
        "SELECT chat_id, scope, user_id, burst_left, last_ts FROM "
        "throttle_state WHERE chat_id IN (?,?) ORDER BY chat_id, scope",
        (SYNTH_A, SYNTH_B))
    trows = [dict(r) for r in await cursor.fetchall()]
    print("STATE throttle_rows=%d %s" % (len(trows), json.dumps(
        trows, ensure_ascii=False)[:600]))
    cursor = await db.db.execute(
        "SELECT ts, level, event_name, outcome, component, stage, reason_code, "
        "chat_id, usage_json FROM mca_events WHERE chat_id=? "
        "ORDER BY id DESC LIMIT 6", (SYNTH_A,))
    erows = [dict(r) for r in await cursor.fetchall()]
    print("STATE mca_events_for_A=%d" % len(erows))
    for r in erows:
        print("STATE event %s" % json.dumps(
            {k: str(v)[:180] for k, v in r.items()}, ensure_ascii=False))
    print("STATE limits burst=%r cooldown=%r image_daily=%r"
          % (cache.get("limits.chat_burst_limit"),
             cache.get("limits.chat_cooldown_seconds"),
             cache.get("limits.image_daily_limit")))
    await db.close()
    await cache.close()
    print("STATE done")
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print("STATE FATAL %s: %s" % (type(exc).__name__, str(exc)[:300]),
              flush=True)
        rc = 1
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(rc if isinstance(rc, int) else 0)
