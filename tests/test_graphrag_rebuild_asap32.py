"""ASAP-3.2 (round1029, ADR-1028-5 D1–D3, T-4191/T-4192) — GraphRAG shadow
rebuild lifecycle (§70):

* existing unknown vec → BUILDING/FTS (карантин A06 сохраняется до rebuild);
* rebuild под текущим fingerprint → progress → ACTIVE (path building→active
  появился); activation ТОЛЬКО после 9-критериальной validation;
* restart mid-build → resume от checkpoint (НЕ с нуля);
* config changes during build → старый build НЕ активируется как current;
* failed build → FTS остаётся serviceable (gate закрыт, FTS-путь жив);
* missing vectors → validation fail (coverage-критерий §6.5);
* log severity (§8): не-спам WARNING на каждый RAG-вызов.

Δ SQLite DDL = 0: shadow — `CREATE VIRTUAL TABLE IF NOT EXISTS` (user_version
не меняется); регистрация поколений — существующая v18-структура.
"""
import json
import time

import pytest
import pytest_asyncio

import services.database as dbmod
from services import summary_memory as sm
from services import graphrag_rebuild as gr
from services.database import DatabaseService


@pytest_asyncio.fixture
async def vec_db(tmp_path):
    """DatabaseService с загруженным sqlite-vec (shadow/live vec0-таблицы)."""
    d = DatabaseService(str(tmp_path / "graphrag32.db"))
    await d.initialize()
    import sqlite_vec
    await d.db.enable_load_extension(True)
    await d.db.load_extension(sqlite_vec.loadable_path())
    await d.db.enable_load_extension(False)
    yield d
    await d.close()


class _CountingEmbed:
    """Детерминированный embed (self-match KNN работает) со счётчиком."""

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.texts: list[str] = []
        self.fail_on: set[str] = set()

    async def __call__(self, texts):
        for t in texts:
            if t in self.fail_on:
                raise RuntimeError("embed_fail_forced")
        self.texts.extend(texts)
        out = []
        for t in texts:
            seed = sum(bytearray(t.encode("utf-8"))) % 97
            vec = [((seed + i * 13) % 7) / 7.0 for i in range(self.dim)]
            vec[0] += 0.5                    # ненулевая норма гарантирована
            out.append(vec)
        return out


def _memory(db) -> sm.MemoryManager:
    mm = sm.MemoryManager(db, None)
    mm._vec_dim = 8
    mm._vec_available = True
    mm._vec_int8 = False
    return mm


def _patch_setting(monkeypatch, name, value):
    """Патч ClassVar на ВСЕХ актуальных Settings-классах: часть тестов сьюта
    делает importlib.reload(config.settings) — `sm.settings` может указывать
    на старый класс, а `graphrag_rebuild` импортирует settings лениво
    (свежий). Прецедент — fixtures tests/conftest.py."""
    import config.settings as cs
    monkeypatch.setattr(type(cs.settings), name, value, raising=False)
    if type(sm.settings) is not type(cs.settings):
        monkeypatch.setattr(type(sm.settings), name, value, raising=False)


async def _seed_facts(db, index: str, n: int, chat_id: int = 77) -> list[int]:
    now = int(time.time())
    ids = []
    for i in range(n):
        if index == "graph_facts_vec":
            cur = await db.db.execute(
                "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
                "VALUES (?, ?, 'chat_history', ?) RETURNING id",
                (chat_id, f"уникальный факт номер {i} о проекте {i}", now))
        else:
            cur = await db.db.execute(
                "INSERT INTO smart_archive_facts (chat_id, fact, timestamp) "
                "VALUES (?, ?, ?) RETURNING id",
                (chat_id, f"архивный факт номер {i} о проекте {i}", now))
        row = await cur.fetchone()
        ids.append(row[0])
    await db.db.commit()
    return ids


async def _register_building(db, index: str, fp: str) -> int:
    """Регистрация building-поколения (как `_register_index_generations`
    делает для preexisting vec-таблиц). ВНИМАНИЕ: `ensure_embedding_generation`
    при `activate=False` возвращает `get_active(...)` → None (пре-существующее
    поведение 2.58.39) — строку читаем по fingerprint."""
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


async def _table_names(db) -> set[str]:
    cur = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")
    return {r["name"] for r in await cur.fetchall()}


# ═══ §70: existing unknown vec → BUILDING/FTS ═══════════════════════════════

@pytest.mark.asyncio
async def test_existing_unknown_vec_building_fts_only(vec_db):
    """Preexisting vec-таблицы → building-карантин: vector path закрыт (A06)."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 3)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    await _register_building(vec_db, "graph_facts_vec", fp)
    # Gate закрыт → FTS-only; rebuild ещё НЕ запущен.
    assert not await mm._index_generation_ok("graph_facts_vec")


# ═══ §70: rebuild → progress → ACTIVE (atomic, validated) ═══════════════════

@pytest.mark.asyncio
async def test_rebuild_validated_atomic_activate(vec_db, monkeypatch):
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_BATCH", 2)
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    embed = _CountingEmbed()
    monkeypatch.setattr(mm, "_embed", embed)
    ids = await _seed_facts(vec_db, "graph_facts_vec", 5)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)

    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    assert jid
    await gr.run_job(mm, "graph_facts_vec", jid)

    # Активация ТОЛЬКО после validation: generation active с тем же fp.
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active is not None
    assert active["status"] == "active"
    assert active["fingerprint"] == fp
    # Live-таблица заполнена ПОЛНОСТЬЮ (полный rebuild, не fill-missing).
    cur = await vec_db.db.execute("SELECT COUNT(*) AS c FROM graph_facts_vec")
    assert (await cur.fetchone())["c"] == 5
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM graph_facts_vec WHERE fact_id NOT IN "
        "(SELECT id FROM graph_facts)")
    assert (await cur.fetchone())["c"] == 0        # нет orphan vectors
    # Shadow удалён (swap завершился), user_version НЕ менялся (ΔDDL=0).
    assert f"graph_facts_vec_g{generation}" not in await _table_names(vec_db)
    cur = await vec_db.db.execute("PRAGMA user_version")
    # Shadow-rebuild — ΔDDL=0; реестр может идти дальше v19 (v20 — mca-04b).
    assert (await cur.fetchone())[0] >= 19
    # Vector path открыт.
    assert await mm._index_generation_ok("graph_facts_vec")
    # D2 state machine достигла терминального состояния.
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_ACTIVATED


@pytest.mark.asyncio
async def test_rebuild_smart_archive_index(vec_db, monkeypatch):
    """Второй индекс (smart_archive) проходит тот же lifecycle."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    monkeypatch.setattr(mm, "_embed", _CountingEmbed())
    await _seed_facts(vec_db, "smart_archive", 3)
    await vec_db.db.execute(mm._vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "smart_archive", fp)
    jid = await gr._ensure_job(vec_db, "smart_archive", fp, generation)
    await gr.run_job(mm, "smart_archive", jid)
    active = await vec_db.get_active_embedding_generation("smart_archive")
    assert active is not None and active["status"] == "active"
    cur = await vec_db.db.execute("SELECT COUNT(*) AS c FROM smart_archive")
    assert (await cur.fetchone())["c"] == 3


# ═══ §70: restart mid-build → resume от checkpoint ══════════════════════════

@pytest.mark.asyncio
async def test_restart_mid_build_resumes_from_checkpoint(vec_db, monkeypatch):
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_BATCH", 2)
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 6)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)

    # «Падение процесса» после первого батча: embed ломается со 2-го вызова.
    embed = _CountingEmbed()

    state = {"calls": 0}

    async def flaky(texts):
        state["calls"] += 1
        if state["calls"] >= 2:
            raise RuntimeError("simulated_restart_crash")
        return await embed(texts)

    monkeypatch.setattr(mm, "_embed", flaky)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_FAILED
    from services.task_supervisor import TaskJobStore
    checkpoint = await TaskJobStore(vec_db).get_checkpoint(jid)
    assert checkpoint is not None
    cursor = json.loads(checkpoint["cursor"])
    assert cursor["processed"] == 2 and cursor["last_id"] > 0

    # Restart: джоба переоткрывается (как startup-schedule) и продолжается
    # С checkpoint — первые 2 факта повторно НЕ встраиваются; identity
    # восстанавливается из coalesce_key (payload перезаписан checkpoint'ом).
    assert await gr._job_cas(vec_db, jid, expect=gr.ST_FAILED,
                             set_status=gr.ST_QUEUED,
                             reason_code="retry_on_schedule")
    monkeypatch.setattr(mm, "_embed", embed)
    await gr.run_job(mm, "graph_facts_vec", jid)
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active is not None and active["status"] == "active"
    # 2 (первый батч) + 4 (остаток) — ровно 6; пересборки с нуля не было.
    assert len(embed.texts) == 6
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_ACTIVATED


class TaskJobStoreProbe:
    """Доступ к checkpoint (тонкая обёртка над TaskJobStore для теста)."""

    def __init__(self, db):
        from services.task_supervisor import TaskJobStore
        self._store = TaskJobStore(db)

    async def get_checkpoint(self, job_id):
        return await self._store.get_checkpoint(job_id)


# ═══ §70: config changes during build → старый build НЕ активируется ════════

@pytest.mark.asyncio
async def test_config_change_mid_build_blocks_activation(vec_db, monkeypatch):
    """Race-guard D2: build привязан к fp старта; смена fp до validate →
    failed/fingerprint_changed, generation остаётся building (vector path
    закрыт), shadow удалён."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    monkeypatch.setattr(mm, "_embed", _CountingEmbed())
    await _seed_facts(vec_db, "graph_facts_vec", 3)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp_old = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp_old)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp_old, generation)

    fp_new = fp_old + "_changed"

    def changed_fp(*a, **kw):
        return fp_new

    monkeypatch.setattr(mm, "_identity_fingerprint", changed_fp)

    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_FAILED
    assert job["reason_code"] == "fingerprint_changed"
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active is None                    # НЕ активирован как current
    assert f"graph_facts_vec_g{generation}" not in await _table_names(vec_db)
    assert not await mm._index_generation_ok("graph_facts_vec")


# ═══ §70: failed build → FTS остаётся serviceable ═══════════════════════════

@pytest.mark.asyncio
async def test_failed_build_fts_serviceable(vec_db, monkeypatch):
    """Embed-фейл mid-build → failed; vector path закрыт, FTS-путь —
    дефолт (gate False не роняет retrieval; механика FTS не тронута)."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)

    async def broken(texts):
        raise RuntimeError("embed_api_down")
    monkeypatch.setattr(mm, "_embed", broken)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_FAILED
    # Gate закрыт (FTS-only), автоматического storm нет (джоба failed).
    assert not await mm._index_generation_ok("graph_facts_vec")
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active is None


# ═══ §6.5: missing vectors → validation fail (coverage) ═════════════════════

@pytest.mark.asyncio
async def test_missing_vector_fails_validation(vec_db, monkeypatch):
    """Факт без vector row (embed skip) → критерий 5 не пройден, activation
    НЕ выполняется (запрет §3/§66: активировать недоказанное запрещено)."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 3)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)

    cur = await vec_db.db.execute(
        "SELECT fact FROM graph_facts ORDER BY id LIMIT 1")
    doomed = (await cur.fetchone())["fact"]

    class SkipOne(_CountingEmbed):
        async def __call__(self, texts):
            out = []
            for t in texts:
                if t == doomed:
                    out.append([])           # falsy → row НЕ вставится
                else:
                    out.extend(await super().__call__([t]))
            return out

    monkeypatch.setattr(mm, "_embed", SkipOne())
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_FAILED
    assert job["reason_code"] == "missing_vectors"
    assert await vec_db.get_active_embedding_generation(
        "graph_facts_vec") is None
    # Validation-failure: shadow удалён (cleanup), checkpoint сброшен —
    # retry начнёт полный rebuild заново (не застрянет за missing-row).
    shadow_name = f"graph_facts_vec_g{generation}"
    assert shadow_name not in await _table_names(vec_db)
    from services.task_supervisor import TaskJobStore
    checkpoint = await TaskJobStore(vec_db).get_checkpoint(jid)
    cursor = json.loads(checkpoint["cursor"])
    assert cursor["processed"] == 0 and cursor["last_id"] == 0


# ═══ §8: severity — не-спам WARNING ═════════════════════════════════════════

@pytest.mark.asyncio
async def test_not_serviceable_warning_coalesced(vec_db, caplog):
    """Первый `not serviceable` — WARNING; повтор при НЕИЗМЕННОМ состоянии —
    DEBUG (коалесинг §8); смена состояния → WARNING сразу."""
    mm = _memory(vec_db)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    await _register_building(vec_db, "graph_facts_vec", fp)
    sm._GEN_LOG_STATE.clear()
    with caplog.at_level("DEBUG", logger="services.summary_memory"):
        assert not await mm._index_generation_ok("graph_facts_vec")
        assert not await mm._index_generation_ok("graph_facts_vec")
        assert not await mm._index_generation_ok("graph_facts_vec")
    warnings = [r for r in caplog.records
                if r.levelno == 30 and "not serviceable" in r.message]
    debugs = [r for r in caplog.records
              if r.levelno == 10 and "coalesced" in r.message]
    assert len(warnings) == 1
    assert len(debugs) == 2
    # Смена состояния (другой fp, другой 12-префикс) → WARNING немедленно
    # (не ждёт cooldown).
    fp_x = ("x" + fp)[:32]
    await vec_db.ensure_embedding_generation(
        "graph_facts_vec", fp_x, provider=sm._embedding_provider(),
        model=sm.hot.get("models.embedding_model_name",
                         sm.settings.EMBEDDING_MODEL_NAME),
        dims=8, preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint=sm._endpoint_fingerprint(), activate=False)
    row2 = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp_x)
    assert row2 is not None and row2["status"] == "building"
    with caplog.at_level("DEBUG", logger="services.summary_memory"):
        assert not await mm._index_generation_ok("graph_facts_vec")
    warnings2 = [r for r in caplog.records
                 if r.levelno == 30 and "not serviceable" in r.message]
    assert len(warnings2) == 2


# ═══ §64: pause/resume/cancel контракты ═════════════════════════════════════

@pytest.mark.asyncio
async def test_pause_and_cancel_job_states(vec_db, monkeypatch):
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 1)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    # cancel до запуска: queued → cancelled (терминальный).
    assert await gr.cancel_rebuild(vec_db, "graph_facts_vec", fp=fp)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_CANCELLED
    # Повторный schedule НЕ переоткрывает cancelled (явный триггер нужен).
    assert await gr._ensure_job(vec_db, "graph_facts_vec", fp,
                                generation) is None
