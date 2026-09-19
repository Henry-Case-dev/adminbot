"""Раунд 10.24 (F7, ADR-1024-3) — лимит клише (default 200) + фикс крона.

Покрытие: дефолт/резолв/clamp/hard-ceiling лимита; парсер возвращает >20;
крон планирует первый прогон вскоре после старта; freshness-skip по
`fetched_at`; force игнорирует skip; ошибка источника не роняет `tick`.
"""
from __future__ import annotations

import datetime
import json
import types

import pytest
from unittest.mock import AsyncMock

from config.settings import Settings
from services import anticliche_cache as ac
from services import anticliche_worker as aw
from services import hot_config as hot
from services.anticliche_worker import AntiClicheWorker, build_patterns

pytestmark = pytest.mark.system2


# ── фейковый PG (минимальный набор для SELECT/UPSERT/status) ────────────────

class _Store:
    def __init__(self):
        self.row = None


class _FakeConn:
    def __init__(self, store: _Store):
        self.store = store

    async def fetchrow(self, sql, *args):
        flat = " ".join(sql.split())
        if flat.startswith("SELECT patterns"):
            return dict(self.store.row) if self.store.row else None
        if flat.startswith("INSERT INTO anticliche_cache"):
            patterns, source, source_url, status, fetched_at = args
            prev = self.store.row or {}
            version = int(prev.get("version") or 0) + 1
            previous_fetched = prev.get("fetched_at")
            self.store.row = {
                "patterns": patterns, "source": source,
                "source_url": source_url, "version": version,
                "fetched_at": fetched_at if fetched_at is not None
                else previous_fetched,
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
    def __init__(self, store: _Store | None = None):
        self.store = store or _Store()
        self.pool = _FakePool(_FakeConn(self.store))


class _HotCache:
    """Минимальный ConfigCache-подобный объект для hot_config.get."""

    def __init__(self, values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.fixture(autouse=True)
def _reset_state():
    ac.invalidate()
    ac.set_runtime_pg(None)
    aw.set_runtime_worker(None)
    hot.set_config_cache(None)
    yield
    ac.invalidate()
    ac.set_runtime_pg(None)
    aw.set_runtime_worker(None)
    hot.set_config_cache(None)


def _worker(store, *, fetch=None, llm=None, scheduler=None):
    return AntiClicheWorker(llm=llm, pg=_FakePg(store), fetch=fetch,
                            scheduler=scheduler)


# ── резолв лимита ───────────────────────────────────────────────────────────

class TestMaxPatternsResolution:
    def test_default_is_200(self):
        assert ac.ANTICLICHE_MAX_PATTERNS_DEFAULT == 200
        assert ac.ANTICLICHE_MAX_PATTERNS == 200       # deprecated alias
        assert ac.max_patterns() == 200

    def test_hot_key_overrides_settings(self):
        hot.set_config_cache(_HotCache(
            {"limits.anticliche_max_patterns": 321}))
        assert ac.max_patterns() == 321

    def test_settings_value_used_without_hot(self, monkeypatch):
        monkeypatch.setattr(ac, "settings", types.SimpleNamespace(
            ANTICLICHE_MAX_PATTERNS=250))
        assert ac.max_patterns() == 250

    @pytest.mark.parametrize("value,expected", [(0, 1), (-5, 1), (1, 1)])
    def test_low_clamp(self, monkeypatch, value, expected):
        monkeypatch.setattr(ac, "settings", types.SimpleNamespace(
            ANTICLICHE_MAX_PATTERNS=value))
        assert ac.max_patterns() == expected

    def test_hard_ceiling_applied(self, monkeypatch):
        monkeypatch.setattr(ac, "settings", types.SimpleNamespace(
            ANTICLICHE_MAX_PATTERNS=5000))
        assert ac.max_patterns() == ac.ANTICLICHE_MAX_PATTERNS_HARD_CEILING

    def test_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setattr(ac, "settings", types.SimpleNamespace(
            ANTICLICHE_MAX_PATTERNS="мусор"))
        assert ac.max_patterns() == ac.ANTICLICHE_MAX_PATTERNS_DEFAULT


# ── парсер: лимит 20 снят ───────────────────────────────────────────────────

class TestParserLimit:
    def test_more_than_20_returned(self):
        entries = [{"phrase": f"уникальное клише {i}"} for i in range(50)]
        assert len(build_patterns(entries)) == 50

    def test_explicit_limit_caps(self):
        entries = [{"phrase": f"уникальное клише {i}"} for i in range(50)]
        assert len(build_patterns(entries, max_patterns=10)) == 10

    def test_hot_limit_applies_to_parser(self):
        hot.set_config_cache(_HotCache(
            {"limits.anticliche_max_patterns": 7}))
        entries = [{"phrase": f"уникальное клише {i}"} for i in range(50)]
        assert len(build_patterns(entries)) == 7

    def test_rules_use_resolved_limit(self):
        hot.set_config_cache(_HotCache(
            {"limits.anticliche_max_patterns": 3}))
        patterns = [{"phrase": f"клише номер {i}"} for i in range(10)]
        assert len(ac.set_rules(patterns)) == 3


# ── крон: первый прогон вскоре после старта ─────────────────────────────────

class TestCronSchedule:
    def _start(self, **kwargs):
        captured = {}

        class _Sched:
            running = False

            def add_job(self, func, trigger=None, **kw):
                captured["func"] = func
                captured["trigger"] = trigger
                captured.update(kw)

            def start(self):
                self.running = True

        worker = AntiClicheWorker(llm=AsyncMock(), pg=None,
                                  scheduler=_Sched(), **kwargs)
        worker.start()
        return captured

    def test_first_run_scheduled_soon(self):
        captured = self._start()
        assert captured["id"] == aw._JOB_ID
        assert captured["max_instances"] == 1
        assert captured["coalesce"] is True
        assert captured["misfire_grace_time"] == 3600
        nrt = captured["next_run_time"]
        assert nrt is not None
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = (nrt - now).total_seconds()
        # ≈ ANTICLICHE_FIRST_RUN_DELAY_MINUTES (5 мин), а не 7 дней.
        assert 0 < delta <= 6 * 60
        # Далее — недельный интервал (REFRESH_DAYS=7) сохраняется.
        trigger = captured["trigger"]
        assert getattr(trigger, "interval", None) == datetime.timedelta(days=7)

    def test_first_run_delay_env_configurable(self, monkeypatch):
        monkeypatch.setattr(Settings, "ANTICLICHE_FIRST_RUN_DELAY_MINUTES", 2)
        assert aw._first_run_delay_minutes() == 2
        captured = self._start()
        now = datetime.datetime.now(datetime.timezone.utc)
        assert 0 < (captured["next_run_time"] - now).total_seconds() <= 3 * 60


# ── freshness-skip ──────────────────────────────────────────────────────────

class TestFreshness:
    def _fresh_store(self):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        store = _Store()
        store.row = {
            "patterns": [{"code": "dyn_x", "phrase": "старая фраза"}],
            "source": "wikipedia", "source_url": "u", "version": 4,
            "fetched_at": now, "last_status": "ok",
        }
        return store

    def test_recent_datetime_is_fresh(self):
        recent = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=1))
        assert aw._is_fresh(recent) is True

    def test_old_or_bad_is_not_fresh(self):
        assert aw._is_fresh(None) is False
        assert aw._is_fresh("не дата") is False
        old = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(days=10))
        assert aw._is_fresh(old) is False

    @pytest.mark.asyncio
    async def test_refresh_skips_when_fresh(self, monkeypatch):
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = self._fresh_store()
        fetch = AsyncMock(return_value="text")
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(return_value="{}")
        worker = _worker(store, fetch=fetch, llm=llm)
        result = await worker.refresh()
        assert result["status"] == "fresh"
        assert fetch.await_count == 0
        assert llm.generate_worker.await_count == 0
        assert store.row["version"] == 4

    @pytest.mark.asyncio
    async def test_force_ignores_freshness(self, monkeypatch):
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = self._fresh_store()
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(return_value=json.dumps(
            {"patterns": [{"phrase": "новая уникальная фраза"}]}))
        worker = _worker(store, fetch=AsyncMock(return_value="text"), llm=llm)
        result = await worker.refresh(force=True)
        assert result["status"] == "ok"
        assert store.row["version"] == 5

    @pytest.mark.asyncio
    async def test_tick_skips_fresh_without_llm(self, monkeypatch):
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = self._fresh_store()
        llm = AsyncMock()
        llm.generate_worker = AsyncMock(return_value="{}")
        worker = _worker(store, fetch=AsyncMock(return_value="text"), llm=llm)
        await worker.tick()
        assert llm.generate_worker.await_count == 0


# ── устойчивость тика ───────────────────────────────────────────────────────

class TestTickResilience:
    @pytest.mark.asyncio
    async def test_source_error_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(aw.worker_budget, "consume",
                            AsyncMock(return_value=True))
        store = _Store()
        store.row = {"patterns": [], "source": "wikipedia", "source_url": "u",
                     "version": 1, "last_status": "ok"}
        worker = _worker(store, fetch=AsyncMock(side_effect=RuntimeError("x")),
                         llm=AsyncMock())
        await worker.tick()          # не бросает
        assert store.row["last_status"] == "fetch_error"
