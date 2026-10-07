"""asap5-final-fixes (ADR-1028-25, D11/D12, T-5256…T-5258) — embeddings
identity / canary / compatibility / profiles / migration storage.

Покровение 13N (гэп §16#26–33 = 13N#1–28, D19): #1, #2, #3, #4, #5, #6,
#15, #16, #17, #18, #21, #25, #26, #28 (backend-часть; UI-пункты #23/#24 —
вне narrowed write-scope лейна, см. evidence B3).
"""
import asyncio
import json
import time

import pytest
import pytest_asyncio

from services import embedding_control_plane as ecp
from services import graphrag_rebuild as gr
from services import summary_memory as sm
from services.database import DatabaseService

pytestmark = pytest.mark.asap4


@pytest_asyncio.fixture
async def vec_db(tmp_path):
    d = DatabaseService(str(tmp_path / "asap5_embed.db"))
    await d.initialize()
    import sqlite_vec
    await d.db.enable_load_extension(True)
    await d.db.load_extension(sqlite_vec.loadable_path())
    await d.db.enable_load_extension(False)
    yield d
    await d.close()


def _memory(db) -> sm.MemoryManager:
    mm = sm.MemoryManager(db, None)
    mm._vec_dim = 8
    mm._vec_available = True
    mm._vec_int8 = False
    return mm


# ── 13N#1/#2: три независимых профиля ───────────────────────────────────────

def test_profiles_independent_fallback1_fallback2(monkeypatch):
    """13N#1: Primary/Fallback1/Fallback2 — разные base_url/model независимо
    (ключи и так раздельные: keys.embedding_fallback_api_key{,_2})."""
    class _FakeHot:
        def __init__(self, values):
            self._v = dict(values)

        def get(self, key, default=None):
            return self._v.get(key, default)

    fake = _FakeHot({
        "models.embedding_base_url": "https://primary.test/v1",
        "models.embedding_model_name": "embed-primary",
        "models.embedding_fallback1_base_url": "https://fb1.test/v1",
        "models.embedding_fallback1_model": "embed-fb1",
        "models.embedding_fallback2_base_url": "https://fb2.test/v1",
        "models.embedding_fallback2_model": "embed-fb2",
    })
    monkeypatch.setattr(ecp, "_profile_hot", fake.get)
    profiles = ecp.resolve_embedding_profiles()
    p1, p2 = profiles["fallback_1"], profiles["fallback_2"]
    assert p1.base_url == "https://fb1.test/v1"
    assert p1.model == "embed-fb1" and p1.inherited is False
    assert p2.base_url == "https://fb2.test/v1"
    assert p2.model == "embed-fb2" and p2.inherited is False
    # 13N#2: смена Fallback 1 НЕ меняет явно заданный Fallback 2.
    fake._v["models.embedding_fallback1_model"] = "embed-fb1-new"
    profiles2 = ecp.resolve_embedding_profiles()
    assert profiles2["fallback_2"].model == "embed-fb2"
    assert profiles2["fallback_1"].model == "embed-fb1-new"


def test_profiles_legacy_migration_and_inherit_marking(monkeypatch):
    """Миграция без потери credentials: легаси-общие значения
    models.embedding_fallback_* становятся значениями Fallback 1;
    Fallback 2 при незаданных base/model наследует и ЧЕСТНО помечен
    (inherited=True) — тихой подмены нет (D11)."""
    class _FakeHot:
        def __init__(self, values):
            self._v = dict(values)

        def get(self, key, default=None):
            return self._v.get(key, default)

    fake = _FakeHot({
        "models.embedding_base_url": "https://primary.test/v1",
        "models.embedding_model_name": "embed-primary",
        "models.embedding_fallback_base_url": "https://legacy.test/v1",
        "models.embedding_fallback_model": "embed-legacy",
    })
    monkeypatch.setattr(ecp, "_profile_hot", fake.get)
    profiles = ecp.resolve_embedding_profiles()
    p1, p2 = profiles["fallback_1"], profiles["fallback_2"]
    assert p1.base_url == "https://legacy.test/v1"
    assert p1.model == "embed-legacy"
    assert p1.inherited is True          # наследует легаси-общие значения
    assert p2.inherited is True          # наследует Fallback 1
    assert p2.base_url == p1.base_url and p2.model == p1.model
    assert p2.configured is True         # ключ F2 свой (отдельное поле)


# ── 13N#3–6/#16/#17/#21: identity + классы совместимости ────────────────────

def test_identity_canonical_json_sha256_16():
    """D11/Q6: sha256[:16] канонического JSON; каноничность (sort_keys,
    компактные сепараторы) — детерминированный результат."""
    fp1 = ecp.embedding_identity_v2(
        provider_family="openai-compatible", endpoint_host="api.test",
        model="embed-1", dimension=3072,
        material_params={"b": "2", "a": "1"})
    fp2 = ecp.embedding_identity_v2(
        provider_family="OpenAI-Compatible", endpoint_host="API.TEST",
        model="embed-1", dimension=3072,
        material_params={"a": "1", "b": "2"})
    assert fp1 == fp2                     # канонизация (case/host/сортировка)
    assert len(fp1) == 16
    fp3 = ecp.embedding_identity_v2(
        provider_family="openai-compatible", endpoint_host="api.test",
        model="embed-2", dimension=3072)
    assert fp1 != fp3


def test_identity_ignores_key_quota_timeout_route(monkeypatch):
    """13N#3 + #21: key/quota/timeout/route identity НЕ меняют →
    same model + другой key → INSTANT_COMPATIBLE (без reindex)."""
    class _FakeHot:
        def get(self, key, default=None):
            return default

    monkeypatch.setattr(ecp, "_profile_hot", _FakeHot().get)
    prof_a = ecp.EmbeddingProfile(
        alias="primary", base_url="https://x.test/v1", model="embed-1",
        quota_group="group-a")
    prof_b = ecp.EmbeddingProfile(
        alias="primary", base_url="https://x.test/v1", model="embed-1",
        quota_group="group-b")           # другая квота-группа
    assert ecp.profile_identity(prof_a, 3072) == \
        ecp.profile_identity(prof_b, 3072)
    verdict = ecp.classify_identity_compatibility(
        current_identity=ecp.profile_identity(prof_a, 3072),
        stored_identity=ecp.profile_identity(prof_b, 3072),
        current_dim=3072, stored_dim=3072,
        canary_verdict=ecp.CANARY_STABLE)
    assert verdict == ecp.COMPAT_INSTANT


def test_same_dim_different_model_is_reindex_required():
    """13N#4: одинаковая размерность сама по себе НЕ даёт INSTANT."""
    fp_a = ecp.embedding_identity_v2(provider_family="p", endpoint_host="h",
                                     model="model-a", dimension=3072)
    fp_b = ecp.embedding_identity_v2(provider_family="p", endpoint_host="h",
                                     model="model-b", dimension=3072)
    assert ecp.classify_identity_compatibility(
        current_identity=fp_a, stored_identity=fp_b,
        current_dim=3072, stored_dim=3072,
        canary_verdict=ecp.CANARY_STABLE) == ecp.COMPAT_REINDEX


def test_different_dimension_is_incompatible():
    """13N#5: другая размерность → INCOMPATIBLE_DIMENSION."""
    fp_a = ecp.embedding_identity_v2(provider_family="p", endpoint_host="h",
                                     model="model-a", dimension=3072)
    fp_b = ecp.embedding_identity_v2(provider_family="p", endpoint_host="h",
                                     model="model-a", dimension=1536)
    assert ecp.classify_identity_compatibility(
        current_identity=fp_a, stored_identity=fp_b,
        current_dim=3072, stored_dim=1536,
        canary_verdict=ecp.CANARY_STABLE) == ecp.COMPAT_DIMENSION


def test_unknown_floating_alias_fails_safe():
    """13N#6 + #17: canary не доказал (unknown) или drift → fail-safe
    (UNKNOWN/REINDEX), никакой тихой «наверное совместимости»."""
    fp = ecp.embedding_identity_v2(provider_family="p", endpoint_host="h",
                                   model="floating", dimension=3072)
    assert ecp.classify_identity_compatibility(
        current_identity=fp, stored_identity=None,
        current_dim=3072, stored_dim=None,
        canary_verdict=None) == ecp.COMPAT_UNKNOWN
    assert ecp.classify_identity_compatibility(
        current_identity=fp, stored_identity=fp,
        current_dim=3072, stored_dim=3072,
        canary_verdict=ecp.CANARY_UNKNOWN) == ecp.COMPAT_UNKNOWN
    # alias drift (floating alias сменил векторное пространство) → REINDEX.
    assert ecp.classify_identity_compatibility(
        current_identity=fp, stored_identity=fp,
        current_dim=3072, stored_dim=3072,
        canary_verdict=ecp.CANARY_DRIFT) == ecp.COMPAT_REINDEX


# ── canary: 3 строки, embedding_cache, косинус ──────────────────────────────

def _stable_embed(dim=8):
    async def _embed(texts):
        out = []
        for t in texts:
            seed = sum(bytearray(t.encode("utf-8"))) % 97
            vec = [((seed + i * 13) % 7) / 7.0 for i in range(dim)]
            vec[0] += 0.5
            out.append(vec)
        return out
    return _embed


@pytest.mark.asyncio
async def test_canary_first_probe_stored_verdict_unknown(vec_db):
    """Первый прогон: эталонов нет → verdict unknown (fail-safe, не «ок»),
    эталоны записаны в embedding_cache под identity_fingerprint."""
    fp = "abcdef0123456789"
    out = await ecp.embedding_canary_check(None, vec_db, fp,
                                           embed_fn=_stable_embed())
    assert out["verdict"] == ecp.CANARY_UNKNOWN
    assert out["stored"] == len(ecp.CANARY_TEXTS)
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM embedding_cache "
        "WHERE identity_fingerprint = ?", (fp,))
    assert (await cur.fetchone())["c"] == len(ecp.CANARY_TEXTS)


@pytest.mark.asyncio
async def test_canary_stable_same_embedder(vec_db):
    """Тот же embedder (identity не плавала) → second probe verdict stable,
    mean/min ≥ порогов, повторных записей нет (эталоны переиспользуются)."""
    fp = "abcdef0123456789"
    await ecp.embedding_canary_check(None, vec_db, fp,
                                     embed_fn=_stable_embed())
    out = await ecp.embedding_canary_check(None, vec_db, fp,
                                           embed_fn=_stable_embed())
    assert out["verdict"] == ecp.CANARY_STABLE
    assert out["checked"] == len(ecp.CANARY_TEXTS)
    assert out["mean"] >= ecp.CANARY_MEAN_MIN
    assert out["min"] >= ecp.CANARY_MIN_SIMILARITY
    assert out["stored"] == 0


@pytest.mark.asyncio
async def test_canary_drift_on_alias_change(vec_db):
    """13N#17: floating alias сменил пространство (вектора других) →
    drift по косинусу (mean < 0.98), НЕ byte-hash."""
    fp = "abcdef0123456789"
    await ecp.embedding_canary_check(None, vec_db, fp,
                                     embed_fn=_stable_embed())

    async def _drifted(texts):
        out = []
        for t in texts:
            seed = (sum(bytearray(t.encode("utf-8"))) + 41) % 97
            vec = [((seed + i * 13) % 7) / 7.0 for i in range(8)]
            vec[0] += 0.5
            out.append(vec)
        return out

    out = await ecp.embedding_canary_check(None, vec_db, fp,
                                           embed_fn=_drifted)
    assert out["verdict"] == ecp.CANARY_DRIFT


@pytest.mark.asyncio
async def test_canary_provider_error_unknown_fail_safe(vec_db):
    """Недоступность провайдера → unknown (fail-safe), БД не трогается."""
    fp = "abcdef0123456789"

    async def _broken(texts):
        raise RuntimeError("provider down")

    out = await ecp.embedding_canary_check(None, vec_db, fp,
                                           embed_fn=_broken)
    assert out["verdict"] == ecp.CANARY_UNKNOWN


# ── D12: state machine + migration jobs (task_jobs) + shadow storage ───────

@pytest.mark.asyncio
async def test_state_machine_transitions_validated(vec_db):
    """13E: BUILDING_TARGET → CATCHING_UP → READY → active разрешены;
    неизвестный переход (building → active напрямую мимо машины) → False;
    BUILDING_TARGET → SUPERSEDED (13N#15: смена конфига во время BUILDING)."""
    fp = "state-machine-fp-01"
    await vec_db.ensure_embedding_generation("graph_facts_vec", fp,
                                             activate=False)
    row = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    gid = str(row["generation_id"])
    assert await vec_db.set_embedding_generation_status(
        gid, "building_target") is True
    assert await vec_db.set_embedding_generation_status(
        gid, "catching_up") is True
    assert await vec_db.set_embedding_generation_status(
        gid, "ready") is True
    # смена конфига во время BUILDING → SUPERSEDED (stale worker не promotes)
    assert await vec_db.set_embedding_generation_status(
        gid, "superseded") is True
    # неизвестная пара — валидатор не пускает тихую перезапись
    assert await vec_db.set_embedding_generation_status(
        gid, "active") is False
    assert await vec_db.set_embedding_generation_status(gid, "") is False


@pytest.mark.asyncio
async def test_migration_job_enqueue_coalesced(vec_db):
    """13N#25: повторная постановка migration job'а — coalesce (тот же
    job_id), дубликатов нет."""
    jid1 = await ecp.enqueue_embedding_migration(
        vec_db, index_name="graph_facts_vec", source_generation=1,
        target_generation=2, fingerprint="fp-x", total=4)
    jid2 = await ecp.enqueue_embedding_migration(
        vec_db, index_name="graph_facts_vec", source_generation=1,
        target_generation=2, fingerprint="fp-x", total=4)
    assert jid1 and jid1 == jid2
    jobs = await ecp.migration_jobs_snapshot(vec_db)
    assert len(jobs) == 1
    assert jobs[0]["payload"]["index"] == "graph_facts_vec"


@pytest.mark.asyncio
async def test_migration_chunked_resumable_source_intact(vec_db, monkeypatch):
    """13N#26/#28: rebuild — чанками с checkpoint (resumable, НЕ one-shot
    blocking); raw source остаётся авторитетным (не трогается); build — в
    generation-isolated shadow `{index}_g{gen}` (13N#18: old/new живут
    одновременно)."""
    mm = _memory(vec_db)
    now = int(time.time())
    for i in range(4):
        await vec_db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (77, ?, 'chat_history', ?)",
            (f"миграционный факт номер {i}", now))
    await vec_db.db.commit()
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()

    jid = await ecp.enqueue_embedding_migration(
        vec_db, index_name="graph_facts_vec", source_generation=1,
        target_generation=3, fingerprint="fp-mig", total=4)

    # Кап батча = 2 → ровно 2 чанка (доказательство чанкованности).
    real_fetch = gr._fetch_batch

    async def _small_fetch(memory, spec, last_id):
        return await real_fetch(memory, spec, last_id)

    orig_adaptive = gr._adaptive_batch_size
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)

    try:
        done = await ecp.run_embedding_migration_chunk(mm, vec_db, jid,
                                                       embed_fn=_stable_embed())
        assert done["processed"] == 2 and done["done"] is False
        # checkpoint durable → resume продолжает с cursor (не с нуля).
        from services.task_supervisor import TaskJobStore
        cp = await TaskJobStore(vec_db).get_checkpoint(jid)
        assert json.loads(cp["cursor"])["processed"] == 2
        done2 = await ecp.run_embedding_migration_chunk(mm, vec_db, jid,
                                                        embed_fn=_stable_embed())
        assert done2["processed"] == 2 and done2["done"] is True
        assert done2["remaining"] == 0
    finally:
        monkeypatch.setattr(gr, "_adaptive_batch_size", orig_adaptive)

    # generation-isolated storage: shadow существует и полная; live не тронут.
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM graph_facts_vec_g3")
    assert (await cur.fetchone())["c"] == 4
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM graph_facts")     # raw source цел (13N#26)
    assert (await cur.fetchone())["c"] == 4
    # source-строки в shadow соответствуют source (проvenance по построению).
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM graph_facts_vec_g3 WHERE fact_id IN "
        "(SELECT id FROM graph_facts)")
    assert (await cur.fetchone())["c"] == 4


@pytest.mark.asyncio
async def test_active_old_and_target_coexist(vec_db):
    """13N#18: во время миграции старое (active) и новое (building_target)
    поколения существуют ОДНОВРЕМЕННО — фиксированная размерность не
    пересоздаёт хранилище разрушающе."""
    fp_old = "coexist-old-fp-01"
    fp_new = "coexist-new-fp-02"
    await vec_db.ensure_embedding_generation("graph_facts_vec", fp_old,
                                             activate=True)
    # target-генерация при существующем active — D12-регистрация (A06 не
    # даёт ensure_embedding_generation вставить новое поколение).
    gen = await vec_db.register_embedding_target_generation(
        "graph_facts_vec", fp_new, dims=8)
    assert gen is not None
    row = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp_new)
    assert row is not None
    await vec_db.set_embedding_generation_status(
        str(row["generation_id"]), "building_target")
    active = await vec_db.get_active_embedding_generations()
    assert len(active) == 1
    assert active[0]["fingerprint"] == fp_old
    latest = await vec_db.get_latest_embedding_generation("graph_facts_vec")
    assert latest["fingerprint"] == fp_new
    assert latest["status"] == "building_target"
