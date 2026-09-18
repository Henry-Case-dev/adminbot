"""F5 `settings-persistence-audit-round1014` — регресс сохранения/реактивности.

Покрытие (spec F5 §3-§6, задачи T-1512…T-1522):
  * T-1512 инвентарь: каталог-инвариант F5 (Δ=0) + классификация per_chat
    (models.*/keys.* — глобальные, limits.* — per-chat);
  * T-1515 write-path/restart: sync-await запись `ConfigCache.set` немедленно
    попадает в PG-строки и переживает «рестарт» (новый ConfigCache читает те
    же строки); chat_params override переживает новый ChatParamsCache;
  * R10.9-4 (T-1519/T-1515): health-кэш статуса сбрасывается при записи
    `models.*`/`keys.*` (в т.ч. через реальный `_post_config_global`);
  * R10.4-7 (T-1518): cap RAG в direct-пути резолвится per-chat
    (`get_chat_param`), а не глобально;
  * R10.3-1/R10.5-2: per_chat=False (`models.*`/`keys.*`) — глобальный путь,
    серверный гейт 422 (маршрутизация чинится на фронте, gate не ослаблен).
"""
import json
import time
import types

import pytest

from services import param_catalog as pc
from services.chat_params import (
    ChatParamsCache,
    get_chat_param,
    set_chat_params,
    set_chat_params_cache,
)
from services.config_cache import ConfigCache
from services.param_catalog import get_by_pg_key


# ═══ T-1512: каталог-инвариант F5 (Δ = 0) ═══════════════════════════════════

class TestCatalogInvariant:
    def test_counts_unchanged(self):
        """F6 +1 PG-only → 435; 10.18 F1 +1 env-only BETTERSTACK_HOST
        (ADR-1018-1 D3) → 436/406/411/90/88/19; 10.19 F3 (UPD3 п.5) →
        437/407/412/92/90/20."""
        import dataclasses

        from config.settings import Settings
        assert len(pc.REGISTRY) == 441
        assert len(pc.GROUPS) == 92
        assert len(pc._TAB_BY_GROUP) == 90
        assert len(pc.TAB_RULES) == 20
        assert len({f.name for f in dataclasses.fields(Settings)}) == 411
        categorized = [s for s in pc.REGISTRY.values()
                       if s.category is not None]
        assert len(categorized) == 416

    def test_per_chat_classification(self):
        """Маршрутизация scope: models.*/keys.* — строго глобальные (per_chat
        False), limits/prompts/flags — per-chat. Это основа saveBlock/
        saveConfigItem/saveKeyItem global-ветки (R10.12-1)."""
        assert get_by_pg_key("models.llm_timeout").per_chat is False
        assert get_by_pg_key("keys.llm_api_key").per_chat is False
        assert get_by_pg_key("limits.graph_rag_context_max_chars").per_chat
        assert get_by_pg_key("flags.graph_rag_enabled").per_chat
        assert get_by_pg_key("prompts.direct_chat_system_prompt").per_chat


# ═══ T-1515: write-path → PG, переживает рестарт ════════════════════════════

class _SettingsConn:
    """bot_settings-стор: execute(INSERT) пишет, fetch отдаёт (PG-образ)."""

    def __init__(self):
        self.store = {}   # key → (json_str, category)

    async def execute(self, sql, *args):
        if "INSERT INTO bot_settings" in sql:
            self.store[args[0]] = (args[1], args[2])
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return [{"key": k, "value": v, "category": c, "updated_at": None}
                    for k, (v, c) in self.store.items()]
        return []


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm


class _Pg:
    def __init__(self, conn):
        self._pool = _Pool(conn)

    @property
    def pool(self):
        return self._pool


@pytest.mark.asyncio
async def test_bot_settings_save_survives_restart():
    """Сохранил → строка в PG-сторе сразу → «рестарт» (новый ConfigCache из
    тех же строк) → значение на месте (T-1515)."""
    conn = _SettingsConn()
    pg = _Pg(conn)
    cache1 = ConfigCache(pg=pg)
    cache1._pg_available = True      # init() не вызываем — эмулируем онлайн

    await cache1.set("limits.search_max_symbols", 8000, "limits")
    # sync-await: PG-строка записана немедленно (не fire-and-forget).
    assert "limits.search_max_symbols" in conn.store
    assert json.loads(conn.store["limits.search_max_symbols"][0]) == 8000

    # «Рестарт admin_bot»: свежий ConfigCache загружается из тех же строк.
    cache2 = ConfigCache(pg=pg)
    cache2._pg_available = True
    await cache2._load_all()
    assert cache2.get("limits.search_max_symbols") == 8000


@pytest.mark.asyncio
async def test_chat_override_survives_restart(monkeypatch):
    """set_chat_params (транзакция, await) → новый ChatParamsCache читает
    override из PG → get_chat_param отдаёт значение своего скоупа (T-1515)."""
    conn = _ChatConn()
    pg = _ChatPg(conn)
    chat_id = -100777
    conn.add_profile(chat_id)

    cache1 = ChatParamsCache(pg)
    set_chat_params_cache(cache1)
    await set_chat_params(
        chat_id,
        {"overrides": {"limits.graph_rag_context_max_chars": 123}},
        pg=pg)

    # «Рестарт»: новый process-кэш, читает те же PG-строки.
    cache2 = ChatParamsCache(pg)
    set_chat_params_cache(cache2)
    value = await get_chat_param(
        chat_id, "limits.graph_rag_context_max_chars", 9999)
    assert value == 123


# ═══ R10.9-4: health-кэш инвалидируется при save ════════════════════════════

def test_invalidate_health_cache_provider_keys():
    from services.status_service import StatusService
    svc = StatusService()
    svc._health_cache["llm_main"] = (time.monotonic(), {"ok": True})
    svc._health_cache["emb_main"] = (time.monotonic(), {"ok": True})

    # Непровайдерный ключ — кэш не трогаем (не плодим probe).
    assert svc.invalidate_health_cache(["limits.search_max_symbols"]) == 0
    assert len(svc._health_cache) == 2

    # models.*/keys.* → сброс.
    assert svc.invalidate_health_cache(["models.llm_base_url"]) == 2
    assert svc._health_cache == {}


@pytest.mark.asyncio
async def test_global_config_save_invalidates_health_cache(monkeypatch):
    """Реальный `_post_config_global`: запись models.* сбрасывает health-кэш
    (R10.9-4). Роут-уровень: helper вызывается после успешного cache.set."""
    from web.api import routes
    from services.status_service import status

    status._health_cache.clear()
    status._health_cache["llm_main"] = (time.monotonic(), {"ok": True})

    class _Cache:
        pg_available = True

        def __init__(self):
            self.saved = {}

        async def set(self, key, value, category):
            self.saved[key] = value

    cache = _Cache()
    monkeypatch.setattr(routes, "get_cache", lambda request: cache)
    monkeypatch.setattr(routes, "can_edit_param",
                        lambda c, uid, key: True)

    payload = types.SimpleNamespace(
        items=[types.SimpleNamespace(key="models.llm_timeout", value=42)],
        updated_at=None)
    user = types.SimpleNamespace(id=1)
    out = await routes._post_config_global(object(), payload, user)

    assert cache.saved["models.llm_timeout"] == 42
    assert out["updated"] == ["models.llm_timeout"]
    assert status._health_cache == {}, "R10.9-4: health-кэш должен быть сброшен"
    status._health_cache.clear()


@pytest.mark.asyncio
async def test_global_config_save_non_provider_keeps_health_cache(monkeypatch):
    """Запись limits.* health-кэш не трогает (нет ложных probe)."""
    from web.api import routes
    from services.status_service import status

    status._health_cache.clear()
    status._health_cache["llm_main"] = (time.monotonic(), {"ok": True})

    class _Cache:
        pg_available = True

        def __init__(self):
            self.saved = {}

        async def set(self, key, value, category):
            self.saved[key] = value

    cache = _Cache()
    monkeypatch.setattr(routes, "get_cache", lambda request: cache)
    monkeypatch.setattr(routes, "can_edit_param", lambda c, uid, key: True)

    payload = types.SimpleNamespace(
        items=[types.SimpleNamespace(key="limits.search_max_symbols",
                                     value=9000)],
        updated_at=None)
    user = types.SimpleNamespace(id=1)
    await routes._post_config_global(object(), payload, user)

    assert "llm_main" in status._health_cache
    status._health_cache.clear()


# ═══ R10.4-7 / T-1518: per-chat cap RAG в direct-пути ══════════════════════

@pytest.mark.asyncio
async def test_rag_block_cap_is_per_chat(monkeypatch):
    """`_build_rag_block` берёт cap из get_chat_param(chat_id, ...), а не из
    глобального hot.get — сохранённое для чата значение реально режет RAG."""
    from services import direct_chat_service as dcs

    captured = {}

    async def fake_cp_g(chat_id, key, default=None):
        captured["chat_id"] = chat_id
        captured["key"] = key
        captured["default"] = default
        return 8

    class _Mem:
        async def get_rag_facts(self, chat_id, query, **kwargs):
            return [("chat_history", "abcdefghijklmnop")]   # 16 символов

    class _Self:
        memory = _Mem()

    class _Hot:
        @staticmethod
        def get(key, default=None):
            if key == "flags.graph_rag_enabled":
                return True
            if key == "flags.chat_rag_rerank_enabled":
                return False
            if key == "limits.graph_rag_context_max_chars":
                return 99999          # глобальный дефолт — НЕ должен победить
            return default

    monkeypatch.setattr(dcs, "hot", _Hot)
    monkeypatch.setattr(dcs, "_cp_g", fake_cp_g)

    class _Msg:
        text = "query"

    block, _hint = await dcs.DirectChatService._build_rag_block(
        _Self(), -100, _Msg(), "")
    assert captured["chat_id"] == -100
    assert captured["key"] == "limits.graph_rag_context_max_chars"
    assert block.startswith("<RAG_Memory>\n") and block.endswith("\n</RAG_Memory>")
    inner = block[len("<RAG_Memory>\n"):-len("\n</RAG_Memory>")]
    assert len(inner) == 8, "R10.4-7: cap применился per-chat (8), не глобальные 99999"


# ═══ H3: per-chat гейт/вес self-фактов ══════════════════════════════════════


class _SelfDb:
    def __init__(self):
        self.inserted = []

    async def insert_graph_fact(self, chat_id, fact, origin, expires_at, **kw):
        self.inserted.append({"chat_id": chat_id, "fact": fact,
                              "origin": origin, "expires_at": expires_at, **kw})
        return len(self.inserted)


@pytest.mark.asyncio
async def test_memorize_self_reply_per_chat_off(monkeypatch):
    """H3: per-chat OFF `flags.bot_self_awareness_enabled` → self-факт НЕ
    пишется (глобальный hot.get не побеждает)."""
    from services import summary_memory as sm

    async def fake_limit(chat_id, key, default=None):
        if key == "flags.bot_self_awareness_enabled":
            return False
        return default

    monkeypatch.setattr(sm, "_chat_limit", fake_limit)
    db = _SelfDb()
    mm = sm.MemoryManager(db=db, llm=None)
    assert await mm.memorize_self_reply(-100, "суть") == 0
    assert db.inserted == []


@pytest.mark.asyncio
async def test_memorize_self_reply_weight_is_per_chat(monkeypatch):
    """H3: per-chat `limits.graph_fact_weight_bot` реально попадает в вес
    записываемого self-факта (реактивность override)."""
    from services import summary_memory as sm

    async def fake_limit(chat_id, key, default=None):
        if key == "flags.bot_self_awareness_enabled":
            return True
        if key == "limits.graph_fact_weight_bot":
            return 0.9
        if key == "limits.chat_direct_reply_ttl_days":
            return 0
        return default

    monkeypatch.setattr(sm, "_chat_limit", fake_limit)
    db = _SelfDb()
    mm = sm.MemoryManager(db=db, llm=None)
    assert await mm.memorize_self_reply(-100, "A B") == 1
    assert db.inserted[0]["origin"] == "bot_self_reply"
    assert db.inserted[0]["weight"] == 0.9


# ═══ T-1514: фронтовый сброс scope ══════════════════════════════════════════

def test_set_active_chat_resets_scope_state():
    """Статическая гарантия T-1514: `setActiveChat` сбрасывает optimistic-метку
    и черновики (поведенчески — в tests/js/routing_test.js)."""
    js = open("web/app.js", encoding="utf-8").read()
    start = js.index("setActiveChat: function (chatId) {")
    end = js.index("isChatContext: function ()", start)
    block = js[start:end]
    assert "this.configChatUpdatedAt = null;" in block, \
        "T-1514: configChatUpdatedAt не сброшен при смене scope"
    assert "this.keyDrafts = {};" in block, \
        "T-1514: keyDrafts не сброшены при смене scope"
    assert "this.ownKeyDraft = '';" in block, \
        "T-1514: BYOK-черновик не сброшен при смене scope"
    assert "this.blockDrafts = {};" in block
    assert "this.personaDraft = null;" in block
    assert "this.scopeEpoch++;" in block


# ── chat_params PG-фейк (зеркало tests/test_chat_params.py) ─────────────────

class _ChatConn:
    def __init__(self):
        self.profiles = {}
        self._seq = 0

    def _ts(self):
        self._seq += 1
        return f"2026-09-13T10:00:{self._seq:02d}+00:00"

    def add_profile(self, chat_id, chat_params=None):
        self.profiles[chat_id] = {
            "chat_id": chat_id,
            "updated_at": self._ts(),
            "chat_params": chat_params or {},
            "gates_opt_in": False,
        }

    async def fetchrow(self, sql, *args):
        if sql.startswith("SELECT"):
            row = self.profiles.get(args[0])
            return json.loads(json.dumps(row)) if row else None
        if "UPDATE chat_profiles" in sql:
            row = self.profiles.get(args[0])
            if not row:
                return None
            row["chat_params"] = json.loads(json.dumps(args[1]))
            row["updated_at"] = self._ts()
            return json.loads(json.dumps(row))
        return None

    async def execute(self, sql, *args):
        if "INSERT INTO chat_lore_history" in sql or "pg_notify" in sql:
            return "OK"
        return "UPDATE 1"

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx


class _ChatPg:
    def __init__(self, conn):
        self._conn = conn

    @property
    def pool(self):
        return _Pool(self._conn)
