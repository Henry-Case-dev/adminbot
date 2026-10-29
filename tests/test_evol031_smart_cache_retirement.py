"""EVOL-031 (30.10.2026) — вывод Exact Match Cache готовых LLM-ответов из
эксплуатации (источник: plans/current_task.md EVOL-031; карта удаления:
plans/features/evol/audit/base-revalidation.md §EVOL-031).

Контракты:
(a) тот же вопрос дважды → ОБА раза живой путь (stub-LLM вызван 2 раза,
    реплея нет) — handlers search/web;
(b) direct_dedup-ветка удалена: повторный идентичный текст Direct Chat не
    шорткатит, ЛЮБАЯ комбинация legacy-рубильников (CHAT_DEDUP_ENABLED /
    SMART_CACHE_ENABLED / hot-флаги) не возвращает готовый ответ;
    в таблице smart_cache не появляется payload-ов ответов;
(c) REGRESSION: дедуп Telegram-update (identity-маркеры, MCA-22) и
    wide-context срез фактчека (CFG-06) работают на тех же методах;
    коротко-TTL запись НЕ выметает 24-часовые маркеры;
(d) UI/каталог: «Умный кэш» отсутствует в app.js/index.html/param_catalog
    (вкладка, карточки, флаги, группы, маршруты); старая ссылка
    #/ai/smart-cache алиасится на витрину «ИИ»; dedicated-эндпоинтов нет;
(e) REGRESSION stub: утилиты normalize/build_key живы, защищённые слаги
    (`factcheck`, `factcheck_wide_context`) работают, ответные слаги
    (`search`/`web`/`youtube`/`direct_dedup`) удалены; кеш эмбеддингов —
    независимое хранилище (embedding_cache в database.py, без smart_cache).

Без сети, без Telegram-отправок: bot — AsyncMock, LLM — FakeLLM.
"""
import inspect
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import settings
from services import hot_config as hot
from services import param_catalog as pc
from services.smart_cache import (
    SmartCache,
    build_key,
    normalize_text,
    normalize_url,
)

CHAT_ID = -1001234567890


class _HotCfg:
    """Минимальный ConfigCache-двойник для hot.set_config_cache (.get)."""

    def __init__(self, values):
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)


# ═══ (a) Ответный путь: повторный запрос идёт в живой путь ═══════════════


class TestAnswerPathAlwaysLive:
    """R51-4б инвертирован EVOL-031: 2-й вызов с тем же входом ОБЯЗАН снова
    дёрнуть сервис (LLM). Кеша готовых ответов больше нет."""

    @pytest.mark.asyncio
    async def test_search_second_identical_query_runs_llm_again(self):
        import handlers.search as search_mod

        service = MagicMock()
        service.research = AsyncMock(return_value="свежий ответ поиска")
        search_mod.setup_search(service, None)
        bot = AsyncMock()
        sent = MagicMock()
        sent.message_id = 999
        bot.send_message = AsyncMock(return_value=sent)
        try:
            msg = _text_message("Бот, найди погоду в Москве")
            await search_mod.smartsearch_handler(msg, bot=bot)
            assert service.research.await_count == 1
            # тот же вопрос (нормализация текста совпала бы в старом кэше)
            search_mod._cooldown._last.clear()
            msg2 = _text_message("БОТ, НАЙДИ погоду в Москве", message_id=22)
            await search_mod.smartsearch_handler(msg2, bot=bot)
            # EVOL-031: живой путь — второй LLM-вызов, не реплей
            assert service.research.await_count == 2
            assert bot.send_message.await_count == 2
            second = bot.send_message.await_args_list[1]
            assert second.args[1] == "свежий ответ поиска"
        finally:
            search_mod.setup_search(None)
            search_mod._cooldown._last.clear()

    @pytest.mark.asyncio
    async def test_web_second_identical_url_runs_llm_again(self, monkeypatch):
        import handlers.web as web_mod

        service = MagicMock()
        service.summarize = AsyncMock(return_value="свежая выжимка")
        web_mod.setup_web(service)
        bot = AsyncMock()
        sent = MagicMock()
        sent.message_id = 999
        bot.send_message = AsyncMock(return_value=sent)
        try:
            msg = _text_message("Бот, выжимка https://site.ru/article")
            await web_mod.web_handler(msg, bot=bot)
            assert service.summarize.await_count == 1
            # тот же URL (с мусорным utm — нормализация URL совпала бы)
            web_mod._cooldown._last.clear()
            msg2 = _text_message(
                "Бот, выжимка https://site.ru/article?utm_source=x",
                message_id=33)
            await web_mod.web_handler(msg2, bot=bot)
            assert service.summarize.await_count == 2
            assert bot.send_message.await_count == 2
        finally:
            web_mod.setup_web(None)
            web_mod._cooldown._last.clear()

    @pytest.mark.asyncio
    async def test_youtube_url_branch_has_no_cache_consult(self):
        """Структурно: в URL-ветке youtube больше нет consult+store кеша."""
        import handlers.youtube as yt_mod

        src = inspect.getsource(yt_mod)
        assert "get_smart_cache" not in src
        assert 'build_key("youtube"' not in src
        assert "cache hit" not in src


def _text_message(text, message_id=11, chat_id=CHAT_ID):
    msg = MagicMock()
    msg.text = text
    msg.caption = None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = 10
    msg.reply_to_message = None
    msg.forward_origin = None
    return msg


# ═══ (b) direct_dedup: ветка реплея удалена безвозвратно ══════════════════


class TestDirectDedupRetired:
    """Epic 60 (67.4) text-replay выведен из эксплуатации (продуктовое
    решение EVOL-031): повторный идентичный текст обрабатывается заново."""

    @pytest.fixture(autouse=True)
    def _legacy_topology_off(self, monkeypatch):
        """Изоляция топологии (как autouse-фикстуры test_direct_chat):
        L1-линия OFF, self-awareness OFF — иначе побочные LLM-потребители
        искажают счётчик generate()."""
        from config.settings import Settings
        from services import hot_config as _hot

        monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", False)
        real_get = _hot.get
        monkeypatch.setattr(
            _hot, "get",
            lambda key, default=None: False
            if key == "flags.bot_self_awareness_enabled"
            else real_get(key, default))

    @pytest_asyncio.fixture
    async def cache(self, tmp_path):
        c = SmartCache(str(tmp_path / "evol031-dedup.db"))
        yield c
        await c.close()

    @pytest.mark.asyncio
    async def test_repeated_identical_text_processed_fresh(
            self, cache, monkeypatch):
        # Изоляция: обновляемый модуль direct_chat_service.time (CB/throttle).
        from test_direct_chat import (FakeLLM, _bot, _make_service, _message,
                                      _user)

        state = {"now": 1000.0}

        class FakeTime:
            @staticmethod
            def monotonic():
                return state["now"]

            @staticmethod
            def time():
                return state["now"]

        monkeypatch.setattr("services.direct_chat_service.time", FakeTime)
        # Принудительно ВКЛЮЧАЕМ все legacy-рубильники: реплей не должен
        # возвращаться НИ при какой комбинации флагов (никаких мёртвых
        # переключателей).
        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            replace(settings, CHAT_DEDUP_ENABLED=True,
                    SMART_CACHE_ENABLED=True))
        hot.set_config_cache(_HotCfg({
            "flags.chat_dedup_enabled": True,
            "flags.smart_cache_enabled": True,
        }))
        llm = FakeLLM(text="живой ответ бота")
        service = _make_service(llm=llm, cache=cache)
        bot = _bot()
        try:
            await service.handle(bot, _message(text="бот, привет",
                                               message_id=1), _user())
            n_first = llm.call_count
            assert n_first >= 1                  # первый ход — живая генерация
            # идентичный текст, ДРУГОЙ Telegram update (другой message_id)
            await service.handle(bot, _message(text="БОТ, ПРИВЕТ",
                                               message_id=2), _user())
            assert llm.call_count == n_first + 1  # никакого шортката: новая генерация
            assert bot.send_message.await_count == 2
            second = bot.send_message.await_args_list[1]
            assert second.args[1] == "живой ответ бота"   # живой ответ, не реплей

            # В таблице smart_cache — только identity-маркеры обновлений;
            # ни ответов, ни маркеров «молчания» для реплея.
            cur = await cache._db.execute(
                "SELECT key, payload FROM smart_cache")
            rows = await cur.fetchall()
            assert rows, "update-маркеры должны записываться (protected)"
            for row in rows:
                assert row["key"].startswith("direct_update\x00")
                assert "живой ответ бота" not in row["payload"]
        finally:
            hot.set_config_cache(None)

    def test_smart_cache_module_has_no_replay_api(self):
        """Никакого API, которым можно было бы снова включить replay."""
        assert not hasattr(SmartCache, "get")
        assert not hasattr(SmartCache, "set")
        assert not hasattr(SmartCache, "get_dedup")
        assert not hasattr(SmartCache, "set_dedup")

    def test_direct_chat_service_has_no_dedup_branch(self):
        import services.direct_chat_service as dcs

        src = inspect.getsource(dcs)
        assert "direct_dedup\x00" not in src
        assert ".get_dedup(" not in src
        assert ".set_dedup(" not in src
        assert "def _legacy_text_replay_enabled" not in src
        assert "def _answer_cache_disabled_notified" not in src
        # и вызовов старых хелперов не осталось
        assert "_legacy_text_replay_enabled()" not in src


# ═══ (c) REGRESSION: защищённые механизмы работают ════════════════════════


class TestProtectedMechanisms:
    """Дедуп Telegram-update (MCA-22) и wide-context срез (CFG-06) живут
    на той же таблице — их поведение не изменилось (identity, явный TTL)."""

    @pytest_asyncio.fixture
    async def cache(self, tmp_path):
        c = SmartCache(str(tmp_path / "evol031-protected.db"))
        yield c
        await c.close()

    @pytest.mark.asyncio
    async def test_update_marker_roundtrip(self, cache):
        from services.response_freshness import (
            UPDATE_DEDUP_TTL_SECONDS,
            check_update_seen,
            mark_update_seen,
        )

        assert await check_update_seen(cache, CHAT_ID, 501) is False
        await mark_update_seen(cache, CHAT_ID, 501)
        assert await check_update_seen(cache, CHAT_ID, 501) is True
        # другой update (другой tg id) — fresh processing
        assert await check_update_seen(cache, CHAT_ID, 502) is False

    @pytest.mark.asyncio
    async def test_short_ttl_write_keeps_update_markers(self, cache,
                                                        monkeypatch):
        """REGRESSION на смежный фикс: запись wide-context среза (~120 с)
        не выметает 24-часовые update-маркеры (ленивая чистка идёт порогом
        max(TTL записи, 24 h), а не «сырым» TTL вызывающего)."""
        state = {"now": 1000.0}

        class FakeTime:
            @staticmethod
            def monotonic():
                return state["now"]

        monkeypatch.setattr("services.smart_cache.time", FakeTime)
        await cache.set_update_marker("direct_update\x00m1", "1",
                                      ttl_seconds=24 * 3600)
        state["now"] += 10
        # wide-context паттерн: короткий TTL
        await cache.set_update_marker("factcheck_wide_context\x00k1", "{}",
                                      ttl_seconds=120)
        marker = await cache.get_update_marker(
            "direct_update\x00m1", ttl_seconds=24 * 3600)
        assert marker == "1"                  # маркер пережил коротко-TTL запись

    @pytest.mark.asyncio
    async def test_marker_expiry_still_works(self, cache, monkeypatch):
        state = {"now": 1000.0}

        class FakeTime:
            @staticmethod
            def monotonic():
                return state["now"]

        monkeypatch.setattr("services.smart_cache.time", FakeTime)
        await cache.set_update_marker("direct_update\x00m2", "1",
                                      ttl_seconds=100)
        state["now"] += 101
        assert await cache.get_update_marker(
            "direct_update\x00m2", ttl_seconds=100) is None


# ═══ (d) UI/каталог/эндпоинты: поверхность «Умный кэш» снята ═════════════


class TestUISurfaceRemoved:
    def test_param_catalog_has_no_smart_cache_surface(self):
        assert not hasattr(pc, "TAB_SMART_CACHE")
        group_ids = {g.id for g in pc.GROUPS}
        assert "limits_smart_cache" not in group_ids
        assert "flags_smart_cache" not in group_ids
        registry_keys = {spec.pg_key for spec in pc.REGISTRY.values()}
        for gone in ("SMART_CACHE_ENABLED", "SMART_CACHE_TTL_SECONDS",
                     "SMART_CACHE_MAX_ROWS", "CHAT_DEDUP_ENABLED",
                     "CHAT_DEDUP_TTL_SECONDS"):
            assert gone not in registry_keys
        # правило вкладки удалено (группы больше никуда не замаплены)
        assert "limits_smart_cache" not in pc._TAB_BY_GROUP
        assert "flags_smart_cache" not in pc._TAB_BY_GROUP

    def test_app_js_has_no_smart_cache_surface(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        src = (root / "web" / "app.js").read_text(encoding="utf-8")
        assert "id: 'smart_cache'" not in src          # вкладка TABS
        assert "tab: 'smart_cache'" not in src          # карточки хабов
        assert "'#/ai/smart-cache': 'smart_cache'" not in src   # ROUTE_TO_TAB
        assert "smart_cache: '#/ai/smart-cache'" not in src     # TAB_TO_ROUTE
        assert "{ icon: 'bolt', title: 'Умный кэш'" not in src  # карточки
        assert "limits_smart_cache" not in src
        assert "flags_smart_cache" not in src
        # старая ссылка не 404 — алиас на витрину «ИИ» (без возврата кэша)
        assert "'#/ai/smart-cache': '#/ai'" in src

    def test_index_html_has_no_smart_cache_strings(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        src = (root / "web" / "index.html").read_text(encoding="utf-8")
        assert "Умный кэш" not in src
        assert "smart_cache" not in src
        assert "Exact Match" not in src

    def test_web_api_has_no_smart_cache_endpoints(self):
        """Никаких dedicated-эндпоинтов, которые могли бы снова включить кеш
        (generic /api/config отдаёт только каталог — поверхность снята там)."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        api_dir = root / "web" / "api"
        for py in sorted(api_dir.glob("*.py")):
            src = py.read_text(encoding="utf-8")
            assert "smart_cache" not in src, py.name
            assert "smart-cache" not in src, py.name


# ═══ (e) REGRESSION stub: утилиты/слаги/чужие кеши ════════════════════════


class TestProtectedUtilsAndForeignCaches:
    def test_shared_normalize_utils_intact(self):
        # D208/D209 — утилиты общие (lore/temporal_factcheck/factcheck_context)
        assert normalize_url(
            "https://Site.Ru/page/?utm_source=x&fbclid=z&id=5#frag"
        ) == "https://site.ru/page?id=5"
        assert normalize_text("  Привет   БОТ ") == "привет бот"
        assert build_key("factcheck", "x") == build_key("factcheck", " x ")

    def test_answer_slugs_removed_protected_slugs_kept(self):
        for gone in ("search", "web", "youtube", "direct_dedup",
                     "factcheck_temporal"):
            with pytest.raises(ValueError):
                build_key(gone, "x")
        # защищённые: provenance-метка фактчека + wide-context срез
        assert build_key("factcheck", "x")
        assert build_key("factcheck_wide_context", "x")

    def test_embedding_cache_is_independent_storage(self):
        """Кеш эмбеддингов — отдельная таблица embedding_cache, к smart_cache
        не имеет отношения (EVOL-031 не трогает эмбеддинги/индексы)."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        db_src = (root / "services" / "database.py").read_text(encoding="utf-8")
        assert "CREATE TABLE IF NOT EXISTS embedding_cache" in db_src
        ecp_src = (root / "services" / "embedding_control_plane.py") \
            .read_text(encoding="utf-8")
        assert "smart_cache" not in ecp_src
