"""F2 `sleep-manual-cascade-badges` (раунд 10.18, итерация 2) — БЕЗ флагов.

Покрытие (spec §4.1/§4.2/§4.3/§4.4, ADR-1018-2 D1–D10, T-1714…T-1719,
T-1767…T-1771):
  * code-дефолты порогов (2/8/2/10/60/300000/10);
  * идемпотентная DML-миграция `migrate_dream_thresholds` (прежний дефолт →
    новый; кастом НЕ трогаем; повторный прогон — no-op; PG down → skip);
  * manual обходит kill-switch (`gate_override`) и суточные бюджеты
    (`budget_override`) БЕЗУСЛОВНО, но расход `worker_budget.consume` пишется;
  * manual-каскад стартует без `flags.deep_sleep_enabled`, `run_once` отдаёт
    аддитивный `stats["cascade"]`;
  * диагностика Личности: `no_self_facts`, `json_error`, `persona_disabled`
    (каскад НЕ глушится молча — только запись traits уважается).

LLM/DB — моки; SQLite in-memory; R17-safe (только причины/числа/chat_id).
"""
import asyncio
import logging
import time

import pytest

from config.settings import settings
from services import hot_config as hot
from services.database import DatabaseService
from services.dream_worker import DreamWorker
from services.config_migrations import (
    DREAM_THRESHOLD_MIGRATIONS,
    migrate_dream_thresholds,
)

CHAT_ID = -100
_NOW = 1_740_000_000

_ANS_A = ('{"beliefs":[{"text":"вася всегда платит за всех в баре",'
          '"evidence":[1,2,3]}]}')


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class _FakeLLM:
    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    async def generate(self, messages, temperature=None):
        self.calls.append((messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return '{"beliefs":[]}'


def _hot_cache(monkeypatch, values: dict | None = None):
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


async def _add_fact(db, text, *, origin="chat_history", importance=4):
    return await db.insert_graph_fact(CHAT_ID, text, origin, None,
                                      importance=importance)


async def _add_batch(db, n, topic_words, importance=4):
    for i in range(n):
        await _add_fact(
            db, f"{topic_words[0]} {topic_words[1]} в {i + 1} раз "
                f"{topic_words[2]} подряд", importance=importance)


async def _log_kinds(db) -> list[tuple]:
    cursor = await db.db.execute(
        "SELECT kind, status FROM memory_dream_log ORDER BY id")
    rows = await cursor.fetchall()
    return [(r["kind"], r["status"]) for r in rows]


# ── T-1714/T-1769: code-дефолты порогов ─────────────────────────────────────

class TestThresholdDefaults:
    def test_new_code_defaults(self):
        assert settings.DREAM_REPEAT_THRESHOLD == 2
        assert settings.DREAM_IMPORTANCE_SUM_THRESHOLD == 8
        assert settings.DREAM_MIN_NEW_FACTS_PER_CHAT == 2
        assert settings.DREAM_MAX_CLUSTERS_PER_RUN == 10
        assert settings.DREAM_DISTILLATIONS_PER_DAY == 60
        assert settings.DREAM_TOKENS_PER_DAY == 300000
        assert settings.DREAM_QUIET_CHECK_MINUTES == 10

    def test_anti_garbage_thresholds_unchanged(self):
        assert settings.DREAM_CLUSTER_OVERLAP_TOKENS == 2
        assert settings.DREAM_INITIAL_WINDOW_HOURS == 168


# ── T-1714/T-1769: идемпотентная DML-миграция ───────────────────────────────

class _FakeCache:
    def __init__(self, values, *, pg=True):
        self.values = dict(values)
        self.pg_available = pg
        self.set_calls = []

    def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, category):
        self.values[key] = value
        self.set_calls.append((key, value, category))


class TestDreamThresholdMigration:
    @pytest.mark.asyncio
    async def test_old_defaults_updated(self):
        old = {key: prev for key, (prev, _) in
               DREAM_THRESHOLD_MIGRATIONS.items()}
        cache = _FakeCache(old)
        report = await migrate_dream_thresholds(cache)
        assert set(report) == set(DREAM_THRESHOLD_MIGRATIONS)
        for key, (_, new) in DREAM_THRESHOLD_MIGRATIONS.items():
            assert cache.values[key] == new
            assert ("memory") == cache.set_calls[
                [c[0] for c in cache.set_calls].index(key)][2]

    @pytest.mark.asyncio
    async def test_idempotent_second_run_noop(self):
        old = {key: prev for key, (prev, _) in
               DREAM_THRESHOLD_MIGRATIONS.items()}
        cache = _FakeCache(old)
        await migrate_dream_thresholds(cache)
        report2 = await migrate_dream_thresholds(cache)
        assert report2 == {}

    @pytest.mark.asyncio
    async def test_custom_value_untouched(self):
        cache = _FakeCache({
            "memory.dream_repeat_threshold": 7,          # кастом владельца
            "memory.dream_tokens_per_day": 60000,        # прежний дефолт
        })
        report = await migrate_dream_thresholds(cache)
        assert cache.values["memory.dream_repeat_threshold"] == 7
        assert "memory.dream_repeat_threshold" not in report
        assert cache.values["memory.dream_tokens_per_day"] == 300000

    @pytest.mark.asyncio
    async def test_missing_key_seeded_by_configcache(self):
        cache = _FakeCache({})
        report = await migrate_dream_thresholds(cache)
        assert report == {}
        assert cache.set_calls == []

    @pytest.mark.asyncio
    async def test_pg_down_skip(self):
        cache = _FakeCache({}, pg=False)
        report = await migrate_dream_thresholds(cache)
        assert report == {}


# ── T-1715/T-1767: manual обходит gate/budget (без флага) ───────────────────

class TestManualBypassGate:
    @pytest.mark.asyncio
    async def test_manual_ignores_kill_switch_with_audit(self, db, monkeypatch):
        """Глобальный рубильник OFF: manual всё равно дистиллирует, аудит
        фиксирует gate_override."""
        _hot_cache(monkeypatch, {"memory.dream_enabled": False})
        worker = DreamWorker(db, memory=None, llm=_FakeLLM(_ANS_A))
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 1
        assert ("skipped", "gate_override") in await _log_kinds(db)

    @pytest.mark.asyncio
    async def test_plan_run_still_gated(self, db, monkeypatch):
        """Контроль: плановый прогон при OFF — скип (гейт не сломан)."""
        _hot_cache(monkeypatch, {"memory.dream_enabled": False})
        llm = _FakeLLM(_ANS_A)
        worker = DreamWorker(db, memory=None, llm=llm)
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker._run(manual=False, only_chat=CHAT_ID)
        assert res["distilled"] == 0
        assert llm.calls == []              # manual-обход не «протёк» в план


class TestManualBypassBudget:
    @pytest.mark.asyncio
    async def test_manual_ignores_budget_but_consumes(self, db, monkeypatch):
        """Суточный бюджет уже исчерпан, рубильник OFF, деградация True:
        manual дистиллирует (budget_override), расход consume пишется."""
        from services import worker_budget
        _hot_cache(monkeypatch, {
            "memory.dream_enabled": False,
            "memory.dream_distillations_per_day": 1,
            "memory.dream_tokens_per_day": 100000,
        })
        consumed = {"n": 0}

        async def _consume(*a, **kw):
            consumed["n"] += 1
            return True

        async def _degraded(*a, **kw):
            return False       # global budget exhausted

        monkeypatch.setattr(worker_budget, "consume", _consume)
        monkeypatch.setattr(worker_budget, "global_degradation_allows",
                            _degraded)
        worker = DreamWorker(db, memory=None, llm=_FakeLLM(_ANS_A))
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        # расход «за сегодня» уже на пределе → _budget_reason=distillations
        await db.log_dream_event(CHAT_ID, int(time.time()),
                                 kind="distilled", tokens=10, status="ok")
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 1
        assert res["budget_stop"] is False
        assert consumed["n"] > 0            # учёт расхода сохранён (fail-open)
        assert ("skipped", "budget_override") in await _log_kinds(db)

    @pytest.mark.asyncio
    async def test_plan_run_stops_on_budget(self, db, monkeypatch):
        """Контроль: плановый путь бюджет уважает (не сломан)."""
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda ts, tz=None: 5)
        _hot_cache(monkeypatch, {
            "memory.dream_enabled": True,
            "memory.dream_distillations_per_day": 1,
            "memory.dream_tokens_per_day": 100000,
        })
        worker = DreamWorker(db, memory=None, llm=_FakeLLM(_ANS_A))
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        await db.log_dream_event(CHAT_ID, int(time.time()),
                                 kind="distilled", tokens=10, status="ok")
        res = await worker._run(manual=False, only_chat=CHAT_ID)
        assert res["distilled"] == 0
        assert res["budget_stop"] is True


# ── T-1716: каскад Сон → Глубокий (manual игнорирует флаг) ──────────────────

class TestManualCascade:
    @pytest.mark.asyncio
    async def test_manual_ignores_deep_flag(self, db, monkeypatch):
        _hot_cache(monkeypatch, {"flags.deep_sleep_enabled": False})
        worker = DreamWorker(db, memory=None, llm=_FakeLLM())
        seen = {}

        async def _fake(ids, *, since_ts=None, manual=False):
            seen["ids"] = list(ids)
            seen["manual"] = manual
            return {"chats": len(ids), "paradigms": 0, "ran": 0,
                    "skipped": 0, "traits": 0}

        monkeypatch.setattr(worker, "_run_deep_all", _fake)
        worker._last_chat_ids = [CHAT_ID]
        out = await worker._maybe_deep_after_sleep(
            {"distilled": 1, "chats": 1}, manual=True)
        assert seen["manual"] is True
        assert seen["ids"] == [CHAT_ID]
        assert out["chats"] == 1

    @pytest.mark.asyncio
    async def test_run_once_returns_cascade_additive(self, db, monkeypatch):
        _hot_cache(monkeypatch, {"flags.deep_sleep_enabled": False})
        worker = DreamWorker(db, memory=None, llm=_FakeLLM())

        async def _fake_run(*, manual, only_chat=None):
            return {"chats": 1, "clusters": 0, "distilled": 0,
                    "unchanged": 0, "errors": 0, "window_skips": 0,
                    "budget_stop": False}

        async def _fake_deep(ids, *, since_ts=None, manual=False):
            return {"chats": len(ids), "paradigms": 2, "ran": 1,
                    "skipped": 0, "traits": 3}

        monkeypatch.setattr(worker, "_run", _fake_run)
        monkeypatch.setattr(worker, "_run_deep_all", _fake_deep)
        res = await worker.run_once(CHAT_ID)
        assert res["status"] == "ok"
        assert res["cascade"]["deep"]["paradigms"] == 2
        assert res["cascade"]["traits"]["written"] == 3


# ── S10.18-23: настоящий маркер ручного прогона на воркере ──────────────────

class TestManualRunMarker:
    @pytest.mark.asyncio
    async def test_run_once_sets_manual_run_marker(self, db, monkeypatch):
        """`run_once` (обычный) выставляет `manual_run_active`; здесь
        `_run_deep_all` замокан (реальный deep не шёл), поэтому
        `manual_deep_active` НЕ выставляется — S10.18-29 (позитивный кейс —
        в `test_run_once_cascade_sets_manual_deep_marker`)."""
        _hot_cache(monkeypatch, {})
        worker = DreamWorker(db, memory=None, llm=_FakeLLM())
        assert worker.manual_run_active is False

        async def _fake_run(*, manual, only_chat=None):
            return {"chats": 0}

        async def _fake_deep(ids, *, since_ts=None, manual=False):
            return {"chats": 0, "paradigms": 0, "ran": 0, "skipped": 0,
                    "traits": 0}

        monkeypatch.setattr(worker, "_run", _fake_run)
        monkeypatch.setattr(worker, "_run_deep_all", _fake_deep)
        await worker.run_once(CHAT_ID)
        assert worker.manual_run_active is True
        assert worker.manual_deep_active is False

    @pytest.mark.asyncio
    async def test_run_once_cascade_sets_manual_deep_marker(
            self, db, monkeypatch):
        """S10.18-29: manual-каскад `run_once(deep=False)` реально запускает
        Глубокий сон (здесь — `_run_deep_all` настоящий, memory=None →
        `no_memory`) → `manual_deep_active` выставлен на всё время прогона,
        а не только для `?deep=1`."""
        _hot_cache(monkeypatch, {})
        worker = DreamWorker(db, memory=None, llm=_FakeLLM())
        worker._last_chat_ids = [CHAT_ID]

        async def _fake_run(*, manual, only_chat=None):
            return {"chats": 1, "distilled": 1, "clusters": 0,
                    "unchanged": 0, "errors": 0, "window_skips": 0,
                    "budget_stop": False}

        monkeypatch.setattr(worker, "_run", _fake_run)
        res = await worker.run_once(CHAT_ID)
        assert res["status"] == "ok"
        assert worker.manual_run_active is True
        assert worker.manual_deep_active is True
        assert worker._manual_deep_run is False      # прогон уже завершился

    @pytest.mark.asyncio
    async def test_run_once_deep_sets_manual_deep_marker(self, db, monkeypatch):
        """`run_once(deep=True)` выставляет `manual_deep_active`."""
        _hot_cache(monkeypatch, {})
        worker = DreamWorker(db, memory=None, llm=_FakeLLM())

        async def _fake_deep(ids, *, since_ts=None, manual=False):
            return {"chats": 0, "paradigms": 0, "ran": 0, "skipped": 0,
                    "traits": 0}

        monkeypatch.setattr(worker, "_run_deep_all", _fake_deep)
        await worker.run_once(CHAT_ID, deep=True)
        assert worker.manual_deep_active is True
        assert worker.manual_run_active is False


# ── S10.18-25: `0` как per-chat лимит = «без лимита» ────────────────────────

class TestZeroLimitUnlimited:
    @pytest.mark.asyncio
    async def test_zero_distillation_limit_does_not_budget_stop(
            self, db, monkeypatch):
        """`memory.dream_distillations_per_day=0` — без лимита: near-limit не
        останавливает чат (оба трактуют 0 одинаково)."""
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda ts, tz=None: 5)
        _hot_cache(monkeypatch, {"memory.dream_enabled": True,
                                 "memory.dream_distillations_per_day": 0})
        worker = DreamWorker(db, memory=None, llm=_FakeLLM(_ANS_A))
        await _add_batch(db, 2, ("вася", "платит", "в баре"), importance=4)
        res = await worker._run(manual=False, only_chat=CHAT_ID)
        assert res["budget_stop"] is False, "0 = без лимита, не стоп"
        assert res["distilled"] == 1


# ── T-1717/T-1770: диагностика Личности ─────────────────────────────────────

class _FakeMemory:
    _vec_available = False

    def __init__(self, anchors):
        self._anchors = list(anchors)

    async def get_rag_facts(self, chat_id, query):
        return list(self._anchors)


class _FakeWorkerLLM:
    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    async def generate_worker(self, role, messages, temperature=None):
        self.calls.append(role)
        if self._answers:
            return self._answers.pop(0)
        return '{"paradigms":[]}'

    async def generate(self, messages, temperature=None, chat_id=None):
        return '{"beliefs":[]}'


async def _hot_values(monkeypatch, values):
    _hot_cache(monkeypatch, values)


class TestPersonaDiagnostics:
    @pytest.mark.asyncio
    async def test_no_self_facts_warning(self, db, monkeypatch, caplog):
        caplog.set_level(logging.WARNING)
        worker = DreamWorker(db, memory=None, llm=_FakeLLM())
        out = await worker._run_persona_traits_once(CHAT_ID, now=_NOW)
        assert out == {"status": "empty", "traits": 0}
        assert any("reason=no_self_facts" in r.getMessage()
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_json_error_warning(self, db, monkeypatch, caplog):
        caplog.set_level(logging.WARNING)
        await _add_fact(db, "[Бот] решил чаще шутить",
                        origin="bot_self_reply")
        worker = DreamWorker(db, memory=None, llm=_FakeLLM("не json вовсе"))
        monkeypatch.setattr(
            worker, "_deep_budget_ok",
            lambda *a, **kw: _async_true())
        out = await worker._run_persona_traits_once(CHAT_ID, now=_NOW)
        assert out == {"status": "error", "traits": 0}
        msgs = [r.getMessage() for r in caplog.records]
        assert any("reason=json_error" in m and "raw_len=" in m for m in msgs)

    @pytest.mark.asyncio
    async def test_persona_disabled_logged_cascade_not_muted(
            self, db, monkeypatch, caplog):
        """persona OFF: запись traits не обходим, но шаг ЛИЧНОСТИ не глушим
        молча — WARNING reason=persona_disabled (T-1770)."""
        caplog.set_level(logging.WARNING)
        await _add_fact(db, "толян снова заказал литрбол", importance=6)
        memory = _FakeMemory([
            ("chat_history", "толян пил каждую пятницу",
             _NOW - 200 * 86400, None),
            ("chat_history", "толян бросил пить", _NOW - 200 * 86400, None),
        ])
        llm = _FakeWorkerLLM(
            '{"paradigms":[{"text":"Толян теперь спортсмен",'
            '"anchors":[1,2]}]}')
        _hot_cache(monkeypatch, {"flags.deep_sleep_enabled": True,
                                 "flags.persona_enabled": False,
                                 "memory.deep_sleep_trigger": "after_sleep"})
        worker = DreamWorker(db, memory=memory, llm=llm)
        monkeypatch.setattr(
            worker, "_deep_budget_ok",
            lambda *a, **kw: _async_true())
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "ok"
        assert out["traits"] == 0
        assert any("reason=persona_disabled" in r.getMessage()
                   for r in caplog.records)


async def _async_true():
    return True


# ── T-1767: grep-proof отсутствия manual-флагов ─────────────────────────────

class TestNoManualFeatureFlag:
    def test_no_manual_override_feature_flags(self):
        from pathlib import Path
        src = Path("services/dream_worker.py").read_text(encoding="utf-8")
        assert "sleep_manual_priority_enabled" not in src
        assert "sleep_relaxed_thresholds_enabled" not in src
        # нет гейта «manual + фича-флаг/бюджет-условие»
        assert "manual and flags." not in src
        assert "manual and settings." not in src
        assert "manual_priority" not in src


# ── T-1771 (A): кандидат ровно с 2 фактами при min_new_facts=2 ─────────────

class TestCandidateMinFacts:
    @pytest.mark.asyncio
    async def test_exactly_two_facts_qualified(self, db, monkeypatch):
        """Ровно 2 факта на общий topic → чат-кандидат (порог min=2) и кластер
        квалифицируется (repeat=2, Σimportance=8 при importance=4)."""
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda ts, tz=None: 5)
        _hot_cache(monkeypatch, {"memory.dream_enabled": True})
        llm = _FakeLLM(_ANS_A)
        worker = DreamWorker(db, memory=None, llm=llm)
        await _add_batch(db, 2, ("вася", "платит", "в баре"), importance=4)
        res = await worker._run(manual=False)
        assert res["chats"] == 1, "порог min_new_facts=2 пропускает 2 факта"
        assert res["distilled"] == 1
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_one_fact_below_threshold(self, db, monkeypatch):
        """Контроль границы: 1 факт < min_new_facts=2 → чат не кандидат."""
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda ts, tz=None: 5)
        _hot_cache(monkeypatch, {"memory.dream_enabled": True})
        llm = _FakeLLM(_ANS_A)
        worker = DreamWorker(db, memory=None, llm=llm)
        await _add_batch(db, 1, ("вася", "платит", "в баре"), importance=4)
        res = await worker._run(manual=False)
        assert res["chats"] == 0
        assert llm.calls == []


# ── T-1771 (C): manual обходит окно дистилляций ─────────────────────────────

class TestManualBypassesWindow:
    @pytest.mark.asyncio
    async def test_manual_distills_outside_window(self, db, monkeypatch):
        """Окно [4,6); монки-час = 12 → `_window_open_for` False, но manual
        всё равно дистиллирует (T-1715, безусловный обход)."""
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda ts, tz=None: 12)
        _hot_cache(monkeypatch, {"memory.dream_enabled": True})
        worker = DreamWorker(db, memory=None, llm=_FakeLLM(_ANS_A))
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        assert await worker._window_open_for(CHAT_ID, _NOW) is False
        res = await worker.run_once(CHAT_ID)
        assert res["distilled"] == 1, "manual обходит закрытое окно"

    @pytest.mark.asyncio
    async def test_auto_window_skip_outside_hours(self, db, monkeypatch):
        """Контроль: авто-путь вне окна → window_skip (обход не «протёк»)."""
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda ts, tz=None: 12)
        _hot_cache(monkeypatch, {"memory.dream_enabled": True})
        llm = _FakeLLM(_ANS_A)
        worker = DreamWorker(db, memory=None, llm=llm)
        await _add_batch(db, 3, ("вася", "платит", "в баре"))
        res = await worker._run(manual=False, only_chat=CHAT_ID)
        assert res["window_skips"] >= 1
        assert res["distilled"] == 0
        assert llm.calls == []


# ── T-1771 (D1/D3): manual игнорирует verdict consume и исчерпанный кап ─────

class TestManualBudgetVerdictIgnored:
    @pytest.mark.asyncio
    async def test_deep_consume_false_still_true(self, db, monkeypatch):
        """`consume → False` при manual всё равно даёт True (4 consume
        выполнены, verdict проигнорирован)."""
        from services import worker_budget
        calls = []

        async def _consume(*a, **kw):
            calls.append(a)
            return False

        async def _degraded(*a, **kw):
            return False

        monkeypatch.setattr(worker_budget, "consume", _consume)
        monkeypatch.setattr(worker_budget, "global_degradation_allows",
                            _degraded)
        worker = DreamWorker(db, memory=None, llm=_FakeLLM())
        ok = await worker._deep_budget_ok(CHAT_ID, "prompt", manual=True)
        assert ok is True
        assert len(calls) == 4, "все 4 consume выполнены независимо"

    @pytest.mark.asyncio
    async def test_dream_consume_false_still_true(self, db, monkeypatch):
        """То же для module-level `_dream_budget_ok` (D3)."""
        from services import worker_budget
        from services.dream_worker import _dream_budget_ok
        calls = []

        async def _consume(*a, **kw):
            calls.append(a)
            return False

        async def _degraded(*a, **kw):
            return False

        monkeypatch.setattr(worker_budget, "consume", _consume)
        monkeypatch.setattr(worker_budget, "global_degradation_allows",
                            _degraded)
        ok = await _dream_budget_ok(CHAT_ID, "text", manual=True)
        assert ok is True
        assert len(calls) == 4

    @pytest.mark.asyncio
    async def test_persona_reached_with_exhausted_deep_cap(
            self, db, monkeypatch):
        """Исчерпан `limits.deep_sleep_tokens_per_day` + `consume → False`:
        manual-каскад всё равно доходит до Личности (D1)."""
        from services import worker_budget, bot_persona
        _hot_cache(monkeypatch, {
            "flags.deep_sleep_enabled": True,
            "flags.persona_enabled": True,
            "memory.deep_sleep_trigger": "after_sleep",
            "limits.deep_sleep_tokens_per_day": 1,
        })
        await _add_fact(db, "[Бот] решил чаще шутить",
                        origin="bot_self_reply")
        await _add_fact(db, "толян снова заказал литрбол", importance=6)
        memory = _FakeMemory([
            ("chat_history", "толян пил каждую пятницу",
             _NOW - 200 * 86400, None),
            ("chat_history", "толян бросил пить", _NOW - 200 * 86400, None),
        ])
        # F8/ADR-1024-5 D1: traits (background) исполняются ДО парадигм
        # (history) — эволюция характера больше не зависит от paradigm-ветки.
        llm = _FakeWorkerLLM(
            '["стал спокойнее", "чаще шутить"]',
            '{"paradigms":[{"text":"Толян теперь спортсмен",'
            '"anchors":[1,2]}]}')
        # Суточный deep-кап уже исчерпан прошлым прогоном.
        await db.log_dream_event(CHAT_ID, int(time.time()),
                                 kind="deep_run", tokens=9999, status="ok")

        async def _consume(*a, **kw):
            return False

        async def _degraded(*a, **kw):
            return False

        async def _append(traits, *, chat_id=None, source=None):
            return len(traits)

        async def _status(*a, **kw):
            return None

        monkeypatch.setattr(worker_budget, "consume", _consume)
        monkeypatch.setattr(worker_budget, "global_degradation_allows",
                            _degraded)
        monkeypatch.setattr(bot_persona, "append_traits", _append)
        monkeypatch.setattr(bot_persona, "record_trait_status", _status)
        worker = DreamWorker(db, memory=memory, llm=llm)
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "ok"
        assert out["traits"] >= 1, "Личность достигнута при исчерпанном капе"
        assert llm.calls == ["background", "history"]
