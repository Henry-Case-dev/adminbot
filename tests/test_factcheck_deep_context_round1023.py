"""Раунд 10.23 (F2 `factcheck-deep-context-round1023`, ADR-1023-2) — тесты.

Покрытие:
  * `DatabaseService.get_messages_around` — двунаправленное окно (ASC,
    якорь ровно один раз, границы 0, fail-open → legacy recent);
  * `format_chat_context` — приём `<reply_chains>`-под-блока (байт-в-байт без
    него), маркер F1 сохраняется;
  * `services/thread_chain` — общий util графа реплаев + рендер + паритет
    с `DirectChatService`;
  * handler `_fetch_chat_context`/`_clamp_window` — двунаправленная выборка,
    кап, инжекция цепочки, fail-open;
  * `migrate_factcheck_context_defaults` — legacy → before, идемпотентность,
    кастом не затирается;
  * промпт — обязательный веб-поиск (+ F1-правило сохранено);
  * каталог — +2 ключа, hidden legacy, код-кап вне каталога, вкладка фактчека.
"""
import asyncio
import dataclasses

import pytest

from config.settings import Settings, settings
from services import param_catalog as pc
from services.chat_context import format_chat_context
from services.config_migrations import migrate_factcheck_context_defaults
from services.database import DatabaseService
from services import thread_chain
from services.direct_chat_service import _ChainItem, DirectChatService
from services.factcheck_prompts import (
    FACTCHECK_ANALYST_SYSTEM_PROMPT,
    PREV_FACTCHECK_ANALYST_R1023,
    PREV_FACTCHECK_ANALYST_R1023_F2,
    PREV_FACTCHECK_ANALYST_R1023_F3,
    WEB_SEARCH_INSTRUCTION_BLOCK,
)
from services.target_marking import TARGET_INSTRUCTION_BLOCK
from services import prompt_migrations as pm

CHAT_ID = -100999


# ── DatabaseService.get_messages_around ─────────────────────────────────────

@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


async def _seed(db, texts):
    """texts — список (tg_id, text). Возвращает id строк (по порядку)."""
    ids = []
    for i, (tg, text) in enumerate(texts):
        row_id = await db.save_smart_message(
            user_id=1, chat_id=CHAT_ID, text=text, reply_to_id=None,
            timestamp=1000 + i, media_type="text", author_name="Вася",
            message_id=tg)
        ids.append(row_id)
    return ids


class TestGetMessagesAround:
    @pytest.mark.asyncio
    async def test_bidirectional_asc_and_anchor_once(self, db):
        await _seed(db, [(10, "м1"), (20, "м2"), (30, "якорь"),
                         (40, "м4"), (50, "м5")])
        rows = await db.get_messages_around(CHAT_ID, 30, 1, 1)
        texts = [r["text"] for r in rows]
        assert texts == ["м2", "якорь", "м4"]
        assert texts.count("якорь") == 1

    @pytest.mark.asyncio
    async def test_boundaries_zero_and_full(self, db):
        await _seed(db, [(10, "м1"), (20, "м2"), (30, "м3")])
        assert [r["text"] for r in await db.get_messages_around(
            CHAT_ID, 20, 0, 0)] == ["м2"]
        assert [r["text"] for r in await db.get_messages_around(
            CHAT_ID, 20, 10, 10)] == ["м1", "м2", "м3"]

    @pytest.mark.asyncio
    async def test_anchor_not_found_falls_back_to_recent(self, db):
        await _seed(db, [(10, "м1"), (20, "м2"), (30, "м3")])
        rows = await db.get_messages_around(CHAT_ID, 999, 2, 2)
        assert len(rows) == 3                      # legacy recent(before+after)

    @pytest.mark.asyncio
    async def test_fail_open_on_db_error(self):
        class _BrokenConn:
            async def execute(self, *a, **k):
                raise RuntimeError("boom")

        class _FakeSelf:
            db = _BrokenConn()

            async def get_recent_messages(self, chat_id, limit):
                return [{"fallback": True}]

        out = await DatabaseService.get_messages_around(
            _FakeSelf(), CHAT_ID, 1, 2, 3)
        assert out == [{"fallback": True}]


# ── format_chat_context + reply_chains ──────────────────────────────────────

def _row(tg, text="привет", ts=1000, name="Вася", uid=1):
    return dict(tg_message_id=tg, id=tg, text=text, timestamp=ts,
                author_name=name, user_id=uid, is_forward=0)


class TestChatContextReplyChains:
    def test_no_chain_byte_for_byte_legacy(self):
        rows = [_row(1), _row(2)]
        assert (format_chat_context(rows)
                == format_chat_context(rows, reply_chains=""))

    def test_reply_chains_inserted_inside_block(self):
        rows = [_row(1)]
        chains = ('<reply_chains note="x">[11.11.1111 | Кто-то | tg:9]: '
                  'уникальный_маркер_цепи</reply_chains>')
        out = format_chat_context(rows, reply_chains=chains)
        assert out.startswith("<chat_context ")
        assert "уникальный_маркер_цепи" in out
        assert out.endswith("</chat_context>")
        # цепь — ПОСЛЕ окна (внутри <chat_context>)
        window_line = "[01.01.1970 00:16 | Вася | tg:1]: привет"
        assert window_line in out
        assert out.index(window_line) < out.index("уникальный_маркер_цепи")

    def test_trigger_marker_preserved_with_chains(self):
        rows = [_row(1), _row(2)]
        out = format_chat_context(
            rows, trigger_message_id=2,
            reply_chains="<reply_chains note=\"x\">y</reply_chains>")
        assert "[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]" in out

    def test_chain_note_marks_not_evidence(self):
        block = thread_chain.render_reply_chains(
            [thread_chain.ChainItem(1, "Вася", "привет", False, 1000,
                                    "tg:1", None)])
        assert "НЕ доказательства" in block
        assert block.startswith("<reply_chains")
        assert block.endswith("</reply_chains>")


# ── thread_chain util / паритет direct ──────────────────────────────────────

class _FakeChainDB:
    """db-контракт thread_chain: user-строки + бот-ответы по parent-линкам."""

    def __init__(self, messages, bot_replies=None, parents=None):
        self.messages = messages                # tg_id → row
        self.bot_replies = bot_replies or {}    # tg_id → text
        self.parents = parents or {}            # tg_id → parent tg_id
        self.calls = []

    async def get_smart_message_by_tg_id(self, chat_id, tg_id):
        self.calls.append(("msg", tg_id))
        return self.messages.get(tg_id)

    async def get_bot_reply(self, chat_id, tg_id, now):
        return self.bot_replies.get(tg_id)

    async def get_bot_reply_parent(self, chat_id, tg_id, now):
        return self.parents.get(tg_id)


class TestThreadChainUtil:
    @pytest.mark.asyncio
    async def test_chain_through_bot_replies_newest_first(self):
        messages = {
            30: dict(text="ты кто?", reply_to_id=None, timestamp=100,
                     author_name="вася", user_id=10, tg_message_id=30,
                     id=30, is_forward=0),
            50: dict(text="а почему так?", reply_to_id=40, timestamp=200,
                     author_name="петя", user_id=20, tg_message_id=50,
                     id=50, is_forward=0),
            70: dict(text="вот это новости", reply_to_id=60, timestamp=300,
                     author_name="вася", user_id=10, tg_message_id=70,
                     id=70, is_forward=0),
        }
        db = _FakeChainDB(
            messages,
            bot_replies={40: "я твой кошмар", 60: "потому что так надо"},
            parents={40: 30, 60: 50})
        chain = await thread_chain.collect_thread_chain(db, CHAT_ID, 70, 6)
        # от текущего (msg 70) к корню (tg:30), сквозь бот-ответы
        assert [c.item_id for c in chain] == \
            ["tg:70", "tg:60", "tg:50", "tg:40", "tg:30"]
        assert chain[1].is_bot and chain[-1].uid == 10

    @pytest.mark.asyncio
    async def test_accepts_message_like_and_int(self):
        db = _FakeChainDB({})
        assert await thread_chain.collect_thread_chain(db, CHAT_ID, 7, 3) == []
        assert db.calls == [("msg", 7)]

    @pytest.mark.asyncio
    async def test_depth_limit(self):
        messages = {i: dict(text=f"t{i}", reply_to_id=i - 1, timestamp=i,
                            author_name="a", user_id=1, tg_message_id=i,
                            id=i, is_forward=0) for i in range(1, 6)}
        db = _FakeChainDB(messages)
        chain = await thread_chain.collect_thread_chain(db, CHAT_ID, 5, 2)
        assert [c.item_id for c in chain] == ["tg:5", "tg:4"]

    def test_render_asc_root_first(self):
        chain = [
            thread_chain.ChainItem(None, "бот", "реплика_бота", True, None,
                                   "tg:2", None),
            thread_chain.ChainItem(1, "вася", "реплика_юзера", False, 100,
                                   "tg:1", None),
        ]
        out = thread_chain.render_reply_chains(chain)
        assert out.index("реплика_юзера") < out.index("реплика_бота")

    def test_direct_parity_aliases_and_line(self):
        assert _ChainItem is thread_chain.ChainItem
        item = _ChainItem(10, "вася", "привет", False, 1_700_000_000,
                          "tg:5", None)
        assert DirectChatService._chain_line(None, item, {}) == \
            thread_chain.format_chain_line(item, {})
        assert DirectChatService._chain_line(None, item, {}) == \
            thread_chain.format_chain_line(item, {})


# ── handler: clamp + _fetch_chat_context + инжекция ─────────────────────────

class TestHandlerWindow:
    def test_clamp_defaults(self):
        from handlers import factcheck as fc
        assert fc._clamp_window(6, 6) == (6, 6)

    def test_clamp_zero(self):
        from handlers import factcheck as fc
        assert fc._clamp_window(0, 0) == (0, 0)
        assert fc._clamp_window(None, None) == (0, 0)
        assert fc._clamp_window("x", "y") == (0, 0)

    def test_clamp_total_cap(self):
        from handlers import factcheck as fc
        from config.settings import settings as s
        cap = s.FACTCHECK_CONTEXT_TOTAL_CAP
        b, a = fc._clamp_window(25, 25)
        assert (b, a) == (25, cap - 25)
        assert b + a <= cap
        b, a = fc._clamp_window(1000, 1000)
        assert (b, a) == (cap, 0)

    @pytest.mark.asyncio
    async def test_fetch_uses_clamped_bidir_window(self, monkeypatch):
        from handlers import factcheck as fc

        class _DB:
            def __init__(self):
                self.calls = []

            async def get_messages_around(self, chat_id, target, before, after):
                self.calls.append((chat_id, target, before, after))
                return [_row(30, "якорь", ts=1500)]

            async def get_smart_message_by_tg_id(self, chat_id, tg_id):
                return None

        db = _DB()
        monkeypatch.setattr(fc, "_db", db)
        out = await fc._fetch_chat_context(
            CHAT_ID, 25, 25, target_tg_message_id=30, trigger_message_id=31)
        assert db.calls == [(CHAT_ID, 30, 25, 15)]
        assert "якорь" in out

    @pytest.mark.asyncio
    async def test_fetch_injects_reply_chain_for_anchor(self, monkeypatch):
        from handlers import factcheck as fc

        class _DB:
            async def get_messages_around(self, chat_id, target, before, after):
                return [_row(30, "якорь", ts=1500)]

            async def get_smart_message_by_tg_id(self, chat_id, tg_id):
                if tg_id == 30:
                    return dict(text="якорь", reply_to_id=None, timestamp=1500,
                                author_name="Вася", user_id=1,
                                tg_message_id=30, id=30, is_forward=0)
                return None

        monkeypatch.setattr(fc, "_db", _DB())
        out = await fc._fetch_chat_context(
            CHAT_ID, 6, 6, target_tg_message_id=30)
        assert "<reply_chains" in out
        assert "НЕ доказательства" in out

    @pytest.mark.asyncio
    async def test_fetch_fail_open_on_db_error(self, monkeypatch):
        from handlers import factcheck as fc

        class _DB:
            async def get_messages_around(self, *a, **k):
                raise RuntimeError("boom")

        monkeypatch.setattr(fc, "_db", _DB())
        assert await fc._fetch_chat_context(
            CHAT_ID, 6, 6, target_tg_message_id=30) == ""

    @pytest.mark.asyncio
    async def test_fetch_no_db_returns_empty(self, monkeypatch):
        from handlers import factcheck as fc
        monkeypatch.setattr(fc, "_db", None)
        assert await fc._fetch_chat_context(
            CHAT_ID, 6, 6, target_tg_message_id=30) == ""


# ── legacy-миграция окна ────────────────────────────────────────────────────

class _FakeCache:
    def __init__(self, values=None, pg_available=True):
        self.pg_available = pg_available
        self.values = dict(values or {})
        self.set_calls = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))


class TestFactcheckContextMigration:
    LEGACY = "limits.factcheck_context_messages"
    BEFORE = "limits.factcheck_context_before"

    @pytest.mark.asyncio
    async def test_legacy_transferred_to_before(self):
        cache = _FakeCache({self.LEGACY: 12})
        report = await migrate_factcheck_context_defaults(cache)
        assert report == {self.BEFORE: "updated"}
        assert cache.set_calls == [(self.BEFORE, 12, "limits")]

    @pytest.mark.asyncio
    async def test_default_before_overwritten_by_legacy(self):
        """Сид поставил code-дефолт (6) — переносим кастом legacy."""
        cache = _FakeCache({self.LEGACY: 12, self.BEFORE: 6})
        report = await migrate_factcheck_context_defaults(cache)
        assert report == {self.BEFORE: "updated"}
        assert cache.set_calls == [(self.BEFORE, 12, "limits")]

    @pytest.mark.asyncio
    async def test_custom_before_not_overwritten(self):
        cache = _FakeCache({self.LEGACY: 12, self.BEFORE: 9})
        report = await migrate_factcheck_context_defaults(cache)
        assert report == {}
        assert cache.set_calls == []

    @pytest.mark.asyncio
    async def test_idempotent(self):
        cache = _FakeCache({self.LEGACY: 12, self.BEFORE: 12})
        report = await migrate_factcheck_context_defaults(cache)
        assert report == {}
        assert cache.set_calls == []

    @pytest.mark.asyncio
    async def test_missing_legacy_skipped(self):
        cache = _FakeCache({})
        assert await migrate_factcheck_context_defaults(cache) == {}

    @pytest.mark.asyncio
    async def test_non_numeric_legacy_skipped(self):
        cache = _FakeCache({self.LEGACY: "abc"})
        assert await migrate_factcheck_context_defaults(cache) == {}

    @pytest.mark.asyncio
    async def test_pg_down_skipped(self):
        cache = _FakeCache({self.LEGACY: 12}, pg_available=False)
        assert await migrate_factcheck_context_defaults(cache) == {}

    @pytest.mark.asyncio
    async def test_none_cache_skipped(self):
        assert await migrate_factcheck_context_defaults(None) == {}


# ── промпт-правило обязательного веб-поиска ─────────────────────────────────

class TestWebSearchPrompt:
    def test_rule_present(self):
        assert WEB_SEARCH_INSTRUCTION_BLOCK in FACTCHECK_ANALYST_SYSTEM_PROMPT
        assert "ОБЯЗАН вызвать веб-поиск" in FACTCHECK_ANALYST_SYSTEM_PROMPT

    def test_f1_marking_rule_preserved(self):
        assert TARGET_INSTRUCTION_BLOCK in FACTCHECK_ANALYST_SYSTEM_PROMPT

    def test_f2_snapshot_is_f1_canon(self):
        assert PREV_FACTCHECK_ANALYST_R1023_F2 != FACTCHECK_ANALYST_SYSTEM_PROMPT
        assert PREV_FACTCHECK_ANALYST_R1023_F2 != PREV_FACTCHECK_ANALYST_R1023
        assert WEB_SEARCH_INSTRUCTION_BLOCK not in PREV_FACTCHECK_ANALYST_R1023_F2

    def test_migration_and_rollback_steps(self):
        key = "prompts.factcheck_analyst_system_prompt"
        assert (PREV_FACTCHECK_ANALYST_R1023,
                FACTCHECK_ANALYST_SYSTEM_PROMPT) in pm.PROMPT_MIGRATIONS[key]
        assert (PREV_FACTCHECK_ANALYST_R1023_F2,
                FACTCHECK_ANALYST_SYSTEM_PROMPT) in pm.PROMPT_MIGRATIONS[key]
        # 10.23 (F3, ADR-1023-3): ступень response_mode стала последней —
        # откат снимает только её (F3-слепок сохраняет правило веб-поиска).
        assert pm.ROLLBACK_MIGRATIONS[key] == (
            FACTCHECK_ANALYST_SYSTEM_PROMPT, PREV_FACTCHECK_ANALYST_R1023_F3)
        assert WEB_SEARCH_INSTRUCTION_BLOCK in PREV_FACTCHECK_ANALYST_R1023_F3


# ── каталог: +2 ключа, hidden legacy, код-кап, вкладка ───────────────────────

class TestCatalogDelta:
    def test_two_new_keys(self):
        before = pc.get("FACTCHECK_CONTEXT_BEFORE")
        after = pc.get("FACTCHECK_CONTEXT_AFTER")
        assert before is not None and after is not None
        assert before.pg_key == "limits.factcheck_context_before"
        assert after.pg_key == "limits.factcheck_context_after"
        assert before.group == "limits_factcheck"
        assert after.group == "limits_factcheck"
        assert before.type == "int" and after.type == "int"

    def test_defaults_six_six(self):
        assert Settings.FACTCHECK_CONTEXT_BEFORE == 6
        assert Settings.FACTCHECK_CONTEXT_AFTER == 6

    def test_total_cap_is_code_classvar_not_catalog(self):
        assert settings.FACTCHECK_CONTEXT_TOTAL_CAP == 40
        field_names = {f.name for f in dataclasses.fields(Settings)}
        assert "FACTCHECK_CONTEXT_TOTAL_CAP" not in field_names
        assert pc.get("FACTCHECK_CONTEXT_TOTAL_CAP") is None

    def test_legacy_hidden_but_in_registry(self):
        legacy = pc.get("FACTCHECK_CONTEXT_MESSAGES")
        assert legacy is not None
        assert legacy.hidden is True

    def test_factcheck_tab_contains_new_keys_group(self):
        assert pc.group_tab("limits_factcheck") == pc.TAB_MOD_FACTCHECK
        visible = {s.pg_key for s in pc.by_category("limits")
                   if not s.hidden}
        assert "limits.factcheck_context_before" in visible
        assert "limits.factcheck_context_after" in visible
        assert "limits.factcheck_context_messages" not in visible
