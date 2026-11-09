"""QND-NONDET §5/§7 — метрики и честность витрин.

Правило владельца: каждая статистика происходит из реального решения, и слово
«работает» не появляется, если квантовых значений фактически не было. Доля без
знаменателя — «нет данных», а не выдуманный процент.

TEST-LIFECYCLE: CONTRACT owner=qnd-nondet-2026-11-10
"""
from __future__ import annotations

import asyncio
import json

import pytest

from services import chat_params
from services import hot_config
from services import mca_events
from services import qnd_diagnostics as qnd
from services import quantum_publication as qp
from services import semantic_schedule as sched
from services.database import DatabaseService
from tests.qnd_fakes import FakeQuantumSource

CHAT = -2701
USER = 42
import time as _time

NOW = int(_time.time())   # окно метрик считается от РЕАЛЬНЫХ часов событий

pytestmark = pytest.mark.asyncio


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeChatParams:
    def __init__(self, by_chat=None):
        self._by_chat = dict(by_chat or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


def _caches(values: dict | None = None):
    base = {"memory.nostalgia_enabled": True,
            "flags.nostalgia_enabled": True,
            "memory.nostalgia_quiet_start_hour": 24,
            "memory.nostalgia_quiet_end_hour": 0}
    base.update(values or {})
    hot_config.set_config_cache(_FakeHot(base))
    chat_params.set_chat_params_cache(_FakeChatParams({CHAT: dict(base)}))


def _reset_caches():
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    service = DatabaseService(":memory:")
    loop.run_until_complete(service.initialize())
    yield service
    loop.run_until_complete(service.close())
    loop.close()


@pytest.fixture(autouse=True)
def _clean():
    mca_events.reset_pending()
    _reset_caches()
    yield
    mca_events.reset_pending()
    _reset_caches()


# ── §7: точные имена тестов ────────────────────────────────────────────────

async def test_status_never_reports_working_without_quantum_draws(db):
    """Нет квантовых значений → слово «работает» запрещено, доли без 0/0."""
    _caches()
    block = await qnd.collect_quantum(db, now=NOW)
    for mechanism in ("nostalgia", "initiative"):
        part = block["mechanisms"][mechanism]
        assert part["draws_quantum"] == 0
        assert part["honesty"]["status_word_allowed"] is False
        assert "не использовался" in part["honesty"]["headline"] or \
            "нет данных" in part["honesty"]["headline"]
        assert "работ" not in part["honesty"]["headline"]
        assert part["interval_histogram"] == []
        # Ноль данных показывается нулями, а не процентами.
        assert part["publications"]["published"] == 0

    # Только fallback-значения: слово «работает» тоже не появляется.
    _caches()
    await sched.draw_next(db, sched.MECH_NOSTALGIA, CHAT, now=NOW,
                          source=FakeQuantumSource([0.4],
                                                   source="pseudorandom",
                                                   fallback_reason="provider_unavailable"),
                          trigger=sched.TRIGGER_SCHEDULE)
    await mca_events.flush_events(db)
    block = await qnd.collect_quantum(db, now=NOW)
    part = block["mechanisms"]["nostalgia"]
    assert part["draws_quantum"] == 0
    assert part["source_shares"]["fallback"] == 1
    assert part["honesty"]["status_word_allowed"] is False
    assert "fallback" in part["honesty"]["headline"]


async def test_interval_histogram_and_silence_shares_from_events(db):
    _caches()
    source = FakeQuantumSource([0.1, 0.5, 0.9])
    stamp = NOW
    for _ in range(3):
        row = await sched.draw_next(db, sched.MECH_NOSTALGIA, CHAT, now=stamp,
                                    source=source,
                                    trigger=sched.TRIGGER_SCHEDULE)
        stamp = int(row["next_due_ts"])
    # Одно решение «публикуем» и одно «молчим по случайному исходу».
    await qp.decide(db, mechanism=qp.MECH_NOSTALGIA, chat_id=CHAT,
                    factors={"r": 1.0, "s": 1.0},
                    candidate_ref="episode:1",
                    source=FakeQuantumSource([0.0]),
                    trigger=sched.TRIGGER_SCHEDULE, now=stamp)
    await qp.decide(db, mechanism=qp.MECH_NOSTALGIA, chat_id=CHAT,
                    factors={"r": 0.1, "s": 0.1},
                    candidate_ref="episode:2",
                    source=FakeQuantumSource([0.99]),
                    trigger=sched.TRIGGER_EVENT, now=stamp)
    await mca_events.flush_events(db)

    block = await qnd.collect_quantum(db, now=stamp + 10)
    part = block["mechanisms"]["nostalgia"]
    assert part["draws_total"] == 3
    # `ts` берётся из КОЛОНКИ события, а не из usage_json (иначе поле мёртвое).
    assert part["last_draw"]["ts"], part["last_draw"]
    assert part["last_draw"]["source"] == "quantum"
    histogram = part["interval_histogram"]
    assert histogram and sum(h["count"] for h in histogram) == 3
    assert part["publications"]["published"] == 1
    assert part["publications"]["silent"] == 1
    assert part["publications"]["silence_by_cause"].get("random_miss") == 1
    assert part["evaluations"]["schedule"] == 1
    assert part["evaluations"]["event"] == 1
    assert part["source_shares"]["quantum"] >= 3
    assert part["honesty"]["status_word_allowed"] is True
    # Кандидаты перечислены с p/u/исходом — таблица «почему так вышло».
    candidates = part["candidates"]
    assert len(candidates) == 2
    assert all(c["p"] is not None and c["u"] is not None for c in candidates)


async def test_probability_value_source_outcome_recorded_per_decision(db):
    _caches()
    decision = await qp.decide(
        db, mechanism=qp.MECH_NOSTALGIA, chat_id=CHAT,
        factors={"r": 1.0, "s": 1.0, "a": 1.0},
        candidate_ref="episode:7", source=FakeQuantumSource([0.01]),
        trigger=sched.TRIGGER_SCHEDULE, now=NOW)
    assert decision.publish is True
    await mca_events.flush_events(db)

    cursor = await db.db.execute(
        "SELECT component, outcome, usage_json FROM mca_events "
        "WHERE event_name = ? ORDER BY id", (sched.EVENT_PUBLICATION,))
    rows = [dict(r) for r in await cursor.fetchall()]
    assert len(rows) == 1
    assert rows[0]["component"] == "qnd"
    payload = json.loads(rows[0]["usage_json"])
    assert payload["mechanism"] == "nostalgia"
    assert payload["chat_id"] == CHAT
    assert payload["candidate_ref"] == "episode:7"
    assert payload["trigger"] == "schedule"
    assert payload["source"] == "quantum"
    assert payload["p"] == pytest.approx(decision.probability)
    assert payload["u"] == pytest.approx(0.01)
    assert payload["hit"] == 1
    assert payload["outcome"] == "delivered"
    assert payload["silence_cause"] is None
    assert payload["draw_id"]
    assert payload["provider"]
    assert "S" in payload and "factors" in payload
