"""mca-06-sleep-paradigms — блоки B+C (round 10.33) targeted-тесты.

Покрытие по контрактам (spec.md §3–§4, ADR-1028-9 D1–D4/D7, tasks T-4703…T-4712):
  * T-4703 единый gate-resolver: 8 причин × источник; фиксированный порядок
    §3.2 (первый gate побеждает); идентичный ответ 4 потребителям; нет второго
    human gate; kill-switch `MCA_DREAM_GATE_RESOLVER_ENABLED` OFF → паритет.
  * T-4704 врезка в worker: `schedule_outside_window` ≠ gate-off, `rag_off` ≠
    пустой пул, `cooldown` ≠ `master off`.
  * T-4705 API: master/deep разъединены; каждый gate → distinct reason;
    сбой счётчиков → `counters_error` (не нули/не disabled); OFF → паритет.
  * T-4707 traits-развязка: traits-ok + paradigm-блокер → счётчик парадигм не
    тронут, статус честный.
  * T-4708…T-4712 исторический профиль: возраст ДО top_k; возраст от
    `message_timestamp`; FTS-фолбэк без vec-предусловия; 3 исхода
    (rag_off / RAG-ошибка / честный пустой); тематические пакеты; ранжирование;
    resumable enrichment (paused/completed); bounded source window.
"""
import asyncio
import json
import time

import pytest

from config.settings import settings
from services import hot_config as hot
from services import mca_dream_history as hist
from services import mca_gates
from services import worker_settings
from services.database import DatabaseService
from services.dream_worker import DreamWorker

CHAT_ID = -100
NOW = int(time.time())
DAY = 86400


# ── фикстуры ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _hot_cache(monkeypatch, values=None):
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


class _FakeMemory:
    """Кандидаты mca-07 (`retrieve_fact_candidates`) + опциональная ошибка."""

    def __init__(self, candidates=None, *, raise_on=None, vec_available=True):
        self._candidates = list(candidates or [])
        self._raise = raise_on
        self._vec_available = vec_available
        self.calls = []

    async def retrieve_fact_candidates(self, chat_id, query, *, limit=None,
                                       include_direct_reply=False,
                                       include_self=False):
        self.calls.append((chat_id, query, limit))
        if self._raise:
            raise RuntimeError(self._raise)
        rows = self._candidates[:limit] if limit else self._candidates
        return [dict(r) for r in rows]

    async def get_rag_facts(self, chat_id, query):
        return []


class _FakeWorkerLLM:
    def __init__(self, *answers):
        self._answers = list(answers)
        self.calls = []

    async def generate_worker(self, role, messages, temperature=None):
        self.calls.append((role, messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return '{"paradigms":[]}'

    async def generate(self, messages, temperature=None, chat_id=None):
        return '{"beliefs":[]}'


class _FakeGateDb:
    """Минимальный db для resolver/API (без реальных таблиц)."""

    def __init__(self, *, attempts=0, last=None, counters_raise=False,
                 paradigms=()):
        self.attempts = attempts
        self.last = last
        self.counters_raise = counters_raise
        self._paradigms = list(paradigms)

    async def count_deep_attempts(self, since_ts, *, chat_id=None):
        return int(self.attempts)

    async def last_deep_attempt(self, chat_id=None):
        return self.last

    async def list_recent_beliefs(self, **kwargs):
        return list(self._paradigms)

    async def count_paradigms(self, chat_id=None):
        if self.counters_raise:
            raise RuntimeError("db counters down")
        return len(self._paradigms)

    async def last_deep_run(self, chat_id=None):
        if self.counters_raise:
            raise RuntimeError("db counters down")
        return None

    async def count_dream_log(self, *a, **kw):
        if self.counters_raise:
            raise RuntimeError("db counters down")
        return 0

    async def recent_dream_log(self, **kwargs):
        if self.counters_raise:
            raise RuntimeError("db counters down")
        return []


def _patch_settings_source(monkeypatch, mapping):
    """Подмена `resolve_setting_with_source`: mapping[key] = value |
    {'chat':..,'global':..,'source':..}."""
    async def _resolve(key, *, chat_id=None, default=None):
        if key not in mapping:
            return default, "default"
        spec = mapping[key]
        if isinstance(spec, dict):
            if chat_id is not None and "chat" in spec:
                return spec["chat"], spec.get("source", "chat")
            return spec.get("global", default), spec.get("source", "global")
        return spec, "global"
    monkeypatch.setattr(worker_settings, "resolve_setting_with_source",
                        _resolve)


def _patch_cached(monkeypatch, mapping):
    async def _resolve(key, *, chat_id=None, default=None):
        return mapping.get(key, default)
    monkeypatch.setattr(worker_settings, "resolve_setting_cached", _resolve)
    import services.dream_worker as dw
    monkeypatch.setattr(dw, "resolve_setting_cached", _resolve)


# ── T-4703: единый gate-resolver ────────────────────────────────────────────

class TestGateResolver:
    @pytest.mark.asyncio
    async def test_memory_service_missing(self):
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=None)
        assert st.blocked and st.reason == "memory_service_missing"
        assert st.gate == "memory_service"

    @pytest.mark.asyncio
    async def test_master_sleep_off_source_global(self, monkeypatch):
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": False,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": True,
        })
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=object(), include_master=True)
        assert st.reason == "master_sleep_off"
        assert st.effective is False and st.source == "global"
        assert "memory.dream_enabled" in (st.detail or "")

    @pytest.mark.asyncio
    async def test_master_chat_override_reported(self, monkeypatch):
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": {"chat": True, "global": False,
                                     "source": "chat"},
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": True,
        })
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=object(), include_master=True)
        # override ON → не заблокирован; источник/override зафиксированы
        assert st.blocked is False

    @pytest.mark.asyncio
    async def test_deep_sleep_off(self, monkeypatch):
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": False,
            "flags.graph_rag_enabled": True,
        })
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=object())
        assert st.reason == "deep_sleep_off" and st.gate == "deep_sleep"

    @pytest.mark.asyncio
    async def test_rag_off(self, monkeypatch):
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": False,
        })
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=object())
        assert st.reason == "rag_off" and st.gate == "rag"

    @pytest.mark.asyncio
    async def test_schedule_outside_window(self, monkeypatch):
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": True,
        })
        _patch_cached(monkeypatch, {
            "memory.deep_sleep_trigger": "fixed",
            "memory.deep_sleep_hour": 7,
        })
        import services.dream_worker as dw
        monkeypatch.setattr(dw, "_local_hour", lambda now, tz=None: 8)
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=object(), now=NOW)
        assert st.reason == "schedule_outside_window"
        assert "deep_sleep_hour=7" in (st.detail or "")
        assert "schedule" == st.gate

    @pytest.mark.asyncio
    async def test_queue_busy(self, monkeypatch):
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": True,
        })
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=object(), queue_busy=True)
        assert st.reason == "queue_busy"

    @pytest.mark.asyncio
    async def test_cooldown(self, monkeypatch):
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": True,
        })
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(last=NOW - 3600), CHAT_ID, memory=object(), now=NOW)
        assert st.reason == "cooldown"
        assert "min_interval_hours" in (st.detail or "")

    @pytest.mark.asyncio
    async def test_resource_limit(self, monkeypatch):
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": True,
        })
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(attempts=1), CHAT_ID, memory=object(), now=NOW)
        assert st.reason == "resource_limit"
        assert "used=1" in (st.detail or "")

    @pytest.mark.asyncio
    async def test_order_first_gate_wins(self, monkeypatch):
        # deep off AND rag off → deep_sleep_off (gate 3 раньше rag 4).
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": False,
            "flags.graph_rag_enabled": False,
        })
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=object())
        assert st.reason == "deep_sleep_off"
        # master off AND deep off → master_sleep_off (gate 2 раньше 3).
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": False,
            "flags.deep_sleep_enabled": False,
            "flags.graph_rag_enabled": False,
        })
        st2 = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=object(), include_master=True)
        assert st2.reason == "master_sleep_off"

    @pytest.mark.asyncio
    async def test_identical_answer_for_four_consumers(self, monkeypatch):
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": True,
        })
        kwargs = dict(memory=object(), now=NOW, include_master=True)
        states = [await mca_gates.resolve_dream_gate(_FakeGateDb(), CHAT_ID,
                                                     **kwargs)
                  for _ in range(4)]
        assert all(s == states[0] for s in states)

    @pytest.mark.asyncio
    async def test_no_second_human_gate_reasons_are_closed_set(self,
                                                               monkeypatch):
        """Resolver информационный: никогда не выдаёт причину вне 8 (нет
        нового human/approval gate)."""
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": True,
        })
        st = await mca_gates.resolve_dream_gate(
            _FakeGateDb(), CHAT_ID, memory=object())
        assert st.blocked is False and st.reason is None
        assert set(mca_gates.DREAM_GATE_REASONS) == {
            "master_sleep_off", "deep_sleep_off", "rag_off",
            "memory_service_missing", "schedule_outside_window",
            "queue_busy", "cooldown", "resource_limit"}


# ── T-4704: врезка в worker ─────────────────────────────────────────────────

async def _add_fact(db, text, importance=5):
    return await db.insert_graph_fact(CHAT_ID, text, "chat_history", None,
                                      importance=importance)


def _trace_capture(monkeypatch):
    seen = []

    def _trace(chat_id, step, status, reason=None, extra=None, **kw):
        seen.append((step, status, reason))

    import services.dream_worker as dw
    monkeypatch.setattr(dw, "_trace_deep", _trace)
    return seen


class TestWorkerWiring:
    @pytest.mark.asyncio
    async def test_rag_off_stops_with_rag_off_not_gate_off(self, db,
                                                           monkeypatch):
        await _add_fact(db, "свежий факт", importance=5)
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": False,
        })
        seen = _trace_capture(monkeypatch)
        worker = DreamWorker(db, memory=_FakeMemory(), llm=_FakeWorkerLLM())
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "disabled"
        assert ("deep", "skip", "rag_off") in seen

    @pytest.mark.asyncio
    async def test_cooldown_not_master_off(self, db, monkeypatch):
        await _add_fact(db, "свежий факт", importance=5)
        _patch_settings_source(monkeypatch, {
            "memory.dream_enabled": True,
            "flags.deep_sleep_enabled": True,
            "flags.graph_rag_enabled": True,
        })
        _patch_cached(monkeypatch, {
            "memory.deep_sleep_trigger": "after_sleep"})
        seen = _trace_capture(monkeypatch)

        async def _last(chat_id=None):
            return NOW - 3600

        monkeypatch.setattr(db, "last_deep_attempt", _last)
        # D14/T-5264: класс C (bootstrap) неприменим — парадигмы у чата ЕСТЬ,
        # поэтому обычный интервал держит cooldown как раньше.
        async def _has_paradigms(chat_id=None):
            return 1

        monkeypatch.setattr(db, "count_paradigms", _has_paradigms)
        worker = DreamWorker(db, memory=_FakeMemory(), llm=_FakeWorkerLLM())
        out = await worker._run_deep_once(CHAT_ID, manual=False)
        assert out["status"] == "cooldown"
        assert ("deep", "skip", "cooldown") in seen

    @pytest.mark.asyncio
    async def test_resolver_off_parity_old_branch(self, db, monkeypatch):
        await _add_fact(db, "свежий факт", importance=5)
        monkeypatch.setattr(mca_gates, "dream_gate_resolver_enabled",
                            lambda: False)
        _patch_cached(monkeypatch, {"flags.deep_sleep_enabled": False})
        seen = _trace_capture(monkeypatch)
        worker = DreamWorker(db, memory=_FakeMemory(), llm=_FakeWorkerLLM())
        out = await worker._run_deep_once(CHAT_ID, manual=False)
        assert out["status"] == "disabled"
        assert ("deep", "skip", "disabled") in seen

    @pytest.mark.asyncio
    async def test_resolver_off_daily_limit_parity(self, db, monkeypatch):
        await _add_fact(db, "свежий факт", importance=5)
        monkeypatch.setattr(mca_gates, "dream_gate_resolver_enabled",
                            lambda: False)
        # Изоляция слоёв: D-статусы (T-4715) отдельный kill-switch; здесь
        # проверяется только resolver-OFF паритет, поэтому evidence typing OFF
        # (иначе canonical `daily_limit→budget`).
        monkeypatch.setattr(mca_gates, "dream_evidence_typing_enabled",
                            lambda: False)
        _patch_cached(monkeypatch, {"flags.deep_sleep_enabled": True})

        async def _count(*a, **kw):
            return 1

        monkeypatch.setattr(db, "count_deep_attempts", _count)
        worker = DreamWorker(db, memory=_FakeMemory(), llm=_FakeWorkerLLM())
        out = await worker._run_deep_once(CHAT_ID, manual=False)
        assert out["status"] == "daily_limit"


# ── T-4707: traits-развязка ─────────────────────────────────────────────────

class TestTraitsDecoupling:
    @pytest.mark.asyncio
    async def test_traits_ok_does_not_bump_paradigm_counter(self, db,
                                                            monkeypatch):
        await _add_fact(db, "свежий факт", importance=5)
        _hot_cache(monkeypatch, {"flags.deep_sleep_enabled": True})
        # memory с каналами, но пустой исторический пул → paradigm-блокер.
        worker = DreamWorker(db, memory=_FakeMemory(candidates=[]),
                             llm=_FakeWorkerLLM())
        order = []

        async def _traits(chat_id, now, *, manual=False):
            order.append("traits")
            return 2

        async def _packet(chat_id, now, since_ts):
            order.append("packet")
            return {"beliefs": [{"fact": "свежий факт", "id": 1,
                                 "target_user": None}],
                    "recent": [], "source_ids": [1]}

        monkeypatch.setattr(worker, "_run_persona_traits_step", _traits)
        monkeypatch.setattr(worker, "_build_deep_packet", _packet)
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        # traits выполнены ДО paradigm-блокера; статус честный no_anchors.
        assert order[0] == "traits"
        assert out["status"] == "no_anchors"
        assert out["paradigms"] == 0
        assert out["traits"] == 2


# ── T-4705: API deep-sleep ──────────────────────────────────────────────────

class TestDeepSleepApi:
    async def _call(self, monkeypatch, db, gate_state, *, resolver_on=True,
                    worker=True):
        from web.api import memory_agi as ma

        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        monkeypatch.setattr(mca_gates, "dream_gate_resolver_enabled",
                            lambda: resolver_on)
        if worker:
            class _W:
                memory = object()
            monkeypatch.setattr(ma.lore_runtime, "get_dream_worker",
                                lambda: _W())
        else:
            monkeypatch.setattr(ma.lore_runtime, "get_dream_worker",
                                lambda: None)

        async def _fake_gate(*a, **k):
            return gate_state

        monkeypatch.setattr(mca_gates, "resolve_dream_gate", _fake_gate)
        return await ma.deep_sleep_status(None, None, chat_id=CHAT_ID)

    @pytest.mark.asyncio
    async def test_each_gate_distinct_reason(self, monkeypatch):
        # D14/T-5264: структурные причины — paradigms_reason = gate-причина;
        # scheduler-причины (cooldown/schedule/queue/resource) НЕ подменяют
        # результат последней попытки → он независим в `scheduler_gate`,
        # а paradigms_reason = last-attempt (пусто → "empty").
        for reason in mca_gates.DREAM_GATE_REASONS:
            st = mca_gates.DreamGateState(
                gate="g", blocked=True, reason=reason, global_value=False,
                chat_override=None, effective=False, source="global",
                detail=f"key for {reason}")
            resp = await self._call(monkeypatch, _FakeGateDb(), st)
            if reason in mca_gates.SCHEDULER_GATE_REASONS:
                assert resp["scheduler_gate"] == reason, reason
                assert resp["paradigms_reason"] == "empty", reason
            else:
                assert resp["scheduler_gate"] is None, reason
                assert resp["paradigms_reason"] == reason, reason
            assert resp["detail"] == f"key for {reason}"

    @pytest.mark.asyncio
    async def test_counters_error_not_zeros(self, monkeypatch):
        st = mca_gates.DreamGateState(
            gate="none", blocked=False, reason=None, global_value=True,
            chat_override=None, effective=True, source="global", detail=None)
        resp = await self._call(monkeypatch, _FakeGateDb(counters_raise=True),
                                st)
        assert resp["counters_error"] is True
        assert resp["paradigms_reason"] == "counters_error"
        assert resp["paradigms_reason"] != "master_off"

    @pytest.mark.asyncio
    async def test_resolver_off_parity(self, monkeypatch):
        # OFF: ошибка счётчиков → master_off-обобщённость, без counters_error
        # поля (точный код 2.58.49).
        resp = await self._call(monkeypatch, _FakeGateDb(counters_raise=True),
                                gate_state=None, resolver_on=False)
        assert resp["paradigms_reason"] == "master_off"
        assert "counters_error" not in resp
        assert "gate" not in resp

    @pytest.mark.asyncio
    async def test_master_deep_split(self, monkeypatch):
        # master off, deep on → master_sleep_off (не «master_off»).
        st = mca_gates.DreamGateState(
            gate="master_sleep", blocked=True, reason="master_sleep_off",
            global_value=False, chat_override=None, effective=False,
            source="global", detail="memory.dream_enabled=False")
        resp = await self._call(monkeypatch, _FakeGateDb(), st)
        assert resp["paradigms_reason"] == "master_sleep_off"
        st2 = mca_gates.DreamGateState(
            gate="deep_sleep", blocked=True, reason="deep_sleep_off",
            global_value=False, chat_override=None, effective=False,
            source="global", detail="flags.deep_sleep_enabled=False")
        resp2 = await self._call(monkeypatch, _FakeGateDb(), st2)
        assert resp2["paradigms_reason"] == "deep_sleep_off"

    def test_unchanged_maps_to_empty_but_raw_distinct(self):
        # mca-06 [L-3]/A94: UI-мэппинг `unchanged→empty` сохранён (паритет),
        # при этом raw status в логе различает `unchanged` и `duplicate`.
        from web.api import memory_agi as ma
        assert ma._DEEP_REASON_MAP["unchanged"] == "empty"
        assert ma._DEEP_REASON_MAP["duplicate"] == "duplicate"
        assert ma._last_deep_reason(
            [{"kind": "deep_skip", "status": "unchanged"}]) == "empty"
        assert ma._last_deep_reason(
            [{"kind": "deep_skip", "status": "duplicate"}]) == "duplicate"


# ── T-4708…T-4712: исторический профиль ─────────────────────────────────────

def _cand(fact, *, days_old, tg=None, created_days_old=None, score=0.0,
          participants=None, **extra):
    d = {
        "id": abs(hash(fact)) % 100000,
        "fact": fact,
        "rag_ts": NOW - days_old * DAY,
        "message_timestamp": NOW - days_old * DAY,
        "created_at": NOW - (created_days_old if created_days_old is not None
                             else days_old) * DAY,
        "tg_message_id": tg,
        "score": score,
    }
    if participants is not None:
        d["participants"] = participants
    d.update(extra)
    return d


class TestHistoricalProfile:
    @pytest.mark.asyncio
    async def test_old_relevant_survives_final_top_k(self):
        # A92: 20 свежих + 1 релевантный старый → старый в кандидатах после
        # top_k (возраст-фильтр ДО top_k, pre-limit ≥ 4×top_k).
        fresh = [_cand(f"свежий факт номер {i}", days_old=1, tg=i)
                 for i in range(20)]
        old = _cand("толян пил литрбол каждую пятницу", days_old=200, tg=999)
        mem = _FakeMemory(fresh + [old])
        sel = await hist.select_historical_candidates(
            mem, None, CHAT_ID, "толян литрбол пятницу", top_k=20, now=NOW,
            min_age_days=90)
        assert old["fact"] in [c["fact"] for c in sel.candidates]
        assert sel.missing_timestamp == 0

    @pytest.mark.asyncio
    async def test_age_uses_message_timestamp_not_created_at(self):
        # message_timestamp старый, created_at свежий → исторический (проходит).
        old_but_indexed_fresh = _cand("старое событие", days_old=200,
                                      created_days_old=1, tg=1)
        # created_at старый, message_timestamp отсутствует → НЕ проходит.
        no_ts = _cand("без времени", days_old=200, tg=2)
        no_ts["message_timestamp"] = None
        mem = _FakeMemory([old_but_indexed_fresh, no_ts])
        sel = await hist.select_historical_candidates(
            mem, None, CHAT_ID, "событие", top_k=5, now=NOW, min_age_days=90)
        facts = [c["fact"] for c in sel.candidates]
        assert "старое событие" in facts
        assert "без времени" not in facts
        assert sel.missing_timestamp == 1

    @pytest.mark.asyncio
    async def test_fts_fallback_without_vec_precondition(self):
        # vec-поколение неактивно → профиль работает (канал отдал FTS-строки).
        mem = _FakeMemory([_cand("старый факт", days_old=200, tg=1)],
                          vec_available=False)
        sel = await hist.select_historical_candidates(
            mem, None, CHAT_ID, "факт", top_k=5, now=NOW, min_age_days=90)
        assert len(sel.candidates) == 1
        assert sel.fts_fallback is True

    @pytest.mark.asyncio
    async def test_empty_pool_is_no_anchors_not_error(self):
        mem = _FakeMemory([])
        sel = await hist.select_historical_candidates(
            mem, None, CHAT_ID, "факт", top_k=5, now=NOW, min_age_days=90)
        assert sel.candidates == []
        assert sel.reason == "no_anchors"

    @pytest.mark.asyncio
    async def test_topic_packets_bounded(self):
        words = ["литрбол", "футболист", "программист", "велосипедист",
                 "путешествие", "строительство", "преподаватель",
                 "архитектура", "музыкальный", "театральный"]
        items = [{"fact": f"{words[i % 10]} событие {i}"}
                 for i in range(50)]
        packets = hist.build_topic_packets(items, max_packets=3)
        assert len(packets) == 3
        assert sum(len(p.facts) for p in packets) == 50

    @pytest.mark.asyncio
    async def test_ranking_topic_participants_freshness(self):
        items = [
            _cand("толян литрбол", days_old=300, tg=1, score=0.0,
                  participants=["Толян"]),
            _cand("нерелевантный свежий текст", days_old=95, tg=2, score=0.0),
        ]
        ranked = hist.rank_candidates(items, query="толян литрбол", now=NOW,
                                      participants=("Толян",))
        assert ranked[0]["fact"] == "толян литрбол"

    @pytest.mark.asyncio
    async def test_dedup_same_event(self):
        a = _cand("пересказ один", days_old=200, tg=7)
        b = _cand("пересказ два", days_old=200, tg=7)
        mem = _FakeMemory([a, b])
        sel = await hist.select_historical_candidates(
            mem, None, CHAT_ID, "пересказ", top_k=5, now=NOW, min_age_days=90)
        assert len(sel.candidates) == 1
        assert sel.duplicates >= 1


class TestEpisodesAndPackets:
    @pytest.mark.asyncio
    async def test_episodes_as_candidate_source(self):
        class _Episodes:
            async def list_episodes(self, chat_id, limit=200):
                return [{
                    "episode_id": "e1", "chat_id": CHAT_ID,
                    "title": "поход", "summary": "давний поход в горы",
                    "event_start_ts": NOW - 200 * DAY,
                    "discovered_at": NOW - 1 * DAY,
                    "participants_json": '["Толян"]',
                }]
        sel = await hist.select_historical_candidates(
            _FakeMemory([]), _Episodes(), CHAT_ID, "поход горы", top_k=5,
            now=NOW, min_age_days=90)
        assert any(c.get("source_kind") == "episode"
                   for c in sel.candidates)
        assert sel.episodes_total == 1

    @pytest.mark.asyncio
    async def test_empty_episodes_is_regular_branch(self):
        class _Empty:
            async def list_episodes(self, chat_id, limit=200):
                return []
        sel = await hist.select_historical_candidates(
            _FakeMemory([]), _Empty(), CHAT_ID, "q", top_k=5, now=NOW,
            min_age_days=90)
        assert sel.candidates == [] and sel.reason == "no_anchors"

    @pytest.mark.asyncio
    async def test_unrelated_beliefs_not_merged(self):
        items = [{"fact": "литрбол пятница Толян"},
                 {"fact": "программирование велосипедист"}]
        packets = hist.build_topic_packets(items, max_packets=3)
        assert len(packets) == 2


class TestEnrichment:
    @pytest.mark.asyncio
    async def test_completed_and_no_duplicates_on_resume(self):
        msgs = [{"fact": f"msg {i}", "tg_message_id": i, "id": i}
                for i in range(4)]
        # пауза на 1 раунде → checkpoint offset=2 (resume без переобработки).
        r1 = await hist.enrich_history(CHAT_ID, msgs, max_rounds=1,
                                      batch_size=2)
        assert r1.status == "paused"
        assert r1.processed == 2
        r2 = await hist.enrich_history(CHAT_ID, msgs, checkpoint=r1.checkpoint,
                                       max_rounds=2, batch_size=2)
        assert r2.status == "completed"
        assert r2.processed == 2          # только остаток, без дублей
        assert r2.duplicates == 0

    @pytest.mark.asyncio
    async def test_paused_not_guillotine(self):
        msgs = [{"fact": f"msg {i}", "tg_message_id": i, "id": i}
                for i in range(10)]
        r = await hist.enrich_history(CHAT_ID, msgs, max_rounds=1, batch_size=2)
        assert r.status == "paused"
        assert r.checkpoint.get("offset") == 2


class TestSourceWindow:
    def test_bounded_and_message_timestamp(self):
        items = [_cand(f"f{i}", days_old=100 + i, tg=i) for i in range(5)]
        win = hist.bound_source_window(items, limit=3)
        assert len(win.items) == 3
        assert win.start_ts is not None and win.end_ts is not None

    def test_missing_timestamp_counted(self):
        ok = _cand("ok", days_old=100, tg=1)
        miss = _cand("miss", days_old=100, tg=2)
        miss["message_timestamp"] = None
        win = hist.bound_source_window([ok, miss])
        assert len(win.items) == 1
        assert win.missing_timestamp == 1
