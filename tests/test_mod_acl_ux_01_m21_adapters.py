"""MOD-ACL-UX-01 M2.1 — per-chat adapters для 12 потребителей модулей.

Каждый тест проверяет ФАКТИЧЕСКУЮ ветку потребления (handler/tool/API/worker),
а не только unit резолвера:

* GLOBAL ON + явный CHAT OFF → функция этого чата не исполняется;
* GLOBAL OFF + явный CHAT ON → исполняется по канонической семантике
  `GLOBAL default → CHAT override` (owner input §2/§5; MAC-S2-TT-4), кроме
  shared-модулей (`initiative`, `character`, `random`), где глобальный master
  сохраняется как AND-ось и чат не обходит его;
* INHERIT читает глобальный слой; stored values не переписываются.

`nostalgia` проверяется отдельным файлом (`test_mod_acl_ux_01_m21_gates.py`)
вместе с precedence и структурным отсутствием второго резолвера.
"""
import copy
import time
import types
from unittest.mock import AsyncMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

from services import chat_params, feature_gates, hot_config, mca_gates
from services import module_registry

ROOT_CHAT = -100
OTHER_CHAT = -200


class _Cache:
    """chat_params-кэш: root-лейаут без side effects (как в M2-тестах)."""

    def __init__(self, by_chat=None):
        self.by_chat = copy.deepcopy(by_chat or {})
        self.invalidated: list[int] = []

    @staticmethod
    def _root(data):
        return {"overrides": dict((data or {}).get("overrides") or {}),
                "gates": dict((data or {}).get("gates") or {})}

    async def get_chat_params(self, chat_id):
        return self._root(self.by_chat.get(int(chat_id)))

    async def get_chat_params_full(self, chat_id):
        return self._root(self.by_chat.get(int(chat_id))), None

    async def get_chat_params_checked(self, chat_id):
        return self._root(self.by_chat.get(int(chat_id))), True

    async def get_chat_params_fresh(self, chat_id):
        return self._root(self.by_chat.get(int(chat_id))), None, True

    async def invalidate_chat(self, chat_id):
        self.invalidated.append(int(chat_id))


class _World:
    def __init__(self):
        self.globals: dict = {}
        self.cache = None


@pytest.fixture
def world(monkeypatch):
    w = _World()
    monkeypatch.setattr(hot_config, "get",
                        lambda key, default=None: w.globals.get(key, default))
    monkeypatch.setattr(module_registry, "env_enabled", lambda mid: True)
    chat_params.set_chat_params_cache(None)
    yield w
    chat_params.set_chat_params_cache(None)


def _set_chat(world, by_chat):
    world.cache = _Cache(by_chat)
    chat_params.set_chat_params_cache(world.cache)
    return world.cache


def _one(overrides=None):
    return {ROOT_CHAT: {"overrides": dict(overrides or {}), "gates": {}}}


def _msg(text="", *, chat_id=ROOT_CHAT, message_id=11, user_id=5):
    msg = types.SimpleNamespace()
    msg.text = text
    msg.caption = None
    msg.message_id = message_id
    msg.chat = types.SimpleNamespace(id=chat_id)
    msg.from_user = types.SimpleNamespace(id=user_id)
    msg.reply_to_message = None
    msg.photo = None
    msg.document = None
    msg.entities = ()
    msg.caption_entities = ()
    return msg


# ═══ 1. direct — триггерная поверхность ════════════════════════════════════

@pytest.mark.asyncio
async def test_direct_handler_per_chat(world, monkeypatch):
    from handlers import direct_chat as dc
    from services import bot_persona

    bot_persona.set_global_name_cache("")
    service = types.SimpleNamespace(handle=AsyncMock())
    dc.setup_direct_chat(service, bot_id=999, bot_username="adminbot")
    try:
        # GLOBAL ON + CHAT OFF → триггер не срабатывает, сервис не вызван.
        world.globals = {"flags.direct_chat_botword_enabled": True}
        _set_chat(world, _one({"flags.direct_chat_botword_enabled": False}))
        assert await dc.direct_chat_handler(_msg("эй, бот"), bot=object()) \
            is UNHANDLED
        service.handle.assert_not_awaited()

        # GLOBAL OFF + CHAT ON → явный чат ON включает функцию (owner §2).
        world.globals = {"flags.direct_chat_botword_enabled": False}
        _set_chat(world, _one({"flags.direct_chat_botword_enabled": True}))
        assert await dc.direct_chat_handler(_msg("эй, бот"), bot=object()) is None
        service.handle.assert_awaited_once()

        # INHERIT → глобальный ON.
        world.globals = {"flags.direct_chat_botword_enabled": True}
        _set_chat(world, _one({}))
        assert await dc.direct_chat_handler(_msg("эй, бот"), bot=object()) is None
        assert service.handle.await_count == 2
    finally:
        dc.setup_direct_chat(None, None, None)


@pytest.mark.asyncio
async def test_direct_functional_yield_is_per_chat(world, monkeypatch):
    from handlers import direct_chat as dc

    monkeypatch.setattr(dc, "download_available", lambda: True)
    world.globals = {"flags.download_enabled": False}
    _set_chat(world, _one({"flags.download_enabled": True}))
    assert await dc._functional_module_active_for_chat(
        ROOT_CHAT, "download") is True     # chat ON → yield воркеру

    world.globals = {"flags.download_enabled": True}
    _set_chat(world, _one({"flags.download_enabled": False}))
    assert await dc._functional_module_active_for_chat(
        ROOT_CHAT, "download") is False    # chat OFF → не съедать команду


# ═══ 2. factcheck ══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_factcheck_handler_per_chat(world, monkeypatch):
    from handlers import factcheck as fc

    reached = []
    monkeypatch.setattr(fc, "_service", object())
    monkeypatch.setattr(fc, "_parse_trigger",
                        lambda message: (reached.append(message.chat.id), (None, None))[1])
    monkeypatch.setattr(fc, "_adjacent_target_or_ambiguous",
                        AsyncMock(return_value=(None, False)))

    world.globals = {"flags.factcheck_enabled": True}
    _set_chat(world, _one({"flags.factcheck_enabled": False}))
    assert await fc.factcheck_handler(_msg("фактчек: правда?"), bot=object()) \
        is UNHANDLED
    assert reached == []

    world.globals = {"flags.factcheck_enabled": False}
    _set_chat(world, _one({"flags.factcheck_enabled": True}))
    assert await fc.factcheck_handler(_msg("фактчек: правда?"), bot=object()) \
        is UNHANDLED
    assert reached == [ROOT_CHAT]


# ═══ 3. search / 4. web ═══════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_search_handler_per_chat(world, monkeypatch):
    from handlers import search as sm

    service = types.SimpleNamespace(research=AsyncMock(return_value="ok"))
    sm.setup_search(service)
    sm._cooldown._last.clear()
    bot = AsyncMock()
    try:
        world.globals = {"flags.search_enabled": True}
        _set_chat(world, _one({"flags.search_enabled": False}))
        assert await sm.smartsearch_handler(
            _msg("Бот, найди X"), bot=bot) is UNHANDLED
        service.research.assert_not_awaited()

        world.globals = {"flags.search_enabled": False}
        _set_chat(world, _one({"flags.search_enabled": True}))
        sm._cooldown._last.clear()
        await sm.smartsearch_handler(_msg("Бот, найди X"), bot=bot)
        service.research.assert_awaited_once()
    finally:
        sm._service = None
        sm._cooldown._last.clear()


@pytest.mark.asyncio
async def test_web_handler_per_chat(world):
    from handlers import web as wm

    service = types.SimpleNamespace(summarize=AsyncMock(return_value="ok"))
    wm.setup_web(service)
    wm._cooldown._last.clear()
    bot = AsyncMock()
    url = "https://habr.com/ru/articles/1"
    try:
        world.globals = {"flags.webpage_enabled": True}
        _set_chat(world, _one({"flags.webpage_enabled": False}))
        assert await wm.web_handler(
            _msg(f"Бот, выжимка {url}"), bot=bot) is UNHANDLED
        service.summarize.assert_not_awaited()

        world.globals = {"flags.webpage_enabled": False}
        _set_chat(world, _one({"flags.webpage_enabled": True}))
        wm._cooldown._last.clear()
        await wm.web_handler(_msg(f"Бот, выжимка {url}"), bot=bot)
        service.summarize.assert_awaited_once()
    finally:
        wm._service = None
        wm._cooldown._last.clear()


# ═══ 5. voice transcribe ══════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_transcribe_handler_per_chat(world, monkeypatch):
    from handlers import voice_transcription as vt

    process = AsyncMock()
    monkeypatch.setattr(vt, "_process", process)
    monkeypatch.setattr(vt, "_service", object())

    world.globals = {"flags.enable_voice_transcription": True}
    _set_chat(world, _one({"flags.enable_voice_transcription": False}))
    assert await vt.voice_transcription_handler(_msg(), bot=object()) \
        is UNHANDLED
    process.assert_not_awaited()

    world.globals = {"flags.enable_voice_transcription": False}
    _set_chat(world, _one({"flags.enable_voice_transcription": True}))
    assert await vt.voice_transcription_handler(_msg(), bot=object()) \
        is UNHANDLED
    process.assert_awaited_once()


# ═══ 6. video summary ═════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_video_summary_dispatch_per_chat(world, monkeypatch):
    from handlers import youtube as yt

    request = types.SimpleNamespace(
        kind="youtube", mode="summary", operation="summary",
        source_ref="", correlation_id="", intent="", video_id="x")
    message = _msg("Бот, выжимка https://youtu.be/x")
    monkeypatch.setattr(yt.video_intent, "job_key",
                        lambda *a, **k: "job")
    monkeypatch.setattr(yt.video_intent, "try_begin", lambda job: False)

    world.globals = {"flags.video_summary_enabled": True}
    _set_chat(world, _one({"flags.video_summary_enabled": False}))
    assert await yt._dispatch_video_request(
        object(), message, request) is UNHANDLED

    world.globals = {"flags.video_summary_enabled": False}
    _set_chat(world, _one({"flags.video_summary_enabled": True}))
    assert await yt._dispatch_video_request(
        object(), message, request) is None


# ═══ 7. media download: handler + tool path ═══════════════════════════════

@pytest.mark.asyncio
async def test_download_handler_per_chat(world, monkeypatch):
    from handlers import video_download as vd

    reached = []
    monkeypatch.setattr(vd, "_downloader", object())
    monkeypatch.setattr(vd, "_command_body",
                        lambda message: reached.append(message.chat.id))

    world.globals = {"flags.download_enabled": True}
    _set_chat(world, _one({"flags.download_enabled": False}))
    assert await vd.video_download_handler(_msg(), bot=object()) is UNHANDLED
    assert reached == []

    world.globals = {"flags.download_enabled": False}
    _set_chat(world, _one({"flags.download_enabled": True}))
    assert await vd.video_download_handler(_msg(), bot=object()) is UNHANDLED
    assert reached == [ROOT_CHAT]


@pytest.mark.asyncio
async def test_download_tool_path_per_chat(world, monkeypatch):
    from services.tool_router import ToolRouter

    router = object.__new__(ToolRouter)
    router.deps = types.SimpleNamespace(downloader=None)
    monkeypatch.setattr(router, "_resolve_tool_source",
                        lambda arguments, ctx: ("url", "https://x", None))
    ctx = types.SimpleNamespace(chat_id=ROOT_CHAT, bot=object(), user_id=1,
                                reply_to_message_id=None)

    world.globals = {"flags.download_enabled": True}
    _set_chat(world, _one({"flags.download_enabled": False}))
    off = await router._download_media({}, ctx)
    assert "Скачивание отключено" in off

    world.globals = {"flags.download_enabled": False}
    _set_chat(world, _one({"flags.download_enabled": True}))
    on = await router._download_media({}, ctx)
    assert "Скачивание недоступно" in on    # гейт пройден, ветка дальше


@pytest.mark.asyncio
async def test_download_callback_rechecks_per_chat(world, monkeypatch):
    """Меню качества, открытое до CHAT OFF, не запускает скачивание."""
    from handlers import video_download as vd

    monkeypatch.setattr(vd, "_downloader", object())
    key = (ROOT_CHAT, 5)
    vd._PENDING[key] = {
        "urls": ["https://example.com/v"], "probes": [None], "selected": 0,
        "trigger_message_id": 11, "expires": time.monotonic() + 60,
    }
    callback = types.SimpleNamespace(
        message=types.SimpleNamespace(chat=types.SimpleNamespace(id=ROOT_CHAT)),
        from_user=types.SimpleNamespace(id=5), data="vd:720",
        answer=AsyncMock())
    try:
        world.globals = {"flags.download_enabled": True}
        _set_chat(world, _one({"flags.download_enabled": False}))
        await vd.cb_pick_quality(callback, bot=object())
        callback.answer.assert_awaited_once()
        assert callback.answer.await_args.args[0] == "Скачивание отключено"
        assert key in vd._PENDING          # меню не исполнено, pending цел
    finally:
        vd._PENDING.pop(key, None)


# ═══ 8. checkup: handler + tool path ══════════════════════════════════════

@pytest.mark.asyncio
async def test_checkup_handler_per_chat(world, monkeypatch):
    from handlers import checkup as ch

    reached = []
    monkeypatch.setattr(ch, "_service", object())
    monkeypatch.setattr(ch, "_fetcher", object())
    monkeypatch.setattr(ch, "_is_checkup_trigger",
                        lambda text: (reached.append(text), False)[1])

    world.globals = {"flags.checkup_enabled": True}
    _set_chat(world, _one({"flags.checkup_enabled": False}))
    assert await ch.checkup_handler(_msg("чекап"), bot=object()) is UNHANDLED
    assert reached == []

    world.globals = {"flags.checkup_enabled": False}
    _set_chat(world, _one({"flags.checkup_enabled": True}))
    assert await ch.checkup_handler(_msg("чекап"), bot=object()) is UNHANDLED
    assert reached == ["чекап"]


@pytest.mark.asyncio
async def test_checkup_tool_per_chat(world, monkeypatch):
    from services.tool_router import ToolRouter

    router = object.__new__(ToolRouter)
    ctx = types.SimpleNamespace(chat_id=ROOT_CHAT)
    router.deps = types.SimpleNamespace(health=None)
    world.globals = {"flags.checkup_enabled": True}
    _set_chat(world, _one({"flags.checkup_enabled": False}))
    assert "модуль выключен" in await router._get_bot_health({}, ctx)

    world.globals = {"flags.checkup_enabled": False}
    _set_chat(world, _one({"flags.checkup_enabled": True}))
    assert "сервис недоступен" in await router._get_bot_health({}, ctx)


# ═══ 9. stories — read-контур API ═════════════════════════════════════════

@pytest.mark.asyncio
async def test_stories_read_api_per_chat(world, monkeypatch):
    from web.api import stories as api

    monkeypatch.setattr(api, "_db_or_unavailable", lambda: None)
    user = types.SimpleNamespace(id=1)
    request = object()

    world.globals = {"flags.stories_vitrina_enabled": True}
    _set_chat(world, _one({"flags.stories_vitrina_enabled": False}))
    off = await api.stories_summary(request, user, str(ROOT_CHAT))
    assert off.get("state") == "disabled"

    world.globals = {"flags.stories_vitrina_enabled": False}
    _set_chat(world, _one({"flags.stories_vitrina_enabled": True}))
    on = await api.stories_summary(request, user, str(ROOT_CHAT))
    assert on.get("state") == "unavailable"     # гейт пройден, БД нет


# ═══ 10. character — использование в чате ═════════════════════════════════

@pytest.mark.asyncio
async def test_character_usage_per_chat(world, monkeypatch):
    from services import bot_persona, lore_runtime, mca_self_model

    called = []
    async def _resolve(*args, **kwargs):
        called.append(kwargs.get("scope_chat_id",
                                 args[1] if len(args) > 1 else None))
        raise RuntimeError("sentinel")

    monkeypatch.setattr(mca_self_model, "resolve_self_model", _resolve)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: object())
    monkeypatch.setattr(bot_persona, "resolve_bot_persona",
                        lambda chat_id: AsyncMock(
                            return_value=bot_persona.BotPersona.empty())())
    monkeypatch.setattr(bot_persona, "get_traits",
                        lambda *a, **k: AsyncMock(return_value=[])())
    monkeypatch.setattr(mca_gates, "self_model_enabled", lambda: True)

    world.globals = {"flags.self_model_enabled": True}
    _set_chat(world, _one({"flags.self_model_enabled": False}))
    await bot_persona.resolve_character_context(ROOT_CHAT)
    assert called == []                         # CHAT OFF → модель не тронута

    world.globals = {"flags.self_model_enabled": True}
    _set_chat(world, _one({"flags.self_model_enabled": True}))
    await bot_persona.resolve_character_context(ROOT_CHAT)
    assert called == [ROOT_CHAT]                # оба ON → использование


# ═══ 11. random — использование в чате ════════════════════════════════════

@pytest.mark.asyncio
async def test_random_usage_per_chat(world, monkeypatch):
    from services import mca_exploration

    async def _use_ok(db, use, chat_id=None):
        return True

    monkeypatch.setattr(mca_exploration, "use_enabled", _use_ok)
    purpose = mca_exploration.PURPOSE_CONVERSATION_VARIANT

    world.globals = {"memory.random_enabled": True}
    _set_chat(world, _one({"memory.random_enabled": False}))
    allowed, reason = await mca_exploration.exploration_allowed(
        None, purpose, ROOT_CHAT)
    assert (allowed, reason) == (False, "disabled")

    world.globals = {"memory.random_enabled": True}
    _set_chat(world, _one({"memory.random_enabled": True}))
    allowed, reason = await mca_exploration.exploration_allowed(
        None, purpose, ROOT_CHAT)
    assert (allowed, reason) == (True, None)


# ═══ 12. initiative — product master-AND + chat ═══════════════════════════

@pytest.mark.asyncio
async def test_initiative_master_and_per_chat(world, monkeypatch):
    from services import initiative_observer as io

    # Глобальный product master OFF → chat ON не обходит master.
    monkeypatch.setattr(io, "observer_enabled", lambda: False)
    _set_chat(world, _one({"initiative.enabled": True}))
    assert await io.initiative_publish_block_reason(ROOT_CHAT) == "capability_off"

    # Master ON, чат OFF → публикация этого чата запрещена.
    monkeypatch.setattr(io, "observer_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
    world.globals = {"initiative.enabled": True}
    _set_chat(world, _one({"initiative.enabled": False}))
    assert await io.initiative_publish_block_reason(ROOT_CHAT) == "capability_off"

    # Master ON + чат ON → публикация разрешена (INHERIT/ON).
    _set_chat(world, _one({"initiative.enabled": True}))
    assert await io.initiative_publish_block_reason(ROOT_CHAT) is None

    # Тик не стартует при выключенном product master (chat ON не спасает).
    monkeypatch.setattr(io, "observer_enabled", lambda: False)
    assert await io.observe_tick(object()) == "disabled"


# ═══ 13. feature_gates adapter — таблица для 8 static-карточек ════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("key", [
    "flags.direct_chat_botword_enabled",
    "flags.factcheck_enabled",
    "flags.search_enabled",
    "flags.webpage_enabled",
    "flags.enable_voice_transcription",
    "flags.video_summary_enabled",
    "flags.download_enabled",
    "flags.checkup_enabled",
])
async def test_module_adapter_truth_table(world, key):
    """GLOBAL/CHAT/INHERIT — ровно каноническая таблица, без второго bool."""
    cases = [(True, None, True), (True, False, False),
             (False, None, False), (False, True, True)]
    for global_on, chat, expected in cases:
        world.globals = {key: global_on}
        _set_chat(world, _one({} if chat is None else {key: chat}))
        assert await feature_gates.module_enabled(ROOT_CHAT, key=key) is expected
    # stored values не переписаны
    assert world.cache.by_chat[ROOT_CHAT]["overrides"] == {key: True}
