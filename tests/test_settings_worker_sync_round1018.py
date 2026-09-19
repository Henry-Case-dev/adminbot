"""Раунд 10.18 (F7 settings-worker-sync, T-1759…T-1764) — тесты единого
источника истины настроек: приоритет per-chat DB → глобальный DB →
env-дефолт, fail-open, source в статус-API, реактивность воркера.

R17-safe: значения секретов не используются; проверяются только bool/int.
"""
import asyncio
import contextlib
import logging

import pytest

from services import chat_params as cp
from services import hot_config as hot
from services import worker_settings as ws
from services.worker_settings import (
    resolve_setting,
    resolve_setting_cached,
    resolve_setting_with_source,
    setting_source,
)


class _FakeHot:
    """Глобальный слой (bot_settings): заданные ключи, иначе default."""

    def __init__(self, values):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakeChatCache:
    def __init__(self, root):
        self.root = root or {}
        self.invalidated = []

    async def get_chat_params(self, chat_id):
        return self.root

    async def invalidate_chat(self, chat_id):
        self.invalidated.append(chat_id)


class _BoomChatCache:
    async def get_chat_params(self, chat_id):
        raise RuntimeError("PG down")

    async def invalidate_chat(self, chat_id):
        pass


def _hot(monkeypatch, values):
    monkeypatch.setattr(hot, "_cache", _FakeHot(values))


def _chat(monkeypatch, root):
    cache = _FakeChatCache(root)
    monkeypatch.setattr(cp, "_chat_params_cache", cache)
    return cache


# ── приоритет per-chat > global > default ──────────────────────────────────

class TestResolvePriority:
    @pytest.mark.asyncio
    async def test_chat_overrides_global(self, monkeypatch):
        _hot(monkeypatch, {"memory.dream_enabled": False})
        _chat(monkeypatch, {"overrides": {"memory.dream_enabled": True}})
        value, source = await resolve_setting_with_source(
            "memory.dream_enabled", chat_id=-100, default=False)
        assert value is True
        assert source == "chat"

    @pytest.mark.asyncio
    async def test_global_when_no_chat_override(self, monkeypatch):
        _hot(monkeypatch, {"memory.dream_enabled": True})
        _chat(monkeypatch, {"overrides": {}})
        value, source = await resolve_setting_with_source(
            "memory.dream_enabled", chat_id=-100, default=False)
        assert value is True
        assert source == "global"

    @pytest.mark.asyncio
    async def test_default_when_nowhere(self, monkeypatch):
        _hot(monkeypatch, {})
        _chat(monkeypatch, {"overrides": {}})
        value, source = await resolve_setting_with_source(
            "memory.dream_repeat_threshold", chat_id=-100, default=3)
        assert value == 3
        assert source == "default"

    @pytest.mark.asyncio
    async def test_no_chat_id_uses_global_only(self, monkeypatch):
        _hot(monkeypatch, {"memory.dream_enabled": True})
        _chat(monkeypatch, {"overrides": {"memory.dream_enabled": False}})
        value = await resolve_setting("memory.dream_enabled", default=False)
        assert value is True          # chat-слой не участвует без chat_id

    @pytest.mark.asyncio
    async def test_chat_garbage_falls_back_to_global(self, monkeypatch):
        _hot(monkeypatch, {"memory.dream_enabled": True})
        _chat(monkeypatch, {"overrides": {"memory.dream_enabled": "мусор"}})
        value, source = await resolve_setting_with_source(
            "memory.dream_enabled", chat_id=-100, default=False)
        # "мусор" не кастуется к bool → глобальный слой
        assert value is True
        assert source == "global"

    @pytest.mark.asyncio
    async def test_regression_symptom_ui_on_chat_off_global(self, monkeypatch):
        """Симптом владельца: UI ON в scope чата + глобальный OFF → воркер
        обязан увидеть ON (source=chat)."""
        _hot(monkeypatch, {"memory.dream_enabled": False})
        cache = _chat(monkeypatch,
                      {"overrides": {"memory.dream_enabled": True}})
        value = await resolve_setting_cached(
            "memory.dream_enabled", chat_id=-100, default=False)
        assert value is True
        # setting_source — best-effort по прогретому in-memory слою
        cache._items = {-100: (0.0, cache.root, None)}
        assert ws.setting_source("memory.dream_enabled", chat_id=-100) == "chat"


# ── fail-open ──────────────────────────────────────────────────────────────

class TestFailOpen:
    @pytest.mark.asyncio
    async def test_chat_cache_error_falls_back_to_global(self, monkeypatch):
        """D-1 (ревью Батча E): значение fail-open (глобал), но source
        помечается 'error' — «слой не читается» отличимо от «override нет»."""
        _hot(monkeypatch, {"memory.dream_enabled": True})
        monkeypatch.setattr(cp, "_chat_params_cache", _BoomChatCache())
        value, source = await resolve_setting_with_source(
            "memory.dream_enabled", chat_id=-100, default=False)
        assert value is True
        assert source == "error"

    @pytest.mark.asyncio
    async def test_no_chat_pool_is_source_error(self, monkeypatch):
        """D-1: `ChatParamsCache` есть, но PG-pool недоступен → 'error'."""
        _hot(monkeypatch, {"memory.dream_enabled": True})

        class _NoPool:
            def _pool(self):
                return None

            async def get_chat_params_checked(self, chat_id):
                return {}, False

            async def get_chat_params(self, chat_id):
                return {}

        monkeypatch.setattr(cp, "_chat_params_cache", _NoPool())
        value, source = await resolve_setting_with_source(
            "memory.dream_enabled", chat_id=-100, default=False)
        assert value is True
        assert source == "error"

    @pytest.mark.asyncio
    async def test_no_caches_returns_default(self, monkeypatch):
        monkeypatch.setattr(hot, "_cache", None)
        monkeypatch.setattr(cp, "_chat_params_cache", None)
        value = await resolve_setting("memory.dream_enabled", default=False)
        assert value is False


# ── setting_source (best-effort, без I/O) ──────────────────────────────────

class TestSettingSource:
    def test_source_chat(self, monkeypatch):
        _hot(monkeypatch, {"memory.dream_enabled": False})
        monkeypatch.setattr(cp, "_chat_params_cache",
                            _FakeChatCache({"overrides":
                                            {"memory.dream_enabled": True}}))
        # best-effort читает _items (заполняется вручную)
        cache = cp.get_chat_params_cache()
        cache._items = {-100: (0.0, cache.root, None)}
        assert setting_source("memory.dream_enabled", chat_id=-100) == "chat"

    def test_source_global(self, monkeypatch):
        _hot(monkeypatch, {"memory.dream_enabled": True})
        monkeypatch.setattr(cp, "_chat_params_cache", None)
        assert setting_source("memory.dream_enabled", chat_id=-100) == "global"

    def test_source_default(self, monkeypatch):
        _hot(monkeypatch, {})
        monkeypatch.setattr(cp, "_chat_params_cache", None)
        assert setting_source("memory.dream_enabled", chat_id=-100) == "default"


# ── NOTIFY-инвалидация (fallback для кросс-процесса) ───────────────────────

class TestNotifyInvalidate:
    @pytest.mark.asyncio
    async def test_payload_invalidates_chat(self, monkeypatch):
        cache = _FakeChatCache({})
        monkeypatch.setattr(cp, "_chat_params_cache", cache)
        await cp.invalidate_chat_from_notify("-100")
        assert cache.invalidated == [-100]

    @pytest.mark.asyncio
    async def test_no_cache_or_bad_payload_is_fail_open(self, monkeypatch):
        monkeypatch.setattr(cp, "_chat_params_cache", None)
        await cp.invalidate_chat_from_notify("-100")     # нет кэша → тихо
        cache = _FakeChatCache({})
        monkeypatch.setattr(cp, "_chat_params_cache", cache)
        await cp.invalidate_chat_from_notify("не-число")  # битый — fail-open
        assert cache.invalidated == []


# ── DreamWorker: per-chat резолв + реактивность ────────────────────────────

class TestDreamWorkerPerChat:
    @pytest.mark.asyncio
    async def test_key_for_resolves_chat_override(self, monkeypatch):
        from services.dream_worker import DreamWorker
        _hot(monkeypatch, {"memory.dream_repeat_threshold": 3})
        monkeypatch.setattr(cp, "_chat_params_cache",
                            _FakeChatCache({"overrides":
                                            {"memory.dream_repeat_threshold": 2}}))
        worker = DreamWorker(db=None, memory=None, llm=None)
        assert await worker._key_for(-100, "repeat_threshold", 5) == 2

    @pytest.mark.asyncio
    async def test_lock_held_tick_returns_and_does_not_interrupt_run(
            self, monkeypatch):
        """F7: если прогон уже активен (`_run_lock` занят), тик делает ранний
        return и НЕ прерывает текущий прогон."""
        from services.dream_worker import DreamWorker
        _hot(monkeypatch, {"memory.dream_enabled": False})
        monkeypatch.setattr(cp, "_chat_params_cache", None)
        worker = DreamWorker(db=None, memory=None, llm=None)
        called = {"n": 0}

        async def _run(*args, **kwargs):
            called["n"] += 1
            return {}

        monkeypatch.setattr(worker, "_run", _run)
        await worker._run_lock.acquire()
        try:
            await worker._tick()             # lock занят → ранний return
            assert called["n"] == 0
            assert worker._run_lock.locked()  # активный прогон не прерван
        finally:
            worker._run_lock.release()

    @pytest.mark.asyncio
    async def test_tick_runs_when_dream_off_but_chat_off_skips(
            self, monkeypatch):
        """F7/R10.18-4: глобальный OFF НЕ отменяет тик (джоб всегда
        зарегистрирован) — решение per-chat в `_process_chat`. Для чата без
        override ON прогон не читает кандидатов (реальная ветка «выключено»)."""
        from services.dream_worker import DreamWorker
        _hot(monkeypatch, {"memory.dream_enabled": False})
        monkeypatch.setattr(cp, "_chat_params_cache", None)
        worker = DreamWorker(db=None, memory=None, llm=None)
        run_calls = {"n": 0}

        async def _run(*args, **kwargs):
            run_calls["n"] += 1
            return {}

        monkeypatch.setattr(worker, "_run", _run)
        await worker._tick()                 # раннего return «по флагу» нет
        assert run_calls["n"] == 1

        candidate_calls = {"n": 0}

        async def _candidates(chat_id, now):
            candidate_calls["n"] += 1
            return []

        monkeypatch.setattr(worker, "_candidates", _candidates)
        out = await worker._process_chat(-100, now=0, manual=False)
        assert out["distilled"] == 0
        assert candidate_calls["n"] == 0     # скип ДО чтения кандидатов


# ── Статус-API: enabled по чату + аддитивный source (R16) ──────────────────

class _FakeDb:
    async def last_run_at(self, kinds, chat_id=None):
        return None

    async def last_deep_run(self, chat_id=None):
        return None

    async def count_dream_log(self, today, kind=None, chat_id=None):
        return 0

    async def sum_dream_tokens(self, today):
        return 0

    async def get_last_user_message_ts(self, chat_id, bot_id):
        return None

    async def recent_nostalgia_sent(self, chat_id, bot_id, limit):
        return []

    # deep_sleep_status
    async def list_recent_beliefs(self, **kwargs):
        return []

    async def count_paradigms(self, chat_id=None):
        return 0

    async def recent_dream_log(self, limit=50, chat_id=None):
        return []


class TestStatusApiSource:
    @pytest.mark.asyncio
    async def test_cognition_status_resolves_chat_source(self, monkeypatch):
        from web.api import memory_agi as ma
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: _FakeDb())
        monkeypatch.setattr(hot, "get",
                            lambda key, default=None: {
                                "limits.summary_timezone": "UTC",
                                "memory.dream_enabled": False,
                            }.get(key, default))
        monkeypatch.setattr(cp, "_chat_params_cache",
                            _FakeChatCache({"overrides":
                                            {"memory.dream_enabled": True,
                                             "flags.deep_sleep_enabled": True}}))
        data = await ma.cognition_status(request=None, user=None, chat_id=-100)
        assert data["dream"]["enabled"] is True
        assert data["source"]["dream"] == "chat"
        assert data["deep_sleep"]["enabled"] is True
        assert data["source"]["deep_sleep"] == "chat"


class TestStatusMatchesWorkerBehavior:
    @pytest.mark.asyncio
    async def test_kill_switch_gates_cognition_active(self, monkeypatch):
        """R10.18-3: cognition `active` учитывает kill-switch так же, как
        воркер (`gates_enabled` → chat-gate → kill-switch → fallback →
        global): master ON + `flags.dream_enabled=false` → OFF, хотя окно
        сна открыто. `enabled` остаётся рубильником (master)."""
        import datetime
        import types
        from web.api import memory_agi as ma
        fixed = datetime.datetime(2026, 9, 14, 5, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: _FakeDb())
        monkeypatch.setattr(ma, "time",
                            types.SimpleNamespace(time=lambda: fixed))
        monkeypatch.setattr(hot, "get",
                            lambda key, default=None: {
                                "limits.summary_timezone": "UTC",
                                "memory.dream_enabled": True,
                                "flags.dream_enabled": False,
                            }.get(key, default))
        monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCache({}))
        data = await ma.cognition_status(request=None, user=None, chat_id=None)
        assert data["dream"]["enabled"] is True        # рубильник (master)
        assert data["dream"]["effective"] is False     # kill-switch побеждает
        assert data["dream"]["active"] is False

    @pytest.mark.asyncio
    async def test_no_kill_switch_in_window_is_active(self, monkeypatch):
        """Контроль: без kill-switch master ON + окно → active=True
        (поведение не сломано)."""
        import datetime
        import types
        from web.api import memory_agi as ma
        fixed = datetime.datetime(2026, 9, 14, 5, 0,
                                  tzinfo=datetime.timezone.utc).timestamp()
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: _FakeDb())
        monkeypatch.setattr(ma, "time",
                            types.SimpleNamespace(time=lambda: fixed))
        monkeypatch.setattr(hot, "get",
                            lambda key, default=None: {
                                "limits.summary_timezone": "UTC",
                                "memory.dream_enabled": True,
                            }.get(key, default))
        monkeypatch.setattr(cp, "_chat_params_cache", _FakeChatCache({}))
        data = await ma.cognition_status(request=None, user=None, chat_id=None)
        assert data["dream"]["effective"] is True
        assert data["dream"]["active"] is True

class TestDreamGateFallback:
    @pytest.mark.asyncio
    async def test_kill_switch_beats_per_chat_fallback(self, monkeypatch):
        """F7/R10.18-3 (регресс): явный глобальный kill-switch
        `flags.dream_enabled=false` ОБЯЗАН остановить тик даже при master-флаге
        `memory.dream_enabled=true` (per-chat override ON → fallback=True).
        Порядок слоёв: chat-gate → kill-switch → fallback → global."""
        from services.feature_gates import gates_enabled
        _hot(monkeypatch, {"memory.dream_enabled": True,
                           "flags.dream_enabled": False})
        monkeypatch.setattr(cp, "_chat_params_cache",
                            _FakeChatCache({"overrides":
                                            {"memory.dream_enabled": True}}))
        assert await gates_enabled(-100, "dream", fallback=True) is False

    @pytest.mark.asyncio
    async def test_fallback_used_when_no_kill_switch(self, monkeypatch):
        """F7/T-1760: без явного kill-switch (`flags.dream_enabled` не задан)
        per-chat master (fallback=True) побеждает глобальный master OFF —
        симптом владельца закрыт."""
        from services.feature_gates import gates_enabled
        _hot(monkeypatch, {"memory.dream_enabled": False})
        monkeypatch.setattr(cp, "_chat_params_cache",
                            _FakeChatCache({"overrides":
                                            {"memory.dream_enabled": True}}))
        assert await gates_enabled(-100, "dream", fallback=True) is True

    @pytest.mark.asyncio
    async def test_explicit_chat_gate_false_wins(self, monkeypatch):
        from services.feature_gates import gates_enabled
        _hot(monkeypatch, {"memory.dream_enabled": True})
        monkeypatch.setattr(cp, "_chat_params_cache",
                            _FakeChatCache({"gates": {"dream": False}}))
        assert await gates_enabled(-100, "dream", fallback=True) is False

    @pytest.mark.asyncio
    async def test_master_fallback_default_matches_worker_env_on(self,
                                                                 monkeypatch):
        """S10.18-15 (регресс): env `DREAM_ENABLED=true` без DB-ключа →
        `master_fallback` и резолв воркера используют ОДИН дефолт → оба True
        (раньше статус давал False при воркере ON)."""
        import types
        from services import feature_gates as fg
        from services.feature_gates import master_fallback
        monkeypatch.setattr(fg, "settings",
                            types.SimpleNamespace(DREAM_ENABLED=True))
        _hot(monkeypatch, {})
        _chat(monkeypatch, {"overrides": {}})
        worker_val = bool(await resolve_setting_cached(
            "memory.dream_enabled", chat_id=-100,
            default=fg.settings.DREAM_ENABLED))
        assert worker_val is True
        assert await master_fallback(-100, "dream") is True

    @pytest.mark.asyncio
    async def test_master_fallback_default_matches_worker_env_off(self,
                                                                  monkeypatch):
        """Контроль: env `DREAM_ENABLED=false` без DB-ключа → оба False."""
        import types
        from services import feature_gates as fg
        from services.feature_gates import master_fallback
        monkeypatch.setattr(fg, "settings",
                            types.SimpleNamespace(DREAM_ENABLED=False))
        _hot(monkeypatch, {})
        _chat(monkeypatch, {"overrides": {}})
        worker_val = bool(await resolve_setting_cached(
            "memory.dream_enabled", chat_id=-100,
            default=fg.settings.DREAM_ENABLED))
        assert worker_val is False
        assert await master_fallback(-100, "dream") is False


class _FakeNotifyConn:
    """asyncpg-соединение-заглушка: add_listener/is_closed/close (прецедент
    tests/test_lore_notify.py)."""

    def __init__(self, conn_id: int = 1):
        self.conn_id = conn_id
        self.listeners: list[tuple[str, object]] = []
        self.closed_flag = False
        self.close_calls = 0

    async def add_listener(self, channel: str, callback) -> None:
        self.listeners.append((channel, callback))

    async def close(self) -> None:
        self.closed_flag = True
        self.close_calls += 1

    def is_closed(self) -> bool:
        return self.closed_flag

    def publish(self, channel: str, payload: str) -> None:
        """Эмуляция NOTIFY: вызов зарегистрированных колбэков."""
        for ch, cb in list(self.listeners):
            if ch == channel:
                cb(self, 0, channel, payload)


class _FakeConnector:
    """Фабрика соединений: первые `fail_first` попыток падают (PG down)."""

    def __init__(self, fail_first: int = 0):
        self.attempts = 0
        self.fail_first = fail_first
        self.conns: list[_FakeNotifyConn] = []

    async def __call__(self):
        self.attempts += 1
        if self.attempts <= self.fail_first:
            raise ConnectionError("pg down")
        conn = _FakeNotifyConn(self.attempts)
        self.conns.append(conn)
        return conn


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise TimeoutError("условие не наступило за таймаут")
        await asyncio.sleep(0.01)


async def _run_notify(notify):
    """Запустить слушатель фоновой таской и вернуть её task."""
    return asyncio.create_task(notify.start())


async def _stop_task(task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


class TestListenerFailOpen:
    @pytest.mark.asyncio
    async def test_no_pool_returns_none_with_warning(self, monkeypatch,
                                                     caplog):
        """F7/T-1764: нет PG/DSN → LISTEN не поднимается, WARNING, бот жив.

        S10.18-10: reload `config.settings` изолирован — исходный объект
        настроек и `sys.modules['bot']` восстанавливаются в finally, чтобы
        тестовые env (пустые токены) не «протекали» в другие тесты при
        произвольном порядке (pytest-randomly)."""
        import importlib
        import sys as _sys
        monkeypatch.setenv("API_TOKEN", "123456:TEST_TOKEN_FOR_BSH")
        monkeypatch.setenv("LOGTAIL_SOURCE_TOKEN", "")
        monkeypatch.setenv("BETTERSTACK_HOST", "")
        monkeypatch.setenv("SENTRY_DSN", "")
        monkeypatch.setattr("sentry_sdk.init", lambda *a, **kw: None)
        import config.settings as settings_mod
        orig_settings = settings_mod.settings
        try:
            importlib.reload(settings_mod)
            _sys.modules.pop("bot", None)
            import bot as bot_mod
            with caplog.at_level(logging.WARNING, logger="bot"):
                task = await bot_mod._start_chat_params_listener(None)
            assert task is None
            assert any("listen unavailable" in r.message
                       for r in caplog.records)
        finally:
            # Возвращаем исходный Settings и выгружаем bot (не оставляем
            # тестовые env/токены в config.settings на весь прогон).
            settings_mod.settings = orig_settings
            _sys.modules.pop("bot", None)


class TestListenerStopLifecycle:
    @pytest.mark.asyncio
    async def test_stop_cancels_pending_and_closes(self, monkeypatch):
        """S10.18-7/-11: `stop()` — живой lifecycle-метод: закрывает
        соединение и снимает фоновые invalidate-задачи (сильные ссылки
        `_pending`, а не «безымянный» create_task)."""
        from services.chat_params_notify import ChatParamsNotify
        import services.chat_params as cp_mod

        async def _slow_invalidate(payload):
            await asyncio.sleep(30)

        monkeypatch.setattr(cp_mod, "invalidate_chat_from_notify",
                            _slow_invalidate)
        connector = _FakeConnector()
        notify = ChatParamsNotify(dsn="x", retry_interval=0.05,
                                  connector=connector)
        task = await _run_notify(notify)
        try:
            await _wait_until(lambda: connector.conns
                              and connector.conns[0].listeners)
            conn = connector.conns[0]
            conn.publish("chat_params_updated", "-100")
            await _wait_until(lambda: bool(notify._pending))
            assert len(notify._pending) == 1
            await notify.stop()
            assert notify._pending == set()          # задачи сняты
            assert conn.closed_flag is True          # соединение закрыто
        finally:
            await _stop_task(task)


class TestListenerRealMount:
    """R10.18-2: реальный путь монтирования LISTEN (отдельное соединение,
    fake-connector) — именно этого теста не хватило, чтобы поймать Critical
    R10.18-1 (`Pool.add_listener` не существует)."""

    @pytest.mark.asyncio
    async def test_mount_and_invalidate_by_payload(self, monkeypatch):
        from services.chat_params_notify import CHANNEL, ChatParamsNotify
        cache = _FakeChatCache({})
        monkeypatch.setattr(cp, "_chat_params_cache", cache)
        connector = _FakeConnector()
        notify = ChatParamsNotify(dsn="postgresql://u:p@h/db",
                                  retry_interval=0.05, connector=connector)
        task = await _run_notify(notify)
        try:
            await _wait_until(lambda: connector.conns)
            conn = connector.conns[0]
            await _wait_until(lambda: bool(conn.listeners))
            assert conn.listeners[0][0] == "chat_params_updated"
            assert CHANNEL == "chat_params_updated"
            conn.publish(CHANNEL, "-100")
            await _wait_until(lambda: cache.invalidated == [-100])
        finally:
            await _stop_task(task)

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, monkeypatch):
        from services.chat_params_notify import ChatParamsNotify
        cache = _FakeChatCache({})
        monkeypatch.setattr(cp, "_chat_params_cache", cache)
        connector = _FakeConnector()
        notify = ChatParamsNotify(dsn="x", retry_interval=0.05,
                                  connector=connector)
        task = await _run_notify(notify)
        try:
            await _wait_until(lambda: connector.conns)
            conn1 = connector.conns[0]
            await _wait_until(lambda: bool(conn1.listeners))
            await conn1.close()              # обрыв соединения
            await _wait_until(lambda: len(connector.conns) >= 2)
            conn2 = connector.conns[-1]
            await _wait_until(lambda: bool(conn2.listeners))
            assert conn2 is not conn1
            assert not task.done()           # слушатель жив после реконнекта
            conn2.publish("chat_params_updated", "-200")
            await _wait_until(lambda: cache.invalidated == [-200])
        finally:
            await _stop_task(task)

    @pytest.mark.asyncio
    async def test_connect_failure_warns_and_recovers(self, monkeypatch,
                                                      caplog):
        from services.chat_params_notify import ChatParamsNotify
        cache = _FakeChatCache({})
        monkeypatch.setattr(cp, "_chat_params_cache", cache)
        connector = _FakeConnector(fail_first=2)   # PG down на старте
        notify = ChatParamsNotify(dsn="x", retry_interval=0.05,
                                  connector=connector)
        task = await _run_notify(notify)
        try:
            with caplog.at_level(
                    logging.WARNING,
                    logger="services.chat_params_notify"):
                await _wait_until(lambda: connector.attempts >= 3)
                await _wait_until(lambda: connector.conns)
            assert any("LISTEN connect failed" in r.message
                       for r in caplog.records)
            assert connector.conns[0].listeners   # в итоге подписан
        finally:
            await _stop_task(task)


class TestStatusApiSourceExtra:
    @pytest.mark.asyncio
    async def test_deep_sleep_status_accepts_chat_id(self, monkeypatch):
        from web.api import memory_agi as ma
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: _FakeDb())
        monkeypatch.setattr(hot, "get",
                            lambda key, default=None: default)
        monkeypatch.setattr(cp, "_chat_params_cache",
                            _FakeChatCache({"overrides":
                                            {"flags.deep_sleep_enabled": True}}))
        data = await ma.deep_sleep_status(request=None, user=None, chat_id=-100)
        assert data["enabled"] is True
        assert data["source"] == "chat"
