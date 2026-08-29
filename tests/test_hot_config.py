"""Epic 85 (T-619) — тесты горячих точек: ConfigCache → settings-фолбек.

DoD T-619: параметр есть в PG → бот берёт из кэша; нет → settings-дефолт;
POST /api/config (cache.set) → СЛЕДУЮЩЕЕ обращение уже с новым значением;
без кэша (не инициализирован/PG down) → поведение = старым settings.X.
"""
import asyncio

import pytest

from services import hot_config as hot
from services.config_cache import ConfigCache
from services.permissions import Permissions


class _FakeCache:
    """Конфиг-кэш-стаб: dict + pg_available (set работает только в память)."""

    def __init__(self, values=None):
        self._settings = dict(values or {})
        self.pg_available = False

    def get(self, key, default=None):
        return self._settings.get(key, default)

    async def set(self, key, value, category):
        self._settings[key] = value


@pytest.fixture(autouse=True)
def _reset_cache():
    hot.set_config_cache(None)
    yield
    hot.set_config_cache(None)


class TestFallbackToSettings:
    def test_no_cache_returns_default(self):
        assert hot.get("limits.search_max_symbols", 8000) == 8000

    def test_get_config_cache_roundtrip(self):
        assert hot.get_config_cache() is None
        cache = _FakeCache({})
        hot.set_config_cache(cache)
        assert hot.get_config_cache() is cache
        hot.set_config_cache(None)
        assert hot.get_config_cache() is None

    def test_cache_miss_returns_default(self):
        hot.set_config_cache(_FakeCache({}))
        assert hot.get("limits.search_max_symbols", 8000) == 8000

    def test_cache_hit_returns_db_value(self):
        hot.set_config_cache(_FakeCache({"limits.search_max_symbols": 123}))
        assert hot.get("limits.search_max_symbols", 8000) == 123

    @pytest.mark.asyncio
    async def test_hot_reload_after_set(self):
        cache = _FakeCache()
        hot.set_config_cache(cache)
        assert hot.get("limits.x", 1) == 1
        await cache.set("limits.x", 42, "limits")
        assert hot.get("limits.x", 1) == 42


class TestLlmClientHotKey:
    def test_api_key_from_cache(self):
        from services.llm_client import LLMClient
        hot.set_config_cache(_FakeCache({"keys.llm_api_key": "sk-new"}))
        client = LLMClient("https://x", "sk-old", "m", "e")
        assert client._current_api_key() == "sk-new"

    def test_api_key_falls_back_to_settings(self):
        from services.llm_client import LLMClient
        hot.set_config_cache(_FakeCache({}))
        client = LLMClient("https://x", "sk-old", "m", "e")
        assert client._current_api_key() == "sk-old"

    @pytest.mark.asyncio
    async def test_client_recreated_on_key_change(self):
        from services.llm_client import LLMClient
        cache = _FakeCache({"keys.llm_api_key": "sk-a"})
        hot.set_config_cache(cache)
        client = LLMClient("https://x", "sk-init", "m", "e")
        c1 = client._get_client()
        assert client._client_key == "sk-a"
        cache._settings["keys.llm_api_key"] = "sk-b"
        c2 = client._get_client()
        assert c2 is not c1
        assert client._client_key == "sk-b"
        await asyncio.sleep(0)   # дать закрыться старому клиенту (fire-and-forget)


class TestCooldownRefresh:
    def test_refresh_updates_tracker_interval(self):
        from services.persistent_throttling import cooldown_refresh
        from services.smartmodule_throttling import CooldownTracker
        tracker = CooldownTracker(300.0)
        cooldown_refresh(tracker, 60.0)
        assert tracker._cooldown == 60.0

    def test_refresh_persistent_tracker(self):
        from services.persistent_throttling import (
            PersistentCooldownTracker,
            cooldown_refresh,
        )
        tracker = PersistentCooldownTracker(300.0, "x", None)
        cooldown_refresh(tracker, 45.0)
        assert tracker._cooldown == 45.0

    def test_hot_reload_in_handler_flow(self):
        """Имитация хендлера: кулдаун читается из кэша перед проверкой."""
        from services.persistent_throttling import cooldown_refresh
        from services.smartmodule_throttling import CooldownTracker

        cache = _FakeCache({"limits.factcheck_cooldown_seconds": 7.0})
        hot.set_config_cache(cache)
        tracker = CooldownTracker(300.0)
        cooldown_refresh(
            tracker,
            hot.get("limits.factcheck_cooldown_seconds", 300.0))
        assert tracker._cooldown == 7.0


class TestServiceHotPoints:
    """Сервисы читают лимиты/промпты из кэша на каждый вызов."""

    @pytest.mark.asyncio
    async def test_factcheck_uses_cached_max_symbols_and_prompt(self):
        from services.factcheck_service import FactCheckService

        hot.set_config_cache(_FakeCache({
            "limits.factcheck_max_symbols": 555,
            "prompts.factcheck_system_prompt": "ПРОМПТ-ИЗ-БД {max_symbols}",
        }))

        class _Agg:
            def __init__(self):
                self.last_max = None

            async def search(self, text, max_symbols):
                self.last_max = max_symbols
                return "выдача"

        class _Llm:
            def __init__(self):
                self.last_system = None

            async def generate(self, messages, temperature=None):
                self.last_system = messages[0]["content"]
                return "вердикт"

        agg = _Agg()
        llm = _Llm()
        service = FactCheckService(agg, llm)
        await service.check_claim("цель")
        assert agg.last_max == 555
        assert llm.last_system == "ПРОМПТ-ИЗ-БД 555"

    @pytest.mark.asyncio
    async def test_factcheck_falls_back_to_settings_without_cache(self):
        from services.factcheck_service import FactCheckService
        from config.settings import settings

        class _Agg:
            async def search(self, text, max_symbols):
                self.last_max = max_symbols
                return ""

        class _Llm:
            async def generate(self, messages, temperature=None):
                return "ок"

        agg = _Agg()
        service = FactCheckService(agg, _Llm())
        await service.check_claim("цель")
        assert agg.last_max == settings.FACTCHECK_MAX_SYMBOLS

    @pytest.mark.asyncio
    async def test_search_rerank_flag_from_cache(self):
        from services.search_service import SearchService

        hot.set_config_cache(_FakeCache({
            "flags.search_rerank_enabled": False,
            "limits.search_max_symbols": 999,
        }))

        class _Agg:
            def __init__(self):
                self.last_max = None

            async def search(self, query, max_symbols):
                self.last_max = max_symbols
                return "выдача без реранка"

        class _Llm:
            async def generate(self, messages, temperature=None):
                return "ответ"

        service = SearchService(_Agg(), _Llm())
        await service.research("запрос")
        # rerank выключен → _rerank_results НЕ вызывался (проверяем косвенно:
        # без исключений и с правильным max_symbols)
        assert service.aggregator.last_max == 999

    def test_info_service_reads_cache_first(self, tmp_path):
        from services.info_service import INFO_KEY, InfoService

        path = tmp_path / "info_text.md"
        path.write_text("<b>файл</b>", encoding="utf-8")
        service = InfoService(file_path=str(path))
        service.load()

        # без кэша → файл
        assert service.get_text() == "<b>файл</b>"

        # с кэшем → БД-значение (источник истины, 84.13.3)
        hot.set_config_cache(_FakeCache({
            INFO_KEY: {"html": "<h1>из БД</h1>", "updated_at": "t",
                       "updated_by": 1},
        }))
        assert service.get_text() == "<h1>из БД</h1>"

        # битый кэш (не dict) → файл
        hot.set_config_cache(_FakeCache({INFO_KEY: None}))
        assert service.get_text() == "<b>файл</b>"
