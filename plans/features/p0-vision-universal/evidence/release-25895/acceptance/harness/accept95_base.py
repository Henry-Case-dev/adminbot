# -*- coding: utf-8 -*-
"""ACCEPTANCE-95 — controlled live acceptance bootstrap for prod 2.58.95.

Same proven ACCEPTANCE-91/92/93/94 bootstrap: runs ON the production host,
imports the deployed modules, uses the real Telegram Bot (prod-faithful local
Bot API session), the real PG/SQLite stores and the real providers. No product
code is modified. Controlled-state writes are limited to the synthetic user
(990002001) and temporary per-chat settings that are restored exactly.

Evidence: /tmp/accept95/evidence/*.json (downloaded by the runner).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import time
import types
import urllib.parse

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
EVID = "/tmp/accept95/evidence"
os.makedirs(EVID, exist_ok=True)

START_EPOCH = int(time.time())
RESULTS: dict = {}
CAPTURED: list[str] = []

#: конфиг-ключи, которыми оперирует приёмка (снапшот/восстановление)
TOUCH_KEYS = (
    "flags.budgets_enabled",
    "flags.vision_enabled",
    "limits.image_daily_limit",
)


def out(tag: str, text) -> None:
    print("ACC95 %s | %s" % (tag, text), flush=True)


def info(tag: str, text) -> None:
    print("ACC95 %s INFO | %s" % (tag, text), flush=True)


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
                "IMAGE_ANALYSIS", "image_analysis", "[image-ctx]")):
            self.lines.append(msg[:1600])


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
            "text_head": head(text, 240),
            "text_full": str(text or "")[:6000],
            "text_len": len(str(text or "")),
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
            "caption_head": head(kwargs.get("caption"), 240),
            "reply_to": kwargs.get("reply_to_message_id"),
            "_msg": msg,
        })
        return msg

    async def send_document(self, chat_id, document, **kwargs):
        msg = await self._real.send_document(chat_id, document, **kwargs)
        self.sends.append({
            "kind": "document", "chat_id": int(chat_id),
            "message_id": getattr(msg, "message_id", None),
            "caption_head": head(kwargs.get("caption"), 240),
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
        self.vision_transport_calls: list[dict] = []
        self.original_overrides: dict = {}


CTX = Ctx()


def make_init_data(user_id: int = ADMIN_ID) -> str:
    from config.settings import settings
    token = settings.API_TOKEN or ""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHaccept95live",
        "user": json.dumps({"id": user_id, "first_name": "Accept95",
                            "username": "accept95"},
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
    # prod-faithful session (2.58.94 VISION-DL-FIX): bot.py builds exactly
    # this when flags.download_enabled/DOWNLOAD_ENABLED is ON.
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
    setup_direct_chat(CTX.svc, CTX.me.id, (CTX.me.username or "").lower())

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
        rec["result_head"] = text[:900]
        rec["result_len"] = len(text)
        try:
            payload = json.loads(text)
            if isinstance(payload, dict):
                rec["status"] = payload.get("status")
                rec["reason"] = payload.get("reason")
                rec["visible_reason"] = payload.get("visible_reason")
                rec["analysis_revision"] = payload.get("analysis_revision")
                rec["cache_hit"] = payload.get("cache_hit")
                rec["job_linked"] = payload.get("job_linked")
                rec["analysis_id"] = payload.get("analysis_id")
                rec["asset_id"] = payload.get("asset_id")
                rec["message_key"] = payload.get("message_key")
                rec["visual_description"] = str(
                    payload.get("visual_description") or "")[:4000]
                rec["visual_description_len"] = len(
                    str(payload.get("visual_description") or ""))
                rec["ocr_blocks"] = payload.get("ocr_blocks")
                rec["ocr_blocks_count"] = len(payload.get("ocr_blocks") or [])
                if str(name) == "recognize_image":
                    rec["result_head"] = json.dumps({
                        k: payload.get(k) for k in (
                            "status", "reason", "visible_reason",
                            "analysis_revision", "cache_hit", "asset_id",
                            "message_key", "job_linked", "out_of_scope",
                            "analysis_id")
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
                                 "block": str(block)[:4000]})
        return block

    ig.maybe_handle_keyword = maybe_spy

    # postgen spy (status/description length; no OCR text stored here)
    from services import postgen_vision
    orig_postgen = postgen_vision.analyze_generated_image

    async def postgen_spy(data, *, chat_id, correlation_id=None):
        outcome = await orig_postgen(data, chat_id=chat_id,
                                     correlation_id=correlation_id)
        CTX.postgen.append({
            "status": getattr(outcome, "status", None),
            "reason": getattr(outcome, "reason", None),
            "detail": getattr(outcome, "detail", None),
            "visible_reason": getattr(outcome, "visible_reason", None),
            "has_content": bool(getattr(outcome, "has_content", False)),
            "description_len": len(str(getattr(outcome,
                                               "visual_description", "") or "")),
            "description_head": str(getattr(outcome,
                                            "visual_description", "") or "")[:600],
            "ocr_blocks": len(getattr(outcome, "ocr_blocks", ()) or ()),
            "cache_hit": bool(getattr(outcome, "cache_hit", False)),
            "bytes_in": len(data or b""),
        })
        return outcome

    postgen_vision.analyze_generated_image = postgen_spy

    # vision transport spy: count real provider attempts + payload size only
    # (R17: no payload content stored).
    orig_transport = mca_vision._default_transport

    async def transport_spy(url, *, payload=None, headers=None, **kw):
        try:
            data_url = ""
            msgs = (payload or {}).get("messages") or []
            if msgs and isinstance(msgs[-1], dict):
                content = msgs[-1].get("content") or []
                for part in content if isinstance(content, list) else []:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        data_url = str((part.get("image_url") or {}).get("url")
                                       or "")
            CTX.vision_transport_calls.append({
                "ts": time.time(), "data_url_chars": len(data_url),
                "model": str((payload or {}).get("model") or "")[:60],
            })
        except Exception:
            CTX.vision_transport_calls.append({"ts": time.time(),
                                               "data_url_chars": -1})
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
    for key in ("target", "claim", "query", "person", "purpose", "mode",
                "asset_selector", "question"):
        if key in arguments:
            val = arguments[key]
            if isinstance(val, dict):
                out[key] = {k: val[k] for k in ("chat_id", "message_id")
                            if k in val}
            else:
                out[key] = str(val)[:220]
    return out


# ─────────────────────────── message helpers ────────────────────────────────

def make_user(uid=SYNTH_USER, first="Acceptance", username="accept95"):
    return types.SimpleNamespace(id=uid, first_name=first, last_name=None,
                                 username=username, is_bot=False)


def make_photo(file_id, unique, width, height, file_size):
    return types.SimpleNamespace(file_id=file_id, file_unique_id=unique,
                                 width=width, height=height,
                                 file_size=file_size)


def make_document(file_id, unique, mime_type, file_size, file_name):
    return types.SimpleNamespace(file_id=file_id, file_unique_id=unique,
                                 mime_type=mime_type, file_size=file_size,
                                 file_name=file_name)


def make_message(*, msg_id, text=None, caption=None, reply_to=None,
                 photo=None, document=None, chat_id=WORK_CHAT):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(id=chat_id, type="supergroup",
                                   title="acceptance"),
        message_id=msg_id,
        text=text,
        caption=caption,
        from_user=make_user(),
        reply_to_message=reply_to,
        photo=([photo] if photo is not None else None),
        document=document, sticker=None, animation=None,
        video=None, video_note=None, voice=None, audio=None,
        media_group_id=None,
        entities=(), caption_entities=(),
        forward_origin=None,
        date=int(time.time()),
    )


async def reset_synth_throttle():
    try:
        await sqlite_exec(
            "DELETE FROM throttle_state WHERE scope IN "
            "('direct_chat','direct_silence') AND chat_id=? AND user_id=?",
            (WORK_CHAT, SYNTH_USER))
    except Exception as exc:  # noqa: BLE001
        info("THROTTLE", "reset failed: %s" % type(exc).__name__)


async def reset_image_freq_throttle():
    try:
        await sqlite_exec(
            "DELETE FROM throttle_state WHERE scope='image_freq' "
            "AND chat_id=? AND user_id IN (?, 0)", (WORK_CHAT, SYNTH_USER))
    except Exception as exc:  # noqa: BLE001
        info("FREQ", "reset failed: %s" % type(exc).__name__)


async def run_turn(text, *, msg_id, reply_to=None, photo=None, document=None,
                   caption=None, label="turn", timeout=300):
    from handlers.direct_chat import direct_chat_handler
    await reset_synth_throttle()
    msg = make_message(msg_id=msg_id, text=text, caption=caption,
                       reply_to=reply_to, photo=photo, document=document)
    start = time.time()
    logs_before = len(CAP.lines)
    tools_before = len(CTX.tool_calls)
    blocks_before = len(CTX.image_blocks)
    postgen_before = len(CTX.postgen)
    sends_before = len(CTX.rec.sends)
    corr_before = len(CTX._corr)
    transport_before = len(CTX.vision_transport_calls)
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
            answer = s.get("text_full") or s.get("text_head") or ""
            break
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
        "vision_transport_calls": CTX.vision_transport_calls[
            transport_before:],
        "sends": sends,
        "answer": answer,
        "elapsed_s": round(time.time() - start, 2),
        "_last_msg": (CTX.rec.sends[-1].get("_msg")
                      if CTX.rec.sends else None),
    }


def _sanitize_sends(sends):
    out = []
    for s in sends:
        out.append({k: v for k, v in s.items() if not k.startswith("_")})
    return out


def _strip_turn(t):
    return {k: v for k, v in t.items() if not k.startswith("_")}


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


def _tool_ctx(label, *, chat_id=None, message_id=None, reply_to=None,
              user_id=SYNTH_USER):
    from services.tool_router import ToolContext
    return ToolContext(chat_id or WORK_CHAT, "", bot=CTX.rec, user_id=user_id,
                       correlation_id=label,
                       media_target_message_id=(int(message_id)
                                                if message_id is not None
                                                else None),
                       reply_to_message_id=(int(reply_to)
                                            if reply_to is not None else None))


async def latest_anchor(fallback=None):
    if CTX.rec.sends:
        m = CTX.rec.sends[-1].get("_msg")
        if m is not None:
            return m
    return fallback


# ─────────────────────────── config helpers ─────────────────────────────────

def pick_cfg(cfg, keys):
    items = cfg.get("items") if isinstance(cfg, dict) else None
    keep = []
    if isinstance(items, list):
        for it in items:
            if str(it.get("key")) in keys:
                keep.append({k: it.get(k) for k in (
                    "key", "value", "global_value", "chat_source",
                    "per_chat", "type", "description", "title", "group")
                    if k in it})
    return keep


def cfg_map(items):
    return {str(it.get("key")): it.get("value") for it in (items or [])}


async def set_cfg(items, tag, *, chat_id=WORK_CHAT):
    import httpx
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000",
                                 timeout=60.0) as c:
        r = await c.post("/api/config", headers={
            "X-Telegram-Init-Data": make_init_data(),
            "X-Chat-Id": str(chat_id)},
            json={"items": items, "updated_at": None})
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
    await invalidate_caches()
    out("CFG", "%s http=%s body=%s" % (tag, r.status_code,
                                       json.dumps(body,
                                                  ensure_ascii=False)[:300]))
    return {"http": r.status_code, "body": body}


async def invalidate_caches():
    try:
        from services.chat_params import get_chat_params_cache
        cpc = get_chat_params_cache()
        if cpc is not None:
            await cpc.invalidate_chat(WORK_CHAT)
    except Exception as exc:  # noqa: BLE001
        out("CACHE", "invalidate failed: %s" % type(exc).__name__)
    try:
        from services import capability_registry as caps
        caps.invalidate("image_generation", WORK_CHAT, reason="accept95")
        caps.invalidate("image_understanding", WORK_CHAT, reason="accept95")
    except Exception:
        pass


async def restore_overrides(keys, tag="restore"):
    """Точное восстановление per-chat overrides по снапшоту в
    CTX.original_overrides (наличие/значение/удаление)."""
    from services import chat_params
    root = await chat_params.get_all_chat_params(WORK_CHAT, pg=CTX.pg)
    ov = dict((root or {}).get("overrides") or {})
    changed = {}
    for key in keys:
        if key in CTX.original_overrides:
            if ov.get(key) != CTX.original_overrides[key]:
                ov[key] = CTX.original_overrides[key]
                changed[key] = CTX.original_overrides[key]
        else:
            if key in ov:
                changed[key] = "<removed>"
                ov.pop(key, None)
    if changed:
        await chat_params.set_chat_params(WORK_CHAT, {"overrides": ov},
                                         changed_by=None, pg=CTX.pg)
    await invalidate_caches()
    out("RESTORE", "%s changed=%s" % (tag, json.dumps(changed,
                                                      ensure_ascii=False)))
    return changed


async def close_all():
    for obj, name in ((CTX.api if hasattr(CTX, "api") else None, "api"),
                      (CTX.llm, "llm"), (CTX.search, "search"),
                      (CTX.fetcher, "fetcher"), (CTX.bot, "bot"),
                      (CTX.db, "db"), (CTX.cache, "cache")):
        try:
            if obj is None:
                continue
            if name == "bot":
                await obj.session.close()
            else:
                await obj.close()
        except Exception:
            pass
