"""F21 (раунд 10.24, `budget-global-toggle-round1024`, ADR-1024-22) — мастер-
рубильник бюджетов `flags.budgets_enabled`.

Покрытие (spec §7.2):
  (a) дефолт ON — поведение байт-в-байт как прежде;
  (b) OFF глобально — enforcement выключен, учёт/диагностика целы,
      sandbox-путь `budget` не срабатывает (llm_client транзитивно);
  (c) OFF per-chat vs global — per-chat override приоритетнее;
  (d) статистика при OFF — UPSERT/`register_usage` продолжают писать;
  (e) fail-open — ошибка резолва → ON;
  (f) фон — `consume` при OFF не блокирует и не резолвит лимит;
  (g) master приоритетнее `flags.chat_context_budgets_enabled`;
  (h) каталог — ключ/группа/вкладка;
  (i) `keys.allow_global=false` не обходится OFF.

R17/R18: значения секретов/ключей не используются и не логируются.
"""
import pytest

from config.settings import settings
from services import budget_gate
from services import chat_params as cp
from services import chat_usage
from services import hot_config as hot
from services import param_catalog as pc


class _FakeHot:
    """Глобальный слой (bot_settings): заданные ключи, иначе default."""

    def __init__(self, values):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakeChatCache:
    def __init__(self, overrides):
        self.overrides = overrides or {}

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides)}

    async def invalidate_chat(self, chat_id):
        pass


class _FakeChatCacheByChat:
    """Разные overrides на разные чаты (для проверки per-chat приоритета)."""

    def __init__(self, by_chat):
        self.by_chat = by_chat or {}

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.by_chat.get(int(chat_id), {}))}

    async def invalidate_chat(self, chat_id):
        pass


def _setup(monkeypatch, *, hot_values=None, overrides=None, used=None):
    monkeypatch.setattr(hot, "_cache", _FakeHot(hot_values))
    monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCache(overrides))

    async def _used(pg, chat_id):
        return dict(used or {})

    monkeypatch.setattr(chat_usage, "used_today", _used)


# ── (a)/(c)/(e): единый резолвер ────────────────────────────────────────────

class TestResolver:
    @pytest.mark.asyncio
    async def test_default_on(self, monkeypatch):
        _setup(monkeypatch)                       # пустые слои
        assert await budget_gate.budgets_enabled(None) is True
        assert await budget_gate.budgets_enabled(-100) is True
        assert settings.BUDGETS_ENABLED is True

    @pytest.mark.asyncio
    async def test_global_off(self, monkeypatch):
        _setup(monkeypatch, hot_values={budget_gate.KEY_BUDGETS_ENABLED: False})
        assert await budget_gate.budgets_enabled(None) is False
        assert await budget_gate.budgets_enabled(-100) is False

    @pytest.mark.asyncio
    async def test_per_chat_overrides_global(self, monkeypatch):
        """global ON + chat OFF → OFF только для чата; global OFF + chat ON →
        ON для чата (per-chat приоритетнее)."""
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: True})
        monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCacheByChat(
            {-100: {budget_gate.KEY_BUDGETS_ENABLED: False}}))
        assert await budget_gate.budgets_enabled(-100) is False
        assert await budget_gate.budgets_enabled(-200) is True
        # обратный случай
        monkeypatch.setattr(hot, "_cache", _FakeHot(
            {budget_gate.KEY_BUDGETS_ENABLED: False}))
        monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCacheByChat(
            {-100: {budget_gate.KEY_BUDGETS_ENABLED: True}}))
        assert await budget_gate.budgets_enabled(-100) is True
        assert await budget_gate.budgets_enabled(-200) is False

    @pytest.mark.asyncio
    async def test_fail_open_on_error(self, monkeypatch):
        async def _boom(*a, **kw):
            raise RuntimeError("pg down")

        monkeypatch.setattr("services.worker_settings.resolve_setting_cached",
                            _boom)
        assert await budget_gate.budgets_enabled(-100) is True


# ── (a)/(b)/(c): direct-снимок ──────────────────────────────────────────────

class TestSnapshot:
    @pytest.mark.asyncio
    async def test_default_on_enforces(self, monkeypatch):
        _setup(monkeypatch,
               hot_values={chat_usage.KEY_BUDGET_REQUESTS: 25,
                           chat_usage.KEY_BUDGET_TOKENS: 100000},
               used={chat_usage.METRIC_CALLS: 25,
                     chat_usage.METRIC_TOKENS: 699})
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["budgets_enabled"] is True
        assert snap["exceeded"] is True
        assert snap["exceeded_metric"] == "calls"
        assert await chat_usage.budget_exceeded(object(), -100) is True

    @pytest.mark.asyncio
    async def test_off_disables_enforcement_keeps_stats(self, monkeypatch):
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False,
                           chat_usage.KEY_BUDGET_REQUESTS: 25,
                           chat_usage.KEY_BUDGET_TOKENS: 100000},
               used={chat_usage.METRIC_CALLS: 999,
                     chat_usage.METRIC_TOKENS: 999})
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["budgets_enabled"] is False
        assert snap["exceeded"] is False
        assert snap["exceeded_metric"] is None
        # диагностика/статистика сохранены (R16)
        assert snap["used_calls"] == 999
        assert snap["used_tokens"] == 999
        assert snap["limit_calls"] == 25
        assert snap["forbidden"] is False
        assert await chat_usage.budget_exceeded(object(), -100) is False

    @pytest.mark.asyncio
    async def test_off_still_visible_forbidden_flag(self, monkeypatch):
        """`0`-лимит (forbidden=True) виден в снимке, но при OFF не стоп."""
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False,
                           chat_usage.KEY_BUDGET_REQUESTS: 0})
        snap = await chat_usage.budget_snapshot(object(), -100)
        assert snap["forbidden"] is True
        assert snap["exceeded"] is False

    @pytest.mark.asyncio
    async def test_per_chat_off_only_for_that_chat(self, monkeypatch):
        _setup(monkeypatch,
               hot_values={chat_usage.KEY_BUDGET_REQUESTS: 25,
                           chat_usage.KEY_BUDGET_TOKENS: 100000},
               used={chat_usage.METRIC_CALLS: 999,
                     chat_usage.METRIC_TOKENS: 999})
        monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCacheByChat(
            {-100: {budget_gate.KEY_BUDGETS_ENABLED: False}}))
        off = await chat_usage.budget_snapshot(object(), -100)
        on = await chat_usage.budget_snapshot(object(), -200)
        assert off["exceeded"] is False and off["budgets_enabled"] is False
        assert on["exceeded"] is True and on["budgets_enabled"] is True

    @pytest.mark.asyncio
    async def test_off_unknown_chat_global_off(self, monkeypatch):
        """global OFF (без override) → OFF и для «пустого» чата."""
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False,
                           chat_usage.KEY_BUDGET_REQUESTS: 0},
               overrides={})
        snap = await chat_usage.budget_snapshot(object(), -300)
        assert snap["exceeded"] is False


# ── (b)/(i): llm_client — транзитивно, права не обходятся ───────────────────

class TestLlmClient:
    @pytest.mark.asyncio
    async def test_off_returns_global_key_not_budget(self, monkeypatch):
        from services.llm_client import LLMClient

        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False,
                           chat_usage.KEY_BUDGET_REQUESTS: 25,
                           chat_usage.KEY_BUDGET_TOKENS: 100000},
               used={chat_usage.METRIC_CALLS: 999,
                     chat_usage.METRIC_TOKENS: 999})

        async def _no_own_key(pg, chat_id, key_name):
            return None

        async def _root(chat_id):
            return {"keys": {"allow_global": True}}

        monkeypatch.setattr("services.chat_keys.get_chat_key", _no_own_key)
        monkeypatch.setattr("services.chat_params.get_all_chat_params",
                            _root)
        client = LLMClient("http://x", "GLOBALKEY", "m", "")
        monkeypatch.setattr(client, "_pg", lambda: object())
        key, source = await client._resolve_api_key_and_source(-100)
        assert (key, source) == ("GLOBALKEY", "global")

    @pytest.mark.asyncio
    async def test_off_does_not_bypass_allow_global_forbidden(
            self, monkeypatch):
        """(i) OFF НЕ расширяет доступ: `keys.allow_global=false` → forbidden."""
        from services.llm_client import LLMClient, NoApiKeyForChat

        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False})

        async def _no_own_key(pg, chat_id, key_name):
            return None

        async def _root(chat_id):
            return {"keys": {"allow_global": False}}

        monkeypatch.setattr("services.chat_keys.get_chat_key", _no_own_key)
        monkeypatch.setattr("services.chat_params.get_all_chat_params",
                            _root)
        client = LLMClient("http://x", "GLOBALKEY", "m", "")
        monkeypatch.setattr(client, "_pg", lambda: object())
        with pytest.raises(NoApiKeyForChat) as exc:
            await client._resolve_api_key_and_source(-100)
        assert exc.value.reason == "forbidden"

    @pytest.mark.asyncio
    async def test_on_exceeded_still_budget(self, monkeypatch):
        """Master ON → прежний путь: sandbox reason='budget'."""
        from services.llm_client import LLMClient, NoApiKeyForChat

        _setup(monkeypatch,
               hot_values={chat_usage.KEY_BUDGET_REQUESTS: 25,
                           chat_usage.KEY_BUDGET_TOKENS: 100000},
               used={chat_usage.METRIC_CALLS: 25,
                     chat_usage.METRIC_TOKENS: 1})

        async def _no_own_key(pg, chat_id, key_name):
            return None

        async def _root(chat_id):
            return {"keys": {"allow_global": True}}

        monkeypatch.setattr("services.chat_keys.get_chat_key", _no_own_key)
        monkeypatch.setattr("services.chat_params.get_all_chat_params",
                            _root)
        client = LLMClient("http://x", "GLOBALKEY", "m", "")
        monkeypatch.setattr(client, "_pg", lambda: object())
        with pytest.raises(NoApiKeyForChat) as exc:
            await client._resolve_api_key_and_source(-100)
        assert exc.value.reason == "budget"


# ── (d)/(f): фон — учёт всегда, enforcement по master ───────────────────────

class _FakeConn:
    def __init__(self):
        self.rows = {}

    async def fetchrow(self, sql, *args):
        key = (args[1], args[2])
        self.rows[key] = self.rows.get(key, 0) + int(args[3])
        return {"used": self.rows[key]}


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _CM()


class _FakePg:
    def __init__(self):
        self.conn = _FakeConn()
        self.pool = _FakePool(self.conn)


class TestWorkerBudget:
    @pytest.mark.asyncio
    async def test_on_forbidden_blocks(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch, overrides={wb.LIMIT_CALLS_PER_CHAT: 0})
        pg = _FakePg()
        assert await wb.consume(pg, "chat:-100", wb.METRIC_CALLS) is False

    @pytest.mark.asyncio
    async def test_off_allows_and_records(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False},
               overrides={wb.LIMIT_CALLS_PER_CHAT: 0})
        pg = _FakePg()
        assert await wb.consume(pg, "chat:-100", wb.METRIC_CALLS) is True
        # UPSERT выполнен до гейта — статистика ведётся и при OFF
        assert pg.conn.rows[("chat:-100", "llm_calls")] == 1

    @pytest.mark.asyncio
    async def test_off_skips_metric_limit(self, monkeypatch):
        """При OFF `_metric_limit` не вызывается (лимит не резолвится)."""
        from services import worker_budget as wb
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False})

        async def _boom(*a, **kw):
            raise AssertionError("_metric_limit не должен вызываться при OFF")

        monkeypatch.setattr(wb, "_metric_limit", _boom)
        pg = _FakePg()
        assert await wb.consume(pg, "chat:-100", wb.METRIC_CALLS) is True

    @pytest.mark.asyncio
    async def test_off_per_chat_scope(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch)
        monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCacheByChat(
            {-100: {budget_gate.KEY_BUDGETS_ENABLED: False,
                    wb.LIMIT_CALLS_PER_CHAT: 0},
             -200: {wb.LIMIT_CALLS_PER_CHAT: 0}}))
        pg = _FakePg()
        assert await wb.consume(pg, "chat:-100", wb.METRIC_CALLS) is True
        # другой чат — master ON → forbidden применяется
        assert await wb.consume(pg, "chat:-200", wb.METRIC_CALLS) is False

    @pytest.mark.asyncio
    async def test_report_call_writes_off(self, monkeypatch):
        """(d) direct-статистика (`report_call`→`register_usage`) пишется при
        OFF (гейт OFF её не затрагивает)."""
        _setup(monkeypatch, hot_values={budget_gate.KEY_BUDGETS_ENABLED: False})
        calls = []

        async def _reg(pg, chat_id, metric, amount=1, day=None):
            calls.append((chat_id, metric, amount))
            return amount

        monkeypatch.setattr(chat_usage, "register_usage", _reg)
        await chat_usage.report_call(object(), -100, 100)
        assert calls and calls[0][0] == -100


# ── (f) фон: предохранитель деградации уважает master ───────────────────────

class TestBackgroundDegradation:
    @pytest.mark.asyncio
    async def test_off_frees_background_even_when_exhausted(self, monkeypatch):
        """High (review iter1): OFF + исчерпанный global-лимит → воркер допущен
        (деградация не скипает тики при выключенных бюджетах)."""
        from services import worker_budget as wb
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False})

        async def _usage(pg=None, scope=None, day=None):
            return [{"metric": wb.METRIC_CALLS, "used": 100, "limit": 60}]

        monkeypatch.setattr(wb, "get_usage", _usage)
        assert await wb.global_degradation_allows("dream") is True
        assert await wb.global_degradation_allows("lore") is True
        assert await wb.global_degradation_allows("nostalgia") is True

    @pytest.mark.asyncio
    async def test_off_zero_limit_still_allows(self, monkeypatch):
        from services import worker_budget as wb
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False})

        async def _usage(pg=None, scope=None, day=None):
            return [{"metric": wb.METRIC_CALLS, "used": 0, "limit": 0}]

        monkeypatch.setattr(wb, "get_usage", _usage)
        assert await wb.global_degradation_allows("dream") is True

    @pytest.mark.asyncio
    async def test_on_degrades_when_exhausted(self, monkeypatch):
        """Master ON — деградация сохранена (не сломали прежнее поведение)."""
        from services import worker_budget as wb
        _setup(monkeypatch)          # пустые слои → master ON (дефолт)

        async def _usage(pg=None, scope=None, day=None):
            return [{"metric": wb.METRIC_CALLS, "used": 100, "limit": 60}]

        monkeypatch.setattr(wb, "get_usage", _usage)
        assert await wb.global_degradation_allows("dream") is False
        # матрица деградации на границе used == limit (позиции dream=0,
        # lore=1, nostalgia=2): dream падает первым, у lore/nostalgia запас.
        assert wb.allowed_workers(("dream", "lore", "nostalgia"), 60, 60) == {
            "dream": False, "lore": True, "nostalgia": True}

    @pytest.mark.asyncio
    async def test_off_does_not_read_usage(self, monkeypatch):
        """OFF → usage не читается (короткое замыкание до get_usage)."""
        from services import worker_budget as wb
        _setup(monkeypatch,
               hot_values={budget_gate.KEY_BUDGETS_ENABLED: False})

        async def _boom(*a, **kw):
            raise AssertionError("get_usage не должен вызываться при OFF")

        monkeypatch.setattr(wb, "get_usage", _boom)
        assert await wb.global_degradation_allows("dream") is True


# ── (g): master приоритетнее context-флага ──────────────────────────────────

class _FakeMemory:
    def __init__(self, window):
        self.window = window

    async def get_window_messages(self, chat_id):
        return self.window


class _StubDirectChat:
    """Обёртка над `DirectChatService._build_user_content` с заглушёнными
    тяжёлыми шагами — проверяем только гейт бюджетов."""

    def __init__(self):
        from services import direct_chat_service as dcs
        self._cls = dcs.DirectChatService
        self.captured = None
        self._stub = self._make()

    def _make(self):
        captured_holder = self

        class _Svc(self._cls):
            def _participant_roster(self, window, active):
                return {}, {}

            def _alias_map_block(self, roster):
                return ""

            def _is_reply_trigger(self, message):
                return False

            def _render_branch(self, chain, suffix_map):
                return ""

            def _render_thread(self, chain, suffix_map, limit):
                return ""

            def _render_current_question(self, message):
                return ""

            def _build_mood_block(self, text):
                return ""

            def _apply_context_budget(self, blocks, enabled=None,
                                      budget_tokens=None):
                captured_holder.captured = {"enabled": enabled}
                return []

            async def _active_participants(self, chat_id):
                return []

            async def _collect_thread_chain(self, chat_id, message):
                return []

            async def _build_global_context(self, *a, **kw):
                return ""

            async def _build_rag_block(self, *a, **kw):
                return "", None

            async def _thread_limit(self, chat_id):
                return 100

            async def _build_user_relations(self, *a, **kw):
                return ""

            async def _chat_lore_state(self, chat_id):
                return False, ""

            async def _build_protected_facts(self, *a, **kw):
                return ""

            async def _build_style_anchors(self, chat_id):
                return ""

            async def _check_context_config_invariant(self, *a, **kw):
                return None

        svc = _Svc.__new__(_Svc)
        svc.memory = _FakeMemory([])
        return svc

    async def run(self, chat_id, master, context_on):
        async def _master(chat_id=None):
            return master

        async def _cp(chat_id, key, default=None):
            if key == "flags.chat_context_budgets_enabled":
                return context_on
            if key == "limits.chat_context_budget_tokens":
                return 1000
            return default

        import services.budget_gate as bg
        import services.chat_params as cpm
        old_bg, old_cp = bg.budgets_enabled, cpm.get_chat_param
        bg.budgets_enabled, cpm.get_chat_param = _master, _cp
        try:
            class _Msg:
                message_id = 1
                text = "привет"
            await self._stub._build_user_content(chat_id, _Msg(), "вася", None)
        finally:
            bg.budgets_enabled, cpm.get_chat_param = old_bg, old_cp
        return self.captured


class TestMasterPriority:
    @pytest.mark.asyncio
    async def test_master_off_overrides_context_on(self):
        runner = _StubDirectChat()
        cap = await runner.run(-100, master=False, context_on=True)
        assert cap["enabled"] is False          # контекст НЕ режется

    @pytest.mark.asyncio
    async def test_master_on_context_off(self):
        runner = _StubDirectChat()
        cap = await runner.run(-100, master=True, context_on=False)
        assert cap["enabled"] is False

    @pytest.mark.asyncio
    async def test_master_on_context_on(self):
        runner = _StubDirectChat()
        cap = await runner.run(-100, master=True, context_on=True)
        assert cap["enabled"] is True


# ── (h): каталог ────────────────────────────────────────────────────────────

class TestCatalog:
    def test_key_spec(self):
        spec = pc.get("BUDGETS_ENABLED")
        assert spec is not None
        assert spec.pg_key == "flags.budgets_enabled"
        assert spec.group == "flags_module_budgets"
        assert spec.category == pc.CATEGORY_FLAGS
        assert spec.type == "bool"
        assert settings.BUDGETS_ENABLED is True

    def test_group_and_tab(self):
        assert pc.get_group("flags_module_budgets") is not None
        assert pc.group_tab("flags_module_budgets") == pc.TAB_MOD_BUDGETS
        assert "flags_module_budgets" in pc.tab_group_ids(pc.TAB_MOD_BUDGETS)

    def test_counts(self):
        import dataclasses
        from config.settings import Settings
        assert len(pc.REGISTRY) == 459
        assert len(pc.GROUPS) == 98
        assert len(pc._TAB_BY_GROUP) == 96
        assert len(pc.TAB_RULES) == 20
        assert len({f.name for f in dataclasses.fields(Settings)}) == 418
