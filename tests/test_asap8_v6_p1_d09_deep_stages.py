"""ASAP 8 v6 P1 — D09.2/M13: Deep Sleep stage truth (§18F.6).

Стадии прогона «глубокого сна» в durable-отчёте (mca_pipeline_runs.
report_json) честные:
* bridge succeeded — ТОЛЬКО после валидного model output (no-response →
  failed/no_response);
* validate succeeded — только после валидного parse (+ мост-валидатор);
  «нет новых выводов» — нейтральный skipped/no_new_insight (не авария);
* write succeeded — только при подтверждённой персистенции (written > 0);
  all-write-failed → failed/all_write_failed; все дубли → skipped.

TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/D09 (M13)
"""
import asyncio
import json

import pytest

from config.settings import settings
from services import hot_config as hot
from services import mca_gates
from services.database import DatabaseService
from services.dream_worker import DreamWorker

CHAT_ID = -100
_DAY = 86400
_NOW = 1_800_000_000


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _hot_cache(monkeypatch, values: dict | None = None):
    class _FakeHotCache:
        def __init__(self, values):
            self._values = dict(values or {})

        def get(self, key, default=None):
            return self._values.get(key, default)

    monkeypatch.setattr(hot, "_cache", _FakeHotCache(values))


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
        self.calls.append((role, messages, temperature))
        if self._answers:
            answer = self._answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return '{"paradigms":[]}'

    async def generate(self, messages, temperature=None, chat_id=None):
        return '{"beliefs":[]}'


def _old_anchor(fact, *, days=200, author=None):
    return ("chat_history", fact, _NOW - days * _DAY, author)


def _worker(db, memory, llm, *, values, monkeypatch):
    _hot_cache(monkeypatch, values)
    monkeypatch.setattr(mca_gates, "dream_evidence_typing_enabled",
                        lambda: False)
    monkeypatch.setattr(mca_gates, "dream_run_reports_enabled", lambda: True)
    return DreamWorker(db, memory=memory, llm=llm)


async def _reports(db, limit: int = 2) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT report_json FROM mca_pipeline_runs "
        "WHERE pipeline_type = 'sleep.deep' AND report_json IS NOT NULL "
        "ORDER BY created_at DESC, pipeline_run_id DESC LIMIT ?", (limit,))
    return [json.loads(r["report_json"]) for r in
            await cursor.fetchall()]


def _stage(rep: dict, name: str) -> dict | None:
    for s in (rep.get("stages") or []):
        if s.get("name") == name:
            return s
    return None


_BRIDGE_OK = ('{"paradigms":[{"text":"Толян раньше пил, теперь спортсмен",'
              '"anchors":[1,2]}]}')


class TestDeepSleepStageTruth:
    @pytest.mark.asyncio
    async def test_success_all_stages_succeeded(self, db, monkeypatch):
        await db.insert_graph_fact(CHAT_ID, "толян снова в баре",
                                   "chat_history", None, importance=6)
        memory = _FakeMemory([
            _old_anchor("толян пил каждую пятницу", author="Толян"),
            _old_anchor("толян бросил пить в 2024")])
        llm = _FakeWorkerLLM(_BRIDGE_OK)
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch, values={
            "flags.deep_sleep_enabled": True})
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "ok"
        rep = (await _reports(db, 1))[0]
        assert _stage(rep, "bridge")["status"] == "succeeded"
        assert _stage(rep, "validate")["status"] == "succeeded"
        assert _stage(rep, "write")["status"] == "succeeded"
        assert int(rep["written"]) == 1

    @pytest.mark.asyncio
    async def test_no_response_bridge_failed_not_succeeded(
            self, db, monkeypatch):
        """M13: no-response модели — НЕ premature success на стадии bridge."""
        await db.insert_graph_fact(CHAT_ID, "толян снова в баре",
                                   "chat_history", None, importance=6)
        memory = _FakeMemory([
            _old_anchor("толян пил каждую пятницу"),
            _old_anchor("толян бросил пить в 2024")])
        llm = _FakeWorkerLLM(RuntimeError("llm down"))
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch, values={
            "flags.deep_sleep_enabled": True})
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "error"
        rep = (await _reports(db, 1))[0]
        bridge = _stage(rep, "bridge")
        assert bridge["status"] == "failed"
        assert bridge.get("reason") == "no_response"
        # провалившаяся стадия bridge не помечена succeeded нигде
        assert all(s.get("status") != "succeeded" or s.get("name") != "bridge"
                   for s in rep.get("stages") or [])

    @pytest.mark.asyncio
    async def test_all_write_failed_stage_failed(self, db, monkeypatch):
        """M13: all-write-failed — провал стадии write (не «успешная
        пустота»); терминальный статус прогона — error."""
        await db.insert_graph_fact(CHAT_ID, "толян снова в баре",
                                   "chat_history", None, importance=6)
        memory = _FakeMemory([
            _old_anchor("толян пил каждую пятницу"),
            _old_anchor("толян бросил пить в 2024")])
        llm = _FakeWorkerLLM(_BRIDGE_OK)
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch, values={
            "flags.deep_sleep_enabled": True})

        async def _boom(*a, **kw):
            raise RuntimeError("db write down")

        monkeypatch.setattr(worker, "_write_paradigm", _boom)
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "error"
        rep = (await _reports(db, 1))[0]
        write = _stage(rep, "write")
        assert write["status"] == "failed"
        assert write.get("reason") == "all_write_failed"

    @pytest.mark.asyncio
    async def test_no_new_insight_neutral_noop(self, db, monkeypatch):
        """M13: «нет новых выводов» — нейтральный no-op (validate skipped),
        терминальный unchanged — не alarm и не premature success."""
        await db.insert_graph_fact(CHAT_ID, "толян снова в баре",
                                   "chat_history", None, importance=6)
        memory = _FakeMemory([
            _old_anchor("толян пил каждую пятницу"),
            _old_anchor("толян бросил пить в 2024")])
        llm = _FakeWorkerLLM('{"paradigms":[]}')
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch, values={
            "flags.deep_sleep_enabled": True})
        out = await worker._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "unchanged"
        rep = (await _reports(db, 1))[0]
        validate = _stage(rep, "validate")
        assert validate["status"] == "skipped"
        assert validate.get("reason") == "no_new_insight"

    @pytest.mark.asyncio
    async def test_duplicates_write_stage_skipped_neutral(
            self, db, monkeypatch):
        await db.insert_graph_fact(CHAT_ID, "толян снова в баре",
                                   "chat_history", None, importance=6)
        memory = _FakeMemory([
            _old_anchor("толян пил каждую пятницу"),
            _old_anchor("толян бросил пить в 2024")])
        llm = _FakeWorkerLLM(_BRIDGE_OK, _BRIDGE_OK)
        worker = _worker(db, memory, llm, monkeypatch=monkeypatch, values={
            "flags.deep_sleep_enabled": True})
        first = await worker._run_deep_once(CHAT_ID, manual=True)
        assert first["status"] == "ok"
        second = await worker._run_deep_once(CHAT_ID, manual=True)
        assert second["status"] == "duplicate"
        # отчёт дубль-прогона: written == 0 (created_at может совпасть
        # с первым прогоном — выбираем по содержимому)
        reps = await _reports(db, 5)
        rep = next(r for r in reps if int(r.get("written") or 0) == 0)
        write = _stage(rep, "write")
        assert write["status"] == "skipped"
        assert write.get("reason") == "all_duplicates"
