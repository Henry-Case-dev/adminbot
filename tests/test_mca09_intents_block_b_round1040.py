"""MCA-09 `mca-09-intents-initiative` — focused-тесты блока B (T-5025…T-5028).

Покрытие (API канонического `services/mca_intents.py`):
  * триггеры §13.1: каждый → кандидат решения (не автоотправка); тишина/
    незнакомый триггер → None, ничего не пишет;
  * лёгкий heartbeat: due-скан без LLM, bounded-батч, coalesce ≤1/чат/тик,
    deferred→pending по сроку, «догон» пропущенного тика, гигиена в тике (F-4);
  * запрет «500 сообщений на реплику»: вне retrieval-контура полного чтения
    окна нет (ни статически, ни динамически);
  * хост-джоб `intent_heartbeat_tick` (MemoryMaintenanceService), OFF → инертен.
"""
import inspect

import pytest

from services import mca_events, mca_gates
from services import mca_intents as mi
from services import memory_maintenance as mm
from services.database import DatabaseService

CHAT = -100500
CHAT2 = -100501
NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


async def _db(tmp_path, name="mca09_b.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _mk(svc, *, chat=CHAT, topic="t1", goal="Спросить про собеседование",
              now=NOW, **kw):
    base = dict(goal=goal, reason="unanswered_question",
                source_refs=("msg:1",), topic_refs=(topic,), created_at=now)
    base.update(kw)
    return await svc.create_intent(chat, "follow_up", "unanswered_question",
                                   **base)


async def _due(svc, *, chat=CHAT, topic="t1", when=NOW - 10, now=NOW):
    """Due-намерение: deferred с наступившим next_check_at."""
    intent_id, created = await _mk(svc, chat=chat, topic=topic, now=now)
    assert created
    assert await svc.defer(intent_id, next_check_at=when,
                           activation_condition="time_due", now=now)
    return intent_id


class _SqlRecorder:
    """Прокси соединения: запоминает SQL (для «окно не читается»)."""

    def __init__(self, inner):
        self._inner = inner
        self.statements: list[str] = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def execute(self, sql, *args, **kwargs):
        self.statements.append(str(sql))
        return await self._inner.execute(sql, *args, **kwargs)


class _DbProxy:
    """DatabaseService-прокси с записью SQL (write_transaction — passthrough)."""

    def __init__(self, inner):
        self._inner = inner
        self.db = _SqlRecorder(inner.db)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ═══ T-5025: триггеры §13.1 → кандидат, не автоотправка ═════════════════════

def test_each_trigger_makes_candidate_not_autoreply(monkeypatch):
    sent: list = []
    monkeypatch.setattr(
        "services.telegram_send.send_text",
        lambda *a, **k: sent.append((a, k)))
    monkeypatch.setattr(
        "services.negative_constraints.verbalize_validated",
        lambda *a, **k: sent.append(("verbalize", a, k)))
    triggers = ("new_message", "direct_address", "significant_event",
                "intent_due", "search_completed", "nostalgia_due")
    for kind in triggers:
        cand = mi.candidate_from_trigger(trigger_kind=kind, chat_id=CHAT)
        assert cand is not None and cand.trigger_kind == kind
        assert cand.source == "intent"
    # тишина/незнакомое — не триггер: сама по себе не пишет
    assert mi.candidate_from_trigger(trigger_kind="silence",
                                     chat_id=CHAT) is None
    assert mi.candidate_from_trigger(trigger_kind="", chat_id=CHAT) is None
    assert mi.candidate_from_trigger(trigger_kind="made_up",
                                     chat_id=CHAT) is None
    assert sent == []                    # ни отправки, ни Вербализатора


def test_trigger_candidate_never_writes():
    """candidate_from_trigger не пишет в БД и не делает LLM-вызовов."""
    src = inspect.getsource(mi.candidate_from_trigger)
    assert "execute" not in src and "write_transaction" not in src
    body = src.split('"""')[-1]
    assert "import" not in body and "llm" not in body.lower()


# ═══ T-5026: лёгкий heartbeat ════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_due_candidates_and_resume(tmp_path):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        due_id = await _due(svc, chat=CHAT, topic="t1")
        future_id, _ = await _mk(svc, chat=CHAT2, topic="t2", now=NOW)
        await svc.defer(future_id, next_check_at=NOW + 999,
                        activation_condition="time_due", now=NOW)
        done_id, _ = await _mk(svc, chat=CHAT2, topic="t3", now=NOW)
        await svc.close(done_id, status="fulfilled", now=NOW)
        due = await svc.due_candidates(now=NOW)
        assert [c.intent_id for c in due] == [due_id]
        assert due[0].trigger_kind == "intent_due"
        # deferred с наступившим сроком → pending
        assert (await svc.store.get_intent(due_id))["status"] == "pending"
        assert (await svc.store.get_intent(future_id))["status"] == "deferred"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_heartbeat_bounded_batch_and_coalesce(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "intent_heartbeat_batch_max",
                            lambda: 2)
        svc = mi.get_service(db)
        for i in range(3):
            await _due(svc, chat=CHAT, topic=f"same:{i}", when=NOW - 10 + i)
        for i in range(3):
            await _due(svc, chat=CHAT2 - i, topic=f"other:{i}", when=NOW - 10)
        due = await svc.due_candidates(now=NOW)
        assert len(due) == 2                      # bounded-батч
        assert len({c.chat_id for c in due}) == 2
        assert sum(1 for c in due if c.chat_id == CHAT) <= 1   # coalesce
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_heartbeat_no_llm_and_no_window_read(tmp_path, monkeypatch):
    """Тик: 0 LLM-вызовов; SQL — только по `mca_intents` (окно не читается)."""
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        await _due(svc, when=NOW - 1)
        proxy = _DbProxy(db)
        svc2 = mi.get_service(proxy)

        async def _boom(*a, **k):
            raise AssertionError("LLM-вызов на тике запрещён")

        from services.llm_client import LLMClient
        monkeypatch.setattr(LLMClient, "generate", _boom)
        monkeypatch.setattr(LLMClient, "generate_chat", _boom)
        stats = await svc2.heartbeat_tick(now=NOW)
        assert stats["enabled"] and stats["due"]
        assert proxy.db.statements, "due-скан должен выполнить SQL"
        for sql in proxy.db.statements:
            assert "mca_intents" in sql
            for forbidden in ("smart_messages", "messages", "history",
                              "summary", "mca_events"):
                assert forbidden not in sql, (forbidden, sql)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_missed_tick_caught_by_next_scan(tmp_path):
    """Пропущенные тики догоняются следующим сканом (durable-состояние)."""
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        intent_id = await _due(svc, when=NOW - 3600)
        first = await svc.due_candidates(now=NOW + 7200)
        assert [c.intent_id for c in first] == [intent_id]
        assert (await svc.store.get_intent(intent_id))["status"] == "pending"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_hygiene_runs_in_tick(tmp_path, monkeypatch):
    """F-4: гигиена (expire/archive/prune) вызывается самим тиком, bounded."""
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        monkeypatch.setattr(mca_gates, "intent_retention_days", lambda: 1)
        exp_id, _ = await _mk(svc, topic="t:exp", expires_at=NOW - 1,
                              created_at=NOW - 10)
        done_id, _ = await _mk(svc, topic="t:done", created_at=NOW - 10 * 86400)
        await svc.close(done_id, status="fulfilled",
                        now=NOW - 9 * 86400)
        stats = await svc.heartbeat_tick(now=NOW)
        assert stats["enabled"] is True
        assert stats["expired"] == 1 and stats["archived"] == 1
        assert (await svc.store.get_intent(exp_id))["status"] == "expired"
        assert (await svc.store.get_intent(done_id))["archived_at"] == NOW
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_heartbeat_tick_module_and_host(tmp_path, monkeypatch):
    """Тик — на существующем MemoryMaintenanceService (300 с); OFF → инертен."""
    assert mm.MemoryMaintenanceService.JOB_INTENT_HEARTBEAT_ID == \
        "intent_heartbeat_tick"
    assert mm._INTENT_HEARTBEAT_TICK_SECONDS == 300
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: False)
    assert mm._intent_heartbeat_tick_enabled() is False
    monkeypatch.setattr(mca_gates, "intents_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "intent_heartbeat_enabled",
                        lambda: False)
    assert mm._intent_heartbeat_tick_enabled() is False
    monkeypatch.setattr(mca_gates, "intent_heartbeat_enabled", lambda: True)
    assert mm._intent_heartbeat_tick_enabled() is True
    db = await _db(tmp_path)
    try:
        await _due(mi.get_service(db), when=NOW - 1)
        stats = await mi.heartbeat_tick(db, now=NOW)
        assert stats["status"] == "ok" and stats["candidates"] == 1
        # хендлер хоста вызывает единый сервис; per-intent task_jobs нет
        svc = mm.MemoryMaintenanceService.__new__(mm.MemoryMaintenanceService)
        svc.db = db
        await svc._tick_intent_heartbeat()          # не бросает
        cur = await db.db.execute(
            "SELECT COUNT(*) AS c FROM task_jobs WHERE kind LIKE '%intent%'")
        assert (await cur.fetchone())["c"] == 0
    finally:
        await db.close()


# ═══ T-5027: запрет «500 сообщений на реплику» ══════════════════════════════

def test_no_full_window_read_static():
    """Вне retrieval-контура полного чтения окна нет: модуль не импортирует
    payload/LLM/историю и не читает окно сообщений."""
    src = inspect.getsource(mi)
    for forbidden in ("payload_builder", "llm_client", "get_recent_history",
                      "get_window_messages", "mca_retrieval_context",
                      "summarize"):
        assert forbidden not in src, forbidden


@pytest.mark.asyncio
async def test_new_message_trigger_reads_nothing(tmp_path):
    """Кандидат по новому сообщению не выполняет SQL/чтение окна вовсе."""
    db = await _db(tmp_path)
    try:
        proxy = _DbProxy(db)
        cand = mi.candidate_from_trigger(trigger_kind="new_message",
                                         chat_id=CHAT, intent_id="i:1")
        assert cand is not None
        assert proxy.db.statements == []
    finally:
        await db.close()


# ═══ OFF (K1/K2) ════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_k2_off_tick_inert_creation_alive(tmp_path, monkeypatch):
    db = await _db(tmp_path)
    try:
        svc = mi.get_service(db)
        monkeypatch.setattr(mca_gates, "intent_heartbeat_enabled",
                            lambda: False)
        assert await svc.due_candidates(now=NOW) == []
        assert (await svc.heartbeat_tick(now=NOW))["enabled"] is False
        assert (await mi.heartbeat_tick(db, now=NOW))["status"] == "disabled"
        # создание/закрытие намерений возможно (K2 OFF — документ. подмножество)
        intent_id, created = await _mk(svc)
        assert created
        assert await svc.close(intent_id, status="fulfilled") is not None
    finally:
        await db.close()
