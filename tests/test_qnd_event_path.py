"""QND-NONDET §2/§7 — событийный путь: реальное пробуждение, а не сканер.

Живое сообщение ставит durable-сигнал и НЕМЕДЛЕННО запускает СУЩЕСТВУЮЩИЙ
Observer (`observe_tick(trigger="event", only_chat=…)`) — без второго Observer,
без словарных триггеров и без опроса текста. Сигнал ограничен: занятый чат
отбрасывается, дебаунс и минимум между платными оценками соблюдаются,
дедупликация и учёт отправок общие с плановым путём.

TEST-LIFECYCLE: CONTRACT owner=qnd-nondet-2026-11-10
"""
from __future__ import annotations

import asyncio
import json

import pytest

from services import chat_params
from services import hot_config
from services import initiative_observer as obs
from services import mca_events
from services import semantic_schedule as sched
from services.database import DatabaseService
from tests.qnd_fakes import FakeQuantumSource

CHAT = -2701
USER = 42
BOT_ID = 999
NOW = 1_800_000_000

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
    base = {
        "flags.initiative_observer_enabled": True,
        "initiative.enabled": True,
        "initiative.frequency_profile": "active",
        "initiative.eval_min_messages": 1,
        "initiative.eval_min_interval_seconds": 0,
        "initiative.min_gap_seconds": 0,
        "initiative.max_replies_per_day": 10,
        "initiative.eval_llm_budget_per_day": 10,
    }
    base.update(values or {})
    hot_config.set_config_cache(_FakeHot(base))
    chat_params.set_chat_params_cache(_FakeChatParams({CHAT: dict(base)}))


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
    def __init__(self, answer=None):
        self.answer = answer or json.dumps({
            "opportunity": True, "kind": "development", "action": "say",
            "horizon": "now", "goal": "участники обсуждают старое событие",
            "topic_key": "tema", "relevance": 0.9, "significance": 0.9,
            "rationale": "есть повод"}, ensure_ascii=False)
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return self.answer


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


async def _msg(db, text, ts):
    return await db.save_smart_message(USER, CHAT, text, None, int(ts),
                                       "text", "Вася")


async def _row(db, mechanism, chat_id=CHAT) -> dict:
    cursor = await db.db.execute(
        "SELECT * FROM semantic_schedule WHERE chat_id = ? AND mechanism = ?",
        (int(chat_id), mechanism))
    row = await cursor.fetchone()
    return dict(row) if row is not None else {}


# ── §7: точные имена тестов ────────────────────────────────────────────────

async def test_live_message_signal_starts_evaluation_with_trigger_event(
        db, monkeypatch):
    _caches()
    captured: list[dict] = []

    async def _fake_tick(db_, **kwargs):
        captured.append(dict(kwargs))
        return "completed"

    monkeypatch.setattr(obs, "observe_tick", _fake_tick)
    result = await sched.request_event(db, chat_id=CHAT,
                                       reason="live_message", now=NOW)

    assert result["requested"] is True
    assert result["dispatch"] == "dispatched"
    assert captured and captured[0]["trigger"] == "event"
    assert captured[0]["only_chat"] == CHAT
    # durable-метка поставлена ОБОИМ механизмам: расписание тоже увидит событие
    assert int((await _row(db, sched.MECH_INITIATIVE))["scan_requested_at"]) == NOW
    assert int((await _row(db, sched.MECH_NOSTALGIA))["scan_requested_at"]) == NOW

    # Тот же путь публикует СВОИМ транспортом: событийный прогон помечает
    # durable-событие `trigger="event"`, а не «schedule».
    runner = obs.InitiativeObserverRunner(db, trigger="event")
    runner._only_chat = CHAT
    assert await runner._schedule_due(CHAT, NOW) == "ok"
    await runner._complete_schedule(CHAT)
    await mca_events.flush_events(db)
    cursor = await db.db.execute(
        "SELECT usage_json FROM mca_events WHERE event_name = ? ORDER BY id",
        (sched.EVENT_DUE,))
    payloads = [json.loads(r["usage_json"] or "{}")
                for r in await cursor.fetchall()]
    assert payloads and payloads[0]["trigger"] == "event"
    assert payloads[0]["executed"] is True


async def test_event_dropped_when_chat_busy_and_per_chat_debounce(
        db, monkeypatch):
    _caches()
    captured: list[dict] = []

    async def _fake_tick(db_, **kwargs):
        captured.append(dict(kwargs))
        return "completed"

    monkeypatch.setattr(obs, "observe_tick", _fake_tick)

    # Занятый чат: durable-задача в статусе running → сигнал ОТБРОШЕН.
    await db.db.execute(
        "INSERT INTO task_jobs (job_id, owner, kind, coalesce_key, status, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("job-busy", obs.EVENT_OWNER, obs.EVENT_KIND,
         obs.event_coalesce_key(CHAT), obs.JOB_RUNNING, NOW, NOW))
    await db.db.commit()
    busy = await obs.dispatch_event(db, chat_id=CHAT, reason="live_message",
                                    now=NOW)
    assert busy == "event_dropped_busy"
    assert captured == []

    # Чат свободен, но только что была смысловая проверка → дебаунс.
    await db.db.execute("DELETE FROM task_jobs")
    await db.db.commit()
    runner = obs.InitiativeObserverRunner(db, trigger="event")
    runner._only_chat = CHAT
    monkeypatch.setattr(obs.sched.NOSTALGIA if False else sched, "ensure",
                        sched.ensure)
    source = FakeQuantumSource([0.5])
    await sched.draw_next(db, sched.MECH_INITIATIVE, CHAT, now=NOW,
                          source=source, trigger=sched.TRIGGER_SCHEDULE)
    await sched.mark_executed(db, sched.MECH_INITIATIVE, CHAT, now=NOW,
                              trigger=sched.TRIGGER_SCHEDULE)
    debounced = await obs.dispatch_event(db, chat_id=CHAT,
                                         reason="live_message", now=NOW + 5)
    assert debounced == "event_dropped_debounce"
    assert captured == []


async def test_event_path_respects_eval_budget_and_floor(db, monkeypatch):
    _caches()
    # Пол между платными оценками: последняя проверка была 60 с назад.
    await sched.draw_next(db, sched.MECH_INITIATIVE, CHAT, now=NOW - 3600,
                          source=FakeQuantumSource([0.5]),
                          trigger=sched.TRIGGER_SCHEDULE)
    await sched.mark_executed(db, sched.MECH_INITIATIVE, CHAT,
                              now=NOW - 200, trigger=sched.TRIGGER_SCHEDULE)
    code = await obs.dispatch_event(db, chat_id=CHAT, reason="live_message",
                                    now=NOW)
    assert code == "event_deferred_floor"

    # Оценка уважает тот же дневной бюджет, что и плановый путь.
    import time as _time
    stamp = int(_time.time())
    _caches({"initiative.eval_llm_budget_per_day": 1})
    runner = obs.InitiativeObserverRunner(
        db, bot=_FakeBot(), writer_service=object(), llm=_FakeLLM(),
        trigger="event")
    runner._only_chat = CHAT
    runner._random = FakeQuantumSource([0.0])
    entry = {"pending": 2, "last_eval_ts": 0, "recent_hashes": [],
             "topics": {}, "eval_day": stamp // 86400, "eval_day_count": 1}
    payload = {"counters": obs.default_counters(),
               "chats": {str(CHAT): entry}, "day": {}}
    await _msg(db, "разговор о старом событии", stamp - 120)
    entry["pending"] = 1
    await runner._evaluate_phase(payload, "job-1")
    assert payload["counters"]["evals"] == 0
    assert payload["counters"]["eval_skips"].get(obs.SKIP_EVAL_BUDGET) == 1
    assert runner._random.count() == 0


async def test_event_and_schedule_share_dedup_and_send_accounting(
        db, monkeypatch):
    _caches()
    from services import direct_chat_service as dcs
    deliveries: list[dict] = []

    async def _fake_handle(**kwargs):
        deliveries.append({k: v for k, v in kwargs.items()
                           if k in ("chat_id", "prepared_text")})
        return {"status": "sent"}

    monkeypatch.setattr(dcs, "handle_initiative", _fake_handle)
    import time as _time
    stamp = int(_time.time())
    await _msg(db, "разговор о старом событии", stamp - 120)
    await _msg(db, "обсуждение продолжается", stamp - 60)
    source = FakeQuantumSource(default=0.0)     # публикуем (u=0 → p > u)

    async def _run_once(trigger: str, *, state: dict | None = None,
                        reset_watermark: bool = False) -> dict:
        runner = obs.InitiativeObserverRunner(
            db, bot=_FakeBot(), writer_service=object(), llm=_FakeLLM(),
            trigger=trigger)
        runner._random = source
        if trigger == "event":
            runner._only_chat = CHAT
        if state is None:
            payload = {"counters": obs.default_counters(),
                       "chats": {str(CHAT): {"pending": 2, "last_eval_ts": 0,
                                             "recent_hashes": [], "topics": {},
                                             "eval_day": stamp // 86400,
                                             "eval_day_count": 0}},
                       "day": {}}
        else:
            payload = state
            payload["chats"][str(CHAT)]["pending"] = 2
        if reset_watermark:
            # «Рестарт потерял watermark»: контекст тот же, дедуп обязан
            # сработать по СОДЕРЖАНИЮ (общий для обеих веток).
            payload["chats"][str(CHAT)]["last_eval_msg_id"] = 0
            payload["chats"][str(CHAT)]["last_seen_msg_id"] = 0
        await runner._evaluate_phase(payload, "job-1")
        return payload

    # Плановый проход тоже наступает (срок в прошлом) — но контекст тот же.
    async def _make_schedule_due():
        await db.db.execute(
            "UPDATE semantic_schedule SET next_due_ts = ?, lease_until = 0 "
            "WHERE chat_id = ? AND mechanism = ?",
            (stamp - 1, CHAT, sched.MECH_INITIATIVE))
        await db.db.commit()

    first = await _run_once("event")
    await _make_schedule_due()
    second = await _run_once("schedule", state=first, reset_watermark=True)

    # Одна доставка на обе ветки: второй проход видит тот же контекст (дедуп).
    assert len(deliveries) == 1
    assert second["counters"]["sent"] == 1        # счётчики общие, доставка одна
    assert second["counters"]["eval_skips"].get(obs.SKIP_CONTEXT_DUP) == 1
    stamps = second["chats"][str(CHAT)].get("sent_stamps") or []
    assert len(stamps) == 1
    # Решение о публикации принималось ОДИН раз (второй проход до него не
    # дошёл вовсе) — дедуп и учёт общие.
    assert source.count("initiative_publication") == 1
