"""QND-NONDET §1/§7 — пер-чатовое квантовое расписание смысловой проверки.

Предмет: момент следующей проверки выбирает ОДНО квантовое значение в
редактируемых границах, состояние durable и переживает рестарт, пропущенный
срок исполняется ровно один раз (или не исполняется вовсе, если слишком
старый), конкурентные прогоны не задваивают исполнение, выключенный модуль не
тратит значений.

Проверяются durable-строки `semantic_schedule` и durable-события, а не число
вызовов «для галочки». Время задаётся явно (`now=`), значения — управляемым
источником: ни гонок по часам, ни настоящего ANU.

TEST-LIFECYCLE: CONTRACT owner=qnd-nondet-2026-11-10
"""
from __future__ import annotations

import asyncio

import pytest

from services import chat_params
from services import hot_config
from services import initiative_observer as obs
from services import mca_events
from services import nostalgia_worker as nw
from services import quantum_publication as qp
from services import semantic_schedule as sched
from services.database import DatabaseService
from tests.qnd_fakes import FakeQuantumSource, RaisingModules

CHAT = -2701
CHAT2 = -2702
USER = 42
BOT_ID = 999
NOW = 1_800_000_000

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


def _caches(values: dict | None = None):
    base = {
        "memory.nostalgia_enabled": True,
        "flags.nostalgia_enabled": True,
        "flags.initiative_observer_enabled": True,
        "initiative.enabled": True,
        "initiative.frequency_profile": "active",
        "initiative.eval_min_messages": 1,
        "initiative.eval_min_interval_seconds": 0,
        "initiative.min_gap_seconds": 0,
        "initiative.max_replies_per_day": 10,
        "initiative.eval_llm_budget_per_day": 10,
        # Тихие часы выключены (никогда не «quiet»): тест проверяет арифметику
        # интервала, а не перенос из тихих часов.
        "memory.nostalgia_quiet_start_hour": 24,
        "memory.nostalgia_quiet_end_hour": 0,
    }
    base.update(values or {})
    hot_config.set_config_cache(_FakeHot(base))
    chat_params.set_chat_params_cache(_FakeChatParams({
        CHAT: dict(base), CHAT2: dict(base)}))


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


class _FakeStore:
    def __init__(self, chats):
        self.chats = list(chats)

    async def list_active_chat_ids(self):
        return list(self.chats)


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


async def _user_msg(db, text, ts, *, chat_id=CHAT):
    return await db.save_smart_message(USER, chat_id, text, None, int(ts),
                                       "text", "Вася")


async def _row(db, mechanism=sched.MECH_NOSTALGIA, chat_id=CHAT) -> dict:
    cursor = await db.db.execute(
        "SELECT * FROM semantic_schedule WHERE chat_id = ? AND mechanism = ?",
        (int(chat_id), mechanism))
    row = await cursor.fetchone()
    return dict(row) if row is not None else {}


async def _qnd_events(db, name: str) -> list[dict]:
    await mca_events.flush_events(db)
    cursor = await db.db.execute(
        "SELECT event_name, outcome, ts, usage_json FROM mca_events "
        "WHERE event_name = ? ORDER BY id", (name,))
    rows = []
    for row in await cursor.fetchall():
        import json
        try:
            payload = json.loads(row["usage_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        rows.append({"outcome": row["outcome"], **payload})
    return rows


def _worker(db, *, source=None, llm=None, bot=None, store=None) -> nw.NostalgiaWorker:
    worker = nw.NostalgiaWorker(
        db, store=store, llm=llm if llm is not None else _FakeLLM(),
        bot=bot if bot is not None else _FakeBot(), bot_id=BOT_ID)
    if source is not None:
        worker._random = source
    return worker


def _expected_delay(cadence: dict, u: float) -> float:
    lo = float(cadence["lo_adj"])
    hi = float(cadence["hi_adj"])
    shape = float(cadence["shape"])
    return lo + (hi - lo) * (u ** shape)


# ── §7: точные имена тестов ────────────────────────────────────────────────

async def _draw(source, db, mechanism=sched.MECH_NOSTALGIA, chat_id=CHAT,
                now=NOW):
    return await sched.draw_next(db, mechanism, chat_id, now=now,
                                 source=source, trigger=sched.TRIGGER_SCHEDULE)


async def test_per_chat_draws_use_quantum_and_differ_between_chats(db):
    _caches()
    source = FakeQuantumSource([0.05, 0.85])
    first = await _draw(source, db, chat_id=CHAT, now=NOW)
    second = await _draw(source, db, chat_id=CHAT2, now=NOW)

    assert first["u"] == pytest.approx(0.05)
    assert second["u"] == pytest.approx(0.85)
    assert first["source"] == "quantum"
    assert second["source"] == "quantum"
    assert first["next_due_ts"] != second["next_due_ts"]
    assert source.purposes() == ["nostalgia_schedule", "nostalgia_schedule"]

    draws = await _qnd_events(db, sched.EVENT_DRAW)
    assert len(draws) == 2
    assert {d["chat_id"] for d in draws} == {CHAT, CHAT2}
    assert all(d["trigger"] == "schedule" for d in draws)
    assert all(d["source"] == "quantum" for d in draws)
    assert all(d["provider"] for d in draws)
    assert all(d["next_due_ts"] for d in draws)


async def test_long_run_200_cycles_matches_scripted_source_and_has_no_fixed_interval(
        db):
    """200 циклов: срок = ровно арифметика от значения; интервалы не равны."""
    _caches()
    values = [((i * 37) % 100) / 100.0 for i in range(200)]
    source = FakeQuantumSource(values)
    stamp = NOW
    delays: list[int] = []
    for index, u in enumerate(values):
        cadence = await sched.resolve_cadence(db, sched.MECH_NOSTALGIA, CHAT,
                                             now=stamp)
        row = await sched.draw_next(db, sched.MECH_NOSTALGIA, CHAT, now=stamp,
                                    source=source,
                                    trigger=sched.TRIGGER_SCHEDULE)
        expected_delay = _expected_delay(cadence, u)
        assert row["delay_seconds"] == int(round(expected_delay))
        assert row["next_due_ts"] == stamp + int(round(expected_delay))
        assert cadence["lo_adj"] <= expected_delay <= cadence["hi_adj"]
        delays.append(row["delay_seconds"])
        stamp = int(row["next_due_ts"])
        assert index < 200
    assert len(set(delays)) > 50
    assert all(delays[i] != delays[i + 1] for i in range(len(delays) - 1))
    assert source.count("nostalgia_schedule") == 200


async def test_restart_keeps_next_due_and_executes_once(db, monkeypatch):
    """Рестарт: durable-строка авторитетна, срок не перевыводится."""
    _caches()
    await _user_msg(db, "привет", NOW - 7 * 86400)
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    source = FakeQuantumSource([0.5])
    first = await _draw(source, db, now=NOW)
    planned = int(first["next_due_ts"])

    # «Рестарт»: новый экземпляр воркера и новый heartbeat.
    restart_source = FakeQuantumSource([0.9])
    worker = _worker(db, source=restart_source)
    row = await sched.ensure(db, sched.MECH_NOSTALGIA, CHAT, now=NOW + 10)
    assert int(row["next_due_ts"]) == planned          # срок сохранён
    assert restart_source.count() == 0                  # draw не повторялся

    # Срок наступил — ровно одно исполнение и НОВЫЙ draw.
    due_now = planned + 5
    monkeypatch.setattr(nw, "_now_ts", lambda: due_now)
    out = await worker._run_chat(CHAT, due_now, manual=False)
    assert out["errors"] == 0
    after = await _row(db)
    assert int(after["last_check_ts"]) == due_now
    assert int(after["next_due_ts"]) != planned
    assert restart_source.count("nostalgia_schedule") == 1
    executed = [d for d in await _qnd_events(db, sched.EVENT_DUE)
                if d.get("executed")]
    assert len(executed) == 1


async def test_missed_deadline_executes_once_then_redraws(db, monkeypatch):
    _caches()
    await _user_msg(db, "привет", NOW - 7 * 86400)
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    source = FakeQuantumSource([0.5])
    first = await _draw(source, db, now=NOW)
    planned = int(first["next_due_ts"])

    late = planned + 300                    # опоздание меньше stale
    monkeypatch.setattr(nw, "_now_ts", lambda: late)
    worker = _worker(db, source=FakeQuantumSource([0.7]))
    out = await worker._run_chat(CHAT, late, manual=False)

    row = await _row(db)
    assert int(row["missed_count"]) == 1
    assert int(row["last_check_ts"]) == late
    assert int(row["next_due_ts"]) > late
    assert out["errors"] == 0
    # Ровно одно исполнение: повторный heartbeat на том же сроке ничего не
    # делает (срок уже перерисован).
    second = await worker._run_chat(CHAT, late, manual=False)
    assert second == {"candidates": 0, "sent": 0, "skipped": 0, "errors": 0}
    assert int((await _row(db))["last_check_ts"]) == late


async def test_stale_deadline_redraws_without_mass_send(db, monkeypatch):
    _caches({"limits.qnd_stale_seconds": 600})
    await _user_msg(db, "привет", NOW - 7 * 86400)
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    source = FakeQuantumSource([0.5])
    bot = _FakeBot()
    worker = _worker(db, source=source, bot=bot)
    first = await _draw(source, db, now=NOW)
    planned = int(first["next_due_ts"])

    very_late = planned + 4000              # > stale (600)
    monkeypatch.setattr(nw, "_now_ts", lambda: very_late)
    out = await worker._run_chat(CHAT, very_late, manual=False)

    assert bot.sent == []                    # массовой отправки нет
    assert out["sent"] == 0
    row = await _row(db)
    assert int(row["missed_count"]) == 1
    assert int(row["last_check_ts"] or 0) == 0     # НЕ исполняли
    assert int(row["next_due_ts"]) > very_late      # срок перерисован
    dues = await _qnd_events(db, sched.EVENT_DUE)
    assert dues[0]["executed"] is False
    assert dues[0]["reason_code"] == sched.REASON_STALE


async def test_concurrent_claim_yields_single_execution(db, monkeypatch):
    _caches()
    await _user_msg(db, "привет", NOW - 7 * 86400)
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    source = FakeQuantumSource([0.5])
    bot = _FakeBot()
    worker = _worker(db, source=source, bot=bot)
    first = await _draw(source, db, now=NOW)
    planned = int(first["next_due_ts"])

    late = planned + 10
    monkeypatch.setattr(nw, "_now_ts", lambda: late)
    won = await sched.claim(db, sched.MECH_NOSTALGIA, CHAT, now=late,
                            owner="worker-a")
    assert won is True
    lost = await sched.claim(db, sched.MECH_NOSTALGIA, CHAT, now=late,
                             owner="worker-b")
    assert lost is False
    dues = await _qnd_events(db, sched.EVENT_DUE)
    assert any(d.get("reason_code") == sched.REASON_LEASE_HELD for d in dues)

    # Второй прогон видит занятую аренду и ничего не исполняет.
    out = await worker._run_chat(CHAT, late, manual=False)
    assert out["sent"] == 0
    assert bot.sent == []


async def test_settings_change_clamps_without_execution(db, monkeypatch):
    _caches()
    await _user_msg(db, "привет", NOW - 7 * 86400)
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    source = FakeQuantumSource([0.999])
    row = await _draw(source, db, now=NOW)
    long_due = int(row["next_due_ts"])

    # Сужаем границы: старый срок выходит за новые.
    _caches({"limits.qnd_nostalgia_max_seconds": 1200,
             "limits.qnd_nostalgia_min_seconds": 600})
    adjusted = await sched.ensure(db, sched.MECH_NOSTALGIA, CHAT,
                                  now=NOW + 60)
    assert int(adjusted["next_due_ts"]) < long_due
    assert int(adjusted["last_check_ts"] or 0) == 0     # НЕ исполняли
    dues = await _qnd_events(db, sched.EVENT_DUE)
    assert dues[0]["executed"] is False
    assert dues[0]["reason_code"] == sched.REASON_SETTINGS_RESCALED


async def test_inactive_chat_intervals_longer_within_bounds(db):
    _caches()
    await _user_msg(db, "свежее сообщение", NOW - 60, chat_id=CHAT)
    await _user_msg(db, "старое сообщение", NOW - 10 * 86400, chat_id=CHAT2)
    source = FakeQuantumSource([0.5, 0.5])
    active = await _draw(source, db, chat_id=CHAT, now=NOW)
    silent = await _draw(source, db, chat_id=CHAT2, now=NOW)

    assert silent["delay_seconds"] > active["delay_seconds"]
    for row in (active, silent):
        cadence = await sched.resolve_cadence(db, sched.MECH_NOSTALGIA,
                                              row["chat_id"], now=NOW)
        assert cadence["lo_adj"] <= row["delay_seconds"] <= cadence["hi_adj"]


async def test_two_chats_are_independent(db):
    _caches()
    source = FakeQuantumSource([0.2, 0.8])
    first = await _draw(source, db, chat_id=CHAT, now=NOW)
    second = await _draw(source, db, chat_id=CHAT2, now=NOW)
    assert first["next_due_ts"] != second["next_due_ts"]
    assert int(first["chat_id"] if "chat_id" in first else CHAT) == CHAT

    # У каждого чата своя строка и свой срок; исполнение одного не двигает
    # второй.
    rows = await _qnd_events(db, sched.EVENT_DRAW)
    assert len({r["chat_id"] for r in rows}) == 2
    assert (await _row(db, chat_id=CHAT))["next_due_ts"] != \
        (await _row(db, chat_id=CHAT2))["next_due_ts"]
    assert await sched.due_chats(db, sched.MECH_NOSTALGIA,
                                 now=NOW + 1) == []


async def test_module_disabled_takes_no_draw_and_publishes_nothing(
        db, monkeypatch):
    _caches({"memory.nostalgia_enabled": False,
             "flags.nostalgia_enabled": False})
    await _user_msg(db, "привет", NOW - 7 * 86400)
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    source = FakeQuantumSource([0.5])
    bot = _FakeBot()
    worker = _worker(db, source=source, bot=bot,
                     store=_FakeStore([CHAT]))
    stats = await worker._run(manual=False)

    assert source.count() == 0                       # ни одного значения
    assert bot.sent == []
    assert stats["sent"] == 0
    assert await _row(db) == {}                      # строки нет вовсе


async def test_provider_failure_is_honest_not_quantum(db, monkeypatch):
    _caches()
    await _user_msg(db, "привет", NOW - 7 * 86400)
    monkeypatch.setattr(nw, "_now_ts", lambda: NOW)
    source = FakeQuantumSource(deferred_reason="provider_unavailable")
    bot = _FakeBot()
    worker = _worker(db, source=source, bot=bot)
    row = await sched.draw_next(db, sched.MECH_NOSTALGIA, CHAT, now=NOW,
                                source=source,
                                trigger=sched.TRIGGER_SCHEDULE)
    assert row["source"] == "unavailable"
    assert row["u"] is None
    assert row["fallback_reason"]
    assert int(row["next_due_ts"]) == NOW            # повтор на heartbeat

    draws = await _qnd_events(db, sched.EVENT_DRAW)
    assert draws[0]["source"] == "unavailable"
    assert draws[0]["u"] is None

    # Недоступный источник не публикует: решение = blocked, ничего не ушло.
    decision = await qp.decide(
        db, mechanism=qp.MECH_NOSTALGIA, chat_id=CHAT,
        factors={"r": 1.0}, source=FakeQuantumSource(
            deferred_reason="provider_unavailable"),
        candidate_ref="test", trigger=sched.TRIGGER_SCHEDULE, now=NOW)
    assert decision.publish is False
    assert decision.outcome == qp.OUTCOME_BLOCKED_RANDOM
    assert decision.source != "quantum"
    assert decision.silence_cause == qp.SILENCE_RANDOM_UNAVAILABLE
    assert bot.sent == []


async def test_no_pseudorandom_in_semantic_paths(db, monkeypatch):
    _caches()
    await _user_msg(db, "привет", NOW - 7 * 86400)
    source = FakeQuantumSource([0.42, 0.13])
    with RaisingModules(monkeypatch):
        row = await sched.draw_next(db, sched.MECH_NOSTALGIA, CHAT, now=NOW,
                                    source=source,
                                    trigger=sched.TRIGGER_SCHEDULE)
        decision = await qp.decide(
            db, mechanism=qp.MECH_NOSTALGIA, chat_id=CHAT,
            factors={"r": 1.0, "s": 1.0}, source=source,
            candidate_ref="test", trigger=sched.TRIGGER_SCHEDULE, now=NOW)
    assert row["source"] == "quantum"
    assert decision.source == "quantum"
    assert decision.value == pytest.approx(0.13)
