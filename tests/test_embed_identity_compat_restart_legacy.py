"""EMBED-IDENTITY-COMPAT — блокеры ревью B1/B3 (LANE EMBED-IDENTITY-FIX2).

B1 (рестарт): пауза «до вердикта совместимости» отличалась от операторской
только process-set `_PAUSED_BY_COMPAT`. После рестарта доказанная
несовместимость НЕ возобновляла сборку: job оставался `paused`, планировщик
возвращал `[]`, индекс навсегда FTS-only, панель рапортовала сборку. Фикс:
durable `reason_code=paused_compat_insufficient` — авторитет снятия паузы.

B3 (legacy-метаданные): у строк реестра от 29.09 `preprocessing_version`
может быть NULL. Прежний `generation_space_identity` возвращал MSI с пустой
версией предобработки, что давало `incompatible` → полную перевекторизацию.
Фикс: MSI выводится из СОХРАНЁННОГО fingerprint, когда это однозначно; иначе
— `insufficient(legacy_metadata_missing)`, без rebuild/adopt.

Фикстуры (реальная SQLite + sqlite-vec, мок только HTTP-embed) берутся из
контрактного файла `test_embed_identity_compat.py`, чтобы не расходиться.

TEST-LIFECYCLE: REGRESSION owner=EMBED-IDENTITY-COMPAT/B1+B3
"""
import time

import pytest
import pytest_asyncio

from services import embedding_control_plane as ecp
from services import graphrag_rebuild as gr
from services import hot_config
from services import summary_memory as sm
from services.database import DatabaseService
from tests import test_embed_identity_compat as contract

DIMS = contract.DIMS
INDEX = contract.INDEX


@pytest_asyncio.fixture
async def ctx(tmp_path, monkeypatch):
    """Та же среда, что в контрактном файле (одна БД на тест)."""
    ecp.reset_compat_state()
    db = DatabaseService(str(tmp_path / "embed_b1b3.db"))
    await db.initialize()
    import sqlite_vec
    await db.db.enable_load_extension(True)
    await db.db.load_extension(sqlite_vec.loadable_path())
    await db.db.enable_load_extension(False)
    hot = contract._Hot()
    monkeypatch.setattr(hot_config, "get", hot.get)
    monkeypatch.setattr(sm, "fire_and_forget", lambda coro, tag: coro.close())
    mm = sm.MemoryManager(db, None)
    mm._vec_dim = DIMS
    mm._vec_available = True
    mm._vec_int8 = False
    try:
        yield contract.SimpleNamespace(db=db, mm=mm, hot=hot)
    finally:
        ecp.reset_compat_state()
        await db.close()


def _restarted(ctx):
    """«Рестарт процесса»: новый MemoryManager (process-состояние уже сброшено)."""
    mm = sm.MemoryManager(ctx.db, None)
    mm._vec_dim = DIMS
    mm._vec_available = True
    mm._vec_int8 = False
    return mm


async def _running_job(ctx, fp: str, generation: int) -> str:
    job_id = await gr._ensure_job(ctx.db, INDEX, fp, generation)
    assert job_id
    await gr._job_cas(ctx.db, job_id, expect=gr.ST_QUEUED,
                      set_status=gr.ST_RUNNING)
    return job_id


async def _legacy_row(ctx, generation_id: int, **columns) -> dict:
    """Прямая правка строки реестра = «legacy-данные без MSI-полей» (B3)."""
    allowed = {"preprocessing_version", "fingerprint", "provider", "model",
               "dims", "endpoint_fingerprint"}
    assert set(columns) <= allowed
    sets = ", ".join(f"{name} = ?" for name in columns)
    await ctx.db.db.execute(
        f"UPDATE mca_embedding_index_generations SET {sets} "
        "WHERE generation_id = ?",
        (*columns.values(), int(generation_id)))
    await ctx.db.db.commit()
    cursor = await ctx.db.db.execute(
        "SELECT * FROM mca_embedding_index_generations WHERE generation_id = ?",
        (int(generation_id),))
    return dict(await cursor.fetchone())


# ── B1: пауза переживает рестарт ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_b1_restart_then_incompatible_resumes_migration(ctx):
    """repro ревью: running → insufficient → paused → РЕСТАРТ →
    incompatible. Было: job остаётся paused, планировщик `[]`. Стало:
    job `queued`, миграция планируется, live не тронут."""
    docs = contract._docs()
    await contract._seed(ctx, docs)
    old_fp, new_fp = contract._gateway_swap(ctx)
    await contract._register_generation(ctx, old_fp)
    target = await contract._register_generation(ctx, new_fp)
    job_id = await _running_job(ctx, new_fp, int(target["generation"]))

    pending = await contract._ensure(ctx, new_fp, contract._Embedder(fail=True))
    assert pending["state"] == ecp.STATE_INSUFFICIENT
    paused = await gr._get_job(ctx.db, job_id)
    assert paused["status"] == gr.ST_PAUSED
    assert paused["reason_code"] == gr.COMPAT_PAUSE_REASON, \
        "пауза обязана отличаться от операторской durable reason_code"

    # ── РЕСТАРТ: process-состояние (в т.ч. _PAUSED_BY_COMPAT) пусто ──
    ecp.reset_compat_state()
    restarted = _restarted(ctx)

    proven = await ecp.ensure_index_compat(
        ctx.db, INDEX, current_fp=new_fp, current_dims=DIMS,
        embed_fn=contract._Embedder(space="space-b"), force_probe=True)
    assert proven["state"] == ecp.STATE_INCOMPATIBLE
    resumed = await gr._get_job(ctx.db, job_id)
    assert resumed["status"] == gr.ST_QUEUED, \
        "доказанная несовместимость обязана снять compat-паузу после рестарта"

    assert await gr.maybe_schedule_rebuilds(restarted) == [INDEX]
    assert await contract._count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") == len(docs)


@pytest.mark.asyncio
async def test_b1_restart_then_insufficient_keeps_pause_without_rebuild(
        ctx, monkeypatch):
    """insufficient → рестарт → снова insufficient: пауза ОСТАЁТСЯ (никакого
    авто-возобновления), rebuild не стартует, панель не врёт про сборку."""
    docs = contract._docs()
    await contract._seed(ctx, docs)
    old_fp, new_fp = contract._gateway_swap(ctx)
    await contract._register_generation(ctx, old_fp)
    target = await contract._register_generation(ctx, new_fp)
    job_id = await _running_job(ctx, new_fp, int(target["generation"]))

    assert (await contract._ensure(ctx, new_fp, contract._Embedder(fail=True)))[
        "state"] == ecp.STATE_INSUFFICIENT
    assert (await gr._get_job(ctx.db, job_id))["status"] == gr.ST_PAUSED

    ecp.reset_compat_state()
    restarted = _restarted(ctx)
    monkeypatch.setattr(restarted, "_embed", contract._Embedder(fail=True))
    again = await ecp.ensure_index_compat(
        ctx.db, INDEX, current_fp=new_fp, current_dims=DIMS,
        embed_fn=contract._Embedder(fail=True), force_probe=True)
    assert again["state"] == ecp.STATE_INSUFFICIENT

    still = await gr._get_job(ctx.db, job_id)
    assert still["status"] == gr.ST_PAUSED
    assert still["reason_code"] == gr.COMPAT_PAUSE_REASON
    assert await gr.maybe_schedule_rebuilds(restarted) == []
    assert (await gr._get_job(ctx.db, job_id))["status"] == gr.ST_PAUSED

    health = await gr.generation_status(ctx.db, current_fp=new_fp,
                                        current_dims=DIMS)
    graph = {i["index"]: i for i in health["indexes"]}[INDEX]
    assert graph["state"] == "compat_insufficient"
    assert graph["reason_code"] == gr.COMPAT_PAUSE_REASON
    assert graph["reindex_required"] is False, \
        "замороженная сборка не выдаётся за «требуется reindex»"
    assert await contract._count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") == len(docs)


@pytest.mark.asyncio
async def test_b1_adopt_cancels_orphaned_compat_pause(ctx):
    """compatible/adopt снимает compat-паузу даже когда строки реестра под её
    fingerprint уже нет (иначе джоба висела бы paused вечно)."""
    await contract._seed(ctx, contract._docs())
    old_fp, new_fp = contract._gateway_swap(ctx)
    await contract._register_generation(ctx, old_fp)
    orphan = await _running_job(ctx, "orphan-fp", 7)
    assert await gr._job_cas(ctx.db, orphan, expect=gr.ST_RUNNING,
                             set_status=gr.ST_PAUSED,
                             reason_code=gr.COMPAT_PAUSE_REASON)

    result = await contract._ensure(ctx, new_fp,
                                    contract._Embedder(space="space-a"))
    assert result["state"] == ecp.STATE_COMPATIBLE
    assert (await gr._get_job(ctx.db, orphan))["status"] == gr.ST_CANCELLED
    assert (await ctx.db.get_active_embedding_generation(INDEX))[
        "fingerprint"] == old_fp


@pytest.mark.asyncio
async def test_b1_compatible_admission_cancels_stale_compat_pause(ctx):
    """Крэш между записью допуска и отменой сборки не оставляет вечную паузу:
    при `compatible` висящая compat-пауза снимается."""
    await contract._seed(ctx, contract._docs())
    old_fp, new_fp = contract._gateway_swap(ctx)
    await contract._register_generation(ctx, old_fp)
    assert (await contract._ensure(ctx, new_fp,
                                   contract._Embedder(space="space-a")))[
        "state"] == ecp.STATE_COMPATIBLE
    stale = await _running_job(ctx, new_fp, 2)
    assert await gr._job_cas(ctx.db, stale, expect=gr.ST_RUNNING,
                             set_status=gr.ST_PAUSED,
                             reason_code=gr.COMPAT_PAUSE_REASON)

    again = await contract._ensure(ctx, new_fp, contract._Embedder(fail=True))
    assert again["state"] == ecp.STATE_COMPATIBLE
    assert (await gr._get_job(ctx.db, stale))["status"] == gr.ST_CANCELLED


# ── B3: legacy-метаданные старых поколений ─────────────────────────────────

@pytest.mark.asyncio
async def test_b3_legacy_null_preprocessing_derives_space_and_adopts(ctx):
    """Строка от 29.09 без `preprocessing_version` НЕ делает index
    `incompatible`: MSI выводится из сохранённого fingerprint (прод-A0:
    старый индекс и новый шлюз совместимы) → проба → adopt, без rebuild."""
    docs = contract._docs()
    await contract._seed(ctx, docs)
    old_fp, new_fp = contract._gateway_swap(ctx)
    row = await contract._register_generation(ctx, old_fp)
    legacy = await _legacy_row(
        ctx, row["generation_id"], preprocessing_version=None,
        endpoint_fingerprint=sm._endpoint_fingerprint(contract.OLD_HOST))
    assert legacy["model"] == contract.MODEL and legacy["dims"] == DIMS
    assert ecp.generation_space_provenance(legacy) == "fingerprint"
    assert ecp.generation_space_identity(legacy) == ecp.model_space_identity(
        model=contract.MODEL, dimension=DIMS)

    compat = await contract._resolve(ctx, new_fp)
    assert compat["state"] != ecp.STATE_INCOMPATIBLE, \
        "legacy-строка не является доказательством другого пространства"
    assert compat["reason_code"] == "compat_not_proven"
    assert compat["needs_probe"] is True
    assert compat["candidate"]["fingerprint"] == old_fp
    # target-поколение (то есть полная перевекторизация) не регистрируется
    assert await gr.ensure_current_generation(ctx.mm, INDEX,
                                              current_fp=new_fp) is None
    assert await ctx.db.get_generation_by_fingerprint(INDEX, new_fp) is None

    result = await contract._ensure(ctx, new_fp,
                                    contract._Embedder(space="space-a"))
    assert result["state"] == ecp.STATE_COMPATIBLE
    assert result["class"] == ecp.COMPAT_ADMITTED
    assert (await ctx.db.get_active_embedding_generation(INDEX))[
        "fingerprint"] == old_fp
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == []
    assert await contract._count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") == len(docs)


@pytest.mark.asyncio
async def test_b3_legacy_without_derivable_msi_is_insufficient(ctx):
    """Провенанс недоказуем (NULL preproc + невоспроизводимый fingerprint):
    `insufficient(legacy_metadata_missing)` — ни rebuild, ни adopt, данные целы."""
    docs = contract._docs()
    await contract._seed(ctx, docs)
    old_fp, new_fp = contract._gateway_swap(ctx)
    row = await contract._register_generation(ctx, old_fp)
    legacy = await _legacy_row(ctx, row["generation_id"],
                               preprocessing_version=None,
                               provider=None,
                               fingerprint="96f8080000000000" * 4)
    assert ecp.generation_space_provenance(legacy) == ""

    compat = await contract._resolve(ctx, new_fp)
    assert compat["state"] == ecp.STATE_INSUFFICIENT
    assert compat["reason_code"] == "legacy_metadata_missing"
    assert compat["action"] == "need_old_vectors"
    assert compat["needs_probe"] is False
    assert compat["legacy_rows"] == 1

    assert await gr.ensure_current_generation(ctx.mm, INDEX,
                                              current_fp=new_fp) is None
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == []
    assert await ctx.db.get_generation_by_fingerprint(INDEX, new_fp) is None
    assert await ctx.db.get_active_embedding_generation(INDEX) is None
    assert await ctx.mm._vec_write_allowed(INDEX) is False
    assert await contract._count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") == len(docs)
    assert await contract._count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts") == len(docs)
    rows = await contract._generation_rows(ctx.db)
    assert [r["status"] for r in rows] == ["building"], \
        "legacy-строка не переводится в target/active"


@pytest.mark.asyncio
async def test_b3_active_legacy_without_msi_never_rebuilds(ctx):
    """ACTIVE-строка без выводимого MSI — тоже `insufficient`, не `incompatible`
    (иначе рестарт прода запускал бы полную перевекторизацию)."""
    docs = contract._docs()
    await contract._seed(ctx, docs)
    old_fp, new_fp = contract._gateway_swap(ctx)
    await contract._register_generation(ctx, old_fp, status="active")
    cursor = await ctx.db.db.execute(
        "SELECT generation_id FROM mca_embedding_index_generations "
        "WHERE index_name = ? AND status = 'active'", (INDEX,))
    gen_id = int((await cursor.fetchone())["generation_id"])
    await _legacy_row(ctx, gen_id, model=None, preprocessing_version=None)

    compat = await contract._resolve(ctx, new_fp)
    assert compat["state"] == ecp.STATE_INSUFFICIENT
    assert compat["reason_code"] == "legacy_metadata_missing"
    assert compat["action"] == "need_old_vectors"

    assert await gr.ensure_current_generation(ctx.mm, INDEX,
                                              current_fp=new_fp) is None
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == []
    assert await contract._count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") == len(docs)
    active = await ctx.db.get_active_embedding_generation(INDEX)
    assert active["fingerprint"] == old_fp, "провенанс не перезаписывается"


# ── anti-regression: операторская пауза НЕ авто-возобновляется ──────────────

@pytest.mark.asyncio
async def test_b1_operator_pause_is_never_auto_resumed(ctx):
    """`reason_code='paused'` (оператор) резолвер не трогает даже при
    доказанной несовместимости."""
    docs = contract._docs()
    await contract._seed(ctx, docs)
    old_fp, new_fp = contract._gateway_swap(ctx)
    await contract._register_generation(ctx, old_fp)
    target = await contract._register_generation(ctx, new_fp)
    job_id = await gr._ensure_job(ctx.db, INDEX, new_fp,
                                  int(target["generation"]))
    await gr._job_cas(ctx.db, job_id, expect=gr.ST_QUEUED,
                      set_status=gr.ST_RUNNING)
    assert await gr.pause_rebuild(ctx.db, INDEX)      # операторская пауза
    assert (await gr._get_job(ctx.db, job_id))["reason_code"] == "paused"

    proven = await contract._ensure(ctx, new_fp,
                                    contract._Embedder(space="space-b"))
    assert proven["state"] == ecp.STATE_INCOMPATIBLE
    job = await gr._get_job(ctx.db, job_id)
    assert job["status"] == gr.ST_PAUSED
    assert job["reason_code"] == "paused"


# ── точка отсчёта производительности фикстур (не сеть) ─────────────────────

@pytest.mark.asyncio
async def test_b3_resolver_is_read_only(ctx):
    """Резолвер (в т.ч. с legacy-строками) не пишет ничего: ΔDDL=0 и
    отсутствие мутаций реестра/live проверяются счётчиками."""
    docs = contract._docs()
    await contract._seed(ctx, docs)
    old_fp, new_fp = contract._gateway_swap(ctx)
    row = await contract._register_generation(ctx, old_fp)
    await _legacy_row(ctx, row["generation_id"], preprocessing_version=None)
    before = await contract._generation_rows(ctx.db)
    before_ts = int(time.time())
    await contract._resolve(ctx, new_fp)
    after = await contract._generation_rows(ctx.db)
    assert after == before
    assert int(after[0]["created_at"]) <= before_ts
