"""Раунд 10.15 (F6, T-1599) — обязательный префикс команд, имя персоны, приоритеты.

Покрывает канон-реестр (17 prefixed + 2 bare), резолв префикса со склонениями,
интеграцию хендлеров (search/youtube/web/checkup/download), отключение
дефолтных ботвордов при заданном Имени и yield direct_chat (UNHANDLED).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

from handlers import checkup as checkup_mod
from handlers import direct_chat as dc
from handlers import search as search_mod
from handlers import video_download as vd
from handlers import web as web_mod
from handlers import youtube as youtube_mod
from services import bot_persona
from services import command_prefix as cp
from services import command_registry as reg
from services.smartmodule_phrases import COMMAND_NO_TARGET_PHRASES

CHAT_ID = -1001234567890
YT_URL = "https://youtu.be/dQw4w9WgXcQ"
WEB_URL = "https://habr.com/ru/articles/1"
DL_URL = "https://example.com/watch?v=1"


@pytest.fixture
def empty_name():
    bot_persona.set_global_name_cache("")
    yield


@pytest.fixture
def oleg_name():
    bot_persona.set_global_name_cache("Олег")
    yield


def _msg(text=None, caption=None, message_id=11, user_id=1,
         reply_to_message=None):
    m = MagicMock()
    m.text = text
    m.caption = caption
    m.message_id = message_id
    m.chat = MagicMock()
    m.chat.id = CHAT_ID
    m.from_user = MagicMock()
    m.from_user.id = user_id
    m.reply_to_message = reply_to_message
    m.video = None
    m.document = None
    m.voice = None
    m.video_note = None
    m.entities = None
    return m


def _enable_flag(monkeypatch, key: str, value: bool) -> None:
    """hot.get, отдающий value для key и реальные дефолты для остальных."""
    real_get = dc.hot.get

    def _get(k, default=None):
        return value if k == key else real_get(k, default)

    monkeypatch.setattr(dc.hot, "get", _get)


# ── 1. Канонический реестр ───────────────────────────────────────────

class TestCommandRegistry:
    def test_exactly_17_prefixed_triggers(self):
        assert len(reg.ALL_TRIGGERS) == 17
        assert len(set(reg.ALL_TRIGGERS)) == 17

    def test_canon_groups(self):
        assert reg.FUNCTIONAL_COMMANDS["search"] == ("найди", "поищи", "загугли")
        assert reg.FUNCTIONAL_COMMANDS["youtube"] == (
            "транскрипт", "че за видос", "о чем видео", "поясни за видос")
        assert reg.FUNCTIONAL_COMMANDS["web"] == (
            "поясни за ссылку", "че по ссылке", "о чем статья", "выжимка")
        assert reg.FUNCTIONAL_COMMANDS["checkup"] == (
            "ты в порядке", "живой?", "чекни здоровье")
        assert reg.FUNCTIONAL_COMMANDS["download"] == ("скачай", "загрузи", "стяни")

    def test_bare_exceptions_outside_functional(self):
        assert reg.BARE_COMMANDS == ("чекап", "фактчек")
        for bare in reg.BARE_COMMANDS:
            assert reg.group_of(bare) is None
            assert not any(bare in cmds
                           for cmds in reg.FUNCTIONAL_COMMANDS.values())

    def test_f6u1_removed_aliases_not_matched(self):
        for alias in ("перескажи видос", "че в видосе", "поясни за статью",
                      "че на сайте", "перескажи статью", "живой собака",
                      "пульс бота", "как сервак", "спизди", "скачать"):
            assert reg.group_of(alias) is None, alias

    def test_matches_group(self):
        assert reg.matches_group("search", "загугли x")
        assert not reg.matches_group("search", "транскрипт x")
        assert reg.matches_group("checkup", "живой?")

    # Review-fix M1: у триггеров есть правая граница слова.
    def test_trigger_right_word_boundary(self):
        for text in ("загуглика", "транскриптер", "найдикто", "поищите"):
            assert reg.group_of(text) is None, text
        assert not reg.matches_group("search", "загуглика")
        assert not reg.matches_group("search", "найдикто")
        assert not reg.matches_group("youtube", "транскриптер")
        # настоящие триггеры по-прежнему валидны (в т.ч. на конце строки).
        assert reg.group_of("загугли") == "search"
        assert reg.group_of("загугли текст") == "search"
        assert reg.group_of("транскрипт видео") == "youtube"
        assert reg.group_of("загуглика") is None


# ── 2. Резолв префикса ───────────────────────────────────────────────

class TestSplitPrefix:
    @pytest.mark.parametrize("text", [
        "Бот, загугли", "бот загугли", "бот: загугли", "ботик, найди",
        "БОТЯРА! загугли", "   Бот, загугли",
    ])
    def test_default_tokens(self, empty_name, text):
        tok, rest = cp.split_prefix(text)
        assert tok is not None
        assert rest.startswith(("загугли", "найди"))

    @pytest.mark.parametrize("text", [
        "Олег, загугли", "олега загугли", "Олегу, найди", "олегом: поищи",
    ])
    def test_name_inflections(self, oleg_name, text):
        tok, rest = cp.split_prefix(text)
        assert tok is not None

    def test_default_tokens_off_when_named(self, oleg_name):
        # Имя задано → ботворд-префикс больше НЕ работает.
        assert cp.split_prefix("Бот, загугли X") == (None, "Бот, загугли X")
        assert cp.split_prefix("ботик, найди X") == (None, "ботик, найди X")

    def test_false_positives_rejected(self, empty_name):
        assert cp.split_prefix("работа загугли X")[0] is None
        assert cp.split_prefix("ботва загугли X")[0] is None

    def test_short_name_no_inflections(self):
        bot_persona.set_global_name_cache("И")
        assert cp.command_prefix_tokens() == ("и",)
        tok, rest = cp.split_prefix("И, загугли X")
        assert tok == "и" and rest == "загугли X"

    def test_split_prefix_anywhere(self, oleg_name):
        # R10.15-1: обращение после URL (якорный split_prefix его не видит).
        text = f"{YT_URL} Олег, поясни за видос"
        assert cp.split_prefix(text)[0] is None
        tok, rest, at = cp.split_prefix_anywhere(text)
        assert tok == "олег" and rest == "поясни за видос"
        assert text[:at].rstrip() == YT_URL
        # нет обращения вовсе.
        assert cp.split_prefix_anywhere("просто текст") == (None, "просто текст", -1)

    def test_functional_group(self, oleg_name):
        assert cp.functional_group("Олег, скачай " + DL_URL) == "download"
        assert cp.functional_group("Олег, привет") is None
        assert cp.functional_group("Олег, запомни X") is None


# ── 3. search ────────────────────────────────────────────────────────

class TestSearch:
    def test_named_body(self, oleg_name):
        assert search_mod._parse_search_query("Олег, загугли X") == "X"

    def test_bare_unhandled(self, oleg_name):
        assert search_mod._parse_search_query("загугли X") is None

    def test_trigger_without_body(self, empty_name):
        assert search_mod._parse_search_query("Бот, найди") == ""

    # Review-fix M1: подстрока-двойник не перехватывается.
    def test_false_positive_not_trigger(self, empty_name):
        assert search_mod._parse_search_query("Бот, загуглика") is None
        assert search_mod._parse_search_query("Бот, найдикто") is None
        assert search_mod._parse_search_query("Бот, поищите") is None


# ── 4. youtube / web ─────────────────────────────────────────────────

class TestYoutubeWeb:
    def test_youtube_parses_with_name(self, oleg_name):
        msg = _msg(text=f"Олег, поясни за видос {YT_URL}")
        target, video_id = youtube_mod._parse(msg)
        assert target is msg and video_id == "dQw4w9WgXcQ"

    @pytest.mark.asyncio
    async def test_youtube_trigger_without_target_consumed(self, oleg_name):
        old = youtube_mod._service
        youtube_mod._service = MagicMock()
        try:
            bot = AsyncMock()
            msg = _msg(text="Олег, поясни за видос")
            result = await youtube_mod.youtube_handler(msg, bot=bot)
            assert result is None
            assert bot.send_message.await_args.args[1] in COMMAND_NO_TARGET_PHRASES
        finally:
            youtube_mod._service = old

    @pytest.mark.asyncio
    async def test_youtube_bare_unhandled(self, oleg_name):
        old = youtube_mod._service
        youtube_mod._service = MagicMock()
        try:
            bot = AsyncMock()
            msg = _msg(text="поясни за видос")
            assert await youtube_mod.youtube_handler(msg, bot=bot) is UNHANDLED
        finally:
            youtube_mod._service = old

    def test_web_parses_with_name(self, oleg_name):
        msg = _msg(text=f"Олег, поясни за ссылку {WEB_URL}")
        target, url = web_mod._parse(msg)
        assert target is msg and url == WEB_URL

    # Follow-up R10.15-1: «ссылка-первой» из гайда F7 §3/§4 (URL до обращения).
    def test_youtube_link_first_parses(self, oleg_name):
        msg = _msg(text=f"{YT_URL} Олег, поясни за видос")
        assert youtube_mod._triggered_body(msg) is not None
        target, video_id = youtube_mod._parse(msg)
        assert target is msg and video_id == "dQw4w9WgXcQ"

    def test_web_link_first_parses(self, oleg_name):
        msg = _msg(text=f"{WEB_URL} Олег, выжимка")
        assert web_mod._triggered_body(msg) is not None
        target, url = web_mod._parse(msg)
        assert target is msg and url == WEB_URL

    def test_link_first_requires_url_before_prefix(self, oleg_name):
        # Без URL до обращения — не команда (обычная речь → LLM).
        assert youtube_mod._triggered_body(
            _msg(text="эй Олег, поясни за видос")) is None
        assert web_mod._triggered_body(_msg(text="эй Олег, выжимка")) is None

    def test_youtube_trigger_anywhere_with_direct_url(self, oleg_name):
        # D126: URL+триггер в любом порядке, цель — прямая медиа-ссылка.
        msg = _msg(text="Олег, скинь https://cdn.example.com/v.mp4 транскрипт")
        assert youtube_mod._triggered_body(msg) is not None

    # Follow-up R10.15-3: речь со словом-триггером вне команды НЕ консьюмится.
    @pytest.mark.asyncio
    async def test_youtube_plain_speech_trigger_not_consumed(self, oleg_name):
        old = youtube_mod._service
        youtube_mod._service = MagicMock()
        try:
            bot = AsyncMock()
            msg = _msg(text="Олег, помнишь транскрипт того созвона?")
            assert await youtube_mod.youtube_handler(msg, bot=bot) is UNHANDLED
            bot.send_message.assert_not_awaited()
        finally:
            youtube_mod._service = old

    @pytest.mark.asyncio
    async def test_web_plain_speech_trigger_not_consumed(self, oleg_name):
        old = web_mod._service
        web_mod._service = MagicMock()
        try:
            bot = AsyncMock()
            msg = _msg(text="Олег, напомни, что такое выжимка?")
            assert await web_mod.web_handler(msg, bot=bot) is UNHANDLED
            bot.send_message.assert_not_awaited()
        finally:
            web_mod._service = old

    # Review-fix M1: подстроки-двойники не триггерят.
    def test_false_positives_not_trigger(self, empty_name):
        assert youtube_mod._has_trigger("транскриптер") is False
        assert youtube_mod._triggered_body(_msg(text="Бот, транскриптер")) is None
        assert web_mod._has_trigger("выжимкалка") is False
        assert web_mod._triggered_body(_msg(text="Бот, выжимкалка")) is None

    @pytest.mark.asyncio
    async def test_youtube_false_positive_unhandled(self, oleg_name):
        old = youtube_mod._service
        youtube_mod._service = MagicMock()
        try:
            bot = AsyncMock()
            msg = _msg(text="Олег, транскриптер")
            assert await youtube_mod.youtube_handler(msg, bot=bot) is UNHANDLED
        finally:
            youtube_mod._service = old

    @pytest.mark.asyncio
    async def test_web_trigger_without_target_consumed(self, oleg_name):
        old = web_mod._service
        web_mod._service = MagicMock()
        try:
            bot = AsyncMock()
            msg = _msg(text="Олег, выжимка")
            result = await web_mod.web_handler(msg, bot=bot)
            assert result is None
            assert bot.send_message.await_args.args[1] in COMMAND_NO_TARGET_PHRASES
        finally:
            web_mod._service = old

    @pytest.mark.asyncio
    async def test_web_bare_unhandled(self, oleg_name):
        old = web_mod._service
        web_mod._service = MagicMock()
        try:
            bot = AsyncMock()
            msg = _msg(text="выжимка")
            assert await web_mod.web_handler(msg, bot=bot) is UNHANDLED
        finally:
            web_mod._service = old


# ── 5. checkup ───────────────────────────────────────────────────────

class TestCheckup:
    def test_bare_chekap(self, oleg_name):
        assert checkup_mod._is_checkup_trigger("чекап") is True

    def test_prefixed_with_name(self, oleg_name):
        assert checkup_mod._is_checkup_trigger("Олег, ты в порядке") is True
        assert checkup_mod._is_checkup_trigger("Олег, чекни здоровье") is True
        assert checkup_mod._is_checkup_trigger("Олег, живой?") is True

    def test_negatives(self, oleg_name):
        assert checkup_mod._is_checkup_trigger("живой") is False
        assert checkup_mod._is_checkup_trigger("живой собака") is False
        assert checkup_mod._is_checkup_trigger("ты в порядке") is False
        assert checkup_mod._is_checkup_trigger("пульс бота") is False


# ── 6. download ──────────────────────────────────────────────────────

class TestDownload:
    @pytest.mark.asyncio
    async def test_prefixed_triggers(self, oleg_name, monkeypatch):
        monkeypatch.setattr(vd, "_downloader", MagicMock(busy=False))
        msg = _msg(text=f"Олег, скачай {DL_URL}")
        assert vd._command_body(msg) == f"скачай {DL_URL}"
        assert vd._TRIGGER_RE.match(vd._command_body(msg))

    @pytest.mark.asyncio
    async def test_bare_unhandled(self, oleg_name, monkeypatch):
        monkeypatch.setattr(vd, "_downloader", MagicMock(busy=False))
        bot = AsyncMock()
        msg = _msg(text=f"скачай {DL_URL}")
        assert await vd.video_download_handler(msg, bot=bot) is UNHANDLED

    @pytest.mark.asyncio
    async def test_removed_aliases_bare_unhandled(self, oleg_name, monkeypatch):
        monkeypatch.setattr(vd, "_downloader", MagicMock(busy=False))
        bot = AsyncMock()
        for word in ("спизди", "скачать"):
            msg = _msg(text=f"Олег, {word} {DL_URL}")
            assert await vd.video_download_handler(msg, bot=bot) is UNHANDLED


# ── 7. direct_chat: имя-триггер и отключение дефолтов ────────────────

class TestDirectChatTrigger:
    @pytest.fixture
    def dc_env(self):
        old = (dc._service, dc._bot_id, dc._bot_username)
        dc.setup_direct_chat(service=MagicMock(), bot_id=999,
                             bot_username="adminbot")
        yield
        dc._service, dc._bot_id, dc._bot_username = old

    def test_name_set_disables_botword(self, oleg_name, dc_env):
        assert dc._is_direct_trigger(_msg(text="эй, бот")) is False

    def test_name_mention_triggers(self, oleg_name, dc_env):
        assert dc._is_direct_trigger(_msg(text="Олег, привет")) is True
        assert dc._is_direct_trigger(_msg(text="Олега, привет")) is True

    def test_empty_name_botword_active(self, empty_name, dc_env):
        assert dc._is_direct_trigger(_msg(text="эй, бот")) is True

    @pytest.mark.asyncio
    async def test_functional_command_yields_unhandled(self, oleg_name, dc_env,
                                                       monkeypatch):
        # Review-fix M2: yield только при ВКЛЮЧЁННОМ воркере download.
        _enable_flag(monkeypatch, "flags.download_enabled", True)
        msg = _msg(text=f"Олег, скачай {DL_URL}")
        assert dc._is_direct_trigger(msg) is True
        bot = AsyncMock()
        assert await dc.direct_chat_handler(msg, bot=bot) is UNHANDLED
        dc._service.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabled_download_not_lost(self, oleg_name, dc_env,
                                              monkeypatch):
        """Review-fix M2: выключенный download → сообщение уходит в LLM."""
        _enable_flag(monkeypatch, "flags.download_enabled", False)
        dc._service.handle = AsyncMock()
        msg = _msg(text=f"Олег, скачай {DL_URL}")
        assert dc._is_direct_trigger(msg) is True
        result = await dc.direct_chat_handler(msg, bot=AsyncMock())
        assert result is not UNHANDLED
        dc._service.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disabled_search_not_lost(self, oleg_name, dc_env,
                                            monkeypatch):
        """Review-fix M2: выключенный search → сообщение не теряется."""
        _enable_flag(monkeypatch, "flags.search_enabled", False)
        dc._service.handle = AsyncMock()
        msg = _msg(text="Олег, загугли новости")
        result = await dc.direct_chat_handler(msg, bot=AsyncMock())
        assert result is not UNHANDLED
        dc._service.handle.assert_awaited_once()


# ── 8. Приоритет: функциональная команда не уходит в LLM ─────────────

class TestPriority:
    @pytest.mark.asyncio
    async def test_search_consumes_llm_not_called(self, oleg_name):
        service = MagicMock()
        service.research = AsyncMock(return_value="ответ поиска")
        old = search_mod._service
        search_mod._service = service
        try:
            bot = AsyncMock()
            msg = _msg(text="Олег, загугли новости")
            result = await search_mod.smartsearch_handler(msg, bot=bot)
            assert result is None
            service.research.assert_awaited_once()
        finally:
            search_mod._service = old
            search_mod._cooldown._last.clear()
