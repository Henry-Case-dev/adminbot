"""VMQ-MEM-TIME (§6): as-of/провенанс — история не подаётся как действующее.

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/time/fix-contract.md`
(§6). Writer не может выдать исторический факт за актуальный:

  * reply-путь: строка с V=0 (`archived_fact`/истёкший TTL) получает ПРЕФИКС
    «(архив, YYYY)» через существующий `_mark_rag_fact`; год — из времени
    самой строки;
  * подтверждённая действующая строка метки не получает;
  * `render_evidence_summary(certainty="archive")` → «архивный факт: » + дата;
  * профиль: аддитивные `status`/`valid_now`/`as_of_year`, `confidence` для
    `archived_fact` считается по весу+provenance, а не по статусу-квоте;
  * промпты не меняются — маркировка живёт в данных.
"""
import calendar
import time

import pytest

from services import chat_prompts
from services import direct_chat_service as dcs
from services import mca_retrieval_context as mrc
from services import tool_router


def _ts(year: int = 2023, month: int = 5, day: int = 4) -> int:
    return calendar.timegm((year, month, day, 10, 0, 0, 0, 0, 0))


def _row(**kwargs) -> dict:
    row = {
        "id": 1, "origin": "chat_history", "fact": "старый факт",
        "item_id": "fact:1", "rag_ts": _ts(2023),
        "message_timestamp": _ts(2023), "created_at": _ts(2023),
        "target_user": "aleksey", "tg_message_id": 77,
        "forward_from": "", "status": "confirmed", "expires_at": None,
        "subject_ref_id": 1, "speaker_author_id": 1,
        "attribution_method": "self_report", "provenance_channel": None,
        "assertion_kind": None, "chat_id": -100,
    }
    row.update(kwargs)
    return row


def _item(row: dict) -> tuple:
    return (row["origin"], row["fact"], row["rag_ts"], row["target_user"],
            row["item_id"], row["forward_from"], False)


class TestReplyMarking:

    def test_archived_fact_gets_as_of_prefix(self):
        """V=0 → «(архив, 2023)»; префикс ставится ДО текста факта."""
        row = _row(status="archived_fact")
        as_of = dcs._rag_as_of_map([row])
        marked = dcs._mark_rag_fact(_item(row), {}, as_of)
        assert marked[1].startswith("(архив, 2023) ")
        assert "старый факт" in marked[1]
        # Текст самого факта не переписан — только добавлен префикс.
        assert marked[1].endswith("старый факт")

    def test_expired_fact_gets_as_of_prefix(self):
        now = int(time.time())
        row = _row(status="confirmed", expires_at=now - 10)
        marked = dcs._mark_rag_fact(_item(row), {}, dcs._rag_as_of_map([row]))
        assert marked[1].startswith("(архив, 2023) ")

    def test_current_fact_is_not_marked(self):
        row = _row(status="confirmed")
        marked = dcs._mark_rag_fact(_item(row), {}, dcs._rag_as_of_map([row]))
        assert marked[1] == "старый факт"

    def test_archive_and_uncertainty_marks_combine(self):
        """Архив и «не подтверждено» — независимые пометки, обе видны."""
        row = _row(status="archived_fact", subject_ref_id=None,
                   speaker_author_id=None)
        ranks = {row["item_id"]: 0}
        marked = dcs._mark_rag_fact(_item(row), ranks,
                                    dcs._rag_as_of_map([row]))
        assert marked[1].startswith("(архив, 2023) ")
        assert "(не подтверждено) " in marked[1]

    def test_archived_fact_is_not_tentative(self):
        """read_policy_rank: квота не делает факт «предположением» (§6)."""
        from services import graphrag_provenance as prov
        archived = _row(status="archived_fact")
        confirmed = _row(status="confirmed")
        assert prov.read_policy_rank(archived) == prov.read_policy_rank(
            confirmed) == 3
        tentative = _row(status="archived_fact", subject_ref_id=None,
                         speaker_author_id=None)
        assert prov.read_policy_rank(tentative) == 0

    def test_unknown_provider_rows_are_not_marked(self):
        """Двойник без статуса: неизвестность не выдаётся за архив."""
        row = {"origin": "chat_history", "fact": "факт", "rag_ts": _ts(2023),
               "item_id": "fact:2"}
        as_of = dcs._rag_as_of_map([row])
        assert as_of["fact:2"][0] is True
        marked = dcs._mark_rag_fact(("chat_history", "факт", _ts(2023),
                                     None, "fact:2"), {}, as_of)
        assert marked[1] == "факт"


class TestEvidenceSummary:

    def test_expired_fact_is_marked_archive(self):
        """V=0 из-за истёкшего TTL → «архивный факт», не действующее."""
        now = int(time.time())
        row = _row(status="confirmed", expires_at=now - 60)
        assert dcs._evidence_certainty(row) == "archive"

    def test_confirmed_live_fact_has_no_archive_mark(self):
        row = _row(status="confirmed", expires_at=None)
        assert dcs._evidence_certainty(row) == ""

    def test_archive_certainty_prefix(self):
        rows = [{"kind": "fact", "text": "переехал в 2023",
                 "ts": _ts(2023), "certainty": "archive"}]
        lines = mrc.render_evidence_summary(rows)
        assert lines and lines[0].startswith("архивный факт: ")
        assert "04.05.2023" in lines[0]

    def test_confirmed_rows_have_no_archive_prefix(self):
        rows = [{"kind": "fact", "text": "живёт в Москве",
                 "ts": _ts(2026), "certainty": ""}]
        lines = mrc.render_evidence_summary(rows)
        assert lines and not lines[0].startswith("архивный факт: ")


class TestProfileEnvelope:

    def _router(self):
        return tool_router.ToolRouter.__new__(tool_router.ToolRouter)

    def test_archived_fact_envelope_marks_valid_now_false(self):
        router = self._router()
        fact = router._memory_lookup_fact_item(
            _row(status="archived_fact"))
        assert fact["valid_now"] is False
        assert fact["status"] == "archived_fact"
        assert fact["as_of_year"] == 2023
        assert fact["source_id"]
        # confidence — по R (вес+provenance), не по статусу-квоте.
        assert fact["confidence"] == "confirmed"

    def test_current_fact_envelope(self):
        router = self._router()
        row = _row(status="confirmed", message_timestamp=_ts(2026),
                   created_at=_ts(2026))
        fact = router._memory_lookup_fact_item(row)
        assert fact["valid_now"] is True
        assert fact["as_of_year"] == 2026

    def test_unconfirmed_is_not_confirmed(self):
        router = self._router()
        row = _row(status="unconfirmed")
        fact = router._memory_lookup_fact_item(row)
        assert fact["confidence"] == "unconfirmed"
        assert fact["valid_now"] is False


class TestPromptsUnchanged:

    def test_no_archive_marking_instruction_added_to_prompts(self):
        """§6: маркировка в ДАННЫХ; новых инструкций Writer'у нет."""
        prompt = chat_prompts.DIRECT_L1_PLANNER_SYSTEM_PROMPT
        assert "(архив" not in prompt
        assert "архивный факт" not in prompt.lower()
