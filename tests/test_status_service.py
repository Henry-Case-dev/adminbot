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

    def test_gap_fill_up_down_down_up(self):
        """10.7 (2b): пропущенные 5-мин слоты между heartbeats → 'down'."""
        now = datetime.datetime.now(datetime.timezone.utc)
        slot = int(now.timestamp() // 300) * 300
        t0 = datetime.datetime.fromtimestamp(slot - 900, datetime.timezone.utc)
        t1 = datetime.datetime.fromtimestamp(slot, datetime.timezone.utc)
        buckets = StatusService._bucketize([_row(t0), _row(t1)])
        statuses = [b["status"] for b in buckets]
        assert statuses[:4] == ["up", "down", "down", "up"], statuses
        assert len(buckets) <= 288

    def test_gap_fill_trailing_downtime(self):
        """10.7 (2b): простой после последнего heartbeat виден как 'down'."""
        now = datetime.datetime.now(datetime.timezone.utc)
        slot = int(now.timestamp() // 300) * 300
        t_last = datetime.datetime.fromtimestamp(slot - 1200, datetime.timezone.utc)
        buckets = StatusService._bucketize([_row(t_last)])
        statuses = [b["status"] for b in buckets]
        assert statuses[0] == "up", statuses
        assert all(s == "down" for s in statuses[1:]), statuses
        assert statuses[-1] == "down"


class TestSnapshot:
    async def _build(self, svc, cache, monkeypatch, is_global_admin=False):
        monkeypatch.setattr(
            "services.status_service.StatusService._server_metrics",
            staticmethod(lambda: {"cpu_percent": 1.0}))
        ctx = types.SimpleNamespace(is_global_admin=is_global_admin)
        return await svc.build_snapshot(cache, ctx=ctx)

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
        assert set(snapshot) == {"bot", "server", "llm", "uptime", "permsoc"}
        bot = snapshot["bot"]
        assert bot["state"] == "polling"
        assert bot["mode"] == "polling"
        assert bot["version"]
        assert bot["uptime_seconds"] >= 0
        assert bot["errors_total"] >= 0
        # ФИКС 2026-09-03: пустые uptime_events → НЕ [], а минимальные
        # бакеты (два последних слота 'down') + generated_at — фронт видит
        # осмысленный график вместо «плоско/нет данных».
        assert len(snapshot["uptime"]["buckets"]) == 2
        assert all(b["status"] == "down" for b in snapshot["uptime"]["buckets"])
        assert snapshot["uptime"]["generated_at"]
        for b in snapshot["uptime"]["buckets"]:
            assert "ts" in b
            assert "status" in b

    @pytest.mark.asyncio
    async def test_uptime_empty_rows_minimal_buckets(self, monkeypatch):
        """ФИКС 2026-09-03: uptime_events пуст → два 5-мин бакета
        status='down' (последние слоты) + generated_at; формат {ts,status}."""
        svc = StatusService()
        svc.mark_started()
        cache = _FakeCache(pg=_FakePg())
        snapshot = await self._build(svc, cache, monkeypatch)
        up = snapshot["uptime"]
        assert len(up["buckets"]) == 2
        for b in up["buckets"]:
            assert b["status"] == "down"
            assert b["ts"].endswith("+00:00") or "T" in b["ts"]
        assert up["generated_at"]
        # 10.7 (2b): fallback-бакеты все 'down' → heartbeat отсутствует.
        assert up["last_heartbeat"] is None

    @pytest.mark.asyncio
    async def test_llm_cards_masked_keys(self, monkeypatch):
        hot.set_config_cache(_FakeCache({
            "keys.llm_api_key": "sk_deepseek_123456",
            "keys.groq_api_key": "gsk_groq_secret_abc",
            "keys.openrouter_api_key": "",
        }))
        svc = StatusService()
        cache = _FakeCache(pg=_FakePg())
        snapshot = await self._build(svc, cache, monkeypatch,
                                     is_global_admin=True)
        cards = {c["module_id"]: c for c in snapshot["llm"]}
        assert "llm_main" in cards
        assert cards["llm_main"]["model"]
        # маскировка: только configured/last4 — полное значение НИКОГДА
        assert cards["llm_main"]["key"] == {
            "configured": True, "last4": "3456"}
        assert cards["stt_groq"]["key"] == {
            "configured": True, "last4": "_abc"}
        assert cards["stt_openrouter"]["key"] == {
            "configured": False, "last4": None}
        # провайдер — реальный host (не хардкод deepseek/groq/openrouter).
        assert cards["llm_main"]["provider"] == "apinet.cloud"
        for card in cards.values():
            assert "sk_deepseek" not in str(card)
            assert "gsk_groq_secret" not in str(card)
        # 10.9: поля групп для единого блока «Доступность ключей».
        assert cards["llm_main"]["group_id"] == "llm_functions"
        assert cards["stt_groq"]["group_id"] == "transcription"
        assert "group_title" in cards["llm_main"]

    @pytest.mark.asyncio
    async def test_llm_cards_no_last4_for_readonly_roles(self, monkeypatch):
        """ФИКС S2 (F-7 §1.2-2): read-only роли (local admin/moderator/user)
        видят только {configured} — last4 глобальных ключей НЕ отдаются."""
        hot.set_config_cache(_FakeCache({
            "keys.llm_api_key": "sk_deepseek_123456",
            "keys.groq_api_key": "gsk_groq_secret_abc",
            "keys.openrouter_api_key": "",
        }))
        svc = StatusService()
        cache = _FakeCache(pg=_FakePg())
        snapshot = await self._build(svc, cache, monkeypatch,
                                     is_global_admin=False)
        cards = {c["module_id"]: c for c in snapshot["llm"]}
        assert cards["llm_main"]["key"] == {"configured": True}
        assert cards["stt_groq"]["key"] == {"configured": True}
        assert cards["stt_openrouter"]["key"] == {"configured": False}
        for card in cards.values():
            assert "last4" not in card["key"]
            assert "sk_deepseek" not in str(card)
        # fail-open: ctx=None → тоже без last4 (защита по умолчанию)
        snapshot2 = await svc.build_snapshot(cache)
        assert "last4" not in snapshot2["llm"][0]["key"]

    @pytest.mark.asyncio
    async def test_permsoc_telemetry_chat_context(self, monkeypatch):
        """F-9 §6: «N из M» модулей PERMsoc для контекста чата (по
        effective-состояниям реестра; решение alan не затрагивается)."""
        svc = StatusService()

        async def fake_master(chat_id):
            return True

        async def fake_module(chat_id, module_id):
            return module_id != "mimic"

        monkeypatch.setattr("services.permsoc.master_enabled", fake_master)
        monkeypatch.setattr("services.permsoc.module_enabled", fake_module)
        tele = await svc.permsoc_telemetry(-100)
        assert tele["master"] is True
        assert tele["total"] == 5
        assert tele["enabled"] == 4
        assert tele["modules"]["alan"] is True
        assert tele["modules"]["mimic"] is False
        # без чата: глобальный слой
        tele2 = await svc.permsoc_telemetry(None)
        assert tele2["total"] == 5

    @pytest.mark.asyncio
    async def test_health_not_configured(self, monkeypatch):
        hot.set_config_cache(_FakeCache(_NO_KEYS))
        svc = StatusService()
        cache = _FakeCache(pg=_FakePg())
        snapshot = await self._build(svc, cache, monkeypatch)
        cards = {c["module_id"]: c for c in snapshot["llm"]}
        assert cards["llm_main"]["health"]["status"] == "not_configured"
        assert cards["llm_main"]["health"]["ok"] is False

    @pytest.mark.asyncio
    async def test_health_unreachable_when_ping_fails(self, monkeypatch):
        async def _fake_probe(base_url, key, model="", kind="chat"):
            return {"ok": False, "status": "unreachable", "http_status": None,
                    "latency_ms": None, "checked_at": "t"}

        hot.set_config_cache(_FakeCache({"keys.llm_api_key": "sk-x"}))
        svc = StatusService()
        monkeypatch.setattr(svc, "_ping_provider",
                            staticmethod(_fake_probe))
        cache = _FakeCache(pg=_FakePg())
        snapshot = await self._build(svc, cache, monkeypatch)
        cards = {c["module_id"]: c for c in snapshot["llm"]}
        assert cards["llm_main"]["health"]["status"] == "unreachable"
        assert cards["llm_main"]["health"]["ok"] is False

    @pytest.mark.asyncio
    async def test_health_error_code_cached_shorter(self, monkeypatch):
        """ADR-109-3: ошибка (502) не отдаёт stale-ok и переспрашивается
        раньше 60с (кэш ошибок 10с)."""
        calls = {"n": 0}

        async def _fake_probe(base_url, key, model="", kind="chat"):
            calls["n"] += 1
            return {"ok": False, "status": "error", "http_status": 502,
                    "latency_ms": 3.0, "checked_at": "t"}

        hot.set_config_cache(_FakeCache({"keys.llm_api_key": "sk-x"}))
        svc = StatusService()
        monkeypatch.setattr(svc, "_ping_provider",
                            staticmethod(_fake_probe))
        h1 = await svc._check_health("llm_main", "https://x/v1", "sk-x",
                                     "m", "chat")
        h2 = await svc._check_health("llm_main", "https://x/v1", "sk-x",
                                     "m", "chat")
        assert h1["status"] == "error" and h1["http_status"] == 502
        assert calls["n"] == 1          # в пределах 10с кэш ошибки
        # искусственно состарим кэш → повторный probe
        svc._health_cache["llm_main"] = (
            time.monotonic() - 11.0, svc._health_cache["llm_main"][1])
        await svc._check_health("llm_main", "https://x/v1", "sk-x", "m", "chat")
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_health_cache_60s(self, monkeypatch):
        """Результат health-check кэшируется: повторный вызов не пингует."""
        calls = {"n": 0}

        async def _fake_ping(base_url, key, model="", kind="chat"):
            calls["n"] += 1
            return {"ok": True, "status": "ok", "http_status": 200,
                    "latency_ms": 5.0, "checked_at": "t"}

        hot.set_config_cache(_FakeCache({
            "keys.llm_api_key": "sk-x",
            "keys.groq_api_key": "gsk-x",
            "keys.openrouter_api_key": "or-x",
        }))
        svc = StatusService()
        monkeypatch.setattr(svc, "_ping_provider", staticmethod(_fake_ping))
        cache = _FakeCache(pg=_FakePg())
        monkeypatch.setattr(
            "services.status_service.StatusService._server_metrics",
            staticmethod(lambda: {}))
        await svc.build_snapshot(cache)
        n_first = calls["n"]
        assert n_first >= 3
        await svc.build_snapshot(cache)
        assert calls["n"] == n_first   # кэш 60с — второй вызов без пингов

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
        # 10.7 (2b): gap-fill может добавить граничный слот 'down' — ≥1.
        assert len(snapshot["uptime"]["buckets"]) >= 1
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

        async def _slow_ping(base, key, model="", kind="chat"):
            await aio.sleep(0.3)
            return {"ok": True, "status": "ok", "http_status": 200,
                    "latency_ms": 1.0, "checked_at": "t"}

        hot.set_config_cache(_FakeCache({
            "keys.llm_api_key": "sk-x",
            "keys.groq_api_key": "gsk-x",
            "keys.openrouter_api_key": "or-x",
        }))
        svc = StatusService()
        monkeypatch.setattr(svc, "_ping_provider", staticmethod(_slow_ping))
        monkeypatch.setattr(
            "services.status_service.StatusService._server_metrics",
            staticmethod(lambda: {}))
        started = time.monotonic()
        snapshot = await svc.build_snapshot(_FakeCache(pg=_FakePg()))
        elapsed = time.monotonic() - started
        assert len(snapshot["llm"]) >= 3
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


class TestEmbedFallbackModelParity:
    """Scanner LOW (10.11): статус fb-модели следует семантике рантайма
    (`llm_client._embed_fallback_model`): пустое значение в PG → ГЛАВНАЯ
    embed-модель, а не env-дефолт; отсутствующий ключ → env-дефолт."""

    def test_empty_pg_value_falls_back_to_main_not_env(self, monkeypatch):
        import dataclasses
        from services import status_service
        replaced = dataclasses.replace(
            status_service.settings,
            EMBEDDING_FALLBACK_MODEL="env-fb-model")
        monkeypatch.setattr(status_service, "settings", replaced)
        hot.set_config_cache(_FakeCache({
            "models.embedding_fallback_base_url": "https://fb.example/v1",
            "models.embedding_fallback_model": "",   # ключ есть, значение пустое
            "keys.embedding_fallback_api_key": "k1",
        }))
        cards = {p["module_id"]: p
                 for p in status_service.StatusService.llm_registry()}
        main_model = cards["emb_main"]["model"]
        assert main_model
        assert cards["emb_fallback"]["model"] == main_model
        assert cards["emb_fallback"]["model"] != "env-fb-model"

    def test_absent_pg_key_uses_env_model(self, monkeypatch):
        import dataclasses
        from services import status_service
        replaced = dataclasses.replace(
            status_service.settings,
            EMBEDDING_FALLBACK_MODEL="env-fb-model")
        monkeypatch.setattr(status_service, "settings", replaced)
        hot.set_config_cache(_FakeCache({
            "models.embedding_fallback_base_url": "https://fb.example/v1",
            "keys.embedding_fallback_api_key": "k1",
        }))
        cards = {p["module_id"]: p
                 for p in status_service.StatusService.llm_registry()}
        assert cards["emb_fallback"]["model"] == "env-fb-model"


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


class TestProbeOpenAI:
    """ADR-109-3: probe_openai различает ok/timeout/unreachable/error/
    not_configured (httpx подменяется в llm_probe)."""

    @pytest.mark.asyncio
    async def test_probe_ok(self, monkeypatch):
        from services import llm_probe

        class _Resp:
            status_code = 200
            text = ""

        async def _fake_post(client, url, headers, body):
            return _Resp()

        monkeypatch.setattr(llm_probe, "_post_json", _fake_post)
        result = await llm_probe.probe_openai(
            "https://x/v1", "sk-key", "m", kind="chat")
        assert result["ok"] is True
        assert result["status"] == "ok"
        assert result["http_status"] == 200

    @pytest.mark.asyncio
    async def test_probe_timeout(self, monkeypatch):
        from services import llm_probe
        import httpx as real_httpx

        async def _fake_post(client, url, headers, body):
            raise real_httpx.TimeoutException("slow")

        monkeypatch.setattr(llm_probe, "_post_json", _fake_post)
        result = await llm_probe.probe_openai(
            "https://x/v1", "sk-key", "m", kind="chat")
        assert result["status"] == "timeout"
        assert result["http_status"] is None

    @pytest.mark.asyncio
    async def test_probe_error_502(self, monkeypatch):
        from services import llm_probe

        class _Resp:
            status_code = 502
            text = "bad gateway"

        async def _fake_post(client, url, headers, body):
            return _Resp()

        monkeypatch.setattr(llm_probe, "_post_json", _fake_post)
        result = await llm_probe.probe_openai(
            "https://x/v1", "sk-key", "m", kind="chat")
        assert result["status"] == "error"
        assert result["http_status"] == 502

    @pytest.mark.asyncio
    async def test_probe_unreachable(self, monkeypatch):
        from services import llm_probe

        async def _fake_post(client, url, headers, body):
            raise ConnectionError("net down")

        monkeypatch.setattr(llm_probe, "_post_json", _fake_post)
        result = await llm_probe.probe_openai(
            "https://x/v1", "sk-key", "m", kind="chat")
        assert result["status"] == "unreachable"

    @pytest.mark.asyncio
    async def test_probe_not_configured(self):
        from services import llm_probe
        r1 = await llm_probe.probe_openai("", "sk-key", "m")
        assert r1["status"] == "not_configured"
        r2 = await llm_probe.probe_openai("https://x/v1", "", "m")
        assert r2["status"] == "not_configured"

    @pytest.mark.asyncio
    async def test_probe_embeddings_endpoint(self, monkeypatch):
        from services import llm_probe

        seen = {}

        class _Resp:
            status_code = 200
            text = ""

        async def _fake_post(client, url, headers, body):
            seen["url"] = url
            return _Resp()

        monkeypatch.setattr(llm_probe, "_post_json", _fake_post)
        await llm_probe.probe_openai("https://x/v1", "sk-key", "emb",
                                     kind="embeddings")
        assert seen["url"].endswith("/embeddings")

    @pytest.mark.asyncio
    async def test_probe_stt_endpoint(self, monkeypatch):
        """CRITICAL-1: STT-проб идёт на POST /audio/transcriptions с файлом,
        а не на /chat/completions (Whisper — не chat-модель)."""
        from services import llm_probe

        seen = {}

        class _Resp:
            status_code = 200
            text = ""

        async def _fake_multipart(client, url, headers, data, files):
            seen["url"] = url
            seen["data"] = data
            seen["files"] = files
            return _Resp()

        monkeypatch.setattr(llm_probe, "_post_multipart", _fake_multipart)
        result = await llm_probe.probe_openai(
            "https://api.groq.com/openai/v1", "gsk-key", "whisper-large-v3",
            kind="stt")
        assert result["ok"] is True
        assert seen["url"] == "https://api.groq.com/openai/v1/audio/transcriptions"
        assert seen["data"]["model"] == "whisper-large-v3"
        assert "file" in seen["files"]
        name, payload, mime = seen["files"]["file"]
        assert name.endswith(".wav") and mime == "audio/wav"
        assert payload[:4] == b"RIFF"      # валидный WAV-заголовок

    def test_registry_kind_stt_vs_chat(self, monkeypatch):
        """CRITICAL-1: stt_groq → kind='stt'; stt_openrouter — chat
        (расшифровка OpenRouter идёт через chat.completions + input_audio)."""
        hot.set_config_cache(_FakeCache({}))
        by_id = {p["module_id"]: p for p in StatusService.llm_registry()}
        assert by_id["stt_groq"]["kind"] == "stt"
        assert by_id["stt_openrouter"]["kind"] == "chat"
        assert by_id["llm_main"]["kind"] == "chat"
        assert by_id["emb_main"]["kind"] == "embeddings"

    def test_fallback_provider_in_registry(self, monkeypatch):
        hot.set_config_cache(_FakeCache({
            "models.llm_fallback_base_url": "https://fb.example/v1",
            "models.llm_fallback_model": "fb-model",
            "keys.llm_fallback_api_key": "sk-fb",
        }))
        providers = StatusService.llm_registry()
        ids = [p["module_id"] for p in providers]
        assert "llm_fallback" in ids
        fb = next(p for p in providers if p["module_id"] == "llm_fallback")
        assert fb["base_url"] == "https://fb.example/v1"
        assert fb["model"] == "fb-model"
        # провайдер — реальный host (без хардкода deepseek_fallback).
        assert fb["provider"] == "fb.example"
        assert fb["group_id"] == "llm_functions"

    def test_registry_has_function_groups(self, monkeypatch):
        """7.1: эмбеддинги и группы функций присутствуют; module_id
        уникальны; провайдер = host."""
        hot.set_config_cache(_FakeCache({}))
        reg = StatusService.llm_registry()
        ids = [p["module_id"] for p in reg]
        assert len(ids) == len(set(ids))
        assert "emb_main" in ids
        assert "video_openrouter" in ids
        for p in reg:
            assert p["provider"] == StatusService._host(p["base_url"])
            assert p["group_id"] in ("llm_functions", "transcription",
                                     "video_summary", "embeddings")


_NO_KEYS = {
    "keys.llm_api_key": "",
    "keys.groq_api_key": "",
    "keys.openrouter_api_key": "",
    "keys.llm_fallback_api_key": "",
    "models.llm_fallback_base_url": "",
    "models.llm_fallback_model": "",
}
