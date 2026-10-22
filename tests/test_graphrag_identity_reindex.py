"""EMBED-REBUILD-MECHANISM (аудит 23.10.2026) — identity-drift → новое
поколение реестра + bounded rebuild; старые векторы/поколения целы.

Прод-факт (RCA): embeddings-провайдер переключён Google → apinet в рантайме.
`_identity_fingerprint()` даёт новый fp (`2d0efab0e817`), а реестр поколений
остался с `building`-поколением старого fp (`96f80838f683`) от 29.09.
`maybe_schedule_rebuilds` по D2 не оживляет чужой build — но и НОВОЕ
поколение не создавал (регистрация жила только в `MemoryManager.initialize`),
поэтому `_vec_write_allowed()` = False, backfill = 0, поиск — тихий FTS-only
без явного статуса «индекс требует перестройки».

Контракт, который защищают тесты:
  * смена fp → новое `building`-поколение под ТЕКУЩИЙ fp + durable-джоба;
  * старое поколение/shadow/live-векторы и source-факты НЕ удаляются;
  * повторный schedule идемпотентен (без дублей поколений/джоб);
  * `_vec_write_allowed` = False на время смешанного пространства и True
    после активации поколения текущего identity;
  * `generation_status()` честно различает active / build_in_progress /
    identity_changed / no_generation;
  * без реестра (тест-двойник) — fail-open и пустой снимок, не исключение.

TEST-LIFECYCLE: REGRESSION owner=EMBED-REBUILD-MECHANISM
"""
import json
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio

from services import graphrag_rebuild as gr
from services import summary_memory as sm
from services.database import DatabaseService

pytestmark = [pytest.mark.asap4]

# Прод-значения (короткие префиксы из логов/реестра): старый Google, новый
# apinet. Реестр хранит полный sha256 — берём 64-символьные строки.
OLD_FP = "96f80838f683" + "a" * 52
NEW_FP = "2d0efab0e817" + "b" * 52


@pytest_asyncio.fixture
async def vec_db(tmp_path):
    d = DatabaseService(str(tmp_path / "embed_rebuild.db"))
    await d.initialize()
    import sqlite_vec
    await d.db.enable_load_extension(True)
    await d.db.load_extension(sqlite_vec.loadable_path())
    await d.db.enable_load_extension(False)
    yield d
    await d.close()


class _Embed:
    """Детерминированный фейк-embed (без сети), dim=8."""

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


def _no_background(monkeypatch) -> None:
    """Планировщик НЕ запускает run_job в фоне: тест детерминированно
    вызывает `run_job` сам (иначе две гонки на одну джобу)."""
    def _fake(coro, tag):
        coro.close()

    monkeypatch.setattr(sm, "fire_and_forget", _fake)


async def _seed_graph_facts(db, n: int = 4, chat_id: int = 77) -> None:
    now = int(time.time())
    for i in range(n):
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (?, ?, 'chat_history', ?)",
            (chat_id, f"факт {i} про смену embedding-провайдера", now))
    await db.db.commit()


async def _seed_old_build(db, mm, index: str = "graph_facts_vec",
                          fp: str = OLD_FP):
    """Прод-состояние 29.09: `building`-поколение старого identity + shadow
    с частично построенными векторами (9797 строк на проде)."""
    await db.ensure_embedding_generation(
        index, fp,
        provider="generativelanguage.googleapis.com",
        model="gemini-embedding-001", dims=8,
        preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint="e42d6fd4c65855c2", activate=False)
    row = await db.get_generation_by_fingerprint(index, fp)
    assert row is not None and row["status"] == "building"
    shadow = gr._shadow_name(index, int(row["generation"]))
    await gr._create_shadow(mm, index, shadow)
    await db.db.execute(
        f"INSERT INTO {shadow}(rowid, fact_id, chat_id, origin, expires_at, "
        "embedding) VALUES (1, 1, 77, 'chat_history', NULL, ?)",
        (json.dumps([0.1] * 8),))
    await db.db.commit()
    return row, shadow


# ── 1. RED-сценарий: смена fp → поколение + джоба (без ручных действий) ─────

@pytest.mark.asyncio
async def test_identity_change_registers_generation_and_job(vec_db, monkeypatch):
    """Смена identity-fingerprint → планировщик регистрирует НОВОЕ
    `building`-поколение под текущий fp и durable-джобу; старое поколение и
    его shadow не тронуты (никакого удаления данных)."""
    _no_background(monkeypatch)
    mm = _memory(vec_db)
    await _seed_graph_facts(vec_db, 4)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    old, old_shadow = await _seed_old_build(vec_db, mm)
    monkeypatch.setattr(mm, "_identity_fingerprint", lambda **kw: NEW_FP)

    scheduled = await gr.maybe_schedule_rebuilds(mm)
    assert scheduled == ["graph_facts_vec"]

    new = await vec_db.get_generation_by_fingerprint("graph_facts_vec", NEW_FP)
    assert new is not None, "под текущий fingerprint обязано появиться поколение"
    assert new["status"] == "building"
    assert int(new["generation"]) == int(old["generation"]) + 1
    # identity-поля заполнены так, чтобы validation §6.3/§6.4 прошла.
    assert new["provider"] == sm._embedding_provider()
    assert new["model"] == sm.hot.get("models.embedding_model_name",
                                      sm.settings.EMBEDDING_MODEL_NAME)
    assert new["preprocessing_version"] == sm.EMBEDDING_PREPROCESSING_VERSION
    assert int(new["dims"]) == 8

    # Старые данные целы: поколение старого identity и его shadow.
    old_after = await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", OLD_FP)
    assert old_after["status"] == "building"
    assert int(old_after["generation"]) == int(old["generation"])
    cur = await vec_db.db.execute(f"SELECT COUNT(*) AS c FROM {old_shadow}")
    assert int((await cur.fetchone())["c"]) == 1

    job = await gr._find_active_job(vec_db, "graph_facts_vec", NEW_FP)
    assert job is not None and job["status"] == gr.ST_QUEUED
    payload = json.loads(job["payload"])
    assert int(payload["generation"]) == int(new["generation"])
    assert payload["fingerprint"] == NEW_FP


# ── 2. Полный путь: build → validate → activate, старые данные целы ─────────

@pytest.mark.asyncio
async def test_identity_change_rebuild_activates_and_keeps_old_data(
        vec_db, monkeypatch):
    """После смены identity bounded rebuild доводит индекс до ACTIVE:
    live-таблица перестроена под новый fp, `_vec_write_allowed=True`,
    source-факты и старое shadow-поколение не удалены."""
    _no_background(monkeypatch)
    mm = _memory(vec_db)
    await _seed_graph_facts(vec_db, 4)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    _old, old_shadow = await _seed_old_build(vec_db, mm)
    monkeypatch.setattr(mm, "_identity_fingerprint", lambda **kw: NEW_FP)
    monkeypatch.setattr(mm, "_embed", _Embed())
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)

    assert await gr.maybe_schedule_rebuilds(mm) == ["graph_facts_vec"]
    job = await gr._find_active_job(vec_db, "graph_facts_vec", NEW_FP)
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))

    job = await gr._get_job(vec_db, job["job_id"])
    assert job["status"] == gr.ST_ACTIVATED
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", NEW_FP)
    assert gen["status"] == "active"
    assert int(gen["activated_at"] or 0) > 0

    cur = await vec_db.db.execute("SELECT COUNT(*) AS c FROM graph_facts_vec")
    assert int((await cur.fetchone())["c"]) == 4
    cur = await vec_db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
    assert int((await cur.fetchone())["c"]) == 4        # source не тронут
    cur = await vec_db.db.execute(f"SELECT COUNT(*) AS c FROM {old_shadow}")
    assert int((await cur.fetchone())["c"]) == 1        # старый shadow цел

    assert await mm._index_generation_ok("graph_facts_vec") is True
    assert await mm._vec_write_allowed("graph_facts_vec") is True


# ── 3. Идемпотентность: повторный schedule не плодит поколения/джобы ────────

@pytest.mark.asyncio
async def test_ensure_current_generation_idempotent(vec_db, monkeypatch):
    _no_background(monkeypatch)
    mm = _memory(vec_db)
    await _seed_graph_facts(vec_db, 2)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    await _seed_old_build(vec_db, mm)
    monkeypatch.setattr(mm, "_identity_fingerprint", lambda **kw: NEW_FP)

    first = await gr.ensure_current_generation(mm, "graph_facts_vec")
    second = await gr.ensure_current_generation(mm, "graph_facts_vec")
    assert first is not None and second is not None
    assert int(first["generation"]) == int(second["generation"])

    await gr.maybe_schedule_rebuilds(mm)
    await gr.maybe_schedule_rebuilds(mm)
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_embedding_index_generations "
        "WHERE index_name = 'graph_facts_vec'")
    assert int((await cur.fetchone())["c"]) == 2        # old + одно новое
    # Ровно одна durable-джоба на (index, fp) — повторный schedule идемпотентен.
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM task_jobs WHERE kind = 'graphrag_rebuild' "
        "AND coalesce_key = ?", (gr._coalesce_key("graph_facts_vec", NEW_FP),))
    assert int((await cur.fetchone())["c"]) == 1


# ── 4. ACTIVE под текущий fp: перестройка не нужна ──────────────────────────

@pytest.mark.asyncio
async def test_active_current_identity_needs_no_rebuild(vec_db, monkeypatch):
    _no_background(monkeypatch)
    mm = _memory(vec_db)
    await vec_db.ensure_embedding_generation("graph_facts_vec", NEW_FP,
                                             dims=8, activate=True)
    monkeypatch.setattr(mm, "_identity_fingerprint", lambda **kw: NEW_FP)

    assert await gr.maybe_schedule_rebuilds(mm) == []
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_embedding_index_generations "
        "WHERE index_name = 'graph_facts_vec'")
    assert int((await cur.fetchone())["c"]) == 1
    assert await mm._vec_write_allowed("graph_facts_vec") is True


# ── 5. ACTIVE старого identity: target строится, ACTIVE не подменяется ──────

@pytest.mark.asyncio
async def test_active_old_identity_gets_target_generation(vec_db, monkeypatch):
    """Смена identity при существующем ACTIVE: старое ACTIVE продолжает
    описывать построенные векторы (A06/§8.4) до promotion; новое поколение —
    `building` под текущий fp."""
    _no_background(monkeypatch)
    mm = _memory(vec_db)
    await _seed_graph_facts(vec_db, 2)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    await vec_db.ensure_embedding_generation("graph_facts_vec", OLD_FP,
                                             dims=8, activate=True)
    monkeypatch.setattr(mm, "_identity_fingerprint", lambda **kw: NEW_FP)

    assert await gr.maybe_schedule_rebuilds(mm) == ["graph_facts_vec"]
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active is not None and active["fingerprint"] == OLD_FP
    assert active["status"] == "active"
    target = await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", NEW_FP)
    assert target["status"] == "building"
    # mixed-space запись в ACTIVE запрещена до promotion.
    assert await mm._vec_write_allowed("graph_facts_vec") is False


# ── 6. `_vec_write_allowed` по фазам: до/во время/после перестройки ─────────

@pytest.mark.asyncio
async def test_vec_write_allowed_follows_generation_lifecycle(vec_db,
                                                              monkeypatch):
    _no_background(monkeypatch)
    mm = _memory(vec_db)
    await _seed_graph_facts(vec_db, 2)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    await _seed_old_build(vec_db, mm)
    monkeypatch.setattr(mm, "_identity_fingerprint", lambda **kw: NEW_FP)
    monkeypatch.setattr(mm, "_embed", _Embed())
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)

    # (1) реестр отстал от identity — записи нет.
    assert await mm._vec_write_allowed("graph_facts_vec") is False

    # (2) поколение зарегистрировано, но build не завершён — всё ещё нет.
    await gr.ensure_current_generation(mm, "graph_facts_vec")
    assert await mm._vec_write_allowed("graph_facts_vec") is False

    # (3) build + validate + activate → запись разрешена.
    await gr.maybe_schedule_rebuilds(mm)
    job = await gr._find_active_job(vec_db, "graph_facts_vec", NEW_FP)
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))
    assert await mm._vec_write_allowed("graph_facts_vec") is True


# ── 7. Честный статус: identity_changed / active / no_generation ────────────

@pytest.mark.asyncio
async def test_generation_status_reports_identity_changed(vec_db, monkeypatch):
    mm = _memory(vec_db)
    await _seed_old_build(vec_db, mm)

    st = await gr.generation_status(vec_db, current_fp=NEW_FP, current_dims=8)
    assert st["current_fp"] == NEW_FP[:12]
    by_index = {i["index"]: i for i in st["indexes"]}
    graph = by_index["graph_facts_vec"]
    assert graph["state"] == "identity_changed"
    assert graph["reason_code"] == "identity_changed"
    assert graph["reindex_required"] is True
    assert graph["active"] is None
    assert graph["latest"]["fingerprint"] == OLD_FP[:12]
    assert graph["dim_mismatch"] is False
    # второй индекс без строк реестра — честно «нет поколения».
    assert by_index["smart_archive"]["state"] == "no_generation"
    assert by_index["smart_archive"]["reindex_required"] is True


@pytest.mark.asyncio
async def test_generation_status_active_and_build_in_progress(vec_db,
                                                              monkeypatch):
    mm = _memory(vec_db)
    await vec_db.ensure_embedding_generation("graph_facts_vec", NEW_FP,
                                             dims=8, activate=True)
    st = await gr.generation_status(vec_db, current_fp=NEW_FP, current_dims=8)
    graph = {i["index"]: i for i in st["indexes"]}["graph_facts_vec"]
    assert graph["state"] == "active" and graph["reindex_required"] is False

    # новое поколение под другой fp → build_in_progress (идёт перестройка)
    other = NEW_FP[:-1] + "c"
    await vec_db.register_embedding_target_generation("graph_facts_vec", other,
                                                      dims=8)
    st = await gr.generation_status(vec_db, current_fp=other, current_dims=8)
    graph = {i["index"]: i for i in st["indexes"]}["graph_facts_vec"]
    assert graph["state"] == "build_in_progress"
    assert graph["reindex_required"] is True


@pytest.mark.asyncio
async def test_generation_status_dim_mismatch_flag(vec_db, monkeypatch):
    mm = _memory(vec_db)
    await _seed_old_build(vec_db, mm)
    st = await gr.generation_status(vec_db, current_fp=NEW_FP, current_dims=16)
    graph = {i["index"]: i for i in st["indexes"]}["graph_facts_vec"]
    assert graph["dim_mismatch"] is True
    assert graph["reason_code"] == "dimension_changed"


# ── 8. Терминальная строка под текущий fp → новое поколение ─────────────────

@pytest.mark.asyncio
async def test_superseded_generation_under_current_fp_registers_new(
        vec_db, monkeypatch):
    _no_background(monkeypatch)
    mm = _memory(vec_db)
    await _seed_graph_facts(vec_db, 2)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    await vec_db.ensure_embedding_generation("graph_facts_vec", NEW_FP,
                                             dims=8, activate=False)
    row = await vec_db.get_generation_by_fingerprint("graph_facts_vec", NEW_FP)
    assert await vec_db.set_embedding_generation_status(
        str(row["generation_id"]), "superseded") is True
    monkeypatch.setattr(mm, "_identity_fingerprint", lambda **kw: NEW_FP)

    fresh = await gr.ensure_current_generation(mm, "graph_facts_vec")
    assert fresh is not None and fresh["status"] == "building"
    assert int(fresh["generation"]) == int(row["generation"]) + 1
    # superseded-строка сохранена (никакого удаления истории).
    old = await vec_db.get_embedding_generation(
        "graph_facts_vec", int(row["generation"]))
    assert old is not None and old["status"] == "superseded"


# ── 9. Fail-open без реестра (тест-двойник/БД без v18) ──────────────────────

@pytest.mark.asyncio
async def test_registryless_db_is_fail_open():
    bare_db = SimpleNamespace()
    memory = SimpleNamespace(db=bare_db, _vec_dim=8,
                             _identity_fingerprint=lambda **kw: NEW_FP)
    assert await gr.maybe_schedule_rebuilds(memory) == []
    assert await gr.ensure_current_generation(memory, "graph_facts_vec") is None
    st = await gr.generation_status(bare_db, current_fp=NEW_FP)
    assert st["indexes"] == []
    assert st["current_fp"] == NEW_FP[:12]
