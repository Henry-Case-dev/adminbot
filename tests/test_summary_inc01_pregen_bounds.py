"""INC-SUMMARY-01 (17.10.2026) — границы pre-generation цепочки Summary.

Прод-инцидент 17.10 01:00:06: ран Summary висел 48+ мин (`RUNNING`, stages
0/0) на неограниченном обслуживании памяти
(`summary_memory._compress_purge_extract_only` — `while True` без общего
дедлайна/капа) и держал пермит пула чата + весь тик крона
(`max_instances=1`, последовательный обход чатов).

Проверяемый контракт (наблюдаемое поведение, не внутренности):
  * большая очередь GraphRAG → цикл выходит по капу/бюджету, обработано
    ≤ кап, остаток очереди НЕ удалён и остаётся `history_processed=0`,
    публикация сводки идёт;
  * зависшее обслуживание памяти → fail-soft skip с durable
    stage/reason (`memory_maintenance`/`skipped`/`deadline_exceeded`),
    публикация состоялась, ран не FAILED, пермит освобождён;
  * зависший чат не останавливает тик (остальные чаты обработаны);
  * рестарт с нетерминальным раном: без окна → FAILED/stale_no_window +
    НОВЫЙ run_id; с окном → resume ТОГО ЖЕ run_id; ровно одна отправка
    (дубль публикации невозможен);
  * конкурентные раны / таймаут пермита → чистый skip БЕЗ run-row,
    тик продолжается;
  * no-progress guard (та же пачка дважды) → стоп с причиной, без спина;
  * OFF `SUMMARY_PREGEN_BOUNDS_ENABLED` → прежний контур (ожидание слота
    без таймаута, кап/дедлайн/новые stage-строки не действуют).

TEST-LIFECYCLE: REGRESSION owner=INC-SUMMARY-01/<case>
"""
import asyncio
import dataclasses
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import Settings, settings
from services import summary_memory as sm
from services import summary_run_store as srs
from services.database import DatabaseService
from services.smartmodule_concurrency import ChatConcurrencyPool
from services.summary_generator import SummaryGenerator
from services.summary_scheduler import SummarySchedulerService
from services.summary_xml import XmlGroundingBuilder
from tests.test_summary_generator import FakeLLM, _row

# Прод-дефолты durable-контура (зона ASAP 4.1): тесты маркированы `asap41`,
# иначе session-fixture `_asap41_flags_off_by_default` глушит
# `SUMMARY_RUN_DURABLE_ENABLED` и durable-поверхность (stage-строки, run-row)
# отсутствует по построению — а инцидент 17.10 наблюдался на прод-дефолтах.
pytestmark = pytest.mark.asap41

CHAT = -100123
BUSY_CHAT = -100111
FREE_CHAT = -100222


# ── helpers ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_live_run_ids():
    """Изоляция in-memory набора живых владельцев run_id между тестами."""
    from services import summary_generator as sg
    sg._LIVE_RUN_IDS.clear()
    yield
    sg._LIVE_RUN_IDS.clear()


async def _fresh_db(tmp_path, name):
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _runs_for_chat(db, chat_id):
    cursor = await db.db.execute(
        "SELECT run_id, state, publication_status, source_ref, window_from, "
        "window_to FROM summary_runs WHERE chat_id = ?", (int(chat_id),))
    return [dict(r) for r in await cursor.fetchall()]


async def _count(db, chat_id, where):
    cursor = await db.db.execute(
        f"SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ? "
        f"AND {where}", (int(chat_id),))
    return int((await cursor.fetchone())["n"])


class _PermitStub:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


class _SelectivePool:
    """Слот ``busy_chat`` всегда занят (try_acquire → None); остальные чаты
    свободны. Фиксирует, каким путём шёл вызов (try_acquire/acquire)."""

    def __init__(self, busy_chat):
        self.busy_chat = busy_chat
        self.try_calls: list = []
        self.acquire_calls = 0

    async def try_acquire(self, chat_id, timeout=None):
        self.try_calls.append((chat_id, timeout))
        if chat_id == self.busy_chat:
            return None
        return _PermitStub()

    async def acquire(self, chat_id):
        self.acquire_calls += 1
        return _PermitStub()


class _GenMemory:
    """Память генератора: окно + durable db + настраиваемое обслуживание."""

    def __init__(self, rows=None, db=None, maintenance=None):
        self.rows = rows if rows is not None else [_row()]
        self.db = db
        self._maintenance = maintenance
        self.events: list = []

    async def compress_and_purge(self, chat_id):
        self.events.append("compress")
        if self._maintenance is not None:
            await self._maintenance(chat_id)

    async def get_window_messages(self, chat_id):
        self.events.append("window")
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


class _DelayedGraphLLM:
    """`generate_background` с задержкой (медленный, но живой провайдер)."""

    def __init__(self, delay=0.0, raw="[]"):
        self.delay = delay
        self.raw = raw
        self.calls = 0

    async def generate_background(self, messages, **kwargs):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.raw


def _gen(memory, bot=None, pool=None, llm=None):
    gen = SummaryGenerator(memory, XmlGroundingBuilder(),
                           llm or FakeLLM(), bot or AsyncMock(),
                           concurrency_pool=pool or ChatConcurrencyPool())
    # Legacy-контур (OFF hybrid) — предмет этих тестов, а не hybrid-путь.
    gen._hybrid_l2_enabled = AsyncMock(return_value=False)
    return gen


def _bare_memory(db):
    mm = sm.MemoryManager.__new__(sm.MemoryManager)
    mm.db = db
    mm._graph_batch_failures = {}
    return mm


def _seed_rows(db, chat_id, n, ts0):
    async def _seed():
        for i in range(n):
            await db.db.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, "
                "timestamp, media_type, author_name, is_forward, "
                "forward_source, tg_message_id, history_processed) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (7, int(chat_id), f"сообщение {i}", int(ts0) + i, "text",
                 "вася", 0, "", 9000 + i, 0))
        await db.db.commit()
    return _seed


# ═══ 1. Большая очередь GraphRAG: бюджет/кап + публикация идёт ═════════════

@pytest.mark.asyncio
async def test_large_graph_queue_bounded_then_publication_completes(
        tmp_path, monkeypatch, caplog):
    """Матрица «большая очередь GraphRAG»: реальный DatabaseService + медленный
    `generate_background` → цикл выходит по капу (обработано ≤ кап×batch),
    остаток очереди остаётся `history_processed=0` (НЕ удалён, не помечен), а
    публикация сводки тем же прогоном состоялась."""
    db = await _fresh_db(tmp_path, "queue.db")
    cutoff_ts = int(time.time()) - 40 * 86400
    await _seed_rows(db, CHAT, 30, cutoff_ts)()

    monkeypatch.setattr(sm, "settings", dataclasses.replace(
        settings, INFINITE_RETENTION=True, SUMMARY_COMPRESS_BATCH=5,
        FULL_MEMORY_RETENTION_DAYS=30))
    monkeypatch.setattr(Settings, "GRAPH_EXTRACT_MAX_CHUNKS", 1, raising=False)
    monkeypatch.setattr(Settings, "GRAPH_EXTRACT_TIMEOUT_SECONDS", 0.2,
                        raising=False)
    monkeypatch.setattr(Settings, "GRAPH_EXTRACT_MAX_ATTEMPTS", 1, raising=False)
    monkeypatch.setenv("SUMMARY_MEMORY_MAINT_MAX_BATCHES", "3")

    mm = _bare_memory(db)
    mm.llm = _DelayedGraphLLM(delay=0.0)

    t0 = time.perf_counter()
    with caplog.at_level(logging.INFO):
        await mm.compress_and_purge(CHAT)
    elapsed = time.perf_counter() - t0

    marked = await _count(db, CHAT, "history_processed = 1")
    remaining = await _count(db, CHAT, "history_processed = 0")
    assert elapsed < 5.0
    assert marked == 15                      # кап 3 батча × batch 5
    assert remaining == 15                   # остаток НЕ удалён и не помечен
    assert "reason=batch_cap_reached" in caplog.text

    # Публикация тем же прогоном (обслуживание памяти — не ворота публикации).
    bot = AsyncMock()
    gen = _gen(_GenMemory(rows=[_row()], db=db,
                          maintenance=mm._compress_purge_extract_only),
               bot=bot)
    await gen.generate_and_send(CHAT)
    assert bot.send_message.await_count == 1
    runs = await _runs_for_chat(db, CHAT)
    assert len(runs) == 1 and runs[0]["state"] in ("DONE", "DEGRADED")
    # Догон очереди следующим прогоном (данные не потеряны).
    assert await _count(db, CHAT, "history_processed = 0") == 0
    await db.close()


# ═══ 2. Зависшее обслуживание памяти → fail-soft skip + публикация ═════════

@pytest.mark.asyncio
async def test_hung_memory_maintenance_fail_soft_skip_publication_proceeds(
        tmp_path, monkeypatch, caplog):
    """Матрица «долгая память»: FakeMemory спит дольше hard-капа → skip со
    durable stage/reason, публикация состоялась, ран не FAILED, пермит
    освобождён, терминал записан."""
    db = await _fresh_db(tmp_path, "hang.db")
    monkeypatch.setenv("SUMMARY_MEMORY_MAINT_HARD_SECONDS", "0.1")

    async def _hang(chat_id):
        await asyncio.sleep(30)

    pool = ChatConcurrencyPool()
    bot = AsyncMock()
    gen = _gen(_GenMemory(rows=[_row()], db=db, maintenance=_hang),
               bot=bot, pool=pool)

    t0 = time.perf_counter()
    with caplog.at_level(logging.WARNING):
        await gen.generate_and_send(CHAT)
    elapsed = time.perf_counter() - t0

    assert elapsed < 5.0, "публикация не должна ждать обслуживание памяти"
    assert bot.send_message.await_count == 1
    assert "outcome=skipped | reason=deadline_exceeded" in caplog.text

    runs = await _runs_for_chat(db, CHAT)
    assert len(runs) == 1
    assert runs[0]["state"] in ("DONE", "DEGRADED")     # ран не FAILED
    stages = {r["stage"]: r for r in await srs.stage_history(
        db, runs[0]["run_id"])}
    assert stages["run_memory_maintenance"]["status"] == "skipped"
    assert stages["run_memory_maintenance"]["reason_code"] == "deadline_exceeded"
    assert stages["run_permit"]["status"] == "ok"
    assert stages["run_source_window"]["status"] == "ok"
    assert stages["run_source_window"]["started_at"] is not None
    assert stages["run"]["finished_at"] is not None      # терминал записан

    # Наблюдаемость: pre-generation стадии видны в СУЩЕСТВУЮЩЕЙ Analytics-
    # поверхности (liveness-карточки run'а из durable stage-строк) — вместо
    # прежних 0/0; новой UI не вводится.
    from services import pipeline_analytics as pa
    view = await pa.collect_run(db, runs[0]["run_id"])
    live_keys = {c["stage"] for c in (view.get("liveness") or [])}
    assert {"run_permit", "run_memory_maintenance",
            "run_source_window"} <= live_keys

    permit = await pool.try_acquire(CHAT, timeout=0.0)
    assert permit is not None, "пермит должен быть освобождён"
    permit.release()
    await db.close()


@pytest.mark.asyncio
async def test_red_off_path_publication_waits_for_memory(tmp_path, monkeypatch):
    """RED-эквивалент причины: без границ (OFF) публикация ЖДЁТ обслуживание
    памяти ровно столько, сколько оно длится; с границами (ON) укладывается в
    жёсткий бюджет и не ждёт."""
    db = await _fresh_db(tmp_path, "red.db")

    async def _slow(chat_id):
        await asyncio.sleep(1.5)

    monkeypatch.setenv("SUMMARY_PREGEN_BOUNDS_ENABLED", "0")
    bot = AsyncMock()
    gen = _gen(_GenMemory(rows=[_row()], db=db, maintenance=_slow), bot=bot)
    t0 = time.perf_counter()
    await gen.generate_and_send(CHAT)
    off_elapsed = time.perf_counter() - t0
    assert off_elapsed >= 1.4                    # публикация ждала память
    assert bot.send_message.await_count == 1

    monkeypatch.setenv("SUMMARY_PREGEN_BOUNDS_ENABLED", "1")
    monkeypatch.setenv("SUMMARY_MEMORY_MAINT_HARD_SECONDS", "0.1")

    async def _hang(chat_id):
        await asyncio.sleep(30)

    bot2 = AsyncMock()
    gen2 = _gen(_GenMemory(rows=[_row()], db=db, maintenance=_hang), bot=bot2)
    t0 = time.perf_counter()
    await gen2.generate_and_send(CHAT)
    on_elapsed = time.perf_counter() - t0
    assert on_elapsed < 2.0 and bot2.send_message.await_count == 1
    await db.close()


# ═══ 3. Тик крона: зависший чат не останавливает остальные ═════════════════

@pytest.mark.asyncio
async def test_tick_hung_chat_does_not_stall_other_chats(tmp_path, monkeypatch):
    """Матрица «крон»: один чат с зависшим обслуживанием памяти больше не
    блокирует тик — оба чата опубликованы, тик завершается быстро."""
    db = await _fresh_db(tmp_path, "tick.db")
    monkeypatch.setenv("SUMMARY_MEMORY_MAINT_HARD_SECONDS", "0.1")
    monkeypatch.setenv("SUMMARY_TICK_CHAT_TIMEOUT_SECONDS", "10")

    async def _hang(chat_id):
        if chat_id == BUSY_CHAT:
            await asyncio.sleep(30)

    bot = AsyncMock()
    gen = _gen(_GenMemory(rows=[_row()], db=db, maintenance=_hang), bot=bot)
    service = SummarySchedulerService(gen, db)
    mod = dataclasses.replace(settings,
                              SUMMARY_TARGET_CHAT_IDS=(BUSY_CHAT, FREE_CHAT))

    t0 = time.perf_counter()
    with patch("services.summary_scheduler.settings", mod):
        await service._tick()
    elapsed = time.perf_counter() - t0

    assert elapsed < 10.0
    sent_chats = {c.args[0] for c in bot.send_message.await_args_list}
    assert sent_chats == {BUSY_CHAT, FREE_CHAT}
    for chat_id in (BUSY_CHAT, FREE_CHAT):
        runs = await _runs_for_chat(db, chat_id)
        assert len(runs) == 1 and runs[0]["state"] in ("DONE", "DEGRADED")
    await db.close()


@pytest.mark.asyncio
async def test_tick_chat_timeout_is_last_resort_and_loop_survives(monkeypatch):
    """Last-resort потолок времени на чат + исключение одного чата не срывает
    обработку остальных (per-chat try/except в `_tick`)."""
    monkeypatch.setenv("SUMMARY_TICK_CHAT_TIMEOUT_SECONDS", "0.2")
    calls: list = []

    class _Gen:
        async def generate_and_send(self, chat_id, manual=False, **kwargs):
            calls.append(chat_id)
            if chat_id == -1:
                await asyncio.sleep(30)
            if chat_id == -2:
                raise RuntimeError("boom")

    db = MagicMock()
    db.get_smart_chat_ids = AsyncMock(return_value=[])
    service = SummarySchedulerService(_Gen(), db)
    mod = dataclasses.replace(settings, SUMMARY_TARGET_CHAT_IDS=(-1, -2, -3))
    with patch("services.summary_scheduler.settings", mod):
        t0 = time.perf_counter()
        await service._tick()
        elapsed = time.perf_counter() - t0

    assert calls == [-1, -2, -3]        # все три чата попытались
    assert elapsed < 3.0                # «висящий» чат не держит тик


# ═══ 4. Рестарт: устаревший ран без окна / resume с окном ══════════════════

@pytest.mark.asyncio
async def test_restart_stale_run_without_window_closed_new_run_id(
        tmp_path, monkeypatch, caplog):
    """Матрица «рестарт (а)»: нетерминальный ран без окна и без живого
    владельца → FAILED/stale_no_window, новый прогон получает СВОЙ run_id,
    публикация ровно одна (у прежнего рана окна не было)."""
    db = await _fresh_db(tmp_path, "stale.db")
    await db.create_summary_run(run_id="run-old", chat_id=CHAT,
                                state="CREATED", manual=False,
                                created_at=int(time.time()) - 7200)
    monkeypatch.setenv("SUMMARY_STALE_RUN_SECONDS", "900")

    bot = AsyncMock()
    gen = _gen(_GenMemory(rows=[_row()], db=db), bot=bot)
    with caplog.at_level(logging.WARNING):
        await gen.generate_and_send(CHAT)

    assert "SUMMARY_STALE_RUN_CLOSED" in caplog.text
    old = await srs.get_run(db, "run-old")
    assert old["state"] == "FAILED"
    # публикации у прежнего рана не было и не будет (не отправлено ничего)
    assert old["publication_status"] not in ("published", "publishing")
    old_stages = await srs.stage_history(db, "run-old")
    assert any(r["stage"] == "run" and r["reason_code"] == "stale_no_window"
               for r in old_stages)

    runs = await _runs_for_chat(db, CHAT)
    assert len(runs) == 2
    fresh = [r for r in runs if r["run_id"] != "run-old"]
    assert len(fresh) == 1
    assert fresh[0]["state"] in ("DONE", "DEGRADED")
    assert bot.send_message.await_count == 1            # ровно одна отправка
    await db.close()


@pytest.mark.asyncio
async def test_restart_run_with_window_resumes_same_run_id_single_send(
        tmp_path, monkeypatch):
    """Матрица «рестарт (б)»: у рана ЕСТЬ durable окно → resume ТОГО ЖЕ run_id
    (snapshot = контракт), второго живого рана на то же окно не создаётся,
    отправка одна (дубль публикации невозможен)."""
    db = await _fresh_db(tmp_path, "resume.db")
    await db.create_summary_run(run_id="run-win", chat_id=CHAT,
                                state="SOURCE_READY", manual=False,
                                created_at=int(time.time()) - 7200)
    await db.update_summary_run_state("run-win", "SOURCE_READY",
                                      window_from=1_700_000_000,
                                      window_to=1_700_010_000,
                                      source_ref="sr-1")
    monkeypatch.setenv("SUMMARY_STALE_RUN_SECONDS", "900")

    bot = AsyncMock()
    gen = _gen(_GenMemory(rows=[_row()], db=db), bot=bot)
    await gen.generate_and_send(CHAT)

    runs = await _runs_for_chat(db, CHAT)
    assert [r["run_id"] for r in runs] == ["run-win"]    # второй run_id не создан
    assert runs[0]["state"] in ("DONE", "DEGRADED")
    assert bot.send_message.await_count == 1
    await db.close()


# ═══ 5. Конкурентные раны / таймаут пермита ════════════════════════════════

@pytest.mark.asyncio
async def test_permit_timeout_clean_skip_without_run_row_and_tick_continues(
        tmp_path, monkeypatch, caplog):
    """Матрица «конкурентные раны»: слот занят → bounded-ожидание истекает →
    чистый skip БЕЗ run-row (ручной путь получает честный UX), а тик идёт к
    следующему чату и публикует его."""
    db = await _fresh_db(tmp_path, "permit.db")
    monkeypatch.setenv("SUMMARY_PERMIT_WAIT_SECONDS", "0.05")
    monkeypatch.setenv("SUMMARY_TICK_CHAT_TIMEOUT_SECONDS", "10")

    pool = _SelectivePool(busy_chat=BUSY_CHAT)
    bot = AsyncMock()
    gen = _gen(_GenMemory(rows=[_row()], db=db), bot=bot, pool=pool)

    with caplog.at_level(logging.WARNING):
        await gen.generate_and_send(BUSY_CHAT, manual=True)

    assert pool.acquire_calls == 0                       # без бесконечного ожидания
    assert (BUSY_CHAT, 0.0) in pool.try_calls
    assert (BUSY_CHAT, 0.05) in pool.try_calls
    assert "SUMMARY_PERMIT_WAIT" in caplog.text
    assert "outcome=timeout" in caplog.text
    assert await _runs_for_chat(db, BUSY_CHAT) == []     # run-row не создаётся
    ux = [c.args[1] for c in bot.send_message.await_args_list]
    assert "уже делаю саммари, подожди" in ux
    assert "саммари занято, попробуй позже" in ux

    # Тик: занятый чат пропущен, свободный — обработан.
    bot.reset_mock()
    service = SummarySchedulerService(gen, db)
    mod = dataclasses.replace(settings,
                              SUMMARY_TARGET_CHAT_IDS=(BUSY_CHAT, FREE_CHAT))
    with patch("services.summary_scheduler.settings", mod):
        await service._tick()
    assert {c.args[0] for c in bot.send_message.await_args_list} == {FREE_CHAT}
    assert len(await _runs_for_chat(db, FREE_CHAT)) == 1
    assert await _runs_for_chat(db, BUSY_CHAT) == []
    await db.close()


# ═══ 6. No-progress guard и LLM-недоступность ═════════════════════════════

@pytest.mark.asyncio
async def test_no_progress_same_batch_stops_with_reason(monkeypatch, caplog):
    """Матрица «no-progress guard»: маркер — no-op, та же пачка приходит
    второй раз → стоп с причиной (без спина и без повторной экстракции)."""
    batch = [{"id": i, "text": f"t{i}"} for i in range(5)]

    class _StuckDB:
        def __init__(self):
            self.fetches = 0

        async def get_smart_raw(self, chat_id, cutoff, batch_size,
                                exclude_imported=True, exclude_processed=True):
            self.fetches += 1
            return list(batch)

        async def mark_smart_messages_processed(self, chat_id, ids):
            return 0                      # молчаливый no-op

    db = _StuckDB()
    mm = _bare_memory(db)
    calls: list = []

    async def _extract(chat_id, b):
        calls.append(len(b))

    mm._extract_and_save_graph = _extract
    monkeypatch.setattr(sm, "settings", dataclasses.replace(
        settings, INFINITE_RETENTION=True, SUMMARY_COMPRESS_BATCH=5))

    with caplog.at_level(logging.WARNING):
        await mm._compress_purge_extract_only(CHAT)

    assert calls == [5]                    # пачка экстрактится РОВНО один раз
    assert db.fetches == 2                 # вторая выборка → стоп, не спин
    assert "reason=no_progress_same_batch" in caplog.text


@pytest.mark.asyncio
async def test_llm_unavailable_batch_kept_and_loop_exits(monkeypatch):
    """Матрица «LLM недоступен» (seam как в test_summary_asap_hotfix_round1027):
    все чанки падают → батч сохранён (не помечен), метод завершается штатно
    и границы INC-SUMMARY-01 не меняют эту семантику."""
    class _FakeDB:
        def __init__(self, rows):
            self.rows = list(rows)
            self.marked: list = []

        async def get_smart_raw(self, chat_id, cutoff, batch_size,
                                exclude_imported=True, exclude_processed=True):
            return self.rows[:batch_size]

        async def mark_smart_messages_processed(self, chat_id, ids):
            self.marked.append(list(ids))

    db = _FakeDB([{"id": 1, "text": "а"}, {"id": 2, "text": "б"}])
    mm = _bare_memory(db)

    async def _fail(chat_id, b):
        raise sm.GraphExtractionError(
            "graph extract failed: all 1 chunk(s) failed "
            "| reason=LLMTimeoutError")

    mm._extract_and_save_graph = _fail
    monkeypatch.setattr(sm, "settings", dataclasses.replace(
        settings, INFINITE_RETENTION=True, SUMMARY_COMPRESS_BATCH=100))

    await mm._compress_purge_extract_only(CHAT)
    assert db.marked == []                 # батч сохранён — не потерян


# ═══ 7. OFF kill-switch: прежний контур ════════════════════════════════════

@pytest.mark.asyncio
async def test_off_kill_switch_unbounded_permit_and_no_new_stages(
        tmp_path, monkeypatch):
    """OFF `SUMMARY_PREGEN_BOUNDS_ENABLED` → прежний контур: ожидание слота
    через `acquire()` без таймаута, новых stage-строк нет (паритет baseline)."""
    db = await _fresh_db(tmp_path, "off.db")
    monkeypatch.setenv("SUMMARY_PREGEN_BOUNDS_ENABLED", "0")

    pool = _SelectivePool(busy_chat=CHAT)
    bot = AsyncMock()
    gen = _gen(_GenMemory(rows=[_row()], db=db), bot=bot, pool=pool)
    await gen.generate_and_send(CHAT)

    assert pool.acquire_calls == 1
    assert pool.try_calls == [(CHAT, 0.0)]      # только мгновенная проба
    assert bot.send_message.await_count == 1
    runs = await _runs_for_chat(db, CHAT)
    stages = [r["stage"] for r in await srs.stage_history(db,
                                                          runs[0]["run_id"])]
    for name in ("run_permit", "run_memory_maintenance", "run_source_window"):
        assert name not in stages
    await db.close()


@pytest.mark.asyncio
async def test_off_kill_switch_extract_only_ignores_cap(monkeypatch):
    """OFF → extract-only обрабатывает всю очередь (кап не действует):
    паритет прежнего `while True` до короткой пачки."""
    batch = [{"id": i, "text": f"t{i}"} for i in range(4)]

    class _DrainDB:
        def __init__(self, total):
            self.rows = [{"id": i, "text": f"t{i}"} for i in range(total)]

        async def get_smart_raw(self, chat_id, cutoff, batch_size,
                                exclude_imported=True, exclude_processed=True):
            rows, self.rows = self.rows[:batch_size], self.rows[batch_size:]
            return rows

        async def mark_smart_messages_processed(self, chat_id, ids):
            return len(ids)

    db = _DrainDB(12)
    mm = _bare_memory(db)
    seen: list = []

    async def _extract(chat_id, b):
        seen.append(len(b))

    mm._extract_and_save_graph = _extract
    monkeypatch.setattr(sm, "settings", dataclasses.replace(
        settings, INFINITE_RETENTION=True, SUMMARY_COMPRESS_BATCH=4))
    monkeypatch.setenv("SUMMARY_PREGEN_BOUNDS_ENABLED", "0")
    monkeypatch.setenv("SUMMARY_MEMORY_MAINT_MAX_BATCHES", "1")

    await mm._compress_purge_extract_only(CHAT)
    assert seen == [4, 4, 4]               # все три батча, кап проигнорирован


# ═══ 8. Отменобезопасность записи графа ════════════════════════════════════

@pytest.mark.asyncio
async def test_write_graph_triplets_rollback_on_base_exception(
        tmp_path, monkeypatch):
    """Отмена (CancelledError — BaseException) внутри транзакции записи графа
    обязана откатить её: иначе открытая транзакция остаётся на общем
    single-writer соединении."""
    db = await _fresh_db(tmp_path, "tx.db")
    mm = _bare_memory(db)

    async def _cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(db, "upsert_node", _cancel)
    triplets = [{"subject": "а", "object": "б", "predicate": "r",
                 "subject_type": "person", "object_type": "person"}]

    with pytest.raises(asyncio.CancelledError):
        await mm._write_graph_triplets(CHAT, triplets)
    assert db.db.in_transaction is False, "транзакция не откачена"
    await db.close()
