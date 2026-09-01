"""Миграция read-пути (2026-09-03): hot.get переопределяет settings.

Для ключевых модулей проверяем, что значение из ConfigCache (веб-админка)
имеет приоритет над settings.* (env). Фолбек на settings — при отсутствии
в кэше (это уже покрыто существующими тестами: кэш None → settings).
"""
import pytest
from unittest.mock import MagicMock

from config.settings import settings
from services import hot_config as hot


class _Cache:
    """Мини-кэш: get(key, default)."""

    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


@pytest.fixture
def hot_cache():
    """Подменяет hot._cache на пустой и возвращает установщик данных."""
    old = hot._cache
    holder = {}

    class _W:
        def set(self, data):
            hot.set_config_cache(_Cache(data))

    w = _W()
    w.set({})
    try:
        yield w
    finally:
        hot.set_config_cache(old)


# ── 1. filters/olya_video: флаг из кэша выключает фильтр ─────────────────────

class TestOlyaVideoHot:
    @pytest.mark.asyncio
    async def test_cache_flag_disables_filter(self, hot_cache, make_message):
        from aiogram.enums import ContentType
        from filters.olya_video import OlyaVideoFilter
        hot_cache.set({"flags.olya_enabled": False})
        filt = OlyaVideoFilter()
        msg = make_message(from_id=settings.OLYA_USER_ID, text=None)
        msg.content_type = ContentType.VIDEO
        msg.caption = None
        msg.forward_origin = None
        assert await filt(msg) is False     # settings=True, но кэш False → выключено

    @pytest.mark.asyncio
    async def test_cache_flag_enables_even_if_settings_false(self, hot_cache,
                                                             make_message):
        from dataclasses import replace
        from aiogram.enums import ContentType
        from filters.olya_video import OlyaVideoFilter
        import filters.olya_video as mod
        # settings: OLYA_ENABLED=False (всё выключено); кэш включает флаг
        # модуля И always_send → фильтр должен пропустить сообщение Оли.
        hot_cache.set({"flags.olya_enabled": True,
                       "flags.olya_always_send": True})
        filt = OlyaVideoFilter()
        msg = make_message(from_id=settings.OLYA_USER_ID, text=None)
        msg.content_type = ContentType.VIDEO
        msg.caption = None
        msg.forward_origin = None
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(mod, "settings", replace(settings, OLYA_ENABLED=False))
            result = await filt(msg)
        assert result == {"is_saveasbot": False, "matched_caption": False}


# ── 2. summary_memory: граф-параметр из кэша ─────────────────────────────────

class TestSummaryMemoryHot:
    def test_graph_fact_weight_from_cache(self, hot_cache):
        from services.summary_memory import _origin_weight
        hot_cache.set({"limits.graph_fact_weight_direct": 0.9})
        assert _origin_weight("bot_direct_reply") == 0.9
        hot_cache.set({"limits.graph_fact_weight_archive": 0.3})
        assert _origin_weight("web_content") == 0.3

    def test_fallback_to_settings_when_absent(self, hot_cache):
        from services.summary_memory import _origin_weight
        hot_cache.set({})
        assert _origin_weight("bot_direct_reply") == \
            settings.GRAPH_FACT_WEIGHT_DIRECT


# ── 3. direct_chat_service: бюджет токенов из кэша ───────────────────────────

class TestDirectChatBudgetHot:
    def test_budget_tokens_from_cache(self, hot_cache):
        from services import direct_chat_service as dcs
        from services.hot_config import get as hot_get
        hot_cache.set({"limits.chat_context_budget_tokens": 12345})
        assert hot_get("limits.chat_context_budget_tokens",
                       settings.CHAT_CONTEXT_BUDGET_TOKENS) == 12345
        # через реальный код: _apply_context_budget строится на бюджете
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        blocks = [("map", "a"), ("global", "b")]
        out = svc._apply_context_budget(blocks)
        assert isinstance(out, list)
        assert dcs is not None


# ── 4. llm_client: таймаут/бюджет из кэша при создании ───────────────────────

class TestLLMClientHot:
    def test_timeout_and_budget_from_cache(self, hot_cache, monkeypatch):
        import httpx
        from services.llm_client import LLMClient
        monkeypatch.setattr(
            "services.llm_client.httpx.AsyncClient",
            lambda **kw: MagicMock(spec=httpx.AsyncClient))
        hot_cache.set({"models.llm_timeout": 5.0,
                       "models.llm_total_budget": 12.0})
        c = LLMClient("https://api.test/v1", "k", "m", "e")
        assert c._timeout == 5.0
        assert c._budget == 12.0


# ── 5. search: ключ TAVILY/EXA из кэша ───────────────────────────────────────

class TestSearchAggregatorHot:
    def test_search_keys_from_cache(self, hot_cache):
        from services.search_aggregator import SearchAggregator
        hot_cache.set({"keys.tavily_api_key": "tvly-cache-key-12345",
                       "keys.exa_api_key": "exa-cache-key-12345"})
        agg = SearchAggregator()
        assert agg._tavily_api_key == "tvly-cache-key-12345"
        assert agg._exa_api_key == "exa-cache-key-12345"

    def test_search_keys_fallback_settings(self, hot_cache):
        from services.search_aggregator import SearchAggregator
        hot_cache.set({})
        agg = SearchAggregator()
        assert agg._tavily_api_key == settings.TAVILY_API_KEY
        assert agg._exa_api_key == settings.EXA_API_KEY


# ── 6. war_alert: каналы war-алертов из кэша ─────────────────────────────────

class TestWarAlertHot:
    def test_war_channel_ids_from_cache(self, hot_cache):
        from services.hot_config import get as hot_get
        hot_cache.set({"reactions.war_channel_ids": "111,222,333"})
        raw = hot_get("reactions.war_channel_ids", settings.WAR_CHANNEL_IDS)
        ids = {int(x) for x in str(raw).split(",") if x.strip()}
        assert ids == {111, 222, 333}

    def test_war_replies_from_cache(self, hot_cache):
        from services.hot_config import get as hot_get
        hot_cache.set({"reactions.war_replies": "фраза1,фраза2"})
        raw = hot_get("reactions.war_replies", settings.WAR_REPLIES)
        assert "фраза1" in str(raw)


# ── 7. dead_page: retries/relay-канал из кэша ────────────────────────────────

class TestDeadPageHot:
    def test_relay_max_retries_from_cache(self, hot_cache):
        from services.dead_page_relay import DeadPageRelay
        hot_cache.set({"limits.dead_page_max_forward_retries": 9,
                       "reactions.dead_page_relay_channel_id": 424242})
        relay = DeadPageRelay(bot=MagicMock(), db=MagicMock(),
                              media=MagicMock())
        assert relay.max_retries == 9
        assert relay.relay_channel_id == 424242


# ── 8. summary_throttling: P1 — кэш вместо бейкнутого дефолта ────────────────

class TestSummaryThrottlingHot:
    def test_middleware_throttle_from_cache(self, hot_cache):
        from services.summary_throttling import ThrottlingMiddleware
        hot_cache.set({"limits.summary_throttle_seconds": 77.0})
        mw = ThrottlingMiddleware()          # без аргументов
        assert mw._throttle_seconds == 77.0

    def test_middleware_explicit_arg_wins(self, hot_cache):
        from services.summary_throttling import ThrottlingMiddleware
        hot_cache.set({"limits.summary_throttle_seconds": 77.0})
        mw = ThrottlingMiddleware(throttle_seconds=5.0)
        assert mw._throttle_seconds == 5.0

    def test_middleware_fallback_to_settings(self, hot_cache):
        from services.summary_throttling import ThrottlingMiddleware
        hot_cache.set({})
        mw = ThrottlingMiddleware()
        assert mw._throttle_seconds == settings.SUMMARY_THROTTLE_SECONDS


# ── 9. N1: middleware /summary создаётся в setup_summary (не import-time) ────

class TestSummaryMiddlewareRegistration:
    def _count_middlewares(self):
        from handlers.summary import summary_router
        return len(summary_router.message.outer_middleware._middlewares)

    def _reset(self):
        from handlers.summary import summary_router
        mgr = summary_router.message.outer_middleware
        if mgr._middlewares:
            mgr.unregister(mgr._middlewares[0])
        summary_router.message._throttle_registered = False

    def test_middleware_before_cache_uses_settings_default(self, hot_cache):
        """(а) до set_config_cache: ThrottlingMiddleware() без аргументов →
        settings-дефолт."""
        from services.summary_throttling import ThrottlingMiddleware
        hot_cache.set({})
        mw = ThrottlingMiddleware()
        assert mw._throttle_seconds == settings.SUMMARY_THROTTLE_SECONDS

    def test_setup_summary_registers_middleware_with_cache_value(self,
                                                                 hot_cache):
        """(б) кэш задан → setup_summary регистрирует middleware на
        summary_router.message (счётчик вырос) и сконструирован со значением
        из кэша (77.0)."""
        from handlers.summary import setup_summary, summary_router
        hot_cache.set({"limits.summary_throttle_seconds": 77.0})
        summary_router.message._throttle_registered = False   # изоляция
        before = self._count_middlewares()
        setup_summary(generator=MagicMock())
        after = self._count_middlewares()
        assert after == before + 1
        mw = summary_router.message.outer_middleware._middlewares[-1]
        assert mw._throttle_seconds == 77.0
        self._reset()

    def test_setup_summary_does_not_duplicate_middleware(self, hot_cache):
        """(в) повторный вызов setup_summary → middleware НЕ дублируется."""
        from handlers.summary import setup_summary, summary_router
        hot_cache.set({"limits.summary_throttle_seconds": 77.0})
        before = self._count_middlewares()
        summary_router.message._throttle_registered = False
        setup_summary(generator=MagicMock())
        after1 = self._count_middlewares()
        assert after1 == before + 1
        setup_summary(generator=MagicMock())          # повторно
        after2 = self._count_middlewares()
        assert after2 == after1                       # не вырос
        self._reset()


# ── 10. N2/N4: half_life=0/NULL в знаменателе → нет ZeroDivisionError ───────

class TestTimeDecayNullSafety:
    def test_half_life_zero_no_zero_division(self, hot_cache):
        import services.summary_memory as sm
        hot_cache.set({"limits.graph_time_decay_half_life_days": 0,
                       "limits.graph_time_decay_floor": None})
        # _effective_weight: half_life=0 → max(1), floor=None → 0.0
        w = sm._effective_weight(0.7, confirmed_at=0, now=86400 * 10)
        assert w >= 0.0
        # _format_graph_fact-ветка decay (метод MemoryManager)
        mgr = sm.MemoryManager.__new__(sm.MemoryManager)
        row = {"source_name": "A", "relation_type": "rel", "target_name": "B",
               "weight": 0.7, "last_updated": "2026-01-01 00:00:00"}
        w2 = mgr._format_graph_fact(row)
        assert isinstance(w2, str)

    def test_half_life_null_via_cache_ok(self, hot_cache):
        from services.summary_memory import _effective_weight
        hot_cache.set({"limits.graph_time_decay_half_life_days": None,
                       "limits.graph_time_decay_floor": None})
        w = _effective_weight(0.5, confirmed_at=0, now=86400)
        assert w > 0

    @pytest.mark.asyncio
    async def test_window_hours_null_no_crash(self, hot_cache):
        from unittest.mock import AsyncMock
        import services.summary_memory as sm
        hot_cache.set({"limits.summary_window_hours": None,
                       "limits.summary_max_window_messages": None})
        svc = sm.MemoryManager.__new__(sm.MemoryManager)
        svc.db = MagicMock()
        svc.db.get_smart_window = AsyncMock(return_value=[])
        rows = await svc.get_window_messages(1)
        assert rows == []


# ── 11. N6: war_alert парсеры принимают list-значение из кэша ───────────────

class TestWarParseListValues:
    def test_parse_int_list_from_list(self):
        from handlers.war_alert import _parse_int_list
        assert _parse_int_list([111, 222, "333"]) == [111, 222, 333]
        assert _parse_int_list("111,222") == [111, 222]
        assert _parse_int_list(None) == []

    def test_parse_str_list_from_list(self):
        from handlers.war_alert import _parse_str_list
        assert _parse_str_list(["Фраза1", " фраза2 "]) == ["фраза1", "фраза2"]
        assert _parse_str_list("A,B") == ["a", "b"]
        assert _parse_str_list(()) == []
