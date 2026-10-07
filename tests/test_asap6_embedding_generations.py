"""ASAP 6 §8 (P1, P2-D-embed-scope) — embedding generations: multi-chat/
namespace safety, классы совместимости, безопасная смена модели.

Контракт: plans/current_task.md ASAP 6 §8.1–§8.7 (+13C–13I уже частично в
asap5). Приоритеты лейна:
  1  same model + different key → INSTANT_COMPATIBLE (no reindex)
  2  same dimension + different model → REINDEX_REQUIRED (не instant)
  3  different dimension → INCOMPATIBLE_DIMENSION
  4  unknown/floating alias → COMPATIBILITY_UNKNOWN (fail-safe)
  5  ACTIVE scoped: два namespace → две ACTIVE, независимы (§8.1)
  6  global default change → существующие pinned, новые — новый default
  7  per-chat override → target только этого namespace; old active
  8  supersede при повторной смене; stale worker не promote (§8.5)
  9  canary fail → no mixed-space writes (FTS fail-soft) (§8.6)
  10 restart при rebuild → resume той же target, без дублей
  11 promotion atomic: readers не смешивают поколения (§8.4/13E.3)
  12 существующие данные без namespace → 'default', retrieval не сломан
"""
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
    d = DatabaseService(str(tmp_path / "asap6_embed.db"))
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


def _patch_rebuild_batch(monkeypatch, value: int = 2) -> None:
    """GRAPHRAG_REBUILD_BATCH — старт/потолок AIMD-контроллера; `_batch`
    контроллера сидируется ЛЕНИВО из этого значения (process-level синглтон):
    патчим developer-конфиг ДО первого `_fetch_batch` и сбрасываем AIMD,
    иначе миграционный чанк засеивает контроллер дефолтом настроек (50) и
    ломает порядок-зависимые тесты rebuild (batch=50 → один embed-вызов)."""
    import config.settings as cs
    monkeypatch.setattr(type(cs.settings), "GRAPHRAG_REBUILD_BATCH", value,
                        raising=False)
    if type(sm.settings) is not type(cs.settings):
        monkeypatch.setattr(type(sm.settings), "GRAPHRAG_REBUILD_BATCH",
                            value, raising=False)
    ecp.CONTROLLER.reset()


def _stable_embed(seed: int = 0):
    async def _embed(texts):
        out = []
        for t in texts:
            s = (sum(bytearray(t.encode("utf-8"))) + seed) % 97
            out.append([((s + i * 13) % 7) / 7.0 for i in range(8)])
        return out
    return _embed


# ── §8.2: классы совместимости (#1–#4) ──────────────────────────────────────

def test_1_same_model_diff_key_instant():
    """#1: key/quota/route НЕ входят в identity → та же identity + canary
    stable = INSTANT_COMPATIBLE, reindex не нужен (13D.2)."""
    fp = "same-identity-fp"
    out = ecp.classify_identity_compatibility(
        current_identity=fp, stored_identity=fp,
        current_dim=8, stored_dim=8, canary_verdict=ecp.CANARY_STABLE)
    assert out == ecp.COMPAT_INSTANT


def test_2_same_dim_diff_model_reindex():
    """#2: same dimension != same space (§8.2) — другая identity при той же
    размерности = REINDEX_REQUIRED, никогда не instant."""
    out = ecp.classify_identity_compatibility(
        current_identity="fp-model-b", stored_identity="fp-model-a",
        current_dim=8, stored_dim=8, canary_verdict=ecp.CANARY_STABLE)
    assert out == ecp.COMPAT_REINDEX


def test_3_diff_dimension_incompatible():
    """#3: другая размерность — явный INCOMPATIBLE_DIMENSION."""
    out = ecp.classify_identity_compatibility(
        current_identity="fp-x", stored_identity="fp-y",
        current_dim=1536, stored_dim=3072, canary_verdict=None)
    assert out == ecp.COMPAT_DIMENSION


def test_4_unknown_floating_alias_fail_safe():
    """#4: floating alias (та же строка модели, пространство не доказано) →
    COMPATIBILITY_UNKNOWN (fail-safe: без writes/switch in-place)."""
    # canary не запускался → доказательств нет
    assert ecp.classify_identity_compatibility(
        current_identity="fp-a", stored_identity="fp-a",
        canary_verdict=None) == ecp.COMPAT_UNKNOWN
    # canary недоступен (unknown) → тоже fail-safe
    assert ecp.classify_identity_compatibility(
        current_identity="fp-a", stored_identity="fp-a",
        canary_verdict=ecp.CANARY_UNKNOWN) == ecp.COMPAT_UNKNOWN
    # canary поймал drift под той же строкой (§8.6) → REINDEX
    assert ecp.classify_identity_compatibility(
        current_identity="fp-a", stored_identity="fp-a",
        canary_verdict=ecp.CANARY_DRIFT) == ecp.COMPAT_REINDEX


# ── §8.1: ownership/namespace (#5, #12) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_5_active_scoped_two_namespaces(vec_db):
    """#5 (§8.1): (namespace, index) → ровно одна ACTIVE; два namespace —
    две независимые ACTIVE (в т.ч. разные identities)."""
    await vec_db.ensure_embedding_generation("graph_facts_vec", "fp-a",
                                             dims=8, activate=True)
    g = await vec_db.register_embedding_target_generation(
        "graph_facts_vec", "fp-b", namespace="chat_b", dims=16)
    row = await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", "fp-b", namespace="chat_b")
    assert await vec_db.set_embedding_generation_status(
        str(row["generation_id"]), "building_target")
    assert await vec_db.set_embedding_generation_status(
        str(row["generation_id"]), "catching_up")
    assert await vec_db.set_embedding_generation_status(
        str(row["generation_id"]), "ready")
    pr = await vec_db.promote_embedding_generation(
        "graph_facts_vec", str(row["generation_id"]), namespace="chat_b",
        expected_fingerprint="fp-b")
    assert pr is not None
    a_def = await vec_db.get_active_embedding_generation("graph_facts_vec")
    a_b = await vec_db.get_active_embedding_generation(
        "graph_facts_vec", namespace="chat_b")
    assert a_def["fingerprint"] == "fp-a"
    assert a_b["fingerprint"] == "fp-b"
    assert a_def["generation_id"] != a_b["generation_id"]
    actives = await vec_db.get_active_embedding_generations()
    assert {(r["namespace"], r["fingerprint"]) for r in actives} == {
        ("default", "fp-a"), ("chat_b", "fp-b")}


@pytest.mark.asyncio
async def test_12_legacy_rows_default_namespace(vec_db):
    """#12: существующие данные (вставка БЕЗ namespace-колонки) → namespace
    'default'; A06 не даёт подменить активное; retrieval не сломан."""
    # легаси-вставка: старый код не знал про namespace/config_revision
    await vec_db.db.execute(
        "INSERT INTO mca_embedding_index_generations (index_name, generation,"
        " fingerprint, status, created_at, activated_at) "
        "VALUES ('graph_facts_vec', 1, 'legacy-fp', 'active', 1, 1)")
    await vec_db.db.commit()
    row = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert row is not None
    assert (row["namespace"] or "default") == "default"
    # рестарт с тем же конфигом: ensure — no-op (активное не подменяется)
    mm = _memory(vec_db)
    mm._identity_fingerprint = lambda **kw: "legacy-fp"
    await mm._register_index_generations(activate=False)
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["fingerprint"] == "legacy-fp"
    assert int(active["generation"]) == 1
    # retrieval-гейт открыт для совпадающего identity (память жива)
    assert await mm._index_generation_ok("graph_facts_vec") is True
    # глобальный список ACTIVE видит ровно одну
    actives = await vec_db.get_active_embedding_generations()
    assert len(actives) == 1


# ── §8.3: global model change (#6) ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_6_global_change_pins_existing(vec_db):
    """#6 (§8.3/13F.1): смена глобального дефолта НЕ перепрошивает
    существующие чаты — ACTIVE остаётся pinned; новые чаты получают новый
    identity сразу; backend-план честно требует target-generation."""
    await vec_db.ensure_embedding_generation("graph_facts_vec", "fp-old",
                                             dims=8, activate=True)
    plan = await ecp.plan_embedding_change(
        vec_db, index_name="graph_facts_vec", current_identity="fp-new",
        current_dims=8)
    assert plan["compat"] == ecp.COMPAT_REINDEX
    assert plan["reindex_required"] is True
    assert plan["action"] == "target_generation"
    assert plan["active"]["fingerprint"] == "fp-old"
    # begin: существующий чат (default) — target строится, ACTIVE не тронут
    res = await ecp.begin_embedding_migration(
        vec_db, index_name="graph_facts_vec", target_fingerprint="fp-new",
        dims=8, config_revision="rev-new")
    assert res["action"] == "building"
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["fingerprint"] == "fp-old"          # pinned (§8.3)
    # новый чат (новый namespace) сразу активирует новый identity
    await vec_db.ensure_embedding_generation("graph_facts_vec", "fp-new",
                                             namespace="chat_new", dims=8,
                                             activate=True)
    a_new = await vec_db.get_active_embedding_generation(
        "graph_facts_vec", namespace="chat_new")
    assert a_new["fingerprint"] == "fp-new"


# ── §8.4: per-chat override (#7) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_7_per_chat_override_scoped(vec_db):
    """#7 (§8.4): override одного namespace создаёт target только этого
    namespace; другие namespace и old ACTIVE не затронуты до promotion."""
    await vec_db.ensure_embedding_generation("graph_facts_vec", "fp-shared",
                                             dims=8, activate=True)
    await vec_db.ensure_embedding_generation("smart_archive", "fp-shared",
                                             dims=8, activate=True)
    res = await ecp.begin_embedding_migration(
        vec_db, index_name="graph_facts_vec",
        target_fingerprint="fp-chatB", namespace="chat_b", dims=16,
        config_revision="rev-b")
    assert res["action"] == "building"
    # target только chat_b
    row_b = await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", "fp-chatB", namespace="chat_b")
    assert row_b is not None
    assert row_b["status"] == "building"
    assert await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", "fp-chatB") is None           # default не задет
    # old ACTIVE живы в обоих индексах
    assert (await vec_db.get_active_embedding_generation(
        "graph_facts_vec"))["fingerprint"] == "fp-shared"
    assert (await vec_db.get_active_embedding_generation(
        "smart_archive"))["fingerprint"] == "fp-shared"
    # coalesce-ключ job'а namespace-scoped: повтор — тот же job, без дублей
    jid2 = await ecp.enqueue_embedding_migration(
        vec_db, index_name="graph_facts_vec", source_generation=1,
        target_generation=res["target_generation"],
        fingerprint="fp-chatB", total=0, namespace="chat_b")
    assert jid2 == res["job_id"]


# ── §8.5: supersede + stale worker (#8) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_8_supersede_and_stale_worker(vec_db):
    """#8 (§8.5/13G.1): A→B затем B→C — B → SUPERSEDED; чанк job'а B
    завершается без writes; promote B после supersede невозможен; A активен."""
    await vec_db.ensure_embedding_generation("graph_facts_vec", "fp-a",
                                             dims=8, activate=True)
    r_b = await ecp.begin_embedding_migration(
        vec_db, index_name="graph_facts_vec", target_fingerprint="fp-b",
        dims=8, config_revision="rev-b")
    assert r_b["action"] == "building"
    r_c = await ecp.begin_embedding_migration(
        vec_db, index_name="graph_facts_vec", target_fingerprint="fp-c",
        dims=8, config_revision="rev-c")
    assert r_c["action"] == "building"
    assert r_c["superseded"] >= 1                       # B → SUPERSEDED
    row_b = await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", "fp-b")
    assert row_b["status"] == "superseded"
    # stale worker: чанк job'а B видит superseded-target → cancel, no writes
    out = await ecp.run_embedding_migration_chunk(
        _memory(vec_db), vec_db, r_b["job_id"], embed_fn=_stable_embed())
    assert out["phase"] == "superseded"
    assert out["promoted"] is False and out["processed"] == 0
    from services.task_supervisor import TaskJobStore
    job = await TaskJobStore(vec_db).get(r_b["job_id"])
    assert job["status"] == "cancelled"
    # promote superseded-B — отказ (даже мимо state machine)
    assert await vec_db.promote_embedding_generation(
        "graph_facts_vec", str(row_b["generation_id"]), namespace="default",
        expected_fingerprint="fp-b") is None
    # A остаётся активным; C — единственный building-target
    assert (await vec_db.get_active_embedding_generation(
        "graph_facts_vec"))["fingerprint"] == "fp-a"
    row_c = await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", "fp-c")
    assert row_c["status"] == "building"


@pytest.mark.asyncio
async def test_8b_stale_worker_config_revision_guard(vec_db):
    """#8b (13G.1): config_revision поменялся под работающим worker'ом →
    чанк отказывается писать/promote (guard по revision)."""
    await vec_db.ensure_embedding_generation("graph_facts_vec", "fp-a",
                                             dims=8, activate=True)
    gen = await vec_db.register_embedding_target_generation(
        "graph_facts_vec", "fp-b", dims=8, config_revision="rev-1")
    jid = await ecp.enqueue_embedding_migration(
        vec_db, index_name="graph_facts_vec", source_generation=1,
        target_generation=gen, fingerprint="fp-b", total=0,
        config_revision="rev-1")
    # воркер несёт УСТАРЕВШИЙ revision в payload
    from services.task_supervisor import TaskJobStore
    store = TaskJobStore(vec_db)
    await vec_db.db.execute(
        "UPDATE task_jobs SET payload = ? WHERE job_id = ?",
        (json.dumps({"index": "graph_facts_vec", "namespace": "default",
                     "source_generation": 1, "target_generation": gen,
                     "fingerprint": "fp-b", "config_revision": "rev-OLD",
                     "total": 0}), jid))
    await vec_db.db.commit()
    out = await ecp.run_embedding_migration_chunk(
        _memory(vec_db), vec_db, jid, embed_fn=_stable_embed())
    assert out["phase"] == "stale_worker"
    job = await store.get(jid)
    assert job["status"] == "failed"
    # shadow не создан/пуст — writes не было
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND "
        "name='graph_facts_vec_g%d'" % gen)
    row = await cur.fetchone()
    assert row["c"] == 0


# ── §8.6: canary drift → no mixed-space writes (#9) ─────────────────────────

@pytest.mark.asyncio
async def test_9_canary_drift_blocks_writes(vec_db):
    """#9 (§8.6): canary DRIFT (провайдер молча сменил space) → запись в
    ACTIVE запрещена: _save_archive_embedding/text-only, backfill = 0."""
    fp = "drift-identity-fp"
    mm = _memory(vec_db)
    mm._identity_fingerprint = lambda **kw: fp
    await vec_db.ensure_embedding_generation("smart_archive", fp, dims=8,
                                             activate=True)
    ecp._CANARY_VERDICTS.pop(fp, None)
    await ecp.embedding_canary_check(None, vec_db, fp,
                                     embed_fn=_stable_embed(seed=0))
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
    assert ecp.canary_blocks_writes(fp) is True
    # live-таблица ещё не создана: если запись пройдёт мимо гейта — INSERT
    # упадёт; гейт обязан отсечь ДО попытки.
    await vec_db.db.execute(mm._vec_table_sql(8))
    await vec_db.db.commit()
    await mm._save_archive_embedding(77, 1, "факт для дрейфа")
    cur = await vec_db.db.execute("SELECT COUNT(*) AS c FROM smart_archive")
    assert (await cur.fetchone())["c"] == 0      # mixed-space write нет
    assert await mm.backfill_archive_vectors() == 0
    # STABLE снимает блок (TTL-механика процесса)
    await ecp.embedding_canary_check(None, vec_db, fp,
                                     embed_fn=_stable_embed(seed=0))
    assert ecp.canary_blocks_writes(fp) is False
    ecp._CANARY_VERDICTS.pop(fp, None)


@pytest.mark.asyncio
async def test_9b_generation_mismatch_blocks_writes(vec_db):
    """#9b (§8.2/§8.4): ACTIVE другого identity → новые векторы в live
    ACTIVE не пишутся (нет mixed-space), факт остаётся в FTS/source."""
    mm = _memory(vec_db)
    mm._identity_fingerprint = lambda **kw: "fp-current"
    await vec_db.ensure_embedding_generation("graph_facts_vec", "fp-other",
                                             dims=8, activate=True)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    ok = await mm._save_graph_fact_embedding(1, 77, "факт", "chat_history",
                                             None)
    assert ok is False
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM graph_facts_vec")
    assert (await cur.fetchone())["c"] == 0
    assert await mm.backfill_graph_fact_vectors() == 0


# ── §8.4: полный цикл snapshot → backfill → delta → promotion (#10/#11) ─────

async def _seed_facts(db, n: int) -> None:
    now = int(time.time())
    for i in range(n):
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (77, ?, 'chat_history', ?)",
            (f"миграционный факт номер {i} о проекте {i}", now))
    await db.db.commit()


@pytest.mark.asyncio
async def test_10_11_full_cycle_backfill_delta_promote(vec_db, monkeypatch):
    """#10/#11 (§8.4/13E): resumable чанки без дублей; после backfill —
    delta catch-up (строки, добавленные ВО ВРЕМЯ rebuild); promotion только
    при full coverage — атомарно (live swap + реестр в одной транзакции),
    readers видят либо old, либо new; old остаётся rollback-кандидатом."""
    mm = _memory(vec_db)
    monkeypatch.setattr(mm, "_identity_fingerprint",
                        lambda **kw: "fp-old", raising=False)
    await _seed_facts(vec_db, 4)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    # OLD ACTIVE c «частичными» векторами (snapshot-мир)
    old_vec = _stable_embed(seed=100)
    rows = await gr._fetch_batch(mm, gr._INDEX_SPECS["graph_facts_vec"], 0)
    await vec_db.ensure_embedding_generation("graph_facts_vec", "fp-old",
                                             dims=8, activate=True)
    await gr._insert_shadow_rows(
        mm, gr._INDEX_SPECS["graph_facts_vec"], "graph_facts_vec",
        rows, await old_vec([r["fact"] for r in rows]))
    # миграция A→B
    res = await ecp.begin_embedding_migration(
        vec_db, index_name="graph_facts_vec", target_fingerprint="fp-new",
        dims=8, config_revision="rev-2", total=4)
    assert res["action"] == "building" and res["job_id"]
    gen = res["target_generation"]
    _patch_rebuild_batch(monkeypatch, 2)
    mm._identity_fingerprint = lambda **kw: "fp-new"
    embed = _stable_embed(seed=0)
    # #10: restart-устойчивость — чанки с checkpoint, без дублей
    out1 = await ecp.run_embedding_migration_chunk(mm, vec_db, res["job_id"],
                                                   embed_fn=embed)
    assert out1["processed"] == 2 and out1["done"] is False
    out2 = await ecp.run_embedding_migration_chunk(mm, vec_db, res["job_id"],
                                                   embed_fn=embed)
    assert out2["processed"] == 2 and out2["done"] is True
    # во время rebuild появилась НОВАЯ source-строка, курсор которой ещё
    # НЕ догнал (вставлена «ниже» высокого watermark — дельта-фаза)
    now = int(time.time())
    await vec_db.db.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
        "VALUES (77, 'поздний факт после snapshot', 'chat_history', ?)",
        (now,))
    await vec_db.db.commit()
    cur = await vec_db.db.execute(
        f"SELECT COUNT(*) AS c FROM graph_facts_vec_g{gen}")
    assert (await cur.fetchone())["c"] == 4          # backfill-часть в shadow
    # ACTIVE до promotion — old (readers не смешиваются)
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["fingerprint"] == "fp-old"
    # cursor-фаза добивает хвост (поздняя строка с id выше watermark)
    out3 = await ecp.run_embedding_migration_chunk(mm, vec_db, res["job_id"],
                                                   embed_fn=embed)
    assert out3["processed"] == 1 and out3["done"] is True
    assert out3["phase"] == "backfill"
    # имитируем дельту: строка с id НИЖЕ курсора, отсутствующая в shadow
    # (гонка вставки/водяного знака) — чанк обязан догнать её анти-join'ом
    from services.task_supervisor import TaskJobStore
    await vec_db.db.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
        "VALUES (77, 'запоздалая дельта ниже watermark', 'chat_history', ?)",
        (now,))
    await vec_db.db.commit()
    await TaskJobStore(vec_db).save_checkpoint(
        res["job_id"],
        cursor_token=json.dumps({"last_id": 10 ** 9, "processed": 5,
                                 "phase": "backfill"}),
        processed=5,
        checkpoint_ref=f"cp:embedding_migration:graph_facts_vec:{gen}")
    out4 = await ecp.run_embedding_migration_chunk(mm, vec_db, res["job_id"],
                                                   embed_fn=embed)
    assert out4["phase"] == "catching_up"
    assert out4["processed"] == 1                    # delta catch-up
    assert out4["promoted"] is False
    # финальный чанк: дельта пуста → coverage full → ready → promotion
    out5 = await ecp.run_embedding_migration_chunk(mm, vec_db, res["job_id"],
                                                   embed_fn=embed)
    assert out5["promoted"] is True and out5["done"] is True
    # #11: атомарный итог — ровно один ACTIVE, он new; old — rollback;
    # live таблица ПОЛНОСТЬЮ из new-generation (6 строк, без дублей);
    # shadow удалён swap'ом.
    active = await vec_db.get_active_embedding_generation("graph_facts_vec")
    assert active["fingerprint"] == "fp-new"
    assert int(active["generation"]) == int(gen)
    old_row = await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", "fp-old")
    assert old_row["status"] == "active_old"         # 13E.3 retention
    cur = await vec_db.db.execute("SELECT COUNT(*) AS c FROM graph_facts_vec")
    assert (await cur.fetchone())["c"] == 6
    cur = await vec_db.db.execute(
        "SELECT COUNT(DISTINCT fact_id) AS c FROM graph_facts_vec")
    assert (await cur.fetchone())["c"] == 6          # дублей нет (#10)
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND "
        f"name='graph_facts_vec_g{gen}'")
    assert (await cur.fetchone())["c"] == 0
    job = await TaskJobStore(vec_db).get(res["job_id"])
    assert job["status"] == "completed"
    # raw source не тронут (R18)
    cur = await vec_db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
    assert (await cur.fetchone())["c"] == 6


@pytest.mark.asyncio
async def test_10b_resume_same_target_after_restart(vec_db, monkeypatch):
    """#10 (§8.4): рестарт при rebuild → job/coalesce возвращает ТА ЖЕ
    target (begin idempotent), resume продолжается с checkpoint, дублей в
    shadow нет."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, 3)
    r1 = await ecp.begin_embedding_migration(
        vec_db, index_name="graph_facts_vec", target_fingerprint="fp-b",
        dims=8, config_revision="rev-1", total=3)
    # повторный begin той же смены (рестарт/повторный Save) — не плодит
    # новых поколений/jobs
    r2 = await ecp.begin_embedding_migration(
        vec_db, index_name="graph_facts_vec", target_fingerprint="fp-b",
        dims=8, config_revision="rev-1", total=3)
    assert r1["target_generation"] == r2["target_generation"]
    assert r1["job_id"] == r2["job_id"]
    _patch_rebuild_batch(monkeypatch, 2)
    mm._identity_fingerprint = lambda **kw: "fp-b"
    embed = _stable_embed(seed=0)
    o1 = await ecp.run_embedding_migration_chunk(mm, vec_db, r1["job_id"],
                                                 embed_fn=embed)
    assert o1["processed"] == 2
    # «рестарт»: новый вызов чанка продолжает с checkpoint
    o2 = await ecp.run_embedding_migration_chunk(mm, vec_db, r1["job_id"],
                                                 embed_fn=embed)
    assert o2["processed"] == 1
    cur = await vec_db.db.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT fact_id) "
        f"FROM graph_facts_vec_g{r1['target_generation']}")
    row = await cur.fetchone()
    assert row[0] == 3 and row[1] == 3               # без дублей


# ── §8.3/13J: честный план в статусе (additive) ─────────────────────────────

@pytest.mark.asyncio
async def test_13_panel_additive_compat_fields(vec_db):
    """vector_memory_panel: additive-поля namespace/active_generation/
    compat_class не ломают существующий контракт панели."""
    fp = "fp-panel"
    await vec_db.ensure_embedding_generation("graph_facts_vec", fp, dims=8,
                                             activate=True)
    # панель читает индексы из task_jobs (kind='graphrag_rebuild')
    await gr._ensure_job(vec_db, "graph_facts_vec", fp, 1)
    panel = await ecp.vector_memory_panel(vec_db)
    entry = next((e for e in panel["indexes"]
                  if e.get("index") == "graph_facts_vec"), None)
    assert entry is not None
    assert entry["namespace"] == "default"
    assert entry["active_generation"] == 1
    # identity primary-профиля != fp-panel → честный класс (не instant)
    assert entry["compat_class"] in (ecp.COMPAT_REINDEX, ecp.COMPAT_UNKNOWN,
                                     ecp.COMPAT_DIMENSION)
