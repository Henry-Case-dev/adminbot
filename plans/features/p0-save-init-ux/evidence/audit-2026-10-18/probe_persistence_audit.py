"""P0 sаve/init audit — локальное воспроизведение ошибок сохранения SOUL-1.

Lane: PERSIST-AUDIT (read-only аудит; код не меняется).

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe plans/features/p0-save-init-ux/evidence/audit-2026-10-18/probe_persistence_audit.py

Стенд: РЕАЛЬНЫЙ код (services/*, web/api/speech.py, web/api/routes.py, web/app.py)
+ РЕАЛЬНЫЙ FastAPI-роут через ASGI + РЕАЛЬНАЯ TMA-авторизация (HMAC initData,
settings.API_TOKEN). Подменяются только внешние границы:
  * PostgreSQL — двойник уровня asyncpg (пул/соединение), с режимами
    pool=None (PG-only-путь недоступен) и execute-raises (ошибка записи);
  * process-глобальный ChatParamsCache — не инициализирован (PG-двойник без
    строк chat_profiles), чтение override'ов fail-open {} (как PG-down).

Двойник НЕ подменяет вещество дефекта: воспроизведение A1/A2/A3 и весь
chat-scope HTTP-путь падают ещё ДО обращения к PG (services/chat_params.py:422-424).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import logging
import os
import sys
import time
import traceback
from urllib.parse import urlencode

def _find_root(start: str) -> str:
    cur = os.path.abspath(start)
    while cur and cur != os.path.dirname(cur):
        if os.path.isfile(os.path.join(cur, "config", "settings.py")):
            return cur
        cur = os.path.dirname(cur)
    raise RuntimeError("repo root not found")


ROOT = _find_root(os.path.dirname(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

sys.stdout.reconfigure(encoding="utf-8")

REPORT: dict = {"root": ROOT, "sections": []}
LOG_BUFFER = io.StringIO()
logging.basicConfig(stream=LOG_BUFFER, level=logging.DEBUG,
                    format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

from config.settings import settings                      # noqa: E402
from services.config_cache import ConfigCache              # noqa: E402
from services.permissions import Permissions              # noqa: E402
from services import chat_params, style_policy, prompt_factory  # noqa: E402
from services import prompt_registry as pr                # noqa: E402
from web.api import speech as S                           # noqa: E402
from web.app import create_app                            # noqa: E402

UID = 5885953495
CHAT = -1001234567890          # групповой чат (скоуп «чат»)
CHAT_STR = str(CHAT)


def section(name: str, payload: dict) -> None:
    REPORT["sections"].append({"name": name, **payload})


def log_tail(pattern: str, limit: int = 6) -> list[str]:
    out = []
    for line in LOG_BUFFER.getvalue().splitlines():
        if pattern in line:
            out.append(line.strip()[:400])
    return out[-limit:]


# ── двойник PostgreSQL (уровень asyncpg-пула) ────────────────────────────────

class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Conn:
    def __init__(self, owner):
        self._owner = owner

    async def execute(self, sql, *args):
        self._owner.calls.append(("execute", sql.strip().splitlines()[0][:60], args))
        if self._owner.raise_on_write:
            raise RuntimeError("simulated PG write failure (asyncpg)")
        return "UPDATE 1"

    async def fetch(self, sql, *args):
        self._owner.calls.append(("fetch", sql.strip().splitlines()[0][:60], args))
        return []

    async def fetchrow(self, sql, *args):
        self._owner.calls.append(("fetchrow", sql.strip().splitlines()[0][:60], args))
        return None

    async def fetchval(self, sql, *args):
        return 0

    def transaction(self):
        return _Txn()


class _Pool:
    def __init__(self, owner):
        self._owner = owner

    def acquire(self):
        owner = self._owner

        class _CM:
            async def __aenter__(self):
                return _Conn(owner)

            async def __aexit__(self, *exc):
                return False

        return _CM()


class StubPg:
    """PgDatabase-двойник: pool=None (PG-only путь) либо pool с ошибкой записи."""

    def __init__(self, mode: str = "no_pool"):
        self.mode = mode
        self.calls: list = []
        self.pool = None if mode == "no_pool" else _Pool(self)
        self.raise_on_write = (mode == "write_fails")

    async def connect(self):
        return None

    async def init(self, seed_settings: bool = True):
        return None


def make_cache(mode: str = "no_pool") -> ConfigCache:
    cache = ConfigCache(pg=StubPg(mode))
    cache._admins[UID] = "global_admin"
    cache._roles["global_admin"] = {
        "permissions": {"wildcard": True}, "is_custom": False,
        "role_type": "global_admin"}
    cache._permissions["global_admin"] = Permissions.from_dict({"wildcard": True})
    cache._initialized = True
    cache._pg_available = (mode != "no_pool")
    return cache


def make_init_data(user_id: int = UID) -> str:
    data = {
        "auth_date": str(int(time.time())),
        "query_id": "AAtest",
        "user": json.dumps({"id": user_id, "first_name": "Audit"},
                           separators=(",", ":")),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", settings.API_TOKEN.encode(),
                      hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def run(coro):
    try:
        return asyncio.run(coro)
    except Exception as exc:                       # noqa: BLE001
        return exc


# ═══════════════════════════════════════════════════════════════════════════
# A. Прямые вызовы нижних слоёв (без HTTP/PG)
# ═══════════════════════════════════════════════════════════════════════════

def part_a() -> None:
    # A1. chat_params.set_chat_params БЕЗ pg — требует ли пул?
    try:
        asyncio.run(chat_params.set_chat_params(CHAT, {"overrides": {}}))
        a1 = {"raised": None, "note": "вызов прошёл без pg"}
    except Exception as exc:                       # noqa: BLE001
        a1 = {"raised": type(exc).__name__, "message": str(exc),
              "module": type(exc).__module__}
    section("A1 chat_params.set_chat_params(pg=None)", a1)

    # A2. style_policy.save_policy_document — chat-scope (путь POST /api/speech/style)
    cache = make_cache()
    doc = {"rules": [{"id": "r1", "kind": "quotes", "strictness": "hard",
                      "scope": "global", "reason": "audit",
                      "params": {}}],
           "soft_instructions": [{"id": "s1", "text": "короче", "scope": "global",
                                  "enabled": True}]}
    before = len(LOG_BUFFER.getvalue())
    res2 = asyncio.run(style_policy.save_policy_document(
        doc, chat_id=CHAT, cache=cache, actor=UID, reason="owner_edit:style_policy"))
    section("A2 save_policy_document(chat_id)", {
        "result": res2,
        "internal_trace": log_tail("document save failed", 3),
        "logged_delta": LOG_BUFFER.getvalue()[before:][:600],
    })

    # A2b. тот же документ глобально (путь scope=global) — для контраста
    res2b = asyncio.run(style_policy.save_policy_document(
        doc, chat_id=None, cache=make_cache("pool_ok"), actor=UID,
        reason="owner_edit:style_policy"))
    section("A2b save_policy_document(global)", {"result": res2b})

    # A3. speech._write_expression — chat-scope (путь POST /api/speech/expression)
    cache = make_cache()
    res3 = asyncio.run(S._write_expression(cache, CHAT, {
        "wit": "high", "sharpness": "normal", "profanity": "off",
        "verbosity": "short", "note": "аудит"}))
    section("A3 _write_expression(chat_id)", {
        "result": res3,
        "internal_trace": log_tail("expression chat write failed", 3),
    })

    # A4. prompt_factory.write_speech_value — chat-scope (путь POST /api/speech/block/{id})
    cache = make_cache()
    try:
        res4 = asyncio.run(prompt_factory.write_speech_value(
            pr.CORE_FULL_BLOCK_ID, "полный характер (аудит)", cache=cache,
            actor=UID, reason="owner_edit:core.full", chat_id=CHAT))
        a4 = {"result": res4}
    except Exception as exc:                       # noqa: BLE001
        a4 = {"raised": type(exc).__name__, "message": str(exc),
              "trace_tail": traceback.format_exc().strip().splitlines()[-6:]}
    section("A4 prompt_factory.write_speech_value(chat_id)", a4)

    # A5. speech._write_core_meta — chat-scope (путь POST /api/speech/core/meta)
    cache = make_cache()
    res5 = asyncio.run(S._write_core_meta(cache, CHAT,
                                         S.CoreMeta(detail_level="full",
                                                    enabled=True,
                                                    scope="chat"), actor=UID))
    section("A5 _write_core_meta(chat_id)", {
        "result": res5,
        "internal_trace": log_tail("core meta chat write failed", 3),
    })

    # A6. prompt_factory.reset_chat_override — chat-сброс (путь POST .../reset mode=chat)
    try:
        res6 = asyncio.run(prompt_factory.reset_chat_override(CHAT,
                                                             pr.CORE_FULL_BLOCK_ID))
        a6 = {"result": res6}
    except Exception as exc:                       # noqa: BLE001
        a6 = {"raised": type(exc).__name__, "message": str(exc)}
    section("A6 reset_chat_override(chat_id, pg=None)", a6)


# ═══════════════════════════════════════════════════════════════════════════
# B. HTTP через реальный ASGI-стек + реальная TMA-авторизация
# ═══════════════════════════════════════════════════════════════════════════

def make_client(mode: str = "no_pool"):
    from starlette.testclient import TestClient
    cache = make_cache(mode)
    app = create_app(cache)
    client = TestClient(app)
    client.headers.update({"X-Telegram-Init-Data": make_init_data()})
    return client, cache


def http(client, method: str, path: str, *, chat: str | None = CHAT_STR,
         body: dict | None = None) -> dict:
    headers = {} if chat is None else {"X-Chat-Id": chat}
    resp = client.request(method, path, headers=headers, json=body)
    try:
        payload = resp.json()
    except Exception:                              # noqa: BLE001
        payload = resp.text[:200]
    detail = payload.get("detail") if isinstance(payload, dict) else payload
    return {"status": resp.status_code, "detail": detail,
            "body_keys": sorted(payload.keys()) if isinstance(payload, dict) else None}


def part_b() -> None:
    client, cache = make_client("no_pool")

    # 1. Owner-симптом №2: Expression Settings (scope=chat)
    r_expr = http(client, "POST", "/api/speech/expression", chat=CHAT_STR, body={
        "values": {"wit": "high", "sharpness": "normal", "profanity": "off",
                   "verbosity": "short", "note": "аудит"},
        "scope": "chat"})
    section("B1 POST /api/speech/expression (X-Chat-Id)", {
        "http": r_expr,
        "ui_toast": "Не сохранено: " + str(r_expr["detail"]),
    })

    # 2. Owner-симптом №1: Speech Style Policy (scope=chat)
    r_style = http(client, "POST", "/api/speech/style", chat=CHAT_STR, body={
        "document": {"rules": [{"id": "r1", "kind": "quotes",
                                "strictness": "hard", "scope": "global",
                                "reason": "audit", "params": {}}],
                     "soft_instructions": []},
        "scope": "chat", "reason": "owner_edit:style_policy"})
    section("B2 POST /api/speech/style (X-Chat-Id)", {
        "http": r_style,
        "ui_toast": ("Документ не прошёл проверку или конфликт версии"
                     if r_style["status"] == 409 else "—"),
    })

    # 3..7 smoke остальных сохранений того же экрана (scope=chat)
    smoke_chat = {
        "core_meta_full": http(client, "POST", "/api/speech/core/meta",
                               chat=CHAT_STR,
                               body={"detail_level": "full", "scope": "chat"}),
        "core_meta_enabled": http(client, "POST", "/api/speech/core/meta",
                                  chat=CHAT_STR,
                                  body={"enabled": True, "scope": "chat"}),
        "core_block_full": http(client, "POST",
                                f"/api/speech/block/{pr.CORE_FULL_BLOCK_ID}",
                                chat=CHAT_STR,
                                body={"text": "аудит: полная редакция",
                                      "scope": "chat", "reason": "owner_edit"}),
        "style_reset_chat": http(client, "POST", "/api/speech/style/reset-chat",
                                 chat=CHAT_STR, body={}),
        "expression_reset_chat": http(client, "POST",
                                      "/api/speech/expression/reset-chat",
                                      chat=CHAT_STR, body={}),
        "block_reset_chat": http(client, "POST",
                                 f"/api/speech/block/{pr.CORE_FULL_BLOCK_ID}/reset",
                                 chat=CHAT_STR, body={"mode": "chat"}),
        "block_rollback_chat": http(
            client, "POST",
            f"/api/speech/block/{pr.CORE_FULL_BLOCK_ID}/rollback",
            chat=CHAT_STR, body={"sha256_12": "deadbeef0000", "scope": "chat"}),
    }
    section("B3 smoke: остальные chat-scope сохранения SOUL-1", smoke_chat)

    # 8. Глобальный scope того же клиента (PG-двойник без пула → in-memory set)
    client_g, cache_g = make_client("no_pool")
    r_glob_style = http(client_g, "POST", "/api/speech/style", chat=None, body={
        "document": {"rules": [], "soft_instructions": []}, "scope": "global"})
    r_glob_expr = http(client_g, "POST", "/api/speech/expression", chat=None,
                       body={"values": {"wit": "high", "scope": "global"},
                             "scope": "global"})
    stale = cache_g.get("character.expression")
    section("B4 global scope при недоступной записи в PG (следствие 1: тихий 200)",
            {"style": r_glob_style, "expression": r_glob_expr,
             "cache_value_present_after_failed_persist": bool(stale)})

    # 9. Ошибка записи в PG на глобальном пути (execute raises) — что видит UI
    client_w, cache_w = make_client("write_fails")
    r_glob_expr_w = http(client_w, "POST", "/api/speech/expression", chat=None,
                         body={"values": {"wit": "low", "note": "PG-сбой"},
                               "scope": "global"})
    after = cache_w.get("character.expression")
    reread = http(client_w, "GET", "/api/speech/expression", chat=None)
    section("B5 глобальный путь при ошибке записи в PG (следствие 2: расхождение)",
            {"post": r_glob_expr_w,
             "ui_toast": "Не сохранено: " + str(r_glob_expr_w["detail"]),
             "cache_in_memory_value": after,
             "reread_values": (reread["status"], str(reread["detail"])[:200])})


# ═══════════════════════════════════════════════════════════════════════════
# C. Round-trip и jsonb-строка: что читается после перезагрузки кэша из PG
# ═══════════════════════════════════════════════════════════════════════════

def part_c() -> None:
    """Кэш, загруженный ИЗ PG: value JSONB приходит строкой (asyncpg без
    json-кодека) — так же, как это делает ConfigCache._load_all →
    normalize_value. Ключи речевых документов в param_catalog ОТСУТСТВУЮТ,
    поэтому каст не выполняется (normalize_value возвращает as-is)."""
    from services.config_cache import ConfigCache as CC
    expr_doc = {"enabled": True, "wit": "high", "profanity": "off",
                "revision": 3, "updated_at": "2026-10-18T00:00:00Z"}
    style_doc = {"v": 1, "revision": 2, "rules": [{"id": "r1", "kind": "quotes",
                 "strictness": "hard", "scope": "global", "reason": "audit"}],
                 "soft_instructions": []}
    raw_rows = {"character.expression": json.dumps(expr_doc, ensure_ascii=False),
                "style.policy": json.dumps(style_doc, ensure_ascii=False),
                "character.core": json.dumps({"revision": 1,
                                              "full_text": "характер"},
                                             ensure_ascii=False)}
    cache = make_cache("no_pool")
    from services.param_catalog import normalize_value
    cache._settings = {k: normalize_value(k, v) for k, v in raw_rows.items()}

    expr_layer = asyncio.run(S._expression_document(cache, None))
    expr_payload = asyncio.run(S._expression_payload(cache, None))
    style_payload = asyncio.run(S._style_payload(cache, None))
    core_payload = asyncio.run(S._core_payload(cache, type("U", (), {"id": UID})(),
                                               type("C", (), {"is_global_admin": True,
                                                              "effective_permissions": None})(),
                                               None))
    section("C1 чтение документов после загрузки кэша из PG (jsonb→str)", {
        "types_in_cache": {k: type(v).__name__ for k, v in cache._settings.items()},
        "expression_document": expr_layer,
        "expression_payload_present": expr_payload["present"],
        "expression_values_view": expr_payload["values"],
        "expression_rendered_chars": len(expr_payload.get("rendered_text") or ""),
        "style_source": style_payload.get("source"),
        "style_rules_on_screen": len(style_payload.get("rules") or []),
        "style_document_flags": style_payload.get("document"),
        "core_inheritance": core_payload.get("inheritance"),
        "core_source_full": core_payload["editions"]["full"]["source"],
        "core_full_chars": core_payload["editions"]["full"]["chars"],
    })


def main() -> int:
    part_a()
    part_b()
    part_c()
    REPORT["logs"] = {
        "speech_write_errors": log_tail("write failed", 8),
        "style_policy_save_errors": log_tail("document save failed", 8),
        "chat_params_locks": log_tail("advisory lock", 4),
    }
    out = os.path.join(os.path.dirname(__file__), "probe_persistence_audit.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2)
    text = json.dumps(REPORT, ensure_ascii=False, indent=2)
    print(text)
    sys.stdout.flush()
    print(f"\n[probe] report -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
