# -*- coding: utf-8 -*-
"""Read-only снимок состояния синтетики/настроек (прод venv).

Печатает: профиль синтетического чата (PG), строки throttle_state (SQLite),
ревизию style.policy (PG), строки image_reservation (PG), последние mca_events
по синтетическому чату (SQLite), глобальные лимиты из hot-слоя.
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

SYNTH_CHAT = -1009900000201


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
        rows = await conn.fetch(
            "SELECT chat_id, updated_at, chat_params FROM chat_profiles "
            "WHERE chat_id=$1", SYNTH_CHAT)
        print("STATE profile_rows=%d" % len(rows))
        for r in rows:
            cp = r["chat_params"] or {}
            print("STATE profile overrides=%s gates=%s"
                  % (json.dumps(cp.get("overrides") or {}),
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
        if val:
            print("STATE style history=%s"
                  % json.dumps((val.get("history") or [])[:6],
                               ensure_ascii=False, default=str)[:600])
        rrows = await conn.fetch(
            "SELECT reservation_key, status, error_code, delivery_failed, day "
            "FROM image_reservation WHERE chat_id=$1", SYNTH_CHAT)
        print("STATE image_reservation rows=%d" % len(rrows))
        for r in rrows:
            print("STATE reservation %s" % json.dumps(
                {k: str(v) for k, v in dict(r).items()}, ensure_ascii=False))

    cursor = await db.db.execute(
        "SELECT scope, user_id, burst_left, last_ts FROM throttle_state "
        "WHERE chat_id=?", (SYNTH_CHAT,))
    trows = [dict(r) for r in await cursor.fetchall()]
    print("STATE throttle_rows=%d %s" % (len(trows), json.dumps(trows)))
    cursor = await db.db.execute(
        "SELECT ts, level, event_name, outcome, component, stage, reason_code, "
        "chat_id, usage_json FROM mca_events WHERE chat_id=? "
        "ORDER BY id DESC LIMIT 6", (SYNTH_CHAT,))
    erows = [dict(r) for r in await cursor.fetchall()]
    print("STATE mca_events_for_synth=%d" % len(erows))
    for r in erows:
        print("STATE event %s" % json.dumps(
            {k: str(v)[:200] for k, v in r.items()}, ensure_ascii=False))
    try:
        cursor = await db.db.execute(
            "SELECT run_id, factual_verdict, temporal_status FROM "
            "mca_factcheck_runs WHERE chat_id=? LIMIT 3", (SYNTH_CHAT,))
        frows = [dict(r) for r in await cursor.fetchall()]
        print("STATE factcheck_runs_for_synth=%d %s"
              % (len(frows), json.dumps(frows, ensure_ascii=False)))
    except Exception as exc:  # noqa: BLE001
        print("STATE factcheck_runs ERR=%s" % type(exc).__name__)
    print("STATE limits burst=%r cooldown=%r"
          % (cache.get("limits.chat_burst_limit"),
             cache.get("limits.chat_cooldown_seconds")))
    await db.close()
    await cache.close()
    print("STATE done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
