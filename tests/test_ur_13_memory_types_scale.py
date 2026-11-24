"""UR-13 memory types/scale proof: KIND taxonomy, claim gate, paging, identity.

Строки UR-13/13.1/13.4/13.8/UR-BAN-03 остаются PENDING до review.
"""
from types import SimpleNamespace

import pytest

from services import claim_envelope as ce
from services import direct_context_composer as comp
from services import evidence_policy
from services import mca_gates
from services import mca_retrieval_context as rc
from services.database import DatabaseService
from services.summary_memory import MemoryManager

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]

CHAT = -100777
BOT_UID = 999000


def _row(user_id: int, text: str, *, tg: int, ts: int) -> dict:
    return {
        "id": tg, "tg_message_id": tg, "user_id": user_id,
        "author_name": f"user-{user_id}", "text": text, "timestamp": ts,
        "media_type": "text", "reply_to_id": None,
    }


# ── UR-13: KIND taxonomy + claim_envelope gate ─────────────────────────────

def test_kind_taxonomy_distinguishes_authority_classes():
    assert comp.FRAGMENT_KINDS == {
        comp.KIND_USER_STATEMENT, comp.KIND_CHAT_EVENT,
        comp.KIND_BOT_STATEMENT, comp.KIND_SUMMARY_INFERENCE,
        comp.KIND_EXTERNAL_EVIDENCE,
    }
    assert len(comp.FRAGMENT_KINDS) == 5
    assert comp.fragment_kind("joke") == comp.KIND_CHAT_EVENT
    assert comp.fragment_kind("roleplay") == comp.KIND_CHAT_EVENT
    assert comp.fragment_kind(comp.KIND_BOT_STATEMENT) \
        == comp.KIND_BOT_STATEMENT

    user = comp.row_to_fragment(
        _row(42, "я устал", tg=1, ts=10), role=comp.ROLE_FRESH_NEIGHBOUR,
        bot_user_id=BOT_UID)
    bot = comp.row_to_fragment(
        _row(BOT_UID, "я тоже", tg=2, ts=11),
        role=comp.ROLE_FRESH_NEIGHBOUR, bot_user_id=BOT_UID)
    assert user.kind == comp.KIND_USER_STATEMENT
    assert user.authority == comp.AUTHORITY_PRIMARY
    assert bot.kind == comp.KIND_BOT_STATEMENT
    assert bot.authority == comp.AUTHORITY_SUPPORTING

    external = comp.ContextFragment(
        kind=comp.KIND_EXTERNAL_EVIDENCE, source_id="fact:1", text="источник",
        speaker_uid=None, authority=comp.AUTHORITY_PRIMARY)
    summary = comp.ContextFragment(
        kind=comp.KIND_SUMMARY_INFERENCE, source_id="summary:1",
        text="пересказ", authority=comp.AUTHORITY_BACKGROUND)
    assert user.authority == comp.AUTHORITY_PRIMARY
    assert external.authority == comp.AUTHORITY_PRIMARY
    assert summary.authority == comp.AUTHORITY_BACKGROUND
    assert bot.authority == comp.AUTHORITY_SUPPORTING


def test_claim_envelope_gates_joke_roleplay_question_hypothesis():
    gated = {
        "шучу, я президент": "joke_candidate",
        "это ролевая игра, я король": "hypothesis",
        "представь, что я космонавт": "hypothesis",
        "кто я?": "question",
        "может быть, я врач": "hypothesis",
    }
    for text, act in gated.items():
        env = ce.build_envelope(
            speaker_entity_id=1, subject_entity_id=1, claim_text=text,
            attribution_method="self_report")
        assert env.speech_act == act, text
        outcome, reason = ce.validate_personal_write(env)
        assert outcome == ce.OUTCOME_REJECTED, text
        assert reason == f"gated_speech_act:{act}"

    # bot_statement — finding о разговоре, не факт о мире и не trait.
    assert ce.classify_finding_kind(
        "я отвечал по делу", is_bot_author=True) == ce.FINDING_KIND_BOT_STATEMENT
    assert ce.stable_trait_claim_allowed(
        ce.FINDING_KIND_BOT_STATEMENT, 5) is False
    # user_statement/chat_event/summary_inference/external_evidence различны.
    kinds = {ce.FINDING_KIND_PARTICIPANT_CLAIM, ce.FINDING_KIND_BRIEF_EVENT,
             ce.FINDING_KIND_EXTERNAL_NEWS, comp.KIND_SUMMARY_INFERENCE}
    assert len(kinds) == 4


def test_claim_gate_does_not_overblock_legitimate_first_person_facts():
    literal = (
        "я играю в ролевые игры по выходным",
        "представь себе, я купил машину",
        "у меня голос как будто простужен",
        "это ролевая игра, которую мы купили вчера",
        "я словно на иголках",
        "представь, я вчера поймал щуку",
        "представь, я купил машину",
        "представь, я нашёл работу",
        "представь, я уже сделал",
        "мы сыграем в ролевую игру в субботу",
        "мы поиграем в ролевую игру",
    )
    for text in literal:
        assert not ce.is_deny_phrase(text)
        assert ce.classify_speech_act(text) == ce.SPEECH_ACT_ASSERT, text
        assert ce.gate_personal_text_write(text)[0] == ce.OUTCOME_ACCEPTED
    pure_roleplay = (
        "представь, что я космонавт",
        "представь себе, что я космонавт",
        "представьте себе, что я король",
        "представь, я космонавт",
        "представь, я король",
        "представь, я генерал",
        "представь, я адмирал",
        "представь, я маршал",
        "представь, я капрал",
        "представь, я акула",
        "представь, я на Марсе",
        "представь, я буду космонавтом",
        "представь: что я космонавт",
        "представь-ка, что я космонавт",
        "представь-ка, я космонавт",
        "я как будто космонавт",
        "я как-будто космонавт",
        "это ролевая игра, я король",
        "ролевая игра: я король",
        "в ролевой игре я король",
        "давай поиграем в ролевую игру",
        "поиграем в ролевую игру",
        "давай сыграем в ролевую игру",
        "сыграем в ролевую игру",
    )
    for text in pure_roleplay:
        assert ce.classify_speech_act(text) == ce.SPEECH_ACT_HYPOTHESIS, text
        assert ce.gate_personal_text_write(text)[0] == ce.OUTCOME_REJECTED


@pytest.mark.asyncio
async def test_remember_user_fact_saves_literal_facts_real_sqlite():
    """B1 positive control: real SQLite store сохраняет literal facts."""
    db = DatabaseService(":memory:")
    await db.initialize()
    try:
        mem = MemoryManager(db, llm=None)
        for fact in ("я играю в ролевые игры по выходным",
                     "представь себе, я купил машину",
                     "у меня голос как будто простужен",
                     "это ролевая игра, которую мы купили вчера",
                     "я словно на иголках",
                     "представь, я вчера поймал щуку",
                     "представь, я купил машину",
                     "представь, я нашёл работу",
                     "представь, я уже сделал",
                     "мы сыграем в ролевую игру в субботу",
                     "мы поиграем в ролевую игру"):
            assert await mem.remember_user_fact(
                CHAT, fact, target_user="Вася", ttl_days=0) == "saved", fact
        for fact in ("это ролевая игра, я король",
                     "представь, я генерал",
                     "представь, я адмирал",
                     "представь, я маршал",
                     "представь, я капрал",
                     "представь, я акула"):
            assert await mem.remember_user_fact(
                CHAT, fact, target_user="Вася", ttl_days=0) == "skipped_gated", fact
    finally:
        await db.close()


def test_joke_and_retell_precedence_over_roleplay_frame():
    joke = ce.build_speech_understanding("я как будто космонавт))")
    assert joke.speech_act == ce.SPEECH_ACT_JOKE_CANDIDATE
    assert joke.humor_risk is True
    assert joke.active is True

    retell = ce.build_speech_understanding("говорят, как будто я уехал")
    assert retell.speech_act == ce.SPEECH_ACT_RETELL
    assert retell.humor_risk is False
    assert evidence_policy.is_attributed_speech(
        "говорят, как будто я уехал") is True
    assert "act:retell" in retell.flags


def test_identity_keeps_speaker_and_dedups_by_source_id():
    target = comp.row_to_fragment(
        _row(42, "близкая реплика", tg=10, ts=100),
        role=comp.ROLE_FRESH_NEIGHBOUR, bot_user_id=BOT_UID)
    other = comp.row_to_fragment(
        _row(43, "близкая реплика", tg=11, ts=101),
        role=comp.ROLE_FRESH_NEIGHBOUR, bot_user_id=BOT_UID)
    assert target.source_id == "msg:10"
    assert other.source_id == "msg:11"
    assert target.speaker_uid == 42
    assert other.speaker_uid == 43
    selection = comp.build_context_selection(
        current_text="вопрос", fresh_neighbours=(target, other),
        budget_tokens=10_000)
    speakers = {f.speaker_uid for f in selection.fresh_neighbours}
    assert speakers == {42, 43}

    first = comp.ContextFragment(
        kind=comp.KIND_USER_STATEMENT, source_id="msg:10", text="цель",
        speaker_uid=42, tg_message_id=10)
    duplicate = comp.ContextFragment(
        kind=comp.KIND_USER_STATEMENT, source_id="msg:10",
        text="чужая близкая", speaker_uid=43, tg_message_id=10)
    out, duplicates = comp._dedup_fragments([[first, duplicate]])
    assert duplicates == 1
    assert len(out) == 1
    assert out[0].speaker_uid == 42
    assert out[0].text == "цель"


# ── UR-13.8/UR-BAN-03: ≥20k seed, bounded reads/paging 500, old retrieval ──

class _TracingConn:
    def __init__(self, real):
        self.real = real
        self.calls: list = []

    async def execute(self, sql, params=()):
        self.calls.append((str(sql), tuple(params or ())))
        return await self.real.execute(sql, params)


@pytest.mark.asyncio
async def test_large_seed_bounded_paging_and_old_retrieval():
    db = DatabaseService(":memory:")
    await db.initialize()
    try:
        rows = [(CHAT, 10, f"реплика номер {i}", i, 20_000 + i)
                for i in range(1, 20_001)]
        await db.db.executemany(
            "INSERT INTO smart_messages (chat_id, user_id, text, timestamp, "
            "tg_message_id) VALUES (?, ?, ?, ?, ?)", rows)
        await db.db.execute(
            "UPDATE smart_messages SET text = ? WHERE id = 1",
            ("СТАРЫЙМАРКЕР UR13",))
        await db.db.execute(
            "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
            (1, "СТАРЫЙМАРКЕР UR13"))
        await db.db.commit()

        tracing = _TracingConn(db.db)
        db.db = tracing
        try:
            recent = await db.get_recent_messages(CHAT, 2000)
            window = await db.get_smart_window(CHAT, 0, 500)
            long_rows = await MemoryManager(db, None).search_long_term(
                CHAT, ["СТАРЫЙМАРКЕР"], 5)
        finally:
            db.db = tracing.real
        assert len(recent) == 2000
        assert recent[0]["timestamp"] == 18_001
        assert recent[-1]["timestamp"] == 20_000
        assert len(window) == 500
        assert window[0]["timestamp"] == 19_501
        assert window[-1]["timestamp"] == 20_000
        assert long_rows
        assert any(int(row["id"]) == 1 for row in long_rows)
        page_params = [params[-1] for sql, params in tracing.calls
                       if "LIMIT ?" in sql]
        assert len(page_params) >= 5, tracing.calls
        assert max(page_params) <= 500, page_params
        assert 20_000 not in page_params
        assert 5 in page_params
        smart_reads = [(sql, params) for sql, params in tracing.calls
                       if "FROM smart_messages" in sql]
        assert smart_reads
        assert all("LIMIT" in sql for sql, _params in smart_reads)
        assert max(int(params[-1]) for _sql, params in smart_reads
                   if "LIMIT ?" in _sql) == 500

        # retrieval находит сообщение старше окна последних 2000.
        found = await db.search_messages_fts(
            CHAT, "СТАРЫЙМАРКЕР", 5)
        assert found
        assert any(int(row["id"]) == 1 for row in found)
    finally:
        await db.close()


# ── UR-13: real SQLite retrieval channels (messages/graph/lore/vector) ────

@pytest.mark.asyncio
async def test_real_sqlite_retrieval_channels_and_sources(monkeypatch):
    """UR-13: реальный retrieve читает SQLite graph/lore/lexical каналы."""
    db = DatabaseService(":memory:")
    await db.initialize()
    try:
        await db.save_smart_message(
            user_id=42, chat_id=CHAT,
            text="ZXOLDMESSAGE архивная реплика о бюджете",
            reply_to_id=None, timestamp=1_000, media_type="text",
            author_name="Вася", message_id=100)
        fact_id = await db.insert_graph_fact(
            CHAT, "ZXGRAPHFACT бюджет проекта 348 тысяч",
            "chat_history", None, subject_ref_id=42, target_user="42",
            speaker_author_id=42, tg_message_id=100,
            message_timestamp=1_000)
        assert fact_id > 0
        await db.upsert_lore_story(
            CHAT, "zx-lore", "ZXLORETOPIC", "ZXLORESTORY старая сюжетная линия",
            last_ts=1_000)
        stored = await db.list_lore_stories(CHAT, limit=10)
        assert any("ZXLORETOPIC" in str(row["topic"]) for row in stored)

        # Реальный legacy-путь lore_stories (facade OFF), без сети/LLM.
        monkeypatch.setattr(mca_gates, "episodes_enabled", lambda: True)
        monkeypatch.setattr(
            mca_gates, "episodes_compiler_facade_enabled", lambda: False)
        mem = MemoryManager(db, None)
        async def _no_vec() -> bool:
            return False
        # Сетевой embedding-edge не дергается; FTS-канал реальный.
        monkeypatch.setattr(mem, "_ensure_vec_retry", _no_vec)
        request = rc.RetrievalRequest(
            chat_id=CHAT,
            query="ZXOLDMESSAGE ZXGRAPHFACT ZXLORETOPIC",
            channels=("lexical", "vector", "episode"), top_k=10)
        result = await rc.retrieve(db, mem, request)
        assert result.status == rc.RETRIEVAL_OK, result
        assert {"lexical", "vector", "episode"} <= set(result.channels_used), \
            result.channels_used
        assert result.chat_ids == (CHAT,)
        assert len(result.candidates) <= request.top_k

        lexical_messages = [c for c in result.candidates
                            if c.channel == "lexical"
                            and c.entity_type == "message"]
        graph_facts = [c for c in result.candidates
                       if c.entity_type == "graph_fact"]
        episodes = [c for c in result.candidates
                    if c.channel == "episode"]
        assert any("ZXOLDMESSAGE" in c.preview for c in lexical_messages)
        assert any("ZXGRAPHFACT" in c.preview for c in graph_facts)
        assert any("ZXLORETOPIC" in c.preview for c in episodes)
        for candidate in result.candidates:
            assert candidate.id
            # SQL-выборка scoped по chat_id; у части graph_fact-строк поле
            # chat_id не возвращается, поэтому чужой чат здесь недопустим.
            assert candidate.chat_id in (None, CHAT)
            assert candidate.sent_at >= 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_vector_search_fts_fallback_old_and_bounded(monkeypatch):
    """UR-13: _vec_available=False → FTS fallback старого archive fact."""
    db = DatabaseService(":memory:")
    await db.initialize()
    try:
        await db.save_archive_fact(
            CHAT, "ZXARCHIVEOLD сжатый старый факт о встрече", 1_000)
        mem = MemoryManager(db, None)
        assert mem._vec_available is False
        async def _no_vec() -> bool:
            return False
        monkeypatch.setattr(mem, "_ensure_vec_retry", _no_vec)
        tracing = _TracingConn(db.db)
        db.db = tracing
        try:
            facts = await mem.vector_search(CHAT, "ZXARCHIVEOLD", 5)
        finally:
            db.db = tracing.real
        assert facts
        assert any("ZXARCHIVEOLD" in str(fact) for fact in facts)
        archive_calls = [(sql, params) for sql, params in tracing.calls
                         if "smart_archive_facts" in sql]
        assert archive_calls
        assert all("LIMIT" in sql for sql, _params in archive_calls)
        assert max(int(params[-1]) for _sql, params in archive_calls) <= 5
    finally:
        await db.close()


def test_pg_is_companion_not_memory_backend():
    """UR-13: PG DDL не является вторым memory-backend."""
    import inspect
    from services import pg_db

    source = inspect.getsource(pg_db)
    for table in ("smart_messages", "graph_facts", "lore_stories",
                  "mca_retrieval_context"):
        assert table not in source, table


def test_existing_storage_and_provider_modules_are_preserved():
    """UR-13 не вводит второй store/provider: только существующие модули."""
    from services import chat_lore_store, embedding_control_plane
    from services import mca_retrieval_context, summary_memory
    from services.database import DatabaseService

    assert callable(mca_retrieval_context.retrieve)
    assert hasattr(chat_lore_store, "ChatLoreStore")
    assert hasattr(summary_memory, "MemoryManager")
    assert hasattr(DatabaseService, "search_messages_fts")
    assert hasattr(DatabaseService, "get_recent_messages")
    assert callable(embedding_control_plane.control_plane_enabled)
    # Это существующий provider/control-plane; второго не добавляем.
    assert "embedding" in embedding_control_plane.__name__
