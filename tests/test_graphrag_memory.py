"""Tests for the GraphRAG memory layer (Epic 26/46, T-201/T-202/T26.2/T26.3/
T-366-A, Sections 35.4/35.5/55.4/55.6)."""
import asyncio
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from config.settings import settings
from services.database import DatabaseService
from services.llm_client import LLMError
from services.summary_memory import (
    FACT_EXTRACT_PROMPT,
    GraphExtractionError,
    MemoryManager,
    _normalize_name,
    build_rag_context,
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
    async def test_direct_reply_entities_excluded_from_summary_graph(self, db):
        """Epic 50 (58.8, R26-3-фильтр): сущности/рёбра origin='bot_direct_reply'
        НЕ попадают в справки /summary (nodes + edges + оба конца)."""
        await self._graph(db)
        d1 = await db.upsert_node(-100, "бот", "user", origin="bot_direct_reply")
        d2 = await db.upsert_node(-100, "пользователь", "user", origin="bot_direct_reply")
        await db.upsert_edge(d1, d2, "болтает с", origin="bot_direct_reply")
        memory = MemoryManager(db, FakeLLM())
        facts = await memory.get_graph_facts(-100, [_row(author_name="вася")], ["ракеты"])
        texts = " ".join(facts)
        assert "болтает с" not in texts
        assert "пользователь" not in texts
        assert "спорил с" in texts                     # легитимные рёбра на месте

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


# ── Epic 46 (Sections 55.4/55.6, T-366-A #8-16) ──────────────────


class FactsLLM:
    """FakeLLM для memorize_facts (55.4): канон-JSON ответ на FACT_EXTRACT_PROMPT."""

    def __init__(self, response="[]", fail_embed=False, embed_vectors=None):
        self.response = response
        self.fail_embed = fail_embed
        self.embed_vectors = embed_vectors
        self.generate_calls = 0
        self.embed_calls = 0
        self.last_user = None

    async def generate(self, messages):
        self.generate_calls += 1
        assert messages[0]["content"] == FACT_EXTRACT_PROMPT
        self.last_user = messages[1]["content"]
        return self.response

    async def embed(self, texts):
        self.embed_calls += 1
        if self.fail_embed:
            raise LLMError("403 эмбеддингов")
        if self.embed_vectors is not None:
            return self.embed_vectors
        return [[0.1] * settings.EMBEDDING_DIM for _ in texts]


def _fact(subject="Ozon", predicate="доставляет быстрее чем", obj="Wildberries",
          context=None):
    item = {"subject": subject, "predicate": predicate, "object": obj}
    if context is not None:
        item["context"] = context
    return item


def _backlog_fact_extract_prompt() -> str:
    """Канон R46-2 из plans/docs/canon/backlog.md
    (якорь «Канон R46-2 — промпт-экстрактор»)."""
    lines = Path("plans/docs/canon/backlog.md").read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines)
        if line.startswith("**Канон R46-2 — промпт-экстрактор")
    )
    fence = next(
        i for i, line in enumerate(lines[start:], start) if line.strip() == "```"
    )
    end = next(
        i for i, line in enumerate(lines[fence + 1:], fence + 1)
        if line.strip() == "```"
    )
    return "\n".join(lines[fence + 1:end])


class TestFactExtractPromptCanon:
    def test_fact_extract_prompt_byte_for_byte(self):
        """#13: FACT_EXTRACT_PROMPT байт-в-байт == backlog канон R46-2."""
        assert FACT_EXTRACT_PROMPT == _backlog_fact_extract_prompt()

    def test_no_format_placeholders_in_canon(self):
        import re

        assert re.findall(r"\{(\w+)\}", FACT_EXTRACT_PROMPT) == []


class TestMemorizeFacts:
    @pytest.mark.asyncio
    async def test_canon_json_writes_nodes_edges_facts_with_ttl(self, db, monkeypatch):
        """#8: канон-JSON → nodes(2, type fact) + edge + graph_facts с
        origin/expires_at; search_fact → now + GRAPH_FACT_TTL_DAYS (fake_time)."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        llm = FactsLLM(response=json.dumps(
            [_fact(context="из-за большего количества складов")], ensure_ascii=False
        ))
        memory = MemoryManager(db, llm)
        await memory.memorize_facts(-100, "Ozon доставляет быстрее Wildberries",
                                    "search_fact")

        cursor = await db.db.execute(
            "SELECT entity_name, entity_type, origin, expires_at FROM nodes ORDER BY id"
        )
        nodes = await cursor.fetchall()
        assert [(r["entity_name"], r["entity_type"], r["origin"]) for r in nodes] == [
            ("ozon", "fact", "search_fact"), ("wildberries", "fact", "search_fact"),
        ]
        # Epic 60 (66.1, T-479): TTL = base × (0.5 + weight); search_fact →
        # вес GRAPH_FACT_WEIGHT_ARCHIVE 0.4 → множитель 0.9.
        expected_expiry = now + int(
            settings.GRAPH_FACT_TTL_DAYS * 86400.0
            * (0.5 + settings.GRAPH_FACT_WEIGHT_ARCHIVE))
        assert all(r["expires_at"] == expected_expiry for r in nodes)

        cursor = await db.db.execute(
            "SELECT relation_type, origin, expires_at FROM edges"
        )
        edges = await cursor.fetchall()
        assert len(edges) == 1
        assert edges[0]["relation_type"] == "доставляет быстрее чем"
        assert edges[0]["origin"] == "search_fact"
        assert edges[0]["expires_at"] == expected_expiry

        cursor = await db.db.execute("SELECT fact, origin, expires_at FROM graph_facts")
        facts = await cursor.fetchall()
        assert len(facts) == 1
        assert facts[0]["fact"] == (
            "ozon доставляет быстрее чем wildberries (из-за большего количества складов)"
        )
        assert facts[0]["origin"] == "search_fact"
        assert facts[0]["expires_at"] == expected_expiry

    @pytest.mark.asyncio
    async def test_chat_history_expiry_null(self, db):
        """#8: chat_history → expires_at NULL (вечно)."""
        llm = FactsLLM(response=json.dumps(
            [_fact(subject="вася", predicate="спорил с", obj="петя")],
            ensure_ascii=False,
        ))
        memory = MemoryManager(db, llm)
        await memory.memorize_facts(-100, "вася спорил с петей", "chat_history")
        cursor = await db.db.execute("SELECT origin, expires_at FROM graph_facts")
        row = await cursor.fetchone()
        assert row["origin"] == "chat_history"
        assert row["expires_at"] is None

    @pytest.mark.asyncio
    async def test_broken_json_quiet_warning_nothing_saved(self, db, caplog):
        """#9: кривой JSON → тихий WARNING, ничего не сохранено, НЕ бросает."""
        import logging

        memory = MemoryManager(db, FactsLLM(response="каша, не json"))
        with caplog.at_level(logging.WARNING):
            await memory.memorize_facts(-100, "текст", "search_fact")
        assert any("not a JSON list" in r.message for r in caplog.records)
        for table in ("nodes", "edges", "graph_facts"):
            cursor = await db.db.execute(f"SELECT COUNT(*) AS c FROM {table}")
            row = await cursor.fetchone()
            assert row["c"] == 0

    @pytest.mark.asyncio
    async def test_empty_array_and_non_json_object_zero_facts(self, db, caplog):
        """#10: пустой массив / не-JSON-объект → 0 фактов, не бросает."""
        import logging

        memory = MemoryManager(db, FactsLLM(response="[]"))
        with caplog.at_level(logging.WARNING):
            await memory.memorize_facts(-100, "текст", "search_fact")
        memory.llm.response = '{"foo": "bar"}'
        with caplog.at_level(logging.WARNING):
            await memory.memorize_facts(-100, "текст", "search_fact")
        assert any("not a JSON list" in r.message for r in caplog.records)
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        row = await cursor.fetchone()
        assert row["c"] == 0

    @pytest.mark.asyncio
    async def test_embed_fail_fact_saved_text_only(self, db, monkeypatch, caplog):
        """#11: embed-фейл → факт сохранён ТЕКСТОМ (graph_facts есть, vec-строк
        0), WARNING «[graphrag] embed failed». НЕ бросает."""
        import logging

        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
        llm = FactsLLM(
            response=json.dumps([_fact(subject="a", predicate="p", obj="b")],
                                ensure_ascii=False),
            fail_embed=True,
        )
        memory = MemoryManager(db, llm)
        memory._vec_available = True
        with caplog.at_level(logging.WARNING):
            await memory.memorize_facts(-100, "текст", "web_content")
        assert any("[graphrag] embed failed" in r.message for r in caplog.records)
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        row = await cursor.fetchone()
        assert row["c"] == 1

    @pytest.mark.asyncio
    async def test_context_caps_selfloop_unknown_source(self, db, caplog):
        """#12: context → «s p o (context)»; капсы имён / subject==object —
        пропуск; unknown source_type — skip с WARNING."""
        import logging

        long_name = "а" * 101
        llm = FactsLLM(response=json.dumps([
            _fact(subject="S", predicate="P", obj="O", context="  ctx  "),
            _fact(subject=long_name, predicate="p", obj="o"),
            _fact(subject="s", predicate="p", obj="s"),
            _fact(subject="ok", predicate="p2", obj="ok2"),
        ], ensure_ascii=False))
        memory = MemoryManager(db, llm)
        await memory.memorize_facts(-100, "текст", "web_content")
        cursor = await db.db.execute("SELECT fact FROM graph_facts")
        facts = [r["fact"] for r in await cursor.fetchall()]
        assert facts == ["s p o (ctx)", "ok p2 ok2"]

        with caplog.at_level(logging.WARNING):
            await memory.memorize_facts(-100, "текст", "banana_source")
        assert any("unknown source_type" in r.message for r in caplog.records)
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        row = await cursor.fetchone()
        assert row["c"] == 2

    @pytest.mark.asyncio
    async def test_disabled_no_llm_call(self, db):
        """GRAPH_RAG_ENABLED=False → memorize_facts — no-op (0 LLM-вызовов)."""
        llm = FactsLLM(response="[]")
        memory = MemoryManager(db, llm)
        mod = replace(settings, GRAPH_RAG_ENABLED=False)
        with patch("services.summary_memory.settings", mod):
            await memory.memorize_facts(-100, "текст", "search_fact")
        assert llm.generate_calls == 0

    @pytest.mark.asyncio
    async def test_extract_uses_tail_max_chars(self, db):
        """Хвост ≤ _FACT_EXTRACT_MAX_CHARS уходит экстрактору."""
        long_text = "слово " * 10_000
        llm = FactsLLM(response="[]")
        memory = MemoryManager(db, llm)
        await memory.memorize_facts(-100, long_text, "web_content")
        assert len(llm.last_user) <= 8000
        assert llm.last_user.endswith("слово")


class TestBuildRagContext:
    def test_canon_structure_byte_for_byte(self):
        """#14: канон 55.6 — два блока, 2-пробельный отступ."""
        facts = [
            ("chat_history", "вася спорил с петей"),
            ("search_fact", "Ozon доставляет быстрее чем Wildberries"),
        ]
        assert build_rag_context(facts) == (
            "<context>\n"
            "  <user_gossip>вася спорил с петей</user_gossip>\n"
            "  <bot_knowledge>[Из твоего прошлого поиска]: Ozon доставляет быстрее чем Wildberries</bot_knowledge>\n"
            "</context>"
        )

    def test_all_canon_prefixes(self):
        facts = [
            ("search_fact", "a"),
            ("youtube_content", "b"),
            ("web_content", "c"),
        ]
        ctx = build_rag_context(facts)
        assert "[Из твоего прошлого поиска]: a" in ctx
        assert "[Из видео, которое кидали ранее]: b" in ctx
        assert "[Из статьи]: c" in ctx

    def test_unknown_origin_without_prefix(self):
        ctx = build_rag_context([("alien_origin", "x")])
        assert "  <bot_knowledge>x</bot_knowledge>" in ctx
        assert "  <user_gossip></user_gossip>" in ctx

    def test_empty_facts_returns_empty_string(self):
        assert build_rag_context([]) == ""

    def test_xml_escape_applied(self):
        ctx = build_rag_context([("chat_history", "a < b & c")])
        assert "a &lt; b &amp; c" in ctx
        assert "< b" not in ctx

    def test_empty_gossip_block_kept(self):
        ctx = build_rag_context([("search_fact", "a")])
        assert "  <user_gossip></user_gossip>" in ctx


class TestGetRagContextDates:
    """Раунд 4 (T-724, AC-F2): get_rag_context возвращает даты (FTS-путь)."""

    @pytest.mark.asyncio
    async def test_rag_context_renders_created_at_date(self, db, monkeypatch):
        """«что было N-числа» — факт в контексте с датой из created_at."""
        fixed = 1716163200   # 2024-05-20 00:00:00 UTC
        monkeypatch.setattr("services.database.time.time", lambda: fixed)
        monkeypatch.setattr("services.summary_memory.time.time", lambda: fixed)
        await db.insert_graph_fact(-100, "озон быстрее чем вб",
                                   "chat_history", None)
        await db.insert_graph_fact(-100, "озон развозит посылки за день",
                                   "search_fact", fixed + 100)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(-100, "озон")
        assert "[2024-05-20] озон быстрее чем вб" in ctx
        # знаниевый факт — дата ПЕРЕД origin-префиксом
        assert "[2024-05-20] [Из твоего прошлого поиска]: " in ctx

    @pytest.mark.asyncio
    async def test_direct_reply_fact_date_rendered_too(self, db, monkeypatch):
        """include_direct_reply — тот же дата-рендер для bot_direct_reply."""
        now = int(time.time())
        monkeypatch.setattr("services.database.time.time", lambda: now)
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        # токен 'погода' присутствует дословно (FTS без стемминга)
        await db.insert_graph_fact(-100, "погода сегодня будет солнечной",
                                   "bot_direct_reply", None)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(
            -100, "погода", include_direct_reply=True)
        expected = time.strftime("[%Y-%m-%d] ", time.gmtime(now))
        assert expected in ctx
        assert "погода сегодня будет солнечной" in ctx


class TestBuildRagContextDates:
    """Раунд 4 (T-724, AC-F1): дата-префиксы '[%Y-%m-%d] ' (UTC) для
    3-кортежей (origin, fact, created_at); legacy-2-кортежи без дат."""

    TS = 1716163200   # 2024-05-20 00:00:00 UTC

    def test_chat_history_date_prefix_inside_user_gossip(self):
        ctx = build_rag_context(
            [("chat_history", "вася спорил с петей", self.TS)])
        assert ctx == (
            "<context>\n"
            "  <user_gossip>[2024-05-20] вася спорил с петей</user_gossip>\n"
            "  <bot_knowledge></bot_knowledge>\n"
            "</context>"
        )

    def test_knowledge_date_before_origin_prefix(self):
        ctx = build_rag_context(
            [("search_fact", "Ozon быстрее чем вб", self.TS)])
        assert ("[2024-05-20] [Из твоего прошлого поиска]: "
                "Ozon быстрее чем вб") in ctx

    def test_web_content_date_before_origin_prefix(self):
        ctx = build_rag_context(
            [("web_content", "текст статьи", self.TS)])
        assert "[2024-05-20] [Из статьи]: текст статьи" in ctx

    def test_zero_and_none_created_at_no_prefix(self):
        for ts in (0, None):
            ctx = build_rag_context([("chat_history", "без даты", ts)])
            assert "  <user_gossip>без даты</user_gossip>" in ctx
            assert "[20" not in ctx

    def test_legacy_two_tuples_still_no_date(self):
        ctx = build_rag_context(
            [("chat_history", "легаси-сплетня"),
             ("search_fact", "легаси-факт")])
        assert "  <user_gossip>легаси-сплетня</user_gossip>" in ctx
        assert "[Из твоего прошлого поиска]: легаси-факт" in ctx
        assert "[2024-" not in ctx

    def test_mixed_two_and_three_tuples(self):
        facts = [
            ("chat_history", "старая запись без даты"),
            ("chat_history", "новая запись с датой", self.TS),
        ]
        ctx = build_rag_context(facts)
        assert "  <user_gossip>старая запись без даты\n" \
               "[2024-05-20] новая запись с датой</user_gossip>" in ctx

    def test_garbage_created_at_no_crash(self):
        ctx = build_rag_context([("chat_history", "мусор", "not-a-number"),
                                 ("chat_history", "норм", self.TS)])
        assert "мусор" in ctx
        assert "[2024-05-20] норм" in ctx

    def test_bot_knowledge_empty_kept_with_dated_gossip(self):
        ctx = build_rag_context(
            [("chat_history", "сплетня", self.TS),
             ("youtube_content", "видеофакт", self.TS)])
        assert "  <user_gossip>[2024-05-20] сплетня</user_gossip>" in ctx
        assert ("  <bot_knowledge>[2024-05-20] [Из видео, которое кидали "
                "ранее]: видеофакт</bot_knowledge>") in ctx


class TestGetRagContext:
    @pytest.mark.asyncio
    async def test_ttl_expired_not_in_context_fts_path(self, db, monkeypatch):
        """#15: ленивый TTL — истёкший факт не попадает в контекст (FTS-путь)."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        await db.insert_graph_fact(-100, "озон быстрее чем вб", "search_fact", now + 100)
        await db.insert_graph_fact(-100, "озон древний факт", "search_fact", now - 100)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(-100, "озон")
        assert "озон быстрее чем вб" in ctx
        assert "древний" not in ctx

    @pytest.mark.asyncio
    async def test_knn_path_ttl_expired_excluded(self, db, monkeypatch):
        """#15: KNN-путь — факт с истёкшим expires_at НЕ в контексте."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        memory = MemoryManager(db, FactsLLM())
        ok = await memory.initialize()
        if not ok:
            pytest.skip("sqlite-vec extension could not be loaded")
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        f1 = await db.insert_graph_fact(-100, "озон быстрее чем вб", "search_fact",
                                        now + 100)
        f2 = await db.insert_graph_fact(-100, "озон устаревший факт", "search_fact",
                                        now - 100)
        await memory._save_graph_fact_embedding(
            f1, -100, "озон быстрее чем вб", "search_fact", now + 100)
        await memory._save_graph_fact_embedding(
            f2, -100, "озон устаревший факт", "search_fact", now - 100)
        ctx = await memory.get_rag_context(-100, "озон")
        assert "озон быстрее чем вб" in ctx
        assert "устаревший" not in ctx

    @pytest.mark.asyncio
    async def test_vec_off_uses_fts(self, db):
        """#16: vec выключен → FTS-фолбек."""
        await db.insert_graph_fact(-100, "ракеты обсуждались вчера", "web_content",
                                   None)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(-100, "ракеты")
        assert "[Из статьи]: ракеты обсуждались вчера" in ctx

    @pytest.mark.asyncio
    async def test_embed_fail_uses_fts(self, db, monkeypatch):
        """#16: embed упал (vec включён) → FTS-фолбек."""
        monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
        await db.insert_graph_fact(-100, "дроны летали низко", "youtube_content", None)
        memory = MemoryManager(db, FactsLLM(fail_embed=True))
        memory._vec_available = True
        ctx = await memory.get_rag_context(-100, "дроны")
        assert "[Из видео, которое кидали ранее]: дроны летали низко" in ctx

    @pytest.mark.asyncio
    async def test_all_paths_empty_returns_empty_string(self, db):
        memory = MemoryManager(db, FactsLLM())
        assert await memory.get_rag_context(-100, "нет такого факта") == ""

    @pytest.mark.asyncio
    async def test_never_raises_on_broken_db(self, db):
        """#16: НИКОГДА не бросает (любая ошибка → "")."""
        class BrokenDB:
            async def search_graph_facts_fts(self, *args, **kwargs):
                raise sqlite3.OperationalError("бд сломалась")

        memory = MemoryManager(BrokenDB(), FactsLLM())
        ctx = await memory.get_rag_context(-100, "запрос")
        assert ctx == ""

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self, db):
        memory = MemoryManager(db, FactsLLM())
        mod = replace(settings, GRAPH_RAG_ENABLED=False)
        with patch("services.summary_memory.settings", mod):
            assert await memory.get_rag_context(-100, "запрос") == ""

    @pytest.mark.asyncio
    async def test_limits_facts_and_chars(self, db, monkeypatch):
        """#14/55.6: лимит 10 фактов; потолок символов контекста."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        for i in range(15):
            await db.insert_graph_fact(-100, f"тема токен {i}", "search_fact", now + 100)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(-100, "тема")
        assert ctx.count("[Из твоего прошлого поиска]:") <= 10
        # потолок: длинные факты обрезаются до GRAPH_RAG_CONTEXT_MAX_CHARS
        for i in range(10):
            await db.insert_graph_fact(
                -100, f"тема токен {i} " + "х" * 200, "web_content", now + 100)
        ctx2 = await memory.get_rag_context(-100, "тема")
        assert len(ctx2) <= settings.GRAPH_RAG_CONTEXT_MAX_CHARS


class TestEpic50RagFlags:
    """Epic 50 (58.8, D206): sort_by_timestamp/include_direct_reply — флаги
    изолированы, дефолт = ровно старое поведение (58.10 #9)."""

    @pytest.mark.asyncio
    async def test_default_sort_keeps_old_behavior(self, db, monkeypatch):
        """sort_by_timestamp=False (default) — порядок по rank/релевантности,
        НЕ по created_at (в FTS-пути ранжирование внутри SQL)."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        for i in range(5):
            await db.insert_graph_fact(-100, f"тема токен {i}", "search_fact", now + 100)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(-100, "тема")
        assert "тема токен" in ctx                  # просто вернулись факты

    @pytest.mark.asyncio
    async def test_sort_by_timestamp_asc(self, db, monkeypatch):
        """sort_by_timestamp=True — факты в таймлайне created_at ASC."""
        clock = {"now": 1_000_000_000}
        monkeypatch.setattr("services.database.time.time", lambda: clock["now"])
        for delta, text in ((300, "поздний факт"), (100, "ранний факт"),
                            (200, "средний факт")):
            clock["now"] = 1_000_000_000 + delta
            await db.insert_graph_fact(-100, text, "chat_history", None)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(
            -100, "факт", sort_by_timestamp=True, include_direct_reply=True)
        assert ctx.index("ранний факт") < ctx.index("средний факт") < ctx.index("поздний факт")

    @pytest.mark.asyncio
    async def test_direct_reply_excluded_by_default(self, db):
        """default include_direct_reply=False: bot_direct_reply НЕ подмешивается
        в чужие пайплайны (FTS-путь)."""
        await db.insert_graph_fact(-100, "бот рассказал секрет", "bot_direct_reply", None)
        await db.insert_graph_fact(-100, "в чате обсуждали секрет", "chat_history", None)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(-100, "секрет")
        assert "бот рассказал секрет" not in ctx
        assert "обсуждали секрет" in ctx

    @pytest.mark.asyncio
    async def test_direct_reply_included_when_flag_set(self, db):
        await db.insert_graph_fact(-100, "бот рассказал секрет", "bot_direct_reply", None)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(
            -100, "секрет", include_direct_reply=True, sort_by_timestamp=True)
        assert "бот рассказал секрет" in ctx


class TestEpic50MemorizeDirectReply:
    """Epic 50 (58.8, D205): memorize с origin='bot_direct_reply' + target_user;
    раунд 3 (3.7/C2): TTL — CHAT_DIRECT_REPLY_TTL_DAYS (кодовый дефолт 30;
    явный 0 = expires_at NULL, вечное)."""

    @pytest.mark.asyncio
    async def test_direct_reply_gets_default_ttl_30_days(self, db, monkeypatch):
        """FR-C2: без .env-оверрайда новое bot_direct_reply-памятование получает
        expires_at ≈ now + 30д × (0.5 + weight) (вес direct 0.7 → ×1.2)."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        llm = FactsLLM(response=json.dumps(
            [_fact(subject="вася", predicate="спросил про", obj="дроны")],
            ensure_ascii=False))
        memory = MemoryManager(db, llm)
        await memory.memorize_facts(-100, "вася: что там с дронами\nбот: дроны летят",
                                    "bot_direct_reply", target_user="вася")
        cursor = await db.db.execute(
            "SELECT origin, expires_at, target_user FROM graph_facts")
        row = await cursor.fetchone()
        assert row["origin"] == "bot_direct_reply"
        assert row["target_user"] == "вася"
        assert row["expires_at"] == now + int(
            30 * 86400.0 * (0.5 + settings.GRAPH_FACT_WEIGHT_DIRECT))

    @pytest.mark.asyncio
    async def test_direct_reply_ttl_zero_is_eternal(self, db, monkeypatch):
        """FR-C2: явный TTL=0 (вечно) уважается — expires_at NULL."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        mod = replace(settings, CHAT_DIRECT_REPLY_TTL_DAYS=0)
        with patch("services.summary_memory.settings", mod):
            llm = FactsLLM(response=json.dumps(
                [_fact(subject="вася", predicate="спросил про", obj="дроны")],
                ensure_ascii=False))
            memory = MemoryManager(db, llm)
            await memory.memorize_facts(-100, "текст", "bot_direct_reply",
                                        target_user="вася")
        cursor = await db.db.execute(
            "SELECT expires_at FROM graph_facts")
        row = await cursor.fetchone()
        assert row["expires_at"] is None

    @pytest.mark.asyncio
    async def test_direct_reply_ttl_when_configured(self, db, monkeypatch):
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        mod = replace(settings, CHAT_DIRECT_REPLY_TTL_DAYS=7)
        with patch("services.summary_memory.settings", mod):
            llm = FactsLLM(response=json.dumps(
                [_fact(subject="вася", predicate="спросил про", obj="дроны")],
                ensure_ascii=False))
            memory = MemoryManager(db, llm)
            await memory.memorize_facts(-100, "текст", "bot_direct_reply",
                                        target_user="вася")
        cursor = await db.db.execute(
            "SELECT expires_at FROM graph_facts")
        row = await cursor.fetchone()
        # Epic 60 (66.1): TTL = base × (0.5 + weight); direct 0.7 → ×1.2.
        assert row["expires_at"] == now + int(
            7 * 86400.0 * (0.5 + settings.GRAPH_FACT_WEIGHT_DIRECT))

    @pytest.mark.asyncio
    async def test_direct_reply_rag_chronology_included(self, db, monkeypatch):
        """DirectChat: get_rag_context с include_direct_reply=True включает
        direct-факты (58.6 <RAG_Memory>)."""
        await db.insert_graph_fact(-100, "бот: дроны летят на запад", "bot_direct_reply",
                                   None, target_user="вася")
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(
            -100, "дроны", include_direct_reply=True, sort_by_timestamp=True)
        assert "дроны летят на запад" in ctx


class TestEpic60Dedup:
    """Epic 60 (64.1/64.2, T-462/T-463): дедуп фактов при записи
    (exact-noop, KNN-пороги ≥0.95/0.85–0.95/<0.85) + антиотравление
    (supersede-инвалидация, журнал, unconfirmed в RAG не выдаётся)."""

    @pytest.mark.asyncio
    async def test_exact_dup_noop_confirms_weight_and_ts(self, db, monkeypatch):
        """64.9 #1: memorize 2× одинаковый текст → 1 строка (noop),
        weight +0.1 (cap 1.0), last_confirmed_at обновлён, status confirmed.
        Epic 60 (66.1): стартовый вес search_fact = GRAPH_FACT_WEIGHT_ARCHIVE
        (0.4); факт рождается подтверждённым (last_confirmed_at = created_at)."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        llm = FactsLLM(response=json.dumps([_fact()], ensure_ascii=False))
        memory = MemoryManager(db, llm)
        await memory.memorize_facts(-100, "текст", "search_fact")
        cursor = await db.db.execute(
            "SELECT weight, last_confirmed_at FROM graph_facts")
        row = await cursor.fetchone()
        assert row["weight"] == settings.GRAPH_FACT_WEIGHT_ARCHIVE
        assert row["last_confirmed_at"] == now       # рождён подтверждённым

        later = now + 500
        monkeypatch.setattr("services.summary_memory.time.time", lambda: later)
        await memory.memorize_facts(-100, "текст", "search_fact")
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1                # НЕ дублируется
        cursor = await db.db.execute(
            "SELECT weight, last_confirmed_at, status FROM graph_facts")
        row = await cursor.fetchone()
        assert row["weight"] == settings.GRAPH_FACT_WEIGHT_ARCHIVE + \
            settings.GRAPH_DEDUP_WEIGHT_BONUS
        assert row["last_confirmed_at"] == later
        assert row["status"] == "confirmed"

        # cap 1.0: вес вплотную к потолку → noop не превышает
        await db.db.execute("UPDATE graph_facts SET weight = 0.97")
        await db.db.commit()
        await memory.memorize_facts(-100, "текст", "search_fact")
        cursor = await db.db.execute("SELECT weight FROM graph_facts")
        assert (await cursor.fetchone())["weight"] == 1.0

    @pytest.mark.asyncio
    async def test_knn_thresholds_canon(self, db, monkeypatch):
        """64.9 #2: мок-KNN — cosine ≥0.95 → noop (+вес); 0.85–0.95 →
        supersede (старый expires_at=now, новый INSERT со supersedes,
        2 строки, журнал); <0.85 → add."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        base_id = await db.insert_graph_fact(
            -100, "озон доставляет быстрее чем wildberries", "search_fact",
            now + 1000, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
        llm = FactsLLM()
        memory = MemoryManager(db, llm)
        memory._vec_available = True
        memory._dedup_knn = AsyncMock(
            return_value=[{"fact_id": base_id, "distance": 0.0}])

        # cosine 0.97 ≥ 0.95 → noop + подтверждение базового
        llm.response = json.dumps([_fact(subject="озон", predicate="дешевле чем",
                                          obj="wildberries")],
                                  ensure_ascii=False)
        await memory.memorize_facts(-100, "текст", "search_fact")
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1
        cursor = await db.db.execute(
            "SELECT weight FROM graph_facts WHERE id = ?", (base_id,))
        assert (await cursor.fetchone())["weight"] == \
            settings.GRAPH_FACT_WEIGHT_ARCHIVE + settings.GRAPH_DEDUP_WEIGHT_BONUS

        # cosine 0.90 ∈ [0.85, 0.95) → supersede
        memory._dedup_knn.return_value = [{"fact_id": base_id, "distance": 0.10}]
        await memory.memorize_facts(-100, "текст", "search_fact")
        cursor = await db.db.execute(
            "SELECT id, fact, status, supersedes, expires_at "
            "FROM graph_facts ORDER BY id")
        rows = await cursor.fetchall()
        assert len(rows) == 2                                      # обе версии хранятся
        old, new = rows[0], rows[1]
        assert old["id"] == base_id
        assert old["expires_at"] == now                            # инвалидирован, НЕ удалён
        assert new["status"] == "unconfirmed"
        assert new["supersedes"] == base_id
        assert new["fact"] == "озон дешевле чем wildberries"
        cursor = await db.db.execute(
            "SELECT fact_before, fact_after, reason FROM graph_fact_compressions")
        log = await cursor.fetchone()
        assert log["reason"] == "supersede"
        assert log["fact_before"] == "озон доставляет быстрее чем wildberries"
        assert log["fact_after"] == "озон дешевле чем wildberries"

        # cosine 0.70 < 0.85 → add (обычная вставка, confirmed)
        memory._dedup_knn.return_value = [{"fact_id": base_id, "distance": 0.30}]
        llm.response = json.dumps([_fact(subject="озон", predicate="тише чем",
                                          obj="wildberries")],
                                  ensure_ascii=False)
        await memory.memorize_facts(-100, "текст", "search_fact")
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 3
        cursor = await db.db.execute(
            "SELECT status FROM graph_facts ORDER BY id DESC LIMIT 1")
        assert (await cursor.fetchone())["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_vec_off_exact_only(self, db):
        """64.9 #3: vec выключен → только точный дубль (семантические пороги
        не применяются — честная деградация)."""
        llm = FactsLLM()
        memory = MemoryManager(db, llm)                 # _vec_available=False
        llm.response = json.dumps([_fact(subject="озон",
                                          predicate="доставляет быстрее чем",
                                          obj="wildberries")],
                                  ensure_ascii=False)
        await memory.memorize_facts(-100, "текст", "search_fact")
        await memory.memorize_facts(-100, "текст", "search_fact")   # exact → noop
        llm.response = json.dumps([_fact(subject="озон", predicate="дешевле чем",
                                          obj="wildberries")],
                                  ensure_ascii=False)
        await memory.memorize_facts(-100, "текст", "search_fact")   # другой → add
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 2

    @pytest.mark.asyncio
    async def test_dedup_error_fact_written_as_before(self, db, monkeypatch, caplog):
        """64.9 #3: ошибка дедуп-проверки → факт пишется как раньше (WARNING)."""
        import logging

        async def boom(*args, **kwargs):
            raise sqlite3.OperationalError("дедуп сломался")

        monkeypatch.setattr(db, "find_graph_fact_exact", boom)
        llm = FactsLLM(response=json.dumps([_fact()], ensure_ascii=False))
        memory = MemoryManager(db, llm)
        with caplog.at_level(logging.WARNING):
            await memory.memorize_facts(-100, "текст", "search_fact")
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1
        assert any("dedup: check failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_dedup_disabled_old_behavior(self, db, monkeypatch):
        """64.1: GRAPH_DEDUP_ENABLED=false → ровно старое поведение (дубли
        пишутся)."""
        llm = FactsLLM(response=json.dumps([_fact()], ensure_ascii=False))
        memory = MemoryManager(db, llm)
        mod = replace(settings, GRAPH_DEDUP_ENABLED=False)
        with patch("services.summary_memory.settings", mod):
            await memory.memorize_facts(-100, "текст", "search_fact")
            await memory.memorize_facts(-100, "текст", "search_fact")
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 2

    @pytest.mark.asyncio
    async def test_unconfirmed_excluded_and_confirmed_on_repeat(self, db, monkeypatch):
        """64.9 #4: unconfirmed в RAG не попадает (и FTS-путь, и vec-выборка
        текстов); повторное появление → exact-noop → confirmed."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        base_id = await db.insert_graph_fact(
            -100, "озон доставляет быстрее чем wildberries", "search_fact",
            now + 1000)
        llm = FactsLLM()
        memory = MemoryManager(db, llm)
        memory._vec_available = True
        memory._dedup_knn = AsyncMock(
            return_value=[{"fact_id": base_id, "distance": 0.10}])
        llm.response = json.dumps([_fact(subject="озон",
                                          predicate="закрыл магазины чем",
                                          obj="wildberries")],
                                  ensure_ascii=False)
        await memory.memorize_facts(-100, "текст", "search_fact")

        cursor = await db.db.execute(
            "SELECT id, status FROM graph_facts ORDER BY id")
        rows = await cursor.fetchall()
        new_id = rows[-1]["id"]
        assert rows[-1]["status"] == "unconfirmed"

        # FTS-путь: unconfirmed не выдаётся
        ctx = await memory.get_rag_context(-100, "закрыл")
        assert "закрыл" not in ctx
        # vec-путь: статус-фильтр при выборке текстов по KNN-id
        assert await db.get_graph_fact_texts([new_id], status="confirmed") == []

        # повторное появление → exact-noop → confirmed → снова в RAG
        await memory.memorize_facts(-100, "текст", "search_fact")
        cursor = await db.db.execute(
            "SELECT status FROM graph_facts WHERE id = ?", (new_id,))
        assert (await cursor.fetchone())["status"] == "confirmed"
        ctx = await memory.get_rag_context(-100, "закрыл")
        assert "закрыл" in ctx


class TestEpic60PhaseD:
    """Epic 60 Фаза D (66.1–66.12, T-479…T-490): веса значимости, time-decay,
    touch (TTL+LRU), квота, MMR, int8+реранк, защита protected от дедупа."""

    @pytest.mark.asyncio
    async def test_weight_ranks_higher_first(self, db, monkeypatch):
        """66.1: RAG-score = similarity × weight — тяжёлый факт выше лёгкого
        (FTS-путь; оба свежие → decay одинаков)."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        await db.insert_graph_fact(-100, "тема ранжирование низкий приоритет",
                                   "search_fact", now + 1000, weight=0.4)
        await db.insert_graph_fact(-100, "тема ранжирование высокий приоритет",
                                   "search_fact", now + 1000, weight=0.9)
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(-100, "ранжирование")
        assert ctx.index("высокий приоритет") < ctx.index("низкий приоритет")

    @pytest.mark.asyncio
    async def test_time_decay_fresh_beats_old_with_floor(self, db, monkeypatch):
        """66.3: w_eff = weight × 0.5^(Δдней/60) от last_confirmed_at;
        floor 0.1 — старый факт не выпадает из ранга полностью."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        half = int(settings.GRAPH_TIME_DECAY_HALF_LIFE_DAYS * 86400)
        f_old = await db.insert_graph_fact(
            -100, "затухание старый факт", "search_fact", now + 1000, weight=0.9)
        f_new = await db.insert_graph_fact(
            -100, "затухание свежий факт", "search_fact", now + 1000, weight=0.5)
        f_ancient = await db.insert_graph_fact(
            -100, "затухание древний факт", "search_fact", now + 1000, weight=0.9)
        await db.db.execute(
            "UPDATE graph_facts SET last_confirmed_at = ? WHERE id = ?",
            (now - half, f_old))
        await db.db.execute(
            "UPDATE graph_facts SET last_confirmed_at = ? WHERE id = ?",
            (now - 10 * 365 * 86400, f_ancient))
        await db.db.commit()
        memory = MemoryManager(db, FactsLLM())
        ctx = await memory.get_rag_context(-100, "затухание")
        # свежий (0.5) выше полураспавшегося (0.45); древний — floor 0.1
        assert ctx.index("свежий факт") < ctx.index("старый факт")
        assert ctx.index("старый факт") < ctx.index("древний факт")

    @pytest.mark.asyncio
    async def test_touch_extends_expiry_with_cap(self, db, monkeypatch):
        """66.5: RAG-hit продлевает expires_at на GRAPH_FACT_TOUCH_EXTEND_DAYS,
        cap — created_at + 2 × базовый TTL; вечные факты не трогаются."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        extend = settings.GRAPH_FACT_TOUCH_EXTEND_DAYS * 86400
        f1 = await db.insert_graph_fact(-100, "тач уникальный живой", "search_fact",
                                        now + 1000)
        await memory_ctx(db, FactsLLM(), "тач")     # RAG-hit → touch
        cursor = await db.db.execute(
            "SELECT expires_at FROM graph_facts WHERE id = ?", (f1,))
        assert (await cursor.fetchone())["expires_at"] == now + 1000 + extend

        # cap: создан 27 дней назад → потолок created + 28 дней.
        f2 = await db.insert_graph_fact(-100, "тач уникальный старый", "search_fact",
                                        now + 1000)
        await db.db.execute(
            "UPDATE graph_facts SET created_at = ?, last_confirmed_at = ? "
            "WHERE id = ?", (now - 27 * 86400, now - 27 * 86400, f2))
        await db.db.commit()
        await memory_ctx(db, FactsLLM(), "тач")
        cursor = await db.db.execute(
            "SELECT expires_at FROM graph_facts WHERE id = ?", (f2,))
        assert (await cursor.fetchone())["expires_at"] == \
            (now - 27 * 86400) + 2 * settings.GRAPH_FACT_TTL_DAYS * 86400

        # вечный (chat_history, expires NULL) — не трогается.
        f3 = await db.insert_graph_fact(-100, "тач уникальный вечный",
                                        "chat_history", None)
        await memory_ctx(db, FactsLLM(), "тач")
        cursor = await db.db.execute(
            "SELECT expires_at FROM graph_facts WHERE id = ?", (f3,))
        assert (await cursor.fetchone())["expires_at"] is None

    @pytest.mark.asyncio
    async def test_touch_disabled_old_behavior(self, db, monkeypatch):
        """66.5: GRAPH_FACT_TOUCH_ENABLED=false → ровно старое поведение."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        mod = replace(settings, GRAPH_FACT_TOUCH_ENABLED=False)
        with patch("services.summary_memory.settings", mod):
            await db.insert_graph_fact(-100, "нотач уникальный", "search_fact",
                                       now + 1000)
            await memory_ctx(db, FactsLLM(), "нотач")
        cursor = await db.db.execute(
            "SELECT expires_at FROM graph_facts")
        assert (await cursor.fetchone())["expires_at"] == now + 1000

    @pytest.mark.asyncio
    async def test_quota_evicts_lightest_oldest(self, db, monkeypatch):
        """66.4: сверх квоты вытесняется самый лёгкий и старый
        (score = weight/(age_days+1)), журнал reason='quota'."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        f_keep = await db.insert_graph_fact(
            -100, "квота вася любит дроны", "bot_direct_reply", None,
            target_user="вася", weight=0.9)
        f_victim = await db.insert_graph_fact(
            -100, "квота вася имел привычку", "bot_direct_reply", None,
            target_user="вася", weight=0.3)
        await db.db.execute(
            "UPDATE graph_facts SET created_at = ? WHERE id = ?",
            (now - 200 * 86400, f_victim))
        await db.db.commit()
        mod = replace(settings, GRAPH_FACTS_PER_USER_QUOTA=2)
        llm = FactsLLM(response=json.dumps([_fact(subject="квота", predicate="вася спросил про",
                                                   obj="погоду сегодня")],
                                          ensure_ascii=False))
        with patch("services.summary_memory.settings", mod):
            memory = MemoryManager(db, llm)
            await memory.memorize_facts(-100, "текст", "bot_direct_reply",
                                        target_user="вася")
        cursor = await db.db.execute(
            "SELECT id FROM graph_facts WHERE target_user = 'вася'")
        ids = {row["id"] for row in await cursor.fetchall()}
        assert ids == {f_keep} | set(ids - {f_victim}) and f_victim not in ids
        assert len(ids) == 2                       # вытеснение сохранило квоту
        cursor = await db.db.execute(
            "SELECT fact_id, reason FROM graph_fact_compressions "
            "WHERE reason = 'quota'")
        log = await cursor.fetchone()
        assert log is not None and log["fact_id"] == f_victim

    @pytest.mark.asyncio
    async def test_quota_protected_never_evicted(self, db, monkeypatch):
        """66.4 × 65.10: защищённый факт — вне кандидатов на вытеснение;
        если все кандидаты защищены — квота мягко превышается."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        f_p = await db.insert_graph_fact(
            -100, "квота вася защищённый факт", "bot_direct_reply", None,
            target_user="вася", weight=0.3)
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (-100, 'вася', 'квота вася защищённый факт', ?)", (now,))
        await db.db.commit()
        mod = replace(settings, GRAPH_FACTS_PER_USER_QUOTA=1)
        llm = FactsLLM(response=json.dumps([_fact(subject="квота", predicate="вася новый про",
                                                   obj="скейт")],
                                          ensure_ascii=False))
        with patch("services.summary_memory.settings", mod):
            memory = MemoryManager(db, llm)
            await memory.memorize_facts(-100, "текст", "bot_direct_reply",
                                        target_user="вася")
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE target_user = 'вася'")
        assert (await cursor.fetchone())["c"] == 2   # защищённый пережил

    @pytest.mark.asyncio
    async def test_quota_disabled_unlimited(self, db, monkeypatch):
        """66.4: GRAPH_USER_QUOTA_ENABLED=false / квота 0 → без лимита."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        for i in range(3):
            await db.insert_graph_fact(
                -100, f"бесквота вася факт номер {i}", "bot_direct_reply", None,
                target_user="вася")
        mod = replace(settings, GRAPH_USER_QUOTA_ENABLED=False,
                      GRAPH_FACTS_PER_USER_QUOTA=2)
        llm = FactsLLM(response=json.dumps([_fact(subject="бесквота", predicate="вася ещё про",
                                                   obj="самокат")],
                                          ensure_ascii=False))
        with patch("services.summary_memory.settings", mod):
            memory = MemoryManager(db, llm)
            await memory.memorize_facts(-100, "текст", "bot_direct_reply",
                                        target_user="вася")
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE target_user = 'вася'")
        assert (await cursor.fetchone())["c"] == 4

    @pytest.mark.asyncio
    async def test_mmr_duplicates_do_not_fill_topk(self, db, monkeypatch):
        """66.8: greedy MMR λ=0.6 — дубли-близнецы не занимают весь top-K;
        диверсификация по float-векторам."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        f1 = await db.insert_graph_fact(-100, "ммр озон быстрее чем вб", "search_fact", None)
        f2 = await db.insert_graph_fact(-100, "ммр озон быстрее чем вб точно", "search_fact", None)
        f3 = await db.insert_graph_fact(-100, "ммр лето было жарким год", "search_fact", None)
        memory = MemoryManager(db, FactsLLM())
        memory._vec_available = True
        v1 = [1.0, 0.0]
        v3 = [0.0, 1.0]
        memory._vec_candidates = AsyncMock(return_value=[
            (f1, 0.99, list(v1)),
            (f2, 0.98, list(v1)),                  # близнец f1
            (f3, 0.60, list(v3)),
        ])
        rows = await memory._knn_graph_facts(-100, list(v1), 2)
        facts = [fact for _, fact, _ in rows]
        assert len(facts) == 2
        assert any("быстрее" in fact for fact in facts)
        assert any("жарким" in fact for fact in facts)      # разнообразие

    @pytest.mark.asyncio
    async def test_mmr_disabled_topk_by_relevance(self, db, monkeypatch):
        """66.8: GRAPH_MMR_ENABLED=false → ровно top-k по rel (дубли наверху)."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        f1 = await db.insert_graph_fact(-100, "ммр выкл озон быстрее", "search_fact", None)
        f2 = await db.insert_graph_fact(-100, "ммр выкл озон быстрее два", "search_fact", None)
        memory = MemoryManager(db, FactsLLM())
        memory._vec_available = True
        v1 = [1.0, 0.0]
        memory._vec_candidates = AsyncMock(return_value=[
            (f1, 0.99, list(v1)), (f2, 0.98, list(v1))])
        rows = await memory._knn_graph_facts(-100, list(v1), 2)
        assert [fact for _, fact, _ in rows][0].endswith("быстрее")

    @pytest.mark.asyncio
    async def test_int8_schema_two_pass_and_rerank(self, db):
        """66.6: vec-таблицы с embedding_i8; вставка в обе колонки; KNN по
        int8 → реранк float — факты находятся."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        memory = MemoryManager(db, FactsLLM())
        ok = await memory.initialize()
        if not ok:
            pytest.skip("sqlite-vec extension could not be loaded")
        assert memory._vec_int8 is True
        for table in ("smart_archive", "graph_facts_vec"):
            cursor = await db.db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,))
            assert "embedding_i8" in (await cursor.fetchone())["sql"]
        fid = await db.insert_graph_fact(
            -100, "инт8 озон доставляет быстрее", "search_fact", None)
        await memory._save_graph_fact_embedding(fid, -100, "инт8 озон доставляет быстрее",
                                                "search_fact", None)
        cursor = await db.db.execute(
            "SELECT embedding_i8 FROM graph_facts_vec WHERE rowid = ?", (fid,))
        blob = (await cursor.fetchone())["embedding_i8"]
        assert blob is not None and len(bytes(blob)) > 0
        ctx = await memory.get_rag_context(-100, "озон доставляет")
        assert "инт8 озон доставляет быстрее" in ctx

    @pytest.mark.asyncio
    async def test_int8_match_error_falls_back_to_float(
            self, db, monkeypatch, caplog):
        """T-505: исключение MATCH по int8-колонке (except-ветка
        _vec_int8_rows) → гарантированный переход float-path с корректным
        результатом + WARNING."""
        import logging
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        memory = MemoryManager(db, FactsLLM())
        ok = await memory.initialize()
        if not ok:
            pytest.skip("sqlite-vec extension could not be loaded")
        assert memory._vec_int8 is True
        fid = await db.insert_graph_fact(
            -100, "фолбэк озон доставляет быстро", "search_fact", None)
        await memory._save_graph_fact_embedding(
            fid, -100, "фолбэк озон доставляет быстро", "search_fact", None)

        original = db.db.execute

        async def broken_i8(query, params=None):
            if "embedding_i8" in str(query):
                raise sqlite3.OperationalError(
                    "unable to use function MATCH in the requested context")
            return await original(query, params)

        monkeypatch.setattr(db.db, "execute", broken_i8)
        with caplog.at_level(logging.WARNING):
            ctx = await memory.get_rag_context(-100, "озон доставляет")
        assert any("int8 KNN failed" in r.message for r in caplog.records)
        # float-path вернул корректный результат несмотря на смерть int8
        assert "фолбэк озон доставляет быстро" in ctx

    @pytest.mark.asyncio
    async def test_int8_rebuild_from_float_only_table(self, db):
        """66.6: существующая float-only таблица (Фаза B) → DROP+пересоздание
        при старте; backfill восстанавливает векторы ИЗ КЭША (без API)."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        first = MemoryManager(db, FactsLLM(embed_vectors=[[0.1] * settings.EMBEDDING_DIM]))
        if not await first.initialize():
            pytest.skip("sqlite-vec extension could not be loaded")
        fid = await db.insert_graph_fact(
            -100, "ребилд озон вечный факт", "chat_history", None)
        await first._save_graph_fact_embedding(
            fid, -100, "ребилд озон вечный факт", "chat_history", None)
        # Симулируем схему Фазы B: пересоздаём graph_facts_vec БЕЗ i8-колонки.
        await db.db.execute("DROP TABLE graph_facts_vec")
        from services.summary_memory import _GRAPH_VEC_TABLE_SQL
        await db.db.execute(_GRAPH_VEC_TABLE_SQL.format(dim=settings.EMBEDDING_DIM))
        await db.db.commit()

        second = MemoryManager(db, FactsLLM(embed_vectors=[[0.1] * settings.EMBEDDING_DIM]))
        ok = await second.initialize()
        assert ok is True and second._vec_int8 is True
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts_vec")
        # initialize уже запустил фоновый backfill (fire_and_forget) — ждём
        # восстановления строки из кэша и проверяем i8-колонку.
        for _ in range(50):
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM graph_facts_vec")
            if (await cursor.fetchone())["c"] == 1:
                break
            await asyncio.sleep(0.02)
        cursor = await db.db.execute(
            "SELECT embedding_i8 FROM graph_facts_vec WHERE rowid = ?", (fid,))
        assert (await cursor.fetchone())["embedding_i8"] is not None

    @pytest.mark.asyncio
    async def test_vec_int8_disabled_float_only(self, db):
        """66.6: VEC_INT8_ENABLED=false → float-only схема (без i8-колонки)."""
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            pytest.skip("sqlite-vec not installed")
        mod = replace(settings, VEC_INT8_ENABLED=False)
        with patch("services.summary_memory.settings", mod):
            memory = MemoryManager(db, FactsLLM())
            ok = await memory.initialize()
            if not ok:
                pytest.skip("sqlite-vec extension could not be loaded")
            assert memory._vec_int8 is False
            cursor = await db.db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts_vec'")
            assert "embedding_i8" not in (await cursor.fetchone())["sql"]

    @pytest.mark.asyncio
    async def test_protected_fact_not_superseded_or_confirmed(self, db, monkeypatch):
        """65.10/66.10 (T-488): дедуп НЕ трогает защищённый факт — ни noop-
        подтверждение, ни supersede-инвалидацию; пишется как новый."""
        now = 1_800_000_000
        monkeypatch.setattr("services.summary_memory.time.time", lambda: now)
        base_text = "щит озон доставляет быстрее чем wildberries"
        base_id = await db.insert_graph_fact(
            -100, base_text, "search_fact", now + 1000)
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (-100, 'ozon', ?, ?)", (base_text, now))
        await db.db.commit()
        llm = FactsLLM(response=json.dumps([_fact()], ensure_ascii=False))
        memory = MemoryManager(db, llm)
        await memory.memorize_facts(-100, "текст", "search_fact")   # exact-дубль защищён
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 2         # написан НОВЫМ, не noop
        cursor = await db.db.execute(
            "SELECT weight, expires_at FROM graph_facts WHERE id = ?", (base_id,))
        row = await cursor.fetchone()
        assert row["weight"] == 0.5                       # прямая вставка: дефолт, не подтверждён
        assert row["expires_at"] == now + 1000              # не инвалидирован

    @pytest.mark.asyncio
    async def test_edge_decay_ranks_fresh_first(self, db, monkeypatch):
        """66.3: рёбра — w_eff от last_updated; свежая связь выше давней
        (SQL не меняем — пересортировка в Python)."""
        a = await db.upsert_node(-100, "вася", "user")
        b = await db.upsert_node(-100, "ракеты", "topic")
        c = await db.upsert_node(-100, "луна", "topic")
        stale = await db.upsert_edge(a, b, "фанатеет от")
        fresh = await db.upsert_edge(a, c, "любит")
        await db.db.execute(
            "UPDATE edges SET last_updated = '2020-01-01 00:00:00' WHERE id = ?",
            (stale,))
        await db.db.commit()
        memory = MemoryManager(db, FakeLLM())
        facts = await memory.get_graph_facts(-100, [], [])
        texts = " ".join(facts)
        assert texts.index("(любит)") < texts.index("(фанатеет от)")


async def memory_ctx(db, llm, query):
    """Хелпер: get_rag_context на свежем MemoryManager (FTS-путь)."""
    return await MemoryManager(db, llm).get_rag_context(-100, query)


class TestCanonP20Guards:
    """67.1 (T-491, правило п.20, D243/D249): токсичные фразы-ошибки (пулы
    фраз) НИКОГДА не передаются в memorize_facts ни одним fire_and_forget-
    хуком. Статический страж по образцу канон-тестов R46-2 — БЕЗ изменения
    поведения."""

    REPO_ROOT = Path(__file__).resolve().parents[1]

    def _iter_sources(self):
        for folder in ("services", "handlers"):
            for path in sorted((self.REPO_ROOT / folder).glob("*.py")):
                yield path
        yield self.REPO_ROOT / "bot.py"

    def _pool_values(self):
        import services.smartmodule_phrases as phrases_mod
        values = set()
        for name in dir(phrases_mod):
            if not name.isupper():
                continue
            pool = getattr(phrases_mod, name)
            if isinstance(pool, tuple):
                values.update(s for s in pool if isinstance(s, str))
        return values

    def test_phrase_pools_never_reach_memorize_facts(self):
        import ast

        pools = self._pool_values()
        assert pools, "пулы фраз не найдены — страж потерял смысл"
        violations = []
        for path in self._iter_sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name != "memorize_facts":
                    continue
                args = list(node.args) + [kw.value for kw in node.keywords]
                for arg in args:
                    if (isinstance(arg, ast.Constant)
                            and isinstance(arg.value, str)
                            and arg.value in pools):
                        violations.append(f"{path.name}: literal from phrase pool")
        assert not violations, violations

    def test_pools_actually_cover_canon_sets(self):
        """Санити: канонические пулы п.20 действительно в скане."""
        from services.smartmodule_phrases import (
            CHAT_COOLDOWN_PHRASES,
            CHAT_ERROR_PHRASES,
            CHAT_LLM_DOWN_PHRASES,
            CHECKUP_LLM_ERROR_PHRASES,
        )
        pools = self._pool_values()
        for phrase in (CHAT_ERROR_PHRASES + CHAT_COOLDOWN_PHRASES
                       + CHAT_LLM_DOWN_PHRASES + CHECKUP_LLM_ERROR_PHRASES):
            assert phrase in pools
