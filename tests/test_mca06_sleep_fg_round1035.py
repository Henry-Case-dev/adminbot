"""mca-06-sleep-paradigms — блоки F+G (round 10.35) targeted-тесты.

Покрытие по контрактам (spec.md §6–§8.5, ADR-1028-9 D5/D9/D11,
threat-failure THR-5/6/10/11/12/13; tasks T-4723…T-4728):
  * T-4723 per-chat квота ≠ глобальная защита; глобальный кап сохранён.
  * T-4724 cooldown ⊥ backoff ⊥ ресурсы; bounded-экспонента; сброс по данным.
  * T-4725 per-chat singleflight + повторная проверка `last_deep_attempt`.
  * T-4726 процессы сна code-declared в реестре mca-17a (`not_run`→`implemented`).
  * T-4727 durable отчёт прогона `mca_pipeline_runs.report_json` (v25, 8 групп,
    R17-safe); OFF → только прежний `_trace_deep`/лог.
  * T-4728 согласованность запись/счётчик/статус (`written` только при fact_id).
"""
import asyncio
import json
import time

import pytest

from services import mca_gates
from services.database import DatabaseService
from services.dream_worker import DreamWorker

CHAT_ID = -100
CHAT_ID2 = -200
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


class _QuotaDb:
    """Минимальный db для `_resource_gate` (per-chat/global counts)."""

    def __init__(self, per=None, global_used=0):
        self.per = dict(per or {})
        self.global_used = int(global_used)

    async def count_deep_attempts(self, since_ts, *, chat_id=None):
        if chat_id is None:
            return self.global_used
        return int(self.per.get(chat_id, 0))


class _BackoffDb:
    """Минимальный db для `_cooldown_gate` (backoff/cooldown)."""

    def __init__(self, *, last_error=None, streak=0, new_data=None,
                 last_attempt=None):
        self._last_error = last_error
        self._streak = streak
        self._new_data = new_data
        self._last_attempt = last_attempt

    async def deep_error_state(self, chat_id):
        return self._last_error, self._streak

    async def latest_dream_data_ts(self, chat_id):
        return self._new_data

    async def last_deep_attempt(self, chat_id=None):
        return self._last_attempt


# ── T-4723: per-chat / global квоты ─────────────────────────────────────────

class TestQuotas:
    @pytest.mark.asyncio
    async def test_quota_source_split(self):
        assert mca_gates.dream_per_chat_attempts_limit() >= 1
        assert (mca_gates.dream_global_attempts_limit()
                > mca_gates.dream_per_chat_attempts_limit())

    @pytest.mark.asyncio
    async def test_single_chat_fails_only_its_per_chat_quota(self):
        # A93: чат 1 исчерпал per-chat; чат 2 обрабатывается (глобальный кап
        # не снят, но ещё не достигнут).
        db = _QuotaDb(per={CHAT_ID: 1}, global_used=1)
        st1 = await mca_gates._resource_gate(db, CHAT_ID, NOW)
        assert st1 is not None and st1.reason == "resource_limit"
        assert "per-chat" in (st1.detail or "")
        st2 = await mca_gates._resource_gate(db, CHAT_ID2, NOW)
        assert st2 is None, "другой чат не блокируется чужой попыткой"

    @pytest.mark.asyncio
    async def test_global_cap_still_works(self):
        db = _QuotaDb(per={CHAT_ID: 0, CHAT_ID2: 0},
                      global_used=mca_gates.dream_global_attempts_limit())
        st = await mca_gates._resource_gate(db, CHAT_ID, NOW)
        assert st is not None and st.reason == "resource_limit"
        assert "global" in (st.detail or "")

    @pytest.mark.asyncio
    async def test_quotas_off_parity_global_only(self, monkeypatch):
        import services.mca_gates as mg
        monkeypatch.setattr(mg, "dream_quotas_split_enabled", lambda: False)
        # Прежний путь: глобальный count >= 1 → resource_limit (default 1);
        # per-chat не учитывается.
        db = _QuotaDb(per={}, global_used=1)
        st = await mg._resource_gate(db, CHAT_ID, NOW)
        assert st is not None
        assert "global daily deep attempts: used=1, limit=1" in (st.detail or "")

    @pytest.mark.asyncio
    async def test_count_deep_attempts_per_chat_real_db(self, db):
        await db.log_dream_event(CHAT_ID, NOW, kind="deep_skip",
                                 tokens=10, status="error")
        await db.log_dream_event(CHAT_ID2, NOW, kind="deep_run",
                                 tokens=10, status="ok")
        assert await db.count_deep_attempts(NOW - DAY, chat_id=CHAT_ID) == 1
        assert await db.count_deep_attempts(NOW - DAY, chat_id=CHAT_ID2) == 1
        assert await db.count_deep_attempts(NOW - DAY) == 2


# ── T-4724: cooldown / backoff / ресурсы ────────────────────────────────────

class TestBackoff:
    def test_exponential_bounded(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "_int_setting_min",
                            lambda name, default, minimum=1: {
                                "MCA_DREAM_BACKOFF_BASE_SECONDS": 10,
                                "MCA_DREAM_BACKOFF_CAP_SECONDS": 100,
                            }.get(name, default))
        assert mca_gates.dream_backoff_seconds(1) == 10
        assert mca_gates.dream_backoff_seconds(2) == 20
        assert mca_gates.dream_backoff_seconds(3) == 40
        # цикл не разгоняется вечно — cap
        assert mca_gates.dream_backoff_seconds(20) == 100

    @pytest.mark.asyncio
    async def test_backoff_blocks_with_distinct_detail(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "dream_backoff_seconds",
                            lambda streak: 3600)
        st = await mca_gates._cooldown_gate(
            _BackoffDb(last_error=NOW - 10, streak=2), CHAT_ID, NOW)
        assert st is not None and st.reason == "cooldown"
        assert "backoff" in (st.detail or "")
        assert "min_interval_hours" not in (st.detail or "")

    @pytest.mark.asyncio
    async def test_backoff_reset_on_new_data(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "dream_backoff_seconds",
                            lambda streak: 3600)
        st = await mca_gates._cooldown_gate(
            _BackoffDb(last_error=NOW - 10, streak=3,
                       new_data=NOW - 5), CHAT_ID, NOW)
        # новые dream-данные после ошибки → ретрай разрешён (backoff снят)
        assert st is None

    @pytest.mark.asyncio
    async def test_backoff_expires(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "dream_backoff_seconds",
                            lambda streak: 60)
        st = await mca_gates._cooldown_gate(
            _BackoffDb(last_error=NOW - 600, streak=1), CHAT_ID, NOW)
        assert st is None

    @pytest.mark.asyncio
    async def test_cooldown_and_backoff_distinct(self, monkeypatch):
        # обычный cooldown (без ошибок) — detail про min_interval_hours
        st = await mca_gates._cooldown_gate(
            _BackoffDb(last_attempt=NOW - 3600), CHAT_ID, NOW)
        assert st is not None and "min_interval_hours" in (st.detail or "")
        assert "backoff" not in (st.detail or "")


# ── T-4725: manual singleflight + recheck ───────────────────────────────────

class _FakeLLM:
    def __init__(self, *answers):
        self._answers = list(answers)

    async def generate_worker(self, role, messages, temperature=None):
        if self._answers:
            return self._answers.pop(0)
        return '{"paradigms":[]}'

    async def generate(self, messages, temperature=None, chat_id=None):
        return '{"beliefs":[]}'


class TestManualSingleflight:
    @pytest.mark.asyncio
    async def test_same_chat_inflight_coalesced(self, db):
        w = DreamWorker(db, memory=None, llm=_FakeLLM())
        w._deep_chat_inflight.add(CHAT_ID)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] in ("duplicate",)   # без дублей
        assert out["paradigms"] == 0

    @pytest.mark.asyncio
    async def test_manual_recheck_blocks_race(self, db, monkeypatch):
        w = DreamWorker(db, memory=None, llm=_FakeLLM())
        w._manual_request_ts = NOW

        async def _last(chat_id=None):
            return NOW        # прогон завершился после старта запроса

        monkeypatch.setattr(db, "last_deep_attempt", _last)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "duplicate"

    @pytest.mark.asyncio
    async def test_manual_recheck_off_parity(self, db, monkeypatch):
        import services.mca_gates as mg
        monkeypatch.setattr(mg, "dream_quotas_split_enabled", lambda: False)
        w = DreamWorker(db, memory=None, llm=_FakeLLM())
        w._manual_request_ts = NOW

        async def _last(chat_id=None):
            return NOW

        monkeypatch.setattr(db, "last_deep_attempt", _last)
        # OFF → recheck не применяется; memory=None → no_memory/канон disabled
        # (как было в прежнем прогоне).
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] in ("no_memory", "disabled")


# ── T-4726: реестр mca-17a ──────────────────────────────────────────────────

class TestRegistry:
    def test_sleep_deep_declared_and_implemented(self, monkeypatch):
        from services import mca_process_registry as reg
        monkeypatch.setattr(reg, "_settings_gate", lambda gate: True)
        p = reg.get_process("sleep.deep")
        assert p is not None and p.declared_instrumented
        assert "DREAM_DEEP_RUN" in p.event_names
        assert reg.runtime_status(
            p, event_names_present=frozenset({"DREAM_DEEP_RUN"})) == \
            reg.STATUS_IMPLEMENTED
        assert reg.runtime_status(
            p, event_names_present=frozenset()) == reg.STATUS_NOT_RUN

    def test_sleep_deep_disabled_when_gate_off(self, monkeypatch):
        from services import mca_process_registry as reg
        monkeypatch.setattr(reg, "_settings_gate", lambda gate: False)
        p = reg.get_process("sleep.deep")
        assert reg.runtime_status(
            p, event_names_present=frozenset({"DREAM_DEEP_RUN"})) == \
            reg.STATUS_DISABLED

    def test_sleep_deep_pipeline_registered(self):
        from services import mca_process_registry as reg
        pv = reg.get_pipeline("sleep.deep")
        assert pv is not None
        names = {s.name for s in pv.stages}
        assert {"collect", "anchors", "bridge", "write"} <= names


# ── T-4727/T-4728: отчёт прогона + согласованность ──────────────────────────

class _Mem:
    _vec_available = False

    async def retrieve_fact_candidates(self, *a, **k):
        return []

    async def get_rag_facts(self, *a, **k):
        return []


class _Sel:
    def __init__(self, candidates, *, missing_timestamp=0, fts_fallback=False,
                 reason=None, excluded_young=0, duplicates=0):
        self.candidates = list(candidates)
        self.missing_timestamp = missing_timestamp
        self.fts_fallback = fts_fallback
        self.reason = reason
        self.excluded_young = excluded_young
        self.duplicates = duplicates


def _cand(fact, *, tg=None, days_old=200, fid=None):
    return {"id": fid if fid is not None else abs(hash(fact)) % 100000,
            "chat_id": CHAT_ID, "fact": fact, "origin": "chat_history",
            "rag_ts": NOW - days_old * DAY,
            "message_timestamp": NOW - days_old * DAY,
            "created_at": NOW - days_old * DAY, "tg_message_id": tg,
            "target_user": "Толян"}


def _packet(texts):
    return {"beliefs": [{"fact": texts[0], "id": 1, "target_user": "Толян",
                         "created_at": NOW - 3600}],
            "recent": [{"fact": t, "importance": 5} for t in texts[1:]],
            "source_ids": [1]}


PARADIGM_ANSWER = (
    '{"paradigms":[{"text":"Толян изменил привычки литрбол",'
    '"anchors":[1,2]}]}')


def _worker(db, sel, llm, monkeypatch, *, packet=None):
    import services.dream_worker as dw
    import services.mca_dream_history as hist
    monkeypatch.setattr(mca_gates, "dream_gate_resolver_enabled",
                        lambda: False)
    monkeypatch.setattr(dw.mca_gates, "dream_gate_resolver_enabled",
                        lambda: False)

    async def _fake_select(*a, **k):
        return sel

    monkeypatch.setattr(hist, "select_historical_candidates", _fake_select)
    w = DreamWorker(db, memory=_Mem(), llm=llm)
    pkt = packet if packet is not None else _packet(["Толян литрбол"])

    async def _build(chat_id, now, since_ts):
        return pkt

    async def _traits(chat_id, now, *, manual=False):
        return 0

    async def _budget(*a, **k):
        return True

    monkeypatch.setattr(w, "_build_deep_packet", _build)
    monkeypatch.setattr(w, "_run_persona_traits_step", _traits)
    monkeypatch.setattr(w, "_deep_budget_ok", _budget)
    return w


async def _db_runs(db, chat_id=CHAT_ID):
    cursor = await db.db.execute(
        "SELECT * FROM mca_pipeline_runs WHERE chat_id = ? "
        "ORDER BY started_at DESC", (int(chat_id),))
    return [dict(r) for r in await cursor.fetchall()]


BRIDGE_ANCHORS = [
    _cand("Толян пил литрбол каждую пятницу", tg=1),
    _cand("Толян рассказывал про литрбол друзьям", tg=2),
]


class TestRunReport:
    @pytest.mark.asyncio
    async def test_ddl_v25_columns_and_version(self, db):
        cur = await db.db.execute("PRAGMA user_version")
        assert int((await cur.fetchone())[0]) == 25
        cols = {r["name"] for r in await (
            await db.db.execute("PRAGMA table_info(mca_pipeline_runs)")
        ).fetchall()}
        assert {"chat_id", "report_json"} <= cols
        idx = await (await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_mca_pipeline_runs_chat'")).fetchone()
        assert idx is not None

    @pytest.mark.asyncio
    async def test_v25_idempotent(self, db):
        await db._migrate_dream_runs_v25()
        await db._migrate_dream_runs_v25()
        cur = await db.db.execute("PRAGMA user_version")
        assert int((await cur.fetchone())[0]) == 25

    @pytest.mark.asyncio
    async def test_report_has_all_eight_groups(self, db, monkeypatch):
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                    monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written"
        runs = await _db_runs(db)
        assert runs and runs[0]["report_json"]
        rep = json.loads(runs[0]["report_json"])
        assert set(rep) == {"stages", "anchors", "date_ranges", "llm",
                            "validation", "written", "missing_timestamp", "run"}
        assert rep["run"]["chat_id"] == CHAT_ID
        assert rep["run"]["manual"] is True
        assert rep["written"] == 1
        assert rep["anchors"]["found"] >= 2
        assert rep["llm"]["calls"] == 1

    @pytest.mark.asyncio
    async def test_report_profile_reject_reasons(self, db, monkeypatch):
        # mca-06 [M-1]/§7.2 п.2: профильные исключения (excluded_young/
        # duplicates) из HistoricalSelection попадают в durable report_json.
        sel = _Sel(list(BRIDGE_ANCHORS), excluded_young=3, duplicates=2,
                   missing_timestamp=1)
        w = _worker(db, sel, _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written"
        rep = json.loads((await _db_runs(db))[0]["report_json"])
        assert rep["anchors"]["reject_reasons"] == {"excluded_young": 3,
                                                    "duplicates": 2}

    @pytest.mark.asyncio
    async def test_profile_off_uses_legacy_rag_channel(self, db, monkeypatch):
        # mca-06 [L-1]: dedicated OFF-тест `MCA_DREAM_HISTORICAL_PROFILE_ENABLED`.
        # OFF → legacy-ветка (get_rag_facts → top_k → возраст); профильный
        # канал `select_historical_candidates` не вызывается.
        import services.mca_dream_history as hist
        import services.dream_worker as dw

        monkeypatch.setattr(dw.mca_gates, "dream_gate_resolver_enabled",
                            lambda: False)
        monkeypatch.setattr(dw.mca_gates,
                            "dream_historical_profile_enabled", lambda: False)

        class _LegacyMem:
            _vec_available = True

            def __init__(self):
                self.retrieve_calls = 0
                self.rag_calls = 0

            async def retrieve_fact_candidates(self, *a, **k):
                self.retrieve_calls += 1
                return []

            async def get_rag_facts(self, chat_id, query):
                self.rag_calls += 1
                return [dict(a) for a in BRIDGE_ANCHORS]

        async def _must_not_select(*a, **k):
            raise AssertionError("HISTORICAL_PROFILE OFF → legacy branch")

        monkeypatch.setattr(hist, "select_historical_candidates",
                            _must_not_select)
        mem = _LegacyMem()
        w = DreamWorker(db, memory=mem, llm=_FakeLLM(PARADIGM_ANSWER))

        async def _build(chat_id, now, since_ts):
            return _packet(["Толян литрбол"])

        async def _traits(chat_id, now, *, manual=False):
            return 0

        async def _budget(*a, **k):
            return True

        monkeypatch.setattr(w, "_build_deep_packet", _build)
        monkeypatch.setattr(w, "_run_persona_traits_step", _traits)
        monkeypatch.setattr(w, "_deep_budget_ok", _budget)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written"
        assert mem.rag_calls == 1
        assert mem.retrieve_calls == 0

    @pytest.mark.asyncio
    async def test_report_r17_no_raw_text(self, db, monkeypatch):
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                    monkeypatch)
        await w._run_deep_once(CHAT_ID, manual=True)
        raw = (await _db_runs(db))[0]["report_json"]
        assert "пил литрбол" not in raw
        assert "рассказывал" not in raw

    @pytest.mark.asyncio
    async def test_skip_run_has_run_row_and_reason(self, db, monkeypatch):
        # Пустой исторический пул → no_anchors, но run-строка создана.
        w = _worker(db, _Sel([]), _FakeLLM(), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "no_anchors"
        runs = await _db_runs(db)
        assert runs and runs[0]["status"] in ("succeeded", "failed")
        assert runs[0]["report_json"]

    @pytest.mark.asyncio
    async def test_reports_off_no_run_row_no_events(self, db, monkeypatch):
        monkeypatch.setattr(mca_gates, "dream_run_reports_enabled",
                            lambda: False)
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                    monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written"
        assert await _db_runs(db) == []


class TestWriteConsistency:
    @pytest.mark.asyncio
    async def test_write_failure_after_count_is_error(self, db, monkeypatch):
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                    monkeypatch)

        async def _boom(*a, **k):
            raise RuntimeError("write failed")

        monkeypatch.setattr(w, "_write_paradigm", _boom)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "error"
        assert out["paradigms"] == 0
        # скип с честным status='error' в аудите (не duplicate/успех)
        cursor = await db.db.execute(
            "SELECT status FROM memory_dream_log WHERE chat_id = ? "
            "AND kind='deep_skip' ORDER BY id DESC LIMIT 1", (CHAT_ID,))
        row = await cursor.fetchone()
        assert row is not None and str(row["status"]) == "error"

    @pytest.mark.asyncio
    async def test_written_only_with_fact_id(self, db, monkeypatch):
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                    monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written" and out["paradigms"] == 1
        assert await db.count_paradigms(CHAT_ID) == 1
