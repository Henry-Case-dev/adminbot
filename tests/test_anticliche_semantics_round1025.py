"""F0.3 (раунд 10.25, ADR-1025-3) — анти-клише: capacity vs per-run,
пакетное пополнение, дедуп против БД, честные статусы, события.

Тесты падают на старом коде: там `_call_llm` просил `max_patterns()` (200)
и не было ни добора, ни дедупа против БД, ни событий.
"""
import json
import logging

import pytest

from config.settings import Settings
from services import anticliche_cache as ac
from services import anticliche_worker as aw

pytestmark = pytest.mark.system2


# ── фейковый PG (структура как в test_anticliche_round1023) ─────────────────

class _Store:
    def __init__(self):
        self.row = None


class _FakeConn:
    def __init__(self, store):
        self.store = store

    async def fetchrow(self, sql, *args):
        flat = " ".join(sql.split())
        if flat.startswith("SELECT patterns"):
            return dict(self.store.row) if self.store.row else None
        if flat.startswith("INSERT INTO anticliche_cache"):
            patterns, source, source_url, status, fetched_at = args
            prev = self.store.row or {}
            version = int(prev.get("version") or 0) + 1
            self.store.row = {
                "patterns": patterns, "source": source,
                "source_url": source_url, "version": version,
                "fetched_at": fetched_at if fetched_at is not None
                else prev.get("fetched_at"),
                "updated_at": "2026-09-19T00:00:00+00:00",
                "last_status": status,
            }
            return {"version": version}
        if "INSERT INTO worker_budget" in flat:
            return {"used": 1}
        return None

    async def execute(self, sql, *args):
        flat = " ".join(sql.split())
        if flat.startswith("UPDATE anticliche_cache"):
            if self.store.row is None:
                self.store.row = {"patterns": [], "source": "",
                                  "source_url": "", "version": 0,
                                  "last_status": "never"}
            self.store.row["last_status"] = args[0]
        return "UPDATE 1"


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        outer = self

        class _CM:
            async def __aenter__(self):
                return outer._conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, store=None):
        self.store = store or _Store()
        self.pool = _FakePool(_FakeConn(self.store))


class _FakeLlm:
    def __init__(self, *, batches=None, error=None, model="test-model"):
        self._batches = list(batches or [])
        self._error = error
        self.model = model
        self.calls = 0
        self.messages = []

    async def generate_worker(self, _kind, messages):
        self.calls += 1
        self.messages.append(messages)
        if self._error is not None:
            raise self._error
        if self._batches:
            batch = self._batches.pop(0)
        else:
            batch = []
        return json.dumps({"patterns": batch})


@pytest.fixture(autouse=True)
def _reset_state():
    ac.invalidate()
    ac.set_runtime_pg(None)
    yield
    ac.invalidate()
    ac.set_runtime_pg(None)


def _worker(store, llm, fetch=None):
    return aw.AntiClicheWorker(llm=llm, pg=_FakePg(store),
                               fetch=fetch or (lambda *a, **k: _text()))


async def _text():
    return "текст"


def _row(phrases, *, version=1):
    return {"patterns": [{"code": "dyn_x", "phrase": p, "origin": "w"}
                         for p in phrases],
            "source": "wikipedia", "source_url": "u", "version": version,
            "fetched_at": "2026-01-01T00:00:00+00:00", "last_status": "ok"}


# ── per-run vs capacity ─────────────────────────────────────────────────────

def test_per_run_default_and_clamp(monkeypatch):
    monkeypatch.setattr(Settings, "ANTICLICHE_MAX_PATTERNS_PER_RUN", 7)
    assert aw.max_patterns_per_run() == 7
    # партия не больше вместимости
    monkeypatch.setattr(Settings, "ANTICLICHE_MAX_PATTERNS_PER_RUN", 9999)
    assert aw.max_patterns_per_run() == ac.max_patterns()
    # мусор/0 → минимум 1
    monkeypatch.setattr(Settings, "ANTICLICHE_MAX_PATTERNS_PER_RUN", 0)
    assert aw.max_patterns_per_run() == 1


@pytest.mark.asyncio
async def test_call_llm_asks_per_run_not_capacity(monkeypatch):
    monkeypatch.setattr(Settings, "ANTICLICHE_MAX_PATTERNS_PER_RUN", 7)
    llm = _FakeLlm(batches=[[]])
    worker = aw.AntiClicheWorker(llm=llm, pg=_FakePg(), fetch=None)
    await worker._call_llm("источник")
    system = llm.messages[0][0]["content"]
    assert "до 7" in system
    assert "до 200" not in system          # старая conflation — убрана


# ── пакетное пополнение до вместимости ──────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_replenish_fills_capacity(monkeypatch):
    monkeypatch.setattr(aw.worker_budget, "consume", _always_true)
    monkeypatch.setattr(ac, "max_patterns", lambda: 12)
    monkeypatch.setattr(Settings, "ANTICLICHE_MAX_PATTERNS_PER_RUN", 5)
    monkeypatch.setattr(Settings, "ANTICLICHE_MAX_ROUNDS", 3)
    batches = [
        [{"phrase": f"фраза один {i}"} for i in range(5)],
        [{"phrase": f"фраза два {i}"} for i in range(5)],
        [{"phrase": f"фраза три {i}"} for i in range(5)],
    ]
    store = _Store()
    worker = _worker(store, _FakeLlm(batches=batches))
    result = await worker.refresh(force=True)
    assert result["status"] == "ok"
    assert result["final_count"] >= 12       # добор до вместимости (3 раунда)
    assert store.row["patterns"]
    assert result["count"] == result["final_count"]


@pytest.mark.asyncio
async def test_dedup_against_stored_db(monkeypatch, caplog):
    monkeypatch.setattr(aw.worker_budget, "consume", _always_true)
    monkeypatch.setattr(ac, "max_patterns", lambda: 50)
    monkeypatch.setattr(Settings, "ANTICLICHE_MAX_PATTERNS_PER_RUN", 10)
    store = _Store()
    store.row = _row(["старая фраза один", "старая фраза два"])
    llm = _FakeLlm(batches=[[
        {"phrase": "старая фраза один"},      # дубль против БД
        {"phrase": "новая живая фраза"},      # новая
    ]])
    worker = _worker(store, llm)
    with caplog.at_level(logging.INFO):
        result = await worker.refresh(force=True)
    assert result["status"] == "ok"
    assert result["count"] == 1               # сохранена только новая
    phrases = [p["phrase"] for p in store.row["patterns"]]
    assert "новая живая фраза" in phrases
    assert phrases.count("старая фраза один") == 1
    assert any("event=ANTI_CLICHE_DEDUP_COMPLETE" in r.getMessage()
               for r in caplog.records)


@pytest.mark.asyncio
async def test_zero_new_keeps_cache_success(monkeypatch):
    monkeypatch.setattr(aw.worker_budget, "consume", _always_true)
    store = _Store()
    store.row = _row(["живая фраза один"], version=5)
    llm = _FakeLlm(batches=[[{"phrase": "живая фраза один"}]])
    worker = _worker(store, llm)
    result = await worker.refresh(force=True)
    assert result["status"] == "empty"        # «нет новых» = успех, не ошибка
    assert store.row["version"] == 5          # кэш не перезаписан


# ── честные статусы ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provider_error_is_llm_error(monkeypatch):
    monkeypatch.setattr(aw.worker_budget, "consume", _always_true)
    store = _Store()
    store.row = _row(["старая"], version=2)
    worker = _worker(store, _FakeLlm(error=RuntimeError("provider down")))
    result = await worker.refresh(force=True)
    assert result["status"] == "llm_error"
    assert store.row["last_status"] == "llm_error"


# ── события (§4.4) ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_events_emitted_with_fields(monkeypatch, caplog):
    monkeypatch.setattr(aw.worker_budget, "consume", _always_true)
    monkeypatch.setattr(Settings, "ANTICLICHE_MAX_PATTERNS_PER_RUN", 5)
    store = _Store()
    worker = _worker(store, _FakeLlm(batches=[[
        {"phrase": "свежая фраза"}]]))
    with caplog.at_level(logging.INFO):
        await worker.refresh(force=True)
    text = "\n".join(r.getMessage() for r in caplog.records)
    for name in ("ANTI_CLICHE_UPDATE_START", "ANTI_CLICHE_MODEL_REQUEST",
                 "ANTI_CLICHE_MODEL_RESPONSE", "ANTI_CLICHE_DEDUP_COMPLETE",
                 "ANTI_CLICHE_SAVE_COMPLETE", "ANTI_CLICHE_UPDATE_COMPLETE"):
        assert f"event={name}" in text, name
    assert "capacity=" in text and "per_run=" in text
    assert "model=test-model" in text
    # R17: сами фразы в лог НЕ попадают
    assert "свежая фраза" not in text


async def _always_true(*args, **kwargs):
    return True
