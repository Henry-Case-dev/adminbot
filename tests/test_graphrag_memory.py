"""Tests for the GraphRAG memory layer (Epic 26/46, T-201/T-202/T26.2/T26.3/
T-366-A, Sections 35.4/35.5/55.4/55.6)."""
import asyncio
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

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
    """Канон R46-2 из backlog (якорь «Канон R46-2 — промпт-экстрактор»)."""
    lines = Path("plans/backlog.md").read_text(encoding="utf-8").splitlines()
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
        expected_expiry = now + settings.GRAPH_FACT_TTL_DAYS * 86400
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
    TTL — CHAT_DIRECT_REPLY_TTL_DAYS (пусто → expires_at NULL)."""

    @pytest.mark.asyncio
    async def test_direct_reply_writes_metadata_and_no_ttl_by_default(self, db, monkeypatch):
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
        assert row["expires_at"] is None          # TTL пусто → вечное (по ТЗ)

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
        assert row["expires_at"] == now + 7 * 86400

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
