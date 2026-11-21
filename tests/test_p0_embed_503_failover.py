"""P0 EMBED-503-FAILOVER (owner 22.11.2026) — реальный failover 5xx/timeout.

Прод-дефект на 2.58.228: `EmbeddingExecutor._pick_credential()` всегда брал
первый healthy credential, а `_on_error()` для 5xx/timeout возвращал
`transport`, не исключая отказавшую ногу. Следующая попытка снова шла в тот
же primary (apinet 503), Google fallback'и не вызывались; бюджет 4
расходовался на неизменённый endpoint.

Контракт исправления (минимальный, в существующем control plane):
  * 5xx/timeout помечает отказавшую НЕЗАВИСИМУЮ ногу недоступной для ТЕКУЩЕЙ
    операции → следующая попытка идёт на следующий пригодный slot;
  * при повторе отказа слот коротко паркуется в существующем credential
    health (cooldown, НЕ второй breaker) — следующий запрос не бомбит
    сломанный шлюз, после истечения cooldown primary снова пробуется;
  * bounded retry/backoff и budget≤4 сохранены (единственная нога —
    прежнее поведение, не бесконечный спин);
  * 401/403 не выводят независимые слоты; 429 уважает group cooldown;
  * все ключи отсутствуют → один legacy-вызов/понятный отказ, не каскад.

Identity (MSI/canary/dim/generation/adoption) не меняется этим seam'ом:
совместимость/запись в ACTIVE проверяются существующими гейтами
summary_memory (см. test_embed_identity_compat.py); несовместимый вектор
остаётся text-only + FTS.

TEST-LIFECYCLE: REGRESSION owner=P0-EMBED-503-FAILOVER/A (дефект failover).
"""
import json
import time

import pytest
import pytest_asyncio

from services import embedding_control_plane as ecp
from services.database import DatabaseService
from services.embedding_control_plane import (
    AdaptiveController, EmbeddingBudgetExhausted, EmbeddingExecutor,
    Priority, QuotaGroupRegistry,
)
from services.llm_client import (
    LLMAuthError, LLMError, LLMRateLimitError, LLMServerError, LLMTimeoutError,
)
from services.summary_memory import FACT_EXTRACT_PROMPT, MemoryManager

pytestmark = pytest.mark.asap4

PRIMARY_BASE = "https://apinet.test/v1"
PRIMARY_MODEL = "gemini-embedding-001"
FB1_BASE = "https://generativelanguage.test/v1beta/openai"
FB1_MODEL = "gemini-embedding-001"
FB2_BASE = "https://google-second.test/v1beta/openai"
FB2_MODEL = "gemini-embedding-001"


@pytest.fixture(autouse=True)
def fresh_ecp(monkeypatch):
    """Чистые singleton'ы + нулевой transport backoff (без снов)."""
    ecp.REGISTRY = QuotaGroupRegistry()
    ecp.CONTROLLER = AdaptiveController()
    ecp.SCHEDULER = ecp.PriorityScheduler()
    ecp.EXECUTOR = None
    ecp._last_rotation_warn = 0.0
    ecp._last_primary_warn = 0.0
    ecp._last_state_log.clear()
    if hasattr(ecp, "clear_last_served_credential"):
        ecp.clear_last_served_credential()
    monkeypatch.setattr(ecp, "_TRANSPORT_BACKOFF_BASE", 0.0)
    yield ecp


def _isolate(monkeypatch, values):
    """hot-слой = только заданные ключи; env EMBEDDING_* погашен в "".

    Патчится и `summary_memory.hot` (тот же hot_config): identity-fingerprint
    и route-admission читают configured model/base_url/dim из него.
    """
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
    from services import hot_config
    monkeypatch.setattr(
        hot_config, "get",
        lambda key, default=None: values.get(key, default))


def _three_slots(monkeypatch, labels=""):
    values = {
        "keys.embedding_api_key": "k-primary",
        "keys.embedding_fallback_api_key": "k-fb1",
        "keys.embedding_fallback_api_key_2": "k-fb2",
        "models.embedding_base_url": PRIMARY_BASE,
        "models.embedding_model_name": PRIMARY_MODEL,
        "models.embedding_dim": 4,
        "models.embedding_fallback1_base_url": FB1_BASE,
        "models.embedding_fallback1_model": FB1_MODEL,
        "models.embedding_fallback2_base_url": FB2_BASE,
        "models.embedding_fallback2_model": FB2_MODEL,
        "keys.embedding_quota_group_labels": labels,
    }
    _isolate(monkeypatch, values)
    return values


class RecordingLLM:
    """Фиксирует фактический credential/endpoint каждого HTTP-вызова."""

    def __init__(self, script=None, dim=4):
        self._embed_model = PRIMARY_MODEL
        self.script = list(script or [])
        self.calls = []
        self.legacy_calls = 0
        self.dim = dim

    async def embed_once(self, texts, *, api_key, base_url=None, model=None,
                         max_retries=0, retry_statuses=()):
        self.calls.append({"key": api_key, "base_url": base_url,
                           "model": model, "texts": list(texts)})
        behavior = self.script.pop(0) if self.script else "ok"
        if behavior == "server_error":
            raise LLMServerError("LLM server error 503: " + str(base_url))
        if behavior == "timeout":
            raise LLMTimeoutError("LLM request timed out after 1 attempts")
        if behavior == "auth":
            raise LLMAuthError("LLM auth failed (401)")
        if behavior == "rate_limit":
            exc = LLMRateLimitError("LLM rate limited (429)")
            exc.headers = {"Retry-After": "5"}
            exc.body = ""
            raise exc
        return [[0.1 + i * 0.01 for i in range(self.dim)] for _ in texts]

    async def embed(self, texts):
        self.legacy_calls += 1
        if self.script:
            behavior = self.script.pop(0)
            if behavior == "legacy_error":
                raise LLMError("no embedding credential configured")
        return [[0.1] * self.dim for _ in texts]


# ── 1. 5xx/timeout primary → fallback_1 → fallback_2 ────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["server_error", "timeout"])
async def test_primary_5xx_does_not_burn_all_attempts(monkeypatch, failure):
    """RED на 2.58.228: все 4 попытки уходили в primary, fallback не звался."""
    _three_slots(monkeypatch)
    llm = RecordingLLM(script=[failure, "ok"])
    executor = EmbeddingExecutor(llm)
    vectors = await executor.embed(["текст"], priority=Priority.P1_WRITE)
    assert len(vectors) == 1 and len(vectors[0]) == llm.dim
    assert [c["key"] for c in llm.calls] == ["k-primary", "k-fb1"]
    assert llm.calls[0]["base_url"] == PRIMARY_BASE
    assert llm.calls[1]["base_url"] == FB1_BASE


@pytest.mark.asyncio
async def test_all_legs_5xx_tries_each_independent_leg_once(monkeypatch):
    """primary/fallback_1 fallback_2 по одному разу, затем text-only отказ."""
    _three_slots(monkeypatch)
    llm = RecordingLLM(script=["server_error"] * 10)
    executor = EmbeddingExecutor(llm)
    with pytest.raises(EmbeddingBudgetExhausted):
        await executor.embed(["текст"], priority=Priority.P1_WRITE)
    assert [c["key"] for c in llm.calls] == ["k-primary", "k-fb1", "k-fb2"]
    assert [c["base_url"] for c in llm.calls] == [
        PRIMARY_BASE, FB1_BASE, FB2_BASE]
    # Все три ноги кратко припаркованы в СУЩЕСТВУЮЩЕМ credential health
    # (не второй breaker) → немедленный повторный запрос не бьёт шлюз.
    for alias in ("primary", "fallback_1", "fallback_2"):
        assert ecp.REGISTRY.credential_health(alias) == "cooldown"
        assert ecp.REGISTRY.credential_cooldown_until(alias) > 0
    calls_after_first = len(llm.calls)
    with pytest.raises(EmbeddingBudgetExhausted) as excinfo:
        await executor.embed(["текст"], priority=Priority.P1_WRITE)
    assert "no usable embedding credential" in str(excinfo.value)
    assert len(llm.calls) == calls_after_first
    assert llm.legacy_calls == 0


@pytest.mark.asyncio
async def test_primary_recovery_probe_after_cooldown(monkeypatch):
    """После короткой парковки primary снова пробуется ограниченной попыткой."""
    _three_slots(monkeypatch)
    monkeypatch.setattr(ecp, "_PROVIDER_UNAVAILABLE_COOLDOWN_S", 0.0)
    llm = RecordingLLM(script=["server_error", "server_error",
                               "server_error", "ok"])
    executor = EmbeddingExecutor(llm)
    with pytest.raises(EmbeddingBudgetExhausted):
        await executor.embed(["a"], priority=Priority.P1_WRITE)
    assert [c["key"] for c in llm.calls] == ["k-primary", "k-fb1", "k-fb2"]
    # Cooldown истёк → следующий logical request снова идёт в primary.
    vectors = await executor.embed(["b"], priority=Priority.P1_WRITE)
    assert len(vectors) == 1
    assert llm.calls[-1]["key"] == "k-primary"


@pytest.mark.asyncio
async def test_single_credential_keeps_bounded_retry(monkeypatch):
    """Единственная нога: budget≤4 сохранён (не ранний отказ после 503)."""
    _isolate(monkeypatch, {
        "keys.embedding_api_key": "k-only",
        "models.embedding_base_url": PRIMARY_BASE,
        "models.embedding_model_name": PRIMARY_MODEL,
    })
    llm = RecordingLLM(script=["server_error"] * 10)
    executor = EmbeddingExecutor(llm)
    with pytest.raises(EmbeddingBudgetExhausted):
        await executor.embed(["x"], priority=Priority.P1_WRITE)
    assert [c["key"] for c in llm.calls] == ["k-only"] * 4


# ── 2. 401/403, 429, отсутствие ключей — прежние независимые контракты ──────

@pytest.mark.asyncio
async def test_auth_error_does_not_park_independent_slots(monkeypatch):
    """401 = auth_failed ЭТОГО credential'а; независимые слоты не выводятся."""
    _three_slots(monkeypatch)
    llm = RecordingLLM(script=["auth", "ok"])
    executor = EmbeddingExecutor(llm)
    with pytest.raises(LLMAuthError):
        await executor.embed(["a"], priority=Priority.P1_WRITE)
    assert ecp.REGISTRY.credential_health("primary") == "auth_failed"
    assert ecp.REGISTRY.credential_health("fallback_1") == "healthy"
    assert ecp.REGISTRY.credential_health("fallback_2") == "healthy"
    vectors = await executor.embed(["b"], priority=Priority.P1_WRITE)
    assert len(vectors) == 1
    assert llm.calls[-1]["key"] == "k-fb1"


@pytest.mark.asyncio
async def test_429_respects_group_cooldown_and_next_group(monkeypatch):
    """429 primary → group cooldown; следующий вызов идёт в независимую ногу."""
    _three_slots(monkeypatch)
    llm = RecordingLLM(script=["rate_limit", "ok"])
    executor = EmbeddingExecutor(llm)
    vectors = await executor.embed(["a"], priority=Priority.P1_WRITE,
                                   max_wait_s=0.0)
    assert len(vectors) == 1
    assert [c["key"] for c in llm.calls] == ["k-primary", "k-fb1"]
    assert ecp.REGISTRY.group_state("primary").state == "cooling_down"
    assert ecp.REGISTRY.group_state("primary").next_allowed_at > 0
    # Транспортная парковка 429-слот не добавляет: это quota signal.
    assert ecp.REGISTRY.credential_health("primary") == "cooldown"


@pytest.mark.asyncio
async def test_all_keys_absent_is_single_legacy_refusal(monkeypatch):
    """Ключей нет → один legacy-вызов и понятная ошибка, без каскада."""
    _isolate(monkeypatch, {})
    llm = RecordingLLM(script=["legacy_error"])
    executor = EmbeddingExecutor(llm)
    with pytest.raises(LLMError, match="no embedding credential"):
        await executor.embed(["x"], priority=Priority.P1_WRITE)
    assert llm.legacy_calls == 1
    assert llm.calls == []


# ── 3. E2E: все ноги 503 → text-only/FTS → recovery/backfill без дублей ────

class FactsRecordingLLM(RecordingLLM):
    """Живой MemoryManager-вход: facts-JSON + тот же embed_once-контракт."""

    def __init__(self, facts_json, script=None, dim=4):
        super().__init__(script=script, dim=dim)
        self.facts_json = facts_json

    async def generate(self, messages):
        if messages and messages[0].get("content") == FACT_EXTRACT_PROMPT:
            return self.facts_json
        return "[]"


@pytest_asyncio.fixture
async def vec_db(tmp_path):
    db = DatabaseService(str(tmp_path / "p0-embed-failover.db"))
    await db.initialize()
    # Плоская vec-таблица вместо sqlite-vec: контракт записи/идемпотентности
    # проверяется без расширения (прецедент test_asap44_graphrag_batch_breaker).
    await db.db.execute(
        "CREATE TABLE IF NOT EXISTS graph_facts_vec ("
        "rowid INTEGER PRIMARY KEY, fact_id INTEGER, chat_id INTEGER, "
        "origin TEXT, expires_at INTEGER, embedding TEXT)")
    await db.db.commit()
    yield db
    ecp.REGISTRY.bind_db(None)
    if hasattr(ecp, "clear_last_served_credential"):
        ecp.clear_last_served_credential()
    await db.close()


async def _count(db, table):
    cursor = await db.db.execute(f"SELECT COUNT(*) AS c FROM {table}")
    return int((await cursor.fetchone())["c"])


@pytest.mark.asyncio
async def test_all_legs_down_saves_text_only_then_recovers_backfill(
        vec_db, monkeypatch):
    """DoD A: все три ноги 503 → факты в FTS/source без векторов; после
    восстановления backfill пишет векторы, повторный backfill идемпотентен."""
    _three_slots(monkeypatch)
    # cooldown 0 → следующий logical request снова пробует primary уже в
    # этом тесте (роутинг/парковка проверены отдельными тестами выше).
    monkeypatch.setattr(ecp, "_PROVIDER_UNAVAILABLE_COOLDOWN_S", 0.0)
    facts = json.dumps([
        {"subject": "s0", "predicate": "p", "object": "o0"},
        {"subject": "s1", "predicate": "p", "object": "o1"},
    ], ensure_ascii=False)
    llm = FactsRecordingLLM(facts, script=["server_error"] * 10)
    memory = MemoryManager(vec_db, llm)
    memory._vec_available = True
    memory._vec_int8 = False
    memory._vec_dim = 4

    await memory.memorize_facts(-100, "текст", "web_content")

    # Все три независимые ноги попробованы (batch breaker: второй факт
    # batch уже не ходит в сеть), текст сохранён, вектора нет.
    assert [c["key"] for c in llm.calls] == ["k-primary", "k-fb1", "k-fb2"]
    assert await _count(vec_db, "graph_facts") == 2
    assert await _count(vec_db, "graph_facts_vec") == 0
    found = await vec_db.search_graph_facts_fts(
        -100, '"s0"*', 5, int(time.time()) + 10)
    assert found, "text-only факт обязан находиться через FTS"

    # Восстановление: primary снова отвечает → bounded backfill без дублей.
    llm.script.clear()
    processed = await memory.backfill_graph_fact_vectors()
    assert processed == 2
    assert await _count(vec_db, "graph_facts_vec") == 2
    assert await memory.backfill_graph_fact_vectors() == 0
    assert await _count(vec_db, "graph_facts_vec") == 2
    assert llm.calls[-1]["key"] == "k-primary"
