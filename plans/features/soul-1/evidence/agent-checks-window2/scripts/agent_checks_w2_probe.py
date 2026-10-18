# -*- coding: utf-8 -*-
"""AGENT-CHECKS-2 / window-2 — прод-проба (2.58.89, deployed d59fab94).

Запуск на проде (venv):
    cd /var/www/admin_bot && PYTHONIOENCODING=utf-8 \
        /var/www/admin_bot/venv/bin/python /tmp/agent_checks_w2_probe.py

Фазы (W2_PHASES=G,H,S,I,J,L,K,M; default — все по порядку):
  G — CFG-01.AC1: глобальный burst 10->2 (штатный API), 3-й запрос ограничен
      (фраза R50-7 + слот + событие), возврат 10 без рестарта -> поведение вернулось.
  H — CFG-01.AC2: override чата-A (burst=2/cooldown=180), чат-B (без override)
      резолвит global; поведенческая проверка «утечки нет»; restore.
  S — SOUL-AMD.8.3: включённое правило стиля (пресет trailing_period) реально
      меняет текст в живой try-сборке; мгновенный откат; fallback-проверки.
  I — SOUL-AMD.8.10 (+8.8 OFF): per-chat OFF модуля -> витрина capabilities,
      L1 <capability_notice>, полный ход с честным отказом; revert.
  J — SOUL-AMD.8.7: неоднозначное «сделай это» -> ровно один уточняющий вопрос
      полным ходом _handle_turn (0 платных).
  L — SOUL-AMD.5.17/8.6/8.9: РЕАЛЬНАЯ доставка картинки (реальный Telegram-бот),
      повтор без дубля; send-fail реальной ошибкой Telegram; журнал резервов.
      Платно: ровно 2 минимальные генерации (защита бюджета перед каждой).
  K — SOUL-AMD.8.8: правдивые отказы no-key (per-chat override ключа, глобальный
      ключ НЕ трогается) и quota (реальная бухгалтерия used>=limit); OFF — в фазе I.
  M — SOUL-AMD.8.11: видео остаётся not_configured (остаток подтверждён).

Принципы: настройки только синтетического чата, с восстановлением; глобальные
лимиты — правка+возврат через штатный API; ключи не печатаются (R17); fail-soft
по фазам; машинный SUMMARY в конце.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
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

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s %(name)s: %(message)s")

SYNTH_A = -1009900000201
SYNTH_B = -1009900000202
SYNTH_USER = 990002001
ADMIN_ID = 5885953495
OWNER_DM = 5885953495
MSG_G4 = 990000801
MSG_H4A = 990000802
MSG_H5B = 990000803
MSG_I5 = 990000804
MSG_I6 = 990000805
MSG_J1 = 990000806
MSG_L1 = 990000811
MSG_L3 = 990000808
MSG_K1 = 990000809
MSG_K2 = 990000810
CORR = "probe-agent-checks-w2"
FACE = "Бот, нарисуй мем про кота"
STYLE_TEXT = "Это агентская проверка: завершающая точка должна исчезнуть."

BIND_FILES = (
    "services/direct_chat_service.py", "services/persistent_throttling.py",
    "services/chat_params.py", "services/capability_registry.py",
    "services/image_generation.py", "services/style_policy.py",
    "services/worker_budget.py", "services/direct_capabilities.py",
    "services/chat_prompts.py", "services/prompt_composer.py",
    "web/api/speech.py", "web/api/routes.py", "config/settings.py",
)

RESULTS: list[tuple[str, bool, str]] = []


def out(tag: str, ok: bool, text: str) -> None:
    RESULTS.append((tag, bool(ok), str(text)))
    print("W2 %s %s | %s" % (tag, "OK" if ok else "FAIL", text), flush=True)


def info(tag: str, text: str) -> None:
    print("W2 %s INFO | %s" % (tag, text), flush=True)


_ERROR_PHRASES = ("внутренняя ошибка базы", "мои мозги расплавились",
                  "я подавился токенами")


def err_phrase_like(text: str) -> bool:
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
        "query_id": "AAHagentcheck2",
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
    """Заглушка aiogram-бота: фиксирует вызовы (никаких сетевых отправок)."""

    def __init__(self):
        self.sent: list[dict] = []
        self.photos: list[dict] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": str(text),
                          "kwargs": {k: v for k, v in kwargs.items()}})
        return types.SimpleNamespace(message_id=MSG_G4 + len(self.sent))

    async def send_photo(self, chat_id, photo, **kwargs):
        self.photos.append({"chat_id": chat_id,
                            "bytes": len(getattr(photo, "data", b"") or b"")})
        return types.SimpleNamespace(message_id=MSG_G4 + 500 + len(self.photos))

    def __getattr__(self, name):
        async def _noop(*args, **kwargs):
            return types.SimpleNamespace(message_id=0, ok=True)
        return _noop


class RecordingBot:
    """РЕАЛЬНЫЙ aiogram-бот + запись фактических отправок.

    ``redirect_to`` (не None) перенаправляет send_photo с синтетического чата
    на указанный РЕАЛЬНЫЙ чат; сам вызов — реальный Telegram API,
    ``message_id`` — реальный. Остальные методы делегируются.
    """

    def __init__(self, real, redirect_to=None):
        self._real = real
        self._redirect = redirect_to
        self.calls: list[dict] = []

    async def send_photo(self, chat_id, photo, **kwargs):
        target = chat_id
        redirected = False
        if self._redirect is not None and int(chat_id) == SYNTH_A:
            target = int(self._redirect)
            redirected = True
        rec = {"chat_requested": int(chat_id), "target": int(target),
               "bytes": len(getattr(photo, "data", b"") or b""),
               "redirected": redirected}
        send_kwargs = dict(kwargs)
        if redirected:
            # reply-таргет принадлежит синтетическому чату: в другом чате его нет
            send_kwargs.pop("reply_to_message_id", None)
        self.calls.append(rec)
        try:
            msg = await self._real.send_photo(int(target), photo, **send_kwargs)
            rec["ok"] = True
            rec["message_id"] = getattr(msg, "message_id", None)
            return msg
        except Exception as exc:  # noqa: BLE001
            rec["ok"] = False
            rec["error"] = type(exc).__name__
            rec["error_text"] = str(exc)[:160]
            raise

    def __getattr__(self, name):
        return getattr(self._real, name)


def fake_message(text: str, msg_id: int, *, chat_id: int = SYNTH_A,
                 reply_to=None):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(id=chat_id, type="supergroup"),
        text=text, message_id=msg_id,
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
        self.real_bot = None
        self.provider_calls: list[str] = []
        self.reach: dict[int, bool] = {}
        self.send_target = None          # реальный получатель позитивной доставки
        self.limits_key = "limits.chat_burst_limit"


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
    info("BOOT", "version=%s pg_available=%s"
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


async def sqlite_exec(ctx: Ctx, sql: str, args=()) -> None:
    await ctx.db.db.execute(sql, args)
    await ctx.db.db.commit()


async def set_chat_overrides(ctx: Ctx, chat_id: int, items: list[dict]):
    """Запись per-chat overrides через реальный API; при не-200 — сервисное
    письмо (как в окне-1: CFG_FALLBACK). Возврат (status, detail)."""
    status, body = await ctx.api.req(
        "POST", "/api/config", chat_id=chat_id,
        json_body={"items": items, "updated_at": None})
    if status == 200:
        return status, "updated=%s" % ((body or {}).get("updated"),)
    from services import chat_params
    root = await chat_params.get_all_chat_params(chat_id, pg=ctx.pg)
    ov = dict((root or {}).get("overrides") or {})
    for item in items:
        ov[item["key"]] = item["value"]
    try:
        await chat_params.set_chat_params(chat_id, {"overrides": ov},
                                          changed_by=None, pg=ctx.pg)
        info("CFG_FALLBACK", "chat=%s API status=%s -> service write: ok"
             % (chat_id, status))
        return status, "service_write updated=%s" % (
            [i["key"] for i in items],)
    except Exception as exc:  # noqa: BLE001
        return status, "service_write failed %s" % type(exc).__name__


async def reset_chat_overrides(ctx: Ctx, chat_id: int) -> None:
    from services import chat_params
    try:
        await chat_params.set_chat_params(chat_id, {"overrides": {}},
                                          changed_by=None, pg=ctx.pg)
    except Exception as exc:  # noqa: BLE001
        info("CFG_RESET", "chat=%s override reset failed: %s"
             % (chat_id, type(exc).__name__))


async def raw_chat_override(ctx: Ctx, chat_id: int, key: str, value) -> None:
    """Прямая (сервисная) правка одного ключа overrides — для симуляций,
    которые MiniApp-путь запрещает по дизайну (keys.* — глобальный секрет)."""
    from services import chat_params
    root = await chat_params.get_all_chat_params(chat_id, pg=ctx.pg)
    ov = dict((root or {}).get("overrides") or {})
    ov[key] = value
    await chat_params.set_chat_params(chat_id, {"overrides": ov},
                                      changed_by=None, pg=ctx.pg)


async def drop_chat_override(ctx: Ctx, chat_id: int, key: str) -> None:
    from services import chat_params
    root = await chat_params.get_all_chat_params(chat_id, pg=ctx.pg)
    ov = dict((root or {}).get("overrides") or {})
    ov.pop(key, None)
    await chat_params.set_chat_params(chat_id, {"overrides": ov},
                                      changed_by=None, pg=ctx.pg)


async def invalidate_chat(ctx: Ctx, chat_id: int) -> None:
    from services import chat_params
    from services import capability_registry as caps
    cache = chat_params.get_chat_params_cache()
    if cache is not None:
        await cache.invalidate_chat(chat_id)
    caps.invalidate("image_generation", chat_id, reason="probe-w2")


async def resolve_limits(ctx: Ctx, chat_id: int):
    from services.persistent_throttling import resolve_direct_chat_limits
    return await resolve_direct_chat_limits(chat_id)


async def prime_charge(ctx: Ctx, chat_id: int, limit, cooldown):
    from services.persistent_throttling import throttle_refresh
    throttle_refresh(ctx.svc.throttle, limit, cooldown)
    r = ctx.svc.throttle.allow(chat_id, SYNTH_USER)
    if asyncio.iscoroutine(r):
        r = await r
    return r


async def slot_row(ctx: Ctx, chat_id: int):
    rows = await sqlite_fetch(
        ctx, "SELECT burst_left, last_ts FROM throttle_state "
             "WHERE scope='direct_chat' AND chat_id=? AND user_id=?",
        (chat_id, SYNTH_USER))
    return rows[0] if rows else None


def _parse_phrase_remaining(phrase: str) -> int | None:
    m = re.search(r"(\d+ мин(?: \d+ сек)?|\d+ сек)", phrase or "")
    if not m:
        return None
    seg = m.group(0)
    if "мин" in seg:
        mp = re.match(r"(\d+) мин(?: (\d+) сек)?$", seg)
        if not mp:
            return None
        return int(mp.group(1)) * 60 + int(mp.group(2) or 0)
    mp2 = re.match(r"(\d+) сек$", seg)
    return int(mp2.group(1)) if mp2 else None


# ═══════════════════════════ PHASE 0: PRE snapshot ═══════════════════════════

async def phase0(ctx: Ctx) -> None:
    info("P0_TIME", "now_utc=%s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                                 time.gmtime()))
    try:
        with open("/tmp/agent_checks_w2_probe.py", "rb") as fh:
            info("P0_PROBE_SHA", hashlib.sha256(fh.read()).hexdigest())
    except Exception as exc:  # noqa: BLE001
        info("P0_PROBE_SHA", "ERR:%s" % type(exc).__name__)
    for rel in BIND_FILES:
        info("P0_SHA", "%s %s" % (rel, sha12(rel)))
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as cl:
            r = await cl.get("http://127.0.0.1:8000/healthz")
            info("P0_HEALTHZ", "status=%s body=%s" % (r.status_code,
                                                      r.text[:120]))
    except Exception as exc:  # noqa: BLE001
        info("P0_HEALTHZ", "ERR %s" % type(exc).__name__)
    from services import hot_config as hot
    from config.settings import settings
    info("P0_GLOBAL_LIMITS",
         "burst=%r cooldown=%r silence_enabled=%r after=%r"
         % (hot.get("limits.chat_burst_limit", settings.CHAT_BURST_LIMIT),
            hot.get("limits.chat_cooldown_seconds",
                    settings.CHAT_COOLDOWN_SECONDS),
            hot.get("flags.chat_silence_enabled",
                    settings.CHAT_SILENCE_ENABLED),
            hot.get("limits.chat_silence_after_cooldowns",
                    settings.CHAT_SILENCE_AFTER_COOLDOWNS)))
    rows = await pg_fetch(ctx, "SELECT count(*) AS n FROM chat_profiles")
    info("P0_PROFILES", "total=%s" % (rows[0]["n"] if rows else "?"))
    for cid in (SYNTH_A, SYNTH_B):
        rows = await pg_fetch(
            ctx, "SELECT chat_id FROM chat_profiles WHERE chat_id=$1", cid)
        info("P0_SYNTH", "chat=%s profile_exists=%s" % (cid, bool(rows)))
    rows = await sqlite_fetch(
        ctx, "SELECT chat_id, scope, count(*) AS n FROM throttle_state "
             "WHERE chat_id IN (?,?) GROUP BY chat_id, scope",
        (SYNTH_A, SYNTH_B))
    info("P0_THROTTLE", json.dumps([{k: str(v) for k, v in r.items()}
                                    for r in rows], ensure_ascii=False))
    rows = await pg_fetch(
        ctx, "SELECT value FROM bot_settings WHERE key='style.policy'")
    doc = rows[0]["value"] if rows else None
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except Exception:  # noqa: BLE001
            doc = None
    info("P0_STYLE_PG", "present=%s revision=%s rules=%s soft=%s"
         % (bool(rows), (doc or {}).get("revision"),
            len((doc or {}).get("rules") or []),
            len((doc or {}).get("soft_instructions") or [])))
    try:
        rows = await pg_fetch(
            ctx, "SELECT day, scope, used FROM worker_budget "
                 "WHERE metric='image_calls' ORDER BY day DESC LIMIT 8")
        info("P0_BUDGET", json.dumps([{k: str(v) for k, v in r.items()}
                                      for r in rows], ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        info("P0_BUDGET", "ERROR=%s" % type(exc).__name__)
    from services import capability_registry as caps
    for cap in ("image_generation", "video_summary"):
        try:
            st = await caps.resolve(cap, SYNTH_A)
            info("P0_CAP", "%s status=%s reason=%s detail=%s"
                 % (cap, st.status, st.reason_code, str(st.detail)[:80]))
        except Exception as exc:  # noqa: BLE001
            info("P0_CAP", "%s ERROR=%s" % (cap, type(exc).__name__))
    # ── Telegram-рекон: какие чаты РЕАЛЬНО достижимы (read-only getChat) ──
    try:
        from aiogram import Bot
        from config.settings import settings as _s
        ctx.real_bot = Bot(token=_s.API_TOKEN)
        me = await ctx.real_bot.get_me()
        info("P0_BOT", "get_me username=%s id=%s"
             % (getattr(me, "username", "?"), getattr(me, "id", "?")))
        candidates = [SYNTH_A, SYNTH_B, OWNER_DM, -1002661910336,
                      -1004482340693]
        for cid in candidates:
            try:
                chat = await ctx.real_bot.get_chat(cid)
                ctx.reach[cid] = True
                info("P0_REACH", "chat=%s reachable=True type=%s title=%r"
                     % (cid, getattr(chat, "type", "?"),
                        str(getattr(chat, "title", ""))[:40]))
            except Exception as exc:  # noqa: BLE001
                ctx.reach[cid] = False
                info("P0_REACH", "chat=%s reachable=False error=%s"
                     % (cid, type(exc).__name__))
    except Exception as exc:  # noqa: BLE001
        ctx.real_bot = None
        info("P0_REACH", "real bot unavailable: %s" % type(exc).__name__)
    if ctx.reach.get(SYNTH_A):
        ctx.send_target = None            # синтетика достижима — без редиректа
    elif ctx.reach.get(OWNER_DM):
        ctx.send_target = OWNER_DM        # редирект: ЛС владельца
    else:
        ctx.send_target = None
    info("P0_SEND_TARGET", "target=%r (None = без редиректа)" % (ctx.send_target,))


# ═════════════════ PHASE G: CFG-01.AC1 — глобальный burst ═══════════════════

def _find_item(body, key):
    for it in ((body or {}).get("items") or []):
        if it.get("key") == key:
            return it
    return None


async def phaseG(ctx: Ctx) -> None:
    from services import mca_events
    from services.smartmodule_phrases import CHAT_COOLDOWN_PHRASES

    # G0: baseline global
    status, body = await ctx.api.req("GET", "/api/config")
    it = _find_item(body, ctx.limits_key)
    it_cd = _find_item(body, "limits.chat_cooldown_seconds")
    out("G0_global_before", status == 200 and it is not None
        and int(it.get("value")) == 10,
        "status=%s burst=%r cooldown=%r" % (status, (it or {}).get("value"),
                                            (it_cd or {}).get("value")))

    # G1: глобальная запись burst=2 через штатный API (no X-Chat-Id)
    status, body = await ctx.api.req(
        "POST", "/api/config",
        json_body={"items": [{"key": ctx.limits_key, "value": 2}]})
    out("G1_global_write_2", status == 200
        and ctx.limits_key in ((body or {}).get("updated") or []),
        "status=%s updated=%s" % (status, (body or {}).get("updated")))

    # G2: витрина после записи + резолв в пробе (штатный cache.reload)
    status2, body2 = await ctx.api.req("GET", "/api/config")
    it2 = _find_item(body2, ctx.limits_key)
    await ctx.cache.reload()
    lim, cd, src = await resolve_limits(ctx, SYNTH_A)
    out("G2_resolve_after_write", lim == 2 and float(cd) == 300.0
        and src == "global",
        "api_value=%r resolve=(burst=%s cooldown=%s source=%r)"
        % ((it2 or {}).get("value"), lim, cd, src))

    # G3: два «запроса» израсходовали заряд (та же точка allow, что в _handle_turn)
    await sqlite_exec(ctx, "DELETE FROM throttle_state WHERE chat_id=?",
                      (SYNTH_A,))
    a1 = await prime_charge(ctx, SYNTH_A, lim, cd)
    s1 = await slot_row(ctx, SYNTH_A)
    a2 = await prime_charge(ctx, SYNTH_A, lim, cd)
    s2 = await slot_row(ctx, SYNTH_A)
    out("G3_two_charges", float(a1) == 0.0 and float(a2) == 0.0,
        "allow1=%r burst_left=%s allow2=%r burst_left=%s"
        % (a1, (s1 or {}).get("burst_left"), a2, (s2 or {}).get("burst_left")))

    # G4: ТРЕТИЙ запрос — полный _handle_turn → отказ (фраза + слот)
    sent_before = len(ctx.stub.sent)
    t0 = time.time()
    await ctx.svc._handle_turn(ctx.stub, fake_message("привет", MSG_G4),
                               fake_user())
    elapsed = time.time() - t0
    sent = ctx.stub.sent[sent_before:]
    phrase = sent[-1]["text"] if sent else ""
    reply_to = sent[-1]["kwargs"].get("reply_to_message_id") if sent else None
    err_phrase = err_phrase_like(phrase)
    last = await slot_row(ctx, SYNTH_A)
    last_ts = float(last["last_ts"]) if last else None
    rem_db = (float(cd) - (time.time() - last_ts)) if last_ts else None
    prefixes = [p.split("{remaining_time}")[0] for p in CHAT_COOLDOWN_PHRASES]
    shape_ok = any(phrase.startswith(pfx) for pfx in prefixes)
    phrase_secs = _parse_phrase_remaining(phrase)
    delta = (abs(phrase_secs - rem_db)
             if (rem_db is not None and phrase_secs is not None) else None)
    out("G4_third_restricted", bool(sent) and not err_phrase,
        "sends=%d elapsed=%.1fs reply_to=%s error_phrase=%s phrase=%r"
        % (len(sent), elapsed, reply_to, err_phrase, phrase))
    out("G5_phrase_contract",
        shape_ok and delta is not None and delta <= 2.0
        and phrase_secs is not None and phrase_secs >= 0,
        "shape_ok=%s phrase_tail=%ss db_remaining=%.1fs delta=%s"
        % (shape_ok, phrase_secs, rem_db if rem_db is not None else -1.0,
           ("%.1f" % delta) if delta is not None else None))
    info("G5_slot", "burst_left=%s last_ts=%s cooldown=%s source=%s"
         % ((last or {}).get("burst_left"), last_ts, cd, src))
    info("G5_phrase_pool", "из пула R50-7 (%d шаблонов), 'технически не могу'=%s"
         % (len(CHAT_COOLDOWN_PHRASES),
            "технически не могу" in phrase.lower()))

    # G6: durable-событие + просмотрщик
    flushed = await mca_events.flush_events(ctx.db)
    info("G6_flush", "events_flushed=%s" % flushed)
    status, body = await ctx.api.req(
        "GET", "/api/status/logs?component=direct_chat&chat_id=%d&limit=50"
        % SYNTH_A)
    events = (body or {}).get("events") or []
    ours = [e for e in events if e.get("event_name") == "direct_chat_throttle"]
    payload = {}
    try:
        payload = json.loads((ours[0].get("usage_json") if ours else "") or "{}")
    except Exception:  # noqa: BLE001
        payload = {}
    out("G6_viewer_event", bool(ours),
        "viewer_status=%s events=%d matched=%d" % (status, len(events),
                                                   len(ours)))
    out("G7_event_payload",
        bool(ours) and payload.get("source") == "global"
        and int(payload.get("burst_limit") or -1) == 2
        and float(payload.get("remaining_seconds") or 0) > 0,
        "stage=%s reason=%s usage_json=%s"
        % ((ours[0].get("stage") if ours else None),
           (ours[0].get("reason_code") if ours else None),
           json.dumps(payload, ensure_ascii=False)))

    # G8: возврат 10 через штатный API (без рестарта) → резолв видит 10
    status, body = await ctx.api.req(
        "POST", "/api/config",
        json_body={"items": [{"key": ctx.limits_key, "value": 10}]})
    await ctx.cache.reload()
    lim2, cd2, src2 = await resolve_limits(ctx, SYNTH_A)
    out("G8_restore_resolve", status == 200 and lim2 == 10
        and float(cd2) == 300.0 and src2 == "global",
        "status=%s updated=%s resolve=(burst=%s cooldown=%s source=%r)"
        % (status, (body or {}).get("updated"), lim2, cd2, src2))

    # G9: поведение вернулось — 2 заряда + третий allow СНОВА разрешён
    await sqlite_exec(ctx, "DELETE FROM throttle_state WHERE chat_id=?",
                      (SYNTH_A,))
    b1 = await prime_charge(ctx, SYNTH_A, lim2, cd2)
    b2 = await prime_charge(ctx, SYNTH_A, lim2, cd2)
    b3 = await prime_charge(ctx, SYNTH_A, lim2, cd2)
    out("G9_behavior_restored",
        float(b1) == 0.0 and float(b2) == 0.0 and float(b3) == 0.0,
        "allow1=%r allow2=%r allow3=%r (третий снова допущен — поведение "
        "вернулось)" % (b1, b2, b3))
    await sqlite_exec(ctx, "DELETE FROM throttle_state WHERE chat_id=?",
                      (SYNTH_A,))

    # G10: глобальный слой как был (burst=10, cooldown=300)
    status, body = await ctx.api.req("GET", "/api/config")
    itf = _find_item(body, ctx.limits_key)
    itcdf = _find_item(body, "limits.chat_cooldown_seconds")
    out("G10_global_after", int((itf or {}).get("value") or -1) == 10
        and float((itcdf or {}).get("value") or -1) == 300.0,
        "burst=%r cooldown=%r" % ((itf or {}).get("value"),
                                  (itcdf or {}).get("value")))


# ═════════════════ PHASE H: CFG-01.AC2 — два синтетических чата ═════════════

async def phaseH(ctx: Ctx) -> None:
    from services import chat_params
    await chat_params.ensure_scope_profile(SYNTH_A, dm=False, pg=ctx.pg)

    # H0: чат-B до любых правок — без override, value == global
    status, body = await ctx.api.req("GET", "/api/config", chat_id=SYNTH_B)
    itb = _find_item(body, ctx.limits_key)
    out("H0_chatB_baseline", status == 200 and itb is not None
        and int(itb.get("value")) == 10 and not itb.get("chat_source"),
        "status=%s value=%r chat_source=%r"
        % (status, (itb or {}).get("value"), (itb or {}).get("chat_source")))

    # H1: override чата-A через реальный API
    status, detail = await set_chat_overrides(ctx, SYNTH_A, [
        {"key": "limits.chat_burst_limit", "value": 2},
        {"key": "limits.chat_cooldown_seconds", "value": 180}])
    out("H1_override_A", status == 200 or "service_write" in detail,
        "status=%s %s" % (status, detail))
    await invalidate_chat(ctx, SYNTH_A)

    # H2/H3: резолв обоих чатов (B — при активном override A: проверка утечки)
    limA, cdA, srcA = await resolve_limits(ctx, SYNTH_A)
    limB, cdB, srcB = await resolve_limits(ctx, SYNTH_B)
    out("H2_resolve_A", limA == 2 and float(cdA) == 180.0 and srcA == "chat",
        "resolve=(burst=%s cooldown=%s source=%r)" % (limA, cdA, srcA))
    out("H3_resolve_B_no_leak", limB == 10 and float(cdB) == 300.0
        and srcB == "global",
        "resolve=(burst=%s cooldown=%s source=%r) при активном override A"
        % (limB, cdB, srcB))

    # H4: поведение A — 2 заряда, третий отказ
    await sqlite_exec(ctx, "DELETE FROM throttle_state WHERE chat_id IN (?,?)",
                      (SYNTH_A, SYNTH_B))
    a1 = await prime_charge(ctx, SYNTH_A, limA, cdA)
    a2 = await prime_charge(ctx, SYNTH_A, limA, cdA)
    a3 = await prime_charge(ctx, SYNTH_A, limA, cdA)
    out("H4_behavior_A_limited", float(a1) == 0.0 and float(a2) == 0.0
        and float(a3) > 0.0,
        "allow1=%r allow2=%r allow3=%r (>0 — ограничен)" % (a1, a2, a3))

    # H5: поведение B — третий снова допущен (global 10, утечки нет)
    b1 = await prime_charge(ctx, SYNTH_B, limB, cdB)
    b2 = await prime_charge(ctx, SYNTH_B, limB, cdB)
    b3 = await prime_charge(ctx, SYNTH_B, limB, cdB)
    out("H5_behavior_B_global", float(b1) == 0.0 and float(b2) == 0.0
        and float(b3) == 0.0,
        "allow1=%r allow2=%r allow3=%r (третий допущен по global)"
        % (b1, b2, b3))

    # H6: restore — снять override A, чат-B не тронут
    await reset_chat_overrides(ctx, SYNTH_A)
    await invalidate_chat(ctx, SYNTH_A)
    rows = await pg_fetch(
        ctx, "SELECT chat_params FROM chat_profiles WHERE chat_id=$1", SYNTH_A)
    ov = (rows[0]["chat_params"] or {}).get("overrides") if rows else {}
    limA2, cdA2, srcA2 = await resolve_limits(ctx, SYNTH_A)
    out("H6_restore", not ov and limA2 == 10 and float(cdA2) == 300.0
        and srcA2 == "global",
        "overrides_after=%s resolve=(burst=%s cooldown=%s source=%r)"
        % (json.dumps(ov or {}), limA2, cdA2, srcA2))
    rows_b = await pg_fetch(
        ctx, "SELECT chat_id FROM chat_profiles WHERE chat_id=$1", SYNTH_B)
    out("H7_chatB_untouched", not rows_b,
        "chatB_profile_rows=%d (профиль не создавался)" % len(rows_b))
    await sqlite_exec(ctx, "DELETE FROM throttle_state WHERE chat_id IN (?,?)",
                      (SYNTH_A, SYNTH_B))


# ═══════════════ PHASE S: SOUL-AMD.8.3 — эффект правила стиля ════════════════

async def phaseS(ctx: Ctx) -> None:
    from services import style_policy as sp

    # S0: baseline (API + PG)
    status, style_body = await ctx.api.req("GET", "/api/speech/style")
    rows = await pg_fetch(
        ctx, "SELECT value FROM bot_settings WHERE key='style.policy'")
    prev_doc = rows[0]["value"] if rows else None
    if isinstance(prev_doc, str):
        try:
            prev_doc = json.loads(prev_doc)
        except Exception:  # noqa: BLE001
            prev_doc = None
    base_rules = len((prev_doc or {}).get("rules") or [])
    base_soft = len((prev_doc or {}).get("soft_instructions") or [])
    out("S0_baseline_state", status == 200 and isinstance(prev_doc, dict),
        "api_status=%s global_present=%s revision=%s rules=%s soft=%s"
        % (status, (style_body or {}).get("global_present"),
           (style_body or {}).get("global_revision"),
           (style_body or {}).get("global_rules"),
           (style_body or {}).get("global_soft")))

    # S1: try ДО правила
    _, t0 = await ctx.api.req("POST", "/api/speech/try",
                              json_body={"text": STYLE_TEXT})
    sp0 = ((t0 or {}).get("extent") or {}).get("style_pass") or {}
    masked0 = ((t0 or {}).get("extent") or {}).get("style_text_masked")
    ver0 = (((t0 or {}).get("current") or {}).get("versions") or {}).get(
        "style_policy", "<none>")
    out("S1_try_before", bool(t0) and masked0 == STYLE_TEXT
        and int(sp0.get("repaired") or 0) == 0,
        "text_same=%s repaired=%s applied=%r versions=%r"
        % (masked0 == STYLE_TEXT, sp0.get("repaired"), sp0.get("applied"),
           ver0))

    # S2: включённое правило (пресет) в глобальный документ через реальный API
    cand = dict(prev_doc or {})
    rule = sp.preset_rules("no_trailing_period")[0]
    cand["rules"] = list(cand.get("rules") or []) + [dict(rule)]
    status, body = await ctx.api.req(
        "POST", "/api/speech/style",
        json_body={"document": cand, "scope": "global",
                   "reason": "agent-check-w2 probe (временно)"})
    res = (body or {}).get("result") or {}
    new_rev = res.get("revision")
    out("S2_rule_write", status == 200 and bool(res.get("applied"))
        and int(res.get("rules") or -1) == base_rules + 1,
        "status=%s applied=%s revision=%s rules=%s rule_id=%s"
        % (status, res.get("applied"), new_rev, res.get("rules"),
           rule.get("id")))

    # S3: следующая try РЕАЛЬНО отражает правило
    _, t1 = await ctx.api.req("POST", "/api/speech/try",
                              json_body={"text": STYLE_TEXT})
    sp1 = ((t1 or {}).get("extent") or {}).get("style_pass") or {}
    masked1 = ((t1 or {}).get("extent") or {}).get("style_text_masked")
    ver1 = (((t1 or {}).get("current") or {}).get("versions") or {}).get(
        "style_policy", "<none>")
    expected = STYLE_TEXT[:-1] if STYLE_TEXT.endswith(".") else STYLE_TEXT
    exp_sha = hashlib.sha256(expected.encode("utf-8")).hexdigest()[:12]
    effect_ok = (masked1 == expected) or (
        str(sp1.get("text_sha12") or "") == exp_sha
        and int(sp1.get("repaired") or 0) >= 1)
    out("S3_effect_next_try", effect_ok,
        "before=%r after=%r expected=%r repaired=%s text_sha12=%r "
        "applied=%r"
        % (STYLE_TEXT, masked1, expected, sp1.get("repaired"),
           sp1.get("text_sha12"), sp1.get("applied")))
    pref_ok = any(str(ver1).startswith("%s%s" % (tag, int(new_rev or -1)))
                  for tag in ("c", "g"))
    out("S4_revision_bump", pref_ok,
        "before=%r after=%r (ожидался префикс c%s/g%s)"
        % (ver0, ver1, new_rev, new_rev))

    # S5: МГНОВЕННЫЙ откат — вернуть исходный документ
    status, body = await ctx.api.req(
        "POST", "/api/speech/style",
        json_body={"document": prev_doc, "scope": "global",
                   "reason": "agent-check-w2 restore"})
    res_r = (body or {}).get("result") or {}
    out("S5_restore", status == 200 and bool(res_r.get("applied")),
        "status=%s applied=%s revision=%s" % (status, res_r.get("applied"),
                                              res_r.get("revision")))
    await ctx.cache.reload()
    rows = await pg_fetch(
        ctx, "SELECT value FROM bot_settings WHERE key='style.policy'")
    doc2 = rows[0]["value"] if rows else None
    if isinstance(doc2, str):
        doc2 = json.loads(doc2)
    probe_rule = [r for r in ((doc2 or {}).get("rules") or [])
                  if isinstance(r, dict)
                  and str(r.get("id")) == "trailing_period.hard.strip"]
    out("S6_final_state",
        not probe_rule and len((doc2 or {}).get("rules") or []) == base_rules
        and len((doc2 or {}).get("soft_instructions") or []) == base_soft,
        "rules=%s soft=%s probe_rule_present=%s (ожидалось %s/%s)"
        % (len((doc2 or {}).get("rules") or []),
           len((doc2 or {}).get("soft_instructions") or []),
           bool(probe_rule), base_rules, base_soft))
    _, t2 = await ctx.api.req("POST", "/api/speech/try",
                              json_body={"text": STYLE_TEXT})
    sp2 = ((t2 or {}).get("extent") or {}).get("style_pass") or {}
    masked2 = ((t2 or {}).get("extent") or {}).get("style_text_masked")
    out("S7_try_after_restore", masked2 == STYLE_TEXT
        and int(sp2.get("repaired") or 0) == 0,
        "text_same=%s repaired=%s applied=%r"
        % (masked2 == STYLE_TEXT, sp2.get("repaired"), sp2.get("applied")))

    # S8: fallback-a — невалидное правило отбрасывается с ЯВНОЙ причиной
    # (детерминированно, без записи): не «протекает» в рантайм и не молчит.
    bad = dict(prev_doc or {})
    bad["rules"] = list(bad.get("rules") or []) + [
        {"id": "bogus.rule", "kind": "no_such_kind", "strictness": "hard"}]
    norm_bad, issues = sp.validate_document(bad)
    ids_bad = [r.get("id") for r in (norm_bad or {}).get("rules") or []]
    out("S8_invalid_not_silent",
        bool(issues) and any("rule_kind_unknown" in i for i in issues)
        and "bogus.rule" not in ids_bad,
        "validate_issues=%d contains_kind=%s bogus_dropped=%s issues=%s"
        % (len(issues), any("rule_kind_unknown" in i for i in issues),
           "bogus.rule" not in ids_bad,
           json.dumps(list(issues)[:4], ensure_ascii=False)))

    # S9: fallback-b — композер при недоступном W3-модуле не подставляет
    # «старого персонажа»: ref строится ТОЛЬКО из реального документа.
    from services import prompt_composer as composer
    orig = sp.resolve_style_policy_ref
    try:
        async def _boom(chat_id):
            raise RuntimeError("probe: W3 unavailable")
        sp.resolve_style_policy_ref = _boom
        ref = await composer.resolve_style_policy_ref(SYNTH_A)
        exp_hint = composer._style_hint(doc2 or {})
        out("S9_composer_fallback",
            str(getattr(ref, "hint", "")) == exp_hint
            and len(str(getattr(ref, "hint", ""))) < 400,
            "fallback_hint=%r expected_from_real_doc=%r source=%r skip=%r"
            % (getattr(ref, "hint", None), exp_hint,
               getattr(ref, "source", None),
               getattr(ref, "skip_reason", None)))
    finally:
        sp.resolve_style_policy_ref = orig


# ══════ PHASE I: SOUL-AMD.8.10 (+8.8 OFF) — per-chat OFF модуля ═════════════

async def phaseI(ctx: Ctx) -> None:
    from services import chat_params
    from services import capability_registry as caps
    from services import direct_capabilities as dcaps
    from services import direct_l1 as _l1

    await chat_params.ensure_scope_profile(SYNTH_A, dm=False, pg=ctx.pg)

    st = await caps.resolve("image_generation", SYNTH_A)
    out("I0_before_on", st.status == "ready",
        "status=%s detail=%s" % (st.status, str(st.detail)[:60]))

    status, detail = await set_chat_overrides(ctx, SYNTH_A, [
        {"key": "flags.image_generation_module_enabled", "value": False}])
    out("I1_override_off", "updated" in detail or status == 200,
        "status=%s %s" % (status, detail))
    await invalidate_chat(ctx, SYNTH_A)
    st_off = await caps.resolve("image_generation", SYNTH_A)
    out("I2_capability_disabled", st_off.status == "disabled"
        and st_off.reason_code == "module_disabled",
        "status=%s reason=%s detail=%s"
        % (st_off.status, st_off.reason_code, str(st_off.detail)[:60]))

    # витрина «Возможности бота» (то, что рендерит UI)
    status, body = await ctx.api.req("GET", "/api/speech/capabilities",
                                     chat_id=SYNTH_A)
    items = (body or {}).get("capabilities") or []
    cap_img = next((c for c in items
                    if c.get("capability_id") == "image_generation"), {})
    summary = (body or {}).get("summary") or {}
    out("I3_showcase", status == 200 and cap_img.get("status") == "disabled"
        and cap_img.get("reason_code") == "module_disabled",
        "status=%s image_generation=%s summary=%s"
        % (status, json.dumps({k: cap_img.get(k) for k in
                               ("status", "reason_code", "detail")},
                              ensure_ascii=False),
           json.dumps(summary)))
    status, body = await ctx.api.req("GET", "/api/speech/overview",
                                     chat_id=SYNTH_A)
    out("I4_overview_summary",
        status == 200 and int(((body or {}).get("capability_summary")
                               or {}).get("disabled") or 0) >= 1,
        "status=%s capability_summary=%s"
        % (status, json.dumps((body or {}).get("capability_summary"))))

    # L1-консистентность: <capability_notice> с реальным статусом
    intent = dcaps.detect_action_intent(FACE, addressed=True)
    plan = _l1.L1Plan(capabilities_needed=("image_generation",))
    block, fired, denied = await ctx.svc._l1_capability_consistency(
        SYNTH_A, FACE, fake_message(FACE, MSG_I5), ctx.stub, plan,
        intent=intent, image_pre_gate_fired=False,
        correlation_id=CORR + "-l1")
    out("I5_L1_notice",
        'capability_notice status="disabled"' in block
        and "image_generation" in block and denied == ("image_generation",)
        and fired is False,
        "denied=%s fired=%s block=%r" % (list(denied), fired, block[:200]))

    # живой отказной путь (8.8-OFF): реальный метод гейта — тот же, что зовёт
    # _handle_turn (полный ход в пробе с memory=None недостижим: сборка
    # контекста падает до гейта — ограничение харнесса, не продукта).
    sent_before = len(ctx.stub.sent)
    before_calls = len(ctx.provider_calls)
    expected_tpl = caps.status_message(st_off)[0]
    handled6, intent6 = await ctx.svc._image_capability_gate(
        SYNTH_A, FACE, fake_message(FACE, MSG_I6), ctx.stub)
    refusal = (ctx.stub.sent[-1]["text"]
               if len(ctx.stub.sent) > sent_before else "")
    out("I6_off_refusal_gate",
        handled6 is True and bool(refusal) and refusal == expected_tpl
        and "не умею" not in refusal.lower()
        and not err_phrase_like(refusal)
        and len(ctx.provider_calls) == before_calls,
        "handled=%s refusal=%r ==status_message=%s provider_delta=%d"
        % (handled6, refusal, refusal == expected_tpl,
           len(ctx.provider_calls) - before_calls))

    # revert штатным MiniApp-путём (DELETE override) + витрина (TTL реестра
    # способностей — до 60 c, документированный контракт)
    status, body = await ctx.api.req(
        "DELETE", "/api/config/chat/flags.image_generation_module_enabled",
        chat_id=SYNTH_A)
    out("I7_override_delete", status == 200,
        "status=%s body=%s" % (status, json.dumps(body)[:160]
                               if isinstance(body, dict) else str(body)[:120]))
    await invalidate_chat(ctx, SYNTH_A)
    st_on = await caps.resolve("image_generation", SYNTH_A)
    info("I7_probe_resolve", "status=%s (немедленно после снятия override)"
         % st_on.status)
    await asyncio.sleep(65)          # TTL-кэш реестра в прод-процессе
    status, body = await ctx.api.req("GET", "/api/speech/capabilities",
                                     chat_id=SYNTH_A)
    cap_img2 = next((c for c in ((body or {}).get("capabilities") or [])
                     if c.get("capability_id") == "image_generation"), {})
    out("I8_restored_ready", st_on.status == "ready"
        and cap_img2.get("status") == "ready",
        "probe_resolve=%s showcase_status=%s (после TTL 65s)"
        % (st_on.status, cap_img2.get("status")))


# ══════════ PHASE J: SOUL-AMD.8.7 — одно уместное уточнение ════════════════

async def phaseJ(ctx: Ctx) -> None:
    from services import capability_registry as caps
    from services import direct_capabilities as dcaps

    it = dcaps.detect_action_intent("сделай это", addressed=True)
    info("J0_intent", "intent=%s confidence=%s reason=%s actionable=%s"
         % (it.intent, it.confidence, it.reason, it.actionable))
    expected = caps.clarify_text()[0]
    sent_before = len(ctx.stub.sent)
    before_calls = len(ctx.provider_calls)
    handled, intent = await ctx.svc._image_capability_gate(
        SYNTH_A, "сделай это", fake_message("сделай это", MSG_J1), ctx.stub)
    sent = ctx.stub.sent[sent_before:]
    text = sent[-1]["text"] if sent else ""
    out("J1_clarify_gate",
        handled is True and bool(sent) and text == expected
        and len(sent) == 1
        and len(ctx.provider_calls) == before_calls
        and not err_phrase_like(text),
        "handled=%s sends=%d text=%r ==template=%s provider_delta=%d"
        % (handled, len(sent), text, text == expected,
           len(ctx.provider_calls) - before_calls))


# ══════ PHASE L: SOUL-AMD.5.17/8.6/8.9 — реальная доставка и send-fail ═════

async def phaseL(ctx: Ctx) -> None:
    from services import image_generation as ig
    from services import direct_capabilities as dcaps
    from services import capability_registry as caps
    from services import worker_budget as wb

    calls = ctx.provider_calls
    orig_post, orig_get = ig._generate_post, ig._generate_get

    async def spy_post(*args, **kwargs):
        calls.append("post")
        return await orig_post(*args, **kwargs)

    async def spy_get(*args, **kwargs):
        calls.append("get")
        return await orig_get(*args, **kwargs)

    ig._generate_post, ig._generate_get = spy_post, spy_get
    try:
        # L0: бюджетная защита
        try:
            shared_lim, chat_lim, src = await wb.image_limits(SYNTH_A)
            usage = await wb.get_usage(scope="chat:%d" % SYNTH_A)
            used_chat = next((int(u.get("used") or 0) for u in usage
                              if u.get("metric") == "image_calls"), 0)
            usage_g = await wb.get_usage(scope="global")
            used_shared = next((int(u.get("used") or 0) for u in usage_g
                                if u.get("metric") == "image_calls"), 0)
        except Exception as exc:  # noqa: BLE001
            shared_lim, chat_lim, used_chat, used_shared = -1, -1, 0, 0
            src = "ERR:%s" % type(exc).__name__
        info("L0_budget", "shared=%s used_shared=%s | chat=%s used_chat=%s "
                          "src=%s" % (shared_lim, used_shared, chat_lim,
                                      used_chat, src))
        budget_ok = ((shared_lim < 0 or used_shared + 2 <= shared_lim)
                     and (chat_lim < 0 or used_chat + 2 <= chat_lim))
        if not budget_ok:
            out("L0_budget_guard", False,
                "бюджет не позволяет 2 генерации — платные пробы пропущены "
                "(shared=%s/%s chat=%s/%s)"
                % (used_shared, shared_lim, used_chat, chat_lim))
            return

        q1 = "Бот, нарисуй минимальный мем: кот спит на клавиатуре"
        it1 = dcaps.detect_action_intent(q1, addressed=True)
        info("L1_intent", "intent=%s confidence=%s actionable=%s"
             % (it1.intent, it1.confidence, it1.actionable))

        reachable_target = (ctx.reach.get(SYNTH_A) or ctx.reach.get(OWNER_DM))
        if ctx.real_bot is None or not reachable_target:
            out("L1_real_delivery", False,
                "реальный бот/достижимый чат недоступны (bot=%s A=%s dm=%s) — "
                "позитивная реальная доставка не выполнима"
                % (ctx.real_bot is not None, ctx.reach.get(SYNTH_A),
                   ctx.reach.get(OWNER_DM)))
        else:
            redirect = ctx.send_target if not ctx.reach.get(SYNTH_A) else None
            rec_bot = RecordingBot(ctx.real_bot, redirect_to=redirect)
            before = len(calls)
            block = await ctx.svc._image_pre_gate_block(
                SYNTH_A, q1, rec_bot, fake_message(q1, MSG_L1), SYNTH_USER,
                correlation_id=CORR + "-draw-l1", intent=it1,
                intent_confirms=bool(it1.actionable))
            n_gen = len(calls) - before
            call = rec_bot.calls[-1] if rec_bot.calls else {}
            out("L1_real_delivery",
                block.startswith('<image_result status="ok" delivery="sent"')
                and n_gen == 1 and bool(call.get("ok")),
                "provider_calls=%d send=%s block=%r"
                % (n_gen, json.dumps(call, ensure_ascii=False), block[:140]))
            info("L1_redirect", "redirect_to=%r (синтетика достижима=%s)"
                 % (redirect, ctx.reach.get(SYNTH_A)))
            if call.get("ok") and call.get("target") != SYNTH_A:
                try:
                    await ctx.real_bot.delete_message(call["target"],
                                                      call["message_id"])
                    info("L1_delete", "тестовое сообщение удалено из %s "
                         "(mid=%s)" % (call["target"], call["message_id"]))
                except Exception as exc:  # noqa: BLE001
                    info("L1_delete", "delete FAILED %s: %s"
                         % (type(exc).__name__, str(exc)[:120]))

            # L2: повтор того же хода — без дубля
            before = len(calls)
            n_before = len(rec_bot.calls)
            block2 = await ctx.svc._image_pre_gate_block(
                SYNTH_A, q1, rec_bot, fake_message(q1, MSG_L1), SYNTH_USER,
                correlation_id=CORR + "-draw-l1", intent=it1,
                intent_confirms=bool(it1.actionable))
            out("L2_replay_no_dup",
                ('delivery="already"' in block2) and (len(calls) - before) == 0
                and len(rec_bot.calls) == n_before,
                "provider_calls=%d new_sends=%d block=%r"
                % (len(calls) - before, len(rec_bot.calls) - n_before,
                   block2[:140]))

        # L3: send-fail — реальная ошибка Telegram (цель недостижима)
        if os.getenv("W2_SKIP_L3") == "1":
            info("L3_skip", "W2_SKIP_L3=1: send-fail уже подтверждён в прогоне "
                 "№1 (eveidence run-1: 'chat not found') — пропуск")
        else:
            fail_chat = SYNTH_A if not ctx.reach.get(SYNTH_A) else SYNTH_B
            if ctx.real_bot is None or ctx.reach.get(fail_chat):
                out("L3_send_fail_real", False,
                    "нет заведомо недостижимого чата для send-fail "
                    "(A=%s B=%s)" % (ctx.reach.get(SYNTH_A),
                                     ctx.reach.get(SYNTH_B)))
            else:
                q2 = "Бот, нарисуй минимальный мем: кактус в шляпе"
                it2 = dcaps.detect_action_intent(q2, addressed=True)
                rec_bot2 = RecordingBot(ctx.real_bot)   # без редиректа
                before = len(calls)
                block3 = await ctx.svc._image_pre_gate_block(
                    fail_chat, q2, rec_bot2, fake_message(q2, MSG_L3,
                                                          chat_id=fail_chat),
                    SYNTH_USER, correlation_id=CORR + "-draw-l3", intent=it2,
                    intent_confirms=bool(it2.actionable))
                n_gen3 = len(calls) - before
                call3 = rec_bot2.calls[-1] if rec_bot2.calls else {}
                deliv_tpl = caps.failure_text("delivery_failed")[0]
                no_sent = ('status="error"' in block3
                           and 'reason="delivery_failed"' in block3
                           and 'delivery="sent"' not in block3
                           and "Ничего не отправлено" in block3
                           and deliv_tpl in block3)
                out("L3_send_fail_real",
                    bool(call3) and call3.get("ok") is False and n_gen3 >= 1
                    and no_sent,
                    "provider_calls=%d send=%s block=%r"
                    % (n_gen3, json.dumps({k: call3.get(k) for k in
                                           ("ok", "error", "error_text")},
                                          ensure_ascii=False), block3[:200]))

        # L4: журнал резервов (единый механизм доставки/квоты)
        try:
            rows = await pg_fetch(
                ctx, "SELECT reservation_key, chat_id, source, message_id, day, "
                     "status, error_code, delivery_failed FROM image_reservation "
                     "WHERE reservation_key LIKE $1 "
                     "ORDER BY created_at DESC LIMIT 6", "%d:%%" % SYNTH_A)
            info("L4_journal", json.dumps([{k: str(v) for k, v in r.items()}
                                           for r in rows],
                                          ensure_ascii=False))
            committed_ok = any(str(r.get("status")) == "committed"
                               and not r.get("delivery_failed") for r in rows)
            committed_fail = any(str(r.get("status")) == "committed"
                                 and r.get("delivery_failed") for r in rows)
            out("L4_journal_states", committed_ok and committed_fail,
                "committed_ok=%s committed_delivery_failed=%s rows=%d"
                % (committed_ok, committed_fail, len(rows)))
        except Exception as exc:  # noqa: BLE001
            out("L4_journal_states", False, "ERROR=%s" % type(exc).__name__)
    finally:
        ig._generate_post, ig._generate_get = orig_post, orig_get


# ══════ PHASE K: SOUL-AMD.8.8 — правдивые отказы no-key и quota ════════════

async def phaseK(ctx: Ctx) -> None:
    from services import capability_registry as caps
    from services import worker_budget as wb

    # K1: нет ключа (per-chat override; ГЛОБАЛЬНЫЙ ключ не трогается)
    await raw_chat_override(ctx, SYNTH_A, "keys.image_api_key", "")
    await invalidate_chat(ctx, SYNTH_A)
    st_nk = await caps.resolve("image_generation", SYNTH_A)
    out("K1_no_key_state",
        st_nk.status == "not_configured" and st_nk.detail == "key_absent",
        "status=%s reason=%s detail=%s"
        % (st_nk.status, st_nk.reason_code, st_nk.detail))
    expected_nk = caps.status_message(st_nk)[0]
    sent_before = len(ctx.stub.sent)
    before_calls = len(ctx.provider_calls)
    handled_nk, _it_nk = await ctx.svc._image_capability_gate(
        SYNTH_A, FACE, fake_message(FACE, MSG_K1), ctx.stub)
    refusal = (ctx.stub.sent[-1]["text"]
               if len(ctx.stub.sent) > sent_before else "")
    out("K1_no_key_refusal",
        handled_nk is True and bool(refusal) and refusal == expected_nk
        and "не умею" not in refusal.lower()
        and not err_phrase_like(refusal)
        and len(ctx.provider_calls) == before_calls,
        "handled=%s refusal=%r ==status_message=%s provider_delta=%d"
        % (handled_nk, refusal, refusal == expected_nk,
           len(ctx.provider_calls) - before_calls))
    await drop_chat_override(ctx, SYNTH_A, "keys.image_api_key")
    await invalidate_chat(ctx, SYNTH_A)
    st_back = await caps.resolve("image_generation", SYNTH_A)
    info("K1_reverted", "status=%s после снятия per-chat override ключа "
         "(глобальный ключ не изменялся)" % st_back.status)

    # K2: квота исчерпана (реальная бухгалтерия: used >= limit)
    usage = await wb.get_usage(scope="chat:%d" % SYNTH_A)
    used = next((int(u.get("used") or 0) for u in usage
                 if u.get("metric") == "image_calls"), 0)
    limit = max(1, used)
    status, detail = await set_chat_overrides(ctx, SYNTH_A, [
        {"key": "limits.image_daily_limit", "value": limit}])
    info("K2_set", "used=%s limit_override=%s status=%s %s"
         % (used, limit, status, detail))
    await invalidate_chat(ctx, SYNTH_A)
    st_q = await caps.resolve("image_generation", SYNTH_A)
    out("K2_quota_state",
        st_q.status == "quota_exhausted" and used >= 1,
        "status=%s reason=%s detail=%s used=%s limit=%s"
        % (st_q.status, st_q.reason_code, st_q.detail, used, limit))
    expected_q = caps.status_message(st_q)[0]
    sent_before = len(ctx.stub.sent)
    before_calls = len(ctx.provider_calls)
    handled_q, _it_q = await ctx.svc._image_capability_gate(
        SYNTH_A, FACE, fake_message(FACE, MSG_K2), ctx.stub)
    refusal_q = (ctx.stub.sent[-1]["text"]
                 if len(ctx.stub.sent) > sent_before else "")
    out("K2_quota_refusal",
        handled_q is True and bool(refusal_q) and refusal_q == expected_q
        and "не умею" not in refusal_q.lower()
        and not err_phrase_like(refusal_q)
        and len(ctx.provider_calls) == before_calls,
        "handled=%s refusal=%r ==status_message=%s provider_delta=%d"
        % (handled_q, refusal_q, refusal_q == expected_q,
           len(ctx.provider_calls) - before_calls))
    await drop_chat_override(ctx, SYNTH_A, "limits.image_daily_limit")
    await invalidate_chat(ctx, SYNTH_A)
    st_q2 = await caps.resolve("image_generation", SYNTH_A)
    out("K2_restored", st_q2.status == "ready",
        "status=%s detail=%s" % (st_q2.status, str(st_q2.detail)[:60]))


# ═════════════════ PHASE M: SOUL-AMD.8.11 — видео ═══════════════════════════

async def phaseM(ctx: Ctx) -> None:
    from services import capability_registry as caps
    st = await caps.resolve("video_summary", SYNTH_A)
    out("M1_video_state",
        st.status == "not_configured"
        and st.reason_code == "media_source_unconfigured",
        "status=%s reason=%s detail=%s (остаток подтверждён; сценарий без "
        "медиа-источника невыполним)" % (st.status, st.reason_code,
                                         str(st.detail)[:80]))


# ═══════════════════════════════ main ═══════════════════════════════════════

async def cleanup(ctx: Ctx) -> None:
    try:
        await reset_chat_overrides(ctx, SYNTH_A)
    except Exception:  # noqa: BLE001
        pass
    try:
        await pg_exec(ctx, "DELETE FROM chat_profiles WHERE chat_id=$1",
                      SYNTH_A)
    except Exception:  # noqa: BLE001
        pass
    try:
        await sqlite_exec(
            ctx, "DELETE FROM throttle_state WHERE chat_id IN (?,?)",
            (SYNTH_A, SYNTH_B))
    except Exception as exc:  # noqa: BLE001
        info("FINAL_CLEANUP_NOTE", "throttle delete: %s" % type(exc).__name__)
    try:
        await pg_exec(ctx, "DELETE FROM image_reservation WHERE chat_id=$1 "
                           "AND status='reserved'", SYNTH_A)
    except Exception:  # noqa: BLE001
        pass
    rows = await sqlite_fetch(
        ctx, "SELECT count(*) AS n FROM throttle_state WHERE chat_id IN (?,?)",
        (SYNTH_A, SYNTH_B))
    info("FINAL_THROTTLE_LEFTOVER", str(rows[0]["n"] if rows else "?"))
    rows = await pg_fetch(
        ctx, "SELECT chat_id FROM chat_profiles WHERE chat_id=$1", SYNTH_A)
    info("FINAL_PROFILE_LEFTOVER", str(len(rows)))
    rows = await pg_fetch(
        ctx, "SELECT chat_id FROM chat_profiles WHERE chat_id=$1", SYNTH_B)
    info("FINAL_PROFILE_B_LEFTOVER", str(len(rows)))
    rows = await pg_fetch(ctx, "SELECT value FROM bot_settings "
                               "WHERE key IN ('limits.chat_burst_limit',"
                               " 'limits.chat_cooldown_seconds')")
    info("FINAL_GLOBAL_LIMITS",
         json.dumps([{k: str(v)[:40] for k, v in r.items()} for r in rows],
                    ensure_ascii=False))
    rows = await pg_fetch(ctx, "SELECT value FROM bot_settings "
                               "WHERE key='style.policy'")
    doc = rows[0]["value"] if rows else None
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except Exception:  # noqa: BLE001
            doc = None
    info("FINAL_STYLE", "revision=%s rules=%s soft=%s"
         % ((doc or {}).get("revision"),
            len((doc or {}).get("rules") or []),
            len((doc or {}).get("soft_instructions") or [])))


async def main() -> int:
    ctx = Ctx()
    await bootstrap(ctx)
    await phase0(ctx)
    try:
        ctx.svc = await build_service(ctx)
        info("SVC", "DirectChatService готов (llm=None — платные LLM-стадии "
                    "невозможны)")
    except Exception as exc:  # noqa: BLE001
        out("SVC", False, "build failed: %s: %s" % (type(exc).__name__, exc))
        return 2

    phases = (("G", phaseG), ("H", phaseH), ("S", phaseS), ("I", phaseI),
              ("J", phaseJ), ("L", phaseL), ("K", phaseK), ("M", phaseM))
    only = os.getenv("W2_PHASES", "").strip().upper()
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

    await cleanup(ctx)
    if ctx.real_bot is not None:
        try:
            await ctx.real_bot.session.close()
        except Exception:  # noqa: BLE001
            pass
    n_ok = sum(1 for _, ok, _ in RESULTS if ok)
    n_all = len(RESULTS)
    print("W2 SUMMARY ok=%d/%d" % (n_ok, n_all), flush=True)
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
        print("W2 FATAL %s: %s" % (type(exc).__name__, str(exc)[:400]))
        rc = 4
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    print("W2 RC=%d" % rc, flush=True)
    # Гарантированный выход: хвосты asyncpg/сокетов не держат процесс.
    os._exit(rc if isinstance(rc, int) else 4)
