"""Раунд 10.20 (Фаза C, «Летописец») — T-1887…T-1892.

Покрытие:
* T-1887 — 8-й тул: схема/`active_tools` (в test_tool_schemas.py), dispatch,
  сигнал `ToolContext.lore_compiled`, гейт `flags.lore_compiler_enabled`;
* T-1888 — `db.lore_graph_slice` (узел + связи 1-2 ур. + Убеждения, детерминизм);
* T-1889 — `db.lore_dense_dialogs` (earliest/latest + топ-3 бакета, ASC,
  честный пустой случай, UPD-окно `since_ts`);
* T-1890 — канон `LORE_STORY_SYSTEM_PROMPT` (байт-в-байт с эталоном) +
  `build_lore_story_user` (UPD-блоки);
* T-1891 — `lore_stories`: аддитивно, БЕЗ бампа `user_version`, UPSERT;
* T-1892 — доставка: HTML + экранирование + plain-фолбэк.

SQLite in-memory, без сети; LLM — фейк.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from services import direct_chat_service as dcs
from services.database import DatabaseService
from services.lore_compiler_service import LoreCompilerService, topic_tokens
from services.lore_prompts import LORE_STORY_SYSTEM_PROMPT, build_lore_story_user
from services.smartmodule_utils import escape_lore_html
from services.tool_router import ToolContext, ToolDeps, ToolRouter

CHAT_ID = -1001234567890
OTHER_CHAT = -1009999999999


# ── фикстуры/хелперы ─────────────────────────────────────────────────────


async def _new_db() -> DatabaseService:
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


async def _add_message(db, *, text, ts, author="Толян", user_id=1,
                       tg_message_id=None, chat_id=CHAT_ID):
    return await db.save_smart_message(
        user_id, chat_id, text, None, ts, "text", author,
        message_id=tg_message_id)


class _FakeLLM:
    """LLM-фейк сервиса: пишет prompt, отдаёт канонический рассказ."""

    def __init__(self, story="<b>История</b> про Толяна."):
        self.story = story
        self.messages = []
        self.calls = 0

    async def generate(self, messages, temperature=None, chat_id=None):
        self.calls += 1
        self.messages.append(messages)
        return self.story


def _arch_lore_story_prompt() -> str:
    """Эталон из plans/docs/canon/architecture.md (блок
    LORE_STORY_SYSTEM_PROMPT) — извлечение по якорям, как в
    test_checkup_prompts/test_factcheck_prompts."""
    lines = Path("plans/docs/canon/architecture.md").read_text(
        encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines)
        if line.startswith("LORE_STORY_SYSTEM_PROMPT = "))
    end = next(
        i for i, line in enumerate(lines[start:], start)
        if line.endswith('"""'))
    block = lines[start:end + 1]
    block[0] = block[0][len('LORE_STORY_SYSTEM_PROMPT = """'):]
    block[-1] = block[-1][:-3]
    return "\n".join(block)


# ── T-1890: канон промпта + сборка user-контента ────────────────────────


class TestLoreStoryCanon:
    def test_byte_for_byte_with_architecture(self):
        assert LORE_STORY_SYSTEM_PROMPT == _arch_lore_story_prompt()

    def test_canon_structure_and_html(self):
        text = LORE_STORY_SYSTEM_PROMPT
        assert "{topic}" in text
        assert "завязк" in text and "развитие событий" in text
        assert "статус-кво" in text
        assert "постирония" in text
        assert "<b>" in text and "<i>" in text          # О5: HTML, не Markdown
        assert "Маркдаун" in text
        assert "UPD (Свежак)" in text
        assert "НЕ ври про ключевые действия" in text
        assert text.count("{") == 1 and text.count("}") == 1

    def test_topic_placeholder_replacement(self):
        merged = LORE_STORY_SYSTEM_PROMPT.replace("{topic}", "мем про Толяна")
        assert "мем про Толяна" in merged
        assert "{topic}" not in merged


class TestBuildLoreStoryUser:
    def test_first_request_has_stats_graph_and_chronology(self):
        user = build_lore_story_user(
            topic="мем", graph_facts=["[05.2024 | Толян | fact:1]: ф1"],
            dialogs=["[15.05.2024 21:07 | Толян | tg:9]: д1"],
            total_mentions=3, mentions_by_authors={"Толян": 2, "Ваня": 1},
            first_seen="2024-05-15", last_seen="2024-06-01")
        assert "Тема: мем" in user
        assert "упоминаний: 3" in user
        assert "ф1" in user and "д1" in user
        assert "Известная база" not in user
        assert "Хронология (ASC)" in user

    def test_update_request_adds_base_and_upd_blocks(self):
        user = build_lore_story_user(
            topic="мем", graph_facts=[], dialogs=["[новое]: д2"],
            previous_story="Старая история.")
        assert "Известная база (сохраненная ранее история):" in user
        assert "Старая история." in user
        assert "Свежак" in user and "д2" in user
        assert "Хронология (ASC)" not in user

    def test_honest_empty_sections(self):
        user = build_lore_story_user(topic="мем")
        assert "Факты графа памяти (ASC):\n(нет)" in user
        assert "Хронология (ASC):\n(нет)" in user

    def test_no_new_messages_update_is_honest(self):
        user = build_lore_story_user(topic="мем", previous_story="База.")
        assert "(новых сообщений нет)" in user


# ── T-1888: db.lore_graph_slice ─────────────────────────────────────────


class TestLoreGraphSlice:
    @pytest.mark.asyncio
    async def test_node_relations_and_linked_fact(self):
        db = await _new_db()
        try:
            sid = await db.upsert_node(CHAT_ID, "Толян", "user")
            tid = await db.upsert_node(CHAT_ID, "Ваня", "user")
            mid = await db.upsert_node(CHAT_ID, "Мем", "topic")
            fact_id = await db.insert_graph_fact(
                CHAT_ID, "Толян спорил с Ваней из-за мема", "chat_history",
                None, target_user="Толян", message_timestamp=1000)
            await db.upsert_edge(sid, tid, "спорил с", fact_id=fact_id)
            await db.upsert_edge(tid, mid, "обсуждал")
            slice_ = await db.lore_graph_slice(CHAT_ID, "Толян", depth=2)
        finally:
            await db.close()
        names = {n["entity_name"] for n in slice_["nodes"]}
        assert {"Толян", "Ваня"} <= names
        rels = {(e["source"], e["target"], e["relation_type"])
                for e in slice_["edges"]}
        assert ("Толян", "Ваня", "спорил с") in rels
        assert ("Ваня", "Мем", "обсуждал") in rels     # 2-й уровень
        assert slice_["facts"][0]["id"] == fact_id
        assert slice_["facts"][0]["rag_ts"] == 1000

    @pytest.mark.asyncio
    async def test_no_match_is_honest_empty(self):
        db = await _new_db()
        try:
            await db.upsert_node(CHAT_ID, "Толян", "user")
            out = await db.lore_graph_slice(CHAT_ID, "Совсем другое")
        finally:
            await db.close()
        assert out == {"nodes": [], "edges": [], "facts": []}

    @pytest.mark.asyncio
    async def test_facts_sorted_asc_and_other_chat_excluded(self):
        db = await _new_db()
        try:
            sid = await db.upsert_node(CHAT_ID, "Мем", "topic")
            tid = await db.upsert_node(CHAT_ID, "Ваня", "user")
            await db.upsert_node(OTHER_CHAT, "Мемчужный", "topic")
            late = await db.insert_graph_fact(
                CHAT_ID, "поздний", "chat_history", None,
                message_timestamp=2000)
            early = await db.insert_graph_fact(
                CHAT_ID, "ранний", "chat_history", None,
                message_timestamp=1000)
            await db.upsert_edge(sid, tid, "r1", fact_id=late)
            await db.upsert_edge(tid, sid, "r2", fact_id=early)
            slice_ = await db.lore_graph_slice(CHAT_ID, "Мем")
        finally:
            await db.close()
        assert [f["id"] for f in slice_["facts"]] == [early, late]   # ASC
        assert all("Мемчужный" != n["entity_name"] for n in slice_["nodes"])


# ── T-1889: db.lore_dense_dialogs ───────────────────────────────────────


class TestLoreDenseDialogs:
    @pytest.mark.asyncio
    async def test_density_windows_and_asc_full_text(self):
        db = await _new_db()
        try:
            await _add_message(db, text="мем про толяна", ts=1000)
            await _add_message(db, text="просто болтовня", ts=1100)
            await _add_message(db, text="мем мем мем", ts=1200)
            await _add_message(db, text="мем снова", ts=5000)
            out = await db.lore_dense_dialogs(
                CHAT_ID, '"мем"*', max_dialogs=3, window_minutes=30)
        finally:
            await db.close()
        assert out["earliest"] == 1000 and out["latest"] == 5000
        assert out["total"] == 3
        # 2 окна: плотное (1000-1200) и позднее (5000), ASC по началу
        assert len(out["dialogs"]) == 2
        first = out["dialogs"][0]
        texts = [r["text"] for r in first]
        assert texts == ["мем про толяна", "просто болтовня", "мем мем мем"]
        stamps = [int(r["timestamp"]) for r in first]
        assert stamps == sorted(stamps)                 # строго ASC
        assert [int(r["timestamp"]) for r in out["dialogs"][1]] == [5000]

    @pytest.mark.asyncio
    async def test_since_ts_filters_to_new_only(self):
        db = await _new_db()
        try:
            await _add_message(db, text="мем старый", ts=1000)
            await _add_message(db, text="мем свежий", ts=5000)
            out = await db.lore_dense_dialogs(
                CHAT_ID, '"мем"*', since_ts=1500)
        finally:
            await db.close()
        assert out["total"] == 1
        assert out["earliest"] == out["latest"] == 5000
        assert [r["text"] for r in out["dialogs"][0]] == ["мем свежий"]

    @pytest.mark.asyncio
    async def test_empty_case_is_honest(self):
        db = await _new_db()
        try:
            out = await db.lore_dense_dialogs(CHAT_ID, '"ничего"*')
        finally:
            await db.close()
        assert out == {"earliest": None, "latest": None, "total": 0,
                       "dialogs": []}

    @pytest.mark.asyncio
    async def test_empty_match_query_noop(self):
        db = await _new_db()
        try:
            await _add_message(db, text="мем", ts=1000)
            out = await db.lore_dense_dialogs(CHAT_ID, "")
        finally:
            await db.close()
        assert out["total"] == 0 and out["dialogs"] == []


# ── T-1891: lore_stories (аддитивно, без бампа user_version) ────────────


class TestLoreStoriesStorage:
    @pytest.mark.asyncio
    async def test_table_exists_without_user_version_bump(self):
        db = await _new_db()
        try:
            cursor = await db.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='lore_stories'")
            assert await cursor.fetchone() is not None
            cursor = await db.db.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            # lore_stories — аддитивно (О7); user_version поднят Фазой G до 12.
            assert int(row[0]) == 12
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_upsert_and_get_roundtrip(self):
        db = await _new_db()
        try:
            assert await db.get_lore_story(CHAT_ID, "mem") is None
            await db.upsert_lore_story(CHAT_ID, "mem", "мем", "раз", 1000)
            await db.upsert_lore_story(CHAT_ID, "mem", "мем", "два", 2000)
            story = await db.get_lore_story(CHAT_ID, "mem")
        finally:
            await db.close()
        assert story["story"] == "два"
        assert story["last_ts"] == 2000
        assert story["created_at"] <= story["updated_at"]


# ── T-1888/T-1889/T-1890/T-1891: сборка сервисом ────────────────────────


class TestLoreCompilerService:
    @pytest.mark.asyncio
    async def test_first_compile_builds_json_and_saves(self):
        db = await _new_db()
        llm = _FakeLLM()
        try:
            await _add_message(db, text="мем про толяна", ts=1000)
            await _add_message(db, text="мем мем", ts=1010)
            sid = await db.upsert_node(CHAT_ID, "Мем", "topic")
            tid = await db.upsert_node(CHAT_ID, "Толян", "user")
            fid = await db.insert_graph_fact(
                CHAT_ID, "Толян родил мем", "chat_history", None,
                target_user="Толян", message_timestamp=900)
            await db.upsert_edge(sid, tid, "автор", fact_id=fid)
            result = await LoreCompilerService(db, llm).compile(CHAT_ID, "мем")
            saved = await db.get_lore_story(CHAT_ID, "мем")
        finally:
            await db.close()
        assert result["status"] == "ok"
        assert result["is_update"] is False
        assert result["story"] == llm.story
        assert saved is not None and saved["story"] == llm.story
        system, user = llm.messages[0]
        assert system["content"] == LORE_STORY_SYSTEM_PROMPT.replace(
            "{topic}", "мем")
        assert "Толян родил мем" in user["content"]
        assert "мем про толяна" in user["content"]

    @pytest.mark.asyncio
    async def test_second_compile_is_update_with_new_only(self):
        db = await _new_db()
        llm = _FakeLLM()
        try:
            await _add_message(db, text="мем старый", ts=1000)
            first = await LoreCompilerService(db, llm).compile(CHAT_ID, "мем")
            await _add_message(db, text="мем новый", ts=2000)
            second = await LoreCompilerService(db, llm).compile(CHAT_ID, "мем")
        finally:
            await db.close()
        assert first["is_update"] is False
        assert second["is_update"] is True
        assert second["previous_story_at"] is not None
        user = llm.messages[1][1]["content"]
        assert "Известная база" in user
        assert "мем новый" in user
        assert "мем старый" not in user       # база — из story, не дублируется

    @pytest.mark.asyncio
    async def test_update_without_new_data_reuses_story(self):
        db = await _new_db()
        llm = _FakeLLM()
        try:
            await _add_message(db, text="мем", ts=1000)
            await LoreCompilerService(db, llm).compile(CHAT_ID, "мем")
            calls_after_first = llm.calls
            again = await LoreCompilerService(db, llm).compile(CHAT_ID, "мем")
        finally:
            await db.close()
        assert again["status"] == "ok" and again["is_update"] is True
        assert again.get("unchanged") is True
        assert llm.calls == calls_after_first     # дорогой вызов не повторяем

    @pytest.mark.asyncio
    async def test_nothing_found_is_honest(self):
        db = await _new_db()
        llm = _FakeLLM()
        try:
            result = await LoreCompilerService(db, llm).compile(
                CHAT_ID, "ничего нет")
        finally:
            await db.close()
        assert result["status"] == "not_found"
        assert llm.calls == 0


# ── T-1887/T-1892: dispatch тула + сигнал + доставка ───────────────────


def _tool_deps(db, llm):
    return ToolDeps(search=MagicMock(), memory=MagicMock(), db=db, llm=llm)


class TestCompileLoreStoryTool:
    @pytest.mark.asyncio
    async def test_dispatch_sets_signal_and_returns_story_json(self):
        db = await _new_db()
        llm = _FakeLLM()
        try:
            await _add_message(db, text="мем тут", ts=1000)
            router = ToolRouter(_tool_deps(db, llm))
            ctx = ToolContext(CHAT_ID, "поясни за мем")
            out = await router.dispatch("compile_lore_story",
                                        {"topic": "мем"}, ctx)
        finally:
            await db.close()
        assert ctx.lore_compiled is True
        assert '"story"' in out and llm.story in out
        assert "ДОСЛОВНО" in out

    @pytest.mark.asyncio
    async def test_flag_off_disables_tool(self, monkeypatch):
        db = await _new_db()
        llm = _FakeLLM()
        monkeypatch.setattr(
            "services.tool_router.hot.get",
            lambda key, default=None: (
                False if key == "flags.lore_compiler_enabled" else default))
        try:
            router = ToolRouter(_tool_deps(db, llm))
            ctx = ToolContext(CHAT_ID, "поясни за мем")
            out = await router.dispatch("compile_lore_story",
                                        {"topic": "мем"}, ctx)
        finally:
            await db.close()
        assert "отключен" in out
        assert ctx.lore_compiled is False
        assert llm.calls == 0

    @pytest.mark.asyncio
    async def test_missing_topic_uses_user_query_fallback(self):
        db = await _new_db()
        llm = _FakeLLM()
        try:
            await _add_message(db, text="мем тут", ts=1000)
            router = ToolRouter(_tool_deps(db, llm))
            ctx = ToolContext(CHAT_ID, "расскажи историю про мем")
            out = await router.dispatch("compile_lore_story", {}, ctx)
        finally:
            await db.close()
        assert ctx.lore_compiled is True
        assert llm.story in out


class TestLoreStoryDelivery:
    @pytest.mark.asyncio
    async def test_lore_answer_goes_as_html_escaped(self, monkeypatch):
        calls = []

        async def fake_send(bot, chat_id, text, reply_to=None, **kw):
            calls.append((text, kw))
            return 1

        monkeypatch.setattr(dcs, "send_chunked_reply", fake_send)
        await dcs.DirectChatService._send_direct_answer(
            None, CHAT_ID, "<b>ок</b> 5 < 10", 7, lore=True)
        assert calls[0][1] == {"parse_mode": "HTML"}
        assert calls[0][0] == "<b>ок</b> 5 &lt; 10"

    @pytest.mark.asyncio
    async def test_normal_answer_stays_plain(self, monkeypatch):
        calls = []

        async def fake_send(bot, chat_id, text, reply_to=None, **kw):
            calls.append((text, kw))
            return 1

        monkeypatch.setattr(dcs, "send_chunked_reply", fake_send)
        await dcs.DirectChatService._send_direct_answer(
            None, CHAT_ID, "обычный **ответ**", 7, lore=False)
        assert calls[0][1] == {}
        assert calls[0][0] == "обычный **ответ**"

    @pytest.mark.asyncio
    async def test_broken_html_falls_back_to_plain_raw(self, monkeypatch):
        calls = []

        async def fake_send(bot, chat_id, text, reply_to=None, **kw):
            calls.append((text, kw))
            if kw.get("parse_mode") == "HTML":
                raise TelegramBadRequest(method="sendMessage",
                                         message="can't parse entities")
            return 1

        monkeypatch.setattr(dcs, "send_chunked_reply", fake_send)
        await dcs.DirectChatService._send_direct_answer(
            None, CHAT_ID, "<b>битая", 7, lore=True)
        assert len(calls) == 2
        assert calls[0][1] == {"parse_mode": "HTML"}
        assert calls[1][1] == {}
        assert calls[1][0] == "<b>битая"      # исходный текст, не экранированный

    @pytest.mark.asyncio
    async def test_long_story_goes_plain_without_tag_split(self, monkeypatch):
        """S10.20-10: длинная HTML-история не чанкится по тегам — plain без
        разметки, чтобы разрыв тега не вызвал дубль текста."""
        calls = []

        async def fake_send(bot, chat_id, text, reply_to=None, **kw):
            calls.append((text, kw))
            return 1

        monkeypatch.setattr(dcs, "send_chunked_reply", fake_send)
        long_story = "<b>" + ("слово " * 900) + "</b>"
        assert len(long_story) > 4096
        await dcs.DirectChatService._send_direct_answer(
            None, CHAT_ID, long_story, 7, lore=True)
        assert len(calls) == 1
        assert calls[0][1] == {}                 # plain, без parse_mode
        assert "<b>" not in calls[0][0]          # теги срезаны


class TestEscapeLoreHtml:
    def test_keeps_allowed_tags_and_escapes_garbage(self):
        assert escape_lore_html("<b>x</b>") == "<b>x</b>"
        assert escape_lore_html("<i>a</i><b>b</b>") == "<i>a</i><b>b</b>"
        assert escape_lore_html("5 < 10 & 7 > 3") == \
            "5 &lt; 10 &amp; 7 &gt; 3"
        assert escape_lore_html("<script>x</script>") == \
            "&lt;script&gt;x&lt;/script&gt;"

    def test_empty(self):
        assert escape_lore_html("") == ""
        assert escape_lore_html(None) == ""


# ── topic_tokens helper ─────────────────────────────────────────────────


def test_topic_tokens_dedup_and_min_len():
    assert topic_tokens("Мем про Толяна, мем!") == ["мем", "про", "толяна"]
    assert topic_tokens("я!") == []
