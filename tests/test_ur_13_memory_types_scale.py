"""UR-13 memory types/scale proof: KIND taxonomy, claim gate, paging, identity.

Строки UR-13/13.1/13.4/13.8/UR-BAN-03 остаются PENDING до review.
"""
from types import SimpleNamespace

import pytest

from services import claim_envelope as ce
from services import direct_context_composer as comp
from services import evidence_policy
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
        "представь: что я космонавт",
        "я как будто космонавт",
        "это ролевая игра, я король",
        "ролевая игра: я король",
        "в ролевой игре я король",
        "давай поиграем в ролевую игру",
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
                     "я словно на иголках"):
            assert await mem.remember_user_fact(
                CHAT, fact, target_user="Вася", ttl_days=0) == "saved", fact
        assert await mem.remember_user_fact(
            CHAT, "это ролевая игра, я король",
            target_user="Вася", ttl_days=0) == "skipped_gated"
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
        recent = await db.get_recent_messages(CHAT, 2000)
        db.db = tracing.real
        assert len(recent) == 2000
        assert recent[0]["timestamp"] == 18_001
        assert recent[-1]["timestamp"] == 20_000
        page_params = [params[-1] for sql, params in tracing.calls
                       if "LIMIT ?" in sql]
        assert len(page_params) >= 4, tracing.calls
        assert max(page_params) <= 500, page_params
        assert 20_000 not in page_params

        # retrieval находит сообщение старше окна последних 2000.
        found = await db.search_messages_fts(
            CHAT, "СТАРЫЙМАРКЕР", 5)
        assert found
        assert any(int(row["id"]) == 1 for row in found)
    finally:
        await db.close()


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
