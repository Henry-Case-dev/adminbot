"""SPEECH-P0-A2 (§memory-read): текущая реплика — не история; L2 — пересказ
(keep-head + маркер); self-echo не факт; provenance-ранг в direct-RAG.

TEST-LIFECYCLE: REGRESSION owner=SPEECH-P0/A2

Покрытие:
  * current-turn boundary: реплика-триггер исключается из окна истории до
    конспекта/verbatim-хвоста (legacy и composer-билдер), сам вопрос остаётся
    <Current_Question>; без message_id окно не меняется (никаких догадок);
  * L2: кап keep-head (начало пересказа), маркер «пересказ, не источник»;
  * self-echo: `memorize_self_reply` пишет status='tentative' (не
    'confirmed'), в фактический <RAG_Memory> bot_self_reply/bot_direct_reply
    не попадают, style anchors не ломаются;
  * provenance: существующий `graphrag_provenance.read_policy_rank`
    подключён к фактическому direct-RAG — rank 3 без пометки, rank 2
    «предположение», rank 0/1 «не подтверждено»; `with_meta` несёт v17-поля.
"""
import pytest

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import graphrag_provenance  # noqa: E402
from services.database import DatabaseService  # noqa: E402
from services.summary_memory import MemoryManager  # noqa: E402
# Двойники direct-chat (FakeMemory/SummaryDB/фабрика) — REUSE, не копия.
from test_direct_chat import (  # noqa: E402
    CHAT_ID, FakeMemory, SummaryDB, _make_service, _message, _window_row,
)


@pytest.fixture
def fake_time(monkeypatch):
    """Заморозка time в direct_chat_service (bot_replies TTL/style anchors)."""
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

        @staticmethod
        def time():
            return state["now"]

    monkeypatch.setattr("services.direct_chat_service.time", FakeTime)
    return state


# ── doubles ────────────────────────────────────────────────────────────────

class _NoLLM:
    """LLM-заглушка: embed недоступен → FTS-режим MemoryManager."""

    async def generate(self, messages):
        raise AssertionError("generate не должен вызываться")

    async def embed(self, texts):
        raise AssertionError("embed не должен вызываться")


class MetaFakeMemory(FakeMemory):
    """FakeMemory + `with_meta`-кандидаты (provenance-путь direct-RAG)."""

    def __init__(self, rows=None, window=None):
        super().__init__(window=window)
        self.meta_rows = list(rows or [])
        self.meta_calls = []

    async def get_rag_facts(self, chat_id, query, *,
                            include_direct_reply=False,
                            include_self=False, with_meta=False):
        self.rag_facts_calls.append(
            (chat_id, query, include_direct_reply, include_self))
        if not with_meta:
            return [(r["origin"], r["fact"], r.get("rag_ts"))
                    for r in self.meta_rows]
        self.meta_calls.append((chat_id, query))
        return list(self.meta_rows)


class AnchorsDB(SummaryDB):
    """SummaryDB + последние ответы бота (style anchors)."""

    def __init__(self, summary=None, level2=None, replies=None):
        super().__init__(summary, level2)
        self.replies = list(replies or [])

    async def last_bot_replies(self, chat_id, limit, now):
        return list(self.replies)


def _rag_row(origin, fact, *, fact_id=1, ref=None, speaker=None,
             status="confirmed", conflict=None, ts=1_700_000_000):
    """with_meta-кандидат в форме `_search_graph_facts(with_meta=True)`."""
    return {
        "id": fact_id, "origin": origin, "fact": fact, "rag_ts": ts,
        "created_at": ts, "message_timestamp": ts, "target_user": None,
        "tg_message_id": None, "forward_from": "",
        "item_id": f"fact:{fact_id}", "score": 1.0, "expired": False,
        "expires_at": None, "chat_id": CHAT_ID, "status": status,
        "subject_ref_id": ref, "speaker_author_id": speaker,
        "assertion_kind": None, "attribution_method": None,
        "provenance_channel": None, "conflict_status": conflict,
    }


def _row(text, ts, tg_id=None):
    row = _window_row(ts=ts, text=text)
    row["tg_message_id"] = tg_id
    return row


# ── 1. current-turn boundary ───────────────────────────────────────────────

class TestCurrentTurnBoundary:

    @pytest.mark.asyncio
    async def test_current_reply_not_history_question_kept(self, fake_time):
        """Окно [старое, текущее]: текущее не в <Global_Context>, но вопрос
        остаётся отдельным блоком <Current_Question>."""
        window = [_row("старое сообщение", 100, tg_id=1),
                  _row("текущий вопрос про дроны", 200, tg_id=100)]
        summary = {"summary": "суть окна", "window_end_ts": 0,
                   "raw_count": 2}
        service = _make_service(memory=FakeMemory(window=window),
                                db=SummaryDB(summary))
        blocks = await service._build_user_content(
            CHAT_ID, _message(text="текущий вопрос про дроны",
                              message_id=100), "вася")
        global_block = next(b for b in blocks
                            if b.startswith("<Global_Context>"))
        assert "старое сообщение" in global_block
        assert "текущий вопрос про дроны" not in global_block
        current = next(b for b in blocks
                       if b.startswith("<Current_Question>"))
        assert "текущий вопрос про дроны" in current

    @pytest.mark.asyncio
    async def test_parts_builder_excludes_current_turn(self, fake_time):
        """Composer-билдер: tail/middle не содержат текущую реплику."""
        window = [_row("старое сообщение", 100, tg_id=1),
                  _row("текущий вопрос", 200, tg_id=100)]
        service = _make_service(memory=FakeMemory(window=window))
        parts = await service._build_global_context_parts(
            CHAT_ID, window, trigger_message_id=100)
        body = "\n".join(parts["head_lines"] + parts["tail_lines"])
        assert "старое сообщение" in body
        assert "текущий вопрос" not in body
        assert all(r["tg_message_id"] != 100
                   for r in parts["tail_rows"])

    @pytest.mark.asyncio
    async def test_no_trigger_id_keeps_window(self, fake_time):
        """Без message_id окно не меняется (никаких догадок)."""
        window = [_row("старое сообщение", 100, tg_id=1),
                  _row("второе сообщение", 200, tg_id=2)]
        service = _make_service(memory=FakeMemory(window=window))
        ctx = await service._build_global_context(CHAT_ID, window,
                                                 trigger_message_id=None)
        assert "старое сообщение" in ctx
        assert "второе сообщение" in ctx


# ── 2. L2: keep-head + маркер ──────────────────────────────────────────────

class TestLevel2KeepHead:

    @pytest.mark.asyncio
    async def test_parts_keep_head_and_marker(self, fake_time, monkeypatch):
        import dataclasses as _dc
        from config.settings import settings

        monkeypatch.setattr(
            "services.direct_chat_service.settings",
            _dc.replace(settings, CHAT_LEVEL2_MAX_CHARS=40))
        level2_text = "начало-маркер " + "м" * 100 + " конец-маркер"
        summary = {"summary": "суть окна", "window_end_ts": 50,
                   "raw_count": 3}
        level2 = {"summary": level2_text, "msg_count_highwater": 500}
        window = [_row("новое сообщение", 200, tg_id=2)]
        service = _make_service(
            memory=FakeMemory(window=window),
            db=SummaryDB(summary, level2))
        parts = await service._build_global_context_parts(
            CHAT_ID, window, trigger_message_id=None)
        head = "\n".join(parts["head_lines"])
        assert head.split("\n")[0].startswith(
            "широкий фон: пересказ, не источник: ")
        assert "начало-маркер" in head          # keep-head: начало L2
        assert "конец-маркер" not in head       # хвост отброшен
        assert "— пересказ, не источник" in head


# ── 3. self-echo не факт ───────────────────────────────────────────────────

class TestSelfEchoNotFactual:

    @pytest.mark.asyncio
    async def test_self_and_direct_reply_not_in_rag(self, fake_time):
        """bot_self_reply/bot_direct_reply в фактический RAG не попадают
        (существующий provenance.is_self_referential_origin)."""
        rows = [
            _rag_row("bot_self_reply", "[Бот] заявил: любит грибы", fact_id=1),
            _rag_row("bot_direct_reply", "[Бот] отвечал про грибы", fact_id=2),
            _rag_row("chat_history", "вася любит грибы", fact_id=3,
                     ref=7, speaker=10),
        ]
        service = _make_service(memory=MetaFakeMemory(rows=rows))
        block, _hint = await service._build_rag_block(
            CHAT_ID, _message(text="грибы"), "")
        assert "вася любит грибы" in block
        assert "заявил" not in block
        assert "отвечал" not in block

    @pytest.mark.asyncio
    async def test_style_anchors_not_broken(self, fake_time):
        """Прошлые ответы бота остаются интонацией в <style_anchors>."""
        rows = [_rag_row("bot_self_reply", "[Бот] заявил: любит грибы",
                         fact_id=1)]
        db = AnchorsDB(replies=["ну чё, грибы так грибы"])
        service = _make_service(memory=MetaFakeMemory(rows=rows), db=db)
        blocks = await service._build_user_content(
            CHAT_ID, _message(text="грибы"), "вася")
        anchors = next(b for b in blocks if b.startswith("<style_anchors>"))
        assert "грибы так грибы" in anchors
        assert not any(b.startswith("<RAG_Memory>") for b in blocks)

    @pytest.mark.asyncio
    async def test_memorize_self_reply_status_tentative(self):
        """`memorize_self_reply` не пишет status='confirmed' (self-echo не
        подтверждённое знание), origin остаётся bot_self_reply."""
        d = DatabaseService(":memory:")
        await d.initialize()
        try:
            memory = MemoryManager(d, _NoLLM())
            memory._vec_available = False
            fid = await memory.memorize_self_reply(-100, "[Бот] решил: чай")
            assert fid > 0
            cursor = await d.db.execute(
                "SELECT origin, status FROM graph_facts WHERE id = ?",
                (fid,))
            row = await cursor.fetchone()
            assert row["origin"] == "bot_self_reply"
            assert row["status"] == "tentative"
            # фактический retrieval больше не отдаёт self-вывод как факт
            assert await memory.get_rag_facts(
                -100, "чай", include_self=True) == []
        finally:
            await d.close()


# ── 4. provenance в фактическом direct-RAG ─────────────────────────────────

class TestProvenanceInDirectRag:

    @pytest.mark.asyncio
    async def test_read_policy_rank_marks(self, fake_time):
        """rank 3 — обычная строка; rank 2 — «предположение»; rank 0 —
        «не подтверждено» (legacy не удаляется, подаётся weak hint)."""
        rows = [
            _rag_row("chat_history", "подтверждённый факт про грибы", fact_id=1,
                     ref=7, speaker=10),
            _rag_row("chat_history", "предположительный факт про грибы",
                     fact_id=2, ref=7, status="unconfirmed"),
            _rag_row("chat_history", "legacy факт про грибы", fact_id=3),
        ]
        service = _make_service(memory=MetaFakeMemory(rows=rows))
        block, _hint = await service._build_rag_block(
            CHAT_ID, _message(text="грибы"), "")
        assert "подтверждённый факт про грибы" in block
        assert "(предположение) предположительный факт про грибы" in block
        assert "(не подтверждено) legacy факт про грибы" in block
        # подтверждённая строка не помечена
        assert "(не подтверждено) подтверждённый" not in block

    @pytest.mark.asyncio
    async def test_with_meta_carries_provenance_fields(self):
        """`get_rag_facts(with_meta=True)` несёт v17-поля, и существующий
        read_policy_rank возвращает 3 для provenance-backed confirmed."""
        d = DatabaseService(":memory:")
        await d.initialize()
        try:
            fid = await d.insert_graph_fact(
                -100, "вася любит грибы", "chat_history", None,
                target_user="вася", status="confirmed", weight=0.7,
                importance=5, subject_ref_id=7, speaker_author_id=10)
            memory = MemoryManager(d, _NoLLM())
            memory._vec_available = False
            rows = await memory.get_rag_facts(
                -100, "грибы", with_meta=True)
            assert rows, "FTS-путь должен найти факт"
            row = next(r for r in rows if r["id"] == fid)
            assert row["subject_ref_id"] == 7
            assert row["speaker_author_id"] == 10
            assert row["status"] == "confirmed"
            assert graphrag_provenance.read_policy_rank(row) == 3
        finally:
            await d.close()
