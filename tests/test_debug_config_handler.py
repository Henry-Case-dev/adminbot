"""Epic 85 (84.18.4/84.20, T-656/T-658) — тесты Telegram-команды /debug_config.

DoD п.17 84.18 + v2-формат 84.20.3: только wildcard-админ/DM; не-админ —
молчаливый отказ; секреты маскируются в выводе; формат `KEY = value`,
одна meta-строка, маркер `*` для недавно изменённого; резолв env-имени
(case-insensitive); неизвестный ключ → «не найден: X»; <pre>-чанки ≤4096
после html.escape; команда не в set_my_commands.
"""
import asyncio
import inspect
import types
from unittest.mock import AsyncMock

import pytest

from handlers import debug_config as dc_mod
from services import hot_config as hot
from services.debug_config import build_lines, resolve_param_key
from services.permissions import Permissions


class _FakeCache:
    def __init__(self, values=None, updated_at=None, admins=None, roles=None,
                 pg_available=True):
        self._settings = dict(values or {})
        self._settings_updated_at = dict(updated_at or {})
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


def _admin_cache(**overrides):
    values = {"limits.search_max_symbols": 8000,
              "keys.groq_api_key": "gsk_super_secret_1234",
              "prompts.factcheck_system_prompt": "<b>промпт</b>"}
    values.update(overrides.get("values", {}))
    return _FakeCache(
        values=values,
        updated_at=overrides.get("updated_at", {}),
        admins={5885953495: "admin"},
        roles={"admin": {"permissions": {"wildcard": True}}},
    )


@pytest.fixture(autouse=True)
def _cache():
    hot.set_config_cache(_admin_cache())
    yield
    hot.set_config_cache(None)


class TestResolver:
    def test_env_name_case_insensitive(self):
        spec = resolve_param_key("SEARCH_MAX_SYMBOLS")
        assert spec is not None
        assert spec.pg_key == "limits.search_max_symbols"
        spec = resolve_param_key("search_max_symbols")
        assert spec is not None

    def test_pg_key_direct(self):
        spec = resolve_param_key("limits.search_max_symbols")
        assert spec is not None
        assert spec.pg_key == "limits.search_max_symbols"

    def test_pg_only_content(self):
        spec = resolve_param_key("content.info_how_it_works")
        assert spec is not None
        assert spec.env_name is None

    def test_unknown_returns_none(self):
        assert resolve_param_key("НЕ_СУЩЕСТВУЕТ") is None
        assert resolve_param_key("") is None

    def test_display_name_env_style(self):
        assert resolve_param_key("LIMIT_SYMBOLS") is None  # не из каталога
        spec = resolve_param_key("LLM_BASE_URL")
        from services.debug_config import display_name
        assert display_name(spec) == "LLM_BASE_URL"


class TestV2Format:
    def test_build_lines_list_format(self):
        lines = build_lines(hot.get_config_cache())
        assert lines[0].startswith("meta: pid=")   # одна meta-строка
        assert "keys=" in lines[0]
        assert "generated_at=" in lines[0]
        # KEY = value построчно; env-стиль имена
        assert any(l == "SEARCH_MAX_SYMBOLS = 8000" for l in lines)
        assert any(l.startswith("GROQ_API_KEY = configured••••") for l in lines)
        # PG-only (prompts) — pg-ключ с пометкой [pg]
        assert any("prompts.factcheck_system_prompt [pg]" in l
                   for l in lines)

    def test_sorted_by_display_name(self):
        """Фикс 4: сортировка по display_name (env-имя), не по pg-ключу.
        EXA_API_KEY ('keys.exa_api_key') должен идти раньше SUMMARY_ENABLED."""
        lines = build_lines(hot.get_config_cache())
        names = [l.split(" = ", 1)[0].strip() for l in lines if " = " in l
                 and not l.startswith("* ")]
        # маркер-суффикс [pg]/[updated] не мешает: имена в естественном виде
        clean = [n.replace(" [pg]", "") for n in names]
        assert "EXA_API_KEY" in clean and "SUMMARY_ENABLED" in clean
        assert clean.index("EXA_API_KEY") < clean.index("SUMMARY_ENABLED")

    def test_marker_for_recently_changed(self):
        cache = _admin_cache(updated_at={
            "limits.search_max_symbols": "2026-08-30T01:00:00+00:00",
            "flags.summary_enabled": "2026-08-30T02:00:00+00:00"})
        hot.set_config_cache(cache)
        lines = build_lines(cache)
        marker_lines = [l for l in lines if l.startswith("* ")]
        assert len(marker_lines) == 1
        assert "SUMMARY_ENABLED" in marker_lines[0]
        assert "[updated 2026-08-30T02:00:00+00:00]" in marker_lines[0]
        # маркерная строка не продублирована в списке (точное совпадение)
        exact = "* SUMMARY_ENABLED = True " \
            "[updated 2026-08-30T02:00:00+00:00]"
        assert lines.count(exact) == 1

    def test_no_marker_when_no_updated_at(self):
        lines = build_lines(hot.get_config_cache())
        assert not any(l.startswith("* ") for l in lines)

    @pytest.mark.asyncio
    async def test_single_key_via_env_name(self):
        lines = build_lines(hot.get_config_cache(), key="limits.search_max_symbols")
        assert lines[0].startswith("meta: pid=")
        assert lines[1] == "SEARCH_MAX_SYMBOLS = 8000"

    def test_pg_only_rendered_with_mark(self):
        cache = _admin_cache(values={"content.info_how_it_works": {"a": 1}})
        hot.set_config_cache(cache)
        lines = build_lines(cache)
        pg_line = [l for l in lines if "INFO_HOW_IT_WORKS" not in l
                   and "CONTENT.INFO_HOW_IT_WORKS" not in l
                   and "content.info_how_it_works" in l]
        assert pg_line and "[pg]" in pg_line[0]

    def test_secret_masked_even_for_admin(self):
        lines = build_lines(hot.get_config_cache())
        joined = "\n".join(lines)
        assert "gsk_super_secret" not in joined
        assert "configured••••1234" in joined

    def test_secret_not_configured_formatted(self):
        """Фикс 2: секрет-dict с configured=False → 'not configured'."""
        from services.debug_config import _format_value_text
        assert _format_value_text({"configured": False, "last4": None},
                                  True) == "not configured"
        assert _format_value_text({"configured": True, "last4": "abcd"},
                                  True) == "configured••••abcd"


class TestHandlerV2:
    @pytest.mark.asyncio
    async def test_admin_dm_gets_compact_dump(self):
        msg = _make_msg(5885953495)
        await dc_mod.cmd_debug_config(msg)
        assert msg.delete.await_count == 1
        assert msg.answer.await_count >= 1
        html = "\n".join(c.args[0] for c in msg.answer.call_args_list)
        assert "<pre>" in html
        assert "meta: pid=" in html              # meta — часть вывода
        assert "SEARCH_MAX_SYMBOLS = 8000" in html
        assert "GROQ_API_KEY = configured••••" in html

    @pytest.mark.asyncio
    async def test_arg_env_name_resolves(self):
        msg = _make_msg(5885953495, text="/debug_config SEARCH_MAX_SYMBOLS")
        await dc_mod.cmd_debug_config(msg)
        html = msg.answer.call_args_list[0].args[0]
        assert "SEARCH_MAX_SYMBOLS = 8000" in html
        assert "source=memory-cache" not in html   # v2: без «воды»

    @pytest.mark.asyncio
    async def test_arg_lowercase_resolves(self):
        msg = _make_msg(5885953495, text="/debug_config search_max_symbols")
        await dc_mod.cmd_debug_config(msg)
        html = msg.answer.call_args_list[0].args[0]
        assert "SEARCH_MAX_SYMBOLS = 8000" in html

    @pytest.mark.asyncio
    async def test_unknown_key_not_found_message(self):
        msg = _make_msg(5885953495, text="/debug_config НЕ_СУЩЕСТВУЕТ")
        await dc_mod.cmd_debug_config(msg)
        html = "\n".join(c.args[0] for c in msg.answer.call_args_list)
        assert "не найден: НЕ_СУЩЕСТВУЕТ" in html
        assert "<pre>" not in html       # 404-текст без <pre> (84.20.3)

    @pytest.mark.asyncio
    async def test_secret_masked_in_escaped_output(self):
        msg = _make_msg(5885953495, text="/debug_config GROQ_API_KEY")
        await dc_mod.cmd_debug_config(msg)
        html = "\n".join(c.args[0] for c in msg.answer.call_args_list)
        assert "gsk_super_secret" not in html
        assert "configured••••1234" in html

    @pytest.mark.asyncio
    async def test_html_value_escaped(self):
        # prompts — PG-only: резолв по pg-ключу (env-имени у них нет)
        cache = _admin_cache(values={
            "prompts.factcheck_system_prompt": "<b>промпт</b>"})
        hot.set_config_cache(cache)
        msg = _make_msg(5885953495,
                        text="/debug_config prompts.factcheck_system_prompt")
        await dc_mod.cmd_debug_config(msg)
        html = "\n".join(c.args[0] for c in msg.answer.call_args_list)
        assert "<b>" not in html
        assert "&lt;b&gt;" in html

    @pytest.mark.asyncio
    async def test_long_dump_split_into_chunks(self):
        values = {f"limits.k{i}": i for i in range(400)}
        hot.set_config_cache(_admin_cache(values=values))
        msg = _make_msg(5885953495)
        await dc_mod.cmd_debug_config(msg)
        assert msg.answer.await_count > 1
        for call in msg.answer.call_args_list:
            assert len(call.args[0]) <= 4096

    @pytest.mark.asyncio
    async def test_non_admin_silent_rejection(self):
        msg = _make_msg(999999999)
        await dc_mod.cmd_debug_config(msg)
        assert msg.answer.await_count == 0
        assert msg.delete.await_count == 0


def test_command_not_in_menu():
    """D95: /debug_config скрыта — не в set_my_commands (services/bot_commands.py)."""
    import services.bot_commands as bc_mod
    src = open(bc_mod.__file__, encoding="utf-8").read()
    assert "debug_config" not in src


def test_router_filter_private_only():
    """Регистрация DM-only: хендлер объявлен с F.chat.type == 'private'."""
    src = inspect.getsource(dc_mod)
    assert 'F.chat.type == "private"' in src
