"""MOD-ACL-UX-01 M2.1 — per-chat adapters для 12 потребителей модулей.

Каждый тест проверяет ФАКТИЧЕСКУЮ ветку потребления (handler/tool/API/worker),
а не только unit резолвера:

* GLOBAL ON + явный CHAT OFF → функция этого чата не исполняется;
* GLOBAL OFF + явный CHAT ON → исполняется по канонической семантике
  `GLOBAL default → CHAT override` (owner input §2/§5; MAC-S2-TT-4) для всех
  12 модулей, включая shared-сервисы (`initiative`, `character`, `random`):
  чат решает использование, общий пул/модель/планировщик не останавливаются;
* аварийная env-ось (`MCA_INTENTS_ENABLED`, `MCA_SELF_MODEL_ENABLED`,
  `MCA_RANDOM_SOURCE_ENABLED`) остаётся отдельным `emergency_block`;
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
    # ACL-порядок проверяется отдельным тестом F8; здесь — per-chat гейт.
    monkeypatch.setattr(api, "_require_scope_access", AsyncMock())
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

    world.globals = {"flags.self_model_enabled": True}
    _set_chat(world, _one({"flags.self_model_enabled": False}))
    await bot_persona.resolve_character_context(ROOT_CHAT)
    assert called == []                         # CHAT OFF → модель не тронута

    # GLOBAL OFF + CHAT ON → модель используется только в этом чате.
    world.globals = {"flags.self_model_enabled": False}
    _set_chat(world, _one({"flags.self_model_enabled": True}))
    await bot_persona.resolve_character_context(ROOT_CHAT)
    assert called == [ROOT_CHAT]

    called.clear()
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

    # GLOBAL OFF + CHAT ON → использование в чате разрешено (пул жив).
    world.globals = {"memory.random_enabled": False}
    _set_chat(world, _one({"memory.random_enabled": True}))
    allowed, reason = await mca_exploration.exploration_allowed(
        None, purpose, ROOT_CHAT)
    assert (allowed, reason) == (True, None)

    world.globals = {"memory.random_enabled": True}
    _set_chat(world, _one({"memory.random_enabled": True}))
    allowed, reason = await mca_exploration.exploration_allowed(
        None, purpose, ROOT_CHAT)
    assert (allowed, reason) == (True, None)


# ═══ 12. initiative — GLOBAL default + CHAT override, scheduler alive ═════

@pytest.mark.asyncio
async def test_initiative_global_off_chat_on_per_chat(world, monkeypatch):
    from services import initiative_observer as io

    world.globals = {"flags.initiative_enabled": False,
                     "flags.initiative_observer_enabled": True,
                     "initiative.enabled": False}
    _set_chat(world, _one({"initiative.enabled": True}))
    # GLOBAL OFF + CHAT ON → публикация этого чата разрешена.
    assert await io.initiative_publish_block_reason(ROOT_CHAT) is None
    # Планировщик не ранний `disabled`: тик доходит до выбора чатов.
    seen = []

    async def _due(db, *, now=None):
        seen.append("due")
        return [ROOT_CHAT]

    async def _active(db):
        return {"status": io.JOB_RUNNING, "job_id": "job"}

    monkeypatch.setattr(io, "_due_chats", _due)
    monkeypatch.setattr(io, "get_active_observe", _active)
    assert await io.observe_tick(object()) == "running"
    assert seen == ["due"]

    # GLOBAL ON + CHAT OFF → публикация этого чата запрещена.
    world.globals = {"flags.initiative_enabled": True,
                     "initiative.enabled": True}
    _set_chat(world, _one({"initiative.enabled": False}))
    assert await io.initiative_publish_block_reason(ROOT_CHAT) == "capability_off"

    # Аварийная env-ось выключает даже CHAT ON (желание не подменяется).
    monkeypatch.setattr(mca_gates, "settings",
                        types.SimpleNamespace(MCA_INTENTS_ENABLED=False))
    _set_chat(world, _one({"initiative.enabled": True}))
    state = await io.chat_capability_state(ROOT_CHAT, fresh=True)
    assert state is not None
    assert state.desired is True
    assert state.emergency_block is True
    assert state.effective_runtime is False
    assert await io.initiative_publish_block_reason(ROOT_CHAT) == "capability_off"


# ═══ 14. factcheck tool announcement — per chat (F5) ═══════════════════════

@pytest.mark.asyncio
async def test_factcheck_tool_path_per_chat(world, monkeypatch):
    from services import tool_schemas as ts

    monkeypatch.setattr(ts, "_fact_check_tool_env_enabled", lambda: True)
    monkeypatch.setattr(ts, "_temporal_tool_enabled", lambda: True)

    world.globals = {"flags.factcheck_enabled": False}
    _set_chat(world, _one({"flags.factcheck_enabled": True}))
    names = {t["function"]["name"]
             for t in await ts.active_tools_for_chat(ROOT_CHAT)}
    assert "fact_check" in names          # GLOBAL OFF + CHAT ON → инструмент есть

    world.globals = {"flags.factcheck_enabled": True}
    _set_chat(world, _one({"flags.factcheck_enabled": False}))
    names = {t["function"]["name"]
             for t in await ts.active_tools_for_chat(ROOT_CHAT)}
    assert "fact_check" not in names      # GLOBAL ON + CHAT OFF → скрыт

    # Аварийная env-ось важнее чата.
    monkeypatch.setattr(ts, "_fact_check_tool_env_enabled", lambda: False)
    _set_chat(world, _one({"flags.factcheck_enabled": True}))
    names = {t["function"]["name"]
             for t in await ts.active_tools_for_chat(ROOT_CHAT)}
    assert "fact_check" not in names


# ═══ 15. checkup readiness — effective per chat (F6) ═══════════════════════

@pytest.mark.asyncio
async def test_checkup_readiness_per_chat(world):
    from services import capability_registry as cr

    world.globals = {"flags.checkup_enabled": False}
    _set_chat(world, _one({"flags.checkup_enabled": True}))
    state = await cr._build_health(ROOT_CHAT)
    assert state.status == cr.STATUS_READY

    world.globals = {"flags.checkup_enabled": True}
    _set_chat(world, _one({"flags.checkup_enabled": False}))
    state = await cr._build_health(ROOT_CHAT)
    assert state.status == cr.STATUS_DISABLED
    assert state.reason_code == "checkup_module_disabled"


# ═══ 16. stories ACL → per-chat gate order (F8) ════════════════════════════

@pytest.mark.asyncio
async def test_stories_acl_precedes_per_chat_gate(world, monkeypatch):
    from fastapi import HTTPException
    from web.api import stories as api

    class _Request:
        app = types.SimpleNamespace(
            state=types.SimpleNamespace(cache=object()))

    async def _deny(request, user, chat_id):
        raise HTTPException(status_code=403, detail="permission denied")

    monkeypatch.setattr(api, "_require_chat_access", _deny)
    monkeypatch.setattr(api, "_db_or_unavailable", lambda: None)
    world.globals = {"flags.stories_vitrina_enabled": False}
    _set_chat(world, _one({"flags.stories_vitrina_enabled": False}))
    with pytest.raises(HTTPException) as exc:
        await api.stories_summary(_Request(), types.SimpleNamespace(id=1),
                                  str(ROOT_CHAT))
    assert exc.value.status_code == 403


# ═══ 17. voice transcription DI не гейтится глобальным ON (F7) ═════════════

def test_voice_transcription_di_is_not_conditional():
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "bot.py").read_text(encoding="utf-8"))
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "setup_voice_transcription"]
    assert calls, "startup должен выполнять DI голосовой транскрипции"
    for call in calls:
        parent = parents.get(call)
        while parent is not None:
            assert not isinstance(parent, ast.If), (
                "DI не должен зависеть от глобального flags.enable_voice_"
                "transcription: per-chat гейт живёт в handler")
            parent = parents.get(parent)


# ═══ 18. feature_gates adapter — таблица для 8 static-карточек ════════════

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


# ═══ 19. transcribe: командный форс-повтор — per chat (D2) ════════════════

@pytest.mark.asyncio
async def test_force_repeat_transcribe_per_chat(world, monkeypatch):
    """D2: «транскрипт» по reply-ГС уважает чатовый OFF модуля.

    Реальная ветка: `handlers.voice_transcription.force_repeat_from_reply`
    (её же зовёт `handlers/youtube._handle_voice_command`) → STT. При
    GLOBAL ON + CHAT OFF транскрипт НЕ вызывается (fail-closed внутри
    канонического резолвера); при GLOBAL OFF + CHAT ON — вызывается.
    """
    from handlers import voice_transcription as vt

    transcribe = AsyncMock(return_value=True)
    monkeypatch.setattr(vt, "_service", object())
    monkeypatch.setattr(vt, "transcribe_media_message", transcribe)
    voice = types.SimpleNamespace(
        message_id=21, chat=types.SimpleNamespace(id=ROOT_CHAT),
        voice=types.SimpleNamespace(file_id="voice-file"),
        video_note=None)
    command = _msg("транскрипт", message_id=22)
    command.reply_to_message = voice

    world.globals = {"flags.enable_voice_transcription": True}
    _set_chat(world, _one({"flags.enable_voice_transcription": False}))
    assert await vt.force_repeat_from_reply(
        object(), command) == vt.FORCE_REPEAT_NO_TARGET
    transcribe.assert_not_awaited()

    world.globals = {"flags.enable_voice_transcription": False}
    _set_chat(world, _one({"flags.enable_voice_transcription": True}))
    assert await vt.force_repeat_from_reply(
        object(), command) == vt.FORCE_REPEAT_SENT_OK
    transcribe.assert_awaited_once()
    assert transcribe.await_args.kwargs.get("force") is True
    assert transcribe.await_args.args[0] is voice


# ═══ 20. character: frame при GLOBAL OFF + CHAT ON (D3) ════════════════════

@pytest.mark.asyncio
async def test_character_frame_renders_when_global_off_chat_on(
        world, monkeypatch):
    """D3: точка сборки промпта рендерит кадр этого чата, а не legacy.

    GLOBAL OFF + CHAT ON: `resolve_character_context` (канонический per-chat
    резолвер) ставит кадр, `build_persona_prompt_block(chat_id=…)` его
    использует — формат/семантика совпадают с GLOBAL ON (тот же
    `render_frame_block`). GLOBAL ON + CHAT OFF — кадра нет, legacy.
    """
    from services import bot_persona, lore_runtime, mca_self_model as msm

    frame = types.SimpleNamespace(version="v1", applied_rules=())
    snapshot = types.SimpleNamespace(
        persona_enabled=types.SimpleNamespace(effective=lambda *a: True))

    async def _resolve(db, chat_id):
        return snapshot

    rendered: list = []

    def _render(behavior_frame, **kwargs):
        rendered.append((behavior_frame, kwargs))
        return "<FRAME>"

    monkeypatch.setattr(msm, "resolve_self_model", _resolve)
    monkeypatch.setattr(msm, "select_behavior", lambda snap: frame)
    monkeypatch.setattr(msm, "render_frame_block", _render)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: object())
    monkeypatch.setattr(
        bot_persona, "resolve_bot_persona",
        lambda chat_id: AsyncMock(return_value=bot_persona.BotPersona(
            name="Бот", biography="", overrides=""))())
    monkeypatch.setattr(bot_persona, "get_traits",
                        lambda *a, **k: AsyncMock(return_value=[])())

    world.globals = {"flags.self_model_enabled": False}
    _set_chat(world, _one({"flags.self_model_enabled": True}))
    ctx = await bot_persona.resolve_character_context(ROOT_CHAT)
    assert ctx.frame_version == "v1"        # per-chat резолвер сработал
    block = bot_persona.build_persona_prompt_block(
        ctx.persona, ctx.traits, enabled=True, chat_id=ROOT_CHAT)
    assert block == "<FRAME>"               # кадр, а не legacy-ветка
    off_frame = rendered[-1][0]

    # Формат/семантика GLOBAL ON — тот же кадр/тот же рендер.
    world.globals = {"flags.self_model_enabled": True}
    _set_chat(world, _one({"flags.self_model_enabled": True}))
    ctx_on = await bot_persona.resolve_character_context(ROOT_CHAT)
    block_on = bot_persona.build_persona_prompt_block(
        ctx_on.persona, ctx_on.traits, enabled=True, chat_id=ROOT_CHAT)
    assert block_on == block
    assert rendered[-1][0] is off_frame

    # GLOBAL ON + CHAT OFF — кадр не резолвится, сборка остаётся legacy.
    bot_persona.reset_turn_frame()
    world.globals = {"flags.self_model_enabled": True}
    _set_chat(world, _one({"flags.self_model_enabled": False}))
    ctx_off = await bot_persona.resolve_character_context(ROOT_CHAT)
    assert ctx_off.frame_version is None
    legacy = bot_persona.build_persona_prompt_block(
        ctx_off.persona, ctx_off.traits, enabled=True, chat_id=ROOT_CHAT)
    assert legacy != "<FRAME>" and "<Persona>" in legacy
