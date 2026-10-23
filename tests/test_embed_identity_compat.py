"""EMBED-IDENTITY-COMPAT (P0, 23.10.2026) — смена API-шлюза при той же
embedding-модели НЕ запускает полную перевекторизацию.

Контракт (arch-design §1–§7, source-2026-10-23 §1–§6):
  * Model Space Identity (model/revision/dims/task/normalization/preprocessing/
    материальные параметры) — ЕДИНСТВЕННЫЙ критерий совместимости векторов;
    Provider Connection Identity (host/path/alias/quota) — провенанс, он же
    инвалидирует допуск, но сам индекс не закрывает;
  * совместимость доказывается сравнением НОВЫХ векторов со СТАРЫМИ
    сохранёнными (`graph_facts_vec JOIN graph_facts`) + KNN-выдачей новым
    вектором к СТАРОМУ индексу; сравнение «новое против нового» доказательством
    не является (анти-тест ниже);
  * три исхода: compatible → adopt существующего поколения (без rebuild),
    insufficient → ничего не активируем/не перестраиваем (FTS + диагностика),
    incompatible → существующая контролируемая миграция поколений;
  * вердикт durable: `config_revision` ACTIVE-строки `adopt1:...` (ΔDDL=0).

Фикстуры: реальная SQLite + sqlite-vec + реальный реестр поколений. Мокается
ТОЛЬКО embed_fn (HTTP): `_cosine`, KNN/SQL, транзакции реестра и
`_index_generation_ok` — настоящие.

TEST-LIFECYCLE: CONTRACT owner=EMBED-IDENTITY-COMPAT
"""
import asyncio
import hashlib
import json
import math
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio

from services import embedding_control_plane as ecp
from services import graphrag_rebuild as gr
from services import hot_config
from services import summary_memory as sm
from services.database import DatabaseService

pytestmark = pytest.mark.asap4

DIMS = 8
MODEL = "gemini-embedding-001"
OTHER_MODEL = "text-embedding-004"
OLD_HOST = "https://old-gateway.test/v1"
NEW_HOST = "https://apinet.cloud/v1"
OLD_PROVIDER = "old-gateway.test"
INDEX = "graph_facts_vec"


# ── окружение: реальная БД + sqlite-vec + подменяемый hot-конфиг ────────────

class _Hot:
    """Единый источник MSI/PCI для summary_memory/graphrag/control-plane."""

    def __init__(self, *, model: str = MODEL, base_url: str = OLD_HOST,
                 dim: int = DIMS):
        self.model = model
        self.base_url = base_url
        self.dim = dim

    def get(self, key, default=None):
        if key == "models.embedding_model_name":
            return self.model
        if key == "models.embedding_base_url":
            return self.base_url
        if key == "models.embedding_dim":
            return self.dim
        if key == "models.embedding_quota_group":
            return "qg-primary"
        return default


@pytest_asyncio.fixture
async def ctx(tmp_path, monkeypatch):
    ecp.reset_compat_state()
    db = DatabaseService(str(tmp_path / "embed_compat.db"))
    await db.initialize()
    import sqlite_vec
    await db.db.enable_load_extension(True)
    await db.db.load_extension(sqlite_vec.loadable_path())
    await db.db.enable_load_extension(False)
    hot = _Hot()
    monkeypatch.setattr(hot_config, "get", hot.get)
    monkeypatch.setattr(sm, "fire_and_forget",
                        lambda coro, tag: coro.close())
    mm = sm.MemoryManager(db, None)
    mm._vec_dim = DIMS
    mm._vec_available = True
    mm._vec_int8 = False
    try:
        yield SimpleNamespace(db=db, mm=mm, hot=hot)
    finally:
        ecp.reset_compat_state()
        await db.close()


# ── детерминированные векторы (sha256-сид; без сети) ───────────────────────

def _unit(seed: str, dim: int = DIMS) -> list[float]:
    vals: list[float] = []
    i = 0
    while len(vals) < dim:
        digest = hashlib.sha256(f"{seed}#{i}".encode("utf-8")).digest()
        vals.append(int.from_bytes(digest[:4], "little") / (2 ** 32 - 1) * 2 - 1)
        i += 1
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


def _space_vectors(texts, space: str) -> list[list[float]]:
    return [_unit(f"{space}|{t}") for t in texts]


def _rotated_vectors(texts, space: str, cos: float) -> list[list[float]]:
    """Вектор с ЗАДАННЫМ косинусом к space-вектору (ортогональная примесь)."""
    out: list[list[float]] = []
    for text in texts:
        base = _unit(f"{space}|{text}")
        orth = _unit(f"orth|{space}|{text}")
        proj = sum(a * b for a, b in zip(base, orth))
        orth = [o - proj * b for o, b in zip(orth, base)]
        norm = math.sqrt(sum(v * v for v in orth)) or 1.0
        orth = [v / norm for v in orth]
        s = math.sqrt(max(0.0, 1.0 - cos * cos))
        out.append([cos * b + s * o for b, o in zip(base, orth)])
    return out


class _Embedder:
    """Мок ТОЛЬКО HTTP: считает вызовы и отдаёт векторы выбранного пространства.

    `cos_sequence` — косинус по номеру вызова (полоса повторной пробы)."""

    def __init__(self, *, space: str = "space-a", dim: int = DIMS,
                 cos_sequence=None, fail: bool = False):
        self.space = space
        self.dim = dim
        self.cos_sequence = list(cos_sequence or [])
        self.fail = fail
        self.calls: list[list[str]] = []

    async def __call__(self, texts):
        texts = list(texts)
        self.calls.append(texts)
        if self.fail:
            raise RuntimeError("embedding API unavailable")
        if self.dim != DIMS:
            return [_unit(f"{self.space}|{t}", self.dim) for t in texts]
        if self.cos_sequence:
            idx = min(len(self.calls) - 1, len(self.cos_sequence) - 1)
            return _rotated_vectors(texts, self.space, self.cos_sequence[idx])
        return _space_vectors(texts, self.space)


def _docs(n: int = 20) -> list[tuple[int, str]]:
    """Два чата; длины покрывают бакеты (<200 / 200–1999 / ≥2000)."""
    out: list[tuple[int, str]] = []
    for i in range(n):
        chat = 101 if i % 2 == 0 else 202
        if i % 4 == 0:
            text = f"короткий факт {i} про память"
        elif i % 4 == 1:
            text = f"средний факт {i}: " + ("контекст " * 40)
        elif i % 4 == 2:
            text = f"длинный факт {i}: " + ("история сообщений " * 160)
        else:
            text = f"факт {i} о смене embedding-провайдера"
        out.append((chat, text))
    return out


def _live_sql(mm) -> str:
    return mm._graph_vec_table_sql(DIMS)


async def _seed(ctx, docs) -> list[list[float]]:
    """Старые факты + СТАРЫЕ векторы в live-индексе (space-a)."""
    now = int(time.time())
    await ctx.db.db.execute(_live_sql(ctx.mm))
    await ctx.db.db.commit()
    vectors = _space_vectors([t for _c, t in docs], "space-a")
    for (chat_id, text), vec in zip(docs, vectors):
        cursor = await ctx.db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (?, ?, 'chat_history', ?)", (chat_id, text, now))
        fact_id = int(cursor.lastrowid)
        await ctx.db.db.execute(
            "INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, "
            "expires_at, embedding) VALUES (?, ?, ?, 'chat_history', NULL, ?)",
            (fact_id, fact_id, chat_id, json.dumps(vec)))
    await ctx.db.db.commit()
    return vectors


async def _register_generation(ctx, fp: str, *, model: str = MODEL,
                               dims: int = DIMS, status: str = "building",
                               provider: str = OLD_PROVIDER) -> dict:
    await ctx.db.ensure_embedding_generation(
        INDEX, fp, provider=provider, model=model, dims=dims,
        preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint="legacy-endpoint",
        activate=(status == "active"))
    row = await ctx.db.get_generation_by_fingerprint(INDEX, fp)
    assert row is not None and row["status"] == status
    return row


async def _count(db, sql: str, params=()) -> int:
    cursor = await db.db.execute(sql, params)
    return int((await cursor.fetchone())["c"])


async def _generation_rows(db) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT * FROM mca_embedding_index_generations WHERE index_name = ? "
        "ORDER BY generation ASC", (INDEX,))
    return [dict(r) for r in await cursor.fetchall()]


def _gateway_swap(ctx) -> tuple[str, str]:
    """Старый identity → новый шлюз (та же модель). Возвращает (old, new)."""
    old_fp = ctx.mm._identity_fingerprint()
    ctx.hot.base_url = NEW_HOST
    new_fp = ctx.mm._identity_fingerprint()
    assert new_fp != old_fp
    return old_fp, new_fp


async def _resolve(ctx, fp, *, dims: int = DIMS) -> dict:
    return await ecp.resolve_index_compat(
        ctx.db, INDEX, current_fp=fp, current_dims=dims)


async def _ensure(ctx, fp, embedder, *, dims: int = DIMS) -> dict:
    return await ecp.ensure_index_compat(
        ctx.db, INDEX, current_fp=fp, current_dims=dims,
        embed_fn=embedder, force_probe=True)


# ── 1. Одна модель, одинаковые векторы, разные API-провайдеры ───────────────

@pytest.mark.asyncio
async def test_scenario_01_gateway_swap_adopts_existing_index(ctx):
    """Смена ТОЛЬКО шлюза: adopt существующего поколения, rebuild не стартует,
    провенанс (fingerprint/provider/endpoint) не перезаписывается."""
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    compat = await _resolve(ctx, new_fp)
    assert compat["state"] == ecp.STATE_INSUFFICIENT
    assert compat["needs_probe"] is True
    assert compat["class"] == ecp.COMPAT_UNKNOWN
    assert compat["serviceable"] is False

    embedder = _Embedder(space="space-a")
    result = await _ensure(ctx, new_fp, embedder)
    assert result["state"] == ecp.STATE_COMPATIBLE
    assert result["class"] == ecp.COMPAT_ADMITTED
    assert result["serviceable"] is True
    canary = result["canary"]
    assert canary["checked"] >= ecp.COMPAT_PROBE_MIN_SAMPLE
    assert canary["mean"] >= ecp.COMPAT_PROBE_MEAN_MIN
    assert canary["min"] >= ecp.COMPAT_PROBE_MIN_MIN
    assert canary["hit5"] >= ecp.COMPAT_PROBE_HIT5_MIN
    assert len(embedder.calls) == 1, "проба обязана быть ОДНИМ батчем"

    active = await ctx.db.get_active_embedding_generation(INDEX)
    assert active["fingerprint"] == old_fp, "провенанс: fingerprint старый"
    assert active["provider"] == OLD_PROVIDER
    assert active["endpoint_fingerprint"] == "legacy-endpoint"
    assert str(active["config_revision"]).startswith("adopt1:")
    parsed = ecp.parse_admission(active["config_revision"])
    assert parsed["space"] == result["space"]
    assert parsed["conn"] == result["conn"]

    rows = await _generation_rows(ctx.db)
    assert len(rows) == 1, "никаких новых поколений при adopt"
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == []
    assert await ctx.mm._index_generation_ok(INDEX) is True
    assert await ctx.mm._vec_write_allowed(INDEX) is True
    live = await _count(ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec")
    assert live == len(docs)


# ── 2. Малая численная погрешность: полоса → независимый повтор ─────────────

@pytest.mark.asyncio
async def test_scenario_02a_band_requires_repeat_then_compatible(ctx):
    """mean в полосе 0.970–0.995: один независимый повтор; compatible только
    если ОБА прогона compatible (повтор не апгрейдит сам по себе)."""
    await _seed(ctx, _docs())
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    embedder = _Embedder(space="space-a", cos_sequence=[0.99, 1.0])
    result = await _ensure(ctx, new_fp, embedder)
    assert len(embedder.calls) == 2, "полоса обязана дать ровно один повтор"
    assert result["state"] == ecp.STATE_COMPATIBLE
    assert result["canary"]["runs"] == 2
    assert result["canary"]["mean"] >= ecp.COMPAT_PROBE_MEAN_MIN
    assert result["canary"]["band"]["mean"] < ecp.COMPAT_PROBE_MEAN_MIN


@pytest.mark.asyncio
async def test_scenario_02b_band_repeat_not_compatible_is_insufficient(ctx):
    """Повтор не подтвердил полосу → insufficient: НЕ adopt, НЕ rebuild,
    данные целы (индекс/факты/поколение)."""
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    embedder = _Embedder(space="space-a", cos_sequence=[0.99, 0.95])
    result = await _ensure(ctx, new_fp, embedder)
    assert result["state"] == ecp.STATE_INSUFFICIENT
    assert result["serviceable"] is False
    assert result["action"] in ("retry_canary", "need_old_vectors")
    active = await ctx.db.get_active_embedding_generation(INDEX)
    assert active is None, "недоказанная совместимость не активируется"
    rows = await _generation_rows(ctx.db)
    assert len(rows) == 1 and rows[0]["status"] == "building"
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == []
    live = await _count(ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec")
    assert live == len(docs)


# ── 3. Одинаковое имя модели, но РАЗНЫЕ фактические векторы ─────────────────

@pytest.mark.asyncio
async def test_scenario_03_same_name_different_space_is_incompatible(ctx):
    """Одного совпадения имени модели мало: другие векторы → incompatible,
    контролируемая миграция (target-generation), запись закрыта до promotion."""
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    embedder = _Embedder(space="space-b")     # другое пространство
    result = await _ensure(ctx, new_fp, embedder)
    assert result["state"] == ecp.STATE_INCOMPATIBLE
    assert result["reason_code"] in ("numeric_divergence", "low_hit5")
    # Проверка ПОИСКА, а не только размерности: новый вектор не находит
    # старый факт в top-5.
    assert (result["canary"]["hit5"] or 0.0) < ecp.COMPAT_PROBE_HIT5_MIN
    assert await ctx.db.get_active_embedding_generation(INDEX) is None

    assert await gr.maybe_schedule_rebuilds(ctx.mm) == [INDEX]
    target = await ctx.db.get_generation_by_fingerprint(INDEX, new_fp)
    assert target is not None and target["status"] == "building"
    assert await ctx.mm._vec_write_allowed(INDEX) is False
    live = await _count(ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec")
    assert live == len(docs), "live не смешивается и не чистится"


# ── 4. Разные модели/размерности: индексы не смешиваются ────────────────────

@pytest.mark.asyncio
async def test_scenario_04_dimension_mismatch_never_mixes(ctx):
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    compat = await _resolve(ctx, new_fp, dims=16)
    assert compat["state"] == ecp.STATE_INCOMPATIBLE
    assert compat["reason_code"] == "dimension_changed"
    assert compat["class"] == ecp.COMPAT_DIMENSION

    # Проба тоже доказывает расхождение размерностей (физически: старые
    # векторы 8, API вернул 16).
    probe = await ecp.compat_probe(
        ctx.db, INDEX, embed_fn=_Embedder(space="space-a", dim=16))
    assert probe["verdict"] == ecp.STATE_INCOMPATIBLE
    assert probe["reason_code"] == "dim_mismatch"

    result = await _ensure(ctx, new_fp, _Embedder(space="space-a", dim=16),
                           dims=16)
    assert result["state"] == ecp.STATE_INCOMPATIBLE
    assert result["reason_code"] == "dimension_changed"
    assert await ctx.db.get_active_embedding_generation(INDEX) is None
    live = await _count(ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec")
    assert live == len(docs)


# ── 5. API недоступен: ничего не теряется, автоматики нет ───────────────────

@pytest.mark.asyncio
async def test_scenario_05_api_unavailable_is_insufficient_keeps_data(ctx):
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    result = await _ensure(ctx, new_fp, _Embedder(fail=True))
    assert result["state"] == ecp.STATE_INSUFFICIENT
    assert result["reason_code"] == "api_unavailable"
    assert result["action"] == "retry_canary"
    assert result["canary"]["checked"] == 0

    rows = await _generation_rows(ctx.db)
    assert len(rows) == 1 and rows[0]["status"] == "building"
    assert await gr._find_active_job(ctx.db, INDEX, new_fp) is None
    assert await ctx.db.get_active_embedding_generation(INDEX) is None
    assert await _count(ctx.db, "SELECT COUNT(*) AS c FROM graph_facts") == \
        len(docs)
    assert await _count(ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") == \
        len(docs)
    assert await ctx.mm._index_generation_ok(INDEX) is False
    # поиск жив: FTS-путь не отключён и факты на месте
    health = await gr.generation_status(ctx.db, current_fp=new_fp,
                                        current_dims=DIMS)
    graph = {i["index"]: i for i in health["indexes"]}[INDEX]
    assert graph["state"] == "compat_insufficient"
    assert graph["reindex_required"] is False
    assert graph["reason_code"] in ("api_unavailable", "compat_not_proven")


# ── 6. Возврат к прежнему провайдеру: старый индекс переиспользуется ────────

@pytest.mark.asyncio
async def test_scenario_06_flip_back_reuses_confirmed_index(ctx):
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)
    assert (await _ensure(ctx, new_fp, _Embedder(space="space-a")))[
        "state"] == ecp.STATE_COMPATIBLE

    ctx.hot.base_url = OLD_HOST                 # A → B → A
    back_fp = ctx.mm._identity_fingerprint()
    assert back_fp == old_fp

    failing = _Embedder(fail=True)
    compat = await _resolve(ctx, back_fp)
    assert compat["state"] == ecp.STATE_COMPATIBLE
    assert compat["class"] == ecp.COMPAT_INSTANT
    result = await _ensure(ctx, back_fp, failing)
    assert result["state"] == ecp.STATE_COMPATIBLE
    assert failing.calls == [], "при fp==current проба не нужна"
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == []
    assert await ctx.mm._vec_write_allowed(INDEX) is True


# ── 7. Рестарт: вердикт из config_revision, повторной перестройки нет ───────

@pytest.mark.asyncio
async def test_scenario_07_restart_reads_durable_admission(ctx):
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)
    assert (await _ensure(ctx, new_fp, _Embedder(space="space-a")))[
        "state"] == ecp.STATE_COMPATIBLE

    # «Рестарт»: новый MemoryManager и пустой process-кэш вердиктов.
    ecp.reset_compat_state()
    restarted = sm.MemoryManager(ctx.db, None)
    restarted._vec_dim = DIMS
    restarted._vec_available = True
    restarted._vec_int8 = False

    failing = _Embedder(fail=True)
    compat = await ecp.resolve_index_compat(
        ctx.db, INDEX, current_fp=new_fp, current_dims=DIMS)
    assert compat["state"] == ecp.STATE_COMPATIBLE
    assert compat["class"] == ecp.COMPAT_ADMITTED
    assert compat["canary"]["source"] == "admission"
    restarted_result = await ecp.ensure_index_compat(
        ctx.db, INDEX, current_fp=new_fp, current_dims=DIMS,
        embed_fn=failing)
    assert restarted_result["state"] == ecp.STATE_COMPATIBLE
    assert failing.calls == [], "рестарт не перепроверяет settled-допуск"
    assert await restarted._index_generation_ok(INDEX) is True
    assert await gr.ensure_current_generation(restarted, INDEX) is None
    assert await gr.maybe_schedule_rebuilds(restarted) == []
    rows = await _generation_rows(ctx.db)
    assert len(rows) == 1 and rows[0]["status"] == "active"


# ── 8. Два чата: выборка покрывает оба, один adopt, изоляция цела ───────────

@pytest.mark.asyncio
async def test_scenario_08_two_chats_single_adopt_no_isolation_break(ctx):
    docs = _docs(12)
    chats = {chat for chat, _t in docs}
    assert len(chats) == 2
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    row = await _register_generation(ctx, old_fp)

    probe = await ecp.compat_probe(ctx.db, INDEX,
                                   embed_fn=_Embedder(space="space-a"))
    assert probe["verdict"] == ecp.STATE_COMPATIBLE
    cursor = await ctx.db.db.execute(
        "SELECT f.chat_id AS chat_id FROM graph_facts f WHERE f.id IN ("
        + ",".join("?" for _ in probe["sample_ids"]) + ")",
        tuple(probe["sample_ids"]))
    sampled = {int(r["chat_id"]) for r in await cursor.fetchall()}
    assert sampled == chats, "выборка обязана покрывать оба chat_id"
    before_cursor = await ctx.db.db.execute(
        "SELECT fact_id, chat_id FROM graph_facts_vec ORDER BY fact_id")
    before = [dict(r) for r in await before_cursor.fetchall()]

    assert (await _ensure(ctx, new_fp, _Embedder(space="space-a")))[
        "state"] == ecp.STATE_COMPATIBLE
    actives = await ctx.db.get_active_embedding_generations()
    assert len([a for a in actives if a["index_name"] == INDEX]) == 1
    adopted = await ctx.db.get_active_embedding_generation(INDEX)
    assert adopted["fingerprint"] == old_fp
    assert int(adopted["generation"]) == int(row["generation"])
    after_cursor = await ctx.db.db.execute(
        "SELECT fact_id, chat_id FROM graph_facts_vec ORDER BY fact_id")
    after = [dict(r) for r in await after_cursor.fetchall()]
    assert before == after, "adopt не меняет строки/chat_id старых векторов"
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == [], \
        "два чата не дают дублей перестроек"


# ── 9. Уже запущенный rebuild отменяется после adopt ───────────────────────

@pytest.mark.asyncio
async def test_scenario_09_running_rebuild_cancelled_by_adopt(ctx):
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)
    # Старый код уже успел зарегистрировать target и запустить сборку.
    target_row = await _register_generation(ctx, new_fp)
    job_id = await gr._ensure_job(ctx.db, INDEX, new_fp,
                                  int(target_row["generation"]))
    assert job_id
    await gr._job_cas(ctx.db, job_id, expect=gr.ST_QUEUED,
                      set_status=gr.ST_RUNNING)
    assert (await gr._get_job(ctx.db, job_id))["status"] == gr.ST_RUNNING

    result = await _ensure(ctx, new_fp, _Embedder(space="space-a"))
    assert result["state"] == ecp.STATE_COMPATIBLE
    assert (await gr._get_job(ctx.db, job_id))["status"] == gr.ST_CANCELLED
    adopted = await ctx.db.get_active_embedding_generation(INDEX)
    assert adopted["fingerprint"] == old_fp, "принят СТАРЫЙ провенанс"
    superseded = await ctx.db.get_generation_by_fingerprint(INDEX, new_fp)
    assert superseded["status"] == "superseded"
    assert await _count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") == len(docs)
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == []


# ── 10. Поиск по старым фактам новым API: реальная выдача ──────────────────

@pytest.mark.asyncio
async def test_scenario_10_search_new_api_finds_old_facts(ctx):
    """KNN новым вектором к СТАРОМУ индексу: hit5 доказывает выдачу, а не
    только совпадение размерности."""
    await _seed(ctx, _docs())
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    probe = await ecp.compat_probe(ctx.db, INDEX,
                                   embed_fn=_Embedder(space="space-a"))
    assert probe["verdict"] == ecp.STATE_COMPATIBLE
    assert probe["hit5"] == 1.0, "точные векторы обязаны находить свой факт"
    assert probe["checked"] >= 8

    # Контроль: то же число измерений, но другое пространство → выдача падает.
    wrong = await ecp.compat_probe(ctx.db, INDEX,
                                   embed_fn=_Embedder(space="space-b"))
    assert wrong["verdict"] == ecp.STATE_INCOMPATIBLE
    assert (wrong["hit5"] or 0.0) <= ecp.COMPAT_PROBE_HIT5_FLOOR


# ── анти-тест: «новое против нового» доказательством не является ────────────

@pytest.mark.asyncio
async def test_antitheorem_new_vs_new_cannot_prove_compatibility(ctx):
    """Эталоны, созданные НОВЫМ провайдером (embedding_cache), не доказывают
    совместимость со СТАРЫМ индексом: живого индекса нет → insufficient."""
    docs = _docs()
    now = int(time.time())
    # источник есть, live пуст; embedding_cache полон «новых» векторов
    for chat_id, text in docs:
        await ctx.db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (?, ?, 'chat_history', ?)", (chat_id, text, now))
        await ctx.db.db.execute(
            "INSERT INTO embedding_cache(text_hash, text, vector, dim, "
            "created_at, last_used_at) VALUES (?,?,?,?,?,?)",
            (hashlib.sha256(text.encode()).hexdigest(), text,
             json.dumps(_space_vectors([text], "space-a")[0]), DIMS, now, now))
    await ctx.db.db.commit()
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    compat = await _resolve(ctx, new_fp)
    assert compat["state"] == ecp.STATE_NO_GENERATION
    probe = await ecp.compat_probe(ctx.db, INDEX,
                                   embed_fn=_Embedder(space="space-a"))
    assert probe["verdict"] == ecp.STATE_INSUFFICIENT
    assert probe["reason_code"] == "no_old_vectors"
    result = await _ensure(ctx, new_fp, _Embedder(space="space-a"))
    assert result["state"] != ecp.STATE_COMPATIBLE
    assert await ctx.db.get_active_embedding_generation(INDEX) is None


# ── Guard: kill-switch OFF = прежнее поведение ──────────────────────────────

@pytest.mark.asyncio
async def test_kill_switch_off_restores_legacy_rebuild(ctx, monkeypatch):
    monkeypatch.setenv("EMBED_COMPAT_ADOPTION_ENABLED", "0")
    assert ecp.adoption_enabled() is False
    await _seed(ctx, _docs())
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    compat = await _resolve(ctx, new_fp)
    assert compat["state"] == ecp.STATE_INCOMPATIBLE
    assert compat["adoption_enabled"] is False
    failing = _Embedder(fail=True)
    result = await _ensure(ctx, new_fp, failing)
    assert result["state"] == ecp.STATE_INCOMPATIBLE
    assert failing.calls == [], "OFF не запускает пробу"
    assert await gr.maybe_schedule_rebuilds(ctx.mm) == [INDEX]
    target = await ctx.db.get_generation_by_fingerprint(INDEX, new_fp)
    assert target is not None and target["status"] == "building"


# ── Guard: мусорный config_revision — fail-closed ──────────────────────────

@pytest.mark.asyncio
async def test_garbage_admission_fails_closed(ctx):
    await _seed(ctx, _docs())
    old_fp, new_fp = _gateway_swap(ctx)
    await ctx.db.ensure_embedding_generation(
        INDEX, old_fp, provider=OLD_PROVIDER, model=MODEL, dims=DIMS,
        preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint="legacy-endpoint", activate=True,
        config_revision="rev-from-migration")
    assert ecp.parse_admission("rev-from-migration") is None
    compat = await _resolve(ctx, new_fp)
    assert compat["state"] == ecp.STATE_INSUFFICIENT
    assert compat["serviceable"] is False

    result = await _ensure(ctx, new_fp, _Embedder(space="space-a"))
    assert result["state"] != ecp.STATE_COMPATIBLE
    assert result["reason_code"] == "adopt_refused"
    active = await ctx.db.get_active_embedding_generation(INDEX)
    assert active["config_revision"] == "rev-from-migration", \
        "чужой revision не перезаписывается"


# ── Guard: adopt идемпотентен, чужой ACTIVE не подменяется ─────────────────

@pytest.mark.asyncio
async def test_adopt_idempotent_and_never_steals_other_active(ctx):
    await _seed(ctx, _docs())
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)
    admission = ecp.format_admission(
        ecp.model_space_identity(model=MODEL, dimension=DIMS),
        ecp.connection_identity(ecp.resolve_embedding_profiles()["primary"]),
        12, 0.999, 0.998, 1.0, int(time.time()))
    first = await ctx.db.adopt_embedding_generation(INDEX, old_fp,
                                                    admission=admission)
    second = await ctx.db.adopt_embedding_generation(INDEX, old_fp,
                                                     admission=admission)
    assert first is not None and second is not None
    assert first["generation_id"] == second["generation_id"]
    rows = await _generation_rows(ctx.db)
    assert len(rows) == 1 and rows[0]["config_revision"] == admission

    # Другой ACTIVE (другое поколение) — adopt не имеет права подменять.
    other = await ctx.db.register_embedding_target_generation(
        INDEX, "other-fp", provider=OLD_PROVIDER, model=MODEL, dims=DIMS,
        preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint="legacy-endpoint")
    assert other is not None
    refused = await ctx.db.adopt_embedding_generation(
        INDEX, "other-fp", admission=admission)
    assert refused is None
    assert (await ctx.db.get_active_embedding_generation(INDEX))[
        "fingerprint"] == old_fp


# ── INT: единый вердикт читают все точки ──────────────────────────────────

@pytest.mark.asyncio
async def test_register_gate_and_inline_probe_wiring(ctx, monkeypatch):
    """`_register_index_generations` не создаёт target до вердикта, а
    `_ensure_index_compat_inline` (вызывается из initialize ДО recovery/
    backfill) делает adopt; фоновая drift-canary на это время молчит."""
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    await ctx.mm._register_index_generations(activate=False)
    rows = await _generation_rows(ctx.db)
    assert len(rows) == 1, "до вердикта новое building-поколение не регистрируется"
    assert rows[0]["fingerprint"] == old_fp

    embedder = _Embedder(space="space-a")
    monkeypatch.setattr(ctx.mm, "_compat_probe_embed", embedder)
    assert ecp.compat_pending() is False
    await ctx.mm._ensure_index_compat_inline()
    assert len(embedder.calls) == 1
    assert (await ctx.db.get_active_embedding_generation(INDEX))[
        "fingerprint"] == old_fp
    assert await ctx.mm._index_generation_ok(INDEX) is True
    assert ecp.compat_pending() is False

    # После adopt регистрация тоже не создаёт лишних поколений.
    await ctx.mm._register_index_generations(activate=False)
    assert len(await _generation_rows(ctx.db)) == 1

    # Пока вердикт не получен — фоновая drift-canary не дёргает API
    # (эталоны нового fp создавались бы новым же провайдером).
    ecp.reset_compat_state()
    monkeypatch.setattr(ctx.mm, "_identity_fingerprint",
                        lambda **kw: "canary-skip-sentinel-fp")
    calls: list[list[str]] = []

    async def _embed(texts, *, priority=None):
        calls.append(list(texts))
        return _space_vectors(texts, "space-a")

    monkeypatch.setattr(ctx.mm, "_embed", _embed)
    monkeypatch.setattr(
        sm, "fire_and_forget",
        lambda coro, tag: asyncio.ensure_future(coro))
    ecp.note_compat_pending(INDEX, pending=True)
    ctx.mm._schedule_canary_probe()
    await asyncio.sleep(0.01)
    assert calls == [], "при незавершённом вердикте drift-canary не зовёт API"
    # Контроль: без ожидающего вердикта проба выполняется (гейт не «всегда off»).
    ecp.note_compat_pending(INDEX, pending=False)
    ctx.mm._schedule_canary_probe()
    await asyncio.sleep(0.01)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_insufficient_pauses_rebuild_until_verdict(ctx):
    """Пока вердикта нет, уже запущенная сборка под новый fp — на паузе
    (не сжигаем 316 вызовов); доказанная несовместимость снимает паузу."""
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)
    target = await _register_generation(ctx, new_fp)
    job_id = await gr._ensure_job(ctx.db, INDEX, new_fp,
                                  int(target["generation"]))
    await gr._job_cas(ctx.db, job_id, expect=gr.ST_QUEUED,
                      set_status=gr.ST_RUNNING)

    pending = await _ensure(ctx, new_fp, _Embedder(fail=True))
    assert pending["state"] == ecp.STATE_INSUFFICIENT
    assert (await gr._get_job(ctx.db, job_id))["status"] == gr.ST_PAUSED

    proven = await _ensure(ctx, new_fp, _Embedder(space="space-b"))
    assert proven["state"] == ecp.STATE_INCOMPATIBLE
    assert (await gr._get_job(ctx.db, job_id))["status"] in (
        gr.ST_QUEUED, gr.ST_PAUSED_RATE_LIMIT, gr.ST_PAUSED_PROVIDER)


@pytest.mark.asyncio
async def test_uneven_chats_still_reach_min_sample(ctx):
    """Неравномерные чаты: ≤6 на чат могло дать <8 — выборка добирается
    детерминированно до min 8 (без RANDOM) и покрывает оба chat_id."""
    docs = [(900, "единственный факт малого чата")] + [
        (901, f"факт большого чата номер {i} " + ("контекст " * 30))
        for i in range(15)]
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)
    probe = await ecp.compat_probe(ctx.db, INDEX,
                                   embed_fn=_Embedder(space="space-a"))
    assert probe["checked"] >= ecp.COMPAT_PROBE_MIN_SAMPLE
    cursor = await ctx.db.db.execute(
        "SELECT f.chat_id AS chat_id FROM graph_facts f WHERE f.id IN ("
        + ",".join("?" for _ in probe["sample_ids"]) + ")",
        tuple(probe["sample_ids"]))
    sampled = {int(r["chat_id"]) for r in await cursor.fetchall()}
    assert sampled == {900, 901}
    assert (await _ensure(ctx, new_fp, _Embedder(space="space-a")))[
        "state"] == ecp.STATE_COMPATIBLE


@pytest.mark.asyncio
async def test_new_write_after_adopt_is_searchable(ctx):
    """DEC-05: после adopt новые записи идут в ТОТ ЖЕ индекс через новый API
    и находятся поиском (без перестройки старых векторов)."""
    await _seed(ctx, _docs())
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)
    assert (await _ensure(ctx, new_fp, _Embedder(space="space-a")))[
        "state"] == ecp.STATE_COMPATIBLE
    assert await ctx.mm._vec_write_allowed(INDEX) is True

    text = "новый факт после смены шлюза"
    cursor = await ctx.db.db.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
        "VALUES (?, ?, 'chat_history', ?)", (303, text, int(time.time())))
    fact_id = int(cursor.lastrowid)
    vector = _space_vectors([text], "space-a")[0]
    await ctx.mm._insert_graph_vec_row(fact_id, 303, text, "chat_history",
                                       None, vector)
    await ctx.db.db.commit()

    knn = await ecp._knn_top_ids(ctx.db, INDEX, vector, k=1)
    assert knn and fact_id in knn, "новая запись находится тем же индексом"
    assert await _count(ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") \
        == len(_docs()) + 1


@pytest.mark.asyncio
async def test_generation_status_and_panel_share_verdict(ctx):
    await _seed(ctx, _docs())
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    pending = await gr.generation_status(ctx.db, current_fp=new_fp,
                                         current_dims=DIMS)
    graph = {i["index"]: i for i in pending["indexes"]}[INDEX]
    assert graph["state"] == "compat_insufficient"
    assert graph["serviceable"] is False
    assert graph["needs_probe"] is True
    assert graph["reindex_required"] is False

    assert (await _ensure(ctx, new_fp, _Embedder(space="space-a")))[
        "state"] == ecp.STATE_COMPATIBLE
    done = await gr.generation_status(ctx.db, current_fp=new_fp,
                                      current_dims=DIMS)
    graph = {i["index"]: i for i in done["indexes"]}[INDEX]
    assert graph["state"] == "active"
    assert graph["serviceable"] is True
    assert graph["compat_class"] == ecp.COMPAT_ADMITTED
    assert graph["compat"]["admission"]["checked"] >= 8

    # Панель читает ТО ЖЕ решение (без сети) и не врёт про reindex.
    await gr._ensure_job(ctx.db, INDEX, old_fp, 1)
    panel = await ecp.vector_memory_panel(ctx.db)
    entry = next(e for e in panel["indexes"] if e["index"] == INDEX)
    assert entry["compat"]["state"] == ecp.STATE_COMPATIBLE
    assert entry["compat"]["serviceable"] is True
    assert entry["compat_class"] == ecp.COMPAT_ADMITTED
    assert entry["compat"]["canary"]["checked"] >= 8


# ── 11. IDENT-02: MSI реагирует на КАЖДОЕ поле identity ─────────────────────
# TEST-LIFECYCLE: CONTRACT owner=EMBED-IDENTITY-COMPAT

_MSI_BASE = dict(model=MODEL, revision="rev-1", dimension=DIMS,
                 task_mode=ecp.EMBEDDING_TASK_MODE,
                 normalization=ecp.EMBEDDING_NORMALIZATION,
                 preprocessing_version="prep-1",
                 material_params={"task": "retrieval", "dimensions": "8"})


def test_ident_02_msi_changes_with_every_identity_field():
    """L13: model/revision/dims/task_mode/normalization/preprocessing/
    материальные параметры — каждое поле по отдельности меняет MSI."""
    base = ecp.model_space_identity(**_MSI_BASE)
    variants = {
        "model": {"model": OTHER_MODEL},
        "revision": {"revision": "rev-2"},
        "dimension": {"dimension": 16},
        "task_mode": {"task_mode": "text-embedding/query.v1"},
        "normalization": {"normalization": "l2-normalized-v1"},
        "preprocessing_version": {"preprocessing_version": "prep-2"},
        "material_params": {"material_params": {"task": "retrieval",
                                                "dimensions": "16"}},
    }
    for field, change in variants.items():
        altered = dict(_MSI_BASE)
        altered.update(change)
        assert ecp.model_space_identity(**altered) != base, \
            f"MSI не изменился при изменении {field}"


def test_ident_02_msi_stable_for_equal_values_and_param_order():
    """Одинаковые значения → одинаковый MSI: порядок material_params,
    None/'', те же явно переданные константы ничего не меняют."""
    base = ecp.model_space_identity(**_MSI_BASE)
    reordered = dict(_MSI_BASE, material_params={"dimensions": "8",
                                                 "task": "retrieval"})
    assert ecp.model_space_identity(**reordered) == base
    assert ecp.model_space_identity(**_MSI_BASE) == base
    assert ecp.model_space_identity(**dict(_MSI_BASE, revision=None)) == \
        ecp.model_space_identity(**dict(_MSI_BASE, revision=""))
    assert ecp.model_space_identity(model=MODEL, dimension=DIMS) == \
        ecp.model_space_identity(
            model=MODEL, dimension=DIMS, revision="",
            task_mode=ecp.EMBEDDING_TASK_MODE,
            normalization=ecp.EMBEDDING_NORMALIZATION,
            preprocessing_version=ecp._current_preprocessing_version(),
            material_params={})


# ── 12. CANARY-03: проба фиксирует ФАКТИЧЕСКИЕ метаданные ответа ────────────

class _MetaEmbedder(_Embedder):
    """CANARY-03: мок HTTP, возвращающий метаданные ТЕЛА ответа провайдера."""

    def __init__(self, *, answer_model=MODEL, revision=None, params=None,
                 dims_meta=None, **kwargs):
        super().__init__(**kwargs)
        self.answer_model = answer_model
        self.answer_revision = revision
        self.answer_params = params
        self.dims_meta = dims_meta

    async def __call__(self, texts):
        vectors = await super().__call__(texts)
        return {"vectors": vectors, "model": self.answer_model,
                "revision": self.answer_revision,
                "params": self.answer_params, "dims": self.dims_meta}


@pytest.mark.asyncio
async def test_canary_03_probe_records_actual_metadata(ctx):
    """Проба возвращает фактическую model из ответа, доступную revision и
    параметры генерации; при полном наборе метаданных compatible идёт без
    информационного reason_code."""
    await _seed(ctx, _docs())
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    def _answer():
        return _MetaEmbedder(answer_model=" Models/gemini-embedding-001 ",
                             revision="2026-09-01",
                             params={"task": "retrieval", "dimensions": "8"},
                             dims_meta=DIMS)

    probe = await ecp.compat_probe(ctx.db, INDEX, embed_fn=_answer())
    assert probe["verdict"] == ecp.STATE_COMPATIBLE
    meta = probe["metadata"]
    assert meta["model"] == "Models/gemini-embedding-001", \
        "модель фиксируется из ответа, а не из конфига"
    assert ecp._normalized_model_name(meta["model"]) == \
        ecp._normalized_model_name(MODEL)
    assert meta["model_expected"] == MODEL
    assert meta["model_known"] is True
    assert meta["revision"] == "2026-09-01" and meta["revision_known"] is True
    assert meta["params"] == {"task": "retrieval", "dimensions": "8"}
    assert meta["params_known"] is True
    assert meta["declared_dims"] == DIMS and meta["dims"] == DIMS
    assert probe["reason_code"] == ""

    result = await _ensure(ctx, new_fp, _answer())
    assert result["state"] == ecp.STATE_COMPATIBLE
    canary_meta = result["canary"]["metadata"]
    assert canary_meta["model"] == "Models/gemini-embedding-001"
    assert canary_meta["revision"] == "2026-09-01"
    assert canary_meta["params_known"] is True


@pytest.mark.asyncio
async def test_canary_03_explicit_model_mismatch_is_incompatible(ctx):
    """Явное несовпадение фактической модели с заявленной — incompatible
    ДО числовых метрик (имя модели не «переспорить» совпадением векторов)."""
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    def _answer():
        return _MetaEmbedder(answer_model=OTHER_MODEL, revision="rev-x",
                             params={})

    probe = await ecp.compat_probe(ctx.db, INDEX, embed_fn=_answer())
    assert probe["verdict"] == ecp.STATE_INCOMPATIBLE
    assert probe["reason_code"] == "model_mismatch"
    assert probe["metadata"]["model"] == OTHER_MODEL
    assert probe["metadata"]["model_expected"] == MODEL

    result = await _ensure(ctx, new_fp, _answer())
    assert result["state"] == ecp.STATE_INCOMPATIBLE
    assert result["reason_code"] == "model_mismatch"
    assert await ctx.db.get_active_embedding_generation(INDEX) is None
    assert await _count(ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") \
        == len(docs)


@pytest.mark.asyncio
async def test_canary_03_missing_revision_or_params_not_insufficient(ctx):
    """Отсутствие revision/params в ответе → revision_unknown/params_unknown,
    НЕ insufficient: решающее доказательство — старые векторы + KNN-hit5."""
    docs = _docs()
    await _seed(ctx, docs)
    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)

    no_revision = _MetaEmbedder(answer_model=MODEL, revision=None, params=None)
    probe = await ecp.compat_probe(ctx.db, INDEX, embed_fn=no_revision)
    assert probe["verdict"] == ecp.STATE_COMPATIBLE
    assert probe["reason_code"] == "revision_unknown"
    assert probe["metadata"]["revision_known"] is False
    assert probe["metadata"]["params_known"] is False
    assert probe["metadata"]["model_known"] is True

    no_params = _MetaEmbedder(answer_model=MODEL, revision="rev-9", params=None)
    probe2 = await ecp.compat_probe(ctx.db, INDEX, embed_fn=no_params)
    assert probe2["verdict"] == ecp.STATE_COMPATIBLE
    assert probe2["reason_code"] == "params_unknown"
    assert probe2["metadata"]["revision_known"] is True
    assert probe2["metadata"]["params_known"] is False

    result = await _ensure(
        ctx, new_fp,
        _MetaEmbedder(answer_model=MODEL, revision=None, params=None))
    assert result["state"] == ecp.STATE_COMPATIBLE, \
        "недоступность revision/params не должна закрывать допуск"
    assert result["serviceable"] is True
    assert result["canary"]["metadata"]["revision_known"] is False
    active = await ctx.db.get_active_embedding_generation(INDEX)
    assert str(active["config_revision"]).startswith("adopt1:")
    assert await ctx.mm._index_generation_ok(INDEX) is True


# ── 13. DEC-09: откат допуска — данные целы, FTS обслуживает, adopt повторяем ─

@pytest.mark.asyncio
async def test_dec_09_rollback_after_adopt_keeps_data_and_is_reversible(ctx):
    """adopt → откат (status='building', config_revision=NULL) → vec закрыт,
    FTS отдаёт факты, векторы/факты целы; повторный adopt восстанавливает
    допуск без потерь."""
    docs = _docs()
    await _seed(ctx, docs)
    cursor = await ctx.db.db.execute("SELECT id, fact FROM graph_facts")
    for row in await cursor.fetchall():
        await ctx.db.db.execute(
            "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
            (int(row["id"]), str(row["fact"])))
    await ctx.db.db.commit()

    old_fp, new_fp = _gateway_swap(ctx)
    await _register_generation(ctx, old_fp)
    assert (await _ensure(ctx, new_fp, _Embedder(space="space-a")))[
        "state"] == ecp.STATE_COMPATIBLE
    active = await ctx.db.get_active_embedding_generation(INDEX)
    assert active["status"] == "active"
    assert str(active["config_revision"]).startswith("adopt1:")
    assert await ctx.mm._vec_write_allowed(INDEX) is True
    vectors_before = await _count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec")
    facts_before = await _count(ctx.db, "SELECT COUNT(*) AS c FROM graph_facts")

    # Откат допуска (снимаем «принятое» состояние поколения).
    await ctx.db.db.execute(
        "UPDATE mca_embedding_index_generations SET status='building', "
        "config_revision=NULL WHERE index_name=? AND fingerprint=?",
        (INDEX, old_fp))
    await ctx.db.db.commit()

    assert await ctx.db.get_active_embedding_generation(INDEX) is None
    assert await ctx.mm._index_generation_ok(INDEX) is False, \
        "vec-поиск закрыт после отката допуска"
    assert await ctx.mm._vec_write_allowed(INDEX) is False
    assert await _count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") == vectors_before
    assert await _count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts") == facts_before

    fts = await ctx.db.search_graph_facts_fts(
        101, '"факт"*', 5, int(time.time()))
    assert fts, "FTS-путь обязан обслуживать факты при закрытом vec"

    again = await _ensure(ctx, new_fp, _Embedder(space="space-a"))
    assert again["state"] == ecp.STATE_COMPATIBLE, "повторный adopt работает"
    restored = await ctx.db.get_active_embedding_generation(INDEX)
    assert restored["fingerprint"] == old_fp
    assert str(restored["config_revision"]).startswith("adopt1:")
    assert await ctx.mm._index_generation_ok(INDEX) is True
    assert await ctx.mm._vec_write_allowed(INDEX) is True
    assert await _count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts_vec") == vectors_before
    assert await _count(
        ctx.db, "SELECT COUNT(*) AS c FROM graph_facts") == facts_before
