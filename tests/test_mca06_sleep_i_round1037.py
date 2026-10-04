"""mca-06-sleep-paradigms — блок I (round 10.37) воспроизводимые
acceptance-сценарии T-4731 (spec.md §9.1/:381 п.8, §10 A14/A93/A94).

Пять+ детерминированных fixture-сценариев (фиксированные времена/данные,
seed через `MCA_DREAM_RANDOM_EXPLORE_ENABLED` OFF → ранжированный пайплайн),
каждый проверяет итоговый СТАТУС прогона и durable ОТЧЁТ §7.2
(`mca_pipeline_runs.report_json`, 8 групп полей):

  S1  слабые якоря (2 пересказа 1 события) → `insufficient_evidence`
      (не `written`, честный скип);
  S2  2 независимых первичных якоря + подтверждённое изменение → `written`
      (A14: обе группы ссылок раскрываются до исходных сообщений);
  S2b мост валиден, но нового вывода нет → `unchanged` (A94);
  S3  temporal ordering: «раньше» строго раньше «сейчас» → `written`;
      обратный порядок → `insufficient_evidence` (time_order);
  S4  cooldown завершённого прогона → `cooldown`;
      backoff ошибок → `cooldown` (detail=backoff);
  S5  per-chat квота → `budget`; глобальная защита → `budget`
      (detail различает per-chat/global).

Контракты: ADR-1028-9 D7/D8/D9, threat-failure THR-2/4/10.
Без коммитов/деплоя.
"""
import asyncio
import json
import time

import pytest

from services import mca_dream_evidence as ev
from services import mca_gates
from services import worker_settings
from services.database import DatabaseService
from services.dream_worker import DreamWorker

CHAT_ID = -100
NOW = int(time.time())
DAY = 86400

# Восемь групп полей отчёта §7.2 (T-4727).
REPORT_GROUPS = {"stages", "anchors", "date_ranges", "llm", "validation",
                 "written", "missing_timestamp", "run"}


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


class _FakeLLM:
    def __init__(self, *answers):
        self._answers = list(answers)

    async def generate_worker(self, role, messages, temperature=None):
        if self._answers:
            return self._answers.pop(0)
        return '{"paradigms":[]}'

    async def generate(self, messages, temperature=None, chat_id=None):
        return '{"beliefs":[]}'


class _Mem:
    """Кандидаты mca-07 (`retrieve_fact_candidates`) — канал исторического
    профиля; пустой `get_rag_facts` (OFF-паритет не задействован)."""
    _vec_available = False

    async def retrieve_fact_candidates(self, *a, **k):
        return []

    async def get_rag_facts(self, *a, **k):
        return []


class _Sel:
    def __init__(self, candidates, *, missing_timestamp=0, fts_fallback=False,
                 reason=None, selection_meta=None):
        self.candidates = list(candidates)
        self.missing_timestamp = missing_timestamp
        self.fts_fallback = fts_fallback
        self.reason = reason
        self.selection_meta = selection_meta


def _cand(fact, *, days_old=200, tg=None, fid=None, origin="chat_history",
          self_referential=False, **extra):
    d = {
        "id": fid if fid is not None else abs(hash(fact)) % 100000,
        "chat_id": CHAT_ID,
        "fact": fact,
        "origin": origin,
        "rag_ts": NOW - days_old * DAY,
        "message_timestamp": NOW - days_old * DAY,
        "created_at": NOW - days_old * DAY,
        "tg_message_id": tg,
        "target_user": "Толян",
        "self_referential": self_referential,
    }
    d.update(extra)
    return d


def _packet(texts, *, target="Толян", created_at=None):
    created_at = created_at if created_at is not None else NOW - 3600
    return {
        "beliefs": [{"fact": texts[0], "id": 1, "target_user": target,
                     "created_at": created_at}],
        "recent": [{"fact": t, "importance": 5} for t in texts[1:]],
        "source_ids": [1],
    }


def _patch_settings_source(monkeypatch, mapping):
    """Подмена `resolve_setting_with_source` (источник истины resolver'а)."""
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


def _trace_capture(monkeypatch):
    seen = []

    def _trace(chat_id, step, status, reason=None, extra=None, **kw):
        seen.append({"step": step, "status": status, "reason": reason,
                     "extra": extra or {}})

    import services.dream_worker as dw
    monkeypatch.setattr(dw, "_trace_deep", _trace)
    return seen


def _worker(db, sel, llm, monkeypatch, *, packet=None, resolver_on=False):
    """Собрать DreamWorker с детерминированными фикстурами.

    `resolver_on=False` → прямой paradigm-пайплайн (S1–S3, как блок D+E);
    `resolver_on=True` → единый gate-resolver (S4–S5, как блок B/F)."""
    import services.dream_worker as dw
    import services.mca_dream_history as hist
    monkeypatch.setattr(mca_gates, "dream_gate_resolver_enabled",
                        lambda: resolver_on)
    # Детерминированный материал: ранжированный пайплайн (без RandomSource),
    # seed-контракт mca-10a не задействован — воспроизводимость фикстуры.
    monkeypatch.setattr(mca_gates, "dream_random_explore_enabled",
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


async def _report(db, chat_id=CHAT_ID):
    """Последний durable отчёт §7.2 (mca_pipeline_runs.report_json)."""
    cur = await db.db.execute(
        "SELECT * FROM mca_pipeline_runs WHERE chat_id = ? "
        "ORDER BY started_at DESC, rowid DESC LIMIT 1", (int(chat_id),))
    row = await cur.fetchone()
    assert row is not None, "durable run-строка должна существовать (T-4726)"
    assert row["report_json"], "report_json должен быть заполнен (T-4727)"
    rep = json.loads(row["report_json"])
    assert set(rep) == REPORT_GROUPS, "отчёт §7.2 — 8 групп полей"
    return rep


PARADIGM_ANSWER = (
    '{"paradigms":[{"text":"Толян изменил привычки литрбол",'
    '"anchors":[1,2]}]}')

BRIDGE_ANCHORS = [
    _cand("Толян пил литрбол каждую пятницу", tg=1),
    _cand("Толян рассказывал про литрбол друзьям", tg=2),
]


# ── S1: слабые якоря → insufficient_evidence ────────────────────────────────

class TestScenarioWeakAnchors:
    @pytest.mark.asyncio
    async def test_s1_two_retellings_one_event_insufficient(self, db,
                                                            monkeypatch):
        # 2 якоря одного первичного события → independence=1 < 2.
        a = _cand("Толян пил литрбол", tg=7)
        b = _cand("Толян пил литрбол пересказ", tg=7)
        w = _worker(db, _Sel([a, b]), _FakeLLM(), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)

        assert out["status"] == "insufficient_evidence"
        assert out["paradigms"] == 0
        rep = await _report(db)
        assert rep["anchors"]["independent"] == 1
        assert rep["anchors"]["found"] == 2
        assert rep["written"] == 0
        assert rep["run"]["manual"] is True


# ── S2: 2 независимых первичных якоря → written (A14) ───────────────────────

class TestScenarioTwoIndependentAnchors:
    @pytest.mark.asyncio
    async def test_s2_written_and_chain_resolves(self, db, monkeypatch):
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                    monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)

        assert out["status"] == "written"
        assert out["paradigms"] == 1
        rep = await _report(db)
        assert rep["written"] == 1
        assert rep["anchors"]["independent"] == 2
        assert rep["anchors"]["found"] == 2
        assert rep["validation"]["bridge_ok"] == 1
        assert rep["llm"]["calls"] == 1
        # A14: цепочка раскрывается до исходных сообщений.
        rows = await db.list_recent_beliefs(chat_id=CHAT_ID, limit=10,
                                            belief_type="paradigm")
        assert rows
        chain = await ev.expand_chain(db, chat_id=CHAT_ID,
                                      fact_id=rows[0]["id"])
        assert chain["delta"]["new"] == "Толян изменил привычки литрбол"
        assert chain["messages"], "обе группы ссылок → до сообщений"
        assert {m["tg_message_id"] for m in chain["messages"]} == {1, 2}


# ── S2b: валидный мост, но нового вывода нет → unchanged ────────────────────

class TestScenarioUnchanged:
    @pytest.mark.asyncio
    async def test_s2b_no_new_conclusion_unchanged(self, db, monkeypatch):
        # Мост проходит валидацию, но LLM не выдал парадигм → честный
        # `unchanged` (полноценный проверяемый исход, не ошибка; A94).
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM('{"paradigms":[]}'),
                    monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)

        assert out["status"] == "unchanged"
        assert out["paradigms"] == 0
        rep = await _report(db)
        assert rep["written"] == 0
        assert rep["anchors"]["independent"] == 2
        assert rep["llm"]["calls"] == 1


# ── S3: temporal ordering ───────────────────────────────────────────────────

class TestScenarioTemporalOrdering:
    @pytest.mark.asyncio
    async def test_s3_earlier_strictly_before_now_written(self, db,
                                                          monkeypatch):
        # «раньше» (200 дней) строго раньше «сейчас» (packet created_at) →
        # валидный мост → written; диапазоны дат от исходных сообщений.
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                    monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written"
        rep = await _report(db)
        assert rep["validation"]["bridge_ok"] == 1
        assert rep["date_ranges"]["max"] == NOW - 200 * DAY

    @pytest.mark.asyncio
    async def test_s3_reversed_order_insufficient(self, db, monkeypatch):
        # Якорь НЕ раньше «сейчас» (свежее периода пакета) → time_order fail →
        # честный insufficient_evidence, НЕ written.
        a = _cand("Толян пил литрбол вчера", days_old=-1, tg=1)
        b = _cand("Толян рассказывал про литрбол", tg=2)
        seen = _trace_capture(monkeypatch)
        w = _worker(db, _Sel([a, b]), _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)

        assert out["status"] == "insufficient_evidence"
        rep = await _report(db)
        assert rep["written"] == 0
        assert rep["anchors"]["independent"] == 2
        # Причина отказа валидатора — временной порядок.
        assert any(t["reason"] == "time_order" for t in seen)

    @pytest.mark.asyncio
    async def test_s3_reject_reasons_in_report(self, db, monkeypatch):
        # mca-06 [M-1]/§7.2 п.2: два отказа мост-валидатора (no_subject +
        # time_order) → причины отсева заполнены в durable report_json
        # (не только в trace-логе).
        a = _cand("Толян пил литрбол каждую пятницу", tg=1)
        b = _cand("спартакиада проходила в городе", tg=2)
        c = _cand("марафон собрал участников", tg=3)
        d = _cand("Толян литрбол вчера", days_old=-1, tg=4)
        answer = ('{"paradigms":['
                  '{"text":"спартакиада прошла","anchors":[2,3]},'
                  '{"text":"Толян изменил литрбол","anchors":[1,4]}]}')
        w = _worker(db, _Sel([a, b, c, d]), _FakeLLM(answer), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)

        assert out["status"] == "insufficient_evidence"
        rep = await _report(db)
        assert rep["written"] == 0
        assert rep["anchors"]["reject_reasons"] == {"no_subject": 1,
                                                    "time_order": 1}
        assert rep["validation"]["bridge_reject"] == 2


# ── S4: cooldown / backoff → cooldown ───────────────────────────────────────

def _gate_settings(monkeypatch):
    _patch_settings_source(monkeypatch, {
        "memory.dream_enabled": True,
        "flags.deep_sleep_enabled": True,
        "flags.graph_rag_enabled": True,
    })
    _patch_cached(monkeypatch, {"memory.deep_sleep_trigger": "after_sleep"})


class TestScenarioCooldownBackoff:
    @pytest.mark.asyncio
    async def test_s4_cooldown_returns_cooldown(self, db, monkeypatch):
        _gate_settings(monkeypatch)
        seen = _trace_capture(monkeypatch)

        async def _last(chat_id=None):
            return int(time.time()) - 3600     # завершённый прогон час назад

        monkeypatch.setattr(db, "last_deep_attempt", _last)
        w = _worker(db, _Sel([]), _FakeLLM(), monkeypatch, resolver_on=True)
        out = await w._run_deep_once(CHAT_ID, manual=False)

        assert out["status"] == "cooldown"
        assert out["paradigms"] == 0
        assert any(t["reason"] == "cooldown" for t in seen)
        rep = await _report(db)
        assert rep["written"] == 0
        assert rep["run"]["manual"] is False

    @pytest.mark.asyncio
    async def test_s4_backoff_maps_to_cooldown(self, db, monkeypatch):
        # Ошибка недавно + нет новых dream-данных → ограниченный backoff;
        # причина та же `cooldown`, detail различим (`backoff`).
        _gate_settings(monkeypatch)
        seen = _trace_capture(monkeypatch)

        async def _err(chat_id):
            return int(time.time()) - 10, 1     # последняя ошибка, streak=1

        async def _new_data(chat_id):
            return None

        async def _last(chat_id=None):
            return None

        monkeypatch.setattr(db, "deep_error_state", _err)
        monkeypatch.setattr(db, "latest_dream_data_ts", _new_data)
        monkeypatch.setattr(db, "last_deep_attempt", _last)
        w = _worker(db, _Sel([]), _FakeLLM(), monkeypatch, resolver_on=True)
        out = await w._run_deep_once(CHAT_ID, manual=False)

        assert out["status"] == "cooldown"
        cd = [t for t in seen if t["reason"] == "cooldown"]
        assert cd and "backoff" in str(cd[0]["extra"].get("detail") or "")
        rep = await _report(db)
        assert rep["written"] == 0


# ── S5: budget / quotas (per-chat и global) → budget ────────────────────────

class TestScenarioBudgetQuotas:
    @pytest.mark.asyncio
    async def test_s5_per_chat_quota_budget(self, db, monkeypatch):
        _gate_settings(monkeypatch)

        async def _count(since_ts, *, chat_id=None):
            return 1                            # per-chat лимит (default 1)

        async def _last(chat_id=None):
            return None

        monkeypatch.setattr(db, "count_deep_attempts", _count)
        monkeypatch.setattr(db, "last_deep_attempt", _last)
        w = _worker(db, _Sel([]), _FakeLLM(), monkeypatch, resolver_on=True)
        out = await w._run_deep_once(CHAT_ID, manual=False)

        assert out["status"] == "budget"        # daily_limit→budget (D6)
        rep = await _report(db)
        assert rep["written"] == 0
        # detail различает per-chat.
        st = await mca_gates.resolve_dream_gate(
            db, CHAT_ID, memory=object(), now=int(time.time()), manual=False,
            inside_run=True, include_master=False, include_deep=True)
        assert st.reason == "resource_limit"
        assert "per-chat" in (st.detail or "")

    @pytest.mark.asyncio
    async def test_s5_global_cap_budget(self, db, monkeypatch):
        # Глобальная защита сохранена: per-chat свободен, глобальный кап
        # достигнут → `budget` с глобальным detail.
        _gate_settings(monkeypatch)

        async def _count(since_ts, *, chat_id=None):
            return 0 if chat_id is not None else \
                mca_gates.dream_global_attempts_limit()

        async def _last(chat_id=None):
            return None

        monkeypatch.setattr(db, "count_deep_attempts", _count)
        monkeypatch.setattr(db, "last_deep_attempt", _last)
        w = _worker(db, _Sel([]), _FakeLLM(), monkeypatch, resolver_on=True)
        out = await w._run_deep_once(CHAT_ID, manual=False)

        assert out["status"] == "budget"
        rep = await _report(db)
        assert rep["written"] == 0
        st = await mca_gates.resolve_dream_gate(
            db, CHAT_ID, memory=object(), now=int(time.time()), manual=False,
            inside_run=True, include_master=False, include_deep=True)
        assert st.reason == "resource_limit"
        assert "global" in (st.detail or "")


# ── Воспроизводимость: повтор детерминированной фикстуры ────────────────────

class TestScenarioReproducibility:
    @pytest.mark.asyncio
    async def test_s2_repeat_deterministic_written(self, db, monkeypatch):
        # Та же фикстура на том же fingerprint → тот же статус (written) и
        # повтор идемпотентен (0 новых записей, duplicate).
        w1 = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                     monkeypatch)
        out1 = await w1._run_deep_once(CHAT_ID, manual=True)
        assert out1["status"] == "written"
        total = await db.count_paradigms(CHAT_ID)
        w2 = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                     monkeypatch)
        out2 = await w2._run_deep_once(CHAT_ID, manual=True)
        assert out2["status"] == "duplicate"
        assert await db.count_paradigms(CHAT_ID) == total
        rep = await _report(db)
        assert rep["written"] == 0
