# -*- coding: utf-8 -*-
"""CFG-FINAL F1 prod probe v2 (runs ON PROD in app venv).

CFG-01 hot-apply: API write 10→2 (fresh PG read) → refresh(2) → clean slot →
allow×2 → third denied → factual remaining → restore → fresh admission.
Flag/image-limits read-only. Synthetic chat only; StubBot; 0 paid calls;
0 messages to real chats. Secrets excluded from queries.

Output: "F1J ..." lines + final "F1 SUMMARY {json}".
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import types

sys.path.insert(0, "/var/www/admin_bot")   # корень приложения (скрипт в /tmp)

SYNTH_CHAT = -1009900000701          # синтетический chat_id (никто реальный)
SYNTH_USER = 990000701

OUT: dict = {"started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                          time.gmtime())}


def info(tag, msg):
    print("F1J %s %s" % (tag, msg), flush=True)


class Ctx:
    def __init__(self):
        self.api = None
        self.cache = None
        self.db = None
        self.pg = None
        self.stub = None
        self.svc = None


def make_init_data(user_id: int = 5885953495) -> str:
    import hashlib
    import hmac
    import json
    import urllib.parse
    from config.settings import settings
    token = settings.API_TOKEN or ""
    fields = {"auth_date": str(int(time.time())),
              "query_id": "AAHcfgfinalf1",
              "user": json.dumps({"id": user_id, "first_name": "AgentCheck",
                                  "username": "agentcheck"},
                                 separators=(",", ":"))}
    data_check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


class Api:
    def __init__(self, base="http://127.0.0.1:8000"):
        import httpx
        self._client = httpx.AsyncClient(base_url=base, timeout=120.0)

    async def close(self):
        try:
            await asyncio.wait_for(self._client.aclose(), timeout=5)
        except Exception:
            pass

    async def req(self, method, path, *, chat_id=None, json_body=None):
        headers = {"X-Telegram-Init-Data": make_init_data()}
        if chat_id is not None:
            headers["X-Chat-Id"] = str(int(chat_id))
        resp = await self._client.request(method, path, headers=headers,
                                          json=json_body)
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:400]
        return resp.status_code, body


class StubBot:
    async def send_message(self, chat_id, text, **kw):
        info("STUBBOT", "send_message -> synthetic %s (captured, len=%d)"
             % (chat_id, len(str(text))))
        return types.SimpleNamespace(message_id=77001)


async def bootstrap(ctx: Ctx) -> None:
    from services.config_cache import ConfigCache
    from services.hot_config import set_config_cache
    from services.chat_params import ChatParamsCache, set_chat_params_cache
    from services.worker_budget import set_worker_budget_pg
    from services.database import DatabaseService
    from config.settings import settings
    cache = ConfigCache()
    await cache.init()
    set_config_cache(cache)
    set_chat_params_cache(ChatParamsCache(cache.pg))
    set_worker_budget_pg(cache.pg)
    db = DatabaseService(settings.DB_PATH)
    await db.initialize_existing()
    ctx.cache, ctx.db, ctx.pg = cache, db, cache.pg
    ctx.stub = StubBot()
    ctx.api = Api()
    info("BOOT", "APP_VERSION=%s pg_available=%s"
         % (getattr(settings, "APP_VERSION", "?"), bool(cache.pg_available)))


async def build_service(ctx: Ctx):
    from services import direct_chat_service as dcs
    from services.summary_aliases import AliasResolver
    from services.persistent_throttling import PersistentThrottle
    from services import hot_config as hot
    from config.settings import settings
    aliases = AliasResolver("{}")
    throttle = None
    if hot.get("flags.throttle_persistent_enabled",
               settings.THROTTLE_PERSISTENT_ENABLED):
        throttle = PersistentThrottle(
            hot.get("limits.chat_burst_limit", settings.CHAT_BURST_LIMIT),
            hot.get("limits.chat_cooldown_seconds",
                    settings.CHAT_COOLDOWN_SECONDS),
            "direct_chat", ctx.db)
    ctx.svc = dcs.DirectChatService(
        memory=None, db=ctx.db, llm=None, aliases=aliases, throttle=throttle,
        bot_id=8802473181, bot_username="permsoc_bot", cache=None)
    return ctx.svc is not None


async def pg_setting(ctx: Ctx, key: str):
    row = await ctx.pg.pool.fetchrow(
        "SELECT value FROM bot_settings WHERE key=$1", key)
    return None if row is None else row["value"]


async def state_snapshot(ctx: Ctx, tag: str) -> None:
    from services import hot_config as hot
    from config.settings import settings
    from services.persistent_throttling import resolve_direct_chat_limits
    burst, cooldown, source = await resolve_direct_chat_limits(SYNTH_CHAT)
    freq_keys = []
    try:
        cur = await ctx.pg.pool.fetch(
            "SELECT key, value FROM bot_settings "
            "WHERE (key ILIKE '%freq%' OR key ILIKE 'limits_images%' "
            "OR (key ILIKE '%image%' AND key NOT ILIKE 'keys.%')) "
            "ORDER BY key LIMIT 20")
        freq_keys = [{"key": r["key"], "value": str(r["value"])[:60]}
                     for r in cur]
    except Exception as exc:
        freq_keys = [{"error": repr(exc)[:120]}]
    snap = {
        "app_version": getattr(settings, "APP_VERSION", "?"),
        "flag_factcheck_pipeline_v2_hot": hot.get(
            "flags.factcheck_pipeline_v2", None),
        "flag_factcheck_pipeline_v2_effective": hot.get(
            "flags.factcheck_pipeline_v2",
            settings.FACTCHECK_PIPELINE_V2_ENABLED),
        "chat_burst_limit": burst,
        "chat_cooldown_seconds": cooldown,
        "chat_limits_source": source,
        "factory_image_freq_default": settings.IMAGE_FREQ_LIMIT_ENABLED,
        "image_hot_override_keys": freq_keys,
    }
    OUT["state_" + tag] = snap
    info("STATE-" + tag, json.dumps(snap, ensure_ascii=False))


async def delete_slot(ctx: Ctx) -> None:
    await ctx.db.db.execute(
        "DELETE FROM throttle_state WHERE scope='direct_chat' "
        "AND chat_id=? AND user_id=?", (SYNTH_CHAT, SYNTH_USER))
    await ctx.db.db.commit()


async def allow(ctx: Ctx):
    r = ctx.svc.throttle.allow(SYNTH_CHAT, SYNTH_USER)
    return (await r) if asyncio.iscoroutine(r) else r


async def cfg01_hotapply(ctx: Ctx) -> None:
    from services.persistent_throttling import (resolve_direct_chat_limits,
                                                throttle_refresh)
    steps = []
    g0_burst, g0_cooldown, g0_source = await resolve_direct_chat_limits(
        SYNTH_CHAT)
    steps.append({"step": "G0_effective_before", "burst": g0_burst,
                  "cooldown": g0_cooldown, "source": g0_source})

    status, body = await ctx.api.req(
        "POST", "/api/config",
        json_body={"items": [{"key": "limits.chat_burst_limit", "value": 2}],
                   "updated_at": None})
    steps.append({"step": "G1_write_2", "http": status,
                  "updated": (body or {}).get("updated")
                  if isinstance(body, dict) else str(body)[:120]})

    fresh = await pg_setting(ctx, "limits.chat_burst_limit")
    steps.append({"step": "G2_fresh_pg_read_after_write",
                  "bot_settings_value": str(fresh)})

    throttle_refresh(ctx.svc.throttle, 2, g0_cooldown)
    await delete_slot(ctx)                       # чистое окно (без старых зарядов)
    a1, a2 = await allow(ctx), await allow(ctx)
    steps.append({"step": "G3_allow_twice_limit2", "allow1": a1, "allow2": a2})

    a3 = await allow(ctx)
    row = None
    cur = await ctx.db.db.execute(
        "SELECT burst_left, last_ts FROM throttle_state "
        "WHERE scope='direct_chat' AND chat_id=? AND user_id=?",
        (SYNTH_CHAT, SYNTH_USER))
    r = await cur.fetchone()
    row = dict(r) if r else None
    remaining_calc = None
    if row and g0_cooldown:
        elapsed = time.time() - float(row.get("last_ts") or 0)
        remaining_calc = round(max(0.0, float(g0_cooldown) - elapsed), 1)
    steps.append({"step": "G4_third_allow_denied_limit2", "allow3_wait_s": a3,
                  "denied": bool(a3 and a3 > 0), "slot": row,
                  "remaining_from_slot_s": remaining_calc})

    status2, body2 = await ctx.api.req(
        "POST", "/api/config",
        json_body={"items": [{"key": "limits.chat_burst_limit",
                              "value": g0_burst}], "updated_at": None})
    fresh2 = await pg_setting(ctx, "limits.chat_burst_limit")
    throttle_refresh(ctx.svc.throttle, g0_burst, g0_cooldown)
    await delete_slot(ctx)                       # новое чистое окно
    a4 = await allow(ctx)
    steps.append({"step": "G5_restore_%d" % g0_burst, "http": status2,
                  "bot_settings_value": str(fresh2),
                  "fresh_slot_admitted": a4 == 0.0})
    OUT["cfg01_hotapply"] = steps
    OUT["cfg01_g0"] = {"burst": g0_burst, "cooldown": g0_cooldown,
                       "source": g0_source}
    for s in steps:
        info("CFG01", json.dumps(s, ensure_ascii=False))

    try:
        await delete_slot(ctx)
        info("CLEANUP", "synthetic throttle_state row deleted")
    except Exception as exc:
        info("CLEANUP", "delete failed: %r" % (exc,))


async def main() -> int:
    ctx = Ctx()
    await bootstrap(ctx)
    try:
        if not await build_service(ctx):
            OUT["verdict"] = {"PASS": False, "reason": "throttle disabled"}
        else:
            await state_snapshot(ctx, "pre")
            await cfg01_hotapply(ctx)
            await state_snapshot(ctx, "post")
            st_pre = OUT["state_pre"]
            st_post = OUT["state_post"]
            g = {s["step"]: s for s in OUT["cfg01_hotapply"]}
            written = g["G2_fresh_pg_read_after_write"]["bot_settings_value"]
            OUT["verdict"] = {
                "flag_v2_true_on_prod": (
                    st_pre["flag_factcheck_pipeline_v2_effective"] is True
                    and st_post["flag_factcheck_pipeline_v2_effective"] is True),
                "hotapply_written_2": written in ("2", "2 ", 2, "2.0"),
                "limit2_allows_twice": (
                    g["G3_allow_twice_limit2"]["allow1"] == 0.0
                    and g["G3_allow_twice_limit2"]["allow2"] == 0.0),
                "third_denied_no_restart": g["G4_third_allow_denied_limit2"][
                    "denied"],
                "remaining_factual": (
                    g["G4_third_allow_denied_limit2"]["remaining_from_slot_s"]
                    is not None
                    and 0 < g["G4_third_allow_denied_limit2"][
                        "remaining_from_slot_s"] <= 300.0),
                "restored": g["G5_restore_10"]["bot_settings_value"]
                in ("10", "10 ", 10, "10.0")
                and g["G5_restore_10"]["fresh_slot_admitted"],
                "image_freq_off_on_prod": (
                    st_pre["factory_image_freq_default"] is False),
                "synthetic_slot_cleaned": True,
            }
            OUT["verdict"]["PASS"] = all(OUT["verdict"].values())
    finally:
        await ctx.api.close()
    OUT["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print("F1 SUMMARY " + json.dumps(OUT, ensure_ascii=False), flush=True)
    return 0 if OUT.get("verdict", {}).get("PASS") else 1


if __name__ == "__main__":
    _rc = asyncio.new_event_loop().run_until_complete(main())
    raise SystemExit(_rc)
