"""INC-SUMMARY-01 (17.10.2026) — graceful shutdown и финализатор Summary-ранов.

Прод-инцидент: прогон `da33f05d…` стартовал 01:00:06, деплой прислал SIGTERM
в 01:00:08, а через 60 с (`TimeoutStopSec`) systemd добил процесс SIGKILL'ом.
Терминал прогона пишется только в `finally` корутины — SIGKILL его не даёт,
`on_shutdown` не исполнялся вовсе (в журнале нет «Bot shutting down...»), а
финализатора нетерминальных `summary_runs` не было → UI/Oversight вечно
показывал «running» (фантом). Причина хронического SIGKILL: SIGTERM-хендлер
переустанавливал aiogram (`start_polling` → `handle_signals=True` ПОСЛЕ
uvicorn'а), `server.should_exit` не выставлялся, `main()` навсегда оставался в
`await server.serve()`, а `stop_event` никто не ожидал.

Контракт полосы (наблюдаемое поведение, не внутренности):
  * SIGTERM во время in-flight прогона → процесс останавливается САМ в
    пределах бюджета дренажа (`SUMMARY_SHUTDOWN_DRAIN_SECONDS`, default 20 с),
    ран получает терминал с причиной (`FAILED`/`shutdown`), повторной
    публикации нет;
  * aiogram НЕ переустанавливает сигналы (`handle_signals=False`);
  * после остановки новый прогон не начинается (run-row не создаётся);
  * дренаж пустой системы — мгновенный; дренаж под висящим обслуживанием
    памяти — bounded abort (задача НЕ продолжается после отмены);
  * два чата в полёте → финализируются оба;
  * startup-recovery: ран без окна и без живого владельца → FAILED/reason,
    `publication_status` не тронут; ран С окном → докатывается (тот же
    run_id, ровно одна отправка); свежий ран (младше grace) не трогается.

TEST-LIFECYCLE: REGRESSION owner=INC-SUMMARY-01/shutdown
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import signal
import sys
import time
import types
from ast import (AsyncFunctionDef, Attribute, Call, Constant, FunctionDef,
                 Name, parse, walk)
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import summary_run_store as srs
from services.database import DatabaseService
from services.smartmodule_concurrency import ChatConcurrencyPool
from services.summary_generator import SummaryGenerator
from services.summary_scheduler import (SummarySchedulerService,
                                        shutdown_drain_seconds)
from services.summary_xml import XmlGroundingBuilder
from tests.test_summary_generator import FakeLLM, _row

# Прод-дефолты durable-контура (зона ASAP 4.1): иначе session-fixture глушит
# `SUMMARY_RUN_DURABLE_ENABLED` и durable-поверхность отсутствует по
# построению — а инцидент 17.10 наблюдался на прод-дефолтах.
pytestmark = pytest.mark.asap41

CHAT = -100777
CHAT_B = -100888
CHAT_C = -100999


# ── helpers ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_live_registry():
    """Изоляция in-memory реестров живых владельцев между тестами."""
    from services import summary_generator as sg
    sg._LIVE_RUN_IDS.clear()
    sg._LIVE_RUN_TASKS.clear()
    yield
    sg._LIVE_RUN_IDS.clear()
    sg._LIVE_RUN_TASKS.clear()


@pytest.fixture
def bot_module(monkeypatch):
    """Реальный модуль `bot` (reload-паттерн `test_bot_main_flow`) + откат
    обработчиков сигналов после теста (main() их переустанавливает)."""
    import importlib

    import config.settings as settings_mod

    monkeypatch.setenv("API_TOKEN", "123456:TEST_TOKEN_FOR_INC01_SHUTDOWN")
    monkeypatch.delenv("LOGTAIL_SOURCE_TOKEN", raising=False)
    saved = {sig: signal.getsignal(sig)
             for sig in (signal.SIGINT, signal.SIGTERM)}
    sys.modules.pop("bot", None)
    importlib.reload(settings_mod)
    # `.env` (загружается config.settings) несёт прод-SENTRY_DSN: тест логирует
    # ERROR-терминал абортированного прогона и без этого отправил бы события в
    # прод-Sentry. Тест обязан быть локальным.
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    import bot
    yield bot
    sys.modules.pop("bot", None)
    for sig, handler in saved.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError, RuntimeError):  # pragma: no cover
            pass


async def _fresh_db(tmp_path, name) -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _runs_for_chat(db, chat_id) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT run_id, chat_id, state, publication_status, source_ref, "
        "window_from, window_to FROM summary_runs WHERE chat_id = ?",
        (int(chat_id),))
    return [dict(r) for r in await cursor.fetchall()]


async def _stages(db, run_id) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT stage, status, reason_code FROM summary_run_stages "
        "WHERE run_id = ? ORDER BY id", (str(run_id),))
    return [dict(r) for r in await cursor.fetchall()]


class _SlowMemory:
    """Память генератора, чьё обслуживание «висит» (in-flight
    pre-generation, как `_compress_purge_extract_only` в инциденте)."""

    def __init__(self, db, *, delay=30.0, rows=None, expect_entered=1):
        self.db = db
        self.delay = delay
        self.rows = [_row()] if rows is None else rows
        self.entered = asyncio.Event()
        self._entered = 0
        self._expect = max(1, int(expect_entered))
        self.completed = False
        self.window_reads = 0

    async def compress_and_purge(self, chat_id):
        self._entered += 1
        if self._entered >= self._expect:
            self.entered.set()
        await asyncio.sleep(self.delay)
        self.completed = True          # НЕ исполняется при отмене

    async def get_window_messages(self, chat_id):
        self.window_reads += 1
        return self.rows

    async def search_long_term(self, chat_id, keywords, limit):
        return []

    async def vector_search(self, chat_id, query, limit):
        return []

    async def get_graph_facts(self, chat_id, rows, keywords):
        return []

    async def memorize_facts(self, chat_id, raw_text, source_type):
        return None

    async def get_rag_context(self, chat_id, query, *, sort_by_timestamp=False):
        return ""


def _gen(memory, bot=None) -> SummaryGenerator:
    gen = SummaryGenerator(
        memory, XmlGroundingBuilder(), FakeLLM(),
        bot if bot is not None else AsyncMock(),
        concurrency_pool=ChatConcurrencyPool())
    # Legacy-контур (OFF hybrid) — предмет этих тестов, а не hybrid-путь.
    gen._hybrid_l2_enabled = AsyncMock(return_value=False)
    return gen


class _FakeCache:
    def __init__(self):
        self.pg_available = False
        self.is_initialized = False
        self._pg = types.SimpleNamespace(pool=None, close=AsyncMock())
        self.init_calls = 0
        self.closed = False

    async def init(self):
        self.init_calls += 1
        self.is_initialized = True

    def get(self, key, default=None):
        return default

    async def close(self):
        self.closed = True

    @property
    def pg(self):
        return self._pg


class _ShutdownAwareServer:
    """Сервер, завершающий `serve()` ТОЛЬКО по `should_exit` (как uvicorn):
    если shutdown не выставит флаг — тест упадёт по таймауту, а не «пройдёт»."""

    def __init__(self):
        self.should_exit = False

    async def serve(self):
        while not self.should_exit:
            await asyncio.sleep(0.01)


class _TinyASGIApp:
    """Минимальное ASGI-приложение для НАСТОЯЩЕГО uvicorn (lifespan + http)."""

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


def _main_mocks(bot, monkeypatch, polling_calls, *, real_uvicorn):
    """Моки инфраструктуры `bot.main()`: сеть/БД/PG не поднимаются."""
    async def fake_polling(*args, **kwargs):
        polling_calls.append(kwargs)
        while True:
            await asyncio.sleep(0.05)

    monkeypatch.setenv("WEB_PORT", "0")
    monkeypatch.setattr(bot, "ConfigCache", lambda **kw: _FakeCache())
    monkeypatch.setattr(bot, "on_startup", AsyncMock())
    monkeypatch.setattr(bot.dp, "start_polling", fake_polling)
    monkeypatch.setattr(bot, "create_app",
                        lambda cache, control=None: _TinyASGIApp())
    monkeypatch.setattr(bot.ControlService, "flag_file_exists",
                        classmethod(lambda cls, *a, **k: False))
    if not real_uvicorn:
        monkeypatch.setattr(
            bot, "uvicorn",
            types.SimpleNamespace(Server=lambda cfg: _ShutdownAwareServer(),
                                  Config=lambda *a, **kw: None))


async def _await_polling_started(bot, polling_calls, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        if polling_calls and bot.status.state == "polling":
            return
    raise AssertionError("polling не стартовал (main не поднялся)")


async def _sigterm_scenario(bot, tmp_path, monkeypatch, caplog, *,
                            real_uvicorn: bool):
    """Общий сценарий: in-flight Summary-прогон + SIGTERM процессу.

    Возвращает (elapsed_s, db, memory, send_mock, run_task, caplog_text)."""
    db = await _fresh_db(tmp_path, "sigterm.db")
    memory = _SlowMemory(db, delay=30.0)
    send_mock = AsyncMock()
    gen = _gen(memory, bot=send_mock)
    bot._summary_service = SummarySchedulerService(gen, db)

    run_task = asyncio.create_task(gen.generate_and_send(CHAT))
    await asyncio.wait_for(memory.entered.wait(), timeout=10.0)
    assert await _runs_for_chat(db, CHAT), "run-row не создана до SIGTERM"

    polling_calls: list[dict] = []
    _main_mocks(bot, monkeypatch, polling_calls, real_uvicorn=real_uvicorn)

    main_task = asyncio.create_task(bot.main())
    await _await_polling_started(bot, polling_calls)

    # aiogram обязан НЕ переустанавливать SIGTERM-хендлер (корень SIGKILL
    # через 60 с: его хендлер выигрывал у uvicorn'а и не выставлял
    # should_exit). Проверяем ДО сигнала — иначе тест бессмыслен.
    assert polling_calls[0].get("handle_signals") is False, (
        "start_polling обязан вызываться с handle_signals=False")
    assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL, (
        "SIGTERM-хендлер не установлен — сигнал убил бы процесс")

    t0 = time.perf_counter()
    with caplog.at_level(logging.INFO):
        signal.raise_signal(signal.SIGTERM)     # настоящий SIGTERM процессу
        await asyncio.wait_for(main_task, timeout=60.0)
        elapsed = time.perf_counter() - t0
    return elapsed, db, memory, send_mock, run_task


# ═══ 1. SIGTERM во время in-flight прогона ═════════════════════════════════

@pytest.mark.asyncio
async def test_sigterm_during_inflight_run_terminal_state_bounded_exit(
        bot_module, tmp_path, monkeypatch, caplog):
    """Прод-сценарий 17.10 (настоящий uvicorn + настоящий SIGTERM процессу):
    ран получает терминал с причиной, повторной публикации нет, остановка
    укладывается в бюджет дренажа (никакого SIGKILL через 60 с)."""
    bot = bot_module
    elapsed, db, memory, send_mock, run_task = await _sigterm_scenario(
        bot, tmp_path, monkeypatch, caplog, real_uvicorn=True)

    budget = shutdown_drain_seconds()
    assert elapsed < budget + 5.0, (
        f"остановка {elapsed:.2f}s не уложилась в бюджет {budget}s")

    runs = await _runs_for_chat(db, CHAT)
    assert len(runs) == 1, "появился лишний run-row"
    assert runs[0]["state"] == "FAILED", "нетерминальный ран после SIGTERM"
    assert runs[0]["publication_status"] not in ("published", "publishing")
    assert send_mock.send_message.await_count == 0, "публикация при остановке!"
    stages = await _stages(db, runs[0]["run_id"])
    assert any(s["stage"] == "run" and s["reason_code"] == "shutdown"
               for s in stages), "терминал без причины shutdown"
    assert run_task.done(), "таск прогона не завершён"
    assert memory.completed is False, "обслуживание памяти продолжилось"
    # Фазы остановки видны в журнале одной строкой каждая.
    assert "phase=stopping" in caplog.text
    assert "phase=draining" in caplog.text
    assert "phase=finalized" in caplog.text
    assert "[shutdown] bye" in caplog.text
    await db.close()


@pytest.mark.asyncio
async def test_sigterm_stops_process_via_our_handler_without_uvicorn_signals(
        bot_module, tmp_path, monkeypatch, caplog):
    """Тот же сценарий с фейковым сервером (завершается только по
    `should_exit`): остановку обязан инициировать НАШ хендлер
    (`request_shutdown` → stop_event + should_exit). Без фикса тест висел бы."""
    bot = bot_module
    elapsed, db, memory, send_mock, run_task = await _sigterm_scenario(
        bot, tmp_path, monkeypatch, caplog, real_uvicorn=False)

    assert elapsed < shutdown_drain_seconds() + 5.0
    runs = await _runs_for_chat(db, CHAT)
    assert [r["state"] for r in runs] == ["FAILED"]
    assert send_mock.send_message.await_count == 0
    assert bot.status.state == "stopped"
    await db.close()


def test_install_signal_handlers_registers_request_shutdown(bot_module):
    """Хендлер сигналов = `request_shutdown` (stop_event + should_exit), а не
    «просто stop_event.set», который ничего не останавливал."""
    bot = bot_module
    called: list[int] = []

    class _FakeLoop:
        def __init__(self, fail=False):
            self.calls = []
            self.fail = fail

        def add_signal_handler(self, sig, cb, *args):
            if self.fail:
                raise NotImplementedError
            self.calls.append((sig, cb))

    loop = _FakeLoop()
    installed = bot._install_signal_handlers(loop, lambda: called.append(1))
    assert installed == (int(signal.SIGINT), int(signal.SIGTERM))
    assert [sig for sig, _cb in loop.calls] == [signal.SIGINT, signal.SIGTERM]
    loop.calls[0][1]()
    assert called == [1]


def test_install_signal_handlers_windows_fallback(bot_module, monkeypatch):
    """Windows-дев (нет `add_signal_handler`): тот же хендлер ставится через
    `signal.signal` + `call_soon_threadsafe` — процесс всё равно останавливается."""
    bot = bot_module
    saved = {sig: signal.getsignal(sig)
             for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        loop = types.SimpleNamespace(
            add_signal_handler=lambda *a, **kw: (_ for _ in ()).throw(
                NotImplementedError),
            call_soon_threadsafe=lambda cb: cb())
        called: list[int] = []
        installed = bot._install_signal_handlers(
            loop, lambda: called.append(1))
        assert installed == (int(signal.SIGINT), int(signal.SIGTERM))
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not signal.SIG_DFL
        handler(signal.SIGTERM, None)      # эмуляция доставки сигнала
        assert called == [1]
    finally:
        for sig, handler in saved.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError, RuntimeError):  # pragma: no cover
                pass


# ═══ 2. Дренаж: терминал, причина, bounded abort ═══════════════════════════

@pytest.mark.asyncio
async def test_drain_finalizes_inflight_run_reason_shutdown_no_send(
        tmp_path, caplog):
    """Bounded drain: in-flight прогон (внутри обслуживания памяти) отменяется,
    получает терминал FAILED/reason=shutdown, публикации не было, остановка
    быстрая; следующий прогон (новый процесс) публикует ровно один раз."""
    db = await _fresh_db(tmp_path, "drain.db")
    memory = _SlowMemory(db, delay=30.0)
    send_mock = AsyncMock()
    gen = _gen(memory, bot=send_mock)

    run_task = asyncio.create_task(gen.generate_and_send(CHAT))
    await asyncio.wait_for(memory.entered.wait(), timeout=10.0)
    assert gen._pool._active.get(CHAT, 0) > 0 if hasattr(
        gen._pool, "_active") else True          # слот чата занят прогоном

    gen.request_stop()
    with caplog.at_level(logging.INFO):
        t0 = time.perf_counter()
        stats = await gen.abort_in_flight(timeout=5.0)
        elapsed = time.perf_counter() - t0

    assert elapsed < 5.0, f"дренаж не уложился в бюджет: {elapsed:.2f}s"
    assert stats["in_flight"] == 1 and stats["cancelled"] == 1
    assert stats["finalized"] == 1 and stats["left"] == 0
    assert memory.completed is False, "обслуживание памяти продолжилось после abort"
    assert run_task.done() and run_task.cancelled()
    assert send_mock.send_message.await_count == 0
    assert "phase=draining" in caplog.text and "phase=finalized" in caplog.text

    runs = await _runs_for_chat(db, CHAT)
    assert len(runs) == 1 and runs[0]["state"] == "FAILED"
    assert runs[0]["publication_status"] not in ("published", "publishing")
    stages = await _stages(db, runs[0]["run_id"])
    assert any(s["stage"] == "run" and s["reason_code"] == "shutdown"
               for s in stages)
    assert not gen.accepting_runs()

    # Догон в НОВОМ процессе: тот же чат, новый run_id, ровно одна отправка
    # (абортированный ран не «резюмится» — дубля публикации нет).
    gen2 = _gen(_SlowMemory(db, delay=0.0), bot=send_mock)
    await gen2.generate_and_send(CHAT)
    runs = await _runs_for_chat(db, CHAT)
    assert len(runs) == 2
    fresh = [r for r in runs if r["run_id"] != runs[0]["run_id"]
             or r["state"] != "FAILED"]
    assert len(fresh) == 1 and fresh[0]["state"] in ("DONE", "DEGRADED")
    assert send_mock.send_message.await_count == 1
    await db.close()


@pytest.mark.asyncio
async def test_drain_idle_is_fast(tmp_path, caplog):
    """Пустая система: дренаж мгновенный (никакого ожидания бюджета)."""
    db = await _fresh_db(tmp_path, "idle.db")
    gen = _gen(_SlowMemory(db, delay=0.0))
    gen.request_stop()
    with caplog.at_level(logging.INFO):
        t0 = time.perf_counter()
        stats = await gen.abort_in_flight(timeout=20.0)
        elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"пустой дренаж занял {elapsed:.2f}s"
    assert stats == {"in_flight": 0, "cancelled": 0, "finalized": 0, "left": 0,
                     "elapsed_s": stats["elapsed_s"]}
    assert "phase=draining | in_flight=0" in caplog.text
    await db.close()


@pytest.mark.asyncio
async def test_drain_two_chats_in_flight_both_finalized(tmp_path, caplog):
    """Два чата в полёте одновременно → финализируются ОБА (по одной
    терминальной записи на ран, ни одной публикации)."""
    db = await _fresh_db(tmp_path, "two.db")
    memory = _SlowMemory(db, delay=30.0, expect_entered=2)
    send_mock = AsyncMock()
    gen = _gen(memory, bot=send_mock)

    tasks = [asyncio.create_task(gen.generate_and_send(chat))
             for chat in (CHAT, CHAT_B)]
    await asyncio.wait_for(memory.entered.wait(), timeout=10.0)
    gen.request_stop()
    with caplog.at_level(logging.INFO):
        stats = await gen.abort_in_flight(timeout=5.0)

    assert stats["in_flight"] == 2 and stats["cancelled"] == 2
    assert all(t.done() for t in tasks)
    assert send_mock.send_message.await_count == 0
    for chat in (CHAT, CHAT_B):
        runs = await _runs_for_chat(db, chat)
        assert [r["state"] for r in runs] == ["FAILED"], f"чат {chat}"
        stages = await _stages(db, runs[0]["run_id"])
        assert any(s["reason_code"] == "shutdown" for s in stages)
    await db.close()


@pytest.mark.asyncio
async def test_new_run_refused_after_stop(tmp_path, caplog):
    """После остановки новый прогон не начинается: run-row не создаётся,
    отправки нет (честный отказ вместо оборванного рана)."""
    db = await _fresh_db(tmp_path, "refuse.db")
    send_mock = AsyncMock()
    gen = _gen(_SlowMemory(db, delay=0.0), bot=send_mock)
    gen.request_stop()
    assert gen.accepting_runs() is False
    with caplog.at_level(logging.INFO):
        await gen.generate_and_send(CHAT)
    assert await _runs_for_chat(db, CHAT) == []
    assert send_mock.send_message.await_count == 0
    assert "new run refused" in caplog.text
    await db.close()


@pytest.mark.asyncio
async def test_stop_accepting_shuts_scheduler_and_tick_skips(tmp_path, caplog):
    """`stop_accepting` снимает планировщик и генератор; тик, попавший в окно
    остановки, не начинает прогонов. Повторный вызов идемпотентен."""
    db = await _fresh_db(tmp_path, "stop.db")
    gen = _gen(_SlowMemory(db, delay=0.0))
    service = SummarySchedulerService(gen, db)
    service.start()
    with caplog.at_level(logging.INFO):
        await service.stop_accepting()
    assert gen.accepting_runs() is False
    assert service._scheduler.running is False
    assert "phase=stopping" in caplog.text
    await service.stop_accepting()          # идемпотентно
    await service.shutdown()                # идемпотентно, не падает

    gen2 = MagicMock()
    gen2.accepting_runs = MagicMock(return_value=False)
    service2 = SummarySchedulerService(gen2, db)
    await service2._tick()
    assert gen2.generate_and_send.call_count == 0
    await db.close()


# ═══ 3. Startup-recovery: орфан-раны на старте процесса ════════════════════

@pytest.mark.asyncio
async def test_startup_recovery_closes_orphan_without_window(tmp_path, caplog):
    """Орфан без окна (прод-тип: процесс убит SIGKILL'ом) → FAILED/reason,
    `publication_status` НЕ тронут; ран С окном и свежий ран не трогаются."""
    db = await _fresh_db(tmp_path, "orphan.db")
    old_ts = int(time.time()) - 3600
    await db.create_summary_run(run_id="orphan-old", chat_id=CHAT,
                                state="CREATED", manual=False,
                                created_at=old_ts)
    await db.create_summary_run(run_id="with-window", chat_id=CHAT_B,
                                state="SOURCE_READY", manual=False,
                                created_at=old_ts)
    await db.update_summary_run_state("with-window", "SOURCE_READY",
                                      window_from=1_700_000_000,
                                      window_to=1_700_010_000,
                                      source_ref="sr-1")
    await db.create_summary_run(run_id="fresh", chat_id=CHAT_C,
                                state="CREATED", manual=False,
                                created_at=int(time.time()))
    before = {r["run_id"]: r for r in
              await _runs_for_chat(db, CHAT) + await _runs_for_chat(db, CHAT_B)
              + await _runs_for_chat(db, CHAT_C)}

    with caplog.at_level(logging.INFO):
        closed = await srs.close_orphan_runs(db, grace_seconds=60.0)

    assert [c["run_id"] for c in closed] == ["orphan-old"]
    assert closed[0]["closed"] is True
    orphan = (await _runs_for_chat(db, CHAT))[0]
    assert orphan["state"] == "FAILED"
    assert orphan["publication_status"] == before["orphan-old"]["publication_status"]
    stages = await _stages(db, "orphan-old")
    assert any(s["stage"] == "run" and s["status"] == "failed"
               and s["reason_code"] == "orphan_no_owner" for s in stages)
    # Ран с окном и свежий ран не тронуты (resume-контракт §21 / grace-окно).
    assert (await _runs_for_chat(db, CHAT_B))[0]["state"] == "SOURCE_READY"
    assert (await _runs_for_chat(db, CHAT_C))[0]["state"] == "CREATED"
    assert await _stages(db, "with-window") == []
    assert "SUMMARY_ORPHAN_RUN_CLOSED" in caplog.text
    assert "reason=has_window" in caplog.text
    assert "reason=within_grace" in caplog.text
    await db.close()


@pytest.mark.asyncio
async def test_startup_recovery_keeps_windowed_run_then_resumes_same_run_id(
        tmp_path, caplog):
    """Ран С окном на старте не закрывается: следующий прогон докатывает ТОТ
    ЖЕ run_id — ровно одна отправка (дубля публикации нет)."""
    db = await _fresh_db(tmp_path, "resume.db")
    await db.create_summary_run(run_id="run-win", chat_id=CHAT,
                                state="SOURCE_READY", manual=False,
                                created_at=int(time.time()) - 7200)
    await db.update_summary_run_state("run-win", "SOURCE_READY",
                                      window_from=1_700_000_000,
                                      window_to=1_700_010_000,
                                      source_ref="sr-1")
    closed = await srs.close_orphan_runs(db, grace_seconds=0.0)
    assert closed == []

    send_mock = AsyncMock()
    gen = _gen(_SlowMemory(db, delay=0.0), bot=send_mock)
    await gen.generate_and_send(CHAT)

    runs = await _runs_for_chat(db, CHAT)
    assert [r["run_id"] for r in runs] == ["run-win"]     # второй run_id не создан
    assert runs[0]["state"] in ("DONE", "DEGRADED")
    assert send_mock.send_message.await_count == 1
    await db.close()


@pytest.mark.asyncio
async def test_recover_orphan_helper_closes_and_logs(bot_module, tmp_path, caplog):
    """Функция, которую `on_startup` зовёт на старте: закрывает орфан и
    пишет честный итог в журнал."""
    db = await _fresh_db(tmp_path, "helper.db")
    await db.create_summary_run(run_id="orphan-1", chat_id=CHAT,
                                state="CREATED", manual=False,
                                created_at=int(time.time()) - 3600)
    with caplog.at_level(logging.INFO):
        await bot_module._recover_orphan_summary_runs(db)
    assert (await _runs_for_chat(db, CHAT))[0]["state"] == "FAILED"
    assert "startup recovery" in caplog.text
    assert "orphan-1" in caplog.text
    await db.close()


def test_shutdown_env_axes_fail_safe(monkeypatch):
    """Env-оси остановки — операторские ручки: default/валидное/мусор/floor."""
    from services.summary_run_store import orphan_grace_seconds
    from services.summary_scheduler import (SHUTDOWN_DRAIN_DEFAULT,
                                            shutdown_drain_seconds)

    monkeypatch.delenv("SUMMARY_SHUTDOWN_DRAIN_SECONDS", raising=False)
    assert shutdown_drain_seconds() == SHUTDOWN_DRAIN_DEFAULT
    monkeypatch.setenv("SUMMARY_SHUTDOWN_DRAIN_SECONDS", "5")
    assert shutdown_drain_seconds() == 5.0
    monkeypatch.setenv("SUMMARY_SHUTDOWN_DRAIN_SECONDS", "мусор")
    assert shutdown_drain_seconds() == SHUTDOWN_DRAIN_DEFAULT
    monkeypatch.setenv("SUMMARY_SHUTDOWN_DRAIN_SECONDS", "0")
    assert shutdown_drain_seconds() == 1.0            # floor
    monkeypatch.delenv("SUMMARY_ORPHAN_GRACE_SECONDS", raising=False)
    assert orphan_grace_seconds() == 30.0
    monkeypatch.setenv("SUMMARY_ORPHAN_GRACE_SECONDS", "0")
    assert orphan_grace_seconds() == 0.0
    monkeypatch.setenv("SUMMARY_ORPHAN_GRACE_SECONDS", "abc")
    assert orphan_grace_seconds() == 30.0


def test_bot_wiring_guard(bot_module):
    """Guard (проводка, не логика): `on_startup` обязан звать startup-recovery
    орфан-ранов, `on_shutdown` — дренаж Summary. Логика обеих функций покрыта
    поведенческими тестами выше."""
    tree = parse(inspect.getsource(bot_module))

    def _calls(func_name: str) -> set[str]:
        for node in walk(tree):
            if isinstance(node, (FunctionDef, AsyncFunctionDef)) \
                    and node.name == func_name:
                calls = {n.func.attr for n in walk(node)
                         if isinstance(n, Call)
                         and isinstance(n.func, Attribute)}
                calls |= {n.func.id for n in walk(node)
                          if isinstance(n, Call) and isinstance(n.func, Name)}
                return calls
        raise AssertionError(f"{func_name} не найден в bot.py")

    assert "_recover_orphan_summary_runs" in _calls("on_startup")
    assert "_drain_summary_runs" in _calls("on_shutdown")
    # handle_signals=False у polling (корень 60-секундного SIGKILL).
    flags = [kw.value.value for node in walk(tree)
             if isinstance(node, Call)
             and isinstance(node.func, Attribute)
             and node.func.attr == "start_polling"
             for kw in node.keywords
             if kw.arg == "handle_signals"
             and isinstance(kw.value, Constant)]
    assert flags == [False], f"start_polling handle_signals={flags}"
