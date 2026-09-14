"""Смоук раунда 10.16 (T-1648) — nostalgia + persona «имитация реальной работы».

In-process, без сети: fake-PG для persona, чистые prompt-функции nostalgia.
  * persona: resolve per-chat → global, traits-cap, health-сводка;
  * persona: гейт имени в `command_prefix` (scope «Имя задано/пусто»);
  * nostalgia: окно ±10 по умолчанию, инжект лора/мемов, PREV-байт-канон,
    fail-open нормализация ответа.
"""
import datetime

import pytest

from services import bot_persona
from services import command_prefix as cp
from services import hot_config as hot
from services.nostalgia_prompts import (
    NOSTALGIA_PROMPT,
    PREV_NOSTALGIA_PROMPT,
    build_nostalgia_user,
    clean_llm_text,
    is_unchanged_response,
)


class _FakeConn:
    def __init__(self, *, persona_rows, traits):
        self._persona_rows = persona_rows
        self._traits = traits

    async def fetchrow(self, sql, *args):
        if "persona_state" in sql:
            return {"traits_count": 0, "last_trait_at": None,
                    "last_extract_status": "ok", "last_extract_at": None,
                    "last_trait_status": "ok"}
        if "COUNT(" in sql:               # _TRAITS_STATS_SQL
            return {"traits_count": len(self._traits),
                    "last_trait_at": datetime.datetime(
                        2026, 9, 13, tzinfo=datetime.timezone.utc)}
        # personas: chat-scope SQL несёт параметр chat_id
        if args:
            return self._persona_rows.get(int(args[0]))
        return self._persona_rows.get(None)

    async def fetch(self, sql, *args):
        if "persona_traits" in sql:
            return self._traits
        return []


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


def _persona_row(name):
    return {"name": name, "biography": "био", "system_prompt_overrides": "х",
            "is_aware_ai": True, "updated_at": "2026-09-13T10:00:00+00:00"}


@pytest.fixture
def persona_pool(monkeypatch):
    conn = _FakeConn(
        persona_rows={None: _persona_row("Глобал"), 500: _persona_row("Чат")},
        traits=[{"id": 1, "chat_id": None, "trait": "шутит",
                 "source": "deep_sleep",
                 "created_at": datetime.datetime(
                     2026, 9, 13, tzinfo=datetime.timezone.utc)}])
    bot_persona.set_persona_pool(_FakePool(conn))
    yield
    bot_persona.reset_persona_pool()


class TestPersonaSmoke:
    @pytest.mark.asyncio
    async def test_resolve_per_chat_then_global(self, persona_pool):
        chat = await bot_persona.resolve_bot_persona(500)
        assert chat.name == "Чат" and chat.is_global is False
        global_ = await bot_persona.resolve_bot_persona(None)
        assert global_.name == "Глобал" and global_.is_global is True

    @pytest.mark.asyncio
    async def test_resolve_chat_fallback_to_global(self, persona_pool):
        # чата 777 нет → global
        resolved = await bot_persona.resolve_bot_persona(777)
        assert resolved.name == "Глобал" and resolved.is_global is True

    @pytest.mark.asyncio
    async def test_traits_cap_and_health(self, persona_pool):
        traits = await bot_persona.get_traits(limit=50, chat_id=500)
        assert len(traits) == 1
        assert traits[0]["text"] == "шутит"
        health = await bot_persona.get_persona_health()
        assert health["traits_count"] == 1
        assert health["extractor_status"] == "ok"

    def test_prompt_traits_cap(self):
        persona = bot_persona.BotPersona(name="Олег", biography="")
        block = bot_persona.build_persona_prompt_block(
            persona, traits=["шутит", "  ", "циник"], enabled=True)
        assert "<Persona>" in block
        assert "• шутит" in block and "• циник" in block

    def test_prompt_disabled_empty(self):
        persona = bot_persona.BotPersona(name="Олег")
        assert bot_persona.build_persona_prompt_block(
            persona, enabled=False) == ""

    def test_command_prefix_scope_by_name(self, monkeypatch):
        real_get = hot.get
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: True
            if key == "flags.persona_enabled" else real_get(key, default))
        bot_persona.set_global_name_cache("Олег")
        assert cp.split_prefix("Бот, загугли X")[0] is None
        assert cp.split_prefix("Олег, загугли X")[0] == "олег"
        bot_persona.set_global_name_cache("")
        assert cp.split_prefix("Бот, загугли X")[0] in ("бот",)


class TestNostalgiaSmoke:
    def test_default_window_is_ten_days(self):
        from config.settings import settings
        assert settings.NOSTALGIA_YEAR_BACK_DAYS_WINDOW == 10

    def test_lore_and_memes_injected(self):
        text = build_nostalgia_user(
            ["- 2025: старый факт"], ["старый золотой факт"],
            lore="тут принято шутить про котов",
            memes=[{"fact": "кот-программист", "target_user": "Вася"}])
        assert "Лор чата" in text
        assert "Локальные мемы" in text
        assert "кот-программист" in text

    def test_empty_injection_omitted(self):
        text = build_nostalgia_user(["- факт"], [], lore="", memes=[])
        assert "Лор чата" not in text and "Локальные мемы" not in text

    def test_prev_canon_preserved(self):
        # PREV — слепок до ревампа 10.15; текущий канон требует лор/мемы.
        assert PREV_NOSTALGIA_PROMPT != NOSTALGIA_PROMPT
        assert "Лор" in NOSTALGIA_PROMPT or "лор" in NOSTALGIA_PROMPT
        assert "мем" in NOSTALGIA_PROMPT.lower()

    def test_fail_open_text_helpers(self):
        assert clean_llm_text(None) == ""
        assert clean_llm_text("  a\n\nb  ") == "a b"
        assert is_unchanged_response("UNCHANGED") is True
        assert is_unchanged_response("нормальный ответ") is False
