"""P0 save/init audit — часть D: карта потребителей + проверка минимального фикса.

1) Полный smoke chat-scope сохранений SOUL-1 (включая варианты, когда
   переопределение чата уже существует) — что видит UI.
2) Проверка МИНИМАЛЬНОГО фикса (предложение): передавать pg в
   chat_params.set_chat_params → тот же HTTP-путь становится успешным и
   переживает read-after-write из хранилища.

Подмена PG — двойник уровня asyncpg (таблицы chat_profiles/bot_settings в
памяти). Код продукта НЕ меняется: только monkeypatch на время прогона.

Запуск:
  .venv\\Scripts\\python.exe plans/features/p0-save-init-ux/evidence/audit-2026-10-18/probe_part_d.py
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
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

from config.settings import settings                        # noqa: E402
from services.config_cache import ConfigCache                # noqa: E402
from services.permissions import Permissions                # noqa: E402
from services import chat_params                            # noqa: E402
from services import prompt_registry as pr                  # noqa: E402
from web.app import create_app                              # noqa: E402

UID = 5885953495
CHAT = -1002661910336          # PERMsoc (реальный чат владельца)
REPORT: dict = {}


# ── PG-двойник с реальными таблицами в памяти ────────────────────────────────

class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class MemPg:
    def __init__(self):
        self.settings: dict = {}
        self.profiles: dict = {}
        self.history: list = []
        self.pool = self

    def acquire(self):
        return _Ctx(self)

    async def execute(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("SELECT pg_advisory_xact_lock") or \
                s.startswith("SELECT pg_notify"):
            return "SELECT 1"
        if s.startswith("INSERT INTO chat_lore_history"):
            self.history.append(args)
            return "INSERT 0 1"
        if s.startswith("INSERT INTO bot_settings"):
            self.settings[args[0]] = (json.loads(args[1]), args[2])
            return "INSERT 0 1"
        if s.startswith("UPDATE chat_profiles SET gates_opt_in"):
            return "UPDATE 1"
        if s.startswith("INSERT INTO chat_profiles"):
            self.profiles.setdefault(args[0], {
                "chat_id": args[0], "updated_at": "2026-10-18T09:00:00+00:00",
                "chat_params": json.loads(args[3]), "gates_opt_in": args[4]})
            return "INSERT 0 1"
        raise AssertionError(f"unhandled execute: {s[:80]}")

    async def fetch(self, sql, *args):
        return []

    async def fetchrow(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("SELECT chat_id, updated_at, chat_params"):
            row = self.profiles.get(args[0])
            return dict(row) if row else None
        if s.startswith("UPDATE chat_profiles SET chat_params"):
            if len(args) == 3:                      # optimistic (locked)
                row = self.profiles.get(args[0])
                if row is None or row["updated_at"] != args[2]:
                    return None
            payload = json.loads(args[1])
            ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
            self.profiles[args[0]] = {"chat_id": args[0], "updated_at": ts,
                                      "chat_params": payload,
                                      "gates_opt_in": True}
            return dict(self.profiles[args[0]])
        raise AssertionError(f"unhandled fetchrow: {s[:80]}")

    async def fetchval(self, sql, *args):
        return 0

    def transaction(self):
        return _Txn()


class _Ctx:
    def __init__(self, pg):
        self.pg = pg

    async def __aenter__(self):
        return self.pg

    async def __aexit__(self, *exc):
        return False


class StubCache:
    """chat_params._chat_params_cache-двойник (чтение override'ов)."""

    def __init__(self, pg: MemPg):
        self.pg = pg

    async def get_chat_params(self, chat_id):
        row = self.pg.profiles.get(int(chat_id))
        return dict(row["chat_params"]) if row else {}

    async def get_chat_params_full(self, chat_id):
        row = self.pg.profiles.get(int(chat_id))
        return (dict(row["chat_params"]) if row else {},
                row["updated_at"] if row else None)

    async def invalidate_chat(self, chat_id):
        return None


class PgDb:
    """PgDatabase-двойник: .pool = MemPg (для передачи pg=...)."""

    def __init__(self, pg: MemPg):
        self.pool = pg


def make_seeded_pg(with_overrides: bool) -> MemPg:
    pg = MemPg()
    params = {"v": 1, "overrides": {}, "gates": {}, "keys": {},
              "perm_overrides": {}, "meta": {}}
    if with_overrides:
        params["overrides"] = {
            "style.policy": {"v": 1, "revision": 1, "rules": [
                {"id": "r1", "kind": "emoji.hard.off", "strictness": "hard",
                 "scope": "global", "reason": "owner", "params": {}}],
                "soft_instructions": []},
            "character.expression": {"enabled": True, "wit": "high",
                                     "revision": 2, "note": "старое"},
            "character.core": {"revision": 3, "detail_level": "full",
                               "full_text": "локальный характер",
                               "compact_text": ""},
            "humor.craft": {"enabled": True},
            "humor.feedback": {"paused": True},
        }
    pg.profiles[CHAT] = {"chat_id": CHAT, "updated_at": "2026-10-18T09:00:00+00:00",
                         "chat_params": params, "gates_opt_in": True}
    return pg


def make_cache(pg: MemPg) -> ConfigCache:
    cache = ConfigCache(pg=PgDb(pg))
    cache._admins[UID] = "global_admin"
    cache._roles["global_admin"] = {"permissions": {"wildcard": True},
                                    "is_custom": False,
                                    "role_type": "global_admin"}
    cache._permissions["global_admin"] = Permissions.from_dict({"wildcard": True})
    cache._initialized = True
    cache._pg_available = True
    return cache


def init_data() -> str:
    data = {"auth_date": str(int(time.time())),
            "user": json.dumps({"id": UID, "first_name": "Audit"},
                               separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", settings.API_TOKEN.encode(),
                      hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def client_for(pg: MemPg):
    from starlette.testclient import TestClient
    cache = make_cache(pg)
    client = TestClient(create_app(cache))
    client.headers.update({"X-Telegram-Init-Data": init_data()})
    return client, cache


def call(client, method, path, body=None, chat=CHAT):
    headers = {} if chat is None else {"X-Chat-Id": str(chat)}
    resp = client.request(method, path, headers=headers, json=body)
    try:
        payload = resp.json()
    except Exception:                                # noqa: BLE001
        payload = {"raw": resp.text[:200]}
    return resp.status_code, payload


CHAT_SAVES = [
    ("POST /speech/style", "POST", "/api/speech/style",
     {"document": {"rules": [{"id": "r1", "kind": "hard_profanity_off",
                              "strictness": "hard", "scope": "global",
                              "reason": "audit", "params": {}}],
                   "soft_instructions": []},
      "scope": "chat", "reason": "owner_edit:style_policy"}),
    ("POST /speech/expression", "POST", "/api/speech/expression",
     {"values": {"wit": "high", "sharpness": "normal", "profanity": "off",
                 "verbosity": "short", "note": "аудит"}, "scope": "chat"}),
    ("POST /speech/core/meta", "POST", "/api/speech/core/meta",
     {"detail_level": "compact", "scope": "chat"}),
    ("POST /speech/block/core.personality", "POST",
     f"/api/speech/block/{pr.CORE_FULL_BLOCK_ID}",
     {"text": "аудит: чат-редакция", "scope": "chat", "reason": "owner_edit"}),
    ("POST /speech/style/reset-chat", "POST", "/api/speech/style/reset-chat", {}),
    ("POST /speech/expression/reset-chat", "POST",
     "/api/speech/expression/reset-chat", {}),
    ("POST /speech/block/core.personality/reset(mode=chat)", "POST",
     f"/api/speech/block/{pr.CORE_FULL_BLOCK_ID}/reset", {"mode": "chat"}),
    ("POST /speech/humor/craft", "POST", "/api/speech/humor/craft",
     {"enabled": False, "scope": "chat"}),
    ("POST /speech/learning/humor(pause)", "POST",
     "/api/speech/learning/humor", {"action": "pause"}),
]


def run_matrix(client, label: str) -> dict:
    out = {}
    for name, method, path, body in CHAT_SAVES:
        try:
            status, payload = call(client, method, path, body)
        except Exception as exc:                     # noqa: BLE001
            out[name] = {"exception": type(exc).__name__,
                         "message": str(exc)[:200]}
            continue
        detail = payload.get("detail") if isinstance(payload, dict) else None
        out[name] = {"status": status, "detail": detail,
                     "ok": payload.get("ok") if isinstance(payload, dict) else None,
                     "reason": ((payload.get("result") or {}).get("reason")
                                if isinstance(payload.get("result"), dict) else None)}
    REPORT[label] = out
    return out


def main() -> int:
    # Ось HUMOR_FEEDBACK_ENABLED (default OFF в тест-окружении) — включаем,
    # иначе endpoint /speech/learning/humor возвращает 409 humor_feedback_disabled
    # ДО записи и её механизм не наблюдается.
    from services import mca_gates, mca_humor_feedback
    mca_gates.humor_feedback_enabled = lambda: True
    REPORT["gate_humor_feedback"] = bool(mca_humor_feedback.gate_on())

    # D1: chat-scope с существующими override'ами (реальный прод-сценарий)
    pg = make_seeded_pg(with_overrides=True)
    chat_params.set_chat_params_cache(StubCache(pg))
    client, cache = client_for(pg)
    before = run_matrix(client, "D1_chat_scope_with_overrides_status_quo")

    # D2: минимальный фикс — pg прокидывается в set_chat_params
    real_set = chat_params.set_chat_params

    async def fixed_set(chat_id, patch, *, pg=None, **kw):
        return await real_set(chat_id, patch,
                              pg=pg if pg is not None else PgDb(PG_HOLDER["pg"]),
                              **kw)

    PG_HOLDER = {"pg": pg}
    chat_params.set_chat_params = fixed_set          # monkeypatch (только прогон)
    try:
        client2, cache2 = client_for(pg)
        after = run_matrix(client2, "D2_chat_scope_with_minimal_fix")
    finally:
        chat_params.set_chat_params = real_set

    # D3: read-after-write доказательство на слое сервисов (тот же fix)
    pg3 = make_seeded_pg(with_overrides=False)
    chat_params.set_chat_params_cache(StubCache(pg3))
    PG_HOLDER["pg"] = pg3
    chat_params.set_chat_params = fixed_set
    try:
        from services import style_policy
        from web.api import speech as S
        cache3 = make_cache(pg3)
        sres = asyncio.run(style_policy.save_policy_document(
            {"rules": [{"id": "r1", "kind": "hard_profanity_off",
                        "strictness": "hard", "scope": "global",
                        "reason": "audit", "params": {}}],
             "soft_instructions": [{"id": "s1", "text": "короче",
                                    "scope": "global", "enabled": True}]},
            chat_id=CHAT, cache=cache3, actor=UID, reason="owner_edit"))
        eres = asyncio.run(S._write_expression(cache3, CHAT, {
            "wit": "high", "profanity": "off", "verbosity": "short",
            "note": "аудит"}))
        cmeta = asyncio.run(S._write_core_meta(cache3, CHAT,
                                               S.CoreMeta(detail_level="compact",
                                                          scope="chat"),
                                               actor=UID))
    finally:
        chat_params.set_chat_params = real_set
    stored = pg3.profiles[CHAT]["chat_params"]["overrides"]
    REPORT["D3_read_after_write_with_fix"] = {
        "style_save": sres, "expression_save": eres, "core_meta_save": cmeta,
        "stored_style_rules": len((stored.get("style.policy") or {}).get("rules") or []),
        "stored_expression_wit": (stored.get("character.expression") or {}).get("wit"),
        "stored_core_level": (stored.get("character.core") or {}).get("detail_level"),
        "reread_expression_view": asyncio.run(
            S._expression_payload(cache3, CHAT))["values"],
        "reread_style_revision": asyncio.run(
            S._style_payload(cache3, CHAT)).get("revision"),
    }

    with open(os.path.join(os.path.dirname(__file__), "probe_part_d.json"), "w",
              encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2, default=str)
    print(json.dumps(REPORT, ensure_ascii=False, indent=2, default=str)[:9000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
