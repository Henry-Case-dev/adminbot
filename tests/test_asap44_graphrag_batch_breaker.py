"""ASAP 4.4 Z6 — GraphRAG batch circuit breaker + quota groups
(T-4878–T-4880, §6 tests #19–#24).

Покрытие:
  #19 EmbeddingGroupCoolingDown на первом факте → ≤1 network embed-attempt
      на весь logical batch (test_graphrag_memory: было ~2/факт);
  #20 остальные факты batch сохранены text-only (graph_facts есть, vec — 0);
  #21 ровно ОДИН concise WARN/event на batch, без N stacktrace; unexpected
      exception по-прежнему со stacktrace;
  #22 следующий logical batch после recovery снова embeds;
  #23 quota-group labels корректно разделяют независимые группы (группа —
      ТОЛЬКО из label, не из значения ключа);
  #24 unknown groups схлопываются в одну safe group.
  + UI/catalog: ключ `keys.embedding_quota_group_labels` каталогизирован и
      есть в Embeddings-группе MiniApp; Status-панель рендерит
      rotation/groups/next_allowed_at без секретов.

Сеть/провайдер не вызываются: `_embed` инжектируется; pool строится из
patched hot-источника. R17: только коды/числа/алиасы.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import pytest

from config.settings import settings
from services import embedding_control_plane as ecp
from services import param_catalog as pc
from services.database import DatabaseService
from services.summary_memory import FACT_EXTRACT_PROMPT, MemoryManager

pytestmark = [pytest.mark.asap4]

CHAT_ID = -100777
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_memorize_state():
    import services.summary_memory as sm
    sm._memorize_warn_state.clear()
    sm._memorize_lost_totals.clear()
    yield
    sm._memorize_warn_state.clear()
    sm._memorize_lost_totals.clear()


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _facts_json(count, *, offset=0):
    return json.dumps([
        {"subject": f"s{offset + i}", "predicate": "p",
         "object": f"o{offset + i}"}
        for i in range(count)
    ], ensure_ascii=False)


class FactsLLM:
    def __init__(self, response):
        self.response = response
        self.generate_calls = 0

    async def generate(self, messages):
        self.generate_calls += 1
        if messages[0]["content"] == FACT_EXTRACT_PROMPT:
            return self.response
        return "[]"

    async def embed(self, texts):        # реальный канал не используется
        raise AssertionError("network embed must not be called")


class _CoolingStub:
    """_embed всегда отдаёт control-plane cooldown; считает вызовы."""

    def __init__(self, *, group_id="g1", next_allowed_at=None):
        self.calls = 0
        self.group_id = group_id
        self.next_allowed_at = next_allowed_at or int(time.time()) + 3600

    async def __call__(self, texts, *, priority=None):
        self.calls += 1
        raise ecp.EmbeddingGroupCoolingDown(
            group_id=self.group_id, next_allowed_at=self.next_allowed_at)


class _RecoverAfterFirstStub:
    """Первый вызов — cooldown (или ошибка из state), дальше — успех."""

    def __init__(self):
        self.calls = 0
        self.state = "cooling"

    async def __call__(self, texts, *, priority=None):
        self.calls += 1
        if self.state == "cooling":
            self.state = "ok"
            raise ecp.EmbeddingGroupCoolingDown(
                group_id="g1", next_allowed_at=int(time.time()) + 60)
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


def _memory(db, facts_count=3):
    llm = FactsLLM(_facts_json(facts_count))
    memory = MemoryManager(db, llm)
    memory._vec_available = True
    memory._vec_int8 = False
    return memory


_VEC_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS graph_facts_vec ("
    "rowid INTEGER PRIMARY KEY, fact_id INTEGER, chat_id INTEGER, "
    "origin TEXT, expires_at INTEGER, embedding TEXT)")


async def _memory_ready(db, facts_count=3):
    """MemoryManager + плоская graph_facts_vec (без sqlite-vec расширения)."""
    await db.db.execute(_VEC_TABLE_SQL)
    await db.db.commit()
    return _memory(db, facts_count)


async def _count(db, table):
    cursor = await db.db.execute(f"SELECT COUNT(*) AS c FROM {table}")
    row = await cursor.fetchone()
    return int(row["c"])


# ══ #19/#20 — batch breaker: ≤1 attempt, все факты text-only ═══════════════

@pytest.mark.asyncio
async def test_19_cooldown_single_embed_attempt_per_batch(db, monkeypatch):
    memory = await _memory_ready(db, facts_count=3)
    stub = _CoolingStub()
    monkeypatch.setattr(memory, "_embed", stub)
    await memory.memorize_facts(CHAT_ID, "текст", "web_content")
    assert stub.calls == 1                     # было ~2/факт = 6
    assert await _count(db, "graph_facts") == 3
    assert await _count(db, "graph_facts_vec") == 0


@pytest.mark.asyncio
async def test_20_all_facts_saved_text_only(db, monkeypatch, caplog):
    memory = await _memory_ready(db, facts_count=4)
    stub = _CoolingStub()
    monkeypatch.setattr(memory, "_embed", stub)
    with caplog.at_level(logging.INFO):
        await memory.memorize_facts(CHAT_ID, "текст", "web_content")
    assert await _count(db, "graph_facts") == 4
    assert await _count(db, "graph_facts_vec") == 0
    cursor = await db.db.execute("SELECT fact FROM graph_facts ORDER BY id")
    texts = [r["fact"] for r in await cursor.fetchall()]
    assert texts == [f"s{i} p o{i}" for i in range(4)]
    # один batch-event с honest-полями (не per-fact спам)
    batch = [r for r in caplog.records if "embedding unavailable" in r.message]
    assert len(batch) == 1
    assert "chat_id=%s" % CHAT_ID in batch[0].getMessage() or \
        str(CHAT_ID) in batch[0].getMessage()


# ══ #21 — один concise WARN, unexpected — со stacktrace ════════════════════

@pytest.mark.asyncio
async def test_21_one_concise_warn_not_n_stacktraces(db, monkeypatch, caplog):
    memory = await _memory_ready(db, facts_count=3)
    stub = _CoolingStub()
    monkeypatch.setattr(memory, "_embed", stub)
    with caplog.at_level(logging.WARNING):
        await memory.memorize_facts(CHAT_ID, "текст", "web_content")
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    batch_warns = [r for r in warnings if "embedding unavailable" in r.message]
    assert len(batch_warns) == 1
    assert batch_warns[0].exc_info is None
    # старый per-fact stacktrace-спам отсутствует
    assert not [r for r in warnings if "embed failed" in r.message]
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_21b_unexpected_exception_still_has_stacktrace(
        db, monkeypatch, caplog):
    memory = await _memory_ready(db, facts_count=1)

    async def boom(texts, *, priority=None):
        raise RuntimeError("unexpected boom")

    monkeypatch.setattr(memory, "_embed", boom)
    with caplog.at_level(logging.WARNING):
        await memory.memorize_facts(CHAT_ID, "текст", "web_content")
    with_trace = [r for r in caplog.records
                  if r.levelno >= logging.WARNING and r.exc_info is not None]
    assert with_trace, "unexpected exception must stay visible with stacktrace"
    # факт сохранён text-only (fail-soft не сломан)
    assert await _count(db, "graph_facts") == 1


# ══ #22 — следующий batch после recovery снова embeds ═══════════════════════

@pytest.mark.asyncio
async def test_22_next_batch_embeds_after_recovery(db, monkeypatch):
    memory = await _memory_ready(db, facts_count=3)
    stub = _RecoverAfterFirstStub()
    monkeypatch.setattr(memory, "_embed", stub)
    await memory.memorize_facts(CHAT_ID, "batch 1", "web_content")
    assert stub.calls == 1
    assert await _count(db, "graph_facts") == 3
    assert await _count(db, "graph_facts_vec") == 0
    # Следующий logical batch — новый breaker + serviceability recheck.
    memory.llm.response = _facts_json(3, offset=10)
    await memory.memorize_facts(CHAT_ID, "batch 2", "web_content")
    assert await _count(db, "graph_facts") == 6
    assert await _count(db, "graph_facts_vec") == 3     # batch 2 снова embed'ится
    assert stub.calls == 4                              # 1 сгоревший + 3 dedup


# ══ #23/#24 — quota-group labels ════════════════════════════════════════════

def _patch_pool_source(monkeypatch, *, labels, keys=("k1", "k2", "k3")):
    values = {
        "models.embedding_base_url": "https://api.example.com/v1",
        "models.embedding_model_name": "embed-x",
        "keys.embedding_api_key": keys[0],
        "keys.embedding_fallback_api_key": keys[1],
        "keys.embedding_fallback_api_key_2": keys[2],
        "keys.embedding_quota_group_labels": labels,
    }
    monkeypatch.setattr(ecp, "_hot_get", lambda key, default: values.get(
        key, default))
    monkeypatch.setattr(ecp, "_settings_value", lambda name, default: "")


def test_23_labels_split_truly_independent_groups(monkeypatch):
    _patch_pool_source(monkeypatch,
                       labels="primary:alpha,fallback_1:beta,"
                              "fallback_2:beta")
    pool = ecp.build_credential_pool()
    by_alias = {c.alias: c.quota_group_id for c in pool}
    assert by_alias == {"primary": "alpha", "fallback_1": "beta",
                        "fallback_2": "beta"}
    diagnosis = ecp.pool_rotation_diagnosis(pool)
    assert diagnosis["groups"] == ["alpha", "beta"]
    assert diagnosis["degenerate"] is False
    panel = ecp._rotation_panel_block(diagnosis)
    assert panel["status"] == "grouped" and panel["keys"] == 3


def test_23b_grouping_never_derived_from_secret_values(monkeypatch):
    labels = "primary:alpha,fallback_1:beta,fallback_2:beta"
    _patch_pool_source(monkeypatch, labels=labels,
                       keys=("zzz1", "zzz2", "zzz3"))
    first = {c.alias: c.quota_group_id
             for c in ecp.build_credential_pool()}
    _patch_pool_source(monkeypatch, labels=labels,
                       keys=("different", "different", "different"))
    second = {c.alias: c.quota_group_id
              for c in ecp.build_credential_pool()}
    assert first == second                       # только label, не секрет
    labels2 = "primary:one,fallback_1:one,fallback_2:one"
    _patch_pool_source(monkeypatch, labels=labels2,
                       keys=("same", "same", "same"))
    third = {c.alias: c.quota_group_id
             for c in ecp.build_credential_pool()}
    assert set(third.values()) == {"one"}        # один project → одна group


def test_24_unknown_groups_collapse_to_one_safe_group(monkeypatch):
    _patch_pool_source(monkeypatch, labels="")
    pool = ecp.build_credential_pool()
    groups = {c.quota_group_id for c in pool}
    assert groups == {ecp.UNKNOWN_GROUP_ID}      # одна общая safe-группа
    diagnosis = ecp.pool_rotation_diagnosis(pool)
    assert diagnosis["degenerate"] is True
    assert diagnosis["groups"] == [ecp.UNKNOWN_GROUP_ID]
    # Частичные labels: незнанные aliases — та же ОДНА unknown-группа.
    _patch_pool_source(monkeypatch, labels="primary:alpha")
    pool2 = ecp.build_credential_pool()
    by_alias = {c.alias: c.quota_group_id for c in pool2}
    assert by_alias["primary"] == "alpha"
    assert by_alias["fallback_1"] == ecp.UNKNOWN_GROUP_ID
    assert by_alias["fallback_2"] == ecp.UNKNOWN_GROUP_ID


def test_23c_saved_hot_value_reaches_credential_pool(monkeypatch):
    """Значение, записанное в ConfigCache (путь /api/config), реально
    подхватывается пулом без рестарта — save→runtime contract."""
    from services import hot_config
    hot_values = {
        "models.embedding_base_url": "https://api.example.com/v1",
        "models.embedding_model_name": "embed-x",
        "keys.embedding_api_key": "k1",
        "keys.embedding_fallback_api_key": "k2",
        "keys.embedding_fallback_api_key_2": "k3",
        "keys.embedding_quota_group_labels":
            "primary:alpha,fallback_1:beta,fallback_2:beta",
    }

    class _Cache:
        def get(self, key, default=None):
            return hot_values.get(key, default)

    monkeypatch.setattr(hot_config, "_cache", _Cache())
    monkeypatch.setattr(ecp, "_settings_value", lambda name, default: "")
    pool = ecp.build_credential_pool()
    assert {c.alias: c.quota_group_id for c in pool} == {
        "primary": "alpha", "fallback_1": "beta", "fallback_2": "beta"}


# ══ MiniApp/catalog + Status panel (T-4880) ═════════════════════════════════

def test_quota_group_labels_key_catalogued_and_in_embeddings_group():
    spec = pc.get_by_pg_key("keys.embedding_quota_group_labels")
    assert spec is not None
    assert spec.category == "keys"
    assert spec.secret is False
    assert spec.per_chat is False
    assert spec.type == "str"
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    start = app_js.index("id: 'embeddings'")
    end = app_js.index("id: 'intel_history'", start)
    assert "keys.embedding_quota_group_labels" in app_js[start:end]


def test_status_panel_renders_rotation_and_groups_without_secrets():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    block_start = html.index("embeddings-inspector-block")
    block_end = html.index("Интеллект и Память", block_start)
    block = html[block_start:block_end]
    assert "rotation" in block
    assert "next_allowed_at" in block
    assert "quota_group" in block
