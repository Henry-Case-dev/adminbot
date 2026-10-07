"""asap5-final-fixes (ADR-1028-25, D14/T-5264, §13A) — Парадигмы: gate ≠
last-attempt + retry-классы A/B/C.

Покрытие (13A.4, Q11):

* gate ≠ last-attempt: активный cooldown НЕ подменяет результат последней
  попытки — `scheduler_gate` и `last_attempt_result` независимы
  (RCA P1: 16×no_anchors за «cooldown»);
* retry-классы: контент-пустые → A (content_empty), техошибки → B
  (tech_error), bootstrap (парадигм 0) → C;
* класс C: автопопытка раз в 2 ч вместо полного 20-часового интервала,
  кап 6/сутки по ВСЕМ попыткам (вкл. дешёвые no_anchors-скипы);
* парадигмы уже есть → класс C не активируется (обычный интервал);
* `count_deep_attempts_all` — полный счётчик попыток (стоимостной
  `count_deep_attempts` остаётся бит-в-бит).
"""
import asyncio
import time

import pytest

from services import mca_gates
from services.database import DatabaseService

CHAT_ID = -100
NOW = int(time.time())


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


async def _log_attempt(db, *, kind: str, status: str, age_s: int,
                       chat_id: int = CHAT_ID) -> None:
    await db.db.execute(
        "INSERT INTO memory_dream_log (chat_id, run_at, kind, tokens, "
        "status) VALUES (?, ?, ?, 0, ?)",
        (chat_id, int(time.time()) - int(age_s), kind, status))
    await db.db.commit()


# ── retry-классы ────────────────────────────────────────────────────────────

def test_retry_class_mapping():
    """D14/Q11: A — контент-пустые; B — техошибки (error); ok → None."""
    assert mca_gates.deep_retry_class("no_anchors") == \
        mca_gates.DEEP_RETRY_CONTENT_EMPTY
    assert mca_gates.deep_retry_class("no_context") == \
        mca_gates.DEEP_RETRY_CONTENT_EMPTY
    assert mca_gates.deep_retry_class("insufficient_evidence") == \
        mca_gates.DEEP_RETRY_CONTENT_EMPTY
    assert mca_gates.deep_retry_class("unchanged") == \
        mca_gates.DEEP_RETRY_CONTENT_EMPTY
    assert mca_gates.deep_retry_class("duplicate") == \
        mca_gates.DEEP_RETRY_CONTENT_EMPTY
    assert mca_gates.deep_retry_class("error") == \
        mca_gates.DEEP_RETRY_TECH_ERROR
    assert mca_gates.deep_retry_class("ok") is None
    assert mca_gates.deep_retry_class("written") is None
    assert mca_gates.deep_retry_class("") is None


@pytest.mark.asyncio
async def test_count_deep_attempts_all_counts_cheap_skips(db):
    """Кап класса C считает ВСЕ попытки: no_anchors-скип тоже (иначе кап
    6/сутки был бы фикцией). Стоимостной счётчик — паритет (0 для skip)."""
    await _log_attempt(db, kind="deep_skip", status="no_anchors", age_s=3600)
    await _log_attempt(db, kind="deep_skip", status="no_anchors", age_s=1800)
    day_start = int(time.time()) - 86400
    assert await db.count_deep_attempts_all(day_start, chat_id=CHAT_ID) == 2
    assert await db.count_deep_attempts(day_start, chat_id=CHAT_ID) == 0


# ── класс C: bootstrap-интервал и кап ───────────────────────────────────────

@pytest.mark.asyncio
async def test_bootstrap_cooldown_bypass_then_cap(db):
    """Класс C: парадигм 0, последняя попытка 3 ч назад → cooldown НЕ
    блокирует (2-часовой интервал); 6 попыток за сутки → блокирует."""
    # 3 ч назад (больше 2 ч, меньше 20 ч) + пул парадигм пуст.
    await _log_attempt(db, kind="deep_skip", status="no_anchors", age_s=3 * 3600)
    gate = await mca_gates._cooldown_gate(db, CHAT_ID, NOW)
    assert gate is None            # bootstrap: интервал 2 ч, не 20 ч

    # 1 ч назад → ещё рано даже для bootstrap.
    await db.db.execute("DELETE FROM memory_dream_log")
    await _log_attempt(db, kind="deep_skip", status="no_anchors", age_s=3600)
    gate = await mca_gates._cooldown_gate(db, CHAT_ID, NOW)
    assert gate is not None and gate.reason == "cooldown"

    # Кап: 6 попыток за сутки (3 ч назад каждая) → блокировка, не busy-loop.
    await db.db.execute("DELETE FROM memory_dream_log")
    for i in range(6):
        await _log_attempt(db, kind="deep_skip", status="no_anchors",
                           age_s=3 * 3600)
    gate = await mca_gates._cooldown_gate(db, CHAT_ID, NOW)
    assert gate is not None and gate.reason == "cooldown"
    assert "last_attempt" in (gate.detail or "")


@pytest.mark.asyncio
async def test_bootstrap_bypass_requires_empty_paradigm_pool(db):
    """Парадигмы уже есть → класс C НЕ активен: обычный интервал держит."""
    await _log_attempt(db, kind="deep_skip", status="no_anchors", age_s=3 * 3600)
    # парадигма = graph_facts kind='belief' + belief_meta.type='paradigm'.
    await db.db.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, kind, status, "
        "belief_meta, created_at) VALUES (?, 'тест-парадигма', "
        "'derived_belief', 'belief', 'confirmed', "
        "'{\"type\":\"paradigm\"}', ?)", (CHAT_ID, int(time.time())))
    await db.db.commit()
    assert await db.count_paradigms(CHAT_ID) == 1
    gate = await mca_gates._cooldown_gate(db, CHAT_ID, NOW)
    assert gate is not None and gate.reason == "cooldown"


@pytest.mark.asyncio
async def test_class_b_error_backoff_not_relaxed_by_bootstrap(db):
    """Класс B (техошибка): Gate 7a backoff проверяется ДО bootstrap-ветки —
    свежая ошибка держит паузу даже при пустом пуле парадигм (LLM-защита
    не ослабляется)."""
    await db.db.execute(
        "INSERT INTO memory_dream_log (chat_id, run_at, kind, tokens, "
        "status) VALUES (?, ?, 'deep_skip', 10, 'error')",
        (CHAT_ID, int(time.time()) - 60))
    await db.db.commit()
    gate = await mca_gates._cooldown_gate(db, CHAT_ID, NOW)
    assert gate is not None and gate.reason == "cooldown"
    assert "backoff" in (gate.detail or "")


# ── API: gate ≠ last-attempt ────────────────────────────────────────────────

class _FakeGateDb:
    def __init__(self, *, paradigms=(), log_rows=()):
        self._paradigms = list(paradigms)
        self._log_rows = list(log_rows)

    async def list_recent_beliefs(self, **kwargs):
        return list(self._paradigms)

    async def count_paradigms(self, chat_id=None):
        return len(self._paradigms)

    async def last_deep_run(self, chat_id=None):
        return None

    async def count_dream_log(self, since, kind=None, chat_id=None):
        return 0

    async def recent_dream_log(self, limit=50, chat_id=None):
        return list(self._log_rows)

    async def count_deep_attempts_all(self, since_ts, chat_id=None):
        return 0

    async def last_deep_attempt(self, chat_id=None):
        return None


def _dream_row(kind, status, run_at, row_id=1):
    return {"id": row_id, "chat_id": CHAT_ID, "kind": kind,
            "status": status, "run_at": run_at, "tokens": 0}


@pytest.mark.asyncio
async def test_api_gate_does_not_mask_last_attempt(monkeypatch):
    """D14 (главный тест): cooldown-гейт активен, последняя попытка —
    no_anchors → paradigms_reason = no_anchors (НЕ cooldown),
    scheduler_gate = cooldown, last_attempt_result = no_anchors."""
    from web.api import memory_agi as ma
    now = int(time.time())
    gate_state = mca_gates.DreamGateState(
        gate="cooldown", blocked=True, reason="cooldown", global_value=True,
        chat_override=None, effective=False, source="runtime",
        detail="memory.deep_sleep_min_interval_hours=20")
    db = _FakeGateDb(
        log_rows=[_dream_row("deep_skip", "no_anchors", now - 3600)])
    monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
    monkeypatch.setattr(ma, "_db_or_503", lambda: db)
    monkeypatch.setattr(mca_gates, "dream_gate_resolver_enabled", lambda: True)

    class _W:
        memory = object()

    monkeypatch.setattr(ma.lore_runtime, "get_dream_worker", lambda: _W())
    async def _fake_gate(*a, **k):
        return gate_state

    monkeypatch.setattr(mca_gates, "resolve_dream_gate", _fake_gate)

    resp = await ma.deep_sleep_status(None, None, chat_id=CHAT_ID)
    assert resp["paradigms_reason"] == "no_anchors"   # НЕ «cooldown»
    assert resp["scheduler_gate"] == "cooldown"
    assert resp["last_attempt_result"] == "no_anchors"
    assert resp["last_attempt_retry_class"] == "content_empty"
    assert resp["last_attempt_at"] == now - 3600
    # следующая автопопытка: пул парадигм пуст → bootstrap-интервал 2 ч.
    assert resp["next_auto_attempt_at"] == now - 3600 + 2 * 3600


@pytest.mark.asyncio
async def test_api_structural_reason_keeps_gate_priority(monkeypatch):
    """Структурные причины (master/deep off) — прежний честный empty-state:
    paradigms_reason = gate-причина, scheduler_gate = None."""
    from web.api import memory_agi as ma
    gate_state = mca_gates.DreamGateState(
        gate="deep_sleep", blocked=True, reason="deep_sleep_off",
        global_value=False, chat_override=None, effective=False,
        source="global", detail="flags.deep_sleep_enabled=False")
    db = _FakeGateDb()
    monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
    monkeypatch.setattr(ma, "_db_or_503", lambda: db)
    monkeypatch.setattr(mca_gates, "dream_gate_resolver_enabled", lambda: True)

    class _W:
        memory = object()

    monkeypatch.setattr(ma.lore_runtime, "get_dream_worker", lambda: _W())
    async def _fake_gate(*a, **k):
        return gate_state

    monkeypatch.setattr(mca_gates, "resolve_dream_gate", _fake_gate)
    resp = await ma.deep_sleep_status(None, None, chat_id=CHAT_ID)
    assert resp["paradigms_reason"] == "deep_sleep_off"
    assert resp["scheduler_gate"] is None
    assert resp["last_attempt_result"] is None
