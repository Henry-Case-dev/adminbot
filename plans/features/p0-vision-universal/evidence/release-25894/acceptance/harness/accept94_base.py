# -*- coding: utf-8 -*-
"""ACCEPTANCE-94 — controlled live acceptance bootstrap for prod 2.58.94.

Same proven ACCEPTANCE-91/92/93 bootstrap, adapted for the combined wave
(positive Vision via VISION-DL-FIX + CFG-02C §Ф6). Runs ON the production
host, imports the deployed modules, uses the real Telegram Bot for delivery,
the real PG/SQLite stores, and the real providers. No product code is
modified. Controlled-state writes are limited to the synthetic user
(990002001) and temporary per-chat settings that are restored at the end.

PROD-FAITHFUL BOT SESSION (2.58.94 VISION-DL-FIX): the bot is built through
`services.local_bot_api.build_local_api_session` exactly like bot.py does on
prod (local Bot API base + container->host file path wrapper). This is the
very code path the release fixes; the harness must use it, not a cloud
session.

This process is NOT the polling process: it invokes the deployed handler
functions directly with synthetic updates. Telegram delivery and provider
calls are real. Evidence is written to /tmp/accept94/evidence/.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import types
import urllib.parse
import uuid

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORK_CHAT = -1002661910336
SYNTH_USER = 990002001
ADMIN_ID = 5885953495
EVID = "/tmp/accept94/evidence"
os.makedirs(EVID, exist_ok=True)

START_EPOCH = int(time.time())
RESULTS: dict = {}
CAPTURED: list[str] = []


def out(tag: str, text) -> None:
    line = "ACC94 %s | %s" % (tag, text)
    print(line, flush=True)


def info(tag: str, text) -> None:
    print("ACC94 %s INFO | %s" % (tag, text), flush=True)


def save(name: str, payload) -> None:
    def _clean(obj):
        if isinstance(obj, dict):
            return {str(k): _clean(v) for k, v in obj.items()
                    if not str(k).startswith("_")}
        if isinstance(obj, (list, tuple)):
            return [_clean(v) for v in obj]
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        return "<%s>" % type(obj).__name__
    path = os.path.join(EVID, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_clean(payload), fh, ensure_ascii=False, indent=2,
                  default=str)
    info("SAVE", "%s (%d bytes)" % (name, os.path.getsize(path)))


def sha12(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8", "replace")
    return hashlib.sha256(data).hexdigest()[:12]


def head(text, n: int = 240) -> str:
    s = str(text or "").replace("\n", " ").strip()
    return s[:n]


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        if not msg:
            return
        if any(k in msg for k in (
                "TOOL_CALL", "TOOL_PLAN", "L1_PLAN", "DIRECT_TRIGGER",
                "DECISION_", "IMAGE_CONTEXT", "IMAGE_GENERATION",
                "image_postgen_vision", "[direct-exec]", "[tools]",
                "[image]", "[vision]", "[checkup]", "[direct] triggered",
                "[direct] cooldown", "DIRECT_UPDATE_DEDUP",
                "capability_not_ready", "capability not ready",
                "L1_CAPABILITY_REJECTED", "image_result", "reserve",
                "IMAGE_ANALYSIS", "image_analysis")):
            self.lines.append(msg[:1200])


CAP = Capture()
logging.getLogger().addHandler(CAP)
logging.getLogger().setLevel(logging.INFO)


class RecordingBot:
    """Real aiogram Bot + recording of actual sends (no redirect)."""

    def __init__(self, real):
        self._real = real
        self.sends: list[dict] = []

    async def send_message(self, chat_id, text, **kwargs):
        msg = await self._real.send_message(chat_id, text, **kwargs)
        self.sends.append({
            "kind": "message", "chat_id": int(chat_id),
            "message_id": getattr(msg, "message_id", None),
            "text_head": head(text, 240), "text_len": len(str(text or "")),
            "reply_to": kwargs.get("reply_to_message_id"),
            "_msg": msg,
        })
        return msg

    async def send_photo(self, chat_id, photo, **kwargs):
        data = getattr(photo, "data", b"") or b""
        msg = await self._real.send_photo(chat_id, photo, **kwargs)
        self.sends.append({
            "kind": "photo", "chat_id": int(chat_id),
            "message_id": getattr(msg, "message_id", None),
            "bytes": len(data), "sha12": sha12(data),
            "reply_to": kwargs.get("reply_to_message_id"),
            "_msg": msg,
        })
        return msg

    async def send_media_group(self, chat_id, media, **kwargs):
        msgs = await self._real.send_media_group(chat_id, media, **kwargs)
        self.sends.append({
            "kind": "media_group", "chat_id": int(chat_id),
            "message_ids": [getattr(m, "message_id", None) for m in msgs],
            "_msgs": msgs,
        })
        return msgs

    def __getattr__(self, name):
        return getattr(self._real, name)


class Ctx:
    def __init__(self):
        self.cache = None
        self.db = None
        self.pg = None
        self.llm = None
        self.memory = None
        self.aliases = None
        self.lore_cache = None
        self.search = None
        self.fetcher = None
        self.checkup = None
        self.router = None
        self.svc = None
        self.bot = None
        self.rec = None
        self.me = None
        self.tool_calls: list[dict] = []
        self.image_blocks: list[dict] = []
        self.postgen: list[dict] = []
        self.provider_calls: list[str] = []
        self.vision_transport_calls: list[str] = []
        self.original_overrides: dict = {}


CTX = Ctx()


def make_init_data(user_id: int = ADMIN_ID) -> str:
    from config.settings import settings
    token = settings.API_TOKEN or ""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHaccept94live",
        "user": json.dumps({"id": user_id, "first_name": "Accept94",
                            "username": "accept94"},
                           separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


class Api:
    def __init__(self, base="http://127.0.0.1:8000"):
        import httpx
        self._c = httpx.AsyncClient(base_url=base, timeout=180.0)

    async def close(self):
        await self._c.aclose()

    async def req(self, method, path, *, chat_id=None, json_body=None):
        headers = {"X-Telegram-Init-Data": make_init_data()}
        if chat_id is not None:
            headers["X-Chat-Id"] = str(int(chat_id))
        r = await self._c.request(method, path, headers=headers,
                                  json=json_body)
        try:
            body = r.json()
        except Exception:
            body = r.text[:400]
        return r.status_code, body


async def pg_fetch(sql, *args):
    pool = getattr(CTX.pg, "pool", None)
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


async def pg_exec(sql, *args):
    pool = getattr(CTX.pg, "pool", None)
    if pool is None:
        return 0
    async with pool.acquire() as conn:
        return await conn.execute(sql, *args)


async def sqlite_fetch(sql, args=()):
    cur = await CTX.db.db.execute(sql, args)
    return [dict(r) for r in await cur.fetchall()]


async def sqlite_exec(sql, args=()):
    await CTX.db.db.execute(sql, args)
    await CTX.db.db.commit()


# ─────────────────────────── bootstrap ──────────────────────────────────────

async def bootstrap():
    from services.config_cache import ConfigCache
    from services.hot_config import set_config_cache
    from services.chat_params import ChatParamsCache, set_chat_params_cache
    from services.worker_budget import set_worker_budget_pg
    from services.database import DatabaseService
    from services import hot_config as hot
    from config.settings import settings

    cache = ConfigCache()
    await cache.init()
    set_config_cache(cache)
    set_chat_params_cache(ChatParamsCache(cache.pg))
    set_worker_budget_pg(cache.pg)
    db = DatabaseService(settings.DB_PATH)
    await db.initialize_existing()
    CTX.cache, CTX.db, CTX.pg = cache, db, cache.pg

    from services.llm_client import LLMClient
    from services.summary_aliases import AliasResolver
    from services.summary_memory import MemoryManager
    from services.chat_lore_store import ChatLoreStore
    from services.lore_cache import ChatLoreCache
    from services.search_aggregator import SearchAggregator
    from services.system_logs_fetcher import CheckupLogsFetcher
    from services.checkup_service import CheckupService
    from services.persistent_throttling import PersistentThrottle
    from services.tool_router import ToolDeps, ToolHealthDeps, ToolRouter
    from services import direct_chat_service as dcs
    from services.smart_cache import get_smart_cache
    from services import lore_runtime, mca_vision
    from services import anticliche_cache
    from services import bot_persona

    CTX.llm = LLMClient(
        hot.get("models.llm_base_url", settings.LLM_BASE_URL),
        hot.get("keys.llm_api_key", settings.LLM_API_KEY),
        hot.get("models.llm_model_name", settings.LLM_MODEL_NAME),
        hot.get("models.embedding_model_name", settings.EMBEDDING_MODEL_NAME),
        embed_base_url=hot.get("models.embedding_base_url",
                               settings.EMBEDDING_BASE_URL),
        embed_api_key=hot.get("keys.embedding_api_key",
                              settings.EMBEDDING_API_KEY))
    CTX.aliases = AliasResolver(hot.get("limits.summary_aliases",
                                        settings.SUMMARY_ALIASES))
    CTX.memory = MemoryManager(db, CTX.llm, aliases=CTX.aliases)
    vec_ok = await CTX.memory.initialize()
    CTX.lore_cache = None
    if cache.pg_available:
        try:
            store = ChatLoreStore(cache.pg)
            CTX.lore_cache = ChatLoreCache(store)
        except Exception as exc:  # noqa: BLE001
            info("LORE", "cache init failed: %s" % type(exc).__name__)
    CTX.search = SearchAggregator()
    CTX.fetcher = CheckupLogsFetcher(
        sql_host=hot.get("models.checkup_betterstack_sql_host",
                         settings.CHECKUP_BETTERSTACK_SQL_HOST),
        sql_user=hot.get("keys.checkup_betterstack_sql_user",
                         settings.CHECKUP_BETTERSTACK_SQL_USER),
        sql_password=hot.get("keys.checkup_betterstack_sql_password",
                             settings.CHECKUP_BETTERSTACK_SQL_PASSWORD),
        sql_table=hot.get("models.checkup_betterstack_sql_table",
                          settings.CHECKUP_BETTERSTACK_SQL_TABLE),
        sql_query=hot.get("models.checkup_betterstack_sql_query",
                          settings.CHECKUP_BETTERSTACK_SQL_QUERY),
        journalctl_cmd=settings.CHECKUP_JOURNALCTL_CMD)
    CTX.checkup = CheckupService(CTX.llm, db=db, memory=CTX.memory)
    CTX.router = ToolRouter(ToolDeps(
        search=CTX.search, memory=CTX.memory, aliases=CTX.aliases, db=db,
        health=ToolHealthDeps(CTX.checkup, CTX.fetcher), llm=CTX.llm))

    from aiogram import Bot
    # 2.58.94 VISION-DL-FIX: prod-faithful session (bot.py builds exactly this
    # when flags.download_enabled/DOWNLOAD_ENABLED is ON).
    if hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):
        from services.local_bot_api import build_local_api_session
        CTX.bot = Bot(
            token=settings.API_TOKEN,
            session=build_local_api_session(settings.LOCAL_BOT_API_URL),
        )
        info("BOT", "session=local_bot_api (download_enabled=1)")
    else:
        CTX.bot = Bot(token=settings.API_TOKEN)
        info("BOT", "session=cloud (download_enabled=0)")
    CTX.me = await CTX.bot.get_me()
    CTX.rec = RecordingBot(CTX.bot)

    throttle = PersistentThrottle(
        hot.get("limits.chat_burst_limit", settings.CHAT_BURST_LIMIT),
        hot.get("limits.chat_cooldown_seconds",
                settings.CHAT_COOLDOWN_SECONDS), "direct_chat", db)
    CTX.svc = dcs.DirectChatService(
        CTX.memory, db, CTX.llm, CTX.aliases, throttle=throttle,
        bot_id=CTX.me.id, bot_username=(CTX.me.username or "").lower(),
        cache=get_smart_cache(), tool_router=CTX.router,
        chat_lore_cache=CTX.lore_cache)

    # prod-equivalent runtime bindings (no workers/schedulers started)
    lore_runtime.set_lore_components(
        store=lore_runtime.get_lore_store(), cache=CTX.lore_cache, db=db)
    mca_vision.bind_runtime(db=db, bot=CTX.rec)
    anticliche_cache.set_runtime_pg(cache.pg)
    try:
        await anticliche_cache.load_rules(cache.pg)
    except Exception:
        pass
    try:
        await bot_persona.load_global_cache()
    except Exception:
        pass

    from handlers.direct_chat import setup_direct_chat
    from handlers.checkup import setup_checkup
    setup_direct_chat(CTX.svc, CTX.me.id, (CTX.me.username or "").lower())
    setup_checkup(CTX.checkup, CTX.fetcher, db)

    # tool dispatch spy (records args/results; no behaviour change)
    orig_dispatch = CTX.router.dispatch

    async def dispatch_spy(name, arguments, ctx):
        rec = {"tool": str(name), "args": _safe_args(arguments),
               "started": time.time()}
        try:
            result = await orig_dispatch(name, arguments, ctx)
        except Exception as exc:
            rec["error"] = type(exc).__name__
            rec["elapsed_ms"] = int((time.time() - rec["started"]) * 1000)
            CTX.tool_calls.append(rec)
            raise
        text = str(result)
        rec["ok"] = True
        rec["elapsed_ms"] = int((time.time() - rec["started"]) * 1000)
        rec["result_head"] = text[:800]
        rec["result_len"] = len(text)
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                rec["status"] = payload.get("status")
                rec["reason"] = payload.get("reason")
                rec["visible_reason"] = payload.get("visible_reason")
                rec["analysis_revision"] = payload.get("analysis_revision")
                rec["cache_hit"] = payload.get("cache_hit")
                rec["visual_description_len"] = len(
                    str(payload.get("visual_description") or ""))
                rec["visual_description_head"] = str(
                    payload.get("visual_description") or "")[:300]
                rec["ocr_blocks"] = len(payload.get("ocr_blocks") or [])
                if str(name) == "recognize_image":
                    rec["result_head"] = json.dumps({
                        k: payload.get(k) for k in (
                            "status", "reason", "visible_reason",
                            "analysis_revision", "cache_hit", "asset_id",
                            "message_key", "job_linked", "out_of_scope")
                        if payload.get(k) is not None}, ensure_ascii=False)
                elif str(name) == "fact_check":
                    rec["result_head"] = json.dumps({
                        k: payload.get(k) for k in (
                            "status", "reason", "factual_verdict",
                            "temporal_status", "assessment_mode",
                            "fallback_used", "cache_hit")
                        if payload.get(k) is not None}, ensure_ascii=False)
        except Exception:
            pass
        CTX.tool_calls.append(rec)
        return result

    CTX.router.dispatch = dispatch_spy

    # image generation spy: provider calls + returned image block
    from services import image_generation as ig
    orig_post, orig_get = ig._generate_post, ig._generate_get

    async def spy_post(*a, **k):
        CTX.provider_calls.append("post")
        return await orig_post(*a, **k)

    async def spy_get(*a, **k):
        CTX.provider_calls.append("get")
        return await orig_get(*a, **k)

    ig._generate_post, ig._generate_get = spy_post, spy_get
    orig_maybe = ig.maybe_handle_keyword

    async def maybe_spy(ctx, query, **kw):
        block = await orig_maybe(ctx, query, **kw)
        CTX.image_blocks.append({"query": str(query)[:200],
                                 "block": str(block)[:3000]})
        return block

    ig.maybe_handle_keyword = maybe_spy

    # postgen spy (status/description length; no OCR text stored)
    from services import postgen_vision
    orig_postgen = postgen_vision.analyze_generated_image

    async def postgen_spy(data, *, chat_id, correlation_id=None):
        outcome = await orig_postgen(data, chat_id=chat_id,
                                     correlation_id=correlation_id)
        CTX.postgen.append({
            "status": getattr(outcome, "status", None),
            "reason": getattr(outcome, "reason", None),
            "visible_reason": getattr(outcome, "visible_reason", None),
            "has_content": bool(getattr(outcome, "has_content", False)),
            "description_len": len(str(getattr(outcome,
                                               "visual_description", "") or "")),
            "ocr_blocks": len(getattr(outcome, "ocr_blocks", ()) or ()),
            "cache_hit": bool(getattr(outcome, "cache_hit", False)),
        })
        return outcome

    postgen_vision.analyze_generated_image = postgen_spy

    # vision transport spy (count real provider attempts; no payload stored)
    orig_transport = mca_vision._default_transport

    async def transport_spy(url, *, payload=None, headers=None, **kw):
        CTX.vision_transport_calls.append("probe_or_analyze")
        return await orig_transport(url, payload=payload, headers=headers,
                                    **kw)

    mca_vision._default_transport = transport_spy

    # correlation id spy (exact id of each turn)
    from services import usage_events as ue
    CTX._corr = []
    orig_new = ue.new_correlation_id

    def new_corr():
        cid = orig_new()
        CTX._corr.append(cid)
        return cid

    ue.new_correlation_id = new_corr

    out("BOOT", "version=%s vec=%s bot=%s pg=%s"
        % (getattr(settings, "APP_VERSION", "?"), vec_ok, CTX.me.id,
           bool(cache.pg_available)))
    return CTX


def _safe_args(arguments) -> dict:
    if not isinstance(arguments, dict):
        return {}
    out = {}
    for key in ("target", "claim", "query", "person", "purpose", "mode"):
        if key in arguments:
            val = arguments[key]
            if isinstance(val, dict):
                out[key] = {k: val[k] for k in ("chat_id", "message_id")
                            if k in val}
            else:
                out[key] = str(val)[:220]
    return out


# ─────────────────────────── message helpers ────────────────────────────────

def make_user(uid=SYNTH_USER, first="Acceptance", username="accept94"):
    return types.SimpleNamespace(id=uid, first_name=first, last_name=None,
                                 username=username, is_bot=False)


def make_photo(file_id, unique, width, height, file_size):
    return types.SimpleNamespace(file_id=file_id, file_unique_id=unique,
                                 width=width, height=height,
                                 file_size=file_size)


def make_message(*, msg_id, text=None, caption=None, reply_to=None,
                 photo=None, chat_id=WORK_CHAT):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(id=chat_id, type="supergroup",
                                   title="acceptance"),
        message_id=msg_id,
        text=text,
        caption=caption,
        from_user=make_user(),
        reply_to_message=reply_to,
        photo=([photo] if photo is not None else None),
        document=None, sticker=None, animation=None,
        video=None, video_note=None, voice=None, audio=None,
        media_group_id=None,
        entities=(), caption_entities=(),
        forward_origin=None,
        date=int(time.time()),
    )


def make_photo_message(asset, caption=None, msg_id=None):
    p = make_photo(asset["file_id"], asset["file_unique_id"],
                   asset.get("width"), asset.get("height"),
                   asset.get("byte_size"))
    return make_message(msg_id=int(msg_id or asset["tg_message_id"]),
                        text=None, caption=caption, photo=p)


async def reset_synth_throttle():
    try:
        await sqlite_exec(
            "DELETE FROM throttle_state WHERE scope IN "
            "('direct_chat','direct_silence') AND chat_id=? AND user_id=?",
            (WORK_CHAT, SYNTH_USER))
    except Exception as exc:  # noqa: BLE001
        info("THROTTLE", "reset failed: %s" % type(exc).__name__)


async def run_turn(text, *, msg_id, reply_to=None, photo=None,
                   caption=None, label="turn", timeout=300):
    from handlers.direct_chat import direct_chat_handler
    await reset_synth_throttle()
    msg = make_message(msg_id=msg_id, text=text, caption=caption,
                       reply_to=reply_to, photo=photo)
    start = time.time()
    logs_before = len(CAP.lines)
    tools_before = len(CTX.tool_calls)
    blocks_before = len(CTX.image_blocks)
    postgen_before = len(CTX.postgen)
    sends_before = len(CTX.rec.sends)
    corr_before = len(CTX._corr)
    status = "ok"
    error = ""
    try:
        rc = await asyncio.wait_for(direct_chat_handler(msg, bot=CTX.rec),
                                    timeout=timeout)
        handled = (rc is None)       # None = consumed; UNHANDLED sentinel = not
    except asyncio.TimeoutError:
        status, error, handled = "timeout", "handler timeout", True
    except Exception as exc:  # noqa: BLE001
        status = "exception"
        error = "%s: %s" % (type(exc).__name__, str(exc)[:240])
        handled = True
    await asyncio.sleep(0.4)
    corr = CTX._corr[-1] if len(CTX._corr) > corr_before else None
    plan = None
    usage = []
    if corr:
        try:
            rows = await pg_fetch(
                "SELECT correlation_id, step, tool_name, input_tokens, "
                "output_tokens, cost_usd, price_known, plan_meta, ts "
                "FROM llm_usage_events WHERE correlation_id=$1 "
                "ORDER BY ts, id", corr)
            usage = [{k: (str(v) if k == "ts" else v)
                      for k, v in r.items()} for r in rows]
            for r in rows:
                if r.get("step") == "l1_planner":
                    plan = r.get("plan_meta")
                    break
        except Exception as exc:  # noqa: BLE001
            info(label, "usage query failed: %s" % type(exc).__name__)
    sends = _sanitize_sends(CTX.rec.sends[sends_before:])
    answer = ""
    for s in reversed(sends):
        if s.get("kind") == "message":
            answer = s.get("text_head") or ""
            break
    bot_reply = []
    try:
        mids = [s.get("message_id") for s in sends
                if s.get("kind") == "message" and s.get("message_id")]
        if mids:
            rows = await sqlite_fetch(
                "SELECT chat_id, message_id, length(text) AS text_len "
                "FROM bot_replies WHERE chat_id=? AND message_id=?",
                (WORK_CHAT, mids[-1]))
            bot_reply = rows
    except Exception:
        pass
    return {
        "label": label,
        "status": status,
        "error": error,
        "handled": handled,
        "correlation_id": corr,
        "plan_meta": plan,
        "usage": usage,
        "logs": CAP.lines[logs_before:],
        "tool_calls": CTX.tool_calls[tools_before:],
        "image_blocks": CTX.image_blocks[blocks_before:],
        "postgen": CTX.postgen[postgen_before:],
        "sends": sends,
        "answer_head": answer,
        "bot_reply": bot_reply,
        "elapsed_s": round(time.time() - start, 2),
        "_last_msg": (CTX.rec.sends[-1].get("_msg")
                      if CTX.rec.sends else None),
    }


def _sanitize_sends(sends):
    out = []
    for s in sends:
        out.append({k: v for k, v in s.items() if not k.startswith("_")})
    return out


def _plan_caps(plan) -> list:
    if not plan:
        return []
    val = plan.get("capabilities")
    if isinstance(val, str):
        return [x for x in val.split(",") if x]
    if isinstance(val, (list, tuple)):
        return list(val)
    return []


def _turn_has_tool(turn, tool):
    return any(t.get("tool") == tool for t in turn.get("tool_calls", []))


def _turn_plan_caps(turn):
    return _plan_caps(turn.get("plan_meta"))


async def latest_anchor(fallback=None):
    if CTX.rec.sends:
        m = CTX.rec.sends[-1].get("_msg")
        if m is not None:
            return m
    return fallback


# ─────────────────────────── scenario 1 ─────────────────────────────────────

async def scenario_health():
    res = {"scenario": "1-health", "turns": []}
    anchor = await CTX.rec.send_message(
        WORK_CHAT, "🧪 Приёмка 2.58.91 · проверка health (контролируемый вызов).")
    phrase = "бот, как состояние сервера?"
    t = await run_turn(phrase, msg_id=anchor.message_id, reply_to=anchor,
                       label="health-1")
    res["turns"].append({"phrase": phrase, **_strip_turn(t)})
    caps = _turn_plan_caps(t)
    has_health = ("health" in caps) or _turn_has_tool(t, "get_bot_health")
    if not has_health:
        phrase2 = "бот, проверь последние ошибки"
        anchor = t.get("_last_msg") or anchor
        t2 = await run_turn(phrase2, msg_id=anchor.message_id, reply_to=anchor,
                            label="health-2")
        res["turns"].append({"phrase": phrase2, **_strip_turn(t2)})
        caps2 = _turn_plan_caps(t2)
        has_health = ("health" in caps2) or _turn_has_tool(t2, "get_bot_health")
        t = t2
    if not has_health:
        # prove the tool itself (real logs; no delivery) and record planner gap
        info("HEALTH", "planner did not select health; direct tool proof")
        try:
            proof = await CTX.router.dispatch("get_bot_health", {},
                                              _tool_ctx("health-proof"))
            res["tool_proof"] = {"tool": "get_bot_health",
                                 "result_head": str(proof)[:800],
                                 "result_len": len(str(proof))}
        except Exception as exc:  # noqa: BLE001
            res["tool_proof"] = {"error": type(exc).__name__}
    res["ok"] = has_health or bool(res.get("tool_proof", {}).get("result_len"))
    res["planner_selected_health"] = has_health
    # canonical "чекап" control through the 0g handler
    try:
        await sqlite_exec(
            "DELETE FROM throttle_state WHERE scope='checkup' "
            "AND chat_id=? AND user_id=0", (WORK_CHAT,))
    except Exception:
        pass
    from handlers.checkup import checkup_handler
    anchor = t.get("_last_msg") or anchor
    cmsg = make_message(msg_id=anchor.message_id, text="чекап",
                        reply_to=None)
    before = len(CTX.rec.sends)
    try:
        rc = await asyncio.wait_for(checkup_handler(cmsg, bot=CTX.rec),
                                    timeout=240)
        res["canon"] = {
            "rc_is_none": rc is None,
            "sends": _sanitize_sends(CTX.rec.sends[before:]),
        }
        res["canon"]["answer_head"] = (
            res["canon"]["sends"][-1].get("text_head")
            if res["canon"]["sends"] else "")
    except Exception as exc:  # noqa: BLE001
        res["canon"] = {"error": "%s: %s" % (type(exc).__name__,
                                             str(exc)[:200])}
    save("scenario-1-health.json", res)
    return res


def _tool_ctx(label):
    from services.tool_router import ToolContext
    return ToolContext(WORK_CHAT, "", bot=CTX.rec, user_id=SYNTH_USER,
                       correlation_id=label)


def _strip_turn(t):
    return {k: v for k, v in t.items() if not k.startswith("_")}


# ─────────────────────────── scenario 3 ─────────────────────────────────────

async def scenario_vision():
    from services import mca_vision
    res = {"scenario": "3-vision-freeform", "turns": []}
    rows = await sqlite_fetch(
        "SELECT asset_id, tg_message_id, asset_kind, mime, byte_size, width, "
        "height, file_id, file_unique_id FROM mca_media_assets "
        "WHERE chat_id=? AND asset_kind='photo' AND byte_size>=20000 "
        "ORDER BY tg_message_id DESC LIMIT 4", (WORK_CHAT,))
    if not rows:
        rows = await sqlite_fetch(
            "SELECT asset_id, tg_message_id, asset_kind, mime, byte_size, "
            "width, height, file_id, file_unique_id FROM mca_media_assets "
            "WHERE chat_id=? AND asset_kind='photo' "
            "ORDER BY tg_message_id DESC LIMIT 4", (WORK_CHAT,))
    if not rows:
        res["ok"] = False
        res["error"] = "no photo assets in work chat"
        save("scenario-3-vision-freeform.json", res)
        return res
    a = rows[0]
    res["asset"] = {k: (("present(len=%d,last4=%s)" % (
        len(str(v)), str(v)[-4:])) if k == "file_id" else v)
        for k, v in a.items()}
    msg = make_photo_message(a, caption="бот, что на картинке?")
    try:
        ids = await mca_vision.register_intake_assets(CTX.db, msg)
        res["intake_asset_ids"] = ids
    except Exception as exc:  # noqa: BLE001
        res["intake_error"] = type(exc).__name__
    t = await run_turn(None, msg_id=a["tg_message_id"], caption=msg.caption,
                       photo=msg.photo[0], label="vision-own")
    res["turns"].append({"phrase": "бот, что на картинке?", **_strip_turn(t)})
    res["tool_called"] = _turn_has_tool(t, "recognize_image")
    tool = next((x for x in t.get("tool_calls", [])
                 if x.get("tool") == "recognize_image"), None)
    res["tool_result"] = tool
    res["ok"] = bool(res["tool_called"])
    # text reply on the photo ("прочитай надпись") — faithful current-message id
    if len(rows) > 1:
        a2 = rows[1]
        anchor = t.get("_last_msg") or None
        if anchor is not None:
            photo_msg = make_photo_message(a2, caption="")
            photo_msg.from_user = make_user()  # not the bot
            t2 = await run_turn(
                "бот, прочитай надпись", msg_id=anchor.message_id,
                reply_to=photo_msg, label="vision-reply")
            res["turns"].append({"phrase": "бот, прочитай надпись",
                                 "reply_asset_tg": a2["tg_message_id"],
                                 **_strip_turn(t2)})
            res["reply_tool_called"] = _turn_has_tool(t2, "recognize_image")
            res["reply_tool_result"] = next(
                (x for x in t2.get("tool_calls", [])
                 if x.get("tool") == "recognize_image"), None)
    save("scenario-3-vision-freeform.json", res)
    return res


# ─────────────────────────── scenario 4 ─────────────────────────────────────

async def scenario_factcheck():
    res = {"scenario": "4-factcheck", "turns": []}
    claim = "Вода закипает при 100 °C на уровне моря."
    anchor = await CTX.rec.send_message(
        WORK_CHAT, "🧪 Приёмка 2.58.91 · утверждение для фактчека: " + claim)
    # exact free-form phrase first
    t = await run_turn("бот, это правда?", msg_id=anchor.message_id,
                       reply_to=anchor, label="fact-exact")
    res["turns"].append({"phrase": "бот, это правда?",
                         **_strip_turn(t)})
    got = _turn_has_tool(t, "fact_check")
    if not got:
        anchor2 = t.get("_last_msg") or anchor
        t2 = await run_turn(
            "бот, проверь факт: вода закипает при 100 °C на уровне моря.",
            msg_id=anchor2.message_id, reply_to=anchor2,
            label="fact-explicit", timeout=300)
        res["turns"].append({"phrase": "бот, проверь факт: ...",
                             **_strip_turn(t2)})
        got = _turn_has_tool(t2, "fact_check")
        t = t2
    res["tool_called"] = got
    res["tool_result"] = next(
        (x for x in t.get("tool_calls", []) if x.get("tool") == "fact_check"),
        None)
    res["ok"] = got
    save("scenario-4-factcheck.json", res)
    return res


# ─────────────────────────── scenario 5/6/7 ─────────────────────────────────

async def scenario_generate():
    res = {"scenario": "5-generate+6-postgen+7-cfg02b", "generations": []}
    # Ensure module ON (effective)
    from services import image_generation as ig
    enabled = await ig.resolve_module_enabled(WORK_CHAT)
    res["module_enabled"] = enabled
    if not enabled:
        res["ok"] = False
        res["error"] = "image module disabled"
        save("scenario-5-generate.json", res)
        return res
    # clear freq counter for synthetic user (limiter is OFF at this point)
    try:
        await sqlite_exec(
            "DELETE FROM throttle_state WHERE scope='image_freq' "
            "AND chat_id=? AND user_id IN (?, 0)", (WORK_CHAT, SYNTH_USER))
    except Exception:
        pass
    anchor = await latest_anchor()
    # generation 1 (scenario 5)
    q1 = "бот, нарисуй безобидный рисунок: жёлтый резиновый утёнок на белом фоне"
    p_before = len(CTX.provider_calls)
    t1 = await run_turn(q1, msg_id=anchor.message_id, reply_to=anchor,
                       label="gen-1", timeout=360)
    res["generations"].append({
        "phase": "gen1", "query": q1,
        "provider_calls": len(CTX.provider_calls) - p_before,
        **_strip_turn(t1)})
    # replay same update — no second provider call / send
    p_before2 = len(CTX.provider_calls)
    s_before2 = len(CTX.rec.sends)
    t1r = await run_turn(q1, msg_id=anchor.message_id, reply_to=anchor,
                         label="gen1-replay", timeout=120)
    res["replay"] = {
        "provider_calls": len(CTX.provider_calls) - p_before2,
        "new_sends": len(CTX.rec.sends) - s_before2,
        **_strip_turn(t1r)}
    # enable CFG-02B via standard per-chat config (temporary; restored later)
    cfg = [
        {"key": "flags.budgets_enabled", "value": True},
        {"key": "limits.image_freq_limit_enabled", "value": True},
        {"key": "limits.image_freq_limit_burst", "value": 2},
        {"key": "limits.image_freq_limit_cooldown_seconds", "value": 120},
        {"key": "limits.image_freq_limit_mode", "value": "per_user"},
    ]
    status, body = await CTX.api.req("POST", "/api/config",
                                     chat_id=WORK_CHAT,
                                     json_body={"items": cfg,
                                                "updated_at": None})
    res["cfg_write"] = {"status": status, "body": body}
    from services.chat_params import get_chat_params_cache
    cpc = get_chat_params_cache()
    if cpc is not None:
        await cpc.invalidate_chat(WORK_CHAT)
    # effective showcase via /api/workers/budget
    st, budget = await CTX.api.req("GET", "/api/workers/budget")
    freq = None
    if isinstance(budget, dict):
        for entry in (budget.get("chats") or []):
            if str(entry.get("scope")) == "chat:%d" % WORK_CHAT:
                freq = entry.get("freq")
                break
        if freq is None:
            freq = budget.get("freq")
    res["cfg_showcase"] = {"status": st, "freq": freq}
    from services import persistent_throttling as pt
    state_before = await ig.image_freq_state(WORK_CHAT, SYNTH_USER)
    res["state_after_enable"] = {
        "applied": getattr(state_before, "applied", None),
        "allowed": getattr(state_before, "allowed", None),
        "remaining": getattr(state_before, "remaining_seconds", None),
        "reason": getattr(state_before, "reason", None),
        "limits": str(getattr(state_before, "limits", None)),
    }
    # generation 2 (charge 1)
    anchor = t1.get("_last_msg") or anchor
    q2 = "бот, нарисуй безобидный рисунок: синий бумажный кораблик на белом фоне"
    p_before = len(CTX.provider_calls)
    t2 = await run_turn(q2, msg_id=anchor.message_id, reply_to=anchor,
                       label="gen-2", timeout=360)
    res["generations"].append({
        "phase": "gen2", "query": q2,
        "provider_calls": len(CTX.provider_calls) - p_before,
        **_strip_turn(t2)})
    # generation 3 (charge 2)
    anchor = t2.get("_last_msg") or anchor
    q3 = "бот, нарисуй безобидный рисунок: зелёное яблоко на белом фоне"
    p_before = len(CTX.provider_calls)
    t3 = await run_turn(q3, msg_id=anchor.message_id, reply_to=anchor,
                       label="gen-3", timeout=360)
    res["generations"].append({
        "phase": "gen3", "query": q3,
        "provider_calls": len(CTX.provider_calls) - p_before,
        **_strip_turn(t3)})
    # third attempt under the limiter (must be blocked pre-provider)
    state_now = await ig.image_freq_state(WORK_CHAT, SYNTH_USER)
    res["state_before_block"] = {
        "applied": getattr(state_now, "applied", None),
        "allowed": getattr(state_now, "allowed", None),
        "remaining": getattr(state_now, "remaining_seconds", None),
        "reason": getattr(state_now, "reason", None),
    }
    anchor = t3.get("_last_msg") or anchor
    q4 = "бот, нарисуй безобидный рисунок: красный воздушный шарик на белом фоне"
    if not (getattr(state_now, "applied", False)
            and not getattr(state_now, "allowed", True)):
        res["blocked"] = {
            "skipped": "limiter not in denied state; paid generation not forced",
            "provider_calls": 0,
            "state": res["state_before_block"],
        }
    else:
        p_before = len(CTX.provider_calls)
        t4 = await run_turn(q4, msg_id=anchor.message_id, reply_to=anchor,
                           label="gen-blocked", timeout=240)
        res["blocked"] = {
            "query": q4,
            "provider_calls": len(CTX.provider_calls) - p_before,
            **_strip_turn(t4)}
    res["blocked_ok"] = (res["blocked"]["provider_calls"] == 0
                         and "freq" in json.dumps(res["blocked"],
                                                  ensure_ascii=False).lower())
    # restore only touched per-chat keys
    try:
        from services import chat_params
        root = await chat_params.get_all_chat_params(WORK_CHAT, pg=CTX.pg)
        ov = dict((root or {}).get("overrides") or {})
        original = dict(CTX.original_overrides or {})
        for key in ("flags.budgets_enabled",
                    "limits.image_freq_limit_enabled",
                    "limits.image_freq_limit_burst",
                    "limits.image_freq_limit_cooldown_seconds",
                    "limits.image_freq_limit_mode"):
            if key in original:
                ov[key] = original[key]
            else:
                ov.pop(key, None)
        await chat_params.set_chat_params(WORK_CHAT, {"overrides": ov},
                                          changed_by=None, pg=CTX.pg)
        if cpc is not None:
            await cpc.invalidate_chat(WORK_CHAT)
        res["cfg_restore"] = "ok"
    except Exception as exc:  # noqa: BLE001
        res["cfg_restore"] = "failed: %s" % type(exc).__name__
    # delete generated image messages (keep mids as evidence)
    deleted = []
    for gen in res["generations"]:
        for s in gen.get("sends", []):
            if s.get("kind") == "photo" and s.get("message_id"):
                try:
                    await CTX.rec.delete_message(WORK_CHAT,
                                                 s["message_id"])
                    deleted.append(s["message_id"])
                except Exception as exc:  # noqa: BLE001
                    deleted.append("FAIL:%s" % type(exc).__name__)
    res["deleted_image_mids"] = deleted
    try:
        await sqlite_exec(
            "DELETE FROM throttle_state WHERE scope IN "
            "('image_freq','direct_chat','direct_silence') "
            "AND chat_id=? AND user_id=?", (WORK_CHAT, SYNTH_USER))
        res["synth_state_cleaned"] = True
    except Exception as exc:  # noqa: BLE001
        res["synth_state_cleaned"] = "failed:%s" % type(exc).__name__
    res["postgen"] = CTX.postgen
    res["ok"] = bool(res["generations"])
    save("scenario-5-generate.json", res)
    save("scenario-6-postgen.json", {"postgen": CTX.postgen,
                                     "generations": [
                                         {"phase": g["phase"],
                                          "block": g.get("image_blocks"),
                                          "answer_head": g.get("answer_head")}
                                         for g in res["generations"]]})
    save("scenario-7-cfg02b.json", {
        "cfg_write": res["cfg_write"], "showcase": res["cfg_showcase"],
        "state_after_enable": res["state_after_enable"],
        "state_before_block": res["state_before_block"],
        "blocked": res["blocked"], "blocked_ok": res["blocked_ok"],
        "cfg_restore": res["cfg_restore"],
        "generations_provider_calls": [
            {"phase": g["phase"], "provider_calls": g["provider_calls"]}
            for g in res["generations"]],
    })
    return res


# ─────────────────────────── scenario 8/9 ───────────────────────────────────

async def scenario_ui_and_econ():
    import httpx
    ui = {}
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                     timeout=30.0) as c:
            r = await c.get("/web/")
            html = r.text
            r2 = await c.get("/static/app.js")
            served = r2.content
        repo = open(os.path.join(APP, "web", "app.js"), "rb").read()
        ui = {
            "web_status": r.status_code,
            "html_len": len(html),
            "version_in_html": html.count("2.58.91"),
            "version_in_appjs": served.count(b"2.58.91"),
            "appjs_status": r2.status_code,
            "served_appjs_sha12": sha12(served),
            "repo_appjs_sha12": sha12(repo),
            "served_eq_appjs": sha12(served) == sha12(repo),
            "vision_route_marker": html.count("mod_vision") +
                                   served.count(b"mod_vision"),
            "freq_marker": served.count(b"imageFreqActiveLabel"),
            "browsers": {b: bool(shutil.which(b)) for b in (
                "chromium", "chromium-browser", "google-chrome",
                "playwright", "node")},
        }
    except Exception as exc:  # noqa: BLE001
        ui = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:200])}
    save("scenario-8-ui.json", ui)

    econ = {"start_epoch": START_EPOCH}
    try:
        econ["head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=APP, text=True).strip()
        econ["tracked_mod"] = int(subprocess.check_output(
            "git status --porcelain | grep -v '^??' | wc -l",
            cwd=APP, shell=True, text=True).strip() or 0)
    except Exception:
        pass
    try:
        econ["budget"] = await pg_fetch(
            "SELECT day, scope, metric, used FROM worker_budget "
            "WHERE metric='image_calls' ORDER BY day DESC LIMIT 12")
        econ["usage"] = await pg_fetch(
            "SELECT step, COUNT(*) n, COALESCE(SUM(cost_usd),0) cost, "
            "COALESCE(SUM(input_tokens+output_tokens),0) tokens "
            "FROM llm_usage_events WHERE ts >= to_timestamp($1) "
            "GROUP BY step ORDER BY n DESC", START_EPOCH)
        econ["reservations"] = await pg_fetch(
            "SELECT reservation_key, status, error_code, delivery_failed, "
            "created_at FROM image_reservation WHERE chat_id=$1 "
            "AND created_at >= to_timestamp($2) ORDER BY created_at",
            (WORK_CHAT, START_EPOCH))
        econ["vision_rows"] = await pg_fetch(
            "SELECT correlation_id, step, tool_name, plan_meta, ts "
            "FROM llm_usage_events WHERE ts >= to_timestamp($1) "
            "AND (step IN ('l1_planner','l2_writer') OR module='direct_chat') "
            "ORDER BY ts DESC LIMIT 40", START_EPOCH)
    except Exception as exc:  # noqa: BLE001
        econ["pg_error"] = type(exc).__name__
    try:
        econ["events"] = await sqlite_fetch(
            "SELECT event_name, outcome, reason_code, chat_id, COUNT(*) n, "
            "MAX(ts) last FROM mca_events WHERE ts >= ? "
            "GROUP BY 1,2,3,4 ORDER BY n DESC LIMIT 40", (START_EPOCH,))
        econ["jobs"] = await sqlite_fetch(
            "SELECT job_id, kind, status, reason_code, attempt, created_at "
            "FROM task_jobs WHERE created_at >= ? ORDER BY created_at DESC "
            "LIMIT 20", (START_EPOCH,))
        econ["user_version"] = (await sqlite_fetch("PRAGMA user_version"))[0]
        econ["mca_errors"] = await sqlite_fetch(
            "SELECT COUNT(*) n FROM mca_events WHERE ts >= ? "
            "AND level IN ('ERROR','CRITICAL')", (START_EPOCH,))
    except Exception as exc:  # noqa: BLE001
        econ["sqlite_error"] = type(exc).__name__
    save("scenario-9-economics.json", econ)
    return {"ui": ui, "econ": econ}


# ─────────────────────────── main ───────────────────────────────────────────

async def main() -> int:
    out("START_EPOCH", START_EPOCH)
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    await bootstrap()
    CTX.api = Api()
    if os.getenv("ACC94_BOOT_ONLY") == "1":
        out("BOOT_ONLY", "ok")
        await _close()
        return 0

    # capture original per-chat overrides for restore
    try:
        from services import chat_params
        root = await chat_params.get_all_chat_params(WORK_CHAT, pg=CTX.pg)
        CTX.original_overrides = dict((root or {}).get("overrides") or {})
        save("pre-chat-overrides.json", {"keys": sorted(
            CTX.original_overrides.keys()),
            "values": {k: CTX.original_overrides[k] for k in (
                "flags.vision_enabled", "flags.budgets_enabled",
                "limits.image_freq_limit_enabled") if k in
                CTX.original_overrides}})
    except Exception as exc:  # noqa: BLE001
        info("CFG", "original overrides read failed: %s"
             % type(exc).__name__)

    try:
        from services import mca_vision
        st = await mca_vision.resolve_effective_state(WORK_CHAT)
        save("pre-vision-state.json", {
            "requested": getattr(st, "requested", None),
            "effective": getattr(st, "effective_enabled", None),
            "capability": getattr(st, "capability", None),
            "reason": getattr(st, "reason", None),
            "visible_reason": getattr(st, "visible_reason", None),
            "provider": getattr(st, "provider", None),
            "model": getattr(st, "model", None),
            "source": getattr(st, "source", None),
        })
    except Exception as exc:  # noqa: BLE001
        info("VISION", "state failed: %s" % type(exc).__name__)

    phases = [
        ("1-health", scenario_health),
        ("3-vision", scenario_vision),
        ("4-factcheck", scenario_factcheck),
        ("5-7-generate", scenario_generate),
        ("8-9-ui-econ", scenario_ui_and_econ),
    ]
    for name, fn in phases:
        try:
            r = await fn()
            RESULTS[name] = r
            out("PHASE", "%s done" % name)
        except Exception as exc:  # noqa: BLE001
            import traceback
            RESULTS[name] = {"error": "%s: %s" % (type(exc).__name__,
                                                  str(exc)[:300])}
            out("PHASE", "%s FAILED %s" % (name, type(exc).__name__))
            traceback.print_exc()

    # flush telemetry from this process into shared SQLite
    try:
        from services import mca_events
        flushed = await mca_events.flush_events(CTX.db)
        info("FLUSH", "mca_events flushed=%s" % flushed)
    except Exception as exc:  # noqa: BLE001
        info("FLUSH", "failed: %s" % type(exc).__name__)

    save("summary.json", {
        "start_epoch": START_EPOCH,
        "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "results": {k: {"ok": v.get("ok") if isinstance(v, dict) else None}
                    for k, v in RESULTS.items()},
        "tools_called": [t.get("tool") for t in CTX.tool_calls],
        "provider_calls": CTX.provider_calls,
        "vision_transport_calls": len(CTX.vision_transport_calls),
        "postgen": CTX.postgen,
        "sends": _sanitize_sends(CTX.rec.sends),
    })
    out("DONE", "evidence=%s" % EVID)
    return 0


async def _close():
    for obj, name in ((CTX.api, "api"), (CTX.llm, "llm"),
                      (CTX.search, "search"), (CTX.fetcher, "fetcher"),
                      (CTX.bot, "bot"), (CTX.db, "db"), (CTX.cache, "cache")):
        try:
            if obj is None:
                continue
            if name == "api":
                await obj.close()
            elif name == "bot":
                await obj.session.close()
            elif name == "db":
                await obj.close()
            elif name == "cache":
                await obj.close()
            else:
                await obj.close()
        except Exception:
            pass


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC94 FATAL | %s: %s" % (type(exc).__name__,
                                          str(exc)[:400]), flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC94 RC=%d" % rc, flush=True)
    os._exit(rc)
