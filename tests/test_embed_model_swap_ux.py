# -*- coding: utf-8 -*-
"""MODEL-SWAP-01..05 — смена embedding-модели (owner §2, 24.11.2026).

Контракт (finite acceptance):

* MODEL-SWAP-01: смена только провайдера/ключа/адреса не показывает
  предупреждение и не создаёт поколение/rebuild (включая canonical-имена
  `models/gemini-embedding-001` == `gemini-embedding-001`).
* MODEL-SWAP-02: реальная смена модели/размерности → явное предупреждение
  в «Модели и подключения»: старая модель, новая модель, причина; до
  подтверждения rebuild не стартует.
* MODEL-SWAP-03: подтверждение → фоновая resumable-перестройка (прогресс,
  число обработанных, ошибки, состояние), продолжение после рестарта,
  отмена, восстановление после сбоя.
* MODEL-SWAP-04: пока новый индекс строится, прежний ACTIVE-индекс
  продолжает обслуживать память (конфиг модели не меняется); при её
  недоступности остаются FTS/граф/эпизоды/архив/оперативный контекст.
* MODEL-SWAP-05: несовместимые векторы не смешиваются: новые пишутся в
  shadow, live-swap и переключение конфига — только после готовности ВСЕХ
  target-индексов; исходные факты/история не меняются.

Плюс браузерный UI-контракт (Playwright, 1440 + 390): предупреждение,
прогресс/состояние/ошибки, отсутствие горизонтального overflow и console
errors; провайдер-only изменение сохраняется без предупреждения.

TEST-LIFECYCLE: CONTRACT owner=MODEL-SWAP-01..05
"""
import copy
import functools
import json
import socket
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import pytest_asyncio

from services import embedding_control_plane as ecp
from services import graphrag_rebuild as gr
from services import hot_config
from services import summary_memory as sm
from services.database import DatabaseService
from web.api import memory_agi as magi

ROOT = Path(__file__).resolve().parent.parent
OLD_MODEL = "gemini-embedding-001"
NEW_MODEL = "text-embedding-3-large"
DIM = 8

pytestmark = [pytest.mark.asap4]


# ── fixtures/helpers ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def vec_db(tmp_path):
    d = DatabaseService(str(tmp_path / "model_swap.db"))
    await d.initialize()
    import sqlite_vec
    await d.db.enable_load_extension(True)
    await d.db.load_extension(sqlite_vec.loadable_path())
    await d.db.enable_load_extension(False)
    yield d
    await d.close()


class _HotModel:
    def __init__(self, model=OLD_MODEL, dim=DIM, base_url="https://primary.test/v1"):
        self.model = model
        self.dim = dim
        self.base_url = base_url

    def get(self, key, default=None):
        if key == "models.embedding_model_name":
            return self.model
        if key == "models.embedding_dim":
            return self.dim
        if key == "models.embedding_base_url":
            return self.base_url
        if key == "models.embedding_quota_group":
            return ""
        return default


def _use_hot(monkeypatch, hot_fake):
    monkeypatch.setattr(hot_config, "get", hot_fake.get)
    return hot_fake


class _Cache:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set_many(self, items):
        for key, value, _cat in items:
            self.values[key] = value


@pytest.fixture(autouse=True)
def _isolate_cache():
    old = hot_config.get_config_cache()
    hot_config.set_config_cache(None)
    yield
    hot_config.set_config_cache(old)


class _ModelEmbed:
    """Детерминированный embed по target-модели (без сети).

    Значения РАЗНЫЕ для старого/нового пространства — тест может доказать,
    что live-индекс до переключения содержит только старые векторы.
    """

    def __init__(self, dim=DIM):
        self.dim = dim
        self.calls = []

    async def __call__(self, llm, texts, *, priority=None, max_wait_s=None,
                       model_override=None):
        self.calls.append((model_override, list(texts)))
        base = 0.9 if model_override == NEW_MODEL else 0.1
        return [[base + 0.01 * ((i + j) % 5) for j in range(self.dim)]
                for i, _ in enumerate(texts)]


def _memory(db, dim=DIM):
    mm = sm.MemoryManager(db, None)
    mm._vec_dim = dim
    mm._vec_available = True
    mm._vec_int8 = False
    return mm


def _no_background(monkeypatch):
    def _fake(coro, tag):
        coro.close()

    monkeypatch.setattr(sm, "fire_and_forget", _fake)


async def _seed_graph(db, n=4, chat_id=77):
    now = int(time.time())
    for i in range(n):
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (?, ?, 'chat_history', ?)",
            (chat_id, f"факт {i} про смену embedding-модели", now))
    await db.db.commit()


async def _seed_old_index(db, n=4, dim=DIM):
    """ACTIVE-поколение текущего конфига + live-векторы старого пространства."""
    fp = sm.embedding_identity_fingerprint()
    await db.ensure_embedding_generation(
        "graph_facts_vec", fp,
        provider=sm._embedding_provider(),
        model=OLD_MODEL, dims=dim,
        preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint=sm._endpoint_fingerprint(), activate=True)
    mm = _memory(db, dim)
    await db.db.execute(mm._graph_vec_table_sql(dim))
    for i in range(1, n + 1):
        await db.db.execute(
            "INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, "
            "expires_at, embedding) VALUES (?, ?, ?, 'chat_history', NULL, ?)",
            (i, i, 77, json.dumps([0.5] * dim)))
    await db.db.commit()
    await _seed_graph(db, n)


async def _row(db, fp):
    return await db.get_generation_by_fingerprint("graph_facts_vec", fp)


async def _live_values(db):
    cur = await db.db.execute(
        "SELECT embedding FROM graph_facts_vec ORDER BY rowid")
    rows = await cur.fetchall()
    return [gr._read_vector(r["embedding"]) for r in rows]


def _target_row_and_fp():
    return sm.embedding_identity_fingerprint(
        provider=sm._embedding_provider(), model=NEW_MODEL, dims=DIM,
        preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint=sm._endpoint_fingerprint())


# ── MODEL-SWAP-01: provider/key only → no warning, no generation ────────────

@pytest.mark.asyncio
async def test_model_swap_01_provider_only_no_generation(vec_db, monkeypatch):
    hot_fake = _use_hot(monkeypatch, _HotModel())
    await _seed_old_index(vec_db)
    before = await vec_db.get_active_embedding_generation("graph_facts_vec")

    # Смена только адреса/провайдера при той же модели — не смена пространства.
    hot_fake.base_url = "https://new-provider.test/v1"
    res = await gr.start_model_swap(vec_db, model=OLD_MODEL, dims=DIM)
    assert res["ok"] is True and res["required"] is False
    assert res["reason"] == "same_space"
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_embedding_index_generations")
    assert int((await cur.fetchone())["c"]) == 1
    after = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert after["fingerprint"] == before["fingerprint"]
    assert await gr.model_swap_state(vec_db) is None


@pytest.mark.asyncio
async def test_model_swap_01_canonical_model_name_is_same_space(
        vec_db, monkeypatch):
    _use_hot(monkeypatch, _HotModel())
    await _seed_old_index(vec_db)
    res = await gr.start_model_swap(
        vec_db, model="google/models/gemini-embedding-001", dims=DIM)
    assert res["required"] is False
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_embedding_index_generations")
    assert int((await cur.fetchone())["c"]) == 1


# ── MODEL-SWAP-02: real model change → warning with old/new/reason ──────────

@pytest.mark.asyncio
async def test_model_swap_02_warning_names_old_and_new(vec_db, monkeypatch):
    _use_hot(monkeypatch, _HotModel())
    await _seed_old_index(vec_db)
    monkeypatch.setattr(magi, "_require_global_admin", lambda *a, **k: None)
    monkeypatch.setattr(magi, "_db_or_503", lambda: vec_db)
    out = await magi.memory_embedding_change_preview(
        None, object(), model=NEW_MODEL, dim=DIM)
    assert out["requires_rebuild"] is True
    assert out["old_model"] == OLD_MODEL
    assert out["new_model"] == NEW_MODEL
    assert str(out["old_dims"]) == str(DIM)
    assert NEW_MODEL in out["reason"] and OLD_MODEL in out["reason"]
    assert "перестрой" in out["reason"].lower()
    # До подтверждения поколение/rebuild не создаются.
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_embedding_index_generations")
    assert int((await cur.fetchone())["c"]) == 1
    assert await gr.model_swap_state(vec_db) is None


@pytest.mark.asyncio
async def test_model_swap_02_dimension_only_requires_rebuild(
        vec_db, monkeypatch):
    _use_hot(monkeypatch, _HotModel())
    await _seed_old_index(vec_db)
    monkeypatch.setattr(magi, "_require_global_admin", lambda *a, **k: None)
    monkeypatch.setattr(magi, "_db_or_503", lambda: vec_db)
    out = await magi.memory_embedding_change_preview(
        None, object(), model=OLD_MODEL, dim=4)
    assert out["requires_rebuild"] is True
    assert "Размерность" in out["reason"]


# ── MODEL-SWAP-03/04/05: background build; old index serves; no mixing ──────

@pytest.mark.asyncio
async def test_model_swap_03_04_05_full_flow(vec_db, monkeypatch):
    _use_hot(monkeypatch, _HotModel())
    cache = _Cache()
    hot_config.set_config_cache(cache)
    await _seed_old_index(vec_db)
    mm = _memory(vec_db)
    embed = _ModelEmbed()
    monkeypatch.setattr(ecp, "execute_embed", embed)
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)
    _no_background(monkeypatch)

    start = await gr.start_model_swap(vec_db, model=NEW_MODEL, dims=DIM)
    assert start["ok"] is True and start["required"] is True
    target_fp = _target_row_and_fp()
    target = await _row(vec_db, target_fp)
    assert target["status"] == "building"
    assert target["config_revision"] == gr.MODEL_SWAP_PREFIX + \
        ecp.model_space_identity(model=OLD_MODEL, dimension=DIM)

    # Старый индекс продолжает обслуживать память; конфиг НЕ изменён.
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == OLD_MODEL and active["status"] == "active"
    assert cache.values.get("models.embedding_model_name") is None
    state = await gr.model_swap_state(vec_db)
    assert state["pending"] is True
    assert state["old_model"] == OLD_MODEL and state["new_model"] == NEW_MODEL
    assert state["old_index_serving"] is True
    assert state["processed"] == 0 and state["total"] == 4
    assert await mm._index_generation_ok("graph_facts_vec") is True
    old_live = await _live_values(vec_db)
    assert all(v == [0.5] * DIM for v in old_live)

    assert await gr.maybe_schedule_rebuilds(mm) == ["graph_facts_vec"]
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)
    assert job is not None and job["status"] == gr.ST_QUEUED
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))

    # Новое поколение активно, конфиг переключён, старые факты целы.
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == NEW_MODEL
    assert cache.values["models.embedding_model_name"] == NEW_MODEL
    assert cache.values["models.embedding_dim"] == DIM
    job = await gr._get_job(vec_db, job["job_id"])
    assert job["status"] == gr.ST_ACTIVATED
    cur = await vec_db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
    assert int((await cur.fetchone())["c"]) == 4
    new_live = await _live_values(vec_db)
    assert len(new_live) == 4
    # Новые векторы — только новое пространство (смешивания нет).
    assert new_live != old_live
    assert any(abs(v[0] - 0.5) > 0.1 for v in new_live)
    assert any(model == NEW_MODEL for model, _ in embed.calls)
    state = await gr.model_swap_state(vec_db)
    assert state["pending"] is False and state["state"] == "active"


@pytest.mark.asyncio
async def test_model_swap_05_source_change_during_build_never_activates(
        vec_db, monkeypatch):
    hot_fake = _use_hot(monkeypatch, _HotModel())
    hot_config.set_config_cache(_Cache())
    await _seed_old_index(vec_db)
    mm = _memory(vec_db)
    monkeypatch.setattr(ecp, "execute_embed", _ModelEmbed())
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)
    _no_background(monkeypatch)

    await gr.start_model_swap(vec_db, model=NEW_MODEL, dims=DIM)
    target_fp = _target_row_and_fp()
    await gr.maybe_schedule_rebuilds(mm)
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)

    # Конфиг неожиданно сменился во время сборки (вне подтверждённого flow).
    hot_fake.model = "another-model"
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))

    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == OLD_MODEL            # старый индекс не тронут
    job = await gr._get_job(vec_db, job["job_id"])
    assert job["status"] in (gr.ST_FAILED, gr.ST_VALIDATION_FAILED)
    assert job["reason_code"] == "source_space_changed"
    assert all(v == [0.5] * DIM for v in await _live_values(vec_db))


@pytest.mark.asyncio
async def test_model_swap_03_resume_after_restart_from_checkpoint(
        vec_db, monkeypatch):
    _use_hot(monkeypatch, _HotModel())
    hot_config.set_config_cache(_Cache())
    await _seed_old_index(vec_db)
    embed = _ModelEmbed()
    monkeypatch.setattr(ecp, "execute_embed", embed)
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)
    _no_background(monkeypatch)

    await gr.start_model_swap(vec_db, model=NEW_MODEL, dims=DIM)
    target_fp = _target_row_and_fp()
    target = await _row(vec_db, target_fp)
    shadow = gr._shadow_name("graph_facts_vec", int(target["generation"]))
    mm = _memory(vec_db)
    await gr._create_shadow(mm, "graph_facts_vec", shadow, dims=DIM)
    for i in (1, 2):
        await vec_db.db.execute(
            f"INSERT INTO {shadow}(rowid, fact_id, chat_id, origin, "
            "expires_at, embedding) VALUES (?, ?, ?, 'chat_history', NULL, ?)",
            (i, i, 77, json.dumps([0.5] * DIM)))
    await vec_db.db.commit()
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)
    from services.task_supervisor import TaskJobStore
    await TaskJobStore(vec_db).save_checkpoint(
        str(job["job_id"]),
        cursor_token=json.dumps({"last_id": 2, "processed": 2}),
        processed=2, checkpoint_ref="cp:model_swap:test")
    await gr._job_cas(vec_db, str(job["job_id"]), expect=gr.ST_QUEUED,
                      set_status=gr.ST_QUEUED, reason_code="restart_resume")

    # «Рестарт»: новый MemoryManager, планировщик обязан поднять durable job.
    mm2 = _memory(vec_db)
    assert await gr.maybe_schedule_rebuilds(mm2) == ["graph_facts_vec"]
    await gr.run_job(mm2, "graph_facts_vec", str(job["job_id"]))

    # Первый батч после рестарта — только оставшиеся факты (id > 2).
    assert embed.calls and all(
        all("факт 3" in t or "факт 2" in t or "факт " in t for t in texts)
        for _, texts in embed.calls)
    assert "факт 1 про смену embedding-модели" not in embed.calls[0][1]
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == NEW_MODEL


@pytest.mark.asyncio
async def test_model_swap_03_cancel_keeps_old_index(vec_db, monkeypatch):
    _use_hot(monkeypatch, _HotModel())
    hot_config.set_config_cache(_Cache())
    await _seed_old_index(vec_db)
    _no_background(monkeypatch)
    await gr.start_model_swap(vec_db, model=NEW_MODEL, dims=DIM)
    target_fp = _target_row_and_fp()

    out = await gr.cancel_model_swap(vec_db)
    assert "graph_facts_vec" in out["cancelled"]
    target = await _row(vec_db, target_fp)
    assert target["status"] == "cancelled"
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)
    assert job["status"] == gr.ST_CANCELLED
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == OLD_MODEL
    assert all(v == [0.5] * DIM for v in await _live_values(vec_db))
    assert await gr.model_swap_state(vec_db) is None


@pytest.mark.asyncio
async def test_model_swap_03_crash_after_ready_finalized_by_tick(
        vec_db, monkeypatch):
    _use_hot(monkeypatch, _HotModel())
    cache = _Cache()
    hot_config.set_config_cache(cache)
    await _seed_old_index(vec_db)
    monkeypatch.setattr(ecp, "execute_embed", _ModelEmbed())
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)
    _no_background(monkeypatch)
    await gr.start_model_swap(vec_db, model=NEW_MODEL, dims=DIM)
    target_fp = _target_row_and_fp()
    await gr.maybe_schedule_rebuilds(_memory(vec_db))
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)

    original = gr._finalize_model_swap

    async def _crash(*a, **k):
        return False

    monkeypatch.setattr(gr, "_finalize_model_swap", _crash)
    await gr.run_job(_memory(vec_db), "graph_facts_vec", str(job["job_id"]))
    target = await _row(vec_db, target_fp)
    assert target["status"] == "ready"
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == OLD_MODEL            # переключение ещё не было

    monkeypatch.setattr(gr, "_finalize_model_swap", original)
    mm = _memory(vec_db)
    await gr.maybe_schedule_rebuilds(mm)
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == NEW_MODEL
    assert cache.values["models.embedding_model_name"] == NEW_MODEL


@pytest.mark.asyncio
async def test_model_swap_05_dimension_change_switches_ddl(vec_db, monkeypatch):
    _use_hot(monkeypatch, _HotModel())
    cache = _Cache()
    hot_config.set_config_cache(cache)
    await _seed_old_index(vec_db, dim=DIM)
    monkeypatch.setattr(ecp, "execute_embed", _ModelEmbed(dim=4))
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)
    _no_background(monkeypatch)
    mm = _memory(vec_db)

    await gr.start_model_swap(vec_db, model=NEW_MODEL, dims=4)
    target_fp = sm.embedding_identity_fingerprint(
        provider=sm._embedding_provider(), model=NEW_MODEL, dims=4,
        preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint=sm._endpoint_fingerprint())
    await gr.maybe_schedule_rebuilds(mm)
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))

    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == NEW_MODEL and int(active["dims"]) == 4
    assert cache.values["models.embedding_dim"] == 4
    assert mm._vec_dim == 4
    cur = await vec_db.db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='graph_facts_vec'")
    ddl = (await cur.fetchone())["sql"]
    assert "float[4]" in ddl
    assert all(len(v) == 4 for v in await _live_values(vec_db))


@pytest.mark.asyncio
async def test_model_swap_03_executor_uses_target_model_override(
        monkeypatch):
    cred = ecp.EmbeddingCredential(
        alias="primary", api_key="k", base_url="https://p.test/v1",
        model=OLD_MODEL, provider="p.test", quota_group_id="primary",
        quota_group_known=True, quota_group_source="auto", key_source="hot")
    monkeypatch.setattr(ecp, "build_credential_pool", lambda: [cred])
    executor = ecp.EmbeddingExecutor(object())
    seen = []

    async def _call(adapter, credential, texts, stats):
        seen.append((credential.model, list(texts)))
        return [[0.25] * DIM for _ in texts]

    monkeypatch.setattr(executor, "_call_with_segmentation", _call)
    out = await executor.embed(["a", "b"], priority=ecp.Priority.P3_REBUILD,
                               model_override=NEW_MODEL)
    assert len(out) == 2 and out[0] == [0.25] * DIM
    assert seen and seen[0][0] == NEW_MODEL
    assert seen[0][1] == ["a", "b"]


@pytest.mark.asyncio
async def test_model_swap_f1_provider_change_during_build_keeps_rebuild(
        vec_db, monkeypatch):
    """F1: смена провайдера/URL во время сборки — пространство то же (MSI),
    перестройка продолжается и активируется (ложного failed нет)."""
    hot_fake = _use_hot(monkeypatch, _HotModel())
    cache = _Cache()
    hot_config.set_config_cache(cache)
    await _seed_old_index(vec_db)
    mm = _memory(vec_db)
    monkeypatch.setattr(ecp, "execute_embed", _ModelEmbed())
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)
    _no_background(monkeypatch)

    await gr.start_model_swap(vec_db, model=NEW_MODEL, dims=DIM)
    target_fp = _target_row_and_fp()
    await gr.maybe_schedule_rebuilds(mm)
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)

    # UI разрешает сохранить новый «Адрес сервера» во время перестройки:
    # provider-inclusive fingerprint меняется, канонический MSI — нет.
    hot_fake.base_url = "https://new-provider.test/v1"
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))

    job = await gr._get_job(vec_db, job["job_id"])
    assert job["status"] == gr.ST_ACTIVATED
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == NEW_MODEL
    assert cache.values["models.embedding_model_name"] == NEW_MODEL


@pytest.mark.asyncio
async def test_model_swap_f1_failed_resume_after_transient_space_drift(
        vec_db, monkeypatch):
    """F1: failed-состояние отменяемо, а Resume реально возобновляет сборку
    после возврата пространства к подтверждённому source."""
    hot_fake = _use_hot(monkeypatch, _HotModel())
    hot_config.set_config_cache(_Cache())
    await _seed_old_index(vec_db)
    mm = _memory(vec_db)
    monkeypatch.setattr(ecp, "execute_embed", _ModelEmbed())
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)
    _no_background(monkeypatch)

    await gr.start_model_swap(vec_db, model=NEW_MODEL, dims=DIM)
    target_fp = _target_row_and_fp()
    await gr.maybe_schedule_rebuilds(mm)
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)

    hot_fake.model = "transient-model"
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))
    job = await gr._get_job(vec_db, job["job_id"])
    assert job["status"] in (gr.ST_FAILED, gr.ST_VALIDATION_FAILED)
    assert job["reason_code"] == "source_space_changed"
    state = await gr.model_swap_state(vec_db)
    assert state["state"] == "failed"
    assert state["can_cancel"] is True
    assert state["can_resume"] is False

    # Пространство вернулось к source (временный дрейф устранён).
    hot_fake.model = OLD_MODEL
    state = await gr.model_swap_state(vec_db)
    assert state["can_resume"] is True
    out = await gr.resume_model_swap(vec_db)
    assert "graph_facts_vec" in out["resumed"] and not out["blocked"]
    assert await gr.maybe_schedule_rebuilds(mm) == ["graph_facts_vec"]
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == NEW_MODEL


@pytest.mark.asyncio
async def test_model_swap_f1_failed_is_cancellable(vec_db, monkeypatch):
    """F1: явный Cancel снимает failed-джобу и target, старый индекс цел."""
    hot_fake = _use_hot(monkeypatch, _HotModel())
    hot_config.set_config_cache(_Cache())
    await _seed_old_index(vec_db)
    monkeypatch.setattr(ecp, "execute_embed", _ModelEmbed())
    _no_background(monkeypatch)
    await gr.start_model_swap(vec_db, model=NEW_MODEL, dims=DIM)
    target_fp = _target_row_and_fp()
    mm = _memory(vec_db)
    await gr.maybe_schedule_rebuilds(mm)
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)
    hot_fake.model = "transient-model"
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))
    state = await gr.model_swap_state(vec_db)
    assert state["state"] == "failed" and state["can_cancel"] is True

    out = await gr.cancel_model_swap(vec_db)
    assert "graph_facts_vec" in out["cancelled"]
    job = await gr._get_job(vec_db, job["job_id"])
    assert job["status"] == gr.ST_CANCELLED
    assert await gr.model_swap_state(vec_db) is None
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == OLD_MODEL
    assert all(v == [0.5] * DIM for v in await _live_values(vec_db))


@pytest.mark.asyncio
async def test_model_swap_f2_start_without_dimension_is_blocked(
        vec_db, monkeypatch):
    """F2: смена модели без размерности не создаёт target/doomed rebuild."""
    _use_hot(monkeypatch, _HotModel())
    await _seed_old_index(vec_db)
    res = await gr.start_model_swap(vec_db, model=NEW_MODEL)
    assert res["ok"] is False and res["error"] == "dimension_required"
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_embedding_index_generations")
    assert int((await cur.fetchone())["c"]) == 1


@pytest.mark.asyncio
async def test_model_swap_f2_api_probes_actual_dimension(vec_db, monkeypatch):
    """F2: сервер определяет реальную размерность новой модели пробой и
    запускает перестройку именно с ней (4, не старая 8)."""
    _use_hot(monkeypatch, _HotModel())
    cache = _Cache()
    hot_config.set_config_cache(cache)
    await _seed_old_index(vec_db)
    monkeypatch.setattr(magi, "_require_global_admin", lambda *a, **k: None)
    monkeypatch.setattr(magi, "_db_or_503", lambda: vec_db)

    async def _probe(model):
        return {"ok": True, "dims": 4, "model": model, "latency_ms": 12}

    monkeypatch.setattr(magi, "_probe_target_dimension", _probe)
    monkeypatch.setattr(ecp, "execute_embed", _ModelEmbed(dim=4))
    monkeypatch.setattr(gr, "_adaptive_batch_size", lambda: 2)
    _no_background(monkeypatch)

    res = await magi.memory_embedding_change_start(
        None, magi.EmbeddingModelSwapBody(model=NEW_MODEL), object())
    assert res["ok"] is True and res["required"] is True
    assert res["new_dims"] == 4
    assert res["dimension_probe"]["dims"] == 4
    target_fp = sm.embedding_identity_fingerprint(
        provider=sm._embedding_provider(), model=NEW_MODEL, dims=4,
        preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint=sm._endpoint_fingerprint())
    target = await _row(vec_db, target_fp)
    assert int(target["dims"]) == 4

    mm = _memory(vec_db)
    await gr.maybe_schedule_rebuilds(mm)
    job = await gr._find_active_job(vec_db, "graph_facts_vec", target_fp)
    await gr.run_job(mm, "graph_facts_vec", str(job["job_id"]))
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["model"] == NEW_MODEL and int(active["dims"]) == 4
    assert cache.values["models.embedding_dim"] == 4


@pytest.mark.asyncio
async def test_model_swap_f2_api_probe_failure_blocks_confirmation(
        vec_db, monkeypatch):
    """F2: проба не смогла определить размерность → 422, rebuild не начат."""
    _use_hot(monkeypatch, _HotModel())
    await _seed_old_index(vec_db)
    monkeypatch.setattr(magi, "_require_global_admin", lambda *a, **k: None)
    monkeypatch.setattr(magi, "_db_or_503", lambda: vec_db)

    async def _probe_fail(model):
        return {"ok": False, "error": "dimension_probe_failed"}

    monkeypatch.setattr(magi, "_probe_target_dimension", _probe_fail)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await magi.memory_embedding_change_start(
            None, magi.EmbeddingModelSwapBody(model=NEW_MODEL), object())
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "dimension_required"
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_embedding_index_generations")
    assert int((await cur.fetchone())["c"]) == 1


# ── API surface: start/state/cancel/resume (admin) ──────────────────────────

@pytest.mark.asyncio
async def test_model_swap_api_start_and_state(vec_db, monkeypatch):
    _use_hot(monkeypatch, _HotModel())
    hot_config.set_config_cache(_Cache())
    await _seed_old_index(vec_db)
    monkeypatch.setattr(magi, "_require_global_admin", lambda *a, **k: None)
    monkeypatch.setattr(magi, "_db_or_503", lambda: vec_db)
    start = await magi.memory_embedding_change_start(
        None, magi.EmbeddingModelSwapBody(model=NEW_MODEL, dim=DIM), object())
    assert start["ok"] is True and start["required"] is True
    state = await magi.memory_embedding_change_state(None, object())
    assert state["pending"] is not None
    assert state["pending"]["new_model"] == NEW_MODEL
    assert state["pending"]["old_model"] == OLD_MODEL
    assert state["pending"]["total"] == 4
    assert "FTS" in state["fallback_channels"]


# ── UI: warning/confirm/progress at 1440 and 390 (Playwright) ───────────────

def _ui_ready():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def _run_ui():
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import ui_round1025_matrix as M

    def config_stub():
        data = copy.deepcopy(M.CONFIG_STUB)
        for it in data.get("items", []):
            key = it.get("key")
            if key == "models.embedding_model_name":
                it["value"] = OLD_MODEL
            elif key == "models.embedding_dim":
                it["value"] = DIM
            elif key == "models.embedding_base_url":
                it["value"] = "https://old-provider.test/v1"
            elif key == "models.embedding_display_name":
                it["value"] = "Тестовая модель A"
        return data

    cfg = config_stub()
    flags = {"preview": 0, "start": 0, "probe": 0, "probe_fail": False,
             "config_posts": 0, "pending": False, "start_body": None}
    pending_state = {
        "pending": True,
        "state": "building",
        "old_model": OLD_MODEL,
        "old_dims": DIM,
        "new_model": NEW_MODEL,
        "new_dims": 4,
        "processed": 123,
        "total": 500,
        "errors": [{"index": "graph_facts_vec",
                    "reason_code": "knn_dim_mismatch"}],
        "old_model_available": True,
        "can_cancel": True,
        "can_resume": False,
    }

    def handler(route):
        req = route.request
        url = req.url.split("?")[0]
        if url.endswith("/api/memory/embedding-change/preview"):
            flags["preview"] += 1
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({
                              "requires_rebuild": True,
                              "old_model": OLD_MODEL, "old_dims": DIM,
                              "new_model": NEW_MODEL, "new_dims": None,
                              "dimension_known": False,
                              "reason": (
                                  f"Раньше индекс построила модель «{OLD_MODEL}», "
                                  f"выбрана «{NEW_MODEL}». Размерность новой "
                                  "модели будет определена пробой."),
                          }, ensure_ascii=False))
            return
        if url.endswith("/api/memory/embedding-change/probe"):
            flags["probe"] += 1
            if flags["probe_fail"]:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(
                                  {"ok": False,
                                   "error": "dimension_probe_failed"},
                                  ensure_ascii=False))
                return
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "dims": 4,
                                           "model": NEW_MODEL,
                                           "latency_ms": 12},
                                          ensure_ascii=False))
            return
        if url.endswith("/api/memory/embedding-change/start"):
            flags["start"] += 1
            flags["pending"] = True
            try:
                flags["start_body"] = json.loads(req.post_data or "{}")
            except Exception:
                flags["start_body"] = {}
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "required": True,
                                           "state": pending_state},
                                          ensure_ascii=False))
            return
        if url.endswith("/api/memory/embedding-change"):
            body = (pending_state if flags["pending"] else
                    {"pending": None, "configured": {
                        "model": OLD_MODEL, "dims": DIM}})
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(body, ensure_ascii=False))
            return
        if url.endswith("/api/config") and req.method == "POST":
            flags["config_posts"] += 1
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"updated": ["models.embedding_base_url"]}))
            return
        if url.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(cfg, ensure_ascii=False))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(url), ensure_ascii=False))

    class Handler(SimpleHTTPRequestHandler):
        def translate_path(self, path):  # noqa: N802
            import os
            p = path.split("?")[0]
            if p.startswith("/static/"):
                rel = "web/" + p.lstrip("/")
            elif p.startswith("/web/"):
                rel = p.lstrip("/")
            elif p in ("/", "", "/index.html"):
                rel = "web/index.html"
            else:
                rel = p.lstrip("/")
            return os.path.join(str(ROOT), rel.replace("/", os.sep))

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        functools.partial(Handler, directory=str(ROOT)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    sdk = M.TMA_STUB
    results = {}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width, height, tag in ((1440, 900, "desktop"),
                                       (390, 844, "mobile")):
                errors = []
                ctx = browser.new_context(viewport={"width": width,
                                                    "height": height})
                ctx.route("**/api/**", handler)
                ctx.route("**/static/vendor/telegram-web-app.js",
                          lambda r: r.fulfill(
                              status=200, content_type="application/javascript",
                              body=sdk))
                page = ctx.new_page()
                page.on("console", lambda m, e=errors: (
                    e.append(m.text) if m.type == "error" else None))
                page.goto(base + "/#/ai/llm", wait_until="load")
                page.wait_for_selector('[data-block="embeddings"]',
                                       timeout=20000)
                block = page.locator('[data-block="embeddings"]').first
                if block.locator('[data-conn-configure]').count():
                    block.locator('[data-conn-configure]').first.click()
                page.wait_for_selector('[data-block="embeddings_main"]',
                                       timeout=10000)
                if tag == "desktop":
                    row = page.locator(
                        '[data-block="embeddings_main"] .prov-row').filter(
                            has_text="Модель").first
                    row.locator("input").fill(NEW_MODEL)
                    page.locator(
                        '[data-block="embeddings_main"] button').filter(
                            has_text="Сохранить").first.click()
                    page.wait_for_selector("[data-embed-swap-warning]",
                                           timeout=10000)
                    warn = page.locator("[data-embed-swap-models]").inner_text()
                    assert OLD_MODEL in warn and NEW_MODEL in warn
                    assert "8" in warn and "размерность 4" in warn
                    assert "(8 изм.)" not in warn
                    probe_text = page.locator(
                        "[data-embed-swap-probe]").inner_text()
                    assert "4" in probe_text
                    assert flags["probe"] == 1
                    assert flags["config_posts"] == 0
                    page.locator("[data-embed-swap-confirm]").click()
                    page.wait_for_selector("[data-embed-swap-progress]",
                                           timeout=15000)
                    assert flags["start_body"] == {"model": NEW_MODEL, "dim": 4}
                else:
                    flags["pending"] = True
                    page.evaluate("window.__adminbotVm.loadEmbeddingChange()")
                    page.wait_for_selector("[data-embed-swap-progress]",
                                           timeout=10000)
                text = page.locator("[data-embed-swap-progress]").inner_text()
                assert "123" in text and "500" in text
                assert page.locator(
                    "[data-embed-swap-progress]").get_attribute(
                        "data-embed-swap-state") == "building"
                human_err = page.locator(
                    "[data-embed-swap-errors] > div").first.inner_text()
                assert "Провайдер вернул вектор" in human_err
                assert "knn_dim_mismatch" not in human_err
                diag = page.locator(
                    "[data-embed-swap-diagnostics]").evaluate(
                        "el => el.textContent")
                assert "knn_dim_mismatch" in diag
                overflow = page.evaluate(
                    "() => ({doc: document.documentElement.scrollWidth,"
                    " win: window.innerWidth})")
                assert overflow["doc"] <= overflow["win"] + 1, overflow
                assert errors == [], errors
                results[tag] = True
                ctx.close()
            browser.close()

        # provider-only: без предупреждения, сохранение проходит.
        flags["preview"] = 0
        flags["config_posts"] = 0
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.route("**/api/**", handler)
            ctx.route("**/static/vendor/telegram-web-app.js",
                      lambda r: r.fulfill(
                          status=200, content_type="application/javascript",
                          body=sdk))
            page = ctx.new_page()
            page.goto(base + "/#/ai/llm", wait_until="load")
            page.wait_for_selector('[data-block="embeddings"]', timeout=20000)
            block = page.locator('[data-block="embeddings"]').first
            if block.locator('[data-conn-configure]').count():
                block.locator('[data-conn-configure]').first.click()
            page.wait_for_selector('[data-block="embeddings_main"]',
                                   timeout=10000)
            row = page.locator(
                '[data-block="embeddings_main"] .prov-row').filter(
                    has_text="Адрес сервера").first
            row.locator("input").fill("https://new-provider.test/v1")
            page.locator('[data-block="embeddings_main"] button').filter(
                has_text="Сохранить").first.click()
            page.wait_for_timeout(1000)
            assert page.locator("[data-embed-swap-warning]").count() == 0
            assert flags["preview"] == 0
            assert flags["config_posts"] >= 1
            browser.close()

        # F2 fallback: проба не смогла определить размерность → поле ввода,
        # confirm заблокирован до валидного числа; в start уходит введённое.
        flags.update({"preview": 0, "probe": 0, "probe_fail": True,
                      "pending": False, "start_body": None,
                      "config_posts": 0})
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.route("**/api/**", handler)
            ctx.route("**/static/vendor/telegram-web-app.js",
                      lambda r: r.fulfill(
                          status=200, content_type="application/javascript",
                          body=sdk))
            page = ctx.new_page()
            page.goto(base + "/#/ai/llm", wait_until="load")
            page.wait_for_selector('[data-block="embeddings"]', timeout=20000)
            block = page.locator('[data-block="embeddings"]').first
            if block.locator('[data-conn-configure]').count():
                block.locator('[data-conn-configure]').first.click()
            page.wait_for_selector('[data-block="embeddings_main"]',
                                   timeout=10000)
            row = page.locator(
                '[data-block="embeddings_main"] .prov-row').filter(
                    has_text="Модель").first
            row.locator("input").fill(NEW_MODEL)
            page.locator('[data-block="embeddings_main"] button').filter(
                has_text="Сохранить").first.click()
            page.wait_for_selector("[data-embed-swap-warning]", timeout=10000)
            dim_input = page.locator("[data-embed-swap-dim-input]")
            assert dim_input.count() == 1
            confirm = page.locator("[data-embed-swap-confirm]")
            assert confirm.is_disabled() is True
            dim_input.fill("6")
            assert confirm.is_disabled() is False
            confirm.click()
            page.wait_for_selector("[data-embed-swap-progress]", timeout=15000)
            assert flags["start_body"] == {"model": NEW_MODEL, "dim": 6}
            browser.close()
    finally:
        httpd.shutdown()
    assert results == {"desktop": True, "mobile": True}


@pytest.mark.skipif(not _ui_ready(), reason="playwright недоступен")
def test_model_swap_ui_warning_progress_1440_390():
    _run_ui()
