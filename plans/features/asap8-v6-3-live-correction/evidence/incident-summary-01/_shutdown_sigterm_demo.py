"""INC-SUMMARY-01 — локальная демонстрация: SIGTERM во время in-flight
Summary-прогона (реальный `bot.main()` + реальный uvicorn + реальный сигнал).

Сценарий (повторяет прод-таймлайн 17.10, но без прода):
  1) прогон Summary входит в обслуживание памяти (in-flight pre-generation);
  2) процессу доставляется НАСТОЯЩИЙ SIGTERM (`signal.raise_signal`);
  3) ожидание: процесс останавливается сам в пределах бюджета дренажа
     (никакого SIGKILL через 60 с), ран получает терминал FAILED/reason=shutdown,
     повторной публикации нет.

Запуск (из корня репозитория):
    .venv\\Scripts\\python.exe plans/features/asap8-v6-3-live-correction/evidence/incident-summary-01/_shutdown_sigterm_demo.py

Скрипт — evidence-артефакт (не production-код): вся логика остановки/дренажа
берётся из продакшн-модулей (`bot.main`, `_install_signal_handlers`,
`SummaryGenerator.abort_in_flight`, `summary_run_store`), здесь только
сборка сценария и печать чисел.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import signal
import sys
import tempfile
import time
import types
from unittest.mock import AsyncMock

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)

LOGS: list[str] = []


class _ListHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            LOGS.append(f"{record.levelname} {record.name}: {record.getMessage()}")
        except Exception:  # pragma: no cover
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


async def main() -> int:
    workdir = tempfile.mkdtemp(prefix="inc01_shutdown_demo_")
    os.chdir(workdir)
    os.environ["API_TOKEN"] = "123456:TEST_TOKEN_FOR_INC01_DEMO"
    os.environ["WEB_PORT"] = "0"
    os.environ.pop("LOGTAIL_SOURCE_TOKEN", None)

    logging.getLogger().addHandler(_ListHandler())
    logging.getLogger().setLevel(logging.INFO)

    import config.settings as settings_mod
    importlib.reload(settings_mod)
    # `.env` (загружается config.settings) несёт прод-SENTRY_DSN — демо
    # обязано быть локальным (никаких событий в прод-Sentry).
    os.environ.pop("SENTRY_DSN", None)
    import bot

    from services.database import DatabaseService
    from services.smartmodule_concurrency import ChatConcurrencyPool
    from services.summary_generator import SummaryGenerator
    from services.summary_scheduler import (SummarySchedulerService,
                                            shutdown_drain_seconds)
    from services.summary_xml import XmlGroundingBuilder

    CHAT = -100777

    class _SlowMemory:
        """Обслуживание памяти «висит» (in-flight pre-generation)."""

        def __init__(self, db):
            self.db = db
            self.entered = asyncio.Event()
            self.completed = False

        async def compress_and_purge(self, chat_id):
            self.entered.set()
            await asyncio.sleep(30)
            self.completed = True

        async def get_window_messages(self, chat_id):
            return [{"id": 1, "user_id": 10, "timestamp": 1_700_000_000,
                     "author_name": "вася", "text": "привет-привет", "reply_to_id": None,
                     "media_type": "text"}]

        async def search_long_term(self, *a, **kw):
            return []

        async def vector_search(self, *a, **kw):
            return []

        async def get_graph_facts(self, *a, **kw):
            return []

        async def memorize_facts(self, *a, **kw):
            return None

        async def get_rag_context(self, *a, **kw):
            return ""

    class _FakeLLM:
        async def generate(self, messages, **kwargs):
            return "готовое саммари демо"

    db = DatabaseService(os.path.join(workdir, "demo.db"))
    await db.initialize()

    memory = _SlowMemory(db)
    send_mock = AsyncMock()
    gen = SummaryGenerator(memory, XmlGroundingBuilder(), _FakeLLM(), send_mock,
                           concurrency_pool=ChatConcurrencyPool())
    gen._hybrid_l2_enabled = AsyncMock(return_value=False)
    bot._summary_service = SummarySchedulerService(gen, db)

    run_task = asyncio.create_task(gen.generate_and_send(CHAT))
    await asyncio.wait_for(memory.entered.wait(), timeout=10.0)
    print(f"[demo] прогон в полёте (внутри обслуживания памяти), "
          f"run_task={run_task.get_name()}")

    polling_calls: list[dict] = []

    async def fake_polling(*args, **kwargs):
        polling_calls.append(kwargs)
        while True:
            await asyncio.sleep(0.05)

    bot.ConfigCache = lambda **kw: _FakeCache()
    bot.on_startup = AsyncMock()
    bot.dp.start_polling = fake_polling
    bot.create_app = lambda cache, control=None: _TinyASGIApp()
    bot.ControlService.flag_file_exists = classmethod(lambda cls, *a, **k: False)

    main_task = asyncio.create_task(bot.main())
    for _ in range(200):
        await asyncio.sleep(0.05)
        if polling_calls and bot.status.state == "polling":
            break
    assert polling_calls, "main() не поднялся"
    print(f"[demo] main() поднят (реальный uvicorn), "
          f"start_polling kwargs={polling_calls[0]}")
    handler = signal.getsignal(signal.SIGTERM)
    print(f"[demo] SIGTERM-хендлер до сигнала: {handler!r} "
          f"(не SIG_DFL: {handler is not signal.SIG_DFL})")
    assert handler is not signal.SIG_DFL, "хендлер не установлен — сигнал убил бы процесс"

    print(f"[demo] бюджет дренажа = {shutdown_drain_seconds()} с")
    t0 = time.perf_counter()
    signal.raise_signal(signal.SIGTERM)      # настоящий SIGTERM процессу
    await asyncio.wait_for(main_task, timeout=60.0)
    elapsed = time.perf_counter() - t0
    print(f"[demo] процесс остановился сам за {elapsed:.3f} с "
          f"(SIGKILL не потребовался)")

    cursor = await db.db.execute(
        "SELECT run_id, state, publication_status FROM summary_runs")
    runs = [dict(r) for r in await cursor.fetchall()]
    cursor = await db.db.execute(
        "SELECT stage, status, reason_code FROM summary_run_stages")
    stages = [dict(r) for r in await cursor.fetchall()]

    print(f"[demo] runs={runs}")
    print(f"[demo] stages={stages}")
    print(f"[demo] отправок сводки (bot.send_message): "
          f"{send_mock.send_message.await_count}")
    print(f"[demo] обслуживание памяти продолжилось после abort: {memory.completed}")
    print(f"[demo] run_task завершён: {run_task.done()}, "
          f"отменён: {run_task.cancelled()}")
    print("[demo] строки фаз остановки из журнала:")
    for line in LOGS:
        if "shutdown" in line or "SUMMARY_SHUTDOWN_DRAIN" in line \
                or "SUMMARY_RUN_ABORT" in line:
            print("    " + line)

    ok = (len(runs) == 1 and runs[0]["state"] == "FAILED"
          and runs[0]["publication_status"] not in ("published", "publishing")
          and send_mock.send_message.await_count == 0
          and any(s["reason_code"] == "shutdown" for s in stages)
          and memory.completed is False
          and elapsed < shutdown_drain_seconds())

    # ── Сценарий 2: пустая система (idle) — остановка тоже быстрая ─────────
    idle_gen = SummaryGenerator(_SlowMemory(db), XmlGroundingBuilder(),
                                _FakeLLM(), AsyncMock(),
                                concurrency_pool=ChatConcurrencyPool())
    idle_gen._hybrid_l2_enabled = AsyncMock(return_value=False)
    bot._summary_service = SummarySchedulerService(idle_gen, db)
    idle_polls: list[dict] = []

    async def idle_polling(*args, **kwargs):
        idle_polls.append(kwargs)
        while True:
            await asyncio.sleep(0.05)

    bot.dp.start_polling = idle_polling
    idle_main = asyncio.create_task(bot.main())
    for _ in range(200):
        await asyncio.sleep(0.05)
        if idle_polls and bot.status.state == "polling":
            break
    assert idle_polls, "idle main() не поднялся"
    t1 = time.perf_counter()
    signal.raise_signal(signal.SIGTERM)
    await asyncio.wait_for(idle_main, timeout=60.0)
    idle_elapsed = time.perf_counter() - t1
    print(f"[demo] пустая система (нет прогонов): остановка за "
          f"{idle_elapsed:.3f} с")
    ok = ok and idle_elapsed < shutdown_drain_seconds()
    await db.close()

    print(f"[demo] ИТОГ: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
