"""Epic 85 (T-629, 84.11.2) — тесты services/status_service.py.

DoD 84.10 п.6: сводка bot/server/llm/uptime корректна; LLM-ключи — только
{configured, last4} (решение 5); health-check кэшируется 60с; uptime-бакеты
(5 мин, ≤288 точек). psutil/httpx/пул — моки.
"""
import datetime
import time
import types

import pytest

from services import hot_config as hot
from services.status_service import StatusService, _mask_key, status


class _FakeCache:
    def __init__(self, values=None, pg=None):
        self._settings = dict(values or {})
        self.pg = pg

    def get(self, key, default=None):
        return self._settings.get(key, default)


class _FakePool:
    def __init__(self, rows):
        self._rows = list(rows)

    def acquire(self):
        class _CM:
            def __init__(self, pool):
                self._pool = pool

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def fetch(self, sql, *args):
                return self._pool._rows

            async def execute(self, sql, *args):
                return "INSERT 0 1"

        return _CM(self)


class _FakePg:
    def __init__(self, rows=None):
        self.pool = _FakePool(rows or [])


@pytest.fixture(autouse=True)
def _reset_hot(monkeypatch):
    hot.set_config_cache(None)
    yield
    hot.set_config_cache(None)


def _row(ts: datetime.datetime, status_value: str = "up"):
    return {"ts": ts, "status": status_value}


class TestMaskKey:
    def test_configured_and_last4(self):
        assert _mask_key("gsk_abc123456789") == {
            "configured": True, "last4": "6789"}

    def test_empty(self):
        assert _mask_key("") == {"configured": False, "last4": None}
        assert _mask_key(None) == {"configured": False, "last4": None}


class TestBotServerMetrics:
    def test_bot_fields(self):
        svc = StatusService()
        svc.mark_started()
        svc.set_polling_state("polling")
        assert svc.state == "polling"
        assert svc.version
        assert svc.started_at

    def test_server_metrics_shape(self):
        metrics = StatusService._server_metrics()
        assert "cpu_percent" in metrics
        assert set(metrics["memory"]) == {"total", "used", "percent"}
        assert set(metrics["disk"]) == {"total", "used", "percent"}
        assert set(metrics["process"]) == {"pid", "rss_mb", "threads", "cpu"}
        # loadavg: на Windows — None (ключ присутствует всегда)
        assert "loadavg" in metrics


class TestUptimeBuckets:
    def test_empty_rows(self):
        assert StatusService._bucketize([]) == []

    def test_bucketize_5min(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        rows = [
            _row(now - datetime.timedelta(minutes=1)),
            _row(now - datetime.timedelta(minutes=2)),      # соседний (может, тот же бакет)
            _row(now - datetime.timedelta(minutes=7)),      # другой бакет
            _row(now - datetime.timedelta(hours=25)),       # старше окна → выброс
        ]
        buckets = StatusService._bucketize(rows)
        assert 2 <= len(buckets) <= 3
        # все бакеты внутри окна 24ч (старая строка выброшена)
        since = now - datetime.timedelta(seconds=86400)
        for bucket in buckets:
            ts = datetime.datetime.fromisoformat(bucket["ts"])
            assert ts >= since

    def test_bucket_count_within_288(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        rows = [_row(now - datetime.timedelta(minutes=m))
                for m in range(0, 1500)]                    # 25 часов
        assert len(StatusService._bucketize(rows)) <= 288

    def test_naive_ts_localized(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        naive = now.replace(tzinfo=None)
        buckets = StatusService._bucketize([_row(naive)])
        assert len(buckets) == 1


class TestSnapshot:
    async def _build(self, svc, cache, monkeypatch):
        monkeypatch.setattr(
            "services.status_service.StatusService._server_metrics",
            staticmethod(lambda: {"cpu_percent": 1.0}))
        return await svc.build_snapshot(cache)

    @pytest.mark.asyncio
    async def test_snapshot_structure(self, monkeypatch):
        hot.set_config_cache(_FakeCache({
            "keys.llm_api_key": "sk_deepseek_123456",
            "models.llm_model_name": "deepseek-v4-flash",
        }))
        svc = StatusService()
        svc.mark_started()
        svc.set_polling_state("polling")
        cache = _FakeCache(pg=_FakePg())
        snapshot = await self._build(svc, cache, monkeypatch)
        assert set(snapshot) == {"bot", "server", "llm", "uptime"}
        bot = snapshot["bot"]
        assert bot["state"] == "polling"
        assert bot["mode"] == "polling"
        assert bot["version"]
        assert bot["uptime_seconds"] >= 0
        assert bot["errors_total"] >= 0
        assert snapshot["uptime"]["buckets"] == []
        assert snapshot["uptime"]["last_heartbeat"] is None

    @pytest.mark.asyncio
    async def test_llm_cards_masked_keys(self, monkeypatch):
        hot.set_config_cache(_FakeCache({
            "keys.llm_api_key": "sk_deepseek_123456",
            "keys.groq_api_key": "gsk_groq_secret_abc",
            "keys.openrouter_api_key": "",
        }))
        svc = StatusService()
        cache = _FakeCache(pg=_FakePg())
        snapshot = await self._build(svc, cache, monkeypatch)
        cards = {c["provider"]: c for c in snapshot["llm"]}
        assert set(cards) >= {"deepseek", "groq", "openrouter"}
        assert cards["deepseek"]["model"]
        # маскировка: только configured/last4 — полное значение НИКОГДА
        assert cards["deepseek"]["key"] == {
            "configured": True, "last4": "3456"}
        assert cards["groq"]["key"] == {
            "configured": True, "last4": "_abc"}
        assert cards["openrouter"]["key"] == {
            "configured": False, "last4": None}
        for card in cards.values():
            assert "sk_deepseek" not in str(card)
            assert "gsk_groq_secret" not in str(card)

    @pytest.mark.asyncio
    async def test_health_not_configured(self, monkeypatch):
        hot.set_config_cache(_FakeCache(_NO_KEYS))
        svc = StatusService()
        cache = _FakeCache(pg=_FakePg())
        snapshot = await self._build(svc, cache, monkeypatch)
        cards = {c["provider"]: c for c in snapshot["llm"]}
        assert cards["deepseek"]["health"]["status"] == "not_configured"
        assert cards["deepseek"]["health"]["ok"] is False

    @pytest.mark.asyncio
    async def test_health_unreachable_when_ping_fails(self, monkeypatch):
        hot.set_config_cache(_FakeCache({"keys.llm_api_key": "sk-x"}))
        svc = StatusService()
        cache = _FakeCache(pg=_FakePg())
        snapshot = await self._build(svc, cache, monkeypatch)
        health = {c["provider"]: c for c in snapshot["llm"]}["deepseek"]["health"]
        assert health["status"] == "unreachable"   # реальной сети нет
        assert health["ok"] is False

    @pytest.mark.asyncio
    async def test_health_cache_60s(self, monkeypatch):
        """Результат health-check кэшируется: повторный вызов не пингует."""
        calls = {"n": 0}

        async def _fake_ping(base_url, key):
            calls["n"] += 1
            return {"ok": True, "status": "ok", "http_status": 200,
                    "latency_ms": 5.0, "checked_at": "t"}

        # ключи заданы для ТРЁХ провайдеров → ровно 3 пинга за первый вызов
        hot.set_config_cache(_FakeCache({
            "keys.llm_api_key": "sk-x",
            "keys.groq_api_key": "gsk-x",
            "keys.openrouter_api_key": "or-x",
        }))
        svc = StatusService()
        monkeypatch.setattr(svc, "_ping_models", staticmethod(_fake_ping))
        cache = _FakeCache(pg=_FakePg())
        monkeypatch.setattr(
            "services.status_service.StatusService._server_metrics",
            staticmethod(lambda: {}))
        await svc.build_snapshot(cache)
        await svc.build_snapshot(cache)
        assert calls["n"] == 3   # кэш 60с — второй вызов без пингов

    @pytest.mark.asyncio
    async def test_uptime_from_pg(self, monkeypatch):
        now = datetime.datetime.now(datetime.timezone.utc)
        pg = _FakePg([_row(now - datetime.timedelta(minutes=1))])
        hot.set_config_cache(_FakeCache(_NO_KEYS))
        svc = StatusService()
        monkeypatch.setattr(
            "services.status_service.StatusService._server_metrics",
            staticmethod(lambda: {}))
        snapshot = await svc.build_snapshot(_FakeCache(pg=pg))
        assert len(snapshot["uptime"]["buckets"]) == 1
        assert snapshot["uptime"]["last_heartbeat"]

    @pytest.mark.asyncio
    async def test_local_api_flag_in_bot(self, monkeypatch):
        """F11: bot.local_api — признак локального Bot API."""
        hot.set_config_cache(_FakeCache(_NO_KEYS))
        svc = StatusService()
        monkeypatch.setattr(
            "services.status_service.StatusService._server_metrics",
            staticmethod(lambda: {}))
        snapshot = await svc.build_snapshot(_FakeCache(pg=_FakePg()))
        assert "local_api" in snapshot["bot"]
        assert snapshot["bot"]["local_api"] is False   # DOWNLOAD_ENABLED=False в тестах

    @pytest.mark.asyncio
    async def test_health_checks_run_in_parallel(self, monkeypatch):
        """F19: health-check'и провайдеров идут asyncio.gather'ом —
        суммарное время ≈ одному пингу, а не N×пинг."""
        import asyncio as aio

        async def _slow_ping(base, key):
            await aio.sleep(0.3)
            return {"ok": True, "status": "ok", "http_status": 200,
                    "latency_ms": 1.0, "checked_at": "t"}

        hot.set_config_cache(_FakeCache({
            "keys.llm_api_key": "sk-x",
            "keys.groq_api_key": "gsk-x",
            "keys.openrouter_api_key": "or-x",
        }))
        svc = StatusService()
        monkeypatch.setattr(svc, "_ping_models", staticmethod(_slow_ping))
        monkeypatch.setattr(
            "services.status_service.StatusService._server_metrics",
            staticmethod(lambda: {}))
        started = time.monotonic()
        snapshot = await svc.build_snapshot(_FakeCache(pg=_FakePg()))
        elapsed = time.monotonic() - started
        assert len(snapshot["llm"]) == 3
        # последовательно было бы ~0.9с; параллельно — ~0.3с
        assert elapsed < 0.7, f"health-check'и не параллельны: {elapsed:.2f}s"

    def test_record_llm_latency(self):
        svc = StatusService()
        svc.record_llm("deepseek", 123.4)
        assert svc._llm_latency["deepseek"] == 123.4

    def test_record_llm_error_logged(self, caplog):
        import logging
        svc = StatusService()
        with caplog.at_level(logging.INFO):
            svc.record_llm("deepseek", None, error="timeout")
        assert any("llm error" in r.message for r in caplog.records)


class _FakePsutil:
    """psutil-заглушка: loadavg бросает OSError (как на Windows-подобных)."""

    def __init__(self, fail_all=False):
        self.fail_all = fail_all

    def cpu_percent(self, interval=None):
        if self.fail_all:
            raise RuntimeError("boom")
        return 10.0

    def virtual_memory(self):
        return types.SimpleNamespace(total=100, used=50, percent=50.0)

    def disk_usage(self, path):
        return types.SimpleNamespace(total=100, used=20, percent=20.0)

    def getloadavg(self):
        raise OSError("not supported")

    def Process(self, pid):
        if self.fail_all:
            raise RuntimeError("boom")
        return types.SimpleNamespace(
            pid=pid,
            memory_info=lambda: types.SimpleNamespace(rss=1024 * 1024),
            num_threads=lambda: 4,
            cpu_percent=lambda interval=None: 1.0)


class TestServerMetricsPsutil:
    def test_loadavg_none_when_unavailable(self, monkeypatch):
        monkeypatch.setattr("services.status_service.psutil", _FakePsutil())
        metrics = StatusService._server_metrics()
        assert metrics["loadavg"] is None
        assert metrics["process"]["rss_mb"] == 1.0

    def test_metrics_empty_on_psutil_failure(self, monkeypatch):
        monkeypatch.setattr("services.status_service.psutil",
                            _FakePsutil(fail_all=True))
        assert StatusService._server_metrics() == {}


class TestUptimeFetch:
    @pytest.mark.asyncio
    async def test_pg_down_returns_empty(self, monkeypatch, caplog):
        import logging

        class _BoomPool:
            def acquire(self):
                class _CM:
                    async def __aenter__(self):
                        raise ConnectionError("pg down")

                    async def __aexit__(self, *exc):
                        return False

                return _CM()

        class _Pg:
            pool = _BoomPool()

        svc = StatusService()
        with caplog.at_level(logging.WARNING):
            rows = await svc.fetch_uptime_rows(_Pg())
        assert rows == []
        assert any("R6" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_pool_none_returns_empty(self):
        class _Pg:
            pool = None

        assert await StatusService().fetch_uptime_rows(_Pg()) == []


class TestPingModels:
    """Реальный _ping_models (httpx подменяется в sys.modules)."""

    @pytest.mark.asyncio
    async def test_ping_ok(self, monkeypatch):
        import sys
        import types as types_mod

        class _Resp:
            status_code = 200

        class _FakeClient:
            def __init__(self, timeout=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, headers=None):
                return _Resp()

        fake_httpx = types_mod.SimpleNamespace(AsyncClient=_FakeClient)
        monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
        result = await StatusService._ping_models("https://x/v1", "sk-key")
        assert result["ok"] is True
        assert result["http_status"] == 200

    @pytest.mark.asyncio
    async def test_ping_exception_unreachable(self, monkeypatch):
        import sys
        import types as types_mod

        class _FakeClient:
            def __init__(self, timeout=None):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, headers=None):
                raise ConnectionError("net down")

        fake_httpx = types_mod.SimpleNamespace(AsyncClient=_FakeClient)
        monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
        result = await StatusService._ping_models("https://x/v1", "sk-key")
        assert result["ok"] is False
        assert result["status"] == "unreachable"

    def test_fallback_provider_in_registry(self, monkeypatch):
        hot.set_config_cache(_FakeCache({
            "models.llm_fallback_base_url": "https://fb/v1",
            "models.llm_fallback_model": "fb-model",
            "keys.llm_fallback_api_key": "sk-fb",
        }))
        providers = StatusService.llm_registry()
        names = [p["provider"] for p in providers]
        assert "deepseek_fallback" in names
        fb = next(p for p in providers if p["provider"] == "deepseek_fallback")
        assert fb["base_url"] == "https://fb/v1"
        assert fb["model"] == "fb-model"


_NO_KEYS = {
    "keys.llm_api_key": "",
    "keys.groq_api_key": "",
    "keys.openrouter_api_key": "",
    "keys.llm_fallback_api_key": "",
    "models.llm_fallback_base_url": "",
    "models.llm_fallback_model": "",
}
