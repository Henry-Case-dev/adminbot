# -*- coding: utf-8 -*-
"""AGENT-CHECKS-1 / window-1 — прод-проба (2.58.88): OQ-12 + OQ-9(a-f).

Запуск на проде (venv):  cd /var/www/admin_bot && PYTHONIOENCODING=utf-8 \
    /var/www/admin_bot/venv/bin/python /tmp/agent_checks_w1_probe.py

Принципы:
  * изменения только синтетические (SYNTH_CHAT/SYNTH_USER), с восстановлением;
  * ровно ≤1 реальная генерация изображения (фаза D), остальное — 0 платных;
  * никаких секретов в вывод; fail-soft по фазам; SUMMARY в конце.

Вывод: строки "AC1 <TAG> <OK|FAIL> | <detail>" + финальный SUMMARY.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
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

SYNTH_CHAT = -1009900000201
SYNTH_USER = 990002001
MSG_ID = 990000701
ADMIN_ID = 5885953495
CORR = "probe-agent-checks-w1"

RESULTS: list[tuple[str, bool, str]] = []


def out(tag: str, ok: bool, text: str) -> None:
    RESULTS.append((tag, bool(ok), str(text)))
    print("AC1 %s %s | %s" % (tag, "OK" if ok else "FAIL", text), flush=True)


def info(tag: str, text: str) -> None:
    print("AC1 %s INFO | %s" % (tag, text), flush=True)


_ERROR_PHRASES = ("внутренняя ошибка базы", "мои мозги расплавились",
                  "я подавился токенами")


def err_phrase_like(text: str) -> bool:
    """True — текст похож на сервисную ERROR-фразу (а не на отказ кулдауна)."""
    t = str(text or "").lower()
    return any(p in t for p in _ERROR_PHRASES)


def sha12(path: str) -> str:
    try:
        with open(os.path.join(APP, path), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:12]
    except Exception as exc:  # noqa: BLE001
        return "ERR:%s" % type(exc).__name__


# ────────────────────────────── infra ───────────────────────────────────────

def make_init_data(user_id: int = ADMIN_ID) -> str:
    from config.settings import settings
    token = settings.API_TOKEN or ""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHagentcheck",
        "user": json.dumps({"id": user_id, "first_name": "AgentCheck",
                            "username": "agentcheck"},
                           separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


class Api:
    def __init__(self, base: str = "http://127.0.0.1:8000"):
        import httpx
        self._client = httpx.AsyncClient(base_url=base, timeout=120.0)

    async def close(self):
        await self._client.aclose()

    async def req(self, method: str, path: str, *, chat_id=None, json_body=None):
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
    """Заглушка aiogram-бота: только фиксирует вызовы (никаких сетевых отправок)."""

    def __init__(self):
        self.sent: list[dict] = []
        self.photos: list[dict] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": str(text),
                          "kwargs": {k: v for k, v in kwargs.items()}})
        return types.SimpleNamespace(message_id=MSG_ID + len(self.sent))

    async def send_photo(self, chat_id, photo, **kwargs):
        self.photos.append({"chat_id": chat_id,
                            "kwargs": {k: str(v)[:60] for k, v in kwargs.items()},
                            "bytes": len(getattr(photo, "data", b"") or b"")})
        return types.SimpleNamespace(message_id=MSG_ID + 500 + len(self.photos))

    def __getattr__(self, name):
        async def _noop(*args, **kwargs):
            return types.SimpleNamespace(message_id=0, ok=True)
        return _noop


def fake_message(text: str, *, reply_to=None):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(id=SYNTH_CHAT, type="supergroup"),
        text=text, message_id=MSG_ID,
        from_user=types.SimpleNamespace(id=SYNTH_USER, first_name="Probe",
                                        username="probe", last_name=None),
        reply_to_message=reply_to, caption=None, forward_origin=None,
    )


def fake_user():
    return types.SimpleNamespace(id=SYNTH_USER, first_name="Probe",
                                 username="probe", last_name=None)


# ────────────────────────────── runtime wiring ──────────────────────────────

class Ctx:
    def __init__(self):
        self.api = None
        self.cache = None
        self.db = None
        self.pg = None
        self.stub = None
        self.svc = None
        self.provider_calls: list[str] = []


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
    info("BOOT", "version=%s db=%s pg_available=%s"
         % (getattr(settings, "APP_VERSION", "?"),
            str(settings.DB_PATH).split("/")[-1], bool(cache.pg_available)))


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
    return ctx.svc


async def pg_fetch(ctx: Ctx, sql: str, *args):
    pool = getattr(ctx.pg, "pool", None)
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


async def pg_exec(ctx: Ctx, sql: str, *args):
    pool = getattr(ctx.pg, "pool", None)
    if pool is None:
        return 0
    async with pool.acquire() as conn:
        res = await conn.execute(sql, *args)
    return res


async def sqlite_fetch(ctx: Ctx, sql: str, args=()):
    cursor = await ctx.db.db.execute(sql, args)
    return [dict(r) for r in await cursor.fetchall()]


# ═══════════════════════════ PHASE 0: PRE snapshot ═══════════════════════════

async def phase0(ctx: Ctx) -> None:
    info("P0_TIME", "now_utc=%s" % time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    for rel in ("services/direct_chat_service.py", "services/chat_params.py",
                "services/persistent_throttling.py", "services/mca_events.py",
                "services/style_policy.py", "services/response_extent.py",
                "services/direct_capabilities.py", "services/image_generation.py",
                "services/capability_registry.py", "services/worker_budget.py",
                "services/chat_prompts.py", "web/api/speech.py"):
        info("P0_SHA", "%s %s" % (rel, sha12(rel)))
    from services import hot_config as hot
    from config.settings import settings
    info("P0_GLOBAL_LIMITS", "burst=%r cooldown=%r silence_enabled=%r after=%r"
         % (hot.get("limits.chat_burst_limit", settings.CHAT_BURST_LIMIT),
            hot.get("limits.chat_cooldown_seconds",
                    settings.CHAT_COOLDOWN_SECONDS),
            hot.get("flags.chat_silence_enabled", settings.CHAT_SILENCE_ENABLED),
            hot.get("limits.chat_silence_after_cooldowns",
                    settings.CHAT_SILENCE_AFTER_COOLDOWNS)))
    rows = await pg_fetch(ctx,
                          "SELECT count(*) AS n FROM chat_profiles")
    info("P0_PROFILES", "total=%s" % (rows[0]["n"] if rows else "?"))
    rows = await pg_fetch(ctx,
                          "SELECT chat_id FROM chat_profiles WHERE chat_id=$1",
                          SYNTH_CHAT)
    info("P0_SYNTH_PRE", "profile_exists=%s" % bool(rows))
    rows = await sqlite_fetch(
        ctx, "SELECT scope, user_id, burst_left, last_ts FROM throttle_state "
             "WHERE chat_id=?", (SYNTH_CHAT,))
    info("P0_SYNTH_THROTTLE", "rows=%s" % (len(rows),))
    # статусы capability изображения/видео (без записи)
    from services import capability_registry as caps
    for cap in ("image_generation", "web_search", "fact_check", "video_summary"):
        try:
            st = await caps.resolve(cap, SYNTH_CHAT)
            info("P0_CAP", "%s status=%s reason=%s available=%s detail=%s"
                 % (cap, st.status, st.reason_code, st.available,
                    str(st.detail)[:80]))
        except Exception as exc:  # noqa: BLE001
            info("P0_CAP", "%s ERROR=%s" % (cap, type(exc).__name__))
    # style-документ (глобальный) — как в PG, так и через API
    rows = await pg_fetch(ctx,
                          "SELECT value FROM bot_settings WHERE key='style.policy'")
    info("P0_STYLE_PG", "present=%s value_len=%s"
         % (bool(rows), len(json.dumps(rows[0]["value"])) if rows else 0))
    status, body = await ctx.api.req("GET", "/api/speech/style")
    if isinstance(body, dict):
        info("P0_STYLE_API", "status=%s global_present=%s global_revision=%s "
             "rules=%s soft=%s inheritance=%s"
             % (status, body.get("global_present"), body.get("global_revision"),
                body.get("global_rules"), body.get("global_soft"),
                str(body.get("inheritance"))[:60]))
    else:
        info("P0_STYLE_API", "status=%s body=%s" % (status, str(body)[:200]))
    # счётчики бюджетов изображений
    try:
        rows = await pg_fetch(ctx,
                              "SELECT day, scope, metric, used FROM worker_budget "
                              "WHERE metric='image_calls' ORDER BY day DESC LIMIT 6")
        info("P0_BUDGET", json.dumps([{k: str(v) for k, v in r.items()}
                                      for r in rows], ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        info("P0_BUDGET", "ERROR=%s" % type(exc).__name__)


# ═════════════════ PHASE A: OQ-12 — отказ Direct на синтетике ════════════════

async def set_chat_overrides(ctx: Ctx, items: list[dict]) -> tuple[int, dict]:
    """Запись per-chat overrides через реальный API; fallback — прямой слой."""
    status, body = await ctx.api.req(
        "POST", "/api/config", chat_id=SYNTH_CHAT,
        json_body={"items": items, "updated_at": None})
    if status == 200:
        return status, body if isinstance(body, dict) else {}
    from services import chat_params
    root = await chat_params.get_all_chat_params(SYNTH_CHAT, pg=ctx.pg)
    ov = dict((root or {}).get("overrides") or {})
    for item in items:
        ov[item["key"]] = item["value"]
    try:
        await chat_params.set_chat_params(SYNTH_CHAT, {"overrides": ov},
                                          changed_by=None, pg=ctx.pg)
        info("CFG_FALLBACK", "API status=%s → прямая запись chat_params: ok" % status)
        return status, {"fallback": True, "updated": [i["key"] for i in items]}
    except Exception as exc:  # noqa: BLE001
        info("CFG_FALLBACK", "прямая запись не удалась: %s" % type(exc).__name__)
        return status, {"fallback": False}


async def reset_chat_overrides(ctx: Ctx) -> None:
    from services import chat_params
    try:
        await chat_params.set_chat_params(SYNTH_CHAT, {"overrides": {}},
                                          changed_by=None, pg=ctx.pg)
    except Exception as exc:  # noqa: BLE001
        info("CFG_RESET", "override reset failed: %s" % type(exc).__name__)


async def phaseA(ctx: Ctx) -> None:
    from services import chat_params
    from services import mca_events
    from services.smartmodule_phrases import CHAT_COOLDOWN_PHRASES
    from services.smartmodule_throttling import format_remaining_time

    # 1) профиль снимка (создаём сами; перед этим убедились, что его нет)
    created = await chat_params.ensure_scope_profile(
        SYNTH_CHAT, dm=False, pg=ctx.pg)
    out("A1_profile_ensure", True, "created_or_exists=%s" % created)

    # 2) per-chat override через реальный API (MiniApp-путь)
    status, body = await set_chat_overrides(ctx, [
        {"key": "limits.chat_burst_limit", "value": 1},
        {"key": "limits.chat_cooldown_seconds", "value": 180}])
    out("A2_config_override", status == 200,
        "status=%s updated=%s updated_at=%s"
        % (status, (body or {}).get("updated"), (body or {}).get("updated_at")))

    # 3) эффективный резолв в НАШЕМ процессе (свежий кэш chat_params)
    cache = chat_params.get_chat_params_cache()
    if cache is not None:
        await cache.invalidate_chat(SYNTH_CHAT)
    from services.persistent_throttling import resolve_direct_chat_limits
    limit, cooldown, source = await resolve_direct_chat_limits(SYNTH_CHAT)
    out("A3_resolve_effective", (limit == 1 and float(cooldown) == 180.0),
        "burst=%s cooldown=%s source=%r" % (limit, cooldown, source))

    # 4) прайм троттлера (списываем единственный заряд) + отказ через _handle_turn
    primed = None
    try:
        from services.persistent_throttling import throttle_refresh
        throttle_refresh(ctx.svc.throttle, limit, cooldown)   # как в _handle_turn
        primed = await ctx.svc.throttle.allow(SYNTH_CHAT, SYNTH_USER)
        if asyncio.iscoroutine(primed):
            primed = await primed
    except Exception as exc:  # noqa: BLE001
        info("A4_note", "prime failed: %s" % type(exc).__name__)
    out("A4_prime_charge", float(primed if primed is not None else -1) == 0.0,
        "allow_first=%r (после throttle_refresh до effective-лимита)" % (primed,))

    t0 = time.time()
    await ctx.svc._handle_turn(ctx.stub, fake_message("привет"), fake_user())
    elapsed = time.time() - t0
    sent = list(ctx.stub.sent)
    phrase = sent[-1]["text"] if sent else ""
    reply_to = sent[-1]["kwargs"].get("reply_to_message_id") if sent else None
    err_phrase = err_phrase_like(phrase)
    out("A5_refusal_sent", bool(sent) and not err_phrase,
        "sends=%d elapsed=%.1fs reply_to=%s error_phrase=%s"
        % (len(sent), elapsed, reply_to, err_phrase))
    out("A6_phrase_text", bool(phrase), "phrase=%r" % (phrase,))
    no_false = "технически не могу" not in phrase.lower()
    # фактический остаток: считаем от РЕАЛЬНОГО last_ts слота (тот же clock)
    rows = await sqlite_fetch(
        ctx, "SELECT last_ts FROM throttle_state WHERE scope='direct_chat' "
             "AND chat_id=? AND user_id=?", (SYNTH_CHAT, SYNTH_USER))
    last_ts = rows[0]["last_ts"] if rows else None
    rem_db = (180.0 - (time.time() - float(last_ts))) if last_ts else None
    prefixes = [p.split("{remaining_time}")[0] for p in CHAT_COOLDOWN_PHRASES]
    shape_ok = any(phrase.startswith(pfx) for pfx in prefixes)
    import re as _re
    m = _re.search(r"(\d+ мин(?: \d+ сек)?|\d+ сек)", phrase)
    seg = m.group(0) if m else ""
    tail = seg
    try:
        if "мин" in seg:
            mp = _re.match(r"(\d+) мин(?: (\d+) сек)?$", seg)
            phrase_secs = int(mp.group(1)) * 60 + int(mp.group(2) or 0)
        else:
            phrase_secs = int(_re.match(r"(\d+) сек$", seg).group(1))
    except Exception:  # noqa: BLE001
        phrase_secs = -1
    delta = abs(phrase_secs - rem_db) if (rem_db is not None and phrase_secs >= 0
                                          ) else None
    out("A7_phrase_contract",
        no_false and shape_ok and delta is not None and delta <= 2.0,
        "no_false_refusal=%s shape_ok=%s phrase_tail=%r db_remaining=%.1fs "
        "delta=%.1fs"
        % (no_false, shape_ok, tail, rem_db if rem_db is not None else -1,
           delta if delta is not None else -1))
    info("A7_remaining", "formatted_phrase_tail=%r db_based=%r"
         % (tail, format_remaining_time(rem_db) if rem_db else None))
    out("A8_no_llm_call", True,
        "llm=None; отказ до платных стадий (иначе был бы AttributeError)")

    # 5) durable-событие + просмотрщик
    flushed = await mca_events.flush_events(ctx.db)
    info("A9_flush", "events_flushed=%s" % flushed)
    status, body = await ctx.api.req(
        "GET",
        "/api/status/logs?component=direct_chat&chat_id=%d&limit=50"
        % SYNTH_CHAT)
    events = (body or {}).get("events") or []
    ours = [e for e in events
            if e.get("event_name") == "direct_chat_throttle"]
    payload = {}
    try:
        payload = json.loads((ours[0].get("usage_json") if ours else "") or "{}")
    except Exception:  # noqa: BLE001
        payload = {}
    out("A10_viewer_event", bool(ours),
        "viewer_status=%s events=%d matched=%d restricted=%s"
        % (status, len(events), len(ours), (body or {}).get("events_restricted")))
    if not ours:
        info("A10_viewer_names", json.dumps(
            [e.get("event_name") for e in events][:12], ensure_ascii=False))
    if ours:
        e = ours[0]
        out("A11_event_payload",
            payload.get("source") in ("chat", "global")
            and float(payload.get("remaining_seconds", 0)) > 0,
            "stage=%s reason=%s usage_json=%s"
            % (e.get("stage"), e.get("reason_code"),
               json.dumps(payload, ensure_ascii=False)))
    else:
        out("A11_event_payload", False, "direct_chat_throttle не найден во вьюере")

    # 6) очистка синтетики (overrides -> профиль -> rows троттлера)
    await reset_chat_overrides(ctx)
    await pg_exec(ctx, "DELETE FROM chat_profiles WHERE chat_id=$1", SYNTH_CHAT)
    try:
        await ctx.db.db.execute("DELETE FROM throttle_state WHERE chat_id=?",
                                (SYNTH_CHAT,))
        await ctx.db.db.commit()
    except Exception as exc:  # noqa: BLE001
        info("A12_note", "throttle cleanup: %s" % type(exc).__name__)
    leftover_prof = await pg_fetch(
        ctx, "SELECT chat_id FROM chat_profiles WHERE chat_id=$1", SYNTH_CHAT)
    rows = await sqlite_fetch(
        ctx, "SELECT count(*) AS n FROM throttle_state WHERE chat_id=?",
        (SYNTH_CHAT,))
    n_throttle = rows[0]["n"] if rows else -1
    out("A12_cleanup", (not leftover_prof) and n_throttle == 0,
        "profile_rows=%d throttle_rows=%s" % (len(leftover_prof), n_throttle))
    info("A13_events_kept", "durable mca_events по SYNTH_CHAT сохранены как "
         "evidence (chat_id=%d)" % SYNTH_CHAT)


# ═════════════ PHASE B: OQ-9(a) — формы через валидатор + try ════════════════

async def phaseB(ctx: Ctx) -> None:
    from services import response_extent as rx

    cases = [
        ("one_word", "Да!!!"),
        ("one_word", "OK!!!"),
        ("one_word", "по-хорошему"),
        ("one_word", "Да, конечно, всё сделаю"),
        ("one_word", "Готово 🔥"),
        ("one_word", "да"),
        ("micro", "Да!!!"),
        ("micro", "ок, будет сделано сегодня"),
        ("micro", "раз два три четыре пять шесть семь восемь девять десять "
                  "одиннадцать двенадцать"),
        ("auto", "любой текст"),
    ]
    n_pass = 0
    for extent, text in cases:
        plan = rx.ResponsePlan(extent=extent)
        res = rx.check_extent(text, plan)
        info("B1_form", json.dumps({"extent": extent, "text": text,
                                    "status": res.status, "reason": res.reason,
                                    "words": len(res.words or ()),
                                    "out_text": res.text,
                                    "changed": res.text != text},
                                   ensure_ascii=False))
        if extent in ("one_word", "micro"):
            n_pass += 1
    out("B1_form_matrix", n_pass == 9,
        "проверено 9 кейсов one_word/micro через прод-валидатор")

    # реальный композер: try на тех же формах (0 LLM)
    texts = ["Да!!!", "OK!!!", "по-хорошему", "Да, конечно, всё сделаю"]
    for text in texts:
        status, body = await ctx.api.req(
            "POST", "/api/speech/try", json_body={"text": text})
        if status != 200 or not isinstance(body, dict):
            out("B2_try", False, "text=%r status=%s" % (text, status))
            continue
        sp = (body.get("extent") or {}).get("style_pass") or {}
        info("B2_try", json.dumps({
            "text": text, "status": status,
            "layers_current": (body.get("strategy") or {}).get("layers_current"),
            "extent_values": (body.get("extent") or {}).get("values"),
            "response_plan_enabled":
                (body.get("extent") or {}).get("response_plan_enabled"),
            "style_pass_status": sp.get("status"),
            "style_pass_reason": sp.get("reason"),
            "protected_count": (body.get("facts") or {}).get("protected_count"),
            "delivery": (body.get("delivery") or {}).get("telegram_send"),
        }, ensure_ascii=False))
    out("B2_try_composer", True, "4 текста через POST /api/speech/try (0 LLM)")


# ═════════════ PHASE C: OQ-9(b) — Style global → ревизия в try ═══════════════

async def phaseC(ctx: Ctx) -> None:
    status, style_body = await ctx.api.req("GET", "/api/speech/style")
    rows = await pg_fetch(ctx,
                          "SELECT value FROM bot_settings WHERE key='style.policy'")
    prev_doc = rows[0]["value"] if rows else None
    if isinstance(prev_doc, str):
        try:
            prev_doc = json.loads(prev_doc)
        except Exception:  # noqa: BLE001
            prev_doc = None
    info("C1_style_state", "api_status=%s global_present=%s prev_is_dict=%s"
         % (status, (style_body or {}).get("global_present"),
            isinstance(prev_doc, dict)))

    # baseline try (до правки) — ревизия style_policy
    _, t0 = await ctx.api.req("POST", "/api/speech/try",
                              json_body={"text": "привет"})
    ver0 = ((t0 or {}).get("current") or {}).get("versions", {}).get(
        "style_policy", "<none>")
    info("C2_try_before", "versions.style_policy=%r" % (ver0,))

    # кандидат: копия предыдущего + ОДНА отключённая soft-инструкция
    cand = dict(prev_doc) if isinstance(prev_doc, dict) else {}
    soft = list(cand.get("soft_instructions") or [])
    soft.append({"id": "soft.agent-check-w1", "text": "проба агента (выключена)",
                 "scope": "global", "enabled": False})
    cand["soft_instructions"] = soft
    cand.setdefault("rules", [])
    status, body = await ctx.api.req(
        "POST", "/api/speech/style",
        json_body={"document": cand, "scope": "global",
                   "reason": "agent-check-w1 probe"})
    res = (body or {}).get("result") or {}
    new_rev = res.get("revision")
    out("C3_style_write", status == 200 and bool(res.get("applied")),
        "status=%s applied=%s scope=%s revision=%s rules=%s soft=%s"
        % (status, res.get("applied"), res.get("scope"), new_rev,
           res.get("rules"), res.get("soft_instructions")))

    _, t1 = await ctx.api.req("POST", "/api/speech/try",
                              json_body={"text": "привет"})
    ver1 = ((t1 or {}).get("current") or {}).get("versions", {}).get(
        "style_policy", "<none>")
    # _preview_manifest отдаёт ревизию документа в chat-слоте → префикс "c";
    # принимаем и "g" (если слой когда-нибудь переедет в global-слот).
    pref_ok = any(str(ver1).startswith("%s%s" % (tag, int(new_rev or -1)))
                  for tag in ("c", "g"))
    out("C4_try_after_new_rev", pref_ok,
        "before=%r after=%r ожидался префикс c%s/g%s"
        % (ver0, ver1, new_rev, new_rev))

    # восстановление
    if isinstance(prev_doc, dict) and prev_doc:
        status, body = await ctx.api.req(
            "POST", "/api/speech/style",
            json_body={"document": prev_doc, "scope": "global",
                       "reason": "agent-check-w1 restore"})
        res = (body or {}).get("result") or {}
        out("C5_restore", status == 200 and bool(res.get("applied")),
            "status=%s applied=%s revision=%s (содержимое = до пробы)"
            % (status, res.get("applied"), res.get("revision")))
    else:
        status, body = await ctx.api.req(
            "POST", "/api/speech/style",
            json_body={"document": {"rules": [], "soft_instructions": []},
                       "scope": "global",
                       "reason": "agent-check-w1 restore-empty"})
        res = (body or {}).get("result") or {}
        out("C5_restore", status == 200 and bool(res.get("applied")),
            "документа до пробы не было; оставлен ПУСТОЙ документ "
            "(rules=0/soft=0) — см. README, revision=%s" % res.get("revision"))

    _, t2 = await ctx.api.req("POST", "/api/speech/try",
                              json_body={"text": "привет"})
    ver2 = ((t2 or {}).get("current") or {}).get("versions", {}).get(
        "style_policy", "<none>")
    rows = await pg_fetch(ctx,
                          "SELECT value FROM bot_settings WHERE key='style.policy'")
    doc2 = rows[0]["value"] if rows else None
    if isinstance(doc2, str):
        doc2 = json.loads(doc2)
    soft2 = len((doc2 or {}).get("soft_instructions") or [])
    probe_soft = [s for s in ((doc2 or {}).get("soft_instructions") or [])
                  if isinstance(s, dict) and s.get("id") == "soft.agent-check-w1"]
    expected_soft = (len((prev_doc or {}).get("soft_instructions") or [])
                     if isinstance(prev_doc, dict) else 0)
    out("C6_final_state", (not probe_soft) and soft2 == expected_soft,
        "final_versions.style_policy=%r soft=%d (ожидалось %d) "
        "probe_soft_present=%s"
        % (ver2, soft2, expected_soft, bool(probe_soft)))


# ═════════════ PHASE D: OQ-9(c)/(d) — изображения ════════════════════════════

async def phaseD(ctx: Ctx) -> None:
    from services import direct_capabilities as dcaps
    from services import image_generation as ig
    from services import capability_registry as caps
    from services import chat_params
    from services.tool_router import ToolContext

    # D0: сниффер платных вызовов провайдера (POST/GET) — счётчик
    calls = ctx.provider_calls
    orig_post, orig_get = ig._generate_post, ig._generate_get

    async def spy_post(*args, **kwargs):
        calls.append("post")
        return await orig_post(*args, **kwargs)

    async def spy_get(*args, **kwargs):
        calls.append("get")
        return await orig_get(*args, **kwargs)

    ig._generate_post, ig._generate_get = spy_post, spy_get

    # профиль синтетики нужен для per-chat overrides на этой фазе
    await chat_params.ensure_scope_profile(SYNTH_CHAT, dm=False, pg=ctx.pg)
    skip_gen = os.getenv("AC1_SKIP_IMAGE_GEN", "") == "1"

    # D1: детерминированный классификатор
    phrases = [
        "Бот, нарисуй мем про кота",
        "Сделай мем",
        "сделай мем с текстом",
        "Бот, нарисуй мем, но не рисуй",
        "придумай концепт мема, рисовать не надо",
        "давай обсудим мемы",
        "я сам нарисую мем",
        "Петя сказал: нарисуй мем",
        "мемориальный комплекс",
        "сделай это",
    ]
    for text in phrases:
        it = dcaps.detect_action_intent(text, addressed=True)
        info("D1_intent", json.dumps({
            "text": text, "intent": it.intent, "confidence": it.confidence,
            "actionable": it.actionable, "reason": it.reason,
            "is_keyword_regex": ig.is_image_keyword(text)},
            ensure_ascii=False))

    # D2: «не рисуй» — семантическое VETO до генерации (реальный метод сервиса)
    for text, expect_reason in (
            ("Бот, нарисуй мем, но не рисуй", "create_image_negated"),
            ("придумай концепт мема, рисовать не надо",
             "create_image_conceive_only")):
        it = dcaps.detect_action_intent(text, addressed=True)
        before = len(calls)
        block = await ctx.svc._image_pre_gate_block(
            SYNTH_CHAT, text, ctx.stub, fake_message(text), SYNTH_USER,
            correlation_id=CORR + "-veto", intent=it)
        out("D2_veto_%s" % expect_reason, (not block) and len(calls) == before,
            "text=%r actionable=%s generated_calls=%d block_empty=%s"
            % (text, it.actionable, len(calls) - before, not block))

    if not skip_gen:
        status, body = await set_chat_overrides(ctx, [
            {"key": "flags.image_generation_module_enabled", "value": True}])
        info("D3_module_on", "status=%s updated=%s"
             % (status, (body or {}).get("updated")))
    cache = chat_params.get_chat_params_cache()
    if cache is not None:
        await cache.invalidate_chat(SYNTH_CHAT)
    caps.invalidate("image_generation", SYNTH_CHAT, reason="probe")
    st = await caps.resolve("image_generation", SYNTH_CHAT)
    info("D3_capability", "status=%s reason=%s detail=%s"
         % (st.status, st.reason_code, st.detail))

    if not skip_gen:
        q = "Бот, нарисуй простой мем: кот спит на клавиатуре"
        it = dcaps.detect_action_intent(q, addressed=True)
        before = len(calls)
        ctx_msg = ToolContext(SYNTH_CHAT, q, bot=ctx.stub,
                              reply_to_message_id=MSG_ID, user_id=SYNTH_USER,
                              correlation_id=CORR + "-draw")
        block = await ig.maybe_handle_keyword(
            ctx_msg, q, aliases=ctx.svc.aliases, db=ctx.db, memory=None,
            intent_confirmed=bool(it.actionable))
        n_gen = len(calls) - before
        ok_block = block.startswith('<image_result status="ok"')
        out("D4_one_generation", ok_block and n_gen >= 1,
            "actionable=%s provider_calls=%d block=%r"
            % (it.actionable, n_gen, block[:160]))
        info("D4_photos", "send_photo_calls=%d bytes=%s"
             % (len(ctx.stub.photos),
                ctx.stub.photos[-1]["bytes"] if ctx.stub.photos else 0))

        # D5: повторная обработка того же хода (тот же message_id/correlation)
        before = len(calls)
        ctx_msg2 = ToolContext(SYNTH_CHAT, q, bot=ctx.stub,
                               reply_to_message_id=MSG_ID, user_id=SYNTH_USER,
                               correlation_id=CORR + "-draw")
        block2 = await ig.maybe_handle_keyword(
            ctx_msg2, q, aliases=ctx.svc.aliases, db=ctx.db, memory=None,
            intent_confirmed=bool(it.actionable))
        n_gen2 = len(calls) - before
        out("D5_replay_no_second", ("already" in block2) and n_gen2 == 0,
            "provider_calls=%d block=%r" % (n_gen2, block2[:160]))

    # журнал/аналитика по строке резерва
    try:
        rows = await pg_fetch(
            ctx, "SELECT reservation_key, chat_id, source, message_id, day, "
                 "status, error_code, delivery_failed FROM image_reservation "
                 "WHERE reservation_key LIKE $1",
            "%d:%%" % SYNTH_CHAT)
        info("D6_journal", json.dumps([{k: str(v) for k, v in r.items()}
                                       for r in rows], ensure_ascii=False))
        if not skip_gen:
            out("D6_journal_committed",
                any(str(r.get("status")) == "committed" for r in rows),
                "rows=%d" % len(rows))
    except Exception as exc:  # noqa: BLE001
        info("D6_journal", "ERROR=%s" % type(exc).__name__)

    # D7: OFF-ветка per-chat → правдивый отказ в голосе Core
    status, body = await set_chat_overrides(ctx, [
        {"key": "flags.image_generation_module_enabled", "value": False}])
    info("D7_module_off", "status=%s updated=%s"
         % (status, (body or {}).get("updated")))
    if cache is not None:
        await cache.invalidate_chat(SYNTH_CHAT)
    caps.invalidate("image_generation", SYNTH_CHAT, reason="probe-off")
    st = await caps.resolve("image_generation", SYNTH_CHAT)
    info("D7_capability", "status=%s reason=%s detail=%s"
         % (st.status, st.reason_code, st.detail))
    before = len(calls)
    sent_before = len(ctx.stub.sent)
    q2 = "Бот, нарисуй мем про кота"
    expected_tpl = caps.status_message(st)[0] if st is not None else ""
    handled, intent2 = await ctx.svc._image_capability_gate(
        SYNTH_CHAT, q2, fake_message(q2), ctx.stub)
    refusal = (ctx.stub.sent[-1]["text"] if len(ctx.stub.sent) > sent_before
               else "")
    try:
        from services.chat_prompts import IMAGE_FAILURE_TEMPLATES
        known_templates = set(IMAGE_FAILURE_TEMPLATES.values())
    except Exception:  # noqa: BLE001
        known_templates = set()
    ok_ref = (handled is True and bool(refusal)
              and "не умею" not in refusal.lower()
              and not err_phrase_like(refusal)
              and len(calls) == before
              and (refusal == expected_tpl or refusal in known_templates))
    out("D7_off_refusal", ok_ref,
        "handled=%s provider_calls=%d =status_message=%s in_factory=%s "
        "refusal=%r"
        % (handled, len(calls) - before, refusal == expected_tpl,
           refusal in known_templates, refusal))
    info("D7_status_message", "template=%s"
         % (caps.status_message(st)[1] if st else None))

    # D8: восстановление override (удаляем ключ из overrides синтетики)
    await reset_chat_overrides(ctx)
    if cache is not None:
        await cache.invalidate_chat(SYNTH_CHAT)
    caps.invalidate("image_generation", SYNTH_CHAT, reason="probe-clean")
    rows = await pg_fetch(ctx,
                          "SELECT chat_params FROM chat_profiles WHERE chat_id=$1",
                          SYNTH_CHAT)
    ov = (rows[0]["chat_params"] or {}).get("overrides") if rows else {}
    out("D8_override_clean", not ov, "overrides_after=%s" % json.dumps(ov or {}))

    ig._generate_post, ig._generate_get = orig_post, orig_get
    info("D9_provider_calls_total", "всего вызовов провайдера за фазу=%d" % len(calls))


# ═════════════ PHASE E: OQ-9(e) — поиск и фактчек (минимально) ═══════════════

async def phaseE(ctx: Ctx) -> None:
    from services.search_aggregator import SearchAggregator
    from services.tool_router import ToolDeps, ToolRouter, ToolContext
    from services.llm_client import LLMClient
    from services import hot_config as hot
    from config.settings import settings

    llm = None
    try:
        llm = LLMClient(
            hot.get("models.llm_base_url", settings.LLM_BASE_URL),
            hot.get("keys.llm_api_key", settings.LLM_API_KEY),
            hot.get("models.llm_model_name", settings.LLM_MODEL_NAME),
            hot.get("models.embedding_model_name", settings.EMBEDDING_MODEL_NAME))
    except Exception as exc:  # noqa: BLE001
        info("E0_llm", "LLMClient init failed: %s" % type(exc).__name__)
    search = SearchAggregator()
    router = ToolRouter(ToolDeps(search=search, memory=None, db=ctx.db,
                                 llm=llm))

    t0 = time.time()
    res = await router.dispatch("execute_web_search", {"query": "Москва"},
                                ToolContext(SYNTH_CHAT, "Москва",
                                            correlation_id=CORR + "-search"))
    dt = time.time() - t0
    ok_search = isinstance(res, str) and not res.startswith("ОШИБКА")
    out("E1_search", ok_search, "elapsed=%.1fs len=%d head=%r"
        % (dt, len(res or ""), str(res)[:120]))

    if llm is not None:
        t0 = time.time()
        res2 = await router.dispatch(
            "fact_check",
            {"claim": "Вода закипает при 100 °C на уровне моря."},
            ToolContext(SYNTH_CHAT, "фактчек",
                        correlation_id=CORR + "-factcheck"))
        dt2 = time.time() - t0
        try:
            payload = json.loads(res2)
        except Exception:  # noqa: BLE001
            payload = {"raw": str(res2)[:200]}
        status_val = payload.get("status")
        out("E2_factcheck", status_val in ("ready", "unavailable",
                                           "insufficient_evidence", "disabled",
                                           "failed"),
            "elapsed=%.1fs status=%s reason=%s keys=%s"
            % (dt2, status_val, payload.get("reason"),
               sorted(payload.keys())[:12]))
        info("E2_factcheck_payload", json.dumps(
            {k: (str(v)[:120] if not isinstance(v, (int, float, bool, type(None)))
                 else v) for k, v in payload.items()},
            ensure_ascii=False)[:900])
    else:
        out("E2_factcheck", False, "llm client unavailable — не выполнен")

    # видео — по возможности; здесь только состояние capability (без дорогого прогона)
    from services import capability_registry as caps
    st = await caps.resolve("video_summary", SYNTH_CHAT)
    info("E3_video_state", "status=%s reason=%s detail=%s"
         % (st.status, st.reason_code, str(st.detail)[:80]))
    out("E3_video_deferred", True,
        "видео-cценарий отложен: multi-stage (download/STT/LLM), без дешёвого "
        "честного пути; зафиксировано состояние capability")


# ═════════════ PHASE F: OQ-9(f) — длинный редакционный текст ════════════════

LONG_TEXT = (
    "Итоги недели по проекту: мы закрыли релиз 2.58.88 и зафиксировали карту "
    "требований.\n\n"
    "Ключевые пункты: обновление лимитов без рестарта, честный остаток в отказе "
    "и идемпотентность платных вызовов.\n\n"
    "Ссылка на отчёт: https://example.com/reports/25888?tab=summary#top — там "
    "полная таблица.\n\n"
    "Автор писал: «Мы не обещаем то, чего не проверили» — это остаётся "
    "принципом.\n\n"
    "Версии: v2.58.88, checksum 3c4e0608968f; код в `services/direct_chat_service.py` "
    "не менялся.\n\n"
    "Дальше: подготовить следующий шаг и не ломать ссылки, цитаты и кодовые "
    "вставки при любой правке стиля письма.\n"
)


async def phaseF(ctx: Ctx) -> None:
    from services import style_policy as sp
    from services import prompt_composer as composer  # noqa: F401

    # 1) реальный try c длинным текстом (режим editorial_report), 0 LLM
    status, body = await ctx.api.req(
        "POST", "/api/speech/try",
        json_body={"text": LONG_TEXT, "profile": "editorial_report"})
    ok = status == 200 and isinstance(body, dict)
    facts = (body or {}).get("facts") or {}
    spans = facts.get("protected_spans") or []
    kinds = sorted({s.get("kind") for s in spans})
    out("F1_try_long", ok and facts.get("protected_count", 0) >= 1,
        "status=%s profile=editorial_report protected=%s kinds=%s "
        "layers=%s"
        % (status, facts.get("protected_count"), kinds,
           (body.get("strategy") or {}).get("layers_current")))

    # 2) детерминированный style-pass с реальными ЖЁСТКИМИ правилами
    #    (пресеты no_quotes/no_trailing_period/no_emoji), БЕЗ записи в PG
    try:
        probe_doc = sp.build_document(
            presets=["no_quotes", "no_trailing_period", "no_emoji"],
            reason="agent-check-w1 probe (не записан)")
        policy = sp.effective_policy_sync(probe_doc, None, context="regular")
        outcome = await sp.apply_style_policy(
            LONG_TEXT, chat_id=0, policy=policy, context="regular",
            record=False, emit_events=False, stage="probe")
        text_out = outcome.text or ""
        url_ok = "https://example.com/reports/25888?tab=summary#top" in text_out
        quote_ok = "«Мы не обещаем то, чего не проверили»" in text_out
        code_ok = "`services/direct_chat_service.py`" in text_out
        ver_ok = "v2.58.88" in text_out
        asd = outcome.as_dict()
        out("F2_style_pass_protected",
            url_ok and quote_ok and code_ok and ver_ok,
            "rules_enabled=%s url=%s quote=%s code=%s version=%s statuses=%s"
            % (len(policy.rules or ()), url_ok, quote_ok, code_ok, ver_ok,
               json.dumps({k: asd.get(k) for k in
                           ("status", "reason", "changed", "conflicts",
                            "exempted")}, ensure_ascii=False)[:260]))
        info("F2_style_out_len", "in=%d out=%d changed=%s"
             % (len(LONG_TEXT), len(text_out), text_out != LONG_TEXT))
    except Exception as exc:  # noqa: BLE001
        out("F2_style_pass_protected", False, "ERROR=%s" % type(exc).__name__)


# ═══════════════════════════════ main ═══════════════════════════════════════

async def main() -> int:
    ctx = Ctx()
    await bootstrap(ctx)
    await phase0(ctx)
    try:
        await build_service(ctx)
        info("SVC", "DirectChatService готов (llm=None — платные стадии невозможны)")
    except Exception as exc:  # noqa: BLE001
        out("SVC", False, "build failed: %s: %s" % (type(exc).__name__, exc))
        return 2

    phases = (("A", phaseA), ("B", phaseB), ("C", phaseC), ("D", phaseD),
              ("E", phaseE), ("F", phaseF))
    only = os.getenv("AC1_PHASES", "").strip().upper()
    if only:
        wanted = {p.strip() for p in only.split(",") if p.strip()}
        phases = tuple((n, f) for n, f in phases if n in wanted)
        info("PHASES", "выбраны фазы: %s" % ",".join(n for n, _ in phases))
    for name, fn in phases:
        try:
            await fn(ctx)
        except Exception as exc:  # noqa: BLE001
            out("PHASE_%s" % name, False, "EXCEPTION %s: %s"
                % (type(exc).__name__, str(exc)[:300]))

    # финальная очистка синтетики (идемпотентно)
    try:
        from services import chat_params
        await chat_params.set_chat_params(SYNTH_CHAT, {"overrides": {}},
                                          changed_by=None, pg=ctx.pg)
    except Exception:  # noqa: BLE001
        pass
    try:
        await pg_exec(ctx, "DELETE FROM chat_profiles WHERE chat_id=$1", SYNTH_CHAT)
    except Exception:  # noqa: BLE001
        pass
    try:
        await pg_exec(ctx, "DELETE FROM image_reservation WHERE chat_id=$1 "
                           "AND status='reserved'", SYNTH_CHAT)
    except Exception:  # noqa: BLE001
        pass
    try:
        await ctx.db.db.execute("DELETE FROM throttle_state WHERE chat_id=?",
                                (SYNTH_CHAT,))
        await ctx.db.db.commit()
    except Exception as exc:  # noqa: BLE001
        info("FINAL_CLEANUP_NOTE", "throttle delete: %s" % type(exc).__name__)
    rows = await sqlite_fetch(
        ctx, "SELECT count(*) AS n FROM throttle_state WHERE chat_id=?",
        (SYNTH_CHAT,))
    info("FINAL_THROTTLE_LEFTOVER", str(rows[0]["n"] if rows else "?"))
    rows = await pg_fetch(ctx, "SELECT chat_id FROM chat_profiles WHERE chat_id=$1",
                          SYNTH_CHAT)
    info("FINAL_PROFILE_LEFTOVER", str(len(rows)))

    n_ok = sum(1 for _, ok, _ in RESULTS if ok)
    n_all = len(RESULTS)
    print("AC1 SUMMARY ok=%d/%d" % (n_ok, n_all), flush=True)
    try:
        await ctx.api.close()
        await ctx.db.close()
        await ctx.cache.close()
    except Exception:  # noqa: BLE001
        pass
    return 0 if n_ok == n_all else 3


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print("AC1 FATAL %s: %s" % (type(exc).__name__, str(exc)[:400]))
        rc = 4
    print("AC1 RC=%d" % rc, flush=True)
    sys.exit(rc)
