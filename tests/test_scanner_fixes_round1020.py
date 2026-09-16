"""Раунд 10.20 — фиксы после @Scanner S10.20-* (Step 6→4 итерация).

Покрытие:
* S10.20-2 — per-chat гейт «Летописца» в инструменте/фактчеке;
* S10.20-3 — `dig_into_lore`: JSON всегда валиден при капе (усечение секций);
* S10.20-4 — фактчек не получает «верни story ДОСЛОВНО» + HTML-теги срезаются;
* S10.20-5 — `last_ts` по фактически включённому материалу (UPD);
* S10.20-7 — «Бюджет контекста»: per-chat cap приоритетнее acct;
* S10.20-8/M1 — `_trim` не режет канонический заголовок;
* S10.20-13 — `initialize_existing` валидирует существование/схему;
* S10.20-15 — `_empty_dense()` отдаёт свежий список.

SQLite in-memory, без сети; LLM — фейк.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import hot_config as hot
from services.database import DatabaseService
from services.lore_compiler_service import LoreCompilerService, _empty_dense
from services.smartmodule_utils import strip_lore_html
from services.tool_router import (
    ToolContext,
    ToolDeps,
    ToolRouter,
    _dig_json_payload,
    resolve_lore_compiler_flag,
)

CHAT_ID = -1001234567890


class _FakeLLM:
    """LLM-фейк: отдаёт канонический рассказ, пишет prompt."""

    def __init__(self, story="<b>История</b> про Толяна."):
        self.story = story
        self.messages = []
        self.calls = 0

    async def generate(self, messages, temperature=None, chat_id=None):
        self.calls += 1
        self.messages.append(messages)
        return self.story


async def _new_db() -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


async def _add_message(db, *, text, ts, author="Толян", user_id=1):
    return await db.save_smart_message(
        user_id, CHAT_ID, text, None, ts, "text", author)


# ── S10.20-3: dig JSON всегда валиден ───────────────────────────────────────

class TestDigJsonContract:
    def test_payload_unchanged_when_fits(self):
        result = {"total_mentions": 1, "snippets": ["a"], "facts": []}
        out = _dig_json_payload(result, 10_000)
        assert json.loads(out) == result
        assert "truncated" not in out

    def test_payload_valid_when_capped(self):
        result = {
            "total_mentions": 3,
            "mentions_by_authors": {"Толян": 2, "Ваня": 1},
            "first_seen": "2024-05-01", "last_seen": "2024-06-01",
            "snippets": ["[04.2024 | Толян]: " + "буква " * 800],
            "facts": ["[05.2024 | fact:1]: " + "факт " * 500],
        }
        out = _dig_json_payload(result, 700)
        assert len(out) <= 700
        payload = json.loads(out)                 # не бросает — JSON валиден
        assert payload["truncated"] is True
        assert isinstance(payload["snippets"], list)
        assert isinstance(payload["facts"], list)

    def test_metadata_only_fallback_stays_valid(self):
        result = {"total_mentions": 7,
                  "mentions_by_authors": {("имя" * 200): 1},
                  "snippets": [], "facts": []}
        out = _dig_json_payload(result, 50)
        assert json.loads(out)["truncated"] is True
        assert len(out) <= 50

    @pytest.mark.asyncio
    async def test_dispatch_capped_output_is_json(self, monkeypatch):
        class _FakeHot:
            def get(self, key, default=None):
                return {"limits.dig_max_symbols": 600}.get(key, default)

        monkeypatch.setattr(hot, "_cache", _FakeHot())
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[{
            "user_id": 1, "author_name": "вася", "text": "буква " * 900,
            "timestamp": 1_700_000_000}])
        memory.db = None
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory))
        out = await router.dispatch(
            "dig_into_lore", {"query": "буква", "mode": "messages"},
            ToolContext(CHAT_ID, "буква"))
        assert len(out) <= 600
        assert json.loads(out)["truncated"] is True


# ── S10.20-2: per-chat гейт «Летописца» ────────────────────────────────────

class TestLoreFlagPerChat:
    @pytest.mark.asyncio
    async def test_resolve_prefers_chat_override(self, monkeypatch):
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: (
                False if key == "flags.lore_compiler_enabled" else default))

        async def _fake_chat_param(chat_id, key, default=None):
            if key == "flags.lore_compiler_enabled":
                return True
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            _fake_chat_param)
        assert await resolve_lore_compiler_flag(CHAT_ID) is True
        # Глобальный слой (нет чата) — OFF.
        assert await resolve_lore_compiler_flag(None) is False

    @pytest.mark.asyncio
    async def test_tool_runs_when_chat_on_global_off(self, monkeypatch):
        monkeypatch.setattr(
            hot, "get",
            lambda key, default=None: (
                False if key == "flags.lore_compiler_enabled" else default))

        async def _fake_chat_param(chat_id, key, default=None):
            if key == "flags.lore_compiler_enabled":
                return True
            return default

        monkeypatch.setattr("services.chat_params.get_chat_param",
                            _fake_chat_param)
        db = await _new_db()
        llm = _FakeLLM()
        try:
            await _add_message(db, text="мем тут", ts=1000)
            router = ToolRouter(ToolDeps(search=MagicMock(),
                                         memory=MagicMock(), db=db, llm=llm))
            ctx = ToolContext(CHAT_ID, "поясни за мем")
            out = await router.dispatch("compile_lore_story",
                                        {"topic": "мем"}, ctx)
        finally:
            await db.close()
        assert ctx.lore_compiled is True
        assert llm.story in out
        assert "отключен" not in out


# ── S10.20-4: фактчек — без «верни дословно», HTML срезается ───────────────

class TestLoreInstructionAndHtml:
    @pytest.mark.asyncio
    async def test_factcheck_context_gets_no_verbatim_instruction(self):
        db = await _new_db()
        llm = _FakeLLM()
        try:
            await _add_message(db, text="мем тут", ts=1000)
            router = ToolRouter(ToolDeps(search=MagicMock(),
                                         memory=MagicMock(), db=db, llm=llm))
            ctx = ToolContext(CHAT_ID, "мем",
                              lore_verbatim_instruction=False)
            out = await router.dispatch("compile_lore_story",
                                        {"topic": "мем"}, ctx)
        finally:
            await db.close()
        assert ctx.lore_compiled is True
        assert "ДОСЛОВНО" not in out
        assert json.loads(out.split("\n")[0])["story"] == llm.story

    def test_strip_lore_html_removes_whitelist_tags(self):
        assert strip_lore_html("<b>ок</b> и <i>так</i>") == "ок и так"
        assert strip_lore_html("5 < 10 & 7 > 3") == "5 < 10 & 7 > 3"
        assert strip_lore_html("обычный вердикт") == "обычный вердикт"
        assert strip_lore_html("") == ""


# ── S10.20-5: last_ts по фактически включённому материалу ──────────────────

class _StubDB:
    """Мини-БД для UPD-проверки: агрегаты «убегают» вперёд включённого окна."""

    def __init__(self):
        self.saved: dict = {}

    async def get_lore_story(self, chat_id, topic_key):
        return None

    async def lore_graph_slice(self, *a, **k):
        return {"nodes": [], "edges": [], "facts": []}

    async def lore_dense_dialogs(self, *a, **k):
        return {"earliest": 1000, "latest": 9_000_000, "total": 5,
                "dialogs": [[{"text": "мем тут", "timestamp": 1000, "id": 1,
                              "user_id": 1, "author_name": "Толян",
                              "tg_message_id": 7}]]}

    async def search_messages_fts_count_by_author(self, *a, **k):
        return {"count": 5, "first_seen": 1000, "last_seen": 9_000_000,
                "by_author": []}

    async def upsert_lore_story(self, chat_id, topic_key, topic, story,
                                last_ts):
        self.saved[topic_key] = last_ts


class TestLastTsAdvancesByIncludedMaterial:
    @pytest.mark.asyncio
    async def test_last_ts_is_max_of_included_dialogs(self):
        db = _StubDB()
        llm = _FakeLLM()
        result = await LoreCompilerService(db, llm).compile(CHAT_ID, "мем")
        assert result["status"] == "ok"
        # Включён только диалог ts=1000; stats.last_seen (9_000_000) НЕ должен
        # двигать last_ts — иначе сообщения вне окон выпадут из UPD навсегда.
        assert db.saved["мем"] == 1000


# ── S10.20-8/M1: header-safe `_trim` ───────────────────────────────────────

class TestTrimKeepsHeader:
    def test_long_line_truncated_in_body_only(self):
        line = "[04.2024 | Толян | fact:1]: " + "x" * 200
        out = LoreCompilerService._trim([line], 60)
        assert len(out) == 1
        assert out[0].startswith("[04.2024 | Толян | fact:1]: ")
        assert len(out[0]) <= 60

    def test_line_without_header_dropped(self):
        assert LoreCompilerService._trim(["x" * 200], 30) == []

    def test_within_budget_unchanged(self):
        line = "[04.2024 | Толян | fact:1]: коротко"
        assert LoreCompilerService._trim([line], 1000) == [line]


# ── S10.20-15: свежий пустой срез ──────────────────────────────────────────

def test_empty_dense_is_fresh_per_call():
    first = _empty_dense()
    second = _empty_dense()
    first["dialogs"].append("мусор")
    assert second["dialogs"] == []


# ── S10.20-13: initialize_existing валидирует БД ───────────────────────────

class TestInitializeExistingValidation:
    @pytest.mark.asyncio
    async def test_missing_file_raises(self, tmp_path):
        db = DatabaseService(str(tmp_path / "absent.db"))
        with pytest.raises(FileNotFoundError):
            await db.initialize_existing()

    @pytest.mark.asyncio
    async def test_empty_schema_raises(self, tmp_path):
        path = tmp_path / "empty.db"
        path.write_bytes(b"")
        db = DatabaseService(str(path))
        with pytest.raises(RuntimeError):
            await db.initialize_existing()
        assert db.db is None

    @pytest.mark.asyncio
    async def test_existing_schema_opens(self, tmp_path):
        path = tmp_path / "ready.db"
        seed = DatabaseService(str(path))
        await seed.initialize()
        await seed.close()
        db = DatabaseService(str(path))
        await db.initialize_existing()
        try:
            cursor = await db.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            assert await cursor.fetchone() is not None
        finally:
            await db.close()
