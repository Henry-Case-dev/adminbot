"""Раунд 5 (T-733/T-734, spec 5.2.4, FR-C3/FR-C4) — тесты ensure_chat_lore.

Покрытие: константа лора (непустая, ключевые слова из spec Приложения A);
первый вызов ensure — inserted=2 (protected_facts chat-level + graph_facts
origin='user_memory' + FTS-строка по rowid); повторный — inserted=0/skipped=2
(тот же dict-контракт); get_protected_facts(-1002661910336, <любой>) возвращает
лор; persona-карточка включает чат-лор первой строкой (дельта 4.6.2);
fail-open при ошибке БД.
"""
import asyncio
import logging
import time

import pytest

from services.chat_lore import (
    CHAT_LORE_2661910336,
    CHAT_LORE_TARGET_CHAT_ID,
    ensure_chat_lore,
)
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.summary_aliases import AliasResolver


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _service(db) -> DirectChatService:
    return DirectChatService(
        memory=object(), db=db, llm=object(), aliases=AliasResolver("{}"))


class TestChatLoreConstant:
    def test_lore_not_empty(self):
        assert isinstance(CHAT_LORE_2661910336, str)
        assert len(CHAT_LORE_2661910336) > 200

    def test_lore_keywords_from_appendix_a(self):
        for word in ("Пермск", "джаббер", "ВК", "телеграм", "с нулевых"):
            assert word in CHAT_LORE_2661910336

    def test_no_surrounding_newlines(self):
        assert not CHAT_LORE_2661910336.endswith("\n")
        assert not CHAT_LORE_2661910336.startswith("\n")

    def test_target_chat_id_is_runtime_supergroup(self):
        """Hotfix 05.09.2026: runtime-чат приватной супергруппы в БД =
        -100 + id экспорта (aiogram private_supergroup). Под +2661910336
        контексты чата (message.chat.id = -1002661910336) лор НЕ читают."""
        assert CHAT_LORE_TARGET_CHAT_ID == -1002661910336
        assert CHAT_LORE_TARGET_CHAT_ID < 0


class TestEnsureChatLore:
    async def _counts(self, db):
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM protected_facts WHERE chat_id = ? "
            "AND user_name IS NULL AND fact = ?",
            (CHAT_LORE_TARGET_CHAT_ID, CHAT_LORE_2661910336))
        protected = (await cursor.fetchone())["c"]
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE chat_id = ? "
            "AND fact = ? AND origin = 'user_memory'",
            (CHAT_LORE_TARGET_CHAT_ID, CHAT_LORE_2661910336))
        graph = (await cursor.fetchone())["c"]
        return protected, graph

    @pytest.mark.asyncio
    async def test_first_call_inserts_protected_and_graph(self, db):
        result = await ensure_chat_lore(db)
        assert result == {"inserted": 2, "skipped": 0}
        protected, graph = await self._counts(db)
        assert protected == 1
        assert graph == 1
        # graph_facts-строка: origin/expires_at/weight/target_user/status
        cursor = await db.db.execute(
            "SELECT origin, expires_at, weight, target_user, status "
            "FROM graph_facts WHERE chat_id = ? AND fact = ?",
            (CHAT_LORE_TARGET_CHAT_ID, CHAT_LORE_2661910336))
        row = await cursor.fetchone()
        assert row["origin"] == "user_memory"
        assert row["expires_at"] is None          # вечно
        assert row["weight"] == 1.0
        assert row["target_user"] is None         # чат-уровневый
        assert row["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_second_call_is_idempotent(self, db):
        assert await ensure_chat_lore(db) == {"inserted": 2, "skipped": 0}
        assert await ensure_chat_lore(db) == {"inserted": 0, "skipped": 2}
        protected, graph = await self._counts(db)
        assert (protected, graph) == (1, 1)       # дублей нет

    @pytest.mark.asyncio
    async def test_fts_row_present_for_graph_fact(self, db):
        await ensure_chat_lore(db)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts_fts f "
            "JOIN graph_facts g ON g.id = f.rowid "
            "WHERE g.chat_id = ? AND g.origin = 'user_memory'",
            (CHAT_LORE_TARGET_CHAT_ID,))
        assert (await cursor.fetchone())["c"] == 1
        # FTS-поиск по ключевому слову лора находит факт
        rows = await db.search_graph_facts_fts(
            CHAT_LORE_TARGET_CHAT_ID, '"джаббер"*', 5, int(time.time()))
        assert any("джаббер конфы" in r["fact"] for r in rows)

    @pytest.mark.asyncio
    async def test_get_protected_facts_returns_lore_for_any_user(self, db):
        await ensure_chat_lore(db)
        for user in ("ЛюбойЮзер", "вася", "", "2661910336"):
            facts = await db.get_protected_facts(CHAT_LORE_TARGET_CHAT_ID, user)
            assert CHAT_LORE_2661910336 in facts
            # чат-лор — ПЕРВЫМ в списке (ORDER BY (user_name IS NULL) DESC)
            assert facts[0] == CHAT_LORE_2661910336

    @pytest.mark.asyncio
    async def test_include_chat_level_false_excludes_lore(self, db):
        await ensure_chat_lore(db)
        facts = await db.get_protected_facts(
            CHAT_LORE_TARGET_CHAT_ID, "вася", include_chat_level=False)
        assert CHAT_LORE_2661910336 not in facts

    @pytest.mark.asyncio
    async def test_persona_card_contains_lore_first_line(self, db):
        """Дельта 4.6.2: persona-карточка включает чат-лор первой строкой
        (шапка/счётчик N — формат 66.9 VERBATIM)."""
        await ensure_chat_lore(db)
        await db.insert_graph_fact(
            CHAT_LORE_TARGET_CHAT_ID, "вася любит дроны", "bot_direct_reply",
            None, target_user="вася")
        service = _service(db)
        card = await service.build_persona_card(CHAT_LORE_TARGET_CHAT_ID, "вася")
        assert card is not None
        assert card.startswith("карточка: вася")
        assert "знаю о тебе: 2 фактов, 0 связей" in card   # лор + факт юзера
        assert card.index("1. " + CHAT_LORE_2661910336) < \
            card.index("2. вася любит дроны")

    @pytest.mark.asyncio
    async def test_persona_card_without_lore_old_behavior(self, db):
        """Без чат-лора (другой чат) — старое поведение/формат."""
        chat_id = -100500
        await db.insert_graph_fact(
            chat_id, "вася любит дроны", "bot_direct_reply",
            None, target_user="вася")
        service = _service(db)
        card = await service.build_persona_card(chat_id, "вася")
        assert card is not None
        assert "знаю о тебе: 1 фактов, 0 связей" in card
        assert await service.build_persona_card(chat_id, "петя") is None

    @pytest.mark.asyncio
    async def test_fail_open_on_db_error(self, db, monkeypatch, caplog):
        async def broken(*a, **kw):
            raise RuntimeError("бд упала")

        monkeypatch.setattr(db.db, "execute", broken)
        with caplog.at_level(logging.WARNING, logger="services.chat_lore"):
            result = await ensure_chat_lore(db)
        assert result == {"inserted": 0, "skipped": 0}
        assert any("ensure failed — fail-open" in r.message
                   for r in caplog.records)
