"""P0 EMBED-503-FAILOVER — admission is MODEL SPACE (MSI), not PCI.

Owner clarification 22.11.2026: the embedding model never changed
(`gemini-embedding-001`); only the API gateway changed (apinet -> Google).
PCI is connection provenance, not a vector-space identity. A working fallback
with the same MSI/dims must be admitted to the ACTIVE index; absence of a
PCI-specific admission is NOT incompatibility.

Contract under test:
  * same MSI (`e540d4ad890e121d`) + dims, different PCI (apinet vs google)
    → admitted, vector written, semantic KNN finds the new fact;
    historical PCI-keyed durable admission is reused by MSI;
  * different MSI/model → text-only/FTS, no vector, no cache bypass;
  * dimension mismatch → text-only;
  * no MSI metadata + stored old vectors → exactly one bounded probe on those
    vectors; success persists a durable MSI admission, failure stays text-only;
  * canary DRIFT still blocks writes (real incompatibility safety);
  * primary recovery keeps existing vectors and resumes normal routing.

TEST-LIFECYCLE: CONTRACT/REGRESSION owner=P0-EMBED-503-FAILOVER/admission-MSI.
"""
import hashlib
import json
import logging
import math
import time

import pytest
import pytest_asyncio

from services import embedding_control_plane as ecp
from services import hot_config
from services import summary_memory as sm
from services.database import DatabaseService
from services.llm_client import (
    LLMAuthError, LLMRateLimitError, LLMServerError,
)
from services.summary_memory import FACT_EXTRACT_PROMPT, MemoryManager

pytestmark = pytest.mark.asap4

DIMS = 3072
MODEL = "gemini-embedding-001"
OTHER_MODEL = "text-embedding-004"
PRIMARY_BASE = "https://apinet.test/v1"
FB1_BASE = "https://generativelanguage.test/v1beta/openai"
FB2_BASE = "https://google-second.test/v1beta/openai"
INDEX = "graph_facts_vec"
LIVE_MSI = "e540d4ad890e121d"


def _unit(seed: str, dim: int = DIMS) -> list[float]:
    """Deterministic normalized vector (no network/random)."""
    vals: list[float] = []
    i = 0
    while len(vals) < dim:
        digest = hashlib.sha256(f"{seed}#{i}".encode("utf-8")).digest()
        vals.append(int.from_bytes(digest[:4], "little") / (2 ** 32 - 1) * 2 - 1)
        i += 1
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]


@pytest.fixture(autouse=True)
def fresh_ecp(monkeypatch):
    ecp.REGISTRY = ecp.QuotaGroupRegistry()
    ecp.CONTROLLER = ecp.AdaptiveController()
    ecp.SCHEDULER = ecp.PriorityScheduler()
    ecp.EXECUTOR = None
    ecp.reset_compat_state()
    ecp._CANARY_VERDICTS.clear()
    ecp._CANARY_BLOCK_LOG.clear()
    ecp._last_state_log.clear()
    ecp.clear_last_served_credential()
    monkeypatch.setattr(ecp, "_TRANSPORT_BACKOFF_BASE", 0.0)
    yield ecp


def _isolate(monkeypatch, values):
    def _fake_setting(name, default=""):
        if str(name).startswith("EMBEDDING_"):
            return ""
        return default

    monkeypatch.setattr(ecp, "_hot_get",
                        lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(ecp, "_settings_value", _fake_setting)
    monkeypatch.setattr(
        ecp, "_profile_hot",
        lambda key, default="": str(values.get(key, default) or "").strip())
    monkeypatch.setattr(ecp, "_settings_default", _fake_setting)
    monkeypatch.setattr(
        hot_config, "get",
        lambda key, default=None: values.get(key, default))


def _three_slots(monkeypatch, *, labels="", dims=DIMS):
    values = {
        "keys.embedding_api_key": "k-primary",
        "keys.embedding_fallback_api_key": "k-fb1",
        "keys.embedding_fallback_api_key_2": "k-fb2",
        "models.embedding_base_url": PRIMARY_BASE,
        "models.embedding_model_name": MODEL,
        "models.embedding_dim": dims,
        "models.embedding_fallback1_base_url": FB1_BASE,
        "models.embedding_fallback1_model": MODEL,
        "models.embedding_fallback2_base_url": FB2_BASE,
        "models.embedding_fallback2_model": MODEL,
        "keys.embedding_quota_group_labels": labels,
    }
    _isolate(monkeypatch, values)
    return values


class FakeEmbedLLM:
    def __init__(self, facts_json="[]", script=None, dim=DIMS):
        self._embed_model = MODEL
        self.facts_json = facts_json
        self.script = list(script or [])
        self.calls = []
        self.dim = dim

    def _vec(self, text):
        return _unit(f"serving|{text}", self.dim)

    async def embed_once(self, texts, *, api_key, base_url=None, model=None,
                         max_retries=0, retry_statuses=()):
        self.calls.append({"key": api_key, "base_url": base_url,
                           "model": model, "texts": list(texts)})
        behavior = self.script.pop(0) if self.script else "ok"
        if behavior == "server_error":
            raise LLMServerError("LLM server error 503")
        if behavior == "auth":
            raise LLMAuthError("LLM auth failed (401)")
        if behavior == "rate_limit":
            exc = LLMRateLimitError("LLM rate limited (429)")
            exc.headers = {"Retry-After": "5"}
            exc.body = ""
            raise exc
        return [self._vec(t) for t in texts]

    async def generate(self, messages):
        if messages and messages[0].get("content") == FACT_EXTRACT_PROMPT:
            return self.facts_json
        return "[]"

    async def embed(self, texts):       # legacy path not used when pool exists
        return [self._vec(t) for t in texts]


@pytest_asyncio.fixture
async def vec0_db(tmp_path):
    ecp.reset_compat_state()
    db = DatabaseService(str(tmp_path / "p0-admission-msi.db"))
    await db.initialize()
    import sqlite_vec
    await db.db.enable_load_extension(True)
    await db.db.load_extension(sqlite_vec.loadable_path())
    await db.db.enable_load_extension(False)
    yield db
    ecp.REGISTRY.bind_db(None)
    ecp.reset_compat_state()
    await db.close()


async def _memory(db, llm):
    memory = MemoryManager(db, llm)
    memory._vec_available = True
    memory._vec_int8 = False
    memory._vec_dim = DIMS
    await db.db.execute(memory._graph_vec_table_sql(DIMS))
    await db.db.commit()
    return memory


async def _register_active(db, *, fingerprint="old-gateway-fp",
                           model=MODEL, dims=DIMS,
                           provider="generativelanguage.test",
                           admission=None):
    await db.ensure_embedding_generation(
        INDEX, fingerprint, provider=provider, model=model, dims=dims,
        preprocessing_version=sm.EMBEDDING_PREPROCESSING_VERSION,
        endpoint_fingerprint="test-endpoint", activate=True,
        config_revision=admission)
    row = await db.get_active_embedding_generation(INDEX)
    assert row is not None and row["status"] == "active"
    return row


async def _count(db, table):
    cursor = await db.db.execute(f"SELECT COUNT(*) AS c FROM {table}")
    return int((await cursor.fetchone())["c"])


async def _semantic_ids(db, vector, k=5):
    cursor = await db.db.execute(
        "SELECT fact_id FROM graph_facts_vec WHERE embedding MATCH ? AND k = ?",
        (json.dumps([float(x) for x in vector]), int(k)))
    return [int(r["fact_id"]) for r in await cursor.fetchall()]


async def _seed_old_vectors(db, memory, n=12):
    """Source facts + OLD live vectors (same text) for the no-MSI probe."""
    now = int(time.time())
    ids = []
    for i in range(n):
        if i % 4 == 0:
            text = f"короткий факт {i} про память"
        elif i % 4 == 1:
            text = f"средний факт {i}: " + ("контекст " * 40)
        elif i % 4 == 2:
            text = f"длинный факт {i}: " + ("история сообщений " * 160)
        else:
            text = f"факт {i} о смене embedding-провайдера"
        cursor = await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (?, ?, 'chat_history', ?)", (101, text, now))
        fid = int(cursor.lastrowid)
        await db.db.execute(
            "INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, "
            "expires_at, embedding) VALUES (?, ?, ?, 'chat_history', NULL, ?)",
            (fid, fid, 101, json.dumps(_unit(f"old|{text}"))))
        ids.append(fid)
    await db.db.commit()
    return ids


# ── 1. MSI is the admission criterion; PCI is provenance ───────────────────

def test_live_msi_is_reproduced_from_model_and_dims():
    assert ecp.model_space_identity(model=MODEL, dimension=DIMS) == LIVE_MSI


def test_same_space_without_canary_is_instant_compatible():
    space = ecp.model_space_identity(model=MODEL, dimension=DIMS)
    assert ecp.classify_identity_compatibility(
        current_identity="pci-apinet", stored_identity="pci-google",
        current_dim=DIMS, stored_dim=DIMS,
        current_space=space, stored_space=space,
        canary_verdict=None) == ecp.COMPAT_INSTANT


def test_historical_pci_keyed_admission_is_reused_by_msi():
    space = ecp.model_space_identity(model=MODEL, dimension=DIMS)
    adm = ecp.parse_admission(ecp.format_admission(
        space, "a" * 16, 12, 1.0, 1.0, 1.0, int(time.time())))
    assert adm is not None
    # PCI differs (google conn), MSI is the same → admission valid by MSI.
    assert ecp.admission_valid(
        adm, space_now=space, conn_now="b" * 16) is True
    assert ecp.parse_admission(ecp.format_admission(
        "c" * 16, "a" * 16, 12, 1.0, 1.0, 1.0, int(time.time()))) is not None
    assert ecp.admission_valid(
        adm, space_now="c" * 16, conn_now="b" * 16) is False


@pytest.mark.asyncio
async def test_same_msi_different_pci_writes_and_semantic_search(
        vec0_db, monkeypatch):
    """Primary apinet 503 → Google fallback 200: same MSI e540, different PCI
    → vector row written and found by semantic KNN; primary recovery keeps it."""
    _three_slots(monkeypatch, labels=(
        "primary:apinet_paid,fallback_1:google_free_1,"
        "fallback_2:google_free_2"))
    await _register_active(vec0_db, fingerprint="old-gateway-fp",
                           provider="generativelanguage.test")
    facts = json.dumps([{"subject": "s0", "predicate": "p",
                         "object": "o0"}], ensure_ascii=False)
    llm = FakeEmbedLLM(facts, script=["server_error", "ok", "ok"])
    memory = await _memory(vec0_db, llm)

    assert await memory._vec_write_allowed(INDEX) is True
    await memory.memorize_facts(-100, "текст", "web_content")

    assert [c["key"] for c in llm.calls][:2] == ["k-primary", "k-fb1"]
    assert await _count(vec0_db, "graph_facts") == 1
    assert await _count(vec0_db, "graph_facts_vec") == 1
    first_id = (await (await vec0_db.db.execute(
        "SELECT id FROM graph_facts")).fetchone())["id"]
    assert first_id in await _semantic_ids(vec0_db, llm._vec("s0 p o0"))
    # A successful 200 is not "restored memory" unless the vector row and
    # semantic hit exist — both asserted above.
    assert await memory._serving_route_write_allowed(INDEX) is True

    # Primary recovers: new fact uses primary; old vector is not lost.
    ecp.REGISTRY.reset_runtime()
    llm.facts_json = json.dumps(
        [{"subject": "s1", "predicate": "p", "object": "o1"}],
        ensure_ascii=False)
    llm.script = ["ok"]
    await memory.memorize_facts(-100, "текст 2", "web_content")
    assert await _count(vec0_db, "graph_facts_vec") == 2
    assert first_id in await _semantic_ids(vec0_db, llm._vec("s0 p o0"))


@pytest.mark.asyncio
async def test_text_only_backfill_recovers_via_same_msi_fallback(
        vec0_db, monkeypatch):
    """All legs down → fact text-only; when fallback returns, the existing
    backfill writes via the same-MSI fallback without duplicates."""
    _three_slots(monkeypatch, labels=(
        "primary:apinet_paid,fallback_1:google_free_1,"
        "fallback_2:google_free_2"))
    await _register_active(vec0_db, fingerprint="old-gateway-fp")
    facts = json.dumps([{"subject": "s0", "predicate": "p",
                         "object": "o0"}], ensure_ascii=False)
    llm = FakeEmbedLLM(facts, script=["server_error"] * 10)
    memory = await _memory(vec0_db, llm)
    await memory.memorize_facts(-100, "текст", "web_content")
    assert await _count(vec0_db, "graph_facts") == 1
    assert await _count(vec0_db, "graph_facts_vec") == 0

    # Fallback recovered; primary remains down in this call. Existing backfill
    # must use the admitted same-MSI fallback and write exactly one row.
    ecp.REGISTRY.reset_runtime()
    llm.script = ["server_error"]
    processed = await memory.backfill_graph_fact_vectors()
    assert processed == 1
    assert await _count(vec0_db, "graph_facts_vec") == 1
    assert await memory.backfill_graph_fact_vectors() == 0
    assert await _count(vec0_db, "graph_facts_vec") == 1
    fact_id = (await (await vec0_db.db.execute(
        "SELECT id FROM graph_facts")).fetchone())["id"]
    assert fact_id in await _semantic_ids(vec0_db, llm._vec("s0 p o0"))


# ── 2. Real incompatibility remains blocked ────────────────────────────────

@pytest.mark.asyncio
async def test_different_msi_is_text_only(vec0_db, monkeypatch, caplog):
    _three_slots(monkeypatch, labels=(
        "primary:apinet_paid,fallback_1:google_free_1"))
    await _register_active(vec0_db, fingerprint="other-space-fp",
                           model=OTHER_MODEL)
    facts = json.dumps([{"subject": "s0", "predicate": "p",
                         "object": "o0"}], ensure_ascii=False)
    llm = FakeEmbedLLM(facts, script=["server_error", "ok"])
    memory = await _memory(vec0_db, llm)

    compat = await ecp.resolve_index_compat(
        vec0_db, INDEX, current_fp=sm.embedding_identity_fingerprint(),
        current_dims=DIMS)
    assert compat["state"] == ecp.STATE_INCOMPATIBLE
    assert compat["reason_code"] == "identity_changed"
    assert compat["serviceable"] is False
    assert await memory._vec_write_allowed(INDEX) is False

    with caplog.at_level(logging.WARNING):
        await memory.memorize_facts(-100, "текст", "web_content")
    # Dedup/read-path may still compute a vector, but no ACTIVE write occurs.
    assert await _count(vec0_db, "graph_facts") == 1
    assert await _count(vec0_db, "graph_facts_vec") == 0
    found = await vec0_db.search_graph_facts_fts(
        -100, '"s0"*', 5, int(time.time()) + 10)
    assert found, "text-only fact must remain searchable via FTS"
    cursor = await vec0_db.db.execute(
        "SELECT COUNT(*) AS c FROM embedding_cache WHERE text = ?",
        ("s0 p o0",))
    assert (await cursor.fetchone())["c"] == 0, "no cache bypass"


@pytest.mark.asyncio
async def test_dimension_mismatch_is_text_only(vec0_db, monkeypatch):
    _three_slots(monkeypatch)
    await _register_active(vec0_db, fingerprint="dim-mismatch-fp",
                           model=MODEL, dims=1536)
    facts = json.dumps([{"subject": "s0", "predicate": "p",
                         "object": "o0"}], ensure_ascii=False)
    llm = FakeEmbedLLM(facts, script=["server_error", "ok"])
    memory = await _memory(vec0_db, llm)

    compat = await ecp.resolve_index_compat(
        vec0_db, INDEX, current_fp=sm.embedding_identity_fingerprint(),
        current_dims=DIMS)
    assert compat["state"] == ecp.STATE_INCOMPATIBLE
    assert compat["reason_code"] == "dimension_changed"
    assert await memory._vec_write_allowed(INDEX) is False
    await memory.memorize_facts(-100, "текст", "web_content")
    assert await _count(vec0_db, "graph_facts_vec") == 0


@pytest.mark.asyncio
async def test_canary_drift_still_blocks_same_msi(vec0_db, monkeypatch):
    _three_slots(monkeypatch)
    await _register_active(vec0_db, fingerprint="old-gateway-fp")
    fp = sm.embedding_identity_fingerprint()
    ecp.note_canary_verdict(fp, ecp.CANARY_DRIFT)
    facts = json.dumps([{"subject": "s0", "predicate": "p",
                         "object": "o0"}], ensure_ascii=False)
    llm = FakeEmbedLLM(facts, script=["server_error", "ok"])
    memory = await _memory(vec0_db, llm)
    assert await memory._vec_write_allowed(INDEX) is False
    await memory.memorize_facts(-100, "текст", "web_content")
    assert await _count(vec0_db, "graph_facts_vec") == 0


# ── 3. No MSI metadata: one bounded probe on stored old vectors ────────────

def _probe_embed(space: str):
    calls = []

    async def _fn(texts):
        calls.append(list(texts))
        return [_unit(f"{space}|{t}") for t in texts]

    return _fn, calls


@pytest.mark.asyncio
async def test_no_msi_probe_success_persists_msi_admission(vec0_db,
                                                          monkeypatch):
    _three_slots(monkeypatch, labels=(
        "primary:apinet_paid,fallback_1:google_free_1"))
    memory = await _memory(vec0_db, FakeEmbedLLM())
    await _seed_old_vectors(vec0_db, memory, n=12)
    await _register_active(vec0_db, fingerprint="legacy-fp",
                           model=None, dims=None, provider="legacy")
    current_fp = sm.embedding_identity_fingerprint()
    space = ecp.model_space_identity(model=MODEL, dimension=DIMS)
    probe, calls = _probe_embed("old")

    resolved = await ecp.resolve_index_compat(
        vec0_db, INDEX, current_fp=current_fp, current_dims=DIMS)
    assert resolved["needs_probe"] is True
    assert resolved["state"] == ecp.STATE_INSUFFICIENT

    result = await ecp.ensure_index_compat(
        vec0_db, INDEX, current_fp=current_fp, current_dims=DIMS,
        embed_fn=probe, force_probe=True)
    assert result["state"] == ecp.STATE_COMPATIBLE
    assert len(calls) == 1, "exactly one bounded probe"
    active = await vec0_db.get_active_embedding_generation(INDEX)
    admission = ecp.parse_admission(active["config_revision"])
    assert admission is not None and admission["space"] == space
    assert admission["checked"] >= ecp.COMPAT_PROBE_MIN_SAMPLE
    assert ecp.admission_valid(
        admission, space_now=space,
        conn_now=ecp.connection_identity(
            ecp.resolve_embedding_profiles()["fallback_1"])) is True

    facts = json.dumps([{"subject": "s9", "predicate": "p",
                         "object": "o9"}], ensure_ascii=False)
    llm = FakeEmbedLLM(facts, script=["server_error", "ok", "ok"])
    memory.llm = llm
    assert await memory._vec_write_allowed(INDEX) is True
    await memory.memorize_facts(-100, "новый текст", "web_content")
    assert await _count(vec0_db, "graph_facts_vec") == 13
    new_id = (await (await vec0_db.db.execute(
        "SELECT id FROM graph_facts ORDER BY id DESC LIMIT 1")).fetchone())["id"]
    assert new_id in await _semantic_ids(vec0_db, llm._vec("s9 p o9"))


@pytest.mark.asyncio
async def test_no_msi_probe_failure_stays_text_only(vec0_db, monkeypatch):
    _three_slots(monkeypatch)
    memory = await _memory(vec0_db, FakeEmbedLLM())
    await _seed_old_vectors(vec0_db, memory, n=12)
    await _register_active(vec0_db, fingerprint="legacy-fp",
                           model=None, dims=None, provider="legacy")
    current_fp = sm.embedding_identity_fingerprint()
    probe, calls = _probe_embed("different-space")

    result = await ecp.ensure_index_compat(
        vec0_db, INDEX, current_fp=current_fp, current_dims=DIMS,
        embed_fn=probe, force_probe=True)
    assert result["state"] == ecp.STATE_INCOMPATIBLE
    assert len(calls) == 1, "no probe loops"
    active = await vec0_db.get_active_embedding_generation(INDEX)
    assert ecp.parse_admission(active["config_revision"]) is None

    facts = json.dumps([{"subject": "s9", "predicate": "p",
                         "object": "o9"}], ensure_ascii=False)
    llm = FakeEmbedLLM(facts, script=["server_error", "ok"])
    memory.llm = llm
    assert await memory._vec_write_allowed(INDEX) is False
    await memory.memorize_facts(-100, "новый текст", "web_content")
    assert await _count(vec0_db, "graph_facts") == 13
    assert await _count(vec0_db, "graph_facts_vec") == 12
