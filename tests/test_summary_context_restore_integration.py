"""S2 round1026 (ADR-1026-4) — интеграционный регресс врезки восстановления
контекста в ``SummaryGenerator._apply_filter``.

Покрывает SC-01/03/12/13/15/16:

* **SC-01** ON: XML-история = ``RestoreResult.kept``; RAG/graph/память — на
  **исходных** ``rows`` (как в S1);
* **SC-03** OFF ``flags.summary_filter_reply_context_enabled=false`` → XML-вход
  байт-в-байт = ``FilterResult.kept``; ``RESTORE_*`` не эмитятся;
* **SC-12** родители **вне окна** добываются каноническим
  ``thread_chain.collect_thread_chain`` (reuse, без второй цепочки);
* **SC-13** ``RESTORE_*`` + ``FILTER_COMPLETE.restored_count`` с ``run_id``,
  без секретов/содержимого (R17/R18);
* **SC-15** fail-open: ошибка восстановления → рабочее Саммари на S1-выходе;
* **SC-16** ровно **2** LLM-вызова (S2 добавляет 0).
"""
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import summary_generator as sg
from services.summary_xml import XmlGroundingBuilder

from tests.test_summary_generator import FakeMemory, _row
from tests.test_summary_filter_integration import (
    CHAT_A,
    CHAT_B,
    _FLAG,
    _HYBRID_FLAG,
    _S2_FLAG,
    _gen,
    _patch_chat_limit,
    _patch_delivery,
    _spy_build,
    RecMemory,
)


def _s2_rows():
    """5 сообщений: kept=3 (reply+mention); 2 — родитель и сосед; 5 — дальний шум.

    Timestamp-ы разнесены (> ``burst_window_seconds``), чтобы S1 не пометил
    всплеск и набор ``kept``/``dropped`` был предсказуем.
    """
    return [
        _row(id=1, tg_message_id=100, user_id=10, text="старый шум",
             timestamp=1000),
        _row(id=2, tg_message_id=101, user_id=10, text="родительское сообщение",
             timestamp=2000),
        _row(id=3, tg_message_id=102, user_id=11, text="@vasya важный вопрос",
             reply_to_id=101, timestamp=3000),
        _row(id=4, tg_message_id=103, user_id=12, text="шум рядом",
             timestamp=4000),
        _row(id=5, tg_message_id=104, user_id=13, text="дальний шум",
             timestamp=5000),
    ]


class FakeDb:
    """Мини-DB для канонического ``collect_thread_chain`` (без sqlite)."""

    def __init__(self, by_tg):
        self.by_tg = by_tg

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        return self.by_tg.get(tg_message_id)

    async def get_bot_reply(self, chat_id, tg_message_id, now=None):
        return None

    async def get_bot_reply_parent(self, chat_id, tg_message_id, now=None):
        return None


def _xml_ids(captured):
    return [r["id"] for r in captured["rows"]]


# ── SC-01: XML восстановлен, RAG — исходное окно ────────────────────────────

class TestRestoreIntegration:
    @pytest.mark.asyncio
    async def test_on_restores_context_for_xml_rag_original(self, monkeypatch):
        rows = _s2_rows()
        memory = RecMemory(rows=rows)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="текст")
        rec = {"plain": [], "rich": []}
        _patch_delivery(monkeypatch, rec)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        _patch_chat_limit(monkeypatch, {(CHAT_A, _FLAG): True,
                                        (CHAT_A, _HYBRID_FLAG): False})
        gen = _gen(memory, llm)
        captured = {}
        _spy_build(gen, monkeypatch, captured)

        await gen._run(CHAT_A, False)

        # XML = S1.kept (2 — «answered», 3) ∪ восстановленные соседи 1 и 4.
        assert _xml_ids(captured) == [1, 2, 3, 4]
        assert 5 not in _xml_ids(captured)                 # дальний шум не тянулся
        # RAG/graph — по исходному окну (все 5).
        assert [r["id"] for r in memory.graph_rows] == [1, 2, 3, 4, 5]
        m = gen._filter_metrics[CHAT_A]
        assert m["saved_count"] == 2
        assert m["restored_count"] == 2
        assert m["parent_count"] == 0
        assert m["neighbor_count"] == 2
        assert m["restore_status"] == "ok"
        assert rec["plain"]                                # доставка состоялась

    @pytest.mark.asyncio
    async def test_apply_filter_restored_count_matches_effective(self, monkeypatch):
        rows = _s2_rows()
        gen = _gen(FakeMemory(rows=rows), MagicMock())
        _patch_chat_limit(monkeypatch, {(CHAT_A, _FLAG): True})

        kept = await gen._apply_filter(CHAT_A, rows, "run-r", None)

        assert [r["id"] for r in kept] == [1, 2, 3, 4]
        assert gen._filter_metrics[CHAT_A]["restored_count"] == 2


# ── SC-03: OFF байт-в-байт S1 ───────────────────────────────────────────────

class TestOffByteIdentical:
    @pytest.mark.asyncio
    async def test_off_gate_keeps_s1_output(self, monkeypatch, caplog):
        rows = _s2_rows()
        memory = FakeMemory(rows=rows)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="текст")
        rec = {"plain": [], "rich": []}
        _patch_delivery(monkeypatch, rec)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        _patch_chat_limit(monkeypatch, {
            (CHAT_A, _FLAG): True,
            (CHAT_A, _S2_FLAG): False,
            (CHAT_A, _HYBRID_FLAG): False,
        })
        gen = _gen(memory, llm)
        captured = {}
        _spy_build(gen, monkeypatch, captured)

        with caplog.at_level(logging.INFO, logger=sg.__name__):
            await gen._run(CHAT_A, False)

        assert _xml_ids(captured) == [3]                   # только S1 kept
        assert gen._filter_metrics[CHAT_A]["restored_count"] == 0
        assert "restore_status" not in gen._filter_metrics[CHAT_A]
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "RESTORE_START" not in joined
        assert "RESTORE_COMPLETE" not in joined
        assert rec["plain"]

    @pytest.mark.asyncio
    async def test_off_gate_no_db_touch(self, monkeypatch):
        """OFF → адаптер не дёргает thread_chain (нет I/O восстановления)."""
        rows = _s2_rows()
        memory = FakeMemory(rows=rows)

        class BoomDb:
            async def get_smart_message_by_tg_id(self, *a, **kw):
                raise AssertionError("DB не должна вызываться при OFF")

        memory.db = BoomDb()
        gen = _gen(memory, MagicMock())
        _patch_chat_limit(monkeypatch, {
            (CHAT_A, _FLAG): True,
            (CHAT_A, _S2_FLAG): False,
        })

        kept = await gen._apply_filter(CHAT_A, rows, "run-off", None)

        assert [r["id"] for r in kept] == [3]


# ── SC-12: родители вне окна через reuse thread_chain ───────────────────────

class TestExtraParentsOutsideWindow:
    @pytest.mark.asyncio
    async def test_parent_outside_window_restored_via_thread_chain(self, monkeypatch):
        child = _row(id=2, tg_message_id=101, user_id=11,
                     text="@vasya вопрос", reply_to_id=100, timestamp=1001)
        parent = _row(id=1, tg_message_id=100, user_id=10,
                      text="родитель вне окна", timestamp=1000)
        memory = FakeMemory(rows=[child])          # родитель НЕ в окне
        memory.db = FakeDb({101: child, 100: parent})
        gen = _gen(memory, MagicMock())
        _patch_chat_limit(monkeypatch, {
            (CHAT_A, _FLAG): True,
            (CHAT_A, "limits.summary_filter_context_neighbors"): 0,
        })

        kept = await gen._apply_filter(CHAT_A, [child], "run-x", None)

        assert [r["id"] for r in kept] == [1, 2]
        assert gen._filter_metrics[CHAT_A]["restored_count"] == 1
        assert gen._filter_metrics[CHAT_A]["parent_count"] == 1


# ── SC-13: логи RESTORE_* с run_id, без секретов ────────────────────────────

class TestRestoreLogs:
    @pytest.mark.asyncio
    async def test_logs_have_run_id_without_content(self, monkeypatch, caplog):
        rows = _s2_rows()
        gen = _gen(FakeMemory(rows=rows), MagicMock())
        _patch_chat_limit(monkeypatch, {(CHAT_A, _FLAG): True})

        with caplog.at_level(logging.INFO, logger=sg.__name__):
            await gen._apply_filter(CHAT_A, rows, "run-log-1", None)

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "RESTORE_START" in joined
        assert "RESTORE_COMPLETE" in joined
        assert "run_id=run-log-1" in joined
        assert "restored_count=2" in joined
        # R17/R18: без содержимого сообщений.
        assert "важный вопрос" not in joined
        assert "родительское сообщение" not in joined


# ── SC-15: fail-open ────────────────────────────────────────────────────────

class TestFailOpenIntegration:
    @pytest.mark.asyncio
    async def test_restore_error_falls_back_to_s1(self, monkeypatch, caplog):
        rows = _s2_rows()
        memory = FakeMemory(rows=rows)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="текст саммари")
        rec = {"plain": [], "rich": []}
        _patch_delivery(monkeypatch, rec)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        _patch_chat_limit(monkeypatch, {(CHAT_A, _FLAG): True,
                                        (CHAT_A, _HYBRID_FLAG): False})
        gen = _gen(memory, llm)
        captured = {}
        _spy_build(gen, monkeypatch, captured)

        def _boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(sg, "restore_context", _boom)

        with caplog.at_level(logging.WARNING, logger=sg.__name__):
            await gen._run(CHAT_A, False)

        assert _xml_ids(captured) == [2, 3]                # S1-выход
        assert rec["plain"]                                # Саммари не упало
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "RESTORE_ERROR" in joined

    @pytest.mark.asyncio
    async def test_core_error_status_falls_back_to_s1(self, monkeypatch, caplog):
        rows = _s2_rows()
        gen = _gen(FakeMemory(rows=rows), MagicMock())
        _patch_chat_limit(monkeypatch, {(CHAT_A, _FLAG): True})

        class BadResult:
            status = "error"
            kept = None
            restored_count = 0
            parent_count = 0
            neighbor_count = 0
            skipped_ids = ()
            budget = {}
            duration_ms = 1.0

        monkeypatch.setattr(
            sg, "restore_context", lambda *a, **kw: BadResult())

        with caplog.at_level(logging.WARNING, logger=sg.__name__):
            kept = await gen._apply_filter(CHAT_A, rows, "run-e", None)

        assert [r["id"] for r in kept] == [2, 3]
        assert gen._filter_metrics[CHAT_A]["restore_status"] == "error"
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "RESTORE_ERROR" in joined


# ── SC-16: ровно 2 LLM-вызова при восстановлении ────────────────────────────

class TestTwoLlmCalls:
    @pytest.mark.asyncio
    async def test_exactly_two_llm_calls_with_restore(self, monkeypatch):
        import json
        rows = _s2_rows()
        memory = FakeMemory(rows=rows)
        editor = json.dumps({"response_mode": "casual",
                             "digest": "# Тема\n- что-то",
                             "cover_prompt": ""})
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[editor, "готовый текст саммари"])
        rec = {"plain": [], "rich": []}
        _patch_delivery(monkeypatch, rec)
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        _patch_chat_limit(monkeypatch, {(CHAT_A, _FLAG): True,
                                        (CHAT_A, _HYBRID_FLAG): False})
        gen = _gen(memory, llm)

        await gen._run(CHAT_A, False)

        assert llm.generate.await_count == 2               # S2 добавил 0 вызовов


# ── A/B per-chat ────────────────────────────────────────────────────────────

class TestPerChatAB:
    @pytest.mark.asyncio
    async def test_chat_a_restores_chat_b_not(self, monkeypatch):
        rows = _s2_rows()
        gen = _gen(FakeMemory(rows=rows), MagicMock())
        _patch_chat_limit(monkeypatch, {
            (CHAT_A, _FLAG): True,
            (CHAT_B, _FLAG): True,
            (CHAT_B, _S2_FLAG): False,
        })

        kept_a = await gen._apply_filter(CHAT_A, rows, "run-a", None)
        kept_b = await gen._apply_filter(CHAT_B, rows, "run-b", None)

        assert [r["id"] for r in kept_a] == [1, 2, 3, 4]
        assert [r["id"] for r in kept_b] == [3]
