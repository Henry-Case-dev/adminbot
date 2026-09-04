"""Раунд 4 (T-717, AC-D1…D6, spec 3.4/Раздел 6) — Часть D: память-команды.

Слои:
  * распознавание `_parse_memory_command` (reply/mention/«бот», слово vs
    фраза, не-триггеры → обычный direct_chat);
  * маршрут direct_chat_handler: команда consumed (LLM НЕ вызван — handle
    не зовётся), фразы-подтверждения из пулов CHAT_MEMORY_*;
  * хранилище «запомни» (origin='user_memory', weight=1.0, TTL, target_user,
    дедуп, видимость в FTS/RAG) + миграция v5 (origin в CHECK);
  * «забудь» — AND-слова, scope админ/чат vs юзер/свои, журнал
    graph_fact_compressions (reason='user_forget'), protected/bot_direct_reply
    не тронуты, 0-найдено;
  * RBAC×тумблер (админ/модер/юзер, флаг on/off → denied).
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from handlers import direct_chat as dc_mod
from services import hot_config as hot
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.summary_aliases import AliasResolver
from services.summary_memory import MemoryManager
from services.smartmodule_phrases import (
    CHAT_MEMORY_ALREADY_KNOWN_PHRASES,
    CHAT_MEMORY_CMD_DENIED_PHRASES,
    CHAT_MEMORY_FORGET_NOARG_PHRASES,
    CHAT_MEMORY_FORGOT_DONE_PHRASE,
    CHAT_MEMORY_FORGOT_NONE_PHRASES,
    CHAT_MEMORY_REMEMBERED_PHRASE,
    CHAT_MEMORY_TOO_SHORT_PHRASES,
)

CHAT_ID = -1001234567890
ADMIN_ID = settings.ADMIN_USER_ID


@pytest.fixture
def db():
    """In-memory DatabaseService (миграции до v5 применены)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _user(user_id=10, first_name="Вася", last_name="Пупкин", username="vasya"):
    u = MagicMock()
    u.id = user_id
    u.first_name = first_name
    u.last_name = last_name
    u.username = username
    return u


# ── Распознавание (AC-D1) ────────────────────────────────────────


class TestParseMemoryCommand:
    @pytest.mark.parametrize("text,expected", [
        ("бот, запомни: у нас бензин только на лукойле",
         ("remember", "у нас бензин только на лукойле")),
        ("Бот, запомни у нас бензин только на лукойле",
         ("remember", "у нас бензин только на лукойле")),
        ("бот запомни: у нас бензин только на лукойле",
         ("remember", "у нас бензин только на лукойле")),
        ("бот, запиши что я должен алексею",
         ("remember", "что я должен алексею")),
        ("@test_bot запомни: вася не пьёт",
         ("remember", "вася не пьёт")),
        ("ботина, запомни: кота зовут сеня",
         ("remember", "кота зовут сеня")),
    ])
    def test_remember_variants(self, text, expected):
        assert dc_mod._parse_memory_command(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("бот, забудь бензин", ("forget", "бензин")),
        ("бот забудь: заправку на углу",
         ("forget", "заправку на углу")),
        ("забудь про дроны", ("forget", "про дроны")),
        ("@test_bot забудь лукойл", ("forget", "лукойл")),
    ])
    def test_forget_variants(self, text, expected):
        """Fix-раунд 4 (M-1): forget-норма — ТОЛЬКО «забудь» (spec 3.4.2);
        синонимы «забыть/удали из памяти/выкинь из памяти» ушли в
        test_not_a_command (обычный LLM-диалог)."""
        assert dc_mod._parse_memory_command(text) == expected

    @pytest.mark.parametrize("text", [
        "бот, забудь",
        "Бот, забудь",
    ])
    def test_forget_noarg(self, text):
        assert dc_mod._parse_memory_command(text) == ("forget_noarg", "")

    @pytest.mark.parametrize("text", [
        "бот, забудь а",
        "бот, забудь ах",
        "бот, запомни ах",
    ])
    def test_too_short(self, text):
        assert dc_mod._parse_memory_command(text)[0] == "too_short"

    @pytest.mark.parametrize("text", [
        "бот, что думаешь про бензин",
        "бот, а забудь свои обиды, лучше расскажи",
        "бот, а запомни меня в друзья",           # не в начале после «бот»
        "бот, запомни",                           # remember без аргумента — не-команда
        "Бот, забыть бензин",                     # «забыть» — НЕ синоним «забудь»
        "бот, забыть",                            #   (fix-раунд 4, M-1)
        "бот, удали из памяти бензин",
        "бот, выкинь из памяти азс лукойл",
        "бот, запомни:бензин",                    # без пробела после «:» (M-4)
        "привет, как дела",
        "",
    ])
    def test_not_a_command(self, text):
        assert dc_mod._parse_memory_command(text) is None

    def test_forget_vse_noop_help(self):
        """«забудь всё» (fix-раунд 4, M-2): forget-аргумент, casefold-ровно
        «всё», — НЕ удаление: help-фраза (forget_noarg), consumed, сервис
        удаления не зовётся (spec 3.4.8: «забудь всё» намеренно НЕ
        реализуем)."""
        assert dc_mod._parse_memory_command("бот, забудь всё") == (
            "forget_noarg", "")
        assert dc_mod._parse_memory_command("Бот, забудь ВСЁ") == (
            "forget_noarg", "")

    def test_double_peer_prefix(self):
        """Цикл срезает несколько обращений подряд."""
        assert dc_mod._parse_memory_command(
            "бот, бот, запомни: два слова") == ("remember", "два слова")

    def test_whitespace_collapse(self):
        kind, arg = dc_mod._parse_memory_command("бот, запомни:   много   пробелов")
        assert kind == "remember"
        assert arg == "много   пробелов"    # срезаны только края (service схлопнет)


# ── Маршрут direct_chat_handler: consumed, LLM не вызван ─────────


class TestMemoryCommandHandlerFlow:
    @pytest.fixture
    def wire(self):
        service = MagicMock()
        service.handle = AsyncMock()
        service.remember_user_fact = AsyncMock(return_value="saved")
        service.forget_user_facts = AsyncMock(return_value=("ok", 2, "бензин"))
        dc_mod.setup_direct_chat(service, 12345, "test_bot")
        yield service
        dc_mod.setup_direct_chat(None, None, None)

    def _msg(self, text, user_id=10):
        msg = MagicMock()
        msg.text = text
        msg.message_id = 1
        msg.chat = MagicMock()
        msg.chat.id = CHAT_ID
        msg.from_user = MagicMock()
        msg.from_user.id = user_id
        msg.entities = None
        msg.reply_to_message = None
        return msg

    @pytest.mark.asyncio
    async def test_remember_consumed_llm_not_called(self, wire):
        """AC-D5: команда consumed — handle (LLM-путь) НЕ вызывается."""
        bot = AsyncMock()
        result = await dc_mod.direct_chat_handler(
            self._msg("бот, запомни: кота зовут сеня"), bot=bot)
        assert result is not UNHANDLED
        wire.handle.assert_not_called()
        wire.remember_user_fact.assert_awaited_once()
        text = bot.send_message.await_args.args[1]
        assert text == CHAT_MEMORY_REMEMBERED_PHRASE.replace(
            "{факт}", "кота зовут сеня")

    @pytest.mark.asyncio
    async def test_remember_duplicate_phrase(self, wire):
        wire.remember_user_fact = AsyncMock(return_value="duplicate")
        bot = AsyncMock()
        await dc_mod.direct_chat_handler(
            self._msg("бот, запомни: кота зовут сеня"), bot=bot)
        assert bot.send_message.await_args.args[1] in CHAT_MEMORY_ALREADY_KNOWN_PHRASES
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_forget_done_phrase_with_count(self, wire):
        bot = AsyncMock()
        await dc_mod.direct_chat_handler(
            self._msg("бот, забудь бензин"), bot=bot)
        assert bot.send_message.await_args.args[1] == (
            CHAT_MEMORY_FORGOT_DONE_PHRASE.replace("{n}", "2").replace(
                "{запрос}", "бензин"))
        wire.handle.assert_not_called()
        wire.forget_user_facts.assert_awaited_once_with(CHAT_ID, wire.forget_user_facts.await_args.args[1], "бензин")

    @pytest.mark.asyncio
    async def test_forget_zero_found_phrase(self, wire):
        wire.forget_user_facts = AsyncMock(return_value=("ok", 0, "дроны"))
        bot = AsyncMock()
        await dc_mod.direct_chat_handler(
            self._msg("бот, забудь дроны"), bot=bot)
        sent = bot.send_message.await_args.args[1]
        assert sent in [p.replace("{запрос}", "дроны")
                        for p in CHAT_MEMORY_FORGOT_NONE_PHRASES]

    @pytest.mark.asyncio
    async def test_denied_phrase_consumed(self, wire):
        """Тумблер off + юзер → дени-фраза, LLM НЕ вызван (на уровне
        сервиса; здесь — маппинг результата)."""
        wire.remember_user_fact = AsyncMock(return_value="denied")
        bot = AsyncMock()
        await dc_mod.direct_chat_handler(
            self._msg("бот, запомни: кота зовут сеня"), bot=bot)
        assert bot.send_message.await_args.args[1] in CHAT_MEMORY_CMD_DENIED_PHRASES
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_forget_noarg_help_consumed(self, wire):
        """«бот, забудь» без аргумента → help-фраза, сервис не зовётся."""
        bot = AsyncMock()
        await dc_mod.direct_chat_handler(self._msg("бот, забудь"), bot=bot)
        assert bot.send_message.await_args.args[1] in CHAT_MEMORY_FORGET_NOARG_PHRASES
        wire.handle.assert_not_called()
        wire.forget_user_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_too_short_phrase(self, wire):
        bot = AsyncMock()
        await dc_mod.direct_chat_handler(self._msg("бот, забудь ах"), bot=bot)
        assert bot.send_message.await_args.args[1] in CHAT_MEMORY_TOO_SHORT_PHRASES
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_a_command_goes_to_llm(self, wire):
        """Не-команда (даже с «бот, запомни»-оборотом без аргумента) →
        обычный direct_chat (handle)."""
        bot = AsyncMock()
        result = await dc_mod.direct_chat_handler(
            self._msg("бот, что думаешь про бензин"), bot=bot)
        assert result is not UNHANDLED
        wire.handle.assert_awaited_once()
        wire.remember_user_fact.assert_not_called()

    @pytest.mark.asyncio
    async def test_forget_synonyms_go_to_llm(self, wire):
        """Fix-раунд 4 (M-1): «Бот, забыть …» / «удали из памяти …» — обычный
        LLM-диалог (handle), НЕ consumed — ответ модели не теряется."""
        bot = AsyncMock()
        for text in ("Бот, забыть про сегодняшний разговор",
                     "бот, удали из памяти бензин"):
            wire.handle.reset_mock()
            result = await dc_mod.direct_chat_handler(self._msg(text), bot=bot)
            assert result is not UNHANDLED
            wire.handle.assert_awaited_once()
            wire.forget_user_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_forget_vse_help_consumed_no_deletion(self, wire):
        """Fix-раунд 4 (M-2): «бот, забудь всё» → help-фраза, consumed:
        удаление (forget_user_facts) НЕ вызывается, LLM-путь (handle) тоже."""
        bot = AsyncMock()
        await dc_mod.direct_chat_handler(self._msg("бот, забудь всё"), bot=bot)
        assert bot.send_message.await_args.args[1] in CHAT_MEMORY_FORGET_NOARG_PHRASES
        wire.handle.assert_not_called()
        wire.forget_user_facts.assert_not_called()

    @pytest.mark.asyncio
    async def test_remember_without_trigger_unhandled(self, wire):
        """«забудь бензин» БЕЗ reply/mention/«бот» → UNHANDLED (пропагация)."""
        bot = AsyncMock()
        result = await dc_mod.direct_chat_handler(
            self._msg("забудь бензин"), bot=bot)
        assert result is UNHANDLED
        wire.handle.assert_not_called()

    @pytest.mark.asyncio
    async def test_reply_command_consumed(self, wire):
        """Reply на бота разрешает команду и без «бот»."""
        bot = AsyncMock()
        reply_to = MagicMock()
        reply_to.from_user = MagicMock()
        reply_to.from_user.id = 12345            # бот
        msg = self._msg("забудь бензин")
        msg.reply_to_message = reply_to
        result = await dc_mod.direct_chat_handler(msg, bot=bot)
        assert result is not UNHANDLED
        wire.handle.assert_not_called()
        wire.forget_user_facts.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remember_arg_capped_at_500(self, wire):
        """spec 3.4.2: remember-аргумент длиннее 500 — усечение; фраза и
        сервис получают ровно сохранённый текст."""
        long_fact = "слово " * 200                     # 1000 символов
        bot = AsyncMock()
        await dc_mod.direct_chat_handler(
            self._msg("бот, запомни: " + long_fact), bot=bot)
        stored = wire.remember_user_fact.await_args.args[2]
        assert len(stored) == 500
        sent = bot.send_message.await_args.args[1]
        assert sent == CHAT_MEMORY_REMEMBERED_PHRASE.replace("{факт}", stored)

    @pytest.mark.asyncio
    async def test_remember_arg_whitespace_collapsed(self, wire):
        bot = AsyncMock()
        await dc_mod.direct_chat_handler(
            self._msg("бот, запомни:   много   пробелов  "), bot=bot)
        stored = wire.remember_user_fact.await_args.args[2]
        assert stored == "много пробелов"


# ── Хранилище «запомни» (AC-D2) + миграция v5 (AC-D3) ────────────


class TestRememberStore:
    @pytest.fixture
    def mm(self, db):
        m = MemoryManager(db, llm=None)
        m._vec_available = False                  # FTS-режим (без sqlite-vec)
        return m

    async def _row(self, db, fact):
        cursor = await db.db.execute(
            "SELECT chat_id, fact, origin, expires_at, created_at, "
            "target_user, weight, status FROM graph_facts "
            "WHERE origin='user_memory' AND fact = ?", (fact,))
        return await cursor.fetchone()

    @pytest.mark.asyncio
    async def test_admin_fact_chat_wide_target_null(self, db, mm):
        now = int(time.time())
        result = await mm.remember_user_fact(
            CHAT_ID, "у нас бензин только на лукойле", target_user=None,
            ttl_days=365)
        assert result == "saved"
        row = await self._row(db, "у нас бензин только на лукойле")
        assert row is not None
        assert row["target_user"] is None          # админ → факт чата
        assert row["weight"] == 1.0                # FR-D2: вес 1.0
        assert row["status"] == "confirmed"
        assert row["origin"] == "user_memory"
        assert row["expires_at"] == now + 365 * 86400   # TTL прямо, без (0.5+w)

    @pytest.mark.asyncio
    async def test_user_fact_target_user_is_canon(self, db, mm):
        result = await mm.remember_user_fact(
            CHAT_ID, "мой любимый цвет синий", target_user="вася",
            ttl_days=365)
        assert result == "saved"
        row = await self._row(db, "мой любимый цвет синий")
        assert row["target_user"] == "вася"

    @pytest.mark.asyncio
    async def test_ttl_zero_means_forever(self, db, mm):
        await mm.remember_user_fact(CHAT_ID, "факт навсегда",
                                    target_user=None, ttl_days=0)
        row = await self._row(db, "факт навсегда")
        assert row["expires_at"] is None           # 0 = вечно (как direct-reply)

    @pytest.mark.asyncio
    async def test_exact_duplicate_case_insensitive(self, db, mm):
        await mm.remember_user_fact(CHAT_ID, "Кот зовётся Сеня",
                                    target_user=None, ttl_days=365)
        result = await mm.remember_user_fact(
            CHAT_ID, "кот зовётся сеня", target_user=None, ttl_days=365)
        assert result == "duplicate"               # exact-дуп по casefold
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE origin='user_memory'")
        assert (await cursor.fetchone())["c"] == 1

    @pytest.mark.asyncio
    async def test_duplicate_chat_wide_fact_is_shared(self, db, mm):
        """NULL-факт чата — общий: повтор юзера с тем же текстом → дубль
        (3.4.3: target_user IS ? OR IS NULL — exact-дедуп чат-уровня)."""
        await mm.remember_user_fact(CHAT_ID, "общий факт", target_user=None,
                                    ttl_days=365)
        result = await mm.remember_user_fact(CHAT_ID, "общий факт",
                                             target_user="вася", ttl_days=365)
        assert result == "duplicate"

    @pytest.mark.asyncio
    async def test_personal_fact_not_dup_of_other_person(self, db, mm):
        """Личные факты разных людей — не дубли (scope по target_user)."""
        await mm.remember_user_fact(CHAT_ID, "личное васи", target_user="вася",
                                    ttl_days=365)
        result = await mm.remember_user_fact(CHAT_ID, "личное васи",
                                             target_user="петя", ttl_days=365)
        assert result == "saved"

    @pytest.mark.asyncio
    async def test_remember_is_fts_searchable_and_in_rag(self, db, mm):
        await mm.remember_user_fact(
            CHAT_ID, "на какой заправке заправляемся — только лукойл",
            target_user=None, ttl_days=365)
        now = int(time.time())
        rows = await db.search_graph_facts_fts(CHAT_ID, '"лукойл"*', 5, now)
        assert rows and rows[0]["origin"] == "user_memory"
        context = await mm.get_rag_context(CHAT_ID, "на какой заправке бензин?")
        assert "лукойл" in context                # виден RAG (не bot_direct_reply-фильтр)

    @pytest.mark.asyncio
    async def test_remember_whitespace_collapsed(self, db, mm):
        """Схлопывание пробелов (spec 3.4.2) — в БД один пробел."""
        await mm.remember_user_fact(CHAT_ID, "   много   пробелов   ",
                                    target_user=None, ttl_days=365)
        assert await self._row(db, "много пробелов") is not None
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts "
            "WHERE origin='user_memory' AND fact = 'много пробелов'")
        assert (await cursor.fetchone())["c"] == 1

    @pytest.mark.asyncio
    async def test_migration_v5_origin_allowed_and_schema_has_user_memory(self, db):
        """AC-D3: свежая БД — CHECK включает user_memory; INSERT успешен."""
        cursor = await db.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'")
        sql = (await cursor.fetchone())["sql"]
        assert "user_memory" in sql
        fid = await db.insert_graph_fact(CHAT_ID, "факт из «запомни»",
                                         "user_memory", None)
        cursor = await db.db.execute(
            "SELECT origin FROM graph_facts WHERE id = ?", (fid,))
        assert (await cursor.fetchone())["origin"] == "user_memory"

    @pytest.mark.asyncio
    async def test_migration_v5_from_v4_preserves_rows(self, tmp_path):
        """AC-D3: v4-БД → v5: данные/id сохранены, user_version=5, no-op."""
        import sqlite3

        path = tmp_path / "v4.db"
        conn = sqlite3.connect(str(path))
        conn.executescript("""
            CREATE TABLE graph_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                fact TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN
                ('chat_history', 'search_fact', 'youtube_content', 'web_content',
                 'bot_direct_reply', 'voice_transcript', 'video_transcript')),
                expires_at INTEGER, created_at INTEGER NOT NULL,
                target_user TEXT, weight REAL NOT NULL DEFAULT 0.5,
                status TEXT NOT NULL DEFAULT 'confirmed',
                last_confirmed_at INTEGER, supersedes INTEGER);
            """)
        conn.execute(
            "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
            "created_at, target_user, weight, status) VALUES "
            "(42, -100, 'факт до v5', 'voice_transcript', NULL, 1700000000, "
            "'вася', 0.7, 'confirmed')")
        conn.execute("PRAGMA user_version = 4")
        conn.commit()
        conn.close()

        d = DatabaseService(str(path))
        await d.initialize()
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 5
        cursor = await d.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'")
        assert "user_memory" in (await cursor.fetchone())["sql"]
        cursor = await d.db.execute(
            "SELECT id, fact, origin, weight FROM graph_facts")
        row = await cursor.fetchone()
        assert (row["id"], row["fact"], row["weight"]) == (42, "факт до v5", 0.7)
        await d.close()
        # повторный запуск — no-op
        await d.initialize()
        cursor = await d.db.execute("PRAGMA user_version")
        assert (await cursor.fetchone())[0] == 5
        cursor = await d.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1
        await d.close()


# ── «забудь» (AC-D4) ─────────────────────────────────────────────


async def _seed_forget(db):
    """user_memory: чат-факт(ы) + васин + петины; прочие origin — с теми же
    словами (НЕ должны удаляться)."""
    now = int(time.time())
    await db.insert_graph_fact(CHAT_ID, "бензин только на азс лукойл",
                               "user_memory", None, target_user=None, weight=1.0)
    await db.insert_graph_fact(CHAT_ID, "лукойл ближе всех",
                               "user_memory", None, target_user="вася", weight=1.0)
    await db.insert_graph_fact(CHAT_ID, "бензин дешёвый на лукойле",
                               "user_memory", None, target_user="петя", weight=1.0)
    await db.insert_graph_fact(CHAT_ID, "про бензин и дроны",
                               "chat_history", None)
    await db.insert_graph_fact(CHAT_ID, "напомни про бензин",
                               "bot_direct_reply", None, target_user="вася")
    await db.insert_graph_fact(CHAT_ID, "протухший бензин-факт",
                               "user_memory", now - 10, target_user=None, weight=1.0)
    return now


class TestForgetStore:
    def test_words_extraction(self):
        assert DatabaseService._memory_forget_words(
            "Бензин и Лукойл!!") == ["бензин", "лукойл"]
        assert DatabaseService._memory_forget_words("аа") == []   # < 3 симв
        words = DatabaseService._memory_forget_words(
            "ааа бббб вввв гггг дддд ееее жжжж")
        assert len(words) == 5                      # срез до 5

    @pytest.mark.asyncio
    async def test_admin_chat_wide_and_words_and(self, db):
        """Админ (target_user=None) — весь чат; AND-слова."""
        await _seed_forget(db)
        removed = await db.forget_memory_facts(
            CHAT_ID, ["бензин", "лукойл"])
        assert removed == 2          # чат-факт + петин («бензин…лукойл»); лукойл-васин без «бензин» не удалён

    @pytest.mark.asyncio
    async def test_user_scope_own_facts_only(self, db):
        await _seed_forget(db)
        removed = await db.forget_memory_facts(
            CHAT_ID, ["лукойл"], target_user="вася")
        assert removed == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts "
            "WHERE origin='user_memory' AND target_user='петя'")
        assert (await cursor.fetchone())["c"] == 1  # чужой не тронут

    @pytest.mark.asyncio
    async def test_zero_found(self, db):
        removed = await db.forget_memory_facts(CHAT_ID, ["бензин"])
        assert removed == 0

    @pytest.mark.asyncio
    async def test_expired_facts_not_deleted(self, db):
        removed = await db.forget_memory_facts(CHAT_ID, ["протухший"])
        assert removed == 0                          # expires_at в прошлом

    @pytest.mark.asyncio
    async def test_other_origins_and_protected_not_touched(self, db):
        await _seed_forget(db)
        # protected_facts — отдельная таблица
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (?, 'вася', 'про бензин и дроны', ?)",
            (CHAT_ID, time.time()))
        await db.db.commit()
        removed = await db.forget_memory_facts(CHAT_ID, ["бензин"])
        assert removed == 2                          # чат + петя
        for origin in ("chat_history", "bot_direct_reply"):
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM graph_facts "
                "WHERE origin = ? AND chat_id = ?", (origin, CHAT_ID))
            assert (await cursor.fetchone())["c"] == 1
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM protected_facts")
        assert (await cursor.fetchone())["c"] == 1

    @pytest.mark.asyncio
    async def test_journal_user_forget_and_fts_cleaned(self, db):
        await _seed_forget(db)
        removed = await db.forget_memory_facts(
            CHAT_ID, ["бензин", "лукойл"])
        assert removed == 2
        cursor = await db.db.execute(
            "SELECT chat_id, fact_id, fact_before, reason FROM "
            "graph_fact_compressions WHERE reason = 'user_forget'")
        rows = await cursor.fetchall()
        assert len(rows) == 2
        assert all(r["chat_id"] == CHAT_ID for r in rows)
        assert all(r["reason"] == "user_forget" for r in rows)
        # FTS-строки удалены (факты не находятся поиском)
        now = int(time.time())
        rows = await db.search_graph_facts_fts(CHAT_ID, '"лукойл"*', 10, now)
        assert all(r["origin"] != "user_memory" or "бензин" not in r["fact"]
                   for r in rows)

    @pytest.mark.asyncio
    async def test_empty_words_noop(self, db):
        assert await db.forget_memory_facts(CHAT_ID, []) == 0
        assert await db.forget_memory_facts(CHAT_ID, ["аа"]) == 0  # < 3 симв

    @pytest.mark.asyncio
    async def test_forget_missing_vec_table_best_effort(self, db):
        """vec-таблицы нет (FTS-режим) — удаление не падает."""
        await db.insert_graph_fact(CHAT_ID, "бензин где-то тут",
                                   "user_memory", None, target_user=None,
                                   weight=1.0)
        removed = await db.forget_memory_facts(CHAT_ID, ["бензин"])
        assert removed == 1


# ── RBAC×тумблер (AC-D5) на DirectChatService ────────────────────


class FakeMem:
    """Память-заглушка: фиксирует вызовы remember_user_fact."""

    def __init__(self, result="saved"):
        self.result = result
        self.calls = []

    async def remember_user_fact(self, chat_id, fact, *, target_user=None,
                                 ttl_days=None):
        self.calls.append(dict(chat_id=chat_id, fact=fact,
                               target_user=target_user, ttl_days=ttl_days))
        return self.result


class FakeDbMem:
    """БД-заглушка: фиксирует вызовы forget_memory_facts."""

    def __init__(self, result=3):
        self.result = result
        self.calls = []

    @staticmethod
    def _memory_forget_words(phrase):
        return DatabaseService._memory_forget_words(phrase)

    async def forget_memory_facts(self, chat_id, words, target_user=None,
                                  now_ts=0):
        self.calls.append(dict(chat_id=chat_id, words=words,
                               target_user=target_user, now_ts=now_ts))
        return self.result


class _Cache:
    def __init__(self, settings_map=None, roles=None):
        self._settings = dict(settings_map or {})
        self._roles = dict(roles or {})

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def get_role(self, telegram_id):
        return self._roles.get(telegram_id)


class TestMemoryRbac:
    @pytest.fixture
    def hot_cache(self):
        old = hot.get_config_cache()
        cache = _Cache()
        hot.set_config_cache(cache)
        yield cache
        hot.set_config_cache(old)

    def _service(self, memory=None, db=None):
        return DirectChatService(
            memory or FakeMem(),
            db or FakeDbMem(),
            MagicMock(),                       # llm
            AliasResolver({"10": "Вася"}),     # aliases: 10 → Вася
            throttle=MagicMock(),
            bot_id=12345,
            bot_username="test_bot",
            breaker=None,
        )

    @pytest.mark.asyncio
    async def test_admin_remember_always_and_chat_wide(self, hot_cache):
        """(*,admin): тумблер off — не мешает; target_user=None."""
        mem = FakeMem()
        svc = self._service(memory=mem)
        result = await svc.remember_user_fact(CHAT_ID, _user(ADMIN_ID), "факт")
        assert result == "saved"
        assert mem.calls[0]["target_user"] is None

    @pytest.mark.asyncio
    async def test_moderator_remember_chat_wide(self, hot_cache):
        hot_cache._roles[777] = "moderator"
        mem = FakeMem()
        svc = self._service(memory=mem)
        result = await svc.remember_user_fact(CHAT_ID, _user(777), "факт")
        assert result == "saved"
        assert mem.calls[0]["target_user"] is None

    @pytest.mark.asyncio
    async def test_user_toggle_off_denied_llm_not_called(self, hot_cache):
        """(off,user): дени + сервис памяти НЕ вызван."""
        hot_cache._settings["flags.memory_commands_user_enabled"] = False
        mem = FakeMem()
        svc = self._service(memory=mem)
        result = await svc.remember_user_fact(CHAT_ID, _user(10), "факт")
        assert result == "denied"
        assert mem.calls == []

    @pytest.mark.asyncio
    async def test_user_toggle_on_remember_own(self, hot_cache):
        """(on,user): target_user=канон-имя юзера (алиас «Вася»)."""
        hot_cache._settings["flags.memory_commands_user_enabled"] = True
        mem = FakeMem()
        svc = self._service(memory=mem)
        result = await svc.remember_user_fact(CHAT_ID, _user(10), "факт")
        assert result == "saved"
        assert mem.calls[0]["target_user"] == "Вася"

    @pytest.mark.asyncio
    async def test_remember_ttl_from_hot_limit(self, hot_cache):
        """TTL — hot limits.memory_commands_remember_ttl_days."""
        hot_cache._settings["limits.memory_commands_remember_ttl_days"] = 500
        mem = FakeMem()
        svc = self._service(memory=mem)
        await svc.remember_user_fact(CHAT_ID, _user(ADMIN_ID), "факт")
        assert mem.calls[0]["ttl_days"] == 500

    @pytest.mark.asyncio
    async def test_forget_admin_chat_wide(self, hot_cache):
        dbf = FakeDbMem(result=2)
        svc = self._service(db=dbf)
        code, removed, query = await svc.forget_user_facts(
            CHAT_ID, _user(ADMIN_ID), "бензин лукойл")
        assert (code, removed, query) == ("ok", 2, "бензин лукойл")
        assert dbf.calls[0]["target_user"] is None
        assert dbf.calls[0]["words"] == ["бензин", "лукойл"]

    @pytest.mark.asyncio
    async def test_forget_user_toggle_off_denied(self, hot_cache):
        hot_cache._settings["flags.memory_commands_user_enabled"] = False
        dbf = FakeDbMem()
        svc = self._service(db=dbf)
        code, removed, query = await svc.forget_user_facts(
            CHAT_ID, _user(10), "бензин")
        assert code == "denied"
        assert dbf.calls == []

    @pytest.mark.asyncio
    async def test_forget_user_toggle_on_own_scope(self, hot_cache):
        hot_cache._settings["flags.memory_commands_user_enabled"] = True
        dbf = FakeDbMem(result=1)
        svc = self._service(db=dbf)
        code, removed, _ = await svc.forget_user_facts(
            CHAT_ID, _user(10), "бензин")
        assert (code, removed) == ("ok", 1)
        assert dbf.calls[0]["target_user"] == "Вася"

    @pytest.mark.asyncio
    async def test_memory_error_fail_open(self, hot_cache):
        mem = FakeMem()
        mem.remember_user_fact = AsyncMock(side_effect=RuntimeError("db down"))
        svc = self._service(memory=mem)
        result = await svc.remember_user_fact(CHAT_ID, _user(ADMIN_ID), "факт")
        assert result == "error"
