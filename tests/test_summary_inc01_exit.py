"""INC-FIX-RESIDUAL (17.10.2026) — процесс обязан ВЫХОДИТЬ после graceful-фаз.

Прод-факт 2.58.82 (release-25882-report §«Graceful stop»): фазы `stopping →
draining → finalized`, строка `[shutdown] bye | elapsed_ms=523` и
`[betterstack] shutdown flush` отрабатывали, но процесс жил до SIGKILL через
60 с (`State 'stop-sigterm' timed out`, n=2). Причина: у процесса оставался
НЕзакрытый aiosqlite-коннект основного `DatabaseService` (`on_startup` →
`services/database.py:6056`), а worker-thread aiosqlite НЕ демон
(`aiosqlite/core.py` — `Thread(...)` без `daemon=True`) → интерпретатор на
`threading._shutdown()` ждёт его вечно. Тот же механизм уже известен тестовой
инфраструктуре (`conftest.py:8-12`: «если не закрыть, интерпретатор не
выходит»), но в продакшн-коде не закрывался никто.

Второй остаток того же участка: `polling.cancel()` отменял только внешнюю
таску aiogram (`Dispatcher.start_polling`), а его внутренняя
`Dispatcher._polling` оставалась живой — продолжала опрашивать Telegram и
обрабатывать апдейты УЖЕ ПОСЛЕ фазы `stopping`, а гасилась лишь в cleanup
`asyncio.run` (в прод-журнале «Polling stopped for bot …» через 0.36 с ПОСЛЕ
`bye`).

Третий (наблюдаемость): финализатор нетерминальных ранов писал терминал
только в `summary_runs`+stages, а Oversight/Status деривит «running» из
`mca_events` (START без терминала) → у закрытого FAILED-рана бейдж читался
«running» (прод: ран `da33f05d…`).

Проверяемый контракт (наблюдаемое поведение, не внутренности):
  * процесс выходит САМ в пределах бюджета после SIGTERM (без SIGKILL);
  * runtime-SQLite закрыт, «осиротевших» открытых aiosqlite-коннектов нет;
  * aiogram-polling остановлен штатно: внутренних `_polling`-тасок не
    остаётся, «Polling stopped» идёт ДО `bye`;
  * закрытый финализатором ран получает терминальное событие — durable
    FAILED и дериват UI («running») согласованы;
  * прежние фазы/строки остановки не изменены (их покрывает
    `test_summary_inc01_shutdown.py`).

TEST-LIFECYCLE: REGRESSION owner=INC-SUMMARY-01/exit
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock

import pytest

from services import mca_events as mca
from services import pipeline_events
from services import summary_run_store as srs
from services.database import DatabaseService

pytestmark = pytest.mark.asap41

CHAT = -100777
CHILD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "_inc01_exit_child.py")


@pytest.fixture(autouse=True)
def _clean_mca_buffer():
    """Изоляция in-memory буфера телеметрии между тестами."""
    mca.reset_pending()
    yield
    mca.reset_pending()


# ── helpers ────────────────────────────────────────────────────────────────

async def _fresh_db(tmp_path, name) -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _run_row(db, run_id) -> dict | None:
    cursor = await db.db.execute(
        "SELECT run_id, chat_id, state, publication_status FROM summary_runs "
        "WHERE run_id = ?", (str(run_id),))
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


def _events_flag_on(monkeypatch) -> None:
    """Kill-switch `SUMMARY_PIPELINE_EVENTS_ENABLED` ON для ТЕКУЩИХ инстансов
    settings (прецедент `test_pipeline_analytics_asap4._events_flag_off`:
    conftest-фикстуры asap4/asap41 патчат ClassVar на разных классах)."""
    import config.settings as cs
    from config.settings import Settings
    from services import pipeline_events as pe

    for _cls in {Settings, type(cs.settings)}:
        monkeypatch.setattr(_cls, "SUMMARY_PIPELINE_EVENTS_ENABLED", True,
                            raising=False)
    assert pe.events_enabled() is True


def _bot_module(monkeypatch):
    """Реальный модуль `bot` (reload-паттерн `test_summary_inc01_shutdown`)."""
    import importlib

    import config.settings as settings_mod

    monkeypatch.setenv("API_TOKEN", "123456:TEST_TOKEN_FOR_INC01_EXIT")
    monkeypatch.delenv("LOGTAIL_SOURCE_TOKEN", raising=False)
    monkeypatch.delenv("BETTERSTACK_HOST", raising=False)
    saved = {sig: signal.getsignal(sig)
             for sig in (signal.SIGINT, signal.SIGTERM)}
    sys.modules.pop("bot", None)
    importlib.reload(settings_mod)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    import bot
    return bot, saved


def _restore_signals(saved) -> None:
    for sig, handler in saved.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError, RuntimeError):  # pragma: no cover
            pass


class _FakeCache:
    def __init__(self):
        self._pg = types.SimpleNamespace(pool=None, close=AsyncMock())

    async def init(self):
        pass

    def get(self, key, default=None):
        return default

    async def close(self):
        pass

    @property
    def pg(self):
        return self._pg


class _ShutdownAwareServer:
    """Завершает `serve()` только по `should_exit` (как uvicorn)."""

    def __init__(self):
        self.should_exit = False

    async def serve(self):
        while not self.should_exit:
            await asyncio.sleep(0.01)


class _TinyASGIApp:
    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-length", b"2")]})
            await send({"type": "http.response.body", "body": b"ok"})


def _main_mocks(bot, monkeypatch, *, polling=None):
    """Моки инфраструктуры `bot.main()`; `polling=None` → НАСТОЯЩИЙ aiogram."""
    if polling is not None:
        monkeypatch.setattr(bot.dp, "start_polling", polling)
    monkeypatch.setenv("WEB_PORT", "0")
    monkeypatch.setattr(bot, "ConfigCache", lambda **kw: _FakeCache())
    monkeypatch.setattr(bot, "on_startup", AsyncMock())
    monkeypatch.setattr(bot, "create_app",
                        lambda cache, control=None: _TinyASGIApp())
    monkeypatch.setattr(bot, "uvicorn",
                        types.SimpleNamespace(
                            Server=lambda cfg: _ShutdownAwareServer(),
                            Config=lambda *a, **kw: None))
    monkeypatch.setattr(bot.ControlService, "flag_file_exists",
                        classmethod(lambda cls, *a, **k: False))


def _aiogram_polling_tasks() -> list[asyncio.Task]:
    """Живые таски aiogram-polling (внутренняя `_polling` / внешняя)."""
    out = []
    for task in asyncio.all_tasks():
        name = getattr(task.get_coro(), "__qualname__", "")
        if "Dispatcher._polling" in name or "Dispatcher.start_polling" in name:
            out.append(task)
    return out


class _StubBotAPI(BaseHTTPRequestHandler):
    """Мини-заглушка Telegram Bot API: polling реальный, сеть — локальная."""

    protocol_version = "HTTP/1.1"

    def _send(self, obj) -> None:
        data = json.dumps(obj).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def _handle(self) -> None:
        n = int(self.headers.get("content-length") or 0)
        if n:
            self.rfile.read(n)
        method = self.path.rsplit("/", 1)[-1].split("?")[0]
        if method == "getUpdates":
            time.sleep(0.2)
            self._send({"ok": True, "result": []})
        elif method == "getMe":
            self._send({"ok": True, "result": {
                "id": 8802473181, "is_bot": True, "first_name": "Probe",
                "username": "probe_bot"}})
        else:
            self._send({"ok": True, "result": True})

    do_POST = _handle
    do_GET = _handle

    def log_message(self, *a) -> None:
        pass


class _StubServer:
    def __init__(self):
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubBotAPI)
        self.base = f"http://127.0.0.1:{self._srv.server_address[1]}"
        self._thread = threading.Thread(target=self._srv.serve_forever,
                                        daemon=True, name="inc01-stub-botapi")
        self._thread.start()

    def stop(self) -> None:
        self._srv.shutdown()


# ═══ 1. Процесс выходит сам после SIGTERM (живой сабпроцесс) ════════════════

def test_process_exits_within_bounded_time_after_sigterm(tmp_path):
    """Контракт остановки: реальный `bot.main()` + реальный SIGTERM → ПРОЦЕСС
    выходит сам в пределах бюджета (никакого «висит до SIGKILL»).

    В сабпроцессе открыт реальный SQLite `DatabaseService` (как `on_startup`
    прода) — без закрытия runtime-SQLite процесс не выходит НИКОГДА
    (aiosqlite worker-thread не демон), поэтому таймаут сабпроцесса = RED."""
    env = os.environ.copy()
    env.update({
        "ADMINBOT_SKIP_DOTENV": "1",
        "API_TOKEN": "123456:TEST_TOKEN_FOR_INC01_EXIT",
        "WEB_PORT": "0",
        "POSTGRES_DSN": "",
        "DB_PATH": str(tmp_path / "inc01_exit.db"),
        "PYTHONUNBUFFERED": "1",
    })
    for key in ("SENTRY_DSN", "LOGTAIL_SOURCE_TOKEN", "BETTERSTACK_HOST"):
        env.pop(key, None)

    budget = 30.0
    proc = subprocess.Popen(
        [sys.executable, CHILD], cwd=os.path.dirname(CHILD) + os.sep + "..",
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    t0 = time.monotonic()
    try:
        out, _ = proc.communicate(timeout=budget)
        exited = True
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        exited = False
    wall = time.monotonic() - t0
    tail = "\n".join((out or "").splitlines()[-25:])

    assert exited, (
        f"процесс не вышел за {budget:.0f}s после SIGTERM (SIGKILL) — "
        f"открытый aiosqlite-коннект держит интерпретатор:\n{tail}")
    assert proc.returncode == 0, f"rc={proc.returncode}:\n{tail}"
    assert "[shutdown] bye" in out, f"нет строки bye:\n{tail}"
    assert "[shutdown] runtime sqlite closed" in out, f"нет закрытия:\n{tail}"
    assert "sqlite running=False closed=True" in out, f"SQLite не закрыт:\n{tail}"
    # Измерение остановки: от SIGTERM до возврата main() (не только процесса).
    line = [ln for ln in out.splitlines()
            if ln.startswith("[child] SIGTERM→main() returned")]
    assert line, f"нет измерения остановки:\n{tail}"
    stop_s = float(line[0].split(":")[-1].strip().rstrip("s"))
    assert stop_s < 10.0, f"остановка {stop_s:.2f}s (бюджет 10s):\n{tail}"
    assert wall < budget


# ═══ 2. aiogram-polling остановлен штатно (без «осиротевших» тасок) ════════

@pytest.mark.asyncio
async def test_aiogram_polling_stopped_gracefully_no_orphan_task(
        monkeypatch, caplog):
    """Реальный aiogram-polling (локальная заглушка Bot API) + SIGTERM: после
    остановки внутренних `Dispatcher._polling`-тасок НЕ остаётся, «Polling
    stopped» идёт ДО `bye` (в прод-факте — через 0.36 с ПОСЛЕ `bye`, из
    cleanup `asyncio.run`: polling продолжал ходить в Telegram)."""
    from aiogram.client.telegram import TelegramAPIServer

    bot, saved = _bot_module(monkeypatch)
    stub = _StubServer()
    try:
        bot.bot.session.api = TelegramAPIServer.from_base(stub.base)
        _main_mocks(bot, monkeypatch)          # polling НЕ подменяем

        main_task = asyncio.create_task(bot.main())
        for _ in range(300):
            await asyncio.sleep(0.05)
            if bot.status.state == "polling":
                break
        assert bot.status.state == "polling", "main() не поднялся"
        # Дать внутренней `_polling` реально начать long-poll.
        for _ in range(100):
            await asyncio.sleep(0.05)
            if _aiogram_polling_tasks():
                break
        assert _aiogram_polling_tasks(), "aiogram-polling не стартовал"

        with caplog.at_level(logging.INFO):
            signal.raise_signal(signal.SIGTERM)
            await asyncio.wait_for(main_task, timeout=30.0)

        assert not _aiogram_polling_tasks(), (
            "после остановки остались таски aiogram-polling — внутренняя "
            "`_polling` продолжает опрашивать Telegram")
        session = getattr(bot.bot.session, "_session", None)
        assert session is None or session.closed, "сессия бота не закрыта"
        text = caplog.text
        assert "[shutdown] polling stop | graceful=True" in text, text[-2000:]
        assert "Polling stopped" in text and "[shutdown] bye" in text
        assert text.index("Polling stopped") < text.index("[shutdown] bye"), (
            "остановка polling должна завершаться ДО `bye`")
    finally:
        stub.stop()
        _restore_signals(saved)
        sys.modules.pop("bot", None)


# ═══ 3. Helper остановки polling: bounded + fallback на cancel ═════════════

@pytest.mark.asyncio
async def test_stop_polling_helper_bounded_and_fallback(monkeypatch):
    """`_stop_polling_task`: штатный путь ограничен бюджетом; недоступный/
    зависший `stop_polling` не блокирует остановку (fallback `cancel()`)."""
    bot, saved = _bot_module(monkeypatch)
    try:
        async def _never():
            await asyncio.sleep(3600)

        async def _fast():
            return None

        async def _raise():
            raise RuntimeError("Polling is not started")

        class _FakeDP:
            def __init__(self, impl):
                self._impl = impl

            async def stop_polling(self):
                await self._impl()

        # (а) штатный путь: stop_polling завершается быстро
        polling = asyncio.create_task(asyncio.sleep(3600))
        ok = await bot._stop_polling_task(_FakeDP(_fast), polling,
                                          budget=2.0)
        assert ok is True
        polling.cancel()
        with pytest.raises(asyncio.CancelledError):
            await polling

        # (б) polling не стартовал (RuntimeError) → False, вызывающий отменяет
        polling = asyncio.create_task(asyncio.sleep(3600))
        t0 = time.monotonic()
        ok = await bot._stop_polling_task(_FakeDP(_raise), polling, budget=2.0)
        assert ok is False and time.monotonic() - t0 < 1.0
        polling.cancel()
        with pytest.raises(asyncio.CancelledError):
            await polling

        # (в) зависший stop_polling → bounded (бюджет), затем cancel
        polling = asyncio.create_task(asyncio.sleep(3600))
        t0 = time.monotonic()
        ok = await bot._stop_polling_task(_FakeDP(_never), polling, budget=0.3)
        elapsed = time.monotonic() - t0
        assert ok is False and 0.25 <= elapsed < 2.0, elapsed
        polling.cancel()
        with pytest.raises(asyncio.CancelledError):
            await polling

        # (г) polling уже завершён — гасить нечего
        done = asyncio.create_task(asyncio.sleep(0))
        await done
        assert await bot._stop_polling_task(_FakeDP(_raise), done) is True
    finally:
        _restore_signals(saved)
        sys.modules.pop("bot", None)


# ═══ 4. Наблюдаемость: закрытый ран не «running» ═══════════════════════════

@pytest.mark.asyncio
async def test_closed_orphan_run_has_terminal_event_and_ui_not_running(
        tmp_path, caplog, monkeypatch):
    """Ран, закрытый финализатором (орфан-close), обязан иметь ТЕРМИНАЛЬНОЕ
    событие: durable FAILED и дериват Oversight («running» из `mca_events`)
    согласованы. RED-состояние воспроизводится первым ассертом: до закрытия
    ран честно читается «running» (START без терминала) — ровно прод-факт."""
    from services import pipeline_analytics

    _events_flag_on(monkeypatch)
    db = await _fresh_db(tmp_path, "obs.db")
    run_id = "orphan-obs-1"
    await db.create_summary_run(run_id=run_id, chat_id=CHAT, state="CREATED",
                                manual=False, created_at=int(time.time()) - 3600)
    # START-событие прогона (как его пишет реальный прогон) + durable-запись.
    pipeline_events.summary_start(run_id, chat_id=CHAT, mode="cron",
                                  manual=False)
    assert await mca.flush_events(db) >= 1

    before = await pipeline_analytics.collect_run(db, run_id)
    assert before["running"] is True, "предусловие: ран без терминала — running"

    with caplog.at_level(logging.INFO):
        closed = await srs.close_orphan_runs(db, grace_seconds=0.0)
    assert [c["run_id"] for c in closed] == [run_id]

    row = await _run_row(db, run_id)
    assert row["state"] == "FAILED"
    assert row["publication_status"] in (None, "pending")
    cursor = await db.db.execute(
        "SELECT stage, status, reason_code FROM summary_run_stages "
        "WHERE run_id = ?", (run_id,))
    stages = [dict(r) for r in await cursor.fetchall()]
    assert any(s["stage"] == "run" and s["status"] == "failed"
               and s["reason_code"] == "orphan_no_owner" for s in stages)

    # Терминальное событие видно ДЕРИВАТУ UI (mca_events), а не только БД.
    assert await mca.flush_events(db) >= 1, "терминальное событие не эмитилось"
    after = await pipeline_analytics.collect_run(db, run_id)
    assert after["running"] is False, (
        "закрытый ран всё ещё читается «running» (нет SUMMARY_RUN_DONE)")
    cursor = await db.db.execute(
        "SELECT event_name, status, chat_id FROM mca_events "
        "WHERE pipeline_run_id = ? AND event_name = 'SUMMARY_RUN_DONE'",
        (run_id,))
    done_rows = [dict(r) for r in await cursor.fetchall()]
    assert len(done_rows) == 1, done_rows
    assert done_rows[0]["status"] == "failed"
    assert int(done_rows[0]["chat_id"]) == CHAT
    # Список runs (§61.10) строится из тех же DONE-событий.
    entries = await pipeline_analytics.collect_runs_list(db)
    assert [e["run_id"] for e in entries] == [run_id]
    assert entries[0]["health"] == "failed"
    await db.close()


@pytest.mark.asyncio
async def test_stale_close_emits_terminal_event_too(tmp_path, monkeypatch):
    """Тот же контракт для второго пути закрытия (stale-closer в начале
    прогона): закрытый ран получает терминальное событие, `publication_status`
    не тронут (повторной отправки не возникает)."""
    from services import pipeline_analytics

    _events_flag_on(monkeypatch)
    db = await _fresh_db(tmp_path, "obs2.db")
    run_id = "stale-obs-1"
    await db.create_summary_run(run_id=run_id, chat_id=CHAT, state="CREATED",
                                manual=False, created_at=int(time.time()) - 3600)
    pipeline_events.summary_start(run_id, chat_id=CHAT, mode="cron",
                                  manual=False)
    await mca.flush_events(db)
    assert await srs.close_stale_run(db, run_id, reason_code="stale_no_window")
    await mca.flush_events(db)
    assert (await pipeline_analytics.collect_run(db, run_id))["running"] is False
    row = await _run_row(db, run_id)
    assert row["state"] == "FAILED"
    assert row["publication_status"] in (None, "pending")
    await db.close()


# ═══ 5. Диагностика: открытые SQLite-коннекты видны в журнале ══════════════

@pytest.mark.asyncio
async def test_leftover_sqlite_guard_reports_open_connections(monkeypatch):
    """Если соединение осталось открытым, причина 60-секундного зависания
    должна быть ВИДНА в журнале (раньше — 60 с тишины после `bye`). Гвард
    read-only: чужие соединения не закрывает (владелец закрывает свои)."""
    import aiosqlite

    bot, saved = _bot_module(monkeypatch)
    try:
        # Базовая линия: в широком прогоне чужие коннекты могут быть открыты
        # (их закрывает session-finish conftest'а) — считаем дельту.
        before = bot._leftover_sqlite_connections()
        stray = await aiosqlite.connect(":memory:")
        assert stray._running is True and stray._thread.is_alive()
        assert bot._leftover_sqlite_connections() == before + 1
        await stray.close()
        assert bot._leftover_sqlite_connections() == before
    finally:
        _restore_signals(saved)
        sys.modules.pop("bot", None)
