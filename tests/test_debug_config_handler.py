"""Epic 85 (84.18.4, T-656) — тесты Telegram-команды /debug_config.

DoD п.17: только wildcard-админ/DM; не-админ — молчаливый отказ; секреты
маскируются в выводе; <pre>-блоки; разбиение длинного вывода; команда не в
set_my_commands (проверяем bot_commands.py — отсутствие 'debug_config').
"""
import types
from unittest.mock import AsyncMock

import pytest

from handlers import debug_config as dc_mod
from services import hot_config as hot
from services.permissions import Permissions


class _FakeCache:
    def __init__(self, values=None, admins=None, roles=None,
                 pg_available=True):
        self._settings = dict(values or {})
        self._settings_updated_at = {}
        self._loaded_at = "2026-08-30T02:00:00+00:00"
        self._admins = dict(admins or {})
        self._roles = dict(roles or {})
        self.pg_available = pg_available
        self.is_initialized = True

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def get_all(self):
        return dict(self._settings)

    def get_updated_at(self, key):
        return self._settings_updated_at.get(key)

    @property
    def loaded_at(self):
        return self._loaded_at

    def admins(self):
        return dict(self._admins)

    def get_permissions_by_telegram_id(self, tg_id):
        role = self._admins.get(tg_id)
        if role is None:
            return None
        data = (self._roles.get(role) or {}).get("permissions", {})
        return Permissions.from_dict(data)


def _make_msg(user_id, chat_type="private", text="/debug_config"):
    msg = types.SimpleNamespace()
    msg.text = text
    msg.chat = types.SimpleNamespace(id=12345, type=chat_type)
    msg.from_user = types.SimpleNamespace(id=user_id)
    msg.message_id = 1
    msg.delete = AsyncMock()
    msg.answer = AsyncMock()
    return msg


@pytest.fixture(autouse=True)
def _cache():
    hot.set_config_cache(_FakeCache(
        values={"limits.search_max_symbols": 8000,
                "keys.groq_api_key": "gsk_super_secret_1234"},
        admins={5885953495: "admin"},
        roles={"admin": {"permissions": {"wildcard": True}}},
    ))
    yield
    hot.set_config_cache(None)


@pytest.mark.asyncio
async def test_admin_dm_gets_dump(cache=None):
    msg = _make_msg(5885953495)
    await dc_mod.cmd_debug_config(msg)
    assert msg.delete.await_count == 1
    assert msg.answer.await_count >= 1
    html = "\n".join(c.args[0] for c in msg.answer.call_args_list)
    assert "<pre>" in html
    assert "In-Memory State Dump" in html
    assert "limits.search_max_symbols" in html


@pytest.mark.asyncio
async def test_secret_masked_in_output():
    msg = _make_msg(5885953495, text="/debug_config keys.groq_api_key")
    await dc_mod.cmd_debug_config(msg)
    html = msg.answer.call_args_list[0].args[0]
    assert "gsk_super_secret" not in html
    assert "last4: 1234" in html


@pytest.mark.asyncio
async def test_non_admin_silent_rejection():
    msg = _make_msg(999999999)
    await dc_mod.cmd_debug_config(msg)
    assert msg.answer.await_count == 0
    assert msg.delete.await_count == 0   # отказ ДО удаления


@pytest.mark.asyncio
async def test_single_key_output_contains_source_and_type():
    msg = _make_msg(5885953495, text="/debug_config limits.search_max_symbols")
    await dc_mod.cmd_debug_config(msg)
    html = msg.answer.call_args_list[0].args[0]
    assert "source=memory-cache" in html
    assert "type=int" in html


@pytest.mark.asyncio
async def test_long_dump_split_into_chunks():
    values = {f"limits.k{i}": i for i in range(400)}
    cache = _FakeCache(
        values=values,
        admins={5885953495: "admin"},
        roles={"admin": {"permissions": {"wildcard": True}}},
    )
    hot.set_config_cache(cache)
    msg = _make_msg(5885953495)
    await dc_mod.cmd_debug_config(msg)
    assert msg.answer.await_count > 1
    for call in msg.answer.call_args_list:
        assert len(call.args[0]) < 4096


def test_command_not_in_menu():
    """D95: /debug_config скрыта — не в set_my_commands (services/bot_commands.py)."""
    import services.bot_commands as bc_mod
    src = open(bc_mod.__file__, encoding="utf-8").read()
    assert "debug_config" not in src


def test_router_filter_private_only():
    """Регистрация DM-only: хендлер объявлен с F.chat.type == 'private'."""
    import inspect
    src = inspect.getsource(dc_mod)
    assert 'F.chat.type == "private"' in src


# ── HIGH-1 (ревью): HTML/&-значения, dict с HTML, огромный repr ─────────────

@pytest.mark.asyncio
async def test_html_value_escaped_not_parsed():
    """Значение с HTML-разметкой и & не роняет parse_mode и не отдаёт сырой
    разметки: <div> → &lt;div&gt;, & → &amp;."""
    cache = _FakeCache(
        values={"prompts.factcheck_system_prompt":
                '<div class="c"><b>x</b> a=1&b=2</div>'},
        admins={5885953495: "admin"},
        roles={"admin": {"permissions": {"wildcard": True}}},
    )
    hot.set_config_cache(cache)
    msg = _make_msg(5885953495, text="/debug_config prompts.factcheck_system_prompt")
    await dc_mod.cmd_debug_config(msg)
    html = "\n".join(c.args[0] for c in msg.answer.call_args_list)
    assert "<div" not in html
    assert "&lt;div" in html
    assert "&amp;" in html
    assert "&lt;b&gt;" in html


@pytest.mark.asyncio
async def test_dict_with_html_escaped_and_truncated():
    """content.info_how_it_works (dict с HTML) — repr обрезан до 200 +
    [len=…], разметка экранирована."""
    big_html = "<h1>Заголовок</h1>" + "<p>текст</p>" * 60
    cache = _FakeCache(
        values={"content.info_how_it_works": {"html": big_html,
                                              "updated_by": 1}},
        admins={5885953495: "admin"},
        roles={"admin": {"permissions": {"wildcard": True}}},
    )
    hot.set_config_cache(cache)
    msg = _make_msg(5885953495, text="/debug_config content.info_how_it_works")
    await dc_mod.cmd_debug_config(msg)
    html = "\n".join(c.args[0] for c in msg.answer.call_args_list)
    assert "<h1>" not in html
    assert "&lt;h1&gt;" in html
    assert "[len=" in html        # обрезка с указанием полной длины


@pytest.mark.asyncio
async def test_every_chunk_within_limit():
    """Каждый чанк ≤ 4096 даже при огромном dict-repr и сотнях ключей."""
    huge_dict = {"ключ": "значение " * 300}   # repr ~1200 символов
    values = {f"content.big{i}": huge_dict for i in range(30)}
    values["limits.alan_reply_interval"] = 10
    cache = _FakeCache(
        values=values,
        admins={5885953495: "admin"},
        roles={"admin": {"permissions": {"wildcard": True}}},
    )
    hot.set_config_cache(cache)
    msg = _make_msg(5885953495)
    await dc_mod.cmd_debug_config(msg)
    assert msg.answer.await_count >= 1
    for call in msg.answer.call_args_list:
        assert len(call.args[0]) <= 4096, len(call.args[0])


@pytest.mark.asyncio
async def test_secret_still_masked_in_escaped_output():
    cache = _FakeCache(
        values={"keys.groq_api_key": "gsk_super_secret_1234"},
        admins={5885953495: "admin"},
        roles={"admin": {"permissions": {"wildcard": True}}},
    )
    hot.set_config_cache(cache)
    msg = _make_msg(5885953495, text="/debug_config keys.groq_api_key")
    await dc_mod.cmd_debug_config(msg)
    html = "\n".join(c.args[0] for c in msg.answer.call_args_list)
    assert "gsk_super_secret" not in html
    assert "last4: 1234" in html
