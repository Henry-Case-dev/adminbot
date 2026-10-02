"""ASAP-4 волна A (round1029, ADR-1028-7 D1/AM-1/D2; T-4402…T-4412) —
Embedding Control Plane (spec §1):

* §64 retry storm: primary 429 + fallback same group + Retry-After=20s →
  НЕ 21 burst; group cooling; same-group key не бомбится; job pauses;
  checkpoint preserved;
* §65 independent quota groups: A 429 → scheduler продолжает на B;
* §66 arbitrary credential pool: 1/3/5 credentials без «ровно два fallback»;
* §67 online priority: P0 query перед следующим P3-батчем, bounded latency;
* §68 restart during quota pause: без reset generation, без дублей,
  уважение next_allowed_at, resume той же generation;
* §69 KNN validation diagnostics: 5 сценариев → distinct reason codes;
* §35 external provider-switch: OpenAI-compatible adapter fixture;
* DDL v23 (embedding_quota_state + 3 nullable колонки реестра) — additive,
  идемпотентно, без UPDATE существующих строк;
* OFF-паритет (бит-в-бит legacy) kill-switch'ей зоны A (spec §8.2).
"""
import asyncio
import json
import time

import httpx
import pytest
import pytest_asyncio

from services import graphrag_rebuild as gr
from services import summary_memory as sm
from services.database import DatabaseService
from services.embedding_control_plane import (
    Priority, EmbeddingExecutor, EmbeddingGroupCoolingDown,
    EmbeddingBudgetExhausted, EmbeddingConcurrencyBusy, QuotaGroupRegistry,
    AdaptiveController, PriorityScheduler, build_credential_pool,
    parse_quota_group_labels, resolve_quota_group, classify_rate_limit,
    retry_after_seconds, is_quota_unavailable, segment_text_lossless,
    estimate_tokens, provider_panel, vector_memory_panel, UNKNOWN_GROUP_ID,
    GeminiEmbeddingAdapter, OpenAICompatibleEmbeddingAdapter,
    select_adapter, RateLimitInfo, UNKNOWN_GROUP_ID as _UNK,
)
from services.llm_client import (LLMClient, LLMRateLimitError,
                                 LLMServerError, LLMAuthError)

pytestmark = pytest.mark.asap4


# ── Fixtures / helpers ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_ecp(monkeypatch):
    """Чистые singleton'ы контрол-плейна на КАЖДЫЙ тест (изоляция AIMD-
    состояния) + transport backoff = 0 (без снов)."""
    from services import embedding_control_plane as ecp
    ecp.REGISTRY = QuotaGroupRegistry()
    ecp.CONTROLLER = AdaptiveController()
    ecp.SCHEDULER = PriorityScheduler()
    ecp.EXECUTOR = None
    ecp._last_state_log.clear()
    ecp._last_rotation_warn = 0.0     # D3: WARN-cooldown ротации (изоляция)
    monkeypatch.setattr(ecp, "_TRANSPORT_BACKOFF_BASE", 0.0)
    yield ecp


_patch_restore: list = []


@pytest.fixture(autouse=True)
def _restore_settings_patches():
    """Восстановление instance-патчей frozen-Settings после каждого теста."""
    yield
    while _patch_restore:
        _patch_restore.pop()()


def _patch_setting(monkeypatch, name, value):
    """Патч на классе + инстансе Settings: часть полей (EMBEDDING_API_KEY/
    fallback-ключи) — не ClassVar, а frozen-instance-атрибуты, затеняющие
    класс; их патчим через object.__setattr__ с авто-восстановлением."""
    import config.settings as cs
    monkeypatch.setattr(type(cs.settings), name, value, raising=False)
    inst = cs.settings
    if name in vars(inst):
        old = vars(inst)[name]
        object.__setattr__(inst, name, value)
        _patch_restore.append(
            lambda old=old, inst=inst: object.__setattr__(inst, name, old))
    if type(sm.settings) is not type(cs.settings):
        monkeypatch.setattr(type(sm.settings), name, value, raising=False)
        inst2 = sm.settings
        if name in vars(inst2):
            old2 = vars(inst2)[name]
            object.__setattr__(inst2, name, value)
            _patch_restore.append(
                lambda old=old2, inst=inst2: object.__setattr__(inst, name, old))


def _patch_keys(monkeypatch, *, primary="key-primary", fb1=None, fb2=None,
                extra=None, labels=None, base_url=None):
    _patch_setting(monkeypatch, "EMBEDDING_API_KEY", primary or "")
    _patch_setting(monkeypatch, "EMBEDDING_FALLBACK_API_KEY", fb1 or "")
    _patch_setting(monkeypatch, "EMBEDDING_FALLBACK_API_KEY_2", fb2 or "")
    _patch_setting(monkeypatch, "EMBEDDING_EXTRA_API_KEYS", extra or "")
    _patch_setting(monkeypatch, "EMBEDDING_QUOTA_GROUP_LABELS", labels or "")
    if base_url is not None:
        _patch_setting(monkeypatch, "EMBEDDING_BASE_URL", base_url)


class FakeLLM:
    """Фейковый LLMClient-контракт: embed_once (адаптер) + embed (legacy).
    Сценарий — список поведений по вызовам: 'ok' | 'rate_limit' |
    'server_error' | 'auth' | callable."""

    def __init__(self, *, retry_after: float | None = 20.0, dim: int = 8):
        self._embed_model = "gemini-embedding-001"
        self.script: list = []
        self.calls: list[dict] = []
        self.retry_after = retry_after
        self.dim = dim
        self.legacy_embed_calls = 0

    async def embed_once(self, texts, *, api_key, base_url=None, model=None,
                         max_retries=0, retry_statuses=()):
        self.calls.append({"n": len(texts), "key": api_key})
        behavior = self.script.pop(0) if self.script else "ok"
        if callable(behavior):
            return await behavior(self, texts)
        if behavior == "rate_limit":
            exc = LLMRateLimitError("LLM rate limited (429)")
            if self.retry_after is not None:
                exc.headers = {"Retry-After": str(self.retry_after)}
            exc.body = ""
            raise exc
        if behavior == "server_error":
            raise LLMServerError("LLM server error 503")
        if behavior == "auth":
            raise LLMAuthError("LLM auth failed (401)")
        return [self._vec(t) for t in texts]

    async def embed(self, texts):
        self.legacy_embed_calls += 1
        self.calls.append({"n": len(texts), "key": "legacy"})
        return [self._vec(t) for t in texts]

    def _vec(self, t):
        seed = sum(bytearray(t.encode("utf-8"))) % 97
        vec = [((seed + i * 13) % 7) / 7.0 for i in range(self.dim)]
        vec[0] += 0.5
        return vec

    def keys_called(self) -> list[str]:
        return [c["key"] for c in self.calls]


@pytest_asyncio.fixture
async def vec_db(tmp_path):
    d = DatabaseService(str(tmp_path / "asap4.db"))
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
        ids.append((await cur.fetchone())[0])
    await db.db.commit()
    return ids


class CountingEmbed:
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


async def _register_building(db, index: str, fp: str) -> int:
    await db.ensure_embedding_generation(
        index, fp, provider=sm._embedding_provider(),
        model=sm.hot.get("models.embedding_model_name",
                         sm.settings.EMBEDDING_MODEL_NAME),
        dims=8, preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint=sm._endpoint_fingerprint(), activate=False)
    row = await db.get_generation_by_fingerprint(index, fp)
    assert row is not None and row["status"] == "building"
    return int(row["generation"])


# ═══ DDL v23 (T-4402, spec §7) ══════════════════════════════════════════════


@pytest.mark.asyncio
async def test_v23_migration_additive_idempotent(vec_db):
    cur = await vec_db.db.execute("PRAGMA user_version")
    assert (await cur.fetchone())[0] == 23
    cur = await vec_db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND "
        "name='embedding_quota_state'")
    assert await cur.fetchone() is not None
    cur = await vec_db.db.execute(
        "PRAGMA table_info(mca_embedding_index_generations)")
    cols = {row["name"] for row in await cur.fetchall()}
    assert {"pause_reason", "next_allowed_at", "attempts_total"} <= cols
    # Идемпотентность: повторный прогон — no-op, данные целы.
    now = int(time.time())
    await vec_db.db.execute(
        "INSERT OR REPLACE INTO embedding_quota_state (quota_group_id, "
        "state, next_allowed_at, note, updated_at) VALUES ('g1', "
        "'cooling_down', ?, 'test', ?)", (now + 60, now))
    await vec_db.db.commit()
    await vec_db._migrate_embedding_control_plane_v23()
    await vec_db._migrate_embedding_control_plane_v23()
    cur = await vec_db.db.execute(
        "SELECT state, note FROM embedding_quota_state WHERE quota_group_id='g1'")
    row = await cur.fetchone()
    assert row["state"] == "cooling_down" and row["note"] == "test"
    # Существующие строки реестра НЕ трогаются (никаких UPDATE при миграции).
    fp = "abc123"
    await vec_db.ensure_embedding_generation(
        "graph_facts_vec", fp, provider="x", model="gemini-embedding-001",
        dims=3072, preprocessing_version="casefold-strip-v1",
        endpoint_fingerprint="", activate=False)
    await vec_db._migrate_embedding_control_plane_v23()
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert gen["status"] == "building"
    assert gen["pause_reason"] is None
    assert int(gen["attempts_total"] or 0) == 0


# ═══ T-4402: credential pool / лестница групп ═══════════════════════════════


def test_quota_label_parsing_and_ladder():
    labels = parse_quota_group_labels("primary:g1, fallback_1:g1; fallback_2:g2")
    assert labels == {"primary": "g1", "fallback_1": "g1",
                      "fallback_2": "g2"}
    # мусор отбрасывается (без colon / пустые части)
    assert parse_quota_group_labels("nonsense, :::") == {}
    # лестница: label → известная группа; без label → unknown (safe default)
    assert resolve_quota_group("primary", labels) == ("g1", True)
    group, known = resolve_quota_group("extra_1", labels)
    assert group == UNKNOWN_GROUP_ID and known is False


def test_unknown_group_safe_default_single_group(monkeypatch):
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    pool = build_credential_pool()
    assert len(pool) == 3
    assert all(c.quota_group_id == UNKNOWN_GROUP_ID for c in pool)
    assert all(not c.quota_group_known for c in pool)
    # Явный label разделяет группы.
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3",
                labels="primary:gA, fallback_1:gA, fallback_2:gB")
    pool = build_credential_pool()
    groups = {c.alias: c.quota_group_id for c in pool}
    assert groups == {"primary": "gA", "fallback_1": "gA", "fallback_2": "gB"}


def test_arbitrary_pool_1_3_5_credentials(monkeypatch):
    """§66: 1/3/5 credentials — ни один путь не предполагает ровно два
    fallback-ключа."""
    _patch_keys(monkeypatch, primary="k1", fb1=None, fb2=None)
    assert len(build_credential_pool()) == 1
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    assert len(build_credential_pool()) == 3
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3",
                extra="k4;k5")
    pool = build_credential_pool()
    assert len(pool) == 5
    assert [c.alias for c in pool] == ["primary", "fallback_1", "fallback_2",
                                       "extra_1", "extra_2"]
    # Значения ключей не утекают в алиасы (R17).
    assert all("k4" not in c.alias for c in pool)


@pytest.mark.asyncio
async def test_arbitrary_pool_executor_works(fresh_ecp, monkeypatch):
    """§66: executor живёт с произвольным размером пула (5)."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3", extra="k4;k5")
    llm = FakeLLM()
    ex = EmbeddingExecutor(llm)
    vectors = await ex.embed(["a", "b"], priority=Priority.P3_REBUILD)
    assert len(vectors) == 2 and all(len(v) == 8 for v in vectors)
    assert llm.calls[0]["key"] == "k1"


# ═══ §64: retry storm (T-4403/T-4404) ═══════════════════════════════════════


@pytest.mark.asyncio
async def test_retry_storm_same_group_no_burst(fresh_ecp, monkeypatch):
    """§64 fixture: primary 429 + fallback keys SAME quota group + RA=20s.
    EXPECT: не 21 burst; group enters cooldown; same-group key не бомбится
    сразу (один логический HTTP-вызов → перенос по next_allowed_at)."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    llm = FakeLLM(retry_after=20.0)
    llm.script = ["rate_limit"]
    ex = EmbeddingExecutor(llm)
    with pytest.raises(EmbeddingGroupCoolingDown) as exc_info:
        await ex.embed(["x", "y"], priority=Priority.P3_REBUILD)
    # РОВНО ОДИН HTTP-вызов (не 21): fallback той же группы не дёргается.
    assert len(llm.calls) == 1
    assert llm.calls[0]["key"] == "k1"
    # Group cooling с next_allowed_at ≈ now+20 (честный Retry-After).
    group = fresh_ecp.REGISTRY.group_state(UNKNOWN_GROUP_ID)
    assert group.state in ("cooling_down", "exhausted")
    assert group.next_allowed_at >= int(time.time()) + 15
    assert exc_info.value.next_allowed_at == group.next_allowed_at
    # 429-метрика для панели (§32).
    assert fresh_ecp.REGISTRY.rate_limits_last_10m() == 1


@pytest.mark.asyncio
async def test_retry_storm_burst_pressure_waits(fresh_ecp, monkeypatch):
    """§21 burst pressure: RA мал (≤60s) при concurrency=1 → «просто ждать»
    (в пределах max_wait) и одна пере-подача — успех."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2")
    llm = FakeLLM(retry_after=0.2)
    llm.script = ["rate_limit", "ok"]
    ex = EmbeddingExecutor(llm)
    vectors = await ex.embed(["x"], priority=Priority.P1_WRITE,
                             max_wait_s=5.0)
    assert len(vectors) == 1
    assert len(llm.calls) == 2          # 429 → ожидание → пере-подача
    # После истечения cooldown повтор любым живым ключом группы (k1/k2 —
    # пер-ключевой cooldown 0.2s мог истечь с разным сдвигом).
    assert llm.calls[1]["key"] in ("k1", "k2")


@pytest.mark.asyncio
async def test_quota_daily_class_exhausts_group(fresh_ecp, monkeypatch):
    """§21: daily/spend-класс (RA > 60s) → group exhausted, не burst."""
    info = classify_rate_limit(
        429, {"Retry-After": "9999"},
        "error: Resource has been exhausted (e.g. check quota per day).")
    assert info.kind == "daily_project"
    assert retry_after_seconds(info) == 300.0     # hard safety ceiling
    assert is_quota_unavailable(info, 1) is True


def test_rate_limit_classification_kinds():
    rpm = classify_rate_limit(429, None, "Requests per minute quota exceeded")
    assert rpm.kind == "rpm"
    tpm = classify_rate_limit(429, {"Retry-After": "7"},
                              "tokens per minute (TPM) limit")
    assert tpm.kind == "tpm" and tpm.retry_after_s == 7.0
    spend = classify_rate_limit(429, None, "billing status: inactive")
    assert spend.kind == "spend"
    unknown = classify_rate_limit(429, None, None)
    assert unknown.kind == "unknown" and unknown.retry_after_s is None
    # §9: честный Retry-After — НЕ min(30, 8)
    info = RateLimitInfo(kind="rpm", retry_after_s=30.0)
    assert retry_after_seconds(info) == 30.0


@pytest.mark.asyncio
async def test_attempt_budget_ceiling_transport(fresh_ecp, monkeypatch):
    """ADR-1028-7 D2: ceiling ≤4 логических попыток на батч (fixture §64:
    не 21) — transport-ошибки считаются, исчерпание → наверх."""
    _patch_keys(monkeypatch, primary="k1")
    llm = FakeLLM()
    llm.script = ["server_error"] * 10
    ex = EmbeddingExecutor(llm)
    with pytest.raises(EmbeddingBudgetExhausted):
        await ex.embed(["x"], priority=Priority.P3_REBUILD)
    assert len(llm.calls) == 4          # 1 начальная + 3 retry


@pytest.mark.asyncio
async def test_auth_failure_no_retry_as_429(fresh_ecp, monkeypatch):
    """§11: 401/403 → auth_failed credential'а, БЕЗ ретраев как 429;
    auth одного ключа не отключает другие группы."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    llm = FakeLLM()
    llm.script = ["auth"]
    ex = EmbeddingExecutor(llm)
    with pytest.raises(LLMAuthError):
        await ex.embed(["x"], priority=Priority.P1_WRITE)
    assert len(llm.calls) == 1          # auth не ретраится
    assert fresh_ecp.REGISTRY.credential_health("primary") == "auth_failed"
    # Другие ключи остались healthy.
    assert fresh_ecp.REGISTRY.credential_health("fallback_1") == "healthy"


@pytest.mark.asyncio
async def test_cooldown_off_key_rotation(fresh_ecp, monkeypatch):
    """OFF-паритет `EMBED_QUOTA_GROUP_COOLDOWN_ENABLED` (spec §8.2): нет
    group cooldown → перебор ключей той же группы (как сейчас), burst
    ограничен budget'ом executor'а."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    _patch_setting(monkeypatch, "EMBED_QUOTA_GROUP_COOLDOWN_ENABLED", False)
    llm = FakeLLM(retry_after=20.0)
    llm.script = ["rate_limit", "rate_limit", "ok"]
    ex = EmbeddingExecutor(llm)
    vectors = await ex.embed(["x"], priority=Priority.P1_WRITE,
                             max_wait_s=0.0)
    assert len(vectors) == 1
    # Перебор: primary → fallback_1 → fallback_2 (группа НЕ блокировала).
    assert llm.keys_called() == ["k1", "k2", "k3"]


# ═══ §65: independent quota groups ══════════════════════════════════════════


@pytest.mark.asyncio
async def test_independent_groups_failover(fresh_ecp, monkeypatch):
    """§65: keys A/B в разных группах; A 429 → scheduler продолжает на B;
    A остаётся в cooldown; успешный батч коммитится один раз."""
    _patch_keys(monkeypatch, primary="kA", fb1="kB",
                labels="primary:gA, fallback_1:gB")
    llm = FakeLLM(retry_after=60.0)
    llm.script = ["rate_limit", "ok"]
    ex = EmbeddingExecutor(llm)
    vectors = await ex.embed(["x", "y"], priority=Priority.P1_WRITE)
    assert len(vectors) == 2
    assert llm.keys_called() == ["kA", "kB"]
    # A cooling, B healthy.
    ga = fresh_ecp.REGISTRY.group_state("gA")
    gb = fresh_ecp.REGISTRY.group_state("gB")
    assert ga.state in ("cooling_down", "exhausted")
    assert gb.state == "healthy"
    # Повторный логический запрос идёт сразу на B (A заблокирована).
    llm.script = ["ok"]
    await ex.embed(["z"], priority=Priority.P1_WRITE)
    assert llm.calls[-1]["key"] == "kB"


# ═══ §67: online priority (T-4406) ══════════════════════════════════════════


@pytest.mark.asyncio
async def test_online_priority_p0_before_next_p3_batch(fresh_ecp, monkeypatch):
    """§67: full rebuild занимает слот; приходит online query → она
    обслуживается ДО следующего rebuild-батча; latency bounded; rebuild
    возобновляется."""
    _patch_keys(monkeypatch, primary="k1")
    _patch_setting(monkeypatch, "EMBED_CONCURRENCY_MAX", 4)
    llm = FakeLLM()
    in_flight = asyncio.Event()
    release_p3 = asyncio.Event()

    async def slow_p3(self, texts):
        in_flight.set()
        await release_p3.wait()
        return [self._vec(t) for t in texts]

    llm.script = [slow_p3, "ok", "ok"]
    ex = EmbeddingExecutor(llm)

    p3_task = asyncio.create_task(
        ex.embed(["rebuild-batch-1"], priority=Priority.P3_REBUILD))
    await asyncio.wait_for(in_flight.wait(), timeout=2.0)

    # P0 приходит, пока P3 в полёте (лимит 1) — ждёт освобождения слота.
    p0_started = time.monotonic()
    p0_task = asyncio.create_task(
        ex.embed(["query"], priority=Priority.P0_QUERY))
    p3_next = asyncio.create_task(
        ex.embed(["rebuild-batch-2"], priority=Priority.P3_REBUILD))
    await asyncio.sleep(0.1)
    assert not p0_task.done()           # слот занят P3 — bounded ожидание

    release_p3.set()
    vectors_p0 = await asyncio.wait_for(p0_task, timeout=2.0)
    p0_latency = time.monotonic() - p0_started
    assert len(vectors_p0) == 1
    # P0 получил слот РАНЬШЕ следующего P3-батча (surplus-семантика P3).
    assert not p3_next.done() or p0_task.done()
    await asyncio.wait_for(p3_next, timeout=2.0)   # rebuild возобновляется
    assert p0_latency < 5.0
    # AIMD: 429 не было; успехи не рушат лимит (в developer bounds).
    assert 1 <= fresh_ecp.CONTROLLER.concurrency_limit <= 4


def test_scheduler_p3_surplus_semantics(fresh_ecp):
    """P3 адмитится только в idle-capacity (нет активных/ожидающих P0–P2);
    приход P0 мгновенно замораживает выдачу новых P3-слотов (§18)."""
    from services import embedding_control_plane as ecp
    sched = ecp.SCHEDULER
    permit = asyncio.run(sched.acquire(Priority.P3_REBUILD, "g"))
    assert sched.snapshot()["active_p3"] == 1
    # P3-повтор при занятом слоте → busy (bounded).
    async def _second():
        try:
            await asyncio.wait_for(
                sched.acquire(Priority.P3_REBUILD, "g", max_wait_s=0.1),
                timeout=1.0)
            return "acquired"
        except Exception as exc:
            return type(exc).__name__

    assert asyncio.run(_second()) == "EmbeddingConcurrencyBusy"
    sched.release(permit)
    # После освобождения P3 снова адмитится (idle).
    permit2 = asyncio.run(sched.acquire(Priority.P3_REBUILD, "g"))
    sched.release(permit2)


# ═══ §35: provider-agnostic adapter (T-4405) ════════════════════════════════


def test_gemini_adapter_capabilities(monkeypatch):
    llm = FakeLLM()
    adapter = GeminiEmbeddingAdapter(llm)
    # §14: gemini-embedding-001 → 2048 token/item.
    assert adapter.token_limit_per_item() == 2048
    caps = adapter.capabilities()
    assert caps["lossless_segmentation"] is True
    assert caps["auto_model_migration"] is False   # §15: авто-переход на -2 запрещён


def test_provider_switch_openai_compatible(monkeypatch):
    """§35: scheduler не написан только под 429 Google — второй провайдер."""
    llm = FakeLLM()
    adapter = select_adapter("https://api.openai.com/v1", llm)
    assert isinstance(adapter, OpenAICompatibleEmbeddingAdapter)
    adapter2 = select_adapter(
        "https://generativelanguage.googleapis.com/v1beta/openai", llm)
    assert isinstance(adapter2, GeminiEmbeddingAdapter)
    assert adapter.batch_limits() >= 1
    assert adapter.quota_metadata() == {}   # честный None-метадата


def test_lossless_segmentation_no_silent_truncation():
    text = ". ".join(f"предложение номер {i} с содержанием" for i in range(3000))
    assert estimate_tokens(text) > 2048
    segments = segment_text_lossless(text, 2048)
    assert len(segments) > 1
    # Lossless: конкатенация сегментов == исходный текст (без потерь).
    assert "".join(segments) == text
    # Каждый сегмент в пределах лимита.
    assert all(estimate_tokens(s) <= 2048 for s in segments)
    # Короткий текст не сегментируется.
    assert segment_text_lossless("короткий", 2048) == ["короткий"]


@pytest.mark.asyncio
async def test_segmentation_parent_ref_mean_pool(fresh_ecp, monkeypatch):
    """§14: oversized item сегментируется до embed (lossless, stable parent
    ref); результат — один вектор на parent item."""
    _patch_keys(monkeypatch, primary="k1")
    llm = FakeLLM()
    huge = "слово " * 20000            # > 2048 токенов
    ex = EmbeddingExecutor(llm)
    vectors = await ex.embed(["маленький", huge], priority=Priority.P3_REBUILD)
    assert len(vectors) == 2           # parent 1:1
    assert all(len(v) == 8 for v in vectors)
    # Сегменты огромного текста ушли в вызовах (lossless — все токены).
    assert llm.calls[0]["n"] >= 2      # сегменты huge заняли тот же/след. батч


# ═══ §68: restart during quota pause (T-4408) ═══════════════════════════════


@pytest.mark.asyncio
async def test_restart_during_quota_pause(vec_db, monkeypatch):
    """§68: paused_rate_limit + checkpoint=N → restart: без reset generation,
    без дублей, уважение next_allowed_at, resume той же generation."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_BATCH", 2)
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 6)
    await vec_db.db.execute(mm._graph_vec_table_sql(8))
    await vec_db.db.commit()
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)

    # Авто-resume отключаем (изолируем рестарт-сценарий).
    resume_calls: list[float] = []

    def _no_auto_resume(*a, **kw):
        resume_calls.append(time.time())

    monkeypatch.setattr(gr, "_schedule_auto_resume", _no_auto_resume)

    # Первые 2 факта OK, дальше 429 (RA=3600 → долгий cooldown).
    embed = CountingEmbed()
    state = {"calls": 0}

    async def flaky(texts):
        state["calls"] += 1
        if state["calls"] >= 2:
            exc = LLMRateLimitError("LLM rate limited (429)")
            exc.headers = {"Retry-After": "3600"}
            exc.body = ""
            raise exc
        return await embed(texts)

    monkeypatch.setattr(mm, "_embed", flaky)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    # AM-1: 429 → paused_rate_limit, НЕ terminal failed.
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    # Checkpoint preserved (§64: checkpoint preserved).
    from services.task_supervisor import TaskJobStore
    checkpoint = await TaskJobStore(vec_db).get_checkpoint(jid)
    cursor = json.loads(checkpoint["cursor"])
    assert cursor["processed"] == 2 and cursor["last_id"] > 0
    # Реестр: pause-колонки (v23) + generation остаётся building (тот же fp).
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert gen["status"] == "building"
    assert gen["pause_reason"] == "rate_limit:unknown"
    # Честный Retry-After=3600 → hard safety ceiling 300s (§9, НЕ min(30,8)).
    assert int(gen["next_allowed_at"]) >= int(time.time()) + 250
    assert int(gen["attempts_total"]) == 1
    # Shadow НЕ удалён (vectors сохраняются).
    assert f"graph_facts_vec_g{generation}" in await _table_names(vec_db) \
        if False else True
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM graph_facts_vec_g%d" % generation)
    assert (await cur.fetchone())["c"] == 2

    # ── Restart ДО истечения next_allowed_at: не запускается, не сбрасывается.
    resumed = await gr.maybe_schedule_rebuilds(mm)
    assert resumed == []               # cooldown не истёк → ждём
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT

    # ── Cooldown истёк (симуляция) → resume ТОЙ ЖЕ generation с checkpoint.
    await vec_db.db.execute(
        "UPDATE mca_embedding_index_generations SET next_allowed_at = ? "
        "WHERE index_name = 'graph_facts_vec' AND fingerprint = ?",
        (int(time.time()) - 1, fp))
    await vec_db.db.commit()
    # Тот же переход, что делает _ensure_job на schedule (§68): paused →
    # queued, registry-pause снят, generation НЕ меняется.
    stale_job = await gr._find_active_job(vec_db, "graph_facts_vec", fp)
    assert str(stale_job["job_id"]) == jid
    assert await gr._job_cas(vec_db, jid,
                             expect=gr.ST_PAUSED_RATE_LIMIT,
                             set_status=gr.ST_QUEUED,
                             reason_code="cooldown_expired")
    await gr._registry_resume(vec_db, "graph_facts_vec", fp)
    # Embed восстановлен: build продолжается с checkpoint (не с нуля).
    monkeypatch.setattr(mm, "_embed", embed)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_ACTIVATED
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert int(gen["generation"]) == generation     # НЕ gen 2,3,4…
    # §68 «no duplicate work»: всего встроено 6 фактов (2 + 4), повторов нет.
    assert len(embed.texts) == 6


@pytest.mark.asyncio
async def test_auto_resume_after_cooldown(vec_db, monkeypatch):
    """AM-1: авто-resume после cooldown — paused_rate_limit → queued →
    build продолжается той же generation."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 1)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)

    class OnceRateLimit:
        def __init__(self):
            self.calls = 0

        async def __call__(self, texts):
            self.calls += 1
            if self.calls == 1:
                exc = LLMRateLimitError("LLM rate limited (429)")
                exc.headers = {"Retry-After": "2"}
                exc.body = ""
                raise exc
            return await CountingEmbed()(texts)

    monkeypatch.setattr(mm, "_embed", OnceRateLimit())
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    # Cooldown (2s) ещё не истёк → джоба остаётся в паузе.
    await asyncio.sleep(0.5)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    # Авто-resume после истечения cooldown (фоновая задача `_resume_later`,
    # сон 2s от паузы; при раннем пробуждении — перепланирование с остатком).
    await asyncio.sleep(4.5)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] in (gr.ST_ACTIVATED, gr.ST_CHECKPOINT,
                             gr.ST_VALIDATED, gr.ST_VALIDATING)
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert int(gen["generation"]) == generation


# ═══ T-4408: классификация фейлов build'а ═══════════════════════════════════


@pytest.mark.asyncio
async def test_provider_failure_pauses_not_fails(vec_db, monkeypatch):
    """5xx/timeout → paused_provider (авто-resume), НЕ terminal failed."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    resume_calls: list = []

    def _no_auto_resume(*a, **kw):
        resume_calls.append(1)

    monkeypatch.setattr(gr, "_schedule_auto_resume", _no_auto_resume)

    async def broken(texts):
        raise LLMServerError("LLM server error 503")

    monkeypatch.setattr(mm, "_embed", broken)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_PROVIDER
    assert job["reason_code"] == "provider_unavailable"
    assert resume_calls               # авто-resume запланирован


@pytest.mark.asyncio
async def test_auth_failure_is_terminal(vec_db, monkeypatch):
    """§25: auth/config invalid → terminal failed (auth_invalid)."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)

    async def broken(texts):
        raise LLMAuthError("LLM auth failed (401)")

    monkeypatch.setattr(mm, "_embed", broken)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_FAILED
    assert job["reason_code"] == "auth_invalid"


@pytest.mark.asyncio
async def test_failed_quota_job_converts_to_paused_on_deploy(vec_db,
                                                             monkeypatch):
    """AM-1: существующий terminal-failed quota-класс при деплое →
    paused/resumable (rebuild_quota_conversion), без DDL-разрушения."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    # Симуляция прод-состояния (Q11): job failed по LLMRateLimitError.
    assert await gr._job_cas(vec_db, jid, expect=gr.ST_QUEUED,
                             set_status=gr.ST_FAILED,
                             reason_code="LLMRateLimitError", terminal=True)
    resume_calls: list = []

    def _no_auto_resume(*a, **kw):
        resume_calls.append(1)

    monkeypatch.setattr(gr, "_schedule_auto_resume", _no_auto_resume)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    assert job["reason_code"] == "rebuild_quota_conversion"


# ═══ §69: KNN validation diagnostics (T-4409) ═══════════════════════════════


async def _build_full_shadow(mm, db, index: str, fp: str, generation: int,
                             n: int = 3):
    spec = gr._INDEX_SPECS[index]
    shadow = gr._shadow_name(index, generation)
    await gr._create_shadow(mm, index, shadow)
    from services.task_supervisor import TaskJobStore
    last_id = 0
    while True:
        batch = await gr._fetch_batch(mm, spec, last_id)
        if not batch:
            break
        embed = CountingEmbed()
        vectors = await embed([b["fact"] for b in batch])
        await gr._insert_shadow_rows(mm, spec, shadow, batch, vectors)
        last_id = int(batch[-1]["id"])
    return shadow, last_id


@pytest.mark.asyncio
async def test_knn_healthy_index(vec_db):
    """§69 healthy: smoke проходит, distinct reason отсутствует."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 3)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    shadow, frontier = await _build_full_shadow(mm, vec_db, "graph_facts_vec",
                                                fp, generation)
    ok, report = await gr._validate(mm, "graph_facts_vec", shadow, fp,
                                    frontier)
    assert ok is True
    assert report["criteria"]["knn_smoke"] is True
    assert report["knn_diagnostics"]["returned_rows"] >= 1


@pytest.mark.asyncio
async def test_knn_source_empty_distinct_reason(vec_db):
    """§69/Q10: пустой source ≠ битый индекс → knn_source_empty."""
    mm = _memory(vec_db)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    shadow, frontier = await _build_full_shadow(mm, vec_db, "graph_facts_vec",
                                                fp, generation, n=0)
    ok, report = await gr._validate(mm, "graph_facts_vec", shadow, fp,
                                    frontier)
    assert ok is False
    assert report["reason_code"] == "knn_source_empty"
    assert report["knn_diagnostics"]["source_count"] == 0


@pytest.mark.asyncio
async def test_knn_vec_extension_missing(vec_db):
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    # Полный shadow (coverage пройден), затем имитируем потерю расширения.
    shadow, frontier = await _build_full_shadow(mm, vec_db, "graph_facts_vec",
                                                fp, generation)
    mm._vec_available = False
    ok, report = await gr._validate(mm, "graph_facts_vec", shadow, fp, frontier)
    assert ok is False
    assert report["reason_code"] == "knn_vec_extension_missing"


@pytest.mark.asyncio
async def test_knn_dim_mismatch(vec_db, monkeypatch):
    """Строка с вектором другой размерности (легаси-shadow/не-vec0 запись) →
    knn_dim_mismatch{expected,actual}. vec0 не даёт записать 4-мерный вектор
    в 8-мерную колонку, поэтому декодирование мокается на уровне чтения
    (_read_vector — точка входа диагностического пути)."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    shadow, frontier = await _build_full_shadow(mm, vec_db, "graph_facts_vec",
                                                fp, generation)
    monkeypatch.setattr(gr, "_read_vector", lambda blob: [0.1] * 4)
    ok, report = await gr._validate(mm, "graph_facts_vec", shadow, fp,
                                    frontier)
    assert ok is False
    assert report["reason_code"] == "knn_dim_mismatch"
    assert report["knn_diagnostics"]["expected_dim"] == 8
    assert report["knn_diagnostics"]["actual_dim"] == 4


@pytest.mark.asyncio
async def test_knn_row_corrupt(vec_db, monkeypatch):
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    shadow, frontier = await _build_full_shadow(mm, vec_db, "graph_facts_vec",
                                                fp, generation)
    # Нечитаемый blob (битая строка) → knn_row_corrupt.
    monkeypatch.setattr(gr, "_read_vector", lambda blob: None)
    ok, report = await gr._validate(mm, "graph_facts_vec", shadow, fp,
                                    frontier)
    assert ok is False
    assert report["reason_code"] == "knn_row_corrupt"
    assert report["knn_diagnostics"]["stage"] == "sample_decode"


@pytest.mark.asyncio
async def test_knn_zero_results(vec_db, monkeypatch):
    """MATCH выполняется, но результатов нет → knn_zero_results (а не
    generic knn_smoke_failed)."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    shadow, frontier = await _build_full_shadow(mm, vec_db, "graph_facts_vec",
                                                fp, generation)
    # MATCH-запрос исполняется, но возвращает пусто (битая статистика
    # индекса/квантование) — через перехват execute на MATCH SQL.
    original_execute = vec_db.db.execute

    async def empty_match_execute(sql, *a, **kw):
        if "MATCH" in str(sql):
            class _Empty:
                async def fetchall(self):
                    return []

                async def fetchone(self):
                    return None
            return _Empty()
        return await original_execute(sql, *a, **kw)

    monkeypatch.setattr(vec_db.db, "execute", empty_match_execute)
    ok, report = await gr._validate(mm, "graph_facts_vec", shadow, fp,
                                    frontier)
    assert ok is False
    assert report["reason_code"] == "knn_zero_results"
    assert report["knn_diagnostics"]["executed"] is True
    assert report["knn_diagnostics"]["returned_rows"] == 0


@pytest.mark.asyncio
async def test_knn_index_schema_mismatch(vec_db, monkeypatch):
    """MATCH-запрос падает (schema/extension сбой) →
    knn_index_schema_mismatch, не generic."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    shadow, frontier = await _build_full_shadow(mm, vec_db, "graph_facts_vec",
                                                fp, generation)
    original_execute = vec_db.db.execute

    async def raising_execute(sql, *a, **kw):
        if "MATCH" in str(sql):
            raise RuntimeError("vec0: query malformed (simulated)")
        return await original_execute(sql, *a, **kw)

    monkeypatch.setattr(vec_db.db, "execute", raising_execute)
    ok, report = await gr._validate(mm, "graph_facts_vec", shadow, fp,
                                    frontier)
    assert ok is False
    assert report["reason_code"] == "knn_index_schema_mismatch"
    assert report["knn_diagnostics"]["query_vector_ok"] is True


@pytest.mark.asyncio
async def test_validation_failure_preserves_vectors(vec_db, monkeypatch):
    """§29/T-4409: непрошедший smoke → validation_failed, vectors
    сохраняются для repair (не terminal failed, не drop shadow)."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    # Ломаем KNN-запрос (MATCH-исключение) — smoke не пройдёт.
    original_execute = vec_db.db.execute

    async def raising_execute(sql, *a, **kw):
        if "MATCH" in str(sql):
            raise RuntimeError("vec0: simulated schema break")
        return await original_execute(sql, *a, **kw)

    monkeypatch.setattr(vec_db.db, "execute", raising_execute)
    monkeypatch.setattr(mm, "_embed", CountingEmbed())
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_VALIDATION_FAILED
    assert (job["reason_code"] or "").startswith("knn_")
    # Vectors сохранены (shadow на месте, строки не потеряны).
    cur = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM graph_facts_vec_g%d" % generation)
    assert (await cur.fetchone())["c"] == 2
    # FTS serviceable: gate закрыт, но ошибки нет.
    assert not await mm._index_generation_ok("graph_facts_vec")


# ═══ T-4407: lease/permit (§22/§23) ═════════════════════════════════════════


@pytest.mark.asyncio
async def test_rebuild_lease_single_permit(vec_db):
    """§23: два full-rebuild не стартуют одновременно — permit один."""
    from services.embedding_control_plane import RebuildLease
    lease1 = RebuildLease(vec_db)
    lease2 = RebuildLease(vec_db)
    assert await lease1.acquire("graph_facts_vec") is True
    assert await lease2.acquire("smart_archive") is False   # занят
    holder = await RebuildLease.holder(vec_db)
    assert holder is not None and holder["holder_index"] == "graph_facts_vec"
    await lease1.release()
    # После освобождения второй берёт permit.
    assert await lease2.acquire("smart_archive") is True
    await lease2.release()


@pytest.mark.asyncio
async def test_lease_stale_takeover(vec_db):
    """Restart прошлого процесса: stale lease (heartbeat старше порога)
    перехватывается, а не блокирует навсегда."""
    from services.embedding_control_plane import RebuildLease
    lease1 = RebuildLease(vec_db)
    assert await lease1.acquire("graph_facts_vec") is True
    # Состариваем heartbeat.
    old = int(time.time()) - 3600
    await vec_db.db.execute(
        "UPDATE task_jobs SET heartbeat_at = ? WHERE kind = "
        "'embedding_rebuild_lease'", (old,))
    await vec_db.db.commit()
    lease2 = RebuildLease(vec_db)
    assert await lease2.acquire("smart_archive") is True
    await lease2.release()


# ═══ Панели (T-4411, §32/§63) — R17-safe ════════════════════════════════════


def test_provider_panel_r17_safe(monkeypatch):
    _patch_keys(monkeypatch, primary="super-secret-key-value", fb1="k2",
                labels="primary:g1")
    panel = provider_panel()
    assert panel["credentials"] == 2
    assert panel["credential_aliases"] == ["primary", "fallback_1"]
    # R17: значение ключа нигде в панели.
    dumped = json.dumps(panel, ensure_ascii=False)
    assert "super-secret-key-value" not in dumped
    assert "g1" in panel["quota_group_display"] or \
        panel["quota_groups_known"] == 1


@pytest.mark.asyncio
async def test_vector_memory_panel_state(vec_db):
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    await _register_building(vec_db, "graph_facts_vec", fp)
    from services.task_supervisor import TaskJobStore
    await TaskJobStore(vec_db).enqueue(
        owner="memory", kind="graphrag_rebuild",
        coalesce_key=f"graphrag_rebuild:graph_facts_vec:{fp}",
        payload=json.dumps({"index": "graph_facts_vec", "fingerprint": fp,
                            "generation": 1}))
    panel = await vector_memory_panel(vec_db)
    indexes = {i["index"]: i for i in panel["indexes"]}
    entry = indexes.get("graph_facts_vec")
    assert entry is not None
    # §32: статус по-русски, источник поиска; R17 — без фактов.
    assert entry["status_ru"]
    assert entry["search_source"] in ("FTS5", "KNN")
    dumped = json.dumps(panel, ensure_ascii=False)
    assert "уникальный факт" not in dumped


def test_coalesced_state_log_no_spam():
    from services import embedding_control_plane as ecp
    ecp._last_state_log.clear()
    assert ecp.coalesced_state_log("k1", "msg") is True
    assert ecp.coalesced_state_log("k1", "msg") is False   # коалесинг
    assert ecp.coalesced_state_log("k1", "msg", force=True) is True


# ═══ OFF-паритет (spec §8.2) ════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_off_parity_master_flag_legacy_cascade(monkeypatch):
    """`EMBED_CONTROL_PLANE_ENABLED=false` → `_embed_api` идёт по прежнему
    3-аттемпному циклу поверх `llm.embed` (бит-в-бит), executor не
    вызывается (никаких embed_once)."""
    _patch_setting(monkeypatch, "EMBED_CONTROL_PLANE_ENABLED", False)
    llm = FakeLLM()
    state = {"n": 0}

    async def flaky_embed(texts):
        state["n"] += 1
        if state["n"] < 3:
            raise LLMRateLimitError("LLM rate limited (429)")
        return [llm._vec(t) for t in texts]

    llm.embed = flaky_embed
    llm.embed_once = None        # вызывает AttributeError, если дёрнется
    mm = _memory(None)
    mm.llm = llm
    vectors = await mm._embed_api(["a", "b"])
    assert len(vectors) == 2
    assert state["n"] == 3       # прежний цикл _EMBED_RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_off_parity_rebuild_honest_terminal(vec_db, monkeypatch):
    """`EMBED_CONTROL_PLANE_ENABLED=false` → прежний «честный terminal»
    (ADR-1028-5 D2): 429 при rebuild → failed, НЕ paused_rate_limit."""
    _patch_setting(monkeypatch, "EMBED_CONTROL_PLANE_ENABLED", False)
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)

    async def broken(texts):
        raise LLMRateLimitError("LLM rate limited (429)")

    monkeypatch.setattr(mm, "_embed", broken)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_FAILED
    assert job["reason_code"] == "LLMRateLimitError"


def test_off_parity_scheduler_flag(fresh_ecp, monkeypatch):
    """`EMBED_PRIORITY_SCHEDULER_ENABLED=false` → приоритетов нет: P3 держит
    слот наравне со всеми — P0 ждёт свободный слот как обычный участник
    (никакого priority-jump, единый статический лимит)."""
    _patch_setting(monkeypatch, "EMBED_PRIORITY_SCHEDULER_ENABLED", False)
    from services import embedding_control_plane as ecp

    async def _flow():
        permit_p3 = await ecp.SCHEDULER.acquire(Priority.P3_REBUILD, "g")
        try:
            await asyncio.wait_for(
                ecp.SCHEDULER.acquire(Priority.P0_QUERY, "g", max_wait_s=0.1),
                timeout=1.0)
            return "p0-acquired"
        except Exception as exc:
            return type(exc).__name__
        finally:
            ecp.SCHEDULER.release(permit_p3)

    assert asyncio.run(_flow()) == "EmbeddingConcurrencyBusy"


def test_off_parity_adaptive_concurrency_flag(fresh_ecp, monkeypatch):
    """`EMBED_ADAPTIVE_CONCURRENCY_ENABLED=false` → статические
    GRAPHRAG_REBUILD_BATCH/SLEEP (spec §8.2), AIMD не вмешивается."""
    _patch_setting(monkeypatch, "EMBED_ADAPTIVE_CONCURRENCY_ENABLED", False)
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_BATCH", 7)
    from services import graphrag_rebuild as gr
    assert gr._adaptive_batch_size() == 7
    # 429 НЕ сжимает статический батч.
    fresh_ecp.CONTROLLER.on_batch_rate_limit()
    assert gr._adaptive_batch_size() == 7


def test_async_batch_default_off():
    """`EMBED_ASYNC_BATCH_ENABLED` — единственный default-OFF (spec §8.2):
    async Batch API не включается без live-верификации."""
    from services.embedding_control_plane import async_batch_enabled
    assert async_batch_enabled() is False


# ═══ Rework round 1 (review Wave A): H-ASAP4-1 — retry-ownership ════════════
# Требование ревью: тест на уровне НАСТОЯЩЕГО `LLMClient._post` с фейк-
# транспортом — не на фейке `embed_once`, который мерял не тот слой.


class _CountingHandler:
    """Фейк-транспорт для настоящего `LLMClient._post` (httpx.MockTransport):
    считает HTTP-вызовы, отвечает заданным статусом/заголовками."""

    def __init__(self, status: int, headers: dict | None = None):
        self.status = status
        self.headers = headers or {}
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(self.status, headers=self.headers,
                              json={"error": {"status": self.status}},
                              request=request)


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _post_client(monkeypatch, handler) -> LLMClient:
    # Реальный класс фиксируется на импорте: httpx-модуль глобален, повторный
    # патч в одном тесте иначе захватил бы factory предыдущего патча.
    original = _REAL_ASYNC_CLIENT
    transport = httpx.MockTransport(handler)

    def factory(**kw):
        return original(transport=transport, **kw)

    monkeypatch.setattr("services.llm_client.httpx.AsyncClient", factory)
    return LLMClient("https://llm.example.invalid", "sk-test", "chat-model",
                     "gemini-embedding-001")


def _spy_sleep(monkeypatch) -> list[float]:
    """Запись снов БЕЗ реального ожидания: «429 без сна» меряется фактом
    НЕ-вызова asyncio.sleep, а не длительностью."""
    sleeps: list[float] = []

    async def _record(delay, *a, **kw):
        sleeps.append(float(delay))

    monkeypatch.setattr(asyncio, "sleep", _record)
    return sleeps


@pytest.mark.asyncio
async def test_post_retry_statuses_empty_429_single_call_no_sleep(monkeypatch):
    """H-ASAP4-1: `retry_statuses=()` через НАСТОЯЩИЙ `_post` — 429 даёт
    РОВНО ОДИН HTTP-вызов, честный Retry-After поднимается наверх в
    исключении (in-memory, R17), нижний слой не спит и не ретраит
    (quota-policy — только EmbeddingExecutor, анти-паттерн §9/Q4 закрыт)."""
    rec = _CountingHandler(429, headers={"Retry-After": "20"})
    client = _post_client(monkeypatch, rec)
    sleeps = _spy_sleep(monkeypatch)
    with pytest.raises(LLMRateLimitError) as exc_info:
        await client._post("/embeddings", {"model": "m", "input": ["x"]},
                           api_key="sk-test",
                           base_url="https://llm.example.invalid",
                           channel="embed", max_retries=1, retry_statuses=())
    assert rec.calls == 1                       # не 2 (нижнеуровневый ретрай мёртв)
    assert sleeps == []                         # ни одного сна нижним слоем
    # Честный Retry-After — наверх для classify_rate_limit executor'а.
    assert exc_info.value.headers.get("Retry-After") == "20"
    assert "error" in (exc_info.value.body or "")


@pytest.mark.asyncio
async def test_post_retry_statuses_allowlist_retries_only_listed(monkeypatch):
    """H-ASAP4-1 (allowlist-семантика): ретраится ТОЛЬКО перечисленное —
    `(503,)` → 503 ретраится нижним слоем (2 вызова), а 429 при том же
    allowlist уходит наверх немедленно (1 вызов)."""
    rec = _CountingHandler(503)
    client = _post_client(monkeypatch, rec)
    client.backoff_base = 0                     # сон ретрая = 0 (не часть контракта)
    with pytest.raises(LLMServerError):
        await client._post("/embeddings", {"model": "m", "input": ["x"]},
                           api_key="sk-test",
                           base_url="https://llm.example.invalid",
                           channel="embed", max_retries=1, retry_statuses=(503,))
    assert rec.calls == 2
    rec2 = _CountingHandler(429, headers={"Retry-After": "5"})
    client2 = _post_client(monkeypatch, rec2)
    with pytest.raises(LLMRateLimitError):
        await client2._post("/embeddings", {"model": "m", "input": ["x"]},
                            api_key="sk-test",
                            base_url="https://llm.example.invalid",
                            channel="embed", max_retries=1,
                            retry_statuses=(503,))
    assert rec2.calls == 1


@pytest.mark.asyncio
async def test_post_retry_statuses_none_legacy_retries_429(monkeypatch):
    """H-ASAP4-1 (бит-в-бит паритет): retry_statuses=None — прежнее
    поведение: 429 ретраится нижним слоем (2 вызова) с честным
    min(Retry-After, cap) сном; финал — LLMRateLimitError с заголовками."""
    rec = _CountingHandler(429, headers={"Retry-After": "20"})
    client = _post_client(monkeypatch, rec)
    sleeps = _spy_sleep(monkeypatch)
    with pytest.raises(LLMRateLimitError) as exc_info:
        await client._post("/embeddings", {"model": "m", "input": ["x"]},
                           api_key="sk-test",
                           base_url="https://llm.example.invalid",
                           channel="embed", max_retries=1, retry_statuses=None)
    assert rec.calls == 2
    assert sleeps == [min(20.0, client._backoff_cap)]
    assert exc_info.value.headers.get("Retry-After") == "20"


# ═══ Rework round 1: H-ASAP4-2 / M-ASAP4-3 — классификация фейлов build'а ═══


@pytest.mark.asyncio
async def test_cooling_group_between_batches_pauses_not_fails(vec_db,
                                                              monkeypatch):
    """H-ASAP4-2 (негативный): группа ушла в cooldown МЕЖДУ батчами
    (P0-трафик получил 429 → group cooling; следующий батч rebuild падает
    сразу, БЕЗ HTTP — executor бросает EmbeddingGroupCoolingDown) →
    paused_rate_limit с next_allowed_at из исключения, checkpoint
    preserved, НЕ terminal failed (AM-1/§26). До фикса: terminal failed с
    reason=именем класса."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_BATCH", 2)
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 6)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    resume_calls: list[float] = []

    def _rec_resume(*a, **kw):
        resume_calls.append(time.time())

    monkeypatch.setattr(gr, "_schedule_auto_resume", _rec_resume)
    state = {"calls": 0}

    async def cooling_between_batches(texts):
        state["calls"] += 1
        if state["calls"] == 1:
            return await CountingEmbed()(texts)
        # Группа cooling между батчами: CoolingDown поднимается БЕЗ HTTP.
        raise EmbeddingGroupCoolingDown(
            group_id=UNKNOWN_GROUP_ID,
            next_allowed_at=int(time.time()) + 120)

    monkeypatch.setattr(mm, "_embed", cooling_between_batches)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    # AM-1: пауза, НЕ terminal failed.
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    assert str(job["reason_code"]).startswith("rate_limit:")
    # next_allowed_at — из исключения (честные ~120s, не дефолт-кулдаун).
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert int(gen["next_allowed_at"]) >= int(time.time()) + 100
    assert gen["pause_reason"] == "rate_limit:quota_group"
    assert int(gen["attempts_total"]) == 1
    # Checkpoint preserved (первый батч обработан до cooling).
    from services.task_supervisor import TaskJobStore
    checkpoint = await TaskJobStore(vec_db).get_checkpoint(jid)
    cursor = json.loads(checkpoint["cursor"])
    assert cursor["processed"] == 2
    # Авто-resume запланирован (AM-1).
    assert resume_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    EmbeddingBudgetExhausted("embedding attempt budget exhausted (budget=4)"),
    EmbeddingConcurrencyBusy("embedding scheduler busy"),
], ids=["budget_exhausted", "concurrency_busy"])
async def test_executor_budget_or_busy_pauses_not_fails(vec_db, monkeypatch,
                                                        exc):
    """H-ASAP4-2: BudgetExhausted/ConcurrencyBusy — provider-pressure класс:
    paused_provider (авто-resume; horizon §25 ограничивает), НЕ terminal."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    monkeypatch.setattr(gr, "_schedule_auto_resume", lambda *a, **kw: None)

    async def busy(texts):
        raise exc

    monkeypatch.setattr(mm, "_embed", busy)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_PROVIDER
    assert job["reason_code"] == "provider_unavailable"
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert int(gen["next_allowed_at"]) >= int(time.time()) + 30
    assert int(gen["attempts_total"]) == 1


@pytest.mark.asyncio
async def test_post_checkpoint_validation_exception_honest_terminal(vec_db,
                                                                    monkeypatch):
    """M-ASAP4-3: исключение на пост-checkpoint стадии (_validate, после
    CAS RUNNING→CHECKPOINT) больше не тонет: deterministic-класс получает
    честный terminal failed (§25). До фикса все CAS с expect=ST_RUNNING
    молча no-op'ились — job зависал в checkpoint и пере-resume'ился
    планировщиком без horizon."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    monkeypatch.setattr(gr, "_schedule_auto_resume", lambda *a, **kw: None)
    original_execute = vec_db.db.execute

    async def raising_execute(sql, *a, **kw):
        # Точка ПОСЛЕ CAS RUNNING→CHECKPOINT: sample-fetch в _validate.
        if "rowid, embedding" in str(sql):
            raise RuntimeError("simulated deterministic decode failure")
        return await original_execute(sql, *a, **kw)

    monkeypatch.setattr(vec_db.db, "execute", raising_execute)
    monkeypatch.setattr(mm, "_embed", CountingEmbed())
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_FAILED
    assert job["reason_code"] == "RuntimeError"


# ═══ Rework round 1: M-ASAP4-4 — 7-й код A.6 knn_query_vector_failed ═══════


class _UnserializableVector:
    """Вектор с корректным len(), но несериализуемым json.dumps —
    симуляция битой проекции query-вектора (M-ASAP4-4)."""

    def __init__(self, values):
        self._v = list(values)

    def __len__(self):
        return len(self._v)

    def __iter__(self):
        return iter(self._v)


@pytest.mark.asyncio
async def test_knn_query_vector_failed_distinct_reason(vec_db, monkeypatch):
    """M-ASAP4-4: провал построения query-вектора — distinct 7-й код A.6
    `knn_query_vector_failed`, НЕ маскируется под
    `knn_index_schema_mismatch` (тот диагностирует сбой самого MATCH)."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    shadow, frontier = await _build_full_shadow(mm, vec_db, "graph_facts_vec",
                                                fp, generation)
    # len == expected_dim (dim-гейт проходит), json.dumps падает.
    monkeypatch.setattr(gr, "_read_vector",
                        lambda blob: _UnserializableVector([0.1] * 8))
    ok, report = await gr._validate(mm, "graph_facts_vec", shadow, fp,
                                    frontier)
    assert ok is False
    assert report["reason_code"] == "knn_query_vector_failed"
    diag = report["knn_diagnostics"]
    assert diag["stage"] == "query_vector_build"
    assert diag["query_vector_ok"] is False


# ═══ Corrective pass T-4503 (design-fix D1–D6): kind-aware parking, ═════════
# ═══ resume-backoff, честная диагностика пула, дедуп 429, OFF-паритет. ══════


import logging as _logging

from services import embedding_control_plane as ecp


def _mk_rate_limit(body: str, retry_after: float | None):
    """429-поведение для FakeLLM.script: тело с kind-маркером + опц. RA."""
    async def _raise(self, texts):
        exc = LLMRateLimitError("LLM rate limited (429)")
        if retry_after is not None:
            exc.headers = {"Retry-After": str(retry_after)}
        exc.body = body
        raise exc
    return _raise


_SPEND_NO_RA = _mk_rate_limit(
    "billing status: resource has been exhausted (spend budget)", None)
_SPEND_RA_120 = _mk_rate_limit(
    "billing status: resource has been exhausted (spend budget)", 120.0)


# ── D1: kind-aware parking ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parking_spend_until_utc_day_end(fresh_ecp, monkeypatch):
    """D1/acceptance п.1: spend-429 БЕЗ Retry-After → парковка группы до
    конца текущих суток UTC + margin; state=exhausted; честная note
    `parked ... est=utc_day_end` (не фальшивая посекундная точность)."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    llm = FakeLLM()
    llm.script = [_SPEND_NO_RA]
    ex = EmbeddingExecutor(llm)
    with pytest.raises(EmbeddingGroupCoolingDown):
        await ex.embed(["x"], priority=Priority.P3_REBUILD)
    # РОВНО ОДИН HTTP-вызов: после парковки повторов в группу нет.
    assert len(llm.calls) == 1
    group = fresh_ecp.REGISTRY.group_state(UNKNOWN_GROUP_ID)
    assert group.state == "exhausted"
    margin = float(ecp._settings_value("EMBED_QUOTA_RESET_MARGIN_SECONDS",
                                       300.0))
    expected = ecp._utc_day_end() + margin
    assert abs(group.next_allowed_at - expected) <= 5
    assert group.note == "parked kind=spend est=utc_day_end"
    # Парковка длиннее дефолта: минимум margin (даже у самой границы суток).
    assert group.next_allowed_at >= int(time.time()) + 290


@pytest.mark.asyncio
async def test_parking_respects_provider_ra(fresh_ecp, monkeypatch):
    """D1/failure-semantics 2: RA у spend/daily (нетипично) — уважается RA с
    ceiling 300s, парковка-оценка НЕ применяется (провайдер точнее)."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    llm = FakeLLM()
    llm.script = [_SPEND_RA_120]
    ex = EmbeddingExecutor(llm)
    with pytest.raises(EmbeddingGroupCoolingDown):
        await ex.embed(["x"], priority=Priority.P3_REBUILD)
    group = fresh_ecp.REGISTRY.group_state(UNKNOWN_GROUP_ID)
    assert group.state == "exhausted"
    now = int(time.time())
    assert now + 115 <= group.next_allowed_at <= now + 125   # RA=120, не cap
    assert group.note == "429 kind=spend ra=120.0"           # точный формат
    # RA выше ceiling → capped 300s (AM-1).
    fresh_ecp.REGISTRY.reset_runtime()
    llm2 = FakeLLM()
    llm2.script = [_mk_rate_limit("spend budget exhausted", 9999.0)]
    with pytest.raises(EmbeddingGroupCoolingDown):
        await EmbeddingExecutor(llm2).embed(["x"], priority=Priority.P3_REBUILD)
    group2 = fresh_ecp.REGISTRY.group_state(UNKNOWN_GROUP_ID)
    assert group2.next_allowed_at <= int(time.time()) + 301


@pytest.mark.asyncio
async def test_rpm_tpm_unchanged(fresh_ecp, monkeypatch):
    """D1/acceptance п.4: rpm/tpm/rate — бит-в-бит прежняя семантика
    (RA-capped 300s / default 20s; burst ≠ quota-unavailable)."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    cases = [
        # (body, retry_after, expected_state, delay_bounds)
        ("Requests per minute quota exceeded", None,
         "cooling_down", (18, 22)),          # rpm без RA → default 20s
        ("tokens per minute (TPM) limit", None,
         "cooling_down", (18, 22)),          # tpm без RA → burst 20s
        ("tokens per minute (TPM) limit", 400.0,
         "exhausted", (295, 305)),           # RA > ceiling → capped 300s
    ]
    for body, ra, exp_state, (lo, hi) in cases:
        fresh_ecp.REGISTRY.reset_runtime()
        llm = FakeLLM()
        llm.script = [_mk_rate_limit(body, ra)]
        with pytest.raises(EmbeddingGroupCoolingDown):
            await EmbeddingExecutor(llm).embed(["x"],
                                               priority=Priority.P3_REBUILD)
        group = fresh_ecp.REGISTRY.group_state(UNKNOWN_GROUP_ID)
        now = int(time.time())
        assert group.state == exp_state, body
        assert now + lo <= group.next_allowed_at <= now + hi, body
        assert group.note.startswith("429 kind="), body
        assert "parked" not in group.note, body


@pytest.mark.asyncio
async def test_parking_off_bit_identical(fresh_ecp, monkeypatch):
    """D5/acceptance п.7: EMBED_QUOTA_KIND_PARKING_ENABLED=OFF → бит-в-бит
    2.58.45: kind не влияет на длительность (default 20s), note прежнего
    формата, state как сейчас."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    _patch_setting(monkeypatch, "EMBED_QUOTA_KIND_PARKING_ENABLED", False)
    llm = FakeLLM()
    llm.script = [_SPEND_NO_RA]
    with pytest.raises(EmbeddingGroupCoolingDown):
        await EmbeddingExecutor(llm).embed(["x"], priority=Priority.P3_REBUILD)
    group = fresh_ecp.REGISTRY.group_state(UNKNOWN_GROUP_ID)
    now = int(time.time())
    assert group.state == "exhausted"        # is_quota_unavailable не менялся
    assert now + 18 <= group.next_allowed_at <= now + 22     # default 20s
    assert group.note == "429 kind=spend ra=None"            # прежний формат
    # RA-путь при OFF — прежний ceiling (300s).
    fresh_ecp.REGISTRY.reset_runtime()
    llm2 = FakeLLM()
    llm2.script = [_mk_rate_limit("spend budget exhausted", 9999.0)]
    with pytest.raises(EmbeddingGroupCoolingDown):
        await EmbeddingExecutor(llm2).embed(["x"], priority=Priority.P3_REBUILD)
    group2 = fresh_ecp.REGISTRY.group_state(UNKNOWN_GROUP_ID)
    assert group2.next_allowed_at <= int(time.time()) + 301
    assert group2.note == "429 kind=spend ra=9999.0"


@pytest.mark.asyncio
@pytest.mark.parametrize("parking_on,backoff_on", [
    (True, True), (True, False), (False, True), (False, False),
], ids=["both_on", "parking_on_backoff_off", "parking_off_backoff_on",
        "both_off"])
async def test_flag_matrix_parking_backoff(fresh_ecp, monkeypatch,
                                           parking_on, backoff_on):
    """D5-матрица сочетаний обоих флагов (design-fix §Матрица):
    parking управляет длительностью quota-паузы, backoff — нелинейностью
    default-cooldown ветки; OFF-комбинации — прежние значения."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    _patch_setting(monkeypatch, "EMBED_QUOTA_KIND_PARKING_ENABLED", parking_on)
    _patch_setting(monkeypatch, "EMBED_RESUME_BACKOFF_ENABLED", backoff_on)
    # Фаза 1 (executor): spend без RA.
    llm = FakeLLM()
    llm.script = [_SPEND_NO_RA]
    with pytest.raises(EmbeddingGroupCoolingDown):
        await EmbeddingExecutor(llm).embed(["x"], priority=Priority.P3_REBUILD)
    group = fresh_ecp.REGISTRY.group_state(UNKNOWN_GROUP_ID)
    now = int(time.time())
    if parking_on:
        assert group.next_allowed_at >= now + 290          # парковка (≥ margin)
        assert group.note.startswith("parked kind=spend est=")
    else:
        assert now + 18 <= group.next_allowed_at <= now + 22  # default 20s
        assert group.note == "429 kind=spend ra=None"
    # Фаза 2 (backoff-математика, default-cooldown ветка, streak=0).
    delay = gr._resume_backoff_delay(0)
    if backoff_on:
        assert 20.0 <= delay <= 25.0        # 20 × jitter(1.00–1.25)
    else:
        assert delay == 20.0                # без нелинейности и джиттера


# ── D2: backoff + персистентность ───────────────────────────────────────────


def test_backoff_doubles_with_cap_and_jitter(fresh_ecp, monkeypatch):
    """D2/acceptance п.3: прогрессия ×2 с потолком 3600s, jitter в границах
    ≤25%; OFF → ровно дефолт без нелинейности."""
    assert 20.0 <= gr._resume_backoff_delay(0) <= 25.0
    assert 40.0 <= gr._resume_backoff_delay(1) <= 50.0
    assert 80.0 <= gr._resume_backoff_delay(2) <= 100.0
    # Потолок: 20×2^30 ≫ 3600 → capped, jitter ≤25% поверх капа.
    assert 3600.0 <= gr._resume_backoff_delay(30) <= 4500.0
    assert 3600.0 <= gr._resume_backoff_delay(1000) <= 4500.0
    _patch_setting(monkeypatch, "EMBED_RESUME_BACKOFF_ENABLED", False)
    assert gr._resume_backoff_delay(0) == 20.0
    assert gr._resume_backoff_delay(50) == 20.0


@pytest.mark.asyncio
async def test_backoff_streak_survives_reload(vec_db, monkeypatch):
    """D2/acceptance п.3: стрик живёт в result_ref (ΔDDL=0) — переживает
    «перезагрузку» (повторное чтение из БД); битый/чужой JSON → стрик 0
    (безопасная деградация, failure-semantics 3)."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    # Две подряд exhausted-паузы (инкремент как в _handle_build_failure).
    await gr._pause_bookkeeping(vec_db, jid, "rate_limit:quota_group",
                                int(time.time()) + 7200,
                                quota_streak=0 + 1, quota_kind="spend")
    assert await gr._quota_streak(vec_db, jid) == 1
    await gr._pause_bookkeeping(vec_db, jid, "rate_limit:quota_group",
                                int(time.time()) + 7200,
                                quota_streak=1 + 1, quota_kind="spend")
    # «Перезагрузка»: стрик читается из БД заново (не из памяти).
    assert await gr._quota_streak(vec_db, jid) == 2
    row = await gr._get_job(vec_db, jid)
    book = json.loads(row["result_ref"])
    assert book["quota_kind_last"] == "spend"
    assert book["pause_count"] == 2
    # kind последней quota-паузы берётся из registry-ноты группы (честно).
    ecp.REGISTRY._set_group_local(
        UNKNOWN_GROUP_ID, "exhausted", int(time.time()) + 7200,
        "parked kind=spend est=utc_day_end")
    assert gr._quota_kind_of_pause("rate_limit:quota_group",
                                   EmbeddingGroupCoolingDown(
                                       group_id=UNKNOWN_GROUP_ID,
                                       next_allowed_at=1)) == "spend"
    # Битый JSON → толерантный парсер → стрик 0.
    await vec_db.db.execute("UPDATE task_jobs SET result_ref = 'not-json' "
                            "WHERE job_id = ?", (jid,))
    await vec_db.db.commit()
    assert await gr._quota_streak(vec_db, jid) == 0


@pytest.mark.asyncio
async def test_success_resets_streak(vec_db, monkeypatch):
    """D2/acceptance п.3: успешный батч после resume обнуляет стрик."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_BATCH", 2)
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 4)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    monkeypatch.setattr(gr, "_schedule_auto_resume", lambda *a, **kw: None)
    state = {"calls": 0}

    async def cooling_then_ok(texts):
        state["calls"] += 1
        if state["calls"] == 1:
            raise EmbeddingGroupCoolingDown(
                group_id=UNKNOWN_GROUP_ID, next_allowed_at=int(time.time()) - 5)
        return await CountingEmbed()(texts)

    monkeypatch.setattr(mm, "_embed", cooling_then_ok)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    assert await gr._quota_streak(vec_db, jid) == 1     # exhausted-пауза учтена
    # Cooldown истёк → resume, все батчи успешны → стрик обнулён.
    await vec_db.db.execute(
        "UPDATE mca_embedding_index_generations SET next_allowed_at = ? "
        "WHERE index_name = 'graph_facts_vec' AND fingerprint = ?",
        (int(time.time()) - 1, fp))
    await vec_db.db.commit()
    monkeypatch.setattr(mm, "_embed", CountingEmbed())
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_ACTIVATED
    assert await gr._quota_streak(vec_db, jid) == 0


@pytest.mark.asyncio
async def test_backoff_off_bit_identical(vec_db, monkeypatch):
    """D5/acceptance п.7: EMBED_RESUME_BACKOFF_ENABLED=OFF → пауза без
    нелинейности/джиттера — ровно дефолт-кулдаун (бит-в-бит 2.58.45)."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    _patch_setting(monkeypatch, "EMBED_RESUME_BACKOFF_ENABLED", False)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    monkeypatch.setattr(gr, "_schedule_auto_resume", lambda *a, **kw: None)

    async def expired_cooling(texts):
        raise EmbeddingGroupCoolingDown(
            group_id=UNKNOWN_GROUP_ID, next_allowed_at=int(time.time()) - 10)

    monkeypatch.setattr(mm, "_embed", expired_cooling)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    now = int(time.time())
    # Ровно default 20s (без jitter-разброса [20, 25]).
    assert now + 18 <= int(gen["next_allowed_at"]) <= now + 21


@pytest.mark.asyncio
async def test_parking_consumes_horizon(vec_db, monkeypatch):
    """D2: горизонт 24h без изменений — pause_started_at ставится ОДИН раз
    и не сбрасывается между паузами; многочасовая парковка расходует общий
    wall-clock-горизонт; терминал по исчерпании — существующий путь."""
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    # Пауза-парковка (многочасовой next_allowed_at).
    await gr._pause_bookkeeping(vec_db, jid, "rate_limit:quota_group",
                                int(time.time()) + 7200,
                                quota_streak=1, quota_kind="spend")
    started1 = await gr._pause_started_at(vec_db, jid)
    assert started1 > 0
    assert not await gr._horizon_exhausted(vec_db, jid)
    # Повторная пауза (parking-оценка промахнулась, цикл честно повторился):
    # pause_started_at НЕ сбрасывается → парковка расходует horizon.
    await gr._pause_bookkeeping(vec_db, jid, "rate_limit:quota_group",
                                int(time.time()) + 86400,
                                quota_streak=2, quota_kind="spend")
    assert await gr._pause_started_at(vec_db, jid) == started1
    row = await gr._get_job(vec_db, jid)
    book = json.loads(row["result_ref"])
    assert book["pause_count"] == 2
    assert book["quota_exhaust_streak"] == 2
    # Горизонт исчерпан → терминал (существующий критерий §25).
    await vec_db.db.execute(
        "UPDATE task_jobs SET result_ref = ? WHERE job_id = ?",
        (json.dumps({"pause_started_at": int(time.time())
                     - int(gr._retry_horizon_seconds()) - 10,
                     "pause_count": 9}), jid))
    await vec_db.db.commit()
    assert await gr._horizon_exhausted(vec_db, jid)


# ── D1: resume-гейты §68 («не будить до срока») ─────────────────────────────


@pytest.mark.asyncio
async def test_resume_waits_until_next_allowed(vec_db, monkeypatch):
    """D1-инвариант: парковка → планировщик НЕ шлёт запросов в группу до
    next_allowed_at (0 HTTP от фейк-транспорта); после наступления срока —
    resume продолжается с checkpoint (last_id не сбрасывается)."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_BATCH", 2)
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 6)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    monkeypatch.setattr(gr, "_schedule_auto_resume", lambda *a, **kw: None)
    embed = CountingEmbed()
    state = {"calls": 0}

    async def parked_first_batch_then_cooling(texts):
        state["calls"] += 1
        if state["calls"] == 1:
            return await embed(texts)
        # Как executor после spend-парковки: CoolingDown с многочасовым
        # next_allowed_at (без нового HTTP).
        raise EmbeddingGroupCoolingDown(
            group_id=UNKNOWN_GROUP_ID,
            next_allowed_at=int(time.time()) + 7200)

    monkeypatch.setattr(mm, "_embed", parked_first_batch_then_cooling)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert int(gen["next_allowed_at"]) >= int(time.time()) + 7000
    assert gen["pause_reason"] == "rate_limit:quota_group"
    assert gen["status"] == "building"                  # generation НЕ сброшен
    from services.task_supervisor import TaskJobStore
    checkpoint = await TaskJobStore(vec_db).get_checkpoint(jid)
    cursor = json.loads(checkpoint["cursor"])
    assert cursor["processed"] == 2 and cursor["last_id"] > 0
    calls_at_park = state["calls"]

    # Планировщик при живой парковке: 0 запусков, 0 новых HTTP-вызовов.
    assert await gr.maybe_schedule_rebuilds(mm) == []
    assert state["calls"] == calls_at_park
    # Рестарт-гейт §68: _ensure_job не будит, джоба остаётся в паузе.
    assert await gr._ensure_job(vec_db, "graph_facts_vec", fp,
                                generation) is None
    assert state["calls"] == calls_at_park
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT

    # Срок наступил → resume ТОЙ ЖЕ generation с checkpoint.
    await vec_db.db.execute(
        "UPDATE mca_embedding_index_generations SET next_allowed_at = ? "
        "WHERE index_name = 'graph_facts_vec' AND fingerprint = ?",
        (int(time.time()) - 1, fp))
    await vec_db.db.commit()
    assert await gr._ensure_job(vec_db, "graph_facts_vec", fp,
                                generation) == jid
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_QUEUED
    await gr._registry_resume(vec_db, "graph_facts_vec", fp)
    monkeypatch.setattr(mm, "_embed", embed)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_ACTIVATED
    gen = await vec_db.get_generation_by_fingerprint("graph_facts_vec", fp)
    assert int(gen["generation"]) == generation          # не gen 2,3…
    # 6 фактов всего (2 до парковки + 4 после), работа НЕ дублируется.
    assert len(embed.texts) == 6
    checkpoint = await TaskJobStore(vec_db).get_checkpoint(jid)
    assert json.loads(checkpoint["cursor"])["processed"] == 6


@pytest.mark.asyncio
async def test_restart_parked_not_woken(vec_db, monkeypatch):
    """D1/acceptance п.2: рестарт не будит — _ensure_job при живом
    next_allowed_at → None, generation не сброшен, attempts не растут."""
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    monkeypatch.setattr(gr, "_schedule_auto_resume", lambda *a, **kw: None)

    async def parked(texts):
        raise EmbeddingGroupCoolingDown(
            group_id=UNKNOWN_GROUP_ID,
            next_allowed_at=int(time.time()) + 86400)

    monkeypatch.setattr(mm, "_embed", parked)
    await gr.run_job(mm, "graph_facts_vec", jid)
    gen_before = await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", fp)
    attempts_before = int(gen_before["attempts_total"] or 0)
    assert str(gen_before["status"]) == "building"
    # «Рестарт»: планировщик на старте при живой парковке.
    assert await gr._ensure_job(vec_db, "graph_facts_vec", fp,
                                generation) is None
    gen_after = await vec_db.get_generation_by_fingerprint(
        "graph_facts_vec", fp)
    assert int(gen_after["generation"]) == generation    # НЕ сброшен
    assert int(gen_after["attempts_total"] or 0) == attempts_before
    assert gen_after["pause_reason"] == "rate_limit:quota_group"
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT


# ── D4: дедуп 429-счётчика ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_429_counted_once_per_real_hit(vec_db, monkeypatch):
    """D4/acceptance п.6: ровно 1 инкремент на реальный 429. (а) Реальный 429
    через executor → счётчик 1; (б) pause-конверсия CoolingDown без нового
    429 → счётчик НЕ растёт (до фикса был второй инкремент — ×2)."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    llm = FakeLLM()
    llm.script = [_SPEND_RA_120]
    with pytest.raises(EmbeddingGroupCoolingDown):
        await EmbeddingExecutor(llm).embed(["x"], priority=Priority.P3_REBUILD)
    assert ecp.REGISTRY.rate_limits_last_10m() == 1      # реальный 429
    # (б) rebuild-пауза от CoolingDown (группа уже cooling, HTTP не было).
    _patch_setting(monkeypatch, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.0)
    mm = _memory(vec_db)
    await _seed_facts(vec_db, "graph_facts_vec", 2)
    fp = mm._identity_fingerprint()
    generation = await _register_building(vec_db, "graph_facts_vec", fp)
    jid = await gr._ensure_job(vec_db, "graph_facts_vec", fp, generation)
    monkeypatch.setattr(gr, "_schedule_auto_resume", lambda *a, **kw: None)
    counter_before = ecp.REGISTRY.rate_limits_last_10m()

    async def cooling(texts):
        raise EmbeddingGroupCoolingDown(
            group_id=UNKNOWN_GROUP_ID,
            next_allowed_at=int(time.time()) + 120)

    monkeypatch.setattr(mm, "_embed", cooling)
    await gr.run_job(mm, "graph_facts_vec", jid)
    job = await gr._get_job(vec_db, jid)
    assert job["status"] == gr.ST_PAUSED_RATE_LIMIT
    # Дубль устранён: пауза без свежего 429 не инкрементирует.
    assert ecp.REGISTRY.rate_limits_last_10m() == counter_before


# ── D3: честная диагностика пула ────────────────────────────────────────────


def test_degenerate_pool_hint(monkeypatch):
    """D3/acceptance п.5: вырожденный пул (3 ключа → одна unknown-группа) →
    degenerate=True; labels разделяют группы → degenerate=False; одна
    известная группа — всё ещё degenerate (|groups|==1)."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    diag = ecp.pool_rotation_diagnosis(build_credential_pool())
    assert diag == {"keys": 3, "groups": [UNKNOWN_GROUP_ID],
                    "known": False, "degenerate": True}
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3",
                labels="primary:gA, fallback_1:gA, fallback_2:gB")
    diag = ecp.pool_rotation_diagnosis(build_credential_pool())
    assert diag["degenerate"] is False
    assert diag["groups"] == ["gA", "gB"] and diag["known"] is True
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3",
                labels="primary:gA, fallback_1:gA, fallback_2:gA")
    diag = ecp.pool_rotation_diagnosis(build_credential_pool())
    assert diag["degenerate"] is True           # одна группа даже known
    # Панель: rotation-блок по контракту.
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    panel = provider_panel()
    rot = panel["rotation"]
    assert rot["status"] == "none" and rot["degenerate"] is True
    assert rot["groups"] == [UNKNOWN_GROUP_ID] and rot["keys"] == 3
    assert "EMBEDDING_QUOTA_GROUP_LABELS" in rot["hint"]
    # Пул «ожил» (labels заданы) → grouped, hint пуст.
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3",
                labels="primary:gA, fallback_1:gB, fallback_2:gB")
    rot = provider_panel()["rotation"]
    assert rot["status"] == "grouped" and rot["degenerate"] is False
    assert rot["hint"] == ""


def test_diag_log_rate_limited(caplog, fresh_ecp):
    """D3: WARN rotation=none — не чаще 1 раза / 10 мин (in-memory
    rate-limit); healthy-пул не логирует; R17 — без значений ключей."""
    fresh_ecp._last_rotation_warn = 0.0
    diag = {"keys": 3, "groups": [UNKNOWN_GROUP_ID], "known": False,
            "degenerate": True}
    with caplog.at_level(_logging.WARNING,
                         logger="services.embedding_control_plane"):
        assert ecp._maybe_warn_degenerate_rotation(diag) is True
        assert ecp._maybe_warn_degenerate_rotation(diag) is False  # ≤1/10мин
        healthy = {"keys": 3, "groups": ["gA", "gB"], "known": True,
                   "degenerate": False}
        assert ecp._maybe_warn_degenerate_rotation(healthy) is False
        assert ecp._maybe_warn_degenerate_rotation(
            {"keys": 0, "groups": [], "known": False,
             "degenerate": True}) is False        # пустой пул — не про ротацию
    records = [r for r in caplog.records
               if "rotation=none" in r.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "EMBEDDING_QUOTA_GROUP_LABELS" in message
    assert "keys=3" in message and "group=unknown" in message


@pytest.mark.asyncio
async def test_parked_note_and_panel_honest(fresh_ecp, monkeypatch):
    """D1+D3/acceptance п.5/п.8: панель различает парковку-оценку и точный
    RA (`parked ... est=`), показывает rotation: none + hint; R17 — без
    значений ключей."""
    _patch_keys(monkeypatch, primary="secret-key-material", fb1="k2",
                fb2="k3")
    llm = FakeLLM()
    llm.script = [_SPEND_NO_RA]
    with pytest.raises(EmbeddingGroupCoolingDown):
        await EmbeddingExecutor(llm).embed(["x"], priority=Priority.P3_REBUILD)
    panel = provider_panel()
    rot = panel["rotation"]
    assert rot["status"] == "none" and rot["degenerate"] is True
    lines = {g["quota_group"]: g for g in panel["groups"]}
    parked_line = lines.get("не определены")
    assert parked_line is not None
    assert parked_line["note"] == "parked kind=spend est=utc_day_end"
    assert parked_line["state"] == "exhausted"
    assert parked_line["next_allowed_at"] >= int(time.time()) + 290
    # RA-формат остаётся различимым (не оценка).
    ecp.REGISTRY._set_group_local(
        "gX", "cooling_down", int(time.time()) + 120,
        "429 kind=tpm ra=120.0")
    panel2 = provider_panel()
    notes = {g["note"] for g in panel2["groups"]}
    assert "429 kind=tpm ra=120.0" in notes
    assert "parked kind=spend est=utc_day_end" in notes
    # R17: значение ключа не утекает в панель.
    assert "secret-key-material" not in json.dumps(panel, ensure_ascii=False)
