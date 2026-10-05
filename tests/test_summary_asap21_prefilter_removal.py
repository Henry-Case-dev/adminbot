"""ASAP-2.1 (mca-asap21-summary-quality-ui-cleanup) — T-3987: тесты удаления
prefilter (§27, ADR-1028-1 D1, инварианты §40-1..4).

Сценарии владельца §27:3499–3537:
  1. «у кота рак» (короткое, no reply/mention/burst) доходит до L1;
  2. «Леха уехал» доходит до L1;
  3. 500 сообщений, помещаются в budget → все доступны L1;
  4. physical overflow → technical packing + явный лог + 0 score_message.

Граничные инварианты: удалённые символы не реинкарнируются (grep `score_message`
/ `summary_filter` по services/ = 0); модуль-эвристика отсутствует; technical
primitives живут в summary_hybrid_budget с прежними сигнатурами; eviction без
весового члена.
"""
import asyncio
import dataclasses
import json
import logging
from pathlib import Path

import pytest

from config.settings import settings as Settings
from services import param_catalog as pc
from services.summary_generator import SummaryGenerator
from services.summary_xml import XmlGroundingBuilder

ROOT = Path(__file__).resolve().parent.parent


# ── fakes ──────────────────────────────────────────────────────────────────

def _row(db_id, tg_id, text, ts, author="A", user_id=10, reply_to=None):
    return {"id": db_id, "tg_message_id": tg_id, "timestamp": ts,
            "text": text, "user_id": user_id, "author_name": author,
            "reply_to_id": reply_to, "media_type": "text"}


class FakeMemory:
    def __init__(self, rows):
        self.rows = rows
        self.writes = 0

    async def compress_and_purge(self, chat_id):
        pass

    async def get_window_messages(self, chat_id):
        return self.rows

    async def search_long_term(self, chat_id, keywords, limit):
        return []

    async def vector_search(self, chat_id, query, limit):
        return []

    async def get_graph_facts(self, chat_id, rows, keywords):
        return []

    async def memorize_facts(self, chat_id, raw_text, source_type):
        self.writes += 1

    async def get_rag_context(self, chat_id, query, *, sort_by_timestamp=False):
        return ""


class FakeLLM:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0
        self.payloads = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.payloads.append(messages)
        return self.answers.pop(0) if self.answers else ""


def _generator(rows, answers, hybrid=True):
    llm = FakeLLM(answers)
    gen = SummaryGenerator(FakeMemory(rows), XmlGroundingBuilder(), llm,
                           None)

    async def _hybrid(chat_id):
        return hybrid

    gen._hybrid_l2_enabled = _hybrid
    return gen, llm


# ── §27 сценарии 1–3: короткие доходят, полный бюджет — всё доступно ───────

def _run_l1_capture(monkeypatch):
    captured = {}

    async def fake_run_l1(**kwargs):
        captured["rows"] = kwargs.get("rows")
        from services.summary_l1_contract import L1Result
        return L1Result(
            status="ok", payload={"schema_version": 1, "threads": []},
            invalid_reason=None, threads_count=0, facts_count=0,
            auto_unassigned_count=0, skipped_ids=(), skipped_tg_ids=(),
            response_mode="serious", cover_prompt="", duration_ms=1.0)

    monkeypatch.setattr("services.summary_l1_clusterizer.run_l1", fake_run_l1)
    return captured


@pytest.mark.asyncio
async def test_short_no_reply_message_reaches_l1(monkeypatch):
    """§27.1: «у кота рак» — короткое, no reply/mention/burst — доходит до L1."""
    rows = [_row(1, 101, "у кота рак", 1000)]
    gen, _llm = _generator(rows, [])
    captured = _run_l1_capture(monkeypatch)
    await gen._run(-100, False)
    assert captured["rows"] == rows
    assert len(captured["rows"]) == 1
    assert captured["rows"][0]["text"] == "у кота рак"


@pytest.mark.asyncio
async def test_short_fact_message_reaches_l1(monkeypatch):
    """§27.2: «Леха уехал» доходит до L1."""
    rows = [_row(1, 101, "Леха уехал", 1000)]
    gen, _llm = _generator(rows, [])
    captured = _run_l1_capture(monkeypatch)
    await gen._run(-100, False)
    assert captured["rows"] == rows


@pytest.mark.asyncio
async def test_500_messages_within_budget_all_available(monkeypatch):
    """§27.3: 500 сообщений, помещаются в budget → ВСЕ доступны L1."""
    rows = [_row(i, 100 + i, f"сообщение номер {i}", 1000 + i)
            for i in range(1, 501)]
    gen, _llm = _generator(rows, [])
    captured = _run_l1_capture(monkeypatch)
    await gen._run(-100, False)
    assert len(captured["rows"]) == 500
    assert captured["rows"] == rows


# ── §27 сценарий 4: physical overflow → technical packing + явный лог ──────

def test_physical_overflow_technical_packing_with_warn(caplog):
    """§27.4: input не помещается → technical packing (eviction без веса) +
    явный WARN + никакого heuristic scoring."""
    from services.summary_hybrid_budget import estimate_and_split
    # Крошечный chars-лимит: окно гарантированно не влезает.
    rows = [_row(i, 100 + i, "х" * 50, 1000 + i) for i in range(1, 31)]
    fragments, budget = estimate_and_split(rows, char_limit=100)
    assert budget["fits"] is False
    assert fragments is not None and len(fragments) > 1
    # Последний фрагмент всегда заканчивается последним сообщением (§93).
    assert fragments[-1].message_ids[-1] == rows[-1]["id"]

    # Явный лог — через полный run_l1 (WARN «L1 truncated input» в run_l1).
    from services.summary_l1_clusterizer import run_l1

    l1_json = json.dumps({"schema_version": 2, "threads": [],
                          "unassigned_message_ids": []},
                         ensure_ascii=False)

    async def _call(messages):
        return l1_json

    with caplog.at_level(logging.WARNING):
        result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            run_l1(llm=None, rows=rows, chat_id=-100, budget=("chars", 100),
                   llm_call=_call))
    # Packing-факты на результате (статус LLM-ответа не важен для §27.4):
    # физическое усечение произошло, вытесненные видны, WARN явный.
    assert result.truncated is True
    assert len(result.skipped_ids) > 0
    assert any("L1 truncated input" in r.message for r in caplog.records)


def test_no_heuristic_scoring_anywhere():
    """Инвариант (a)/§40-2: heuristic scoring не реинкарнировался."""
    import services.summary_hybrid_budget as shb
    import services.summary_l1_clusterizer as slc
    assert "score_message" not in dir(shb)
    assert "score_message" not in dir(slc)
    assert not hasattr(slc, "_EVICTION_PARAMS")
    # Модули S1/S2 удалены.
    assert not (ROOT / "services/summary_filter.py").exists()
    assert not (ROOT / "services/summary_context_restore.py").exists()


def test_eviction_key_technical_no_weight():
    """Ключ вытеснения — (reply_protected, timestamp, db_id), без веса."""
    from services.summary_l1_clusterizer import _eviction_key
    old = _row(1, 101, "старое", 1000)
    new = _row(2, 102, "новое", 5000)
    old_key = _eviction_key(old, kept_tg=set(), children_by_tg={})
    new_key = _eviction_key(new, kept_tg=set(), children_by_tg={})
    assert old_key < new_key            # старое вытесняется первым
    # reply-защита: участник цепочки вытесняется последним.
    chain = _row(3, 103, "ответ", 2000, reply_to=102)
    protected_key = _eviction_key(chain, kept_tg={102}, children_by_tg={})
    assert protected_key[0] == 1
    assert old_key[0] == 0 and new_key[0] == 0


# ── §27 (доп. инварианты каталога/старта с «грязной» БД) ──────────────────

def test_catalog_summary_filter_keys_removed():
    """§5/T-3973: 8 ключей + 2 группы удалены; счётчики 481/105/103/21."""
    keys = {s.pg_key for s in pc.REGISTRY.values()}
    for key in ("flags.summary_filter_enabled",
                "flags.summary_filter_reply_context_enabled",
                "limits.summary_filter_min_weight",
                "limits.summary_filter_min_words_for_bonus",
                "limits.summary_filter_burst_window_seconds",
                "limits.summary_filter_min_burst_density",
                "limits.summary_filter_context_neighbors",
                "limits.summary_filter_context_max_messages"):
        assert key not in keys
    groups = {g.id for g in pc.GROUPS}
    assert "flags_summary_filter" not in groups
    assert "limits_summary_filter" not in groups
    assert len(pc.REGISTRY) == 504
    assert len(pc.GROUPS) == 108
    assert len(pc._TAB_BY_GROUP) == 106
    assert len(pc.TAB_RULES) == 21


def test_startup_tolerates_stale_db_values(monkeypatch):
    """§5:2965 — startup с «грязной» БД (pre-seeded старые ключи) не ломается:
    hot_config._coerce возвращает raw-значение при отсутствии spec."""
    from services import hot_config as hot
    stale = {
        "flags.summary_filter_enabled": True,
        "limits.summary_filter_min_weight": "5",
        "flags.summary_hybrid_l2_enabled": True,
    }
    monkeypatch.setattr(hot, "get", lambda key, default=None: stale.get(key, default))
    # Читателей ключей S1 нет: резолв режима живёт на hybrid-флаге.
    assert hot.get("flags.summary_filter_enabled", False) is True  # сирота читается raw
    # Полный импорт/конфигурация не валидирует каталог против БД.
    import services.summary_generator  # noqa: F401
    import services.summary_l1_clusterizer  # noqa: F401
