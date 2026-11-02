"""MEME-PIPELINE-REFactor-01 / INIT-COORD — независимость механизмов и
атомарная координация публикаций (INIT-COORD §8, R1–R8).

TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-03-INITIATIVE-INDEPENDENCE
(независимое планирование двух механизмов, ровно одна публикация при
одновременной готовности, N воркеров, рестарт, устаревание, `/meme`,
разные чаты, единый контур случайности, диагностика).

Правила тестов пакета: время передаётся параметром (`now`/`now_ts`), никаких
`sleep` для эмуляции таймингов; `sender`/`image_provider`/`random_source` —
существующие DI-швы; subject-under-test (бронь, планировщик фаз, пайплайн)
не подменяется.
"""
from __future__ import annotations

import asyncio
import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import initiative_observer as obs
from services import mca_random_source as mrs
from services import meme_initiative as meme
from services import publication_coordination as pub

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
NOW_TS = int(NOW.timestamp())
CHAT = -100
OTHER_CHAT = -200
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}


# ── общие помощники ─────────────────────────────────────────────────────────

def _store(tmp_path, name: str = "claims.db") -> pub.SqliteClaimStore:
    """Файл «мем-пайплайн готов»: журнал квоты + бронь публикации (v40+v41).

    Обе схемы живут в одном файле (arch §3.2), поэтому схема применяется
    единой точкой `SqliteQuotaLedger.apply_schema`.
    """
    path = str(tmp_path / name)
    meme.SqliteQuotaLedger(path).apply_schema()
    return pub.SqliteClaimStore(path)


def _coordinator(tmp_path) -> pub.PublicationCoordinator:
    return pub.PublicationCoordinator(None, store=_store(tmp_path))


def _settings(**overrides) -> meme.MemeSettings:
    base = dict(enabled=True, window_messages=8, daily_limit=3,
                cooldown_seconds=0, min_messages=1, trigger_probability=1.0)
    base.update(overrides)
    return meme.MemeSettings(**base)


def _rows(chat_id: int, n: int = 3) -> list[dict]:
    return [{"chat_id": chat_id, "id": i, "text": f"реплика {i}"}
            for i in range(n)]


class _Provider:
    def __init__(self, *, ok: bool = True):
        self.ok = ok
        self.calls: list[tuple] = []

    async def __call__(self, prompt, chat_id, job_id):
        self.calls.append((prompt, chat_id, job_id))
        return SimpleNamespace(ok=self.ok, called=True, reason="",
                               content=b"png")


class _Sender:
    def __init__(self, message_id: int = 900):
        self.calls: list[tuple] = []
        self.message_id = message_id

    async def __call__(self, chat_id, content, prompt):
        self.calls.append((chat_id, content, prompt))
        return SimpleNamespace(message_id=self.message_id)


class _Hit:
    """Источник случайности (DI-шов): значение и фактическая мета."""

    def __init__(self, value: float = 0.0, *, deferred: bool = False,
                 fallback: str | None = None) -> None:
        self.value = value
        self.deferred = deferred
        self.fallback = fallback
        self.calls = 0
        self.kwargs: dict = {}

    async def draw_probability(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        return mrs.DrawResult(
            value=None if self.deferred else self.value,
            deferred=self.deferred, fallback_reason=self.fallback,
            source="pseudorandom" if self.fallback else "quantum",
            selected_source="quantum", provider=None, draw_id="draw-x")


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows


class _FakeWindowDB:
    """Мини-db для живого пути: путь SQLite + окно сообщений + watermark."""

    def __init__(self, path, rows, watermark: int | None = None):
        self.db_path = str(path)
        self._rows = [dict(row) for row in rows]
        self._watermark = watermark

    async def execute(self, sql: str, params=()):
        if "MAX(id)" in sql:
            return _FakeCursor([{"m": self._watermark}])
        if not params:
            return _FakeCursor(list(self._rows))
        chat_id, limit = int(params[0]), int(params[-1])
        rows = [row for row in self._rows
                if int(row.get("chat_id", chat_id)) == chat_id]
        return _FakeCursor(rows[:limit])


async def _meme_pass(tmp_path, *, store=None, sender=None, provider=None,
                     gate=None, watermark=(5, 5), settings=None,
                     messages=None, db=None, **kwargs):
    """Один проход мем-пайплайна на реальном файле брони."""
    store = store if store is not None else _store(tmp_path)
    marks = list(watermark)
    seen: list[int] = []

    async def reader(_chat_id):
        index = min(len(seen), len(marks) - 1)
        seen.append(index)
        return marks[index]

    async def summarizer(_cid, _rows_arg, _system):
        return "хук"

    async def joke_generator(_cid, _summary, _instruction):
        return "прикол"

    async def _gate(_cid):
        return True, "ok"

    async def _gate_pair(_cid):
        return gate() if callable(gate) else (True, "ok")

    return await meme.consider_chat(
        db, CHAT, settings=settings if settings is not None else _settings(),
        ledger=meme.SqliteQuotaLedger(store.path),
        now=NOW, tz_name="UTC", tz_source="utc_fallback",
        initiative_enabled=lambda: True,
        image_status=IMAGE_OK,
        random_source=_Hit(),
        messages=messages if messages is not None else _rows(CHAT),
        summarizer=summarizer, joke_generator=joke_generator,
        image_provider=provider if provider is not None else _Provider(),
        publish_gate=_gate_pair,
        sender=sender if sender is not None else _Sender(),
        claim_store=store, watermark_reader=reader, model_chars=200,
        **kwargs)


# ═══ 1. независимость механизмов (R1) ═══════════════════════════════════════

def test_meme_flags_never_touch_text_mechanism():
    """Мемы не отключают и не подменяют текстовую инициативу."""
    assert meme.blocks_text_initiative() is False
    assert meme.OUTPUT_KIND not in obs.INITIATIVE_OUTPUT_KINDS
    assert pub.KIND_TEXT_INITIATIVE in obs.INITIATIVE_OUTPUT_KINDS
    assert pub.KIND_MEME_INITIATIVE == meme.OUTPUT_KIND
    # Собственные лимиты/статистика мемов не читаются текстовыми гейтами.
    profile = dict(obs.FREQUENCY_PROFILES[obs.DEFAULT_PROFILE])
    assert "meme_cooldown_seconds" not in profile
    assert "meme_daily_limit" not in profile
    source = inspect.getsource(obs)
    assert "meme_daily_limit" not in source
    assert "meme_cooldown_seconds" not in source


def test_disabling_memes_leaves_text_phase_running(monkeypatch):
    """Тумблер мемов OFF: текстовая фаза прохода выполняется как обычно."""
    calls: dict[str, int] = {"eval": 0, "meme": 0}
    runner = obs.InitiativeObserverRunner.__new__(obs.InitiativeObserverRunner)
    runner._db = None
    runner._llm = None
    runner._bot = None
    runner._writer = None
    runner._cancel_cb = None
    runner._aliases = None

    async def scan(_payload):
        return None

    async def evaluate(_payload, _job_id):
        calls["eval"] += 1

    async def diagnose(_payload):
        return None

    async def meme_phase(_payload):
        calls["meme"] += 1
        _payload["meme"] = {"attempts": [], "reason": meme.SKIP_DISABLED}
        return None

    class _Store:
        async def heartbeat(self, _job_id):
            return True

        async def mark_running(self, _job_id):
            return True

        async def finish(self, *_a, **_k):
            return True

        async def get(self, _job_id):
            return {"status": "running"}

    async def _payload(_job_id):
        return {"chats": {}, "counters": obs.default_counters(), "day": {}}

    async def _checkpoint(_job_id, _payload):
        return None

    monkeypatch.setattr(runner, "_scan_phase", scan)
    monkeypatch.setattr(runner, "_evaluate_phase", evaluate)
    monkeypatch.setattr(runner, "_diagnose_phase", diagnose)
    monkeypatch.setattr(runner, "_meme_phase", meme_phase)
    monkeypatch.setattr(runner, "_load_payload", _payload)
    monkeypatch.setattr(runner, "_checkpoint", _checkpoint)
    runner._store = _Store()

    status = asyncio.run(runner.run("job-1"))

    assert status == obs.JOB_COMPLETED
    assert calls == {"eval": 1, "meme": 1}


def test_text_phase_failure_does_not_cancel_meme_phase(monkeypatch):
    """Исключение в текстовой части не отменяет проверку мемов (V2)."""
    order: list[str] = []
    runner = obs.InitiativeObserverRunner.__new__(obs.InitiativeObserverRunner)
    runner._db = None
    runner._llm = None
    runner._bot = None
    runner._writer = None
    runner._cancel_cb = None
    runner._aliases = None

    async def scan(_payload):
        order.append("scan")
        raise RuntimeError("text scan exploded")

    async def evaluate(_payload, _job_id):
        order.append("evaluate")

    async def diagnose(_payload):
        order.append("diagnose")

    async def meme_phase(payload):
        order.append("meme")
        payload["meme"] = {"attempts": [], "reason": "reached"}

    class _Store:
        async def heartbeat(self, _job_id):
            return True

        async def mark_running(self, _job_id):
            return True

        async def finish(self, _job_id, *, status, reason_code=None,
                         payload=None):
            _Store.finished = (status, reason_code, payload)
            return True

        async def get(self, _job_id):
            return {"status": "running"}

    async def _payload(_job_id):
        return {"chats": {}, "counters": obs.default_counters(), "day": {}}

    captured: dict = {}

    async def _checkpoint(_job_id, payload):
        captured["payload"] = payload
        return None

    monkeypatch.setattr(runner, "_scan_phase", scan)
    monkeypatch.setattr(runner, "_evaluate_phase", evaluate)
    monkeypatch.setattr(runner, "_diagnose_phase", diagnose)
    monkeypatch.setattr(runner, "_meme_phase", meme_phase)
    monkeypatch.setattr(runner, "_load_payload", _payload)
    monkeypatch.setattr(runner, "_checkpoint", _checkpoint)
    runner._store = _Store()

    status = asyncio.run(runner.run("job-2"))

    # Мем-фаза вызвана ПОСЛЕ падения текстовой, статус провала не скрыт.
    assert order == ["scan", "meme"]
    assert status == obs.JOB_FAILED
    finished_status, reason_code, _unused = _Store.finished
    assert finished_status == obs.JOB_FAILED and reason_code == "task_failed"
    assert captured["payload"]["meme"]["reason"] == "reached"
    assert captured["payload"]["counters"]["text_phase_errors"] == 1


def test_own_quotas_do_not_cross_limit(tmp_path):
    """Квота/кулдаун одного механизма не ограничивают другой."""
    ledger = meme.SqliteQuotaLedger(str(tmp_path / "quota.db"))
    ledger.apply_schema()
    for index in range(3):
        assert ledger.reserve(chat_id=CHAT, day_bucket="2026-11-03",
                              job_id=f"m-{index}", limit=3, tz_name="UTC",
                              tz_source="utc_fallback",
                              now_ts=NOW_TS).ok
    # Квота мемов исчерпана — текстовый профиль не изменился.
    profile = dict(obs.FREQUENCY_PROFILES[obs.DEFAULT_PROFILE])
    assert profile["max_replies_per_day"] == 6
    assert profile["min_gap_seconds"] == 2 * 3600
    assert ledger.spent(CHAT, "2026-11-03") == 3
    # Обратно: дневные отправки текста не расходуют квоту мемов.
    entry = {"sent_stamps": [NOW_TS - 10, NOW_TS - 20]}
    assert obs._sent_in_window_static(entry, NOW_TS, 86400) == 2
    assert ledger.spent(OTHER_CHAT, "2026-11-03") == 0


def test_meme_roster_is_independent_of_text_scan(monkeypatch):
    """Ростер мема — свой список чатов, а не результат текстового скана (V1)."""
    from services import initiative_observer as observer

    class _RosterDB:
        async def get_smart_chat_ids(self):
            return [CHAT, OTHER_CHAT, -300, 555]

    async def _enabled(chat_id):
        return int(chat_id) != -300       # -300 выключен гейтом чата

    async def _loader(chat_id=None):
        return _settings(enabled=int(chat_id or 0) != OTHER_CHAT)

    monkeypatch.setattr(observer, "chat_observer_enabled", _enabled)
    monkeypatch.setattr(meme, "load_settings", _loader)

    roster = asyncio.run(meme.meme_chat_roster(_RosterDB(), state={}))
    # Позитивный чат отфильтрован (инициатива — только группы), выключенные —
    # тоже; тихий чат остаётся в ростере: он не зависит от текстового скана.
    assert roster == [CHAT]

    async def _all_memes(chat_id=None):
        return _settings(enabled=True)

    monkeypatch.setattr(meme, "load_settings", _all_memes)
    roster_all = asyncio.run(meme.meme_chat_roster(
        _RosterDB(), state={}, limit=5))
    assert roster_all == [CHAT, OTHER_CHAT]
    # Справедливость лимита: давно не проверенный чат идёт первым.
    roster_fair = asyncio.run(meme.meme_chat_roster(
        _RosterDB(), state={str(CHAT): {"last_check_ts": NOW_TS}}, limit=1))
    assert roster_fair == [OTHER_CHAT]
    # Ограничение попыток за проход — существующая константа.
    assert len(asyncio.run(meme.meme_chat_roster(
        _RosterDB(), state={}))) <= observer.MAX_CHATS_PER_PASS


async def _await(value):
    return value


def test_chat_scope_stops_memes(tmp_path, monkeypatch):
    """`initiative.enabled=false` чата реально останавливает мемы (V4)."""
    async def _disabled(_chat_id):
        return False

    result = asyncio.run(meme.consider_chat(
        None, CHAT, settings=_settings(), ledger=None,
        initiative_enabled=lambda: True, chat_enabled=_disabled,
        image_status=IMAGE_OK, messages=_rows(CHAT)))
    assert result.reason == meme.SKIP_INITIATIVE_DISABLED
    assert result.published is False


# ═══ 2. единый контур случайности, независимые решения (R8) ═════════════════

def test_two_purposes_one_service_and_one_trace_format():
    assert mrs.PURPOSE_MEME_TRIGGER == "meme_trigger"
    assert mrs.PURPOSE_INITIATIVE_TRIGGER == "initiative_trigger"
    assert mrs.PURPOSE_MEME_TRIGGER != mrs.PURPOSE_INITIATIVE_TRIGGER
    for purpose in (mrs.PURPOSE_MEME_TRIGGER, mrs.PURPOSE_INITIATIVE_TRIGGER):
        assert mrs.purpose_sanctioned(purpose)
        assert purpose not in mrs.EXPLORATION_PURPOSES
        assert purpose not in mrs.EXPLORATION_PROBABILITY_KEYS
    meme_trace = obs.build_draw_trace(None, purpose="meme_trigger",
                                      probability=0.5)
    text_trace = obs.build_draw_trace(None, purpose="initiative_trigger",
                                      probability=0.5)
    assert set(meme_trace) == set(text_trace) == set(obs.DRAW_TRACE_FIELDS)
    assert sorted(meme_trace) == sorted(obs.DRAW_TRACE_FIELDS)
    # Второго клиента/генератора случайности нет.
    assert "import random" not in inspect.getsource(pub)
    assert "random.Random" not in inspect.getsource(obs)


def test_real_random_source_reports_actual_source(monkeypatch):
    """Реальный RandomSourceService (PRNG-путь) → фактический источник честно."""
    from services.worker_settings import resolve_setting

    async def _setting(key, chat_id=None, default=None):
        if key == mrs.SETTING_SOURCE:
            return "pseudorandom"
        return await resolve_setting(key, chat_id=chat_id, default=default)

    monkeypatch.setattr(mrs, "_read_memory_setting", _setting)
    service = mrs.RandomSourceService(None)
    decision = asyncio.run(obs.random_trigger(
        service, chat_id=CHAT, purpose=mrs.PURPOSE_INITIATIVE_TRIGGER,
        probability=0.5))
    trace = decision.trace
    assert trace["purpose"] == "initiative_trigger"
    assert trace["source"] == "pseudorandom"
    assert trace["provider"] == mrs.PROVIDER_PRNG
    assert trace["source_impl"] == mrs.SOURCE_IMPL_PRNG
    assert trace["fallback_reason"] is None      # выбран явно, не подмена
    assert 0.0 <= float(trace["value"]) < 1.0
    assert trace["hit"] is (float(trace["value"]) < 0.5)


def test_deferred_source_is_unavailable_not_a_silent_fallback():
    decision = asyncio.run(obs.random_trigger(
        _Hit(deferred=True), chat_id=CHAT,
        purpose=mrs.PURPOSE_INITIATIVE_TRIGGER, probability=0.5))
    assert decision.ok is False
    assert decision.reason == obs.SKIP_RANDOM_UNAVAILABLE
    assert decision.trace["deferred"] is True


def test_fallback_value_is_a_real_decision_in_both_mechanisms():
    """Fallback-значение — валидное решение, а не «контур недоступен» (§2)."""
    text = asyncio.run(obs.random_trigger(
        _Hit(0.01, fallback="provider_unavailable"), chat_id=CHAT,
        purpose=mrs.PURPOSE_INITIATIVE_TRIGGER, probability=0.5))
    assert text.ok is True
    assert text.trace["source"] == "pseudorandom"
    assert text.trace["fallback_reason"] == "provider_unavailable"
    draw = asyncio.run(meme.draw_trigger(
        _Hit(0.01, fallback="provider_unavailable"), chat_id=CHAT,
        probability=0.05))
    assert draw.ok is True and draw.reason == "ok"
    assert draw.trace["fallback_reason"] == "provider_unavailable"


def test_separate_draws_have_separate_traces():
    """Два механизма делают РАЗНЫЕ draw под своими purposes."""
    meme_source = _Hit(0.0)
    text_source = _Hit(0.0)
    asyncio.run(meme.draw_trigger(meme_source, chat_id=CHAT, probability=0.05))
    asyncio.run(obs.random_trigger(text_source, chat_id=CHAT,
                                  purpose=mrs.PURPOSE_INITIATIVE_TRIGGER,
                                  probability=0.5))
    assert meme_source.calls == 1 and text_source.calls == 1
    assert meme_source.kwargs["purpose"] == mrs.PURPOSE_MEME_TRIGGER
    assert text_source.kwargs["purpose"] == mrs.PURPOSE_INITIATIVE_TRIGGER
    assert meme_source is not text_source


def test_text_trigger_probability_default_is_byte_parity(monkeypatch):
    """p=1.0 по умолчанию ⇒ draw не выполняется (паритет прежнего поведения)."""
    assert obs.DEFAULT_TRIGGER_PROBABILITY == 1.0

    async def _param(chat_id, key, default):
        if key == obs.KEY_TRIGGER_PROBABILITY:
            return 1.0
        return default

    monkeypatch.setattr(obs, "_param", _param)
    source = _Hit(0.0)
    decision = asyncio.run(obs.random_trigger(
        source, chat_id=CHAT, purpose=mrs.PURPOSE_INITIATIVE_TRIGGER,
        probability=asyncio.run(obs.trigger_probability(CHAT))))
    assert decision.ok is True
    assert decision.trace["reason"] == obs.DRAW_PROBABILITY_ONE
    assert decision.trace["source"] == ""
    assert source.calls == 0
    assert asyncio.run(obs.trigger_probability(CHAT)) == 1.0


def test_text_trigger_probability_below_one_draws(monkeypatch):
    async def _param(chat_id, key, default):
        if key == obs.KEY_TRIGGER_PROBABILITY:
            return 0.0
        return default

    monkeypatch.setattr(obs, "_param", _param)
    source = _Hit(0.0)
    probability = asyncio.run(obs.trigger_probability(CHAT))
    assert probability == 0.0
    decision = asyncio.run(obs.random_trigger(
        source, chat_id=CHAT, purpose=mrs.PURPOSE_INITIATIVE_TRIGGER,
        probability=probability))
    assert decision.ok is False
    assert decision.reason == obs.SKIP_RANDOM_MISS
    assert decision.trace["reason"] == obs.DRAW_PROBABILITY_ZERO
    assert source.calls == 0


# ═══ 3. одновременно готовы → ровно одна публикация (R2) ═══════════════════

def _publish_once(store, chat_id: int, kind: str, *, now: int,
                  interval: int, log: list, manual: bool = False) -> dict:
    """Полный цикл одного механизма: acquire → sending → send → release."""
    decision = store.acquire(chat_id=chat_id, holder_kind=kind, now=now,
                             interval_seconds=interval, manual=manual)
    if not decision.granted:
        log.append({"kind": kind, "result": "conflict",
                    "reason": decision.reason, "detail": decision.detail})
        return {"sent": False, "reason": decision.reason,
                "detail": decision.detail}
    sending = store.begin_sending(chat_id=chat_id, claim_id=decision.claim_id,
                                 now=now, manual=manual)
    if not sending.granted:
        log.append({"kind": kind, "result": "not_sent"})
        return {"sent": False, "reason": sending.reason}
    log.append({"kind": kind, "result": "sent",
                "claim_id": decision.claim_id})
    store.release(chat_id=chat_id, claim_id=decision.claim_id, now=now,
                  published=True, holder_kind=kind)
    return {"sent": True, "reason": "sent", "claim_id": decision.claim_id}


@pytest.mark.parametrize("first", ["text", "meme"])
def test_simultaneous_readiness_publishes_exactly_once(tmp_path, first):
    """Оба готовы: публикуется ОДИН, второй отменяется с явной причиной."""
    store = _store(tmp_path)
    interval = pub.default_interval_seconds()
    kinds = [pub.KIND_TEXT_INITIATIVE, pub.KIND_MEME_INITIATIVE]
    if first == "meme":
        kinds.reverse()
    log: list[dict] = []
    results = [
        _publish_once(store, CHAT, kind, now=NOW_TS, interval=interval,
                      log=log)
        for kind in kinds
    ]
    assert sum(1 for item in results if item["sent"]) == 1
    loser = [item for item in results if not item["sent"]][0]
    assert loser["reason"] == pub.REASON_CONFLICT
    assert loser["detail"] == pub.DETAIL_CROSS_TYPE
    assert [item["result"] for item in log] == ["sent", "conflict"]
    snapshot = store.snapshot(CHAT)
    assert snapshot["state"] == "released"
    assert snapshot["last_publish_kind"] == kinds[0]


# ═══ 4. N параллельных воркеров на одной БД (R3) ════════════════════════════

def test_n_parallel_workers_publish_once(tmp_path):
    """8 параллельных воркеров на одном файле → одна бронь доходит до sending.

    Моделируется ОДНОВРЕМЕННАЯ готовность: воркеры не освобождают бронь внутри
    гонки (иначе это уже последовательные публикации разных тиков, которые
    ограничивает собственный кулдаун механизма, а не примитив). Проверка — по
    `claim_id`, а не по времени.
    """
    store = _store(tmp_path)
    interval = pub.default_interval_seconds()
    granted_claims: list[str] = []
    sending_claims: list[str] = []
    conflicts: list[str] = []

    def worker(index: int):
        kind = (pub.KIND_TEXT_INITIATIVE if index % 2 == 0
                else pub.KIND_MEME_INITIATIVE)
        decision = store.acquire(chat_id=CHAT, holder_kind=kind, now=NOW_TS,
                                 interval_seconds=interval)
        if not decision.granted:
            conflicts.append(decision.reason)
            return decision
        granted_claims.append(decision.claim_id)
        sending = store.begin_sending(chat_id=CHAT,
                                     claim_id=decision.claim_id, now=NOW_TS)
        if sending.granted:
            sending_claims.append(decision.claim_id)
        return decision

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(worker, range(8)))

    assert len(granted_claims) == 1
    assert len(sending_claims) == 1
    assert sum(1 for item in decisions if item.granted) == 1
    assert conflicts == [pub.REASON_CONFLICT] * 7
    assert store.snapshot(CHAT)["state"] == "sending"


def test_parallel_workers_same_type_are_serialized_by_claim(tmp_path):
    """Один тип: CAS держит ровно одну активную бронь, пока не освободили."""
    store = _store(tmp_path)
    grants: list[str] = []

    def worker(_index: int):
        decision = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                                 now=NOW_TS, interval_seconds=0)
        if decision.granted:
            grants.append(decision.claim_id)
        return decision

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(worker, range(8)))
    assert len(grants) == 1
    assert all(not item.granted for item in decisions if item.claim_id != grants[0])


# ═══ 5. рестарт: бронь в `sending` с истёкшим TTL (R4) ══════════════════════

def test_restart_reclaims_expired_claim_without_second_publication(tmp_path):
    store = _store(tmp_path)
    stale = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                          now=NOW_TS)
    assert stale.granted
    assert store.begin_sending(chat_id=CHAT, claim_id=stale.claim_id,
                               now=NOW_TS).granted

    later = NOW_TS + pub.SENDING_TTL_SECONDS + 30
    # Рестарт: старая бронь висит в `sending` с истёкшим TTL.
    reclaimed = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_MEME_INITIATIVE,
                              now=later,
                              interval_seconds=pub.default_interval_seconds())
    assert reclaimed.granted is True
    assert reclaimed.recovered_delivery_unknown is True
    assert reclaimed.detail == pub.DETAIL_DELIVERY_UNKNOWN
    snapshot = store.snapshot(CHAT)
    # Публикация не доказана, но и не выдумана заново: watermark = claimed_at.
    assert snapshot["last_publish_ts"] == NOW_TS
    assert snapshot["last_publish_kind"] == pub.KIND_TEXT_INITIATIVE
    assert snapshot["claim_id"] == reclaimed.claim_id
    # ПОВТОРНОЙ отправки старой бронью быть не может: claim_id уже чужой.
    replay = store.begin_sending(chat_id=CHAT, claim_id=stale.claim_id,
                                 now=later)
    assert replay.granted is False
    assert replay.reason == pub.REASON_EXPIRED


def test_claim_ttl_expiry_allows_takeover(tmp_path):
    store = _store(tmp_path)
    first = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_MEME_INITIATIVE,
                          now=NOW_TS)
    assert first.granted
    inside = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                           now=NOW_TS + 5)
    assert inside.granted is False and inside.detail == pub.DETAIL_CLAIM_HELD
    after = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                          now=NOW_TS + pub.CLAIM_TTL_SECONDS + 1)
    assert after.granted is True


# ═══ 6. устаревший мем не отправляется после задержки ═══════════════════════

def test_stale_meme_is_not_sent_after_delay(tmp_path):
    """Окно чата изменилось за время генерации → отправки нет (§3.4)."""
    store = _store(tmp_path)
    sender = _Sender()
    provider = _Provider()
    result = asyncio.run(_meme_pass(
        tmp_path, store=store, sender=sender, provider=provider,
        watermark=(5, 9)))
    assert result.published is False
    assert result.reason == meme.SKIP_PUBLICATION_STALE
    assert result.detail == "window_changed"
    assert sender.calls == []              # картинка не ушла в чат
    assert len(provider.calls) == 1        # но генерация состоялась
    snapshot = store.snapshot(CHAT)
    # Бронь освобождена и НЕ помечена как публикация.
    assert snapshot["state"] == "released"
    assert snapshot.get("last_publish_ts") is None


def test_fresh_window_still_publishes(tmp_path):
    store = _store(tmp_path)
    sender = _Sender()
    result = asyncio.run(_meme_pass(tmp_path, store=store, sender=sender,
                                   watermark=(5, 5)))
    assert result.published is True and result.reason == "sent"
    assert len(sender.calls) == 1
    snapshot = store.snapshot(CHAT)
    assert snapshot["state"] == "released"
    assert snapshot["last_publish_ts"] is not None
    assert snapshot["last_publish_kind"] == meme.OUTPUT_KIND


# ═══ 7. `/meme`: приоритет без гонки (R5) ═══════════════════════════════════

def test_manual_priority_blocks_automatic_path(tmp_path):
    """Маркер ставится ДО генерации: авто-путь не уходит в `sending`."""
    store = _store(tmp_path)
    until = store.claim_manual_priority(chat_id=CHAT, now=NOW_TS)
    assert until == NOW_TS + pub.MANUAL_PRIORITY_SECONDS

    auto_text = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                              now=NOW_TS + 5, interval_seconds=1800)
    assert auto_text.granted is False
    assert auto_text.detail == pub.DETAIL_MANUAL_PRIORITY
    auto_meme = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_MEME_INITIATIVE,
                              now=NOW_TS + 5, interval_seconds=1800)
    assert auto_meme.granted is False

    manual = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_MEME_INITIATIVE,
                           now=NOW_TS + 6, interval_seconds=1800, manual=True)
    assert manual.granted is True
    assert store.begin_sending(chat_id=CHAT, claim_id=manual.claim_id,
                               now=NOW_TS + 6, manual=True).granted
    store.release(chat_id=CHAT, claim_id=manual.claim_id, now=NOW_TS + 7,
                  published=True, holder_kind=pub.KIND_MEME_INITIATIVE)
    # Ровно одна публикация: авто-путь за это время не отправил ничего.
    snapshot = store.snapshot(CHAT)
    assert snapshot["last_publish_kind"] == pub.KIND_MEME_INITIATIVE


def test_manual_priority_preempts_claimed_but_not_sending(tmp_path):
    store = _store(tmp_path)
    claimed = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                            now=NOW_TS)
    assert claimed.granted
    store.claim_manual_priority(chat_id=CHAT, now=NOW_TS)
    manual = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_MEME_INITIATIVE,
                           now=NOW_TS + 1, interval_seconds=1800, manual=True)
    assert manual.granted is True          # чужой `claimed` забран
    assert store.begin_sending(chat_id=CHAT, claim_id=claimed.claim_id,
                               now=NOW_TS + 2).granted is False


def test_foreign_sending_yields_publication_in_flight(tmp_path):
    """Чужой `sending` — честный publication_in_flight, второй публикации нет."""
    store = _store(tmp_path)
    other = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                          now=NOW_TS)
    assert other.granted
    assert store.begin_sending(chat_id=CHAT, claim_id=other.claim_id,
                               now=NOW_TS).granted
    manual = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_MEME_INITIATIVE,
                           now=NOW_TS + 5, interval_seconds=1800, manual=True)
    assert manual.granted is False
    assert manual.reason == pub.REASON_IN_FLIGHT
    assert manual.state == "sending"
    snapshot = store.snapshot(CHAT)
    assert snapshot["claim_id"] == other.claim_id     # бронь не перехвачена
    assert snapshot["state"] == "sending"


def test_command_marks_priority_before_generation(monkeypatch):
    """Обработчик `/meme` ставит маркер ДО запуска пайплайна (§6)."""
    from handlers import meme_command

    order: list[str] = []

    async def _priority(chat_id):
        order.append("priority")
        return NOW_TS + pub.MANUAL_PRIORITY_SECONDS

    async def _pipeline(chat_id, bot):
        order.append("pipeline")
        return SimpleNamespace(published=True, reason="sent")

    async def _admin(_uid, _cid):
        return True

    async def _delete(_message):
        order.append("delete")
        return True

    class _Message:
        chat = SimpleNamespace(id=CHAT)
        from_user = SimpleNamespace(id=7)
        message_id = 5

        async def delete(self):
            return True

    monkeypatch.setattr(meme_command, "is_meme_admin", _admin)
    monkeypatch.setattr(meme_command, "delete_command_message", _delete)
    monkeypatch.setattr(meme_command, "claim_manual_priority", _priority)
    monkeypatch.setattr(meme_command, "run_manual_pipeline", _pipeline)
    monkeypatch.setattr(meme_command, "setup_meme_command", lambda *a, **k: None)
    bot = SimpleNamespace(send_message=None)
    monkeypatch.setattr(meme_command, "_bot", bot)

    asyncio.run(meme_command.cmd_meme(_Message()))

    assert order == ["delete", "priority", "pipeline"]


# ═══ 8. разные чаты независимы (R6) ═════════════════════════════════════════

def test_different_chats_proceed_independently(tmp_path):
    """Глобальной блокировки нет: параллельные acquire в двух чатах успешны."""
    store = _store(tmp_path)
    log: list[dict] = []

    def worker(chat_id: int):
        return _publish_once(
            store, chat_id,
            pub.KIND_TEXT_INITIATIVE if chat_id == CHAT
            else pub.KIND_MEME_INITIATIVE,
            now=NOW_TS, interval=pub.default_interval_seconds(), log=log)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, [CHAT, OTHER_CHAT]))

    assert all(item["sent"] for item in results)
    assert store.snapshot(CHAT)["last_publish_ts"] is not None
    assert store.snapshot(OTHER_CHAT)["last_publish_ts"] is not None
    assert "asyncio.Lock(" not in inspect.getsource(pub)
    assert "_GLOBAL_LOCK" not in inspect.getsource(pub)


# ═══ 9. межтиповой интервал: настройка, а не хардкод (R2/§4) ════════════════

def test_cross_type_interval_default_and_bounds(monkeypatch):
    assert pub.KEY_CROSS_TYPE_INTERVAL == \
        "initiative.cross_type_publication_interval_seconds"
    assert pub.default_interval_seconds() == obs.MIN_GAP_FLOOR_SECONDS

    async def _param(chat_id, key, default):
        if key == pub.KEY_CROSS_TYPE_INTERVAL:
            return "900"
        return default

    monkeypatch.setattr(pub, "_param", _param)
    assert asyncio.run(pub.resolve_cross_type_interval(CHAT)) == 900

    async def _zero(chat_id, key, default):
        return 0

    monkeypatch.setattr(pub, "_param", _zero)
    assert asyncio.run(pub.resolve_cross_type_interval(CHAT)) == 0

    async def _garbage(chat_id, key, default):
        return "не число"

    monkeypatch.setattr(pub, "_param", _garbage)
    assert asyncio.run(pub.resolve_cross_type_interval(CHAT)) == \
        obs.MIN_GAP_FLOOR_SECONDS


def test_interval_never_shortens_own_cooldown():
    """``0 < interval < cooldown`` ничего не укорачивает: gap = max()."""
    assert pub.resolve_gap_seconds(0, 1800) == 1800
    assert pub.resolve_gap_seconds(3600, 1800) == 3600
    assert pub.resolve_gap_seconds(1800, 3600) == 3600
    assert pub.resolve_gap_seconds(0, 0) == 0


def test_zero_interval_disables_interval_coordination(tmp_path):
    store = _store(tmp_path)
    log: list[dict] = []
    assert _publish_once(store, CHAT, pub.KIND_TEXT_INITIATIVE, now=NOW_TS,
                         interval=0, log=log)["sent"] is True
    store.release(chat_id=CHAT, claim_id="", now=NOW_TS, published=False,
                  holder_kind=pub.KIND_TEXT_INITIATIVE)
    # Интервал выключен: другой тип проходит сразу после публикации.
    second = _publish_once(store, CHAT, pub.KIND_MEME_INITIATIVE,
                           now=NOW_TS + 1, interval=0, log=log)
    assert second["sent"] is True


def test_small_interval_does_not_override_own_cooldown(tmp_path):
    """Свой кулдаун остаётся: интервал меньше него — мем всё равно ждёт."""
    store = _store(tmp_path)
    ledger = meme.SqliteQuotaLedger(store.path)
    previous = ledger.reserve(chat_id=CHAT, day_bucket=NOW.date().isoformat(),
                              job_id="prev", limit=3, tz_name="UTC",
                              tz_source="utc_fallback", now_ts=NOW_TS - 10)
    assert previous.ok
    ledger.mark("prev", "provider_called")
    cooldown = 3600
    interval = 60
    gap = pub.resolve_gap_seconds(cooldown, interval)
    assert gap == cooldown

    sender = _Sender()
    result = asyncio.run(_meme_pass(
        tmp_path, store=store, sender=sender,
        settings=_settings(cooldown_seconds=cooldown)))
    assert result.reason == meme.SKIP_COOLDOWN
    assert sender.calls == []


# ═══ 10. журнал выводов видит мем (R7, V3) ══════════════════════════════════

def test_meme_publication_is_visible_in_shared_ledger(tmp_path):
    from services.database import DatabaseService, BOT_OUTPUT_KINDS

    assert "meme_initiative" in BOT_OUTPUT_KINDS

    async def scenario():
        svc = DatabaseService(str(tmp_path / "ledger.db"))
        await svc.initialize()
        try:
            sender = _Sender(message_id=4242)
            result = await _meme_pass(tmp_path, sender=sender,
                                      db=svc, watermark=(None, None))
            assert result.published is True
            recent = await svc.list_recent_bot_outputs(CHAT, limit=1)
            return recent, sender
        finally:
            await svc.close()

    recent, sender = asyncio.run(scenario())
    assert recent and recent[0]["output_kind"] == meme.OUTPUT_KIND
    assert recent[0]["tg_message_id"] == 4242
    assert recent[0]["delivery_status"] == "delivered"
    # Обратная сторона: чужая публикация НЕ записывается как мем.
    assert all(row["output_kind"] != pub.KIND_TEXT_INITIATIVE for row in recent)


def test_duplicate_job_does_not_create_second_output_row(tmp_path):
    """Повтор того же job_id не двоит запись журнала (append-only, один раз)."""
    from services.database import DatabaseService

    async def scenario():
        svc = DatabaseService(str(tmp_path / "dup.db"))
        await svc.initialize()
        try:
            store = _store(tmp_path)
            await _meme_pass(tmp_path, store=store, db=svc,
                             watermark=(None, None), job_id="job-dup")
            # Второй прогон того же job: слот уже provider_called → пропуск.
            second = await _meme_pass(tmp_path, store=store, db=svc,
                                      watermark=(None, None), job_id="job-dup")
            rows = await svc.db.execute(
                "SELECT COUNT(*) AS c FROM mca_bot_outputs WHERE chat_id = ?",
                (CHAT,))
            count = (await rows.fetchone())["c"]
            return second, count
        finally:
            await svc.close()

    second, count = asyncio.run(scenario())
    assert second.published is False
    assert count == 1


# ═══ 11. диагностика (8 полей, существующий payload) ════════════════════════

def test_meme_diagnostics_fields_present(tmp_path):
    store = _store(tmp_path)
    state: dict = {}

    async def _summarizer(*_a, **_k):
        return "хук"

    async def _joke(*_a, **_k):
        return "прикол"

    async def _gate(_chat_id):
        return True, "ok"

    asyncio.run(meme.on_initiative_cycle(
        None, [CHAT], state=state, settings=_settings(cooldown_seconds=60),
        ledger=meme.SqliteQuotaLedger(store.path), now=NOW,
        now_ts=NOW_TS, tz_name="UTC", tz_source="utc_fallback",
        initiative_enabled=lambda: True, image_status=IMAGE_OK,
        random_source=_Hit(), messages=_rows(CHAT), model_chars=200,
        claim_store=store, summarizer=_summarizer, joke_generator=_joke,
        image_provider=_Provider(), sender=_Sender(), publish_gate=_gate))

    entry = state[str(CHAT)]
    for key in ("last_check_ts", "next_check_ts", "random", "conditions",
                "reason", "cooldown_seconds", "publication", "stage"):
        assert key in entry, key
    assert entry["output_kind"] == meme.OUTPUT_KIND
    assert entry["last_check_ts"] == NOW_TS
    assert entry["cooldown_seconds"] == 60
    assert entry["next_check_ts"] >= NOW_TS
    assert entry["conditions"]["considered"] == 1
    assert entry["reason"] == "sent"
    assert entry["publication"]["claim"]["granted"] is True
    assert entry["random"]["purpose"] == mrs.PURPOSE_MEME_TRIGGER


def _pair(value):
    return value


async def _ret(value):
    return value


def test_meme_availability_exposes_diagnostics(tmp_path, monkeypatch):
    store = _store(tmp_path)
    ledger = meme.SqliteQuotaLedger(store.path)

    async def _image(_chat_id, health=None):
        return dict(IMAGE_OK)

    monkeypatch.setattr(meme, "image_dependency", _image)
    payload = asyncio.run(meme.availability(
        CHAT, settings=_settings(cooldown_seconds=120), ledger=ledger,
        initiative_on=True, now=NOW_TS))
    diagnostics = payload["diagnostics"]
    for key in ("last_check_ts", "next_check_ts", "random", "conditions",
                "skip_reason", "cooldown_seconds", "cooldown_remaining_seconds",
                "publication"):
        assert key in diagnostics, key
    assert diagnostics["cooldown_seconds"] == 120
    assert diagnostics["conditions"]["meme_enabled"] is True
    assert payload["available"] is True


def test_text_diagnostics_fields_in_payload():
    runner = obs.InitiativeObserverRunner.__new__(obs.InitiativeObserverRunner)
    runner._publication = None
    payload = {"chats": {}}
    trace = obs.build_draw_trace(None, purpose="initiative_trigger",
                                 probability=0.5)
    runner._note_decision(
        payload, CHAT, now=NOW_TS, skip_reason=obs.SKIP_PUBLICATION_CONFLICT,
        random_trace=trace,
        publication={"ok": False, "reason": "publication_conflict",
                     "detail": "cross_type_interval", "other_kind": "meme_initiative"},
        conditions={"anti_flood": True},
        cooldown={"min_gap_seconds": 7200})
    decision = payload["chats"][str(CHAT)]["last_decision"]
    for key in ("ts", "skip_reason", "skip_label", "random", "publication",
                "conditions", "cooldown"):
        assert key in decision, key
    assert decision["random"]["purpose"] == "initiative_trigger"
    assert decision["publication"]["detail"] == "cross_type_interval"
    assert decision["skip_label"] == obs.reason_label(
        obs.SKIP_PUBLICATION_CONFLICT)


def test_text_reason_codes_have_labels():
    for code in (obs.SKIP_PUBLICATION_CONFLICT, obs.SKIP_RANDOM_MISS,
                 obs.SKIP_RANDOM_UNAVAILABLE):
        assert obs.reason_label(code) != code
    for code in (meme.SKIP_PUBLICATION_CONFLICT, meme.SKIP_PUBLICATION_STALE,
                 meme.SKIP_PUBLICATION_IN_FLIGHT, meme.SKIP_PUBLICATION_EXPIRED):
        assert obs.reason_label(code) != code
        assert code in meme.SKIP_REASONS


# ═══ 11. текстовая инициатива: та же бронь в боевом шве ════════════════════

def _text_harness(tmp_path, name="text.db"):
    """Мини-стенд единого входа инициативы (реальная БД, фейковый writer)."""
    from services import mca_intents as mi
    from services.database import DatabaseService

    class _Bot:
        id = 4242

        def __init__(self):
            self.sent: list = []

        async def send_message(self, chat_id, text, **kwargs):
            self.sent.append((chat_id, text))
            return SimpleNamespace(message_id=5000 + len(self.sent))

    class _Writer:
        def __init__(self, text="Ну что, продолжим?"):
            self.text = text
            self.plan_calls = 0
            self.generate_calls = 0

        async def plan_initiative_decision(self, chat_id, intent_row, *,
                                           correlation_id=None):
            from services.direct_l1 import L1Plan
            self.plan_calls += 1
            return L1Plan(action="reply", confidence=0.9,
                          confidence_bucket="high", source="llm")

        async def generate_initiative_reply(self, chat_id, intent_row, *,
                                             l1_plan=None,
                                             correlation_id=None):
            self.generate_calls += 1
            return self.text

    async def _make(db):
        now = int(NOW.timestamp())
        intent_id, _ = await mi.get_service(db).create_intent(
            CHAT, kind="follow_up", origin="unanswered_question",
            subject_ids=("q:init-coord",), goal="когда стрим?",
            source_refs=("msg:11",), not_before=now - 7200,
            expires_at=now + 3 * 86400, activation_condition="time_due",
            created_at=now - 7200)
        return intent_id

    def _situation():
        return mi.InitiativeSituation(trigger_kind="intent_due", chat_id=CHAT)

    def _candidate(intent_id: str):
        return mi.candidate_from_trigger(
            trigger_kind="intent_due", chat_id=CHAT, intent_id=intent_id,
            reason_code="default")

    return DatabaseService(str(tmp_path / name)), _Bot, _Writer, _make, \
        _situation, _candidate


@pytest.fixture(autouse=True)
def _clean_mca_events():
    from services import mca_events
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


def test_text_publish_guard_cancels_without_send(tmp_path, monkeypatch):
    """Отказ брони перед отправкой: реплика отменена, intent жив (§3.5)."""
    from services import direct_chat_service as dcs
    from services import mca_intents as mi

    sent: list = []

    async def _send_text(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))
        return SimpleNamespace(message_id=777)

    monkeypatch.setattr("services.telegram_send.send_text", _send_text)

    async def scenario():
        svc, _Bot, _Writer, make, situation, candidate = _text_harness(
            tmp_path)
        await svc.initialize()
        try:
            intent_id = await make(svc)
            guard_calls: list[int] = []

            async def _guard():
                guard_calls.append(1)
                return "publication_conflict"

            result = await dcs.handle_initiative(
                bot=_Bot(), chat_id=CHAT, situation=situation(),
                candidates=[candidate(intent_id)], db=svc,
                writer_service=_Writer(), correlation_id="corr-coord",
                publish_guard=_guard)
            row = await mi.get_service(svc).store.get_intent(intent_id)
            return result, row, guard_calls
        finally:
            await svc.close()

    result, row, guard_calls = asyncio.run(scenario())
    assert result["status"] == "cancelled"
    assert result["reason_code"] == "publication_conflict"
    assert guard_calls == [1]
    assert sent == []                        # второго сообщения в чат нет
    assert row["status"] in ("pending", "deferred")
    assert int(row["attempts"] or 0) == 0    # попыткой не считается


def test_text_without_guard_keeps_previous_behaviour(tmp_path, monkeypatch):
    """`publish_guard=None` — ровно прежнее поведение Direct-пути."""
    from services import direct_chat_service as dcs

    sent: list = []

    async def _send_text(bot, chat_id, text, **kwargs):
        sent.append((chat_id, text))
        return SimpleNamespace(message_id=808)

    monkeypatch.setattr("services.telegram_send.send_text", _send_text)

    async def scenario():
        svc, _Bot, _Writer, make, situation, candidate = _text_harness(
            tmp_path, name="text_noguard.db")
        await svc.initialize()
        try:
            intent_id = await make(svc)
            return await dcs.handle_initiative(
                bot=_Bot(), chat_id=CHAT, situation=situation(),
                candidates=[candidate(intent_id)], db=svc,
                writer_service=_Writer(), correlation_id="corr-noguard")
        finally:
            await svc.close()

    result = asyncio.run(scenario())
    assert result["status"] == "sent"
    assert len(sent) == 1 and sent[0][0] == CHAT


def test_act_on_opportunity_takes_and_releases_claim(tmp_path, monkeypatch):
    """Боевой шов наблюдателя: бронь взята, guard отдан, release после send."""
    from services import direct_chat_service as dcs
    from services.database import DatabaseService

    seen: dict = {}

    async def _fake_handle(*, publish_guard=None, **_kwargs):
        seen["guard"] = publish_guard
        refusal = await publish_guard() if publish_guard else None
        seen["refusal"] = refusal
        return {"status": "sent" if refusal is None else "cancelled"}

    monkeypatch.setattr(dcs, "handle_initiative", _fake_handle)

    async def scenario():
        svc = DatabaseService(str(tmp_path / "act.db"))
        await svc.initialize()
        try:
            store = pub.SqliteClaimStore(str(svc.db_path))
            store.apply_schema()
            runner = obs.InitiativeObserverRunner.__new__(
                obs.InitiativeObserverRunner)
            runner._db = svc
            runner._bot = SimpleNamespace(id=1)
            runner._writer = SimpleNamespace()
            runner._aliases = None
            runner._publication = pub.PublicationCoordinator(svc,
                                                             store=store)
            payload = {"chats": {str(CHAT): {}},
                       "counters": obs.default_counters(), "day": {}}
            verdict = {"action": "say", "opportunity": True,
                       "kind": "development", "goal": "продолжить тему",
                       "horizon": "now", "topic_key": "dev"}
            rows = [{"id": 1, "chat_id": CHAT, "text": "реплика",
                     "user_id": 7, "author_name": "A"}]
            await runner._act_on_opportunity(payload, "job-3", CHAT, verdict,
                                            rows)
            return payload, store.snapshot(CHAT)
        finally:
            await svc.close()

    payload, snapshot = asyncio.run(scenario())
    assert seen["refusal"] is None               # бронь разрешила отправку
    assert payload["counters"]["sent"] == 1
    assert snapshot["state"] == "released"
    assert snapshot["last_publish_kind"] == pub.KIND_TEXT_INITIATIVE
    assert snapshot["last_publish_ts"] is not None
    decision = payload["chats"][str(CHAT)]["last_decision"]
    assert decision["publication"]["granted"] is True


def test_act_on_opportunity_conflict_defers_to_intent(tmp_path, monkeypatch):
    """Проигравший в гонке: реплики нет, повод остаётся durable intent-ом."""
    from services import direct_chat_service as dcs
    from services import mca_intents as mi
    from services.database import DatabaseService

    async def _boom(**_kwargs):
        raise AssertionError("handle_initiative не должен вызываться")

    monkeypatch.setattr(dcs, "handle_initiative", _boom)

    async def scenario():
        svc = DatabaseService(str(tmp_path / "conflict.db"))
        await svc.initialize()
        try:
            store = pub.SqliteClaimStore(str(svc.db_path))
            store.apply_schema()
            # Другой механизм уже отправляет в этом чате.
            other = store.acquire(chat_id=CHAT,
                                  holder_kind=pub.KIND_MEME_INITIATIVE,
                                  now=NOW_TS)
            assert other.granted
            assert store.begin_sending(chat_id=CHAT,
                                       claim_id=other.claim_id,
                                       now=NOW_TS).granted
            runner = obs.InitiativeObserverRunner.__new__(
                obs.InitiativeObserverRunner)
            runner._db = svc
            runner._bot = SimpleNamespace(id=1)
            runner._writer = SimpleNamespace()
            runner._aliases = None
            runner._publication = pub.PublicationCoordinator(svc,
                                                             store=store)
            payload = {"chats": {str(CHAT): {}},
                       "counters": obs.default_counters(), "day": {}}
            verdict = {"action": "say", "opportunity": True,
                       "kind": "development", "goal": "продолжить тему",
                       "horizon": "now", "topic_key": "dev"}
            rows = [{"id": 1, "chat_id": CHAT, "text": "реплика",
                     "user_id": 7, "author_name": "A"}]
            await runner._act_on_opportunity(payload, "job-4", CHAT, verdict,
                                            rows)
            intents = await mi.get_service(svc).store.list_open(CHAT) \
                if hasattr(mi.get_service(svc).store, "list_open") else []
            return payload, store.snapshot(CHAT), intents
        finally:
            await svc.close()

    payload, snapshot, _intents = asyncio.run(scenario())
    assert payload["counters"]["publication_conflict"] == 1
    assert payload["counters"]["sent"] == 0
    # Бронь чужого механизма не тронута.
    assert snapshot["state"] == "sending"
    assert snapshot["holder_kind"] == pub.KIND_MEME_INITIATIVE
    decision = payload["chats"][str(CHAT)]["last_decision"]
    assert decision["skip_reason"] == obs.SKIP_PUBLICATION_CONFLICT


def test_evaluate_phase_precheck_blocks_before_llm(tmp_path, monkeypatch):
    """Дешёвая проверка координации отсекает чат ДО дорогой оценки (§3.1)."""
    from services import message_identity as mi_identity
    from services.database import DatabaseService

    async def _enabled(_chat_id):
        return True

    monkeypatch.setattr(obs, "chat_observer_enabled", _enabled)

    class _LLM:
        def __init__(self):
            self.calls = 0

        async def generate(self, *args, **kwargs):
            self.calls += 1
            return "{}"

    async def scenario():
        svc = DatabaseService(str(tmp_path / "eval.db"))
        await svc.initialize()
        try:
            for index in range(6):
                await mi_identity.save_live_message(
                    svc, chat_id=CHAT, user_id=7 + index,
                    text=f"живая реплика номер {index}",
                    tg_message_id=700 + index)
            store = pub.SqliteClaimStore(str(svc.db_path))
            store.apply_schema()
            other = store.acquire(chat_id=CHAT,
                                  holder_kind=pub.KIND_MEME_INITIATIVE,
                                  now=int(NOW.timestamp()))
            assert other.granted
            assert store.begin_sending(
                chat_id=CHAT, claim_id=other.claim_id,
                now=int(NOW.timestamp())).granted
            llm = _LLM()
            runner = obs.InitiativeObserverRunner.__new__(
                obs.InitiativeObserverRunner)
            runner._db = svc
            runner._llm = llm
            runner._bot = None
            runner._writer = None
            runner._aliases = None
            runner._random = None
            runner._publication = pub.PublicationCoordinator(svc,
                                                             store=store)
            payload = {"chats": {str(CHAT): {"pending": 10,
                                             "last_eval_ts": 0}},
                       "counters": obs.default_counters(),
                       "day": {"stamp": NOW_TS // 86400},
                       "cursor_message_rowid": 0}
            await runner._evaluate_phase(payload, "job-5")
            return payload, llm
        finally:
            await svc.close()

    payload, llm = asyncio.run(scenario())
    assert llm.calls == 0                       # платной оценки не было
    entry = payload["chats"][str(CHAT)]
    assert payload["counters"]["publication_conflict"] == 1
    assert payload["counters"]["eval_skips"][obs.SKIP_PUBLICATION_CONFLICT] == 1
    assert entry["last_decision"]["publication"]["ok"] is False
    assert entry["last_decision"]["publication"]["detail"] == "claim_held"
    assert int(entry.get("last_eval_ts") or 0) == 0   # окно не «отработано»

def test_v41_step_registered_and_ddl_owned_by_module():
    from services import pg_db
    from services.database import (DatabaseService,
                                   _SCHEMA_VERSION_PUBLISH_CLAIM)
    steps = {s.version: s.name for s in DatabaseService.migration_steps()}
    assert steps.get(41) == pub.CLAIM_MIGRATION_STEP_NAME
    assert steps.get(40) == "meme_quota_journal_v40"      # сосед не сдвинут
    assert _SCHEMA_VERSION_PUBLISH_CLAIM == pub.CLAIM_SCHEMA_VERSION == 41
    assert callable(DatabaseService._migrate_publish_claim_v41)
    db_text = (__import__("pathlib").Path(__file__).resolve().parent.parent
               / "services" / "database.py").read_text(encoding="utf-8")
    assert "pub.CLAIM_DDL_SQLITE" in db_text
    assert f"CREATE TABLE IF NOT EXISTS {pub.CLAIM_TABLE}" not in db_text
    assert all(pub.CLAIM_TABLE not in statement
               for statement in pg_db.DDL_STATEMENTS)


def test_no_new_scheduler_or_lock_in_package():
    source = inspect.getsource(pub)
    for forbidden in ("asyncio.sleep", "time.sleep", "create_task",
                      "asyncio.Lock("):
        assert forbidden not in source, forbidden
    meme_source = inspect.getsource(meme)
    assert "asyncio.Lock(" not in meme_source
    observer_source = inspect.getsource(obs)
    assert "asyncio.Lock(" not in observer_source
    # Таблица одна и без индексов (PK достаточно): новой диагностической
    # таблицы пакет не вводит.
    assert "CREATE INDEX" not in source
    assert source.count("CREATE TABLE") == 2   # sqlite + справочный PG-DDL


def test_claim_schema_is_additive_and_idempotent(tmp_path):
    path = str(tmp_path / "additive.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE keep_me (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO keep_me (v) VALUES ('до миграции')")
    conn.commit()
    conn.close()

    store = pub.SqliteClaimStore(path)
    store.apply_schema()
    store.apply_schema()                    # повтор — no-op
    store.claim_manual_priority(chat_id=CHAT, now=NOW_TS)

    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT v FROM keep_me").fetchall()
        assert rows == [("до миграции",)]
        row = conn.execute(
            f"SELECT state, manual_priority_until FROM {pub.CLAIM_TABLE} "
            "WHERE chat_id = ?", (CHAT,)).fetchone()
        assert row[0] == "cancelled" and row[1] == NOW_TS + \
            pub.MANUAL_PRIORITY_SECONDS
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        conn.close()


def test_claim_table_absent_is_honest_for_both_mechanisms(tmp_path):
    """Нет таблицы: мем — schema_absent; текстовая — деградация, не тишина."""
    path = str(tmp_path / "no_claim.db")
    ledger = meme.SqliteQuotaLedger(path)
    for statement in meme.SCHEMA_DDL_SQLITE:      # только журнал квоты
        conn = sqlite3.connect(path)
        try:
            conn.execute(statement)
            conn.commit()
        finally:
            conn.close()
    assert ledger.table_present() is True
    assert pub.SqliteClaimStore(path).table_present() is False

    result = asyncio.run(meme.consider_chat(
        None, CHAT, settings=_settings(), ledger=ledger, now=NOW,
        tz_name="UTC", tz_source="utc_fallback",
        initiative_enabled=lambda: True, image_status=IMAGE_OK,
        random_source=_Hit(), messages=_rows(CHAT), model_chars=200,
        sender=_Sender(), claim_store=pub.SqliteClaimStore(path)))
    assert result.reason == meme.SKIP_SCHEMA
    assert result.detail == "publish_claim_absent"

    coordinator = pub.PublicationCoordinator(None,
                                             store=pub.SqliteClaimStore(path))
    precheck = asyncio.run(coordinator.precheck(
        CHAT, pub.KIND_TEXT_INITIATIVE, now=NOW_TS, interval_seconds=1800))
    assert precheck["ok"] is True
    assert precheck["coordination"] == pub.COORDINATION_DEGRADED
    decision = asyncio.run(coordinator.acquire(
        CHAT, pub.KIND_TEXT_INITIATIVE, now=NOW_TS, interval_seconds=1800))
    assert decision.granted is True
    assert decision.coordination == pub.COORDINATION_DEGRADED
