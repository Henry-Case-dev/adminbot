"""VMQ-MEM RC3 (D2): explicit-year base filter and capacity-based slots."""
import datetime
import types

import pytest

from services import direct_chat_service as dcs

CHAT = -1002661910336


def _ts(year, month=6, day=1):
    return int(datetime.datetime(
        year, month, day, tzinfo=datetime.timezone.utc).timestamp())


def _row(fid, text, year, **kwargs):
    ts = _ts(year)
    row = {
        "id": fid, "fact": text, "origin": "chat_history",
        "rag_ts": ts, "message_timestamp": ts, "created_at": ts,
        "weight": 0.5, "importance": 5, "status": "confirmed",
        "tg_message_id": None, "forward_from": "", "expires_at": None,
        "subject_ref_id": None, "speaker_author_id": None,
        "assertion_kind": None, "attribution_method": None,
        "provenance_channel": None,
    }
    row.update(kwargs)
    return row


class _Result:
    def __init__(self, fact_rows, period_fill=None, candidates=()):
        self.fact_rows = tuple(fact_rows)
        self.period_fill = period_fill
        self.candidates = tuple(candidates)


class _Cand:
    def __init__(self, entity_id, entity_type="message"):
        self.id = f"msg:{entity_id}"
        self.entity_id = str(entity_id)
        self.entity_type = entity_type
        self.channel = "lexical"
        self.sent_at = _ts(2025)
        self.preview = ""


class _DbStub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    async def search_messages_fts(self, *_a, **_k):
        return []


def _service(monkeypatch, base_rows, pool_rows, *, calls=None,
             period_candidates=()):
    async def _identity_rerank(_query, facts):
        return list(facts)

    memory = types.SimpleNamespace(rerank_rag_facts=_identity_rerank)
    service = dcs.DirectChatService(memory=memory, db=_DbStub(),
                                    llm=None, aliases=None)

    async def fake(_db, _memory, chat_id, query, channels, limit, policy,
                   *, period_fill=False, period_intent=None, **_kwargs):
        if calls is not None:
            calls.append({"period_fill": bool(period_fill),
                          "channels": tuple(channels),
                          "period_intent": getattr(period_intent, "kind", None)})
        if period_fill:
            return _Result(pool_rows,
                           period_fill={"vector_leg": "ok",
                                        "vector_rows": 0},
                           candidates=period_candidates)
        return _Result(base_rows)

    monkeypatch.setattr(service, "_rag_retrieve", fake)
    return service


@pytest.mark.asyncio
async def test_rc3_explicit_year_filters_base_and_fills_capacity(monkeypatch):
    base = [
        _row(9001, "2026 текущее", 2026),
        _row(9002, "2026 ещё", 2026),
        _row(1001, "конфликт с Олей 2025", 2025),
        _row(1002, "ещё конфликт 2025", 2025),
    ]
    pool = [_row(2000 + i, f"конфликт 2025 {i}", 2025) for i in range(12)]
    calls: list = []
    service = _service(
        monkeypatch, base, pool, calls=calls,
        period_candidates=(_Cand(60823), _Cand(60824)))
    rows = await service._rag_unified_rows(
        CHAT, "что известно о конфликте Корсара с Олей в 2025 году?",
        None, memory_scope="auto", plan_act="answer")

    # Default graph limit is 10: 2 base + 8 period, all in target year.
    assert len(rows) == 10
    assert {row["id"] for row in rows} >= {1001, 1002}
    assert all(dcs._rag_row_year(row) == 2025 for row in rows)
    period_rows = [row for row in rows if row.get("period_fill")]
    assert len(period_rows) == 8
    assert service._rag_period_stats["base_out_of_year_dropped"] == 2
    assert service._rag_period_stats["breadth_reason"] == "explicit_year"
    assert service._rag_period_stats["breadth_cap"] == 8
    assert service._rag_period_stats["period_message_candidates"] == 2
    assert service._rag_period_stats[
        "period_message_candidates_reason"] == "fact_only_consumer"
    assert any(call["period_fill"] for call in calls)
    assert any(call["period_intent"] == "explicit_year" for call in calls)


@pytest.mark.asyncio
async def test_rc3_current_state_stays_fresh(monkeypatch):
    base = [_row(9000 + i, f"текущее состояние {i}", 2026)
            for i in range(10)]
    pool = [_row(2000 + i, f"старое {i}", 2024) for i in range(3)]
    calls: list = []
    service = _service(monkeypatch, base, pool, calls=calls)
    rows = await service._rag_unified_rows(
        CHAT, "что сейчас происходит с ботом?", None,
        memory_scope="auto", plan_act="answer")
    assert len(rows) == 10
    assert all(dcs._rag_row_year(row) == 2026 for row in rows)
    assert service._rag_period_stats["breadth_allowed"] == 0
    assert not any(call["period_fill"] for call in calls)
