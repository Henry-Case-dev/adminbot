"""QND-NONDET §3/§7 — вероятность публикации вместо двойного гейта.

Главный (решающий) тест контракта: при ОДИНАКОВОЙ семантической ситуации
разные допустимые квантовые значения дают РАЗНЫЕ решения о публикации. Если
это не так — требование владельца не выполнено.

Проверяются durable-решения (`quantum_publication_decision`) и фактический
исход, а не только счётчики вызовов.

TEST-LIFECYCLE: CONTRACT owner=qnd-nondet-2026-11-10
"""
from __future__ import annotations

import asyncio
import json

import pytest

from services import chat_params
from services import hot_config
from services import mca_events
from services import nostalgia_worker as nw
from services import quantum_publication as qp
from services import semantic_schedule as sched
from services.database import DatabaseService
from tests.qnd_fakes import FakeQuantumSource, RaisingModules

CHAT = -2701
USER = 42
BOT_ID = 999
NOW = 1_800_000_000
STRONG_FACTORS = {"r": 1.0, "s": 1.0, "a": 1.0, "t": 1.0, "q": 1.0,
                  "n": 0.0}

pytestmark = pytest.mark.asyncio


# ── инфраструктура ─────────────────────────────────────────────────────────

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


def _caches(values: dict | None = None, *, chat_values: dict | None = None):
    base = {
        "memory.nostalgia_enabled": True,
        "flags.nostalgia_enabled": True,
        "initiative.enabled": True,
        "initiative.frequency_profile": "active",
        "initiative.eval_min_messages": 1,
        "initiative.eval_min_interval_seconds": 0,
        "initiative.min_gap_seconds": 0,
        "initiative.max_replies_per_day": 10,
        "initiative.eval_llm_budget_per_day": 10,
        "memory.nostalgia_quiet_start_hour": 24,
        "memory.nostalgia_quiet_end_hour": 0,
    }
    base.update(values or {})
    hot_config.set_config_cache(_FakeHot(base))
    chat_params.set_chat_params_cache(_FakeChatParams({
        CHAT: dict(chat_values or {})}))


def _reset_caches():
    hot_config.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


class _FakeBot:
    def __init__(self):
        self.id = BOT_ID
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((int(chat_id), str(text)))

        class _Msg:
            message_id = 9000 + len(self.sent)

        return _Msg()


class _FakeLLM:
    def __init__(self, answer="кстати, помню как мы тогда спорили"):
        self.answer = answer
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return self.answer

    async def generate_worker(self, role, messages, **kwargs):
        return await self.generate(messages, **kwargs)


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


async def _decisions(db) -> list[dict]:
    await mca_events.flush_events(db)
    cursor = await db.db.execute(
        "SELECT usage_json FROM mca_events WHERE event_name = ? ORDER BY id",
        (sched.EVENT_PUBLICATION,))
    out = []
    for row in await cursor.fetchall():
        try:
            out.append(json.loads(row["usage_json"] or "{}"))
        except (TypeError, ValueError):
            out.append({})
    return out


def _candidate() -> dict:
    return {"kind": "year_back", "fact_id": None, "weight": 0.5,
            "text": "строка воспоминания",
            "year_lines": ["строка воспоминания"], "episodes": [],
            "golden_lines": [], "context_rows": [], "topical": True}


def _worker(db, *, source, bot=None, llm=None) -> nw.NostalgiaWorker:
    worker = nw.NostalgiaWorker(
        db, store=None, llm=llm if llm is not None else _FakeLLM(),
        bot=bot if bot is not None else _FakeBot(), bot_id=BOT_ID)
    worker._random = source
    return worker


# ── §7: точные имена тестов ────────────────────────────────────────────────

async def test_same_semantic_situation_different_quantum_values_differ(db):
    """РЕШАЮЩИЙ тест владельца: та же ситуация, разные значения → разные исходы.

    Одна и та же семантическая ситуация и одинаковые гейты; различается
    ТОЛЬКО квантовое значение: `u=0.02` — публикуем, `u=0.98` — молчим по
    случайному исходу. Оба исхода легальны.
    """
    _caches()
    source = FakeQuantumSource([0.02, 0.98])
    first = await qp.decide(
        db, mechanism=qp.MECH_NOSTALGIA, chat_id=CHAT,
        factors=dict(STRONG_FACTORS), candidate_ref="episode:1",
        source=source, trigger=sched.TRIGGER_SCHEDULE, now=NOW)
    second = await qp.decide(
        db, mechanism=qp.MECH_NOSTALGIA, chat_id=CHAT,
        factors=dict(STRONG_FACTORS), candidate_ref="episode:1",
        source=source, trigger=sched.TRIGGER_SCHEDULE, now=NOW)

    assert 0.0 < first.probability < 1.0
    assert first.probability == pytest.approx(second.probability)
    assert first.value == pytest.approx(0.02)
    assert second.value == pytest.approx(0.98)
    assert first.publish is True
    assert first.outcome == qp.OUTCOME_DELIVERED
    assert first.silence_cause is None
    assert second.publish is False
    assert second.outcome == qp.OUTCOME_SILENT
    assert second.silence_cause == qp.SILENCE_RANDOM_MISS
    assert first.source == second.source == "quantum"
    assert first.draw_id != second.draw_id

    rows = await _decisions(db)
    assert len(rows) == 2
    assert rows[0]["hit"] == 1 and rows[0]["outcome"] == "delivered"
    assert rows[1]["hit"] == 0 and rows[1]["silence_cause"] == "random_miss"
    assert rows[0]["p"] == rows[1]["p"]               # ситуация одна
    assert rows[0]["u"] < rows[1]["u"]                # значения разные


async def test_probability_monotone_bounded_and_inside_settings(db):
    _caches()
    settings = await qp.resolve_settings(CHAT)
    p_min, p_max = await qp.publication_bounds(CHAT, qp.MECH_NOSTALGIA)
    assert p_min > 0.0 and p_max < 1.0
    previous = -1.0
    for score in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        p = qp.probability(score, p_min=p_min, p_max=p_max,
                           theta=settings["theta"], tau=settings["tau"])
        assert p_min - 1e-9 <= p <= p_max + 1e-9
        assert p >= previous
        previous = p

    # Редактируемая настройка реально сужает диапазон (не «декоративная»).
    _caches({"limits.qnd_nostalgia_publication_max": 0.25})
    tight_min, tight_max = await qp.publication_bounds(
        CHAT, qp.MECH_NOSTALGIA)
    assert tight_max == pytest.approx(0.25)
    assert tight_min <= tight_max

    # Совместимость: явный per-chat `initiative.trigger_probability` — p_max.
    _caches(chat_values={"initiative.trigger_probability": 0.3})
    _min3, max3 = await qp.publication_bounds(CHAT, qp.MECH_INITIATIVE)
    assert max3 == pytest.approx(0.3)


async def test_hard_limits_and_dedup_precede_the_draw(db, monkeypatch):
    _caches({"memory.nostalgia_max_per_day": 1})
    await db.save_smart_message(USER, CHAT, "привет", None,
                                NOW - 7 * 86400, "text", "Вася")
    # Дневной лимит уже израсходован.
    await db.db.execute(
        "INSERT INTO nostalgia_log (chat_id, ts, kind, fact_id, status, meta) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (CHAT, NOW - 60, "year_back", None, "sent",
         json.dumps({"reason": "sent"})))
    await db.db.commit()
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    source = FakeQuantumSource([0.0])
    bot = _FakeBot()
    worker = _worker(db, source=source, bot=bot)
    out = await worker._process_chat(CHAT, NOW, manual=False)

    assert out["sent"] == 0
    assert source.count() == 0          # draw не выполнялся вовсе
    assert bot.sent == []
    assert await _decisions(db) == []


async def test_sendrecheck_never_redraws_or_redecides(db, monkeypatch):
    _caches()
    await db.save_smart_message(USER, CHAT, "привет", None,
                                NOW - 7 * 86400, "text", "Вася")
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    monkeypatch.setattr(nw, "_intent_delegation_enabled", lambda: True)
    source = FakeQuantumSource([0.0, 0.0])
    bot = _FakeBot()
    worker = _worker(db, source=source, bot=bot)

    async def _silent(chat_id, text, candidate):
        return {"status": "silent", "reason_code": "recheck_demoted"}

    monkeypatch.setattr(worker, "_delegate_initiative", _silent)
    out = {"candidates": 0, "sent": 0, "skipped": 0, "errors": 0}
    await worker._candidate_llm_send(
        CHAT, NOW, out, candidate=_candidate(), pick_info={})

    # Ровно ОДИН draw и ОДНО решение: SendRecheck — свежесть, не второй
    # бросок и не повторная оценка уместности.
    assert source.count("nostalgia_publication") == 1
    assert source.count() == 1
    assert out["sent"] == 0
    assert bot.sent == []
    rows = await _decisions(db)
    assert len(rows) == 1 and rows[0]["outcome"] == "delivered"


async def test_llm_veto_without_veto_reason_is_semantic_parse_error(db):
    from services import initiative_observer as obs
    _caches()
    runner = obs.InitiativeObserverRunner(db)
    payload = {"counters": obs.default_counters(), "chats": {}, "day": {}}
    source = FakeQuantumSource([0.0])
    runner._random = source

    # action=silent БЕЗ обоснования — невалидный вердикт, а не «тихий отказ».
    await runner._act_on_opportunity(
        payload, "job-1", CHAT,
        {"opportunity": True, "action": "silent", "kind": "development",
         "horizon": "now", "goal": "x", "topic_key": "t"}, [])
    assert payload["counters"].get(obs.SKIP_PARSE_ERROR) == 1
    assert source.count() == 0

    # С обоснованием — легальное молчание, тоже без draw.
    await runner._act_on_opportunity(
        payload, "job-1", CHAT,
        {"opportunity": True, "action": "silent", "kind": "development",
         "horizon": "now", "goal": "x", "topic_key": "t",
         "veto_reason": "no_substance"}, [])
    assert payload["counters"].get("silent_decisions") == 1
    assert source.count() == 0
    assert await _decisions(db) == []
