"""Tests for the GraphRAG memory layer (Epic 26, T-201/T-202/T26.2/T26.3, Section 35.4/35.5)."""
import asyncio
import json
import sqlite3
import time
from dataclasses import replace
from unittest.mock import patch

import pytest

from config.settings import settings
from services.database import DatabaseService
from services.llm_client import LLMError
from services.summary_memory import (
    GraphExtractionError,
    MemoryManager,
    _normalize_name,
    parse_triplets,
)
from services.summary_prompts import EXTRACT_PROMPT


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class FakeLLM:
    """Canned-JSON pattern (Q10): extract_response для EXTRACT_PROMPT, facts для compress."""

    def __init__(self, facts="факт", extract_response="[]", fail_extract=False,
                 fail_compress=False):
        self.facts = facts
        self.extract_response = extract_response
        self.fail_extract = fail_extract
        self.fail_compress = fail_compress
        self.extract_calls = 0
        self.compress_calls = 0

    async def generate(self, messages):
        if messages[0]["content"] == EXTRACT_PROMPT:
            self.extract_calls += 1
            if self.fail_extract:
                raise LLMError("экстрактор упал")
            return self.extract_response
        self.compress_calls += 1
        if self.fail_compress:
            raise LLMError("компрессор упал")
        return self.facts

    async def embed(self, texts):
        raise LLMError("no embed")


def _triplet(subject="вася", subject_type="user", predicate="спорил с",
             obj="петя", object_type="user"):
    return {
        "subject": subject,
        "subject_type": subject_type,
        "predicate": predicate,
        "object": obj,
        "object_type": object_type,
    }


async def _save(db, chat_id, text, ts, author="кто-то"):
    return await db.save_smart_message(1, chat_id, text, None, ts, "text", author)


def _row(author_name="вася", text="какое-то сообщение"):
    return {"author_name": author_name, "text": text}


# ── parse_triplets (чистая модульная функция) ────────────────────

class TestParseTriplets:
    def test_valid_array_parsed_and_normalized(self):
        raw = json.dumps(
            [
                _triplet(subject="  ВаСя ", predicate=" Спорил  С "),
                _triplet(subject="тема", subject_type="topic", predicate="связана с",
                         obj="другая тема", object_type="topic"),
            ],
            ensure_ascii=False,
        )
        triplets = parse_triplets(raw)
        assert len(triplets) == 2
        assert triplets[0]["subject"] == "вася"
        assert triplets[0]["predicate"] == "спорил с"
        assert triplets[0]["object"] == "петя"
        assert triplets[1]["subject_type"] == "topic"

    def test_code_fence_wrapper_accepted(self):
        raw = "```json\n" + json.dumps([_triplet()], ensure_ascii=False) + "\n```"
        triplets = parse_triplets(raw)
        assert len(triplets) == 1
        assert triplets[0]["subject"] == "вася"

    def test_broken_json_raises(self):
        with pytest.raises(GraphExtractionError):
            parse_triplets("это не json вообще")

    def test_object_without_list_raises(self):
        with pytest.raises(GraphExtractionError):
            parse_triplets('{"foo": "bar"}')

    def test_object_with_list_field_accepted(self):
        raw = json.dumps({"triplets": [_triplet()]}, ensure_ascii=False)
        triplets = parse_triplets(raw)
        assert len(triplets) == 1

    def test_empty_array(self):
        assert parse_triplets("[]") == []

    def test_broken_items_skipped_good_kept(self, caplog):
        import logging

        raw = json.dumps(
            [
                _triplet(),
                {"no": "keys"},
                "just a string",
                42,
                _triplet(subject_type="event"),                      # event — не в v1 (Q1)
                _triplet(subject="   ", predicate="x", obj="y"),     # пустой subject
                _triplet(subject="вася", predicate="р", obj="вася"),  # self-loop
                _triplet(subject="петя", predicate="оскорбил", obj="дима"),
            ],
            ensure_ascii=False,
        )
        with caplog.at_level(logging.WARNING):
            triplets = parse_triplets(raw)
        assert len(triplets) == 2
        assert triplets[0]["subject"] == "вася"
        assert triplets[1]["predicate"] == "оскорбил"
        assert any("skipped 6" in r.message for r in caplog.records)

    def test_name_caps(self):
        long_name = "а" * 101
        raw = json.dumps(
            [
                _triplet(subject=long_name),
                _triplet(obj=long_name),
                _triplet(predicate="р" * 201),
                _triplet(),
            ],
            ensure_ascii=False,
        )
        triplets = parse_triplets(raw)
        assert len(triplets) == 1
        assert triplets[0]["subject"] == "вася"

    def test_max_triplets_cap(self):
        raw = json.dumps(
            [
                _triplet(subject=f"юзер{i}", obj=f"юзер{i + 1}")
                for i in range(10)
            ],
            ensure_ascii=False,
        )
        mod = replace(settings, GRAPH_EXTRACT_MAX_TRIPLETS=3)
        with patch("services.summary_memory.settings", mod):
            triplets = parse_triplets(raw)
        assert len(triplets) == 3

    def test_normalize_name(self):
        assert _normalize_name("  ВаСя\t\t Пупкин \n") == "вася пупкин"
        assert _normalize_name("") == ""


# ── _extract_and_save_graph / compress_and_purge integration ─────

class TestExtractAndSaveGraph:
    @pytest.mark.asyncio
    async def test_success_saves_nodes_and_edges(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое сообщение", old, author="вася")
        llm = FakeLLM(
            facts="факт",
            extract_response=json.dumps(
                [
                    _triplet(subject="Вася", predicate="спорил с", obj="Петя"),
                    _triplet(subject="ракеты", subject_type="topic",
                             predicate="обсуждались", obj="дроны", object_type="topic"),
                ],
                ensure_ascii=False,
            ),
        )
        memory = MemoryManager(db, llm)
        await memory.compress_and_purge(-100)

        cursor = await db.db.execute(
            "SELECT entity_name, entity_type FROM nodes WHERE chat_id = -100 ORDER BY id"
        )
        nodes = await cursor.fetchall()
        assert [(r["entity_name"], r["entity_type"]) for r in nodes] == [
            ("вася", "user"), ("петя", "user"), ("ракеты", "topic"), ("дроны", "topic"),
        ]
        cursor = await db.db.execute(
            "SELECT source_id, target_id, relation_type, weight FROM edges"
        )
        edges = await cursor.fetchall()
        assert len(edges) == 2
        assert edges[0]["relation_type"] == "спорил с"
        assert edges[0]["weight"] == 1
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 100)
        assert raw == []

    @pytest.mark.asyncio
    async def test_repeated_batches_increment_weight(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое 1", old, author="вася")
        await _save(db, -100, "старое 2", old + 1, author="петя")
        llm = FakeLLM(
            facts="факт",
            extract_response=json.dumps([_triplet()], ensure_ascii=False),
        )
        memory = MemoryManager(db, llm)
        mod = replace(settings, SUMMARY_COMPRESS_BATCH=1)
        with patch("services.summary_memory.settings", mod):
            await memory.compress_and_purge(-100)
        cursor = await db.db.execute("SELECT weight, COUNT(*) AS c FROM edges")
        row = await cursor.fetchone()
        assert row["c"] == 1
        assert row["weight"] == 2

    @pytest.mark.asyncio
    async def test_weight_increment_from_settings(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое", old, author="вася")
        llm = FakeLLM(
            facts="факт",
            extract_response=json.dumps([_triplet()], ensure_ascii=False),
        )
        memory = MemoryManager(db, llm)
        mod = replace(settings, GRAPH_EDGE_WEIGHT_INCREMENT=7)
        with patch("services.summary_memory.settings", mod):
            await memory.compress_and_purge(-100)
        cursor = await db.db.execute("SELECT weight FROM edges")
        row = await cursor.fetchone()
        assert row["weight"] == 7

    @pytest.mark.asyncio
    async def test_empty_array_deletes_batch(self, db):
        """Валидный JSON с 0 триплетов — НЕ ошибка: пачка удаляется (защита от застревания)."""
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое", old, author="вася")
        memory = MemoryManager(db, FakeLLM(facts="факт", extract_response="[]"))
        await memory.compress_and_purge(-100)
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 100)
        assert raw == []
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM nodes")
        row = await cursor.fetchone()
        assert row["c"] == 0

    @pytest.mark.asyncio
    async def test_broken_json_keeps_batch(self, db):
        """GraphExtractionError → пачка НЕ удалена, цикл оборван (D68)."""
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое про войну", old, author="вася")
        memory = MemoryManager(db, FakeLLM(facts="факт", extract_response="каша, не json"))
        await memory.compress_and_purge(-100)
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 100)
        assert [r["text"] for r in raw] == ["старое про войну"]
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM nodes")
        row = await cursor.fetchone()
        assert row["c"] == 0

    @pytest.mark.asyncio
    async def test_llm_error_keeps_batch(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое", old, author="вася")
        memory = MemoryManager(db, FakeLLM(facts="факт", fail_extract=True))
        await memory.compress_and_purge(-100)
        raw = await db.get_smart_raw(-100, int(time.time()) + 1, 100)
        assert len(raw) == 1

    @pytest.mark.asyncio
    async def test_pipeline_alive_after_failure(self, db):
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое", old, author="вася")
        llm = FakeLLM(facts="факт", extract_response="не json", fail_extract=False)
        memory = MemoryManager(db, llm)
        await memory.compress_and_purge(-100)               # упал на парсинге
        assert len(await db.get_smart_raw(-100, int(time.time()) + 1, 100)) == 1
        llm.extract_response = json.dumps([_triplet()], ensure_ascii=False)
        await memory.compress_and_purge(-100)               # следующий прогон работает
        assert await db.get_smart_raw(-100, int(time.time()) + 1, 100) == []
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM edges")
        row = await cursor.fetchone()
        assert row["c"] == 1

    @pytest.mark.asyncio
    async def test_disabled_no_extract_call(self, db):
        """D69: GRAPH_RAG_ENABLED=False → extraction не вызван, старое поведение."""
        old = int(time.time()) - 40 * 86400
        await _save(db, -100, "старое", old, author="вася")
        llm = FakeLLM(facts="факт", extract_response="не json")
        memory = MemoryManager(db, llm)
        mod = replace(settings, GRAPH_RAG_ENABLED=False)
        with patch("services.summary_memory.settings", mod):
            await memory.compress_and_purge(-100)
        assert llm.extract_calls == 0
        assert llm.compress_calls == 1
        assert await db.get_smart_raw(-100, int(time.time()) + 1, 100) == []

    @pytest.mark.asyncio
    async def test_batch_without_captions_skips_extract_llm(self, db):
        """Строки с пустым text исключаются из extraction-текста → LLM не дёргается."""
        batch = [
            {"author_name": "вася", "text": ""},
            {"author_name": "петя", "text": None},
        ]
        llm = FakeLLM()
        memory = MemoryManager(db, llm)
        await memory._extract_and_save_graph(-100, batch)
        assert llm.extract_calls == 0
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM nodes")
        row = await cursor.fetchone()
        assert row["c"] == 0

    @pytest.mark.asyncio
    async def test_extract_uses_tail_of_batch_text(self, db):
        """Хвост ≤ _GRAPH_EXTRACT_MAX_CHARS (самые свежие сообщения)."""
        old = int(time.time()) - 40 * 86400
        batch = [{"author_name": "вася", "text": f"сообщение {i}"} for i in range(3)]
        memory = MemoryManager(db, FakeLLM())
        captured = {}

        async def fake_generate(messages):
            captured["user"] = messages[1]["content"]
            return "[]"

        memory.llm.generate = fake_generate
        await memory._extract_and_save_graph(-100, batch)
        assert captured["user"].endswith("[вася]: сообщение 2")
        assert "[вася]: сообщение 0" in captured["user"]


# ── get_graph_facts (R26-3: детерминированный поиск для /summary) ─

class TestGetGraphFacts:
    @pytest.mark.asyncio
    async def _graph(self, db):
        a = await db.upsert_node(-100, "вася", "user")
        b = await db.upsert_node(-100, "петя", "user")
        c = await db.upsert_node(-100, "дима", "user")
        t = await db.upsert_node(-100, "ракеты", "topic")
        await db.upsert_edge(a, b, "спорил с", weight_increment=4)
        await db.upsert_edge(a, t, "фанатеет от")
        return {"a": a, "b": b, "c": c, "t": t}

    @pytest.mark.asyncio
    async def test_authors_and_top_keywords_match(self, db):
        ids = await self._graph(db)
        memory = MemoryManager(db, FakeLLM())
        facts = await memory.get_graph_facts(
            -100, [_row(author_name="Вася")], ["ракеты", "дрон", "лишний"]
        )
        assert facts == [
            "[Историческая справка: вася (спорил с) петя]",
            "[Историческая справка: вася (фанатеет от) ракеты]",
        ]

    @pytest.mark.asyncio
    async def test_format_exact(self, db):
        ids = await self._graph(db)
        memory = MemoryManager(db, FakeLLM())
        facts = await memory.get_graph_facts(
            -100, [_row(author_name="петя")], ["нет"]
        )
        assert facts == ["[Историческая справка: вася (спорил с) петя]"]
        assert all(f.startswith("[Историческая справка: ") and f.endswith("]")
                   for f in facts)

    @pytest.mark.asyncio
    async def test_entity_scoped_empty_falls_back_chat_wide(self, db):
        """Сущность найдена, но рёбер у неё нет → chat-wide top (35.5)."""
        await self._graph(db)
        memory = MemoryManager(db, FakeLLM())
        facts = await memory.get_graph_facts(-100, [_row(author_name="дима")], [])
        assert facts == [
            "[Историческая справка: вася (спорил с) петя]",
            "[Историческая справка: вася (фанатеет от) ракеты]",
        ]

    @pytest.mark.asyncio
    async def test_no_match_falls_back_chat_wide(self, db):
        """Холодное окно (нет ни одного узла) → chat-wide top."""
        await self._graph(db)
        memory = MemoryManager(db, FakeLLM())
        facts = await memory.get_graph_facts(-100, [_row(author_name="олег")], [])
        assert len(facts) == 2

    @pytest.mark.asyncio
    async def test_limit_respected(self, db):
        await self._graph(db)
        for i in range(10):
            n = await db.upsert_node(-100, f"юзер{i}", "user")
            a = await db.upsert_node(-100, "вася", "user")
            await db.upsert_edge(n, a, f"связь {i}")
        memory = MemoryManager(db, FakeLLM())
        facts = await memory.get_graph_facts(-100, [], [])
        assert len(facts) == settings.GRAPH_TOP_EDGES_LIMIT

    @pytest.mark.asyncio
    async def test_empty_graph_returns_empty(self, db):
        memory = MemoryManager(db, FakeLLM())
        assert await memory.get_graph_facts(-100, [_row()], ["тема"]) == []

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, db):
        memory = MemoryManager(db, FakeLLM())
        mod = replace(settings, GRAPH_RAG_ENABLED=False)
        with patch("services.summary_memory.settings", mod):
            facts = await memory.get_graph_facts(-100, [_row()], ["тема"])
        assert facts == []

    @pytest.mark.asyncio
    async def test_sqlite_error_returns_empty_without_raise(self, db):
        class BrokenDB:
            async def match_nodes(self, *args, **kwargs):
                raise sqlite3.OperationalError("бд сломалась")

        memory = MemoryManager(BrokenDB(), FakeLLM())
        facts = await memory.get_graph_facts(-100, [_row()], ["тема"])
        assert facts == []

    @pytest.mark.asyncio
    async def test_never_raises_on_missing_author_key(self, db):
        memory = MemoryManager(db, FakeLLM())
        facts = await memory.get_graph_facts(-100, [{}], [])
        assert facts == []

    @pytest.mark.asyncio
    async def test_chat_isolation(self, db):
        await self._graph(db)
        memory = MemoryManager(db, FakeLLM())
        assert await memory.get_graph_facts(-200, [_row(author_name="вася")], []) == []
