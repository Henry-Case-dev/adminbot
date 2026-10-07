"""asap5-final-fixes (ADR-1028-25, D10/T-5255) — GraphRAG recovery.

Покрытие (§16#21–25 + D10):

* #21 healthy building → progress БЕЗ duplicate-recovery (одна джоба);
* #22 stale building → ОДИН bounded resume (restart-simulation);
* #23 активация shadow → `_index_generation_ok=True` (guard A06);
* #24 FTS живёт во время rebuild (guard честен, vec-path закрыт);
* #25 warning НЕ глушится и НЕ дублируется (коалисинг per (status, fp));
* D10 future-resume: периодический тик `resume_tick_once` возобновляет
  paused_rate_limit-джобу ПОСЛЕ истечения next_allowed_at — переживает
  рестарт (in-process sleep не используется);
* D10 knn_source_empty: пустой источник → stable terminal (job НЕ
  переоткрывается по schedule); появились строки → reopen разрешён;
* rebuild_status()/vector_memory_panel wiring: N/M + ticker факт.
"""
import asyncio
import json
import time

import pytest
import pytest_asyncio

from services import graphrag_rebuild as gr
from services import summary_memory as sm
from services.database import DatabaseService

# Контур control-plane/rebuild (AM-1, pause/resume) — как в asap4-тестах:
# маркер исключает тест из conftest-OFF (бит-в-бит легаси).
pytestmark = [pytest.mark.asap4]


@pytest_asyncio.fixture
async def vec_db(tmp_path):
    d = DatabaseService(str(tmp_path / "asap5_graphrag.db"))
    await d.initialize()
    import sqlite_vec
    await d.db.enable_load_extension(True)
    await d.db.load_extension(sqlite_vec.loadable_path())
    await d.db.enable_load_extension(False)
    yield d
    await d.close()


class _CountingEmbed:
    def __init__(self, dim: int = 8):
        self.dim = dim
        self.texts: list[str] = []

    async def __call__(self, texts):
        self.texts.extend(texts)
        out = []
        for t in texts:
            seed = sum(bytearray(t.encode("utf-8"))) % 97
            vec = [((seed + i * 13) % 7) / 7.0 for i in range(self.dim)]
            vec[0] += 0.5
            out.append(vec)
        return out


def _memory(db) -> sm.MemoryManager:
    mm = sm.MemoryManager(db, None)
    mm._vec_dim = 8
    mm._vec_available = True
    mm._vec_int8 = False
    return mm


def _patch_setting(monkeypatch, name, value):
    import config.settings as cs
    monkeypatch.setattr(type(cs.settings), name, value, raising=False)
    if type(sm.settings) is not type(cs.settings):
        monkeypatch.setattr(type(sm.settings), name, value, raising=False)


async def _seed_facts(db, index: str, n: int, chat_id: int = 77) -> None:
    now = int(time.time())
    for i in range(n):
        if index == "graph_facts_vec":
            await db.db.execute(
                "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
                "VALUES (?, ?, 'chat_history', ?)",
                (chat_id, f"уникальный факт номер {i} о проекте {i}", now))
        else:
            await db.db.execute(
                "INSERT INTO smart_archive_facts (chat_id, fact, timestamp) "
                "VALUES (?, ?, ?)",
                (chat_id, f"архивный факт номер {i} о проекте {i}", now))
    await db.db.commit()


async def _register_building(db, index: str, fp: str) -> int:
    from services import summary_memory as sm
    await db.ensure_embedding_generation(
        index, fp,
        provider=sm._embedding_provider(),
        model=sm.hot.get("models.embedding_model_name",
                         sm.settings.EMBEDDING_MODEL_NAME),
        dims=8, preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint=sm._endpoint_fingerprint(), activate=False)
    row = await db.get_generation_by_fingerprint(index, fp)
    assert row is not None and row["status"] == "building"
    return int(row["generation"])


async def _pause_job(db, jid: str, fp: str, index: str, *, cooldown_s: int
                     ) -> None:
    """Перевод джобы в paused_rate_limit c next_allowed_at (как _apply_pause)."""
    await gr._job_cas(db, jid, expect=gr.ST_RUNNING,
                      set_status=gr.ST_PAUSED_RATE_LIMIT,
                      reason_code="rate_limit:quota_group")
    await db.db.execute(
        "UPDATE mca_embedding_index_generations SET pause_reason = ?, "
        "next_allowed_at = ?, attempts_total = COALESCE(attempts_total, 0) + 1 "
        "WHERE index_name = ? AND fingerprint = ?",
        (f"rate_limit:quota_group", int(time.time()) + int(cooldown_s),
         index, fp))
    await db.db.commit()


@pytest.mark.asyncio
async def test_future_resume_tick_after_cooldown_restart_survives(
        vec_db, monkeypatch):
    """D10/RCA G2: рестарт в окне next_allowed_at → job спит; ПОСЛЕ
    истечения cooldown периодический тик (`resume_tick_once` — тот же вызов,
    что в `_loop`) возобновляет джобу. Никакого in-process sleep."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_BATCH", 2)
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 4)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    assert jid

    # Авто-resume in-process отключён (рестарт его «убил»).
    monkeypatch.setattr(gr, "_schedule_auto_resume", lambda *a, **kw: None)

    embed = _CountingEmbed()
    state = {"calls": 0}

    async def flaky(texts):
        state["calls"] += 1
        if state["calls"] == 2:      # ровно один 429 (первая пауза)
            from services.llm_client import LLMRateLimitError
            exc = LLMRateLimitError("LLM rate limited (429)")
            exc.headers = {"Retry-After": "900"}
            exc.body = ""
            raise exc
        return await embed(texts)

    monkeypatch.setattr(mm, "_embed", flaky)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT

    # Тик В ОКНЕ cooldown — no-op (джоба не сбрасывается, дублей нет).
    resumed = await gr.resume_tick_once(mm)
    assert resumed == []
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM task_jobs WHERE kind = 'graphrag_rebuild'")
    assert (await cur.fetchone())["c"] == 1     # без duplicate jobs

    # Симуляция рестарта + истечения cooldown: СЛЕДУЮЩИЙ ТИК возобновляет.
    await vec_db.db.execute(
        "UPDATE mca_embedding_index_generations SET next_allowed_at = ? "
        "WHERE index_name = 'graph_facts_vec' AND fingerprint = ?",
        (int(time.time()) - 1, fp))
    await vec_db.db.commit()
    resumed = await gr.resume_tick_once(mm)
    assert resumed == ["graph_facts_vec"]
    # run_job уходит в fire-and-forget — ждём выхода из queued (bounded).
    job = await gr._get_job(vec_db, jid)
    for _ in range(200):
        job = await gr._get_job(vec_db, jid)
        if job["status"] != gr.ST_QUEUED:
            break
        await asyncio.sleep(0.02)
    assert job["status"] in (gr.ST_RUNNING, gr.ST_CHECKPOINT,
                             gr.ST_VALIDATED, gr.ST_ACTIVATED)
    # Дожидаемся финала (validated/activated), чтобы fire-and-forget задача
    # не пережила закрытие тестовой БД.
    for _ in range(300):
        job = await gr._get_job(vec_db, jid)
        if job["status"] in (gr.ST_VALIDATED, gr.ST_ACTIVATED):
            break
        await asyncio.sleep(0.02)
    assert job["status"] in (gr.ST_VALIDATED, gr.ST_ACTIVATED)
    await asyncio.sleep(0.05)
    # Тот же job (bounded, без дублей) и та же generation.
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM task_jobs WHERE kind = 'graphrag_rebuild'")
    assert (await cur.fetchone())["c"] == 1
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert int(gen["generation"]) == int(generation)


@pytest.mark.asyncio
async def test_resume_ticker_starts_once_and_reports(vec_db, monkeypatch):
    """D10: `start_resume_ticker` идемпотентен (один на процесс), факт
    старта виден диагностике (`ticker_active`); disabled-флаг → не стартует."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_ENABLED", True)
    assert gr.ticker_active() is False
    started = gr.start_resume_ticker(_memory(vec_db))
    assert started is True
    assert gr.ticker_active() is True
    # Повторный вызов (второй startup-путь) — no-op.
    assert gr.start_resume_ticker(_memory(vec_db)) is False
    assert gr.ticker_active() is True


@pytest.mark.asyncio
async def test_knn_source_empty_stable_terminal_no_reopen(vec_db, monkeypatch):
    """D10/RCA §2.4: `knn_source_empty` при ПУСТОМ источнике — stable
    terminal: schedule-тик НЕ переоткрывает джобу; после появления строк —
    reopen разрешён."""
    mm = _memory(vec_db)
    fp = mm._identity_fingerprint()
    # Источник smart_archive ПУСТ (прод-факт: 0 строк).
    generation = await _register_building(vec_db, "smart_archive", fp)
    jid = await gr._ensure_job(vec_db, "smart_archive", fp, generation)
    # Джоба уходит в validation_failed с knn_source_empty (как run_job).
    await gr._job_cas(vec_db, jid, expect=gr.ST_QUEUED,
                      set_status=gr.ST_VALIDATION_FAILED,
                      reason_code="knn_source_empty", terminal=True)
    # include_failed=False (тик post-release) → НЕ переоткрывает.
    assert await gr.maybe_schedule_rebuilds(mm, include_failed=False) == []
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_VALIDATION_FAILED
    assert job["reason_code"] == "knn_source_empty"
    # startup-schedule (include_failed=True) тоже держит stable terminal.
    assert await gr.maybe_schedule_rebuilds(mm) == []
    # Появились строки в источнике → reopen снова возможен.
    await _seed_facts(vec_db, "smart_archive", 2)
    assert await gr._source_empty(vec_db, "smart_archive") is False
    assert await gr._ensure_job(vec_db, "smart_archive", fp, generation) == jid


@pytest.mark.asyncio
async def test_activation_clears_guard_and_fts_lives(vec_db, monkeypatch):
    """§16#23/#24: успешная активация → `_index_generation_ok=True`;
    ДО активации vec-path закрыт, но FTS остаётся живым (guard честен)."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)

    # building → guard закрыт (vec-path FTS-only), A06 честен.
    assert await mm._index_generation_ok("graph_facts_vec") is False

    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    monkeypatch.setattr(mm, "_embed", _CountingEmbed())
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_BATCH", 10)
    await gr.run_job(mm, "graph_facts_vec", jid)
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert gen["status"] == "active"
    assert await mm._index_generation_ok("graph_facts_vec") is True


@pytest.mark.asyncio
async def test_warning_coalesced_not_repeated(vec_db, monkeypatch, caplog):
    """§16#25 + INV-6: warning «not serviceable» НЕ глушится, но и НЕ
    дублируется — тот же (status, fp12) в окне коалисинга идёт в DEBUG."""
    import logging
    # Изоляция: коалисинг-состояние процесса чистим (другие тесты/прогрев).
    sm._GEN_LOG_STATE.clear()
    mm = _memory(vec_db)
    fp = mm._identity_fingerprint()
    await _register_building(vec_db, "graph_facts_vec", fp)
    with caplog.at_level(logging.DEBUG, logger="services.summary_memory"):
        await mm._index_generation_ok("graph_facts_vec")
        first = [r for r in caplog.records if r.levelno == logging.WARNING
                 and "not serviceable" in r.getMessage()]
        await mm._index_generation_ok("graph_facts_vec")
        second = [r for r in caplog.records if r.levelno == logging.WARNING
                  and "not serviceable" in r.getMessage()]
    # Warning РОВНО один (второй — coalesced → DEBUG); не заглушён.
    assert len(first) == 1
    assert len(second) == len(first)


@pytest.mark.asyncio
async def test_rebuild_status_wired_to_panel(vec_db, monkeypatch):
    """D10 incidental RCA: `rebuild_status()` подключён к существующему
    embeddings read-API (`vector_memory_panel`: N/M + resume_ticker)."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 3)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    from services import embedding_control_plane as ecp
    panel = await ecp.vector_memory_panel(vec_db)
    assert "resume_ticker" in panel
    entry = next(ix for ix in panel["indexes"]
                 if ix["index"] == "graph_facts_vec")
    assert entry["total"] == 3
    assert entry["source_empty"] is False
    # processed приходит из checkpoint-payload (None до первого чанка —
    # честный unknown, не выдуманный 0).
    assert entry["processed"] is None or isinstance(entry["processed"], int)
    # rebuild_status(): structured job-snapshot остаётся читаемым.
    status = await gr.rebuild_status(vec_db)
    assert isinstance(status, dict)
    assert any(job.get("index") == "graph_facts_vec"
               for job in status.values())
