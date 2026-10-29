"""EVOL-010 — embedding NameError → fake budget exhaustion → backfill stalls.

Контракт (`plans/features/evol/audit/base-revalidation.md`, ТЗ §3 EVOL-010):

* первопричина 2.58.141 — vestigial CANARY-03 `.set()` (`_LAST_EMBED_META`)
  без определения: детерминированный NameError после КАЖДОГО успешного
  embed-вызова → REGRESSION-тест успешного пути;
* программные ошибки (NameError/AttributeError/TypeError/KeyError/…) —
  честный НЕ-retryable терминал `EmbeddingCodeDefect`: НЕ транспорт, НЕ
  квота, бюджет попыток НЕ сжигается, `EmbeddingBudgetExhausted` НЕ
  синтезируется;
* transport-ошибки сохраняют retry-семантику; терминал исчерпания попыток —
  честный `EmbeddingRetriesExhausted` (compat-подкласс
  `EmbeddingBudgetExhausted`);
* нет usable credential — честный `EmbeddingNoUsableCredential`;
* backfill: обработанный батч (processed>0), детерминированный сбой —
  честный СТОП без вечного «deferred» и без зависания;
* «durable job missing» (F6, с 2.58.114): зомби-`building`-строка при
  пустом источнике → честный hint «source empty» + реконсиляция
  `superseded` (векторы/строки НЕ трогаются; новое поколение регистрируется
  штатно).

R17: логи/исключения не содержат значений ключей.

TEST-LIFECYCLE: CONTRACT owner=EVOL-010
"""
import logging

import pytest
import pytest_asyncio

from services import embedding_control_plane as ecp
from services.database import DatabaseService
from services.embedding_control_plane import (
    EmbeddingCodeDefect, EmbeddingExecutor, EmbeddingGroupCoolingDown,
    EmbeddingNoUsableCredential, EmbeddingRetriesExhausted, ExecutionStats,
    Priority, QuotaGroupRegistry, AdaptiveController, PriorityScheduler,
    is_serviceability_error,
)
from services.llm_client import LLMRateLimitError
from services.summary_memory import MemoryManager, _embed_fail_reason

pytestmark = pytest.mark.asap4      # control plane — прод-ON (семья ASAP-4)


# ── Fixtures / helpers (прецедент test_asap8_f8_embeddings) ─────────────────


@pytest.fixture(autouse=True)
def fresh_ecp(monkeypatch):
    """Чистые singleton'ы контрол-плейна + backoff=0 (без реальных снов)."""
    ecp.REGISTRY = QuotaGroupRegistry()
    ecp.CONTROLLER = AdaptiveController()
    ecp.SCHEDULER = PriorityScheduler()
    ecp.EXECUTOR = None
    ecp._last_state_log.clear()
    ecp._last_rotation_warn = 0.0
    for key in ("last_reprobe_ts", "last_recovery_ts", "last_backfill_ts",
                "last_processed_archive", "last_processed_graph"):
        ecp.BACKFILL_STATE[key] = 0
    ecp.BACKFILL_STATE["backlog_archive"] = None
    ecp.BACKFILL_STATE["backlog_graph"] = None
    monkeypatch.setattr(ecp, "_TRANSPORT_BACKOFF_BASE", 0.0)
    yield ecp


_patch_restore: list = []


@pytest.fixture(autouse=True)
def _restore_settings_patches():
    yield
    while _patch_restore:
        _patch_restore.pop()()


def _patch_setting(monkeypatch, name, value):
    """Патч frozen-Settings (класс + инстанс, оба модульных объекта) —
    прецедент test_embedding_control_plane_asap4._patch_setting."""
    import config.settings as cs
    import services.summary_memory as sm
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
                lambda old=old2, inst=inst2: object.__setattr__(inst2, name,
                                                                old))


def _patch_keys(monkeypatch, *, primary="key-primary", fb1=None, fb2=None):
    """Ключи пула через class-level settings (hot-хранилище теста пусто →
    default = settings) — прецедент test_asap8_f8_embeddings._patch_keys."""
    _patch_setting(monkeypatch, "EMBEDDING_API_KEY", primary or "")
    _patch_setting(monkeypatch, "EMBEDDING_FALLBACK_API_KEY", fb1 or "")
    _patch_setting(monkeypatch, "EMBEDDING_FALLBACK_API_KEY_2", fb2 or "")


class ScriptedLLM:
    """embed_once-контракт адаптера, сценарий по вызовам: 'ok' |
    'code_error' (NameError — точный прод-класс 2.58.141) | 'transport'
    (ConnectionError) | 'rate_limit' (429, RA=20s). R17: ключей не печатает."""

    def __init__(self, *, dim: int = 8, retry_after: float | None = 20.0):
        self._embed_model = "test-embed-model"
        self.script: list = []
        self.calls = 0
        self.dim = dim
        self.retry_after = retry_after

    async def embed_once(self, texts, *, api_key, base_url=None, model=None,
                         max_retries=0, retry_statuses=()):
        self.calls += 1
        behavior = self.script.pop(0) if self.script else "ok"
        if behavior == "code_error":
            raise NameError("name '_LAST_EMBED_META' is not defined")
        if behavior == "transport":
            raise ConnectionError("connection reset by peer")
        if behavior == "rate_limit":
            exc = LLMRateLimitError("LLM rate limited (429)")
            if self.retry_after is not None:
                exc.headers = {"Retry-After": str(self.retry_after)}
            exc.body = ""
            raise exc
        return [[0.5] * self.dim for _ in texts]


class VectorLLM:
    """Legacy embed-контракт (пустой пул → executor делегирует llm.embed)."""

    def __init__(self, *, dim: int = 8):
        self.dim = dim
        self.embed_calls = 0

    async def embed(self, texts):
        self.embed_calls += 1
        return [[0.5] * self.dim for _ in texts]


@pytest_asyncio.fixture
async def vec_db(tmp_path):
    pytest.importorskip("sqlite_vec")
    d = DatabaseService(str(tmp_path / "evol010.db"))
    await d.initialize()
    import sqlite_vec
    await d.db.enable_load_extension(True)
    await d.db.load_extension(sqlite_vec.loadable_path())
    await d.db.enable_load_extension(False)
    yield d
    await d.close()


# ── (a2) REGRESSION: первопричина — успешный embed больше не падает ─────────


@pytest.mark.asyncio
async def test_successful_embed_no_nameerror_after_http_200(fresh_ecp,
                                                            monkeypatch):
    """REGRESSION (прод 2.58.141): после успешного HTTP-вызова исполнение
    больше НЕ падает с NameError на vestigial `_LAST_EMBED_META.set()` —
    векторы возвращаются вызывающему. Канал удалён целиком (ни определения,
    ни вызова — половинчатое состояние недопустимо)."""
    assert not hasattr(ecp, "_LAST_EMBED_META"), (
        "vestigial ContextVar должен отсутствовать (канал удалён, "
        "consumer на производственной линии не существует)")
    _patch_keys(monkeypatch, primary="kA")
    llm = ScriptedLLM()
    llm.script = ["ok"]
    ex = EmbeddingExecutor(llm)
    stats = ExecutionStats()
    vectors = await ex.embed(["x", "y"], priority=Priority.P1_WRITE,
                             stats=stats)
    assert len(vectors) == 2
    assert all(v == [0.5] * 8 for v in vectors)
    assert stats.http_calls == 1
    assert llm.calls == 1


# ── (a) NameError-класс → code_defect: без ретраев и без фейк-бюджета ───────


@pytest.mark.asyncio
async def test_programming_error_is_code_defect_no_retries_no_budget(
        fresh_ecp, monkeypatch, caplog):
    """(a) Детерминированная ошибка кода (NameError — как в проде) →
    `EmbeddingCodeDefect`: ОДИН вызов (бюджет ≤4 НЕ сжигается), честный
    класс состояния, исходный traceback в цепочке `from`, полный
    traceback в логе; НЕ `EmbeddingBudgetExhausted`, НЕ quota-класс,
    credential/group-здоровье не тронуто."""
    _patch_keys(monkeypatch, primary="kA")
    llm = ScriptedLLM()
    llm.script = ["code_error"]
    ex = EmbeddingExecutor(llm)
    stats = ExecutionStats()
    with caplog.at_level(logging.ERROR, logger="services.embedding_control_plane"):
        with pytest.raises(EmbeddingCodeDefect) as ei:
            await ex.embed(["x"], priority=Priority.P1_WRITE, stats=stats)
    assert stats.http_calls == 1          # ретраев НЕТ (прод: было 4 вызова)
    assert stats.attempts == 1
    assert not isinstance(ei.value, ecp.EmbeddingBudgetExhausted)
    assert not isinstance(ei.value, EmbeddingGroupCoolingDown)
    assert isinstance(ei.value.__cause__, NameError)
    assert any("embed code defect" in r.message and r.exc_info
               for r in caplog.records)   # диагностируемый traceback в логе
    # группа/ключ не деградировали (это не транспорт и не 429)
    assert fresh_ecp.REGISTRY.group_blocked("primary") is False


@pytest.mark.asyncio
async def test_code_defect_is_serviceability_terminal(fresh_ecp):
    """(a) `EmbeddingCodeDefect` — serviceability-терминал для batch-policy
    (T-4878): повторный embed в том же batch бессмысленен, факты идут
    text-only без повторных попыток."""
    assert is_serviceability_error(EmbeddingCodeDefect("boom")) is True


def test_programming_error_classification_boundary():
    """Границы классификатора: Python-дефекты — да, транспорт/квота — нет
    (TimeoutError/ConnectionError остаются retryable-транспортом)."""
    assert ecp._is_programming_error(NameError("x")) is True
    assert ecp._is_programming_error(AttributeError("x")) is True
    assert ecp._is_programming_error(TypeError("x")) is True
    assert ecp._is_programming_error(KeyError("x")) is True
    assert ecp._is_programming_error(ImportError("x")) is True
    assert ecp._is_programming_error(SyntaxError("x")) is True
    assert ecp._is_programming_error(UnboundLocalError()) is True
    assert ecp._is_programming_error(RecursionError("x")) is True
    assert ecp._is_programming_error(TimeoutError("x")) is False
    assert ecp._is_programming_error(ConnectionError("x")) is False
    assert ecp._is_programming_error(LLMRateLimitError("429")) is False


# ── (b) transport-ошибки: retry-семантика сохранена, честный терминал ───────


@pytest.mark.asyncio
async def test_transport_error_retries_preserved_honest_terminal(
        fresh_ecp, monkeypatch):
    """(b) Transport (5xx/timeout-класс) ретраится как раньше (до 4 попыток);
    терминал исчерпания — честный `EmbeddingRetriesExhausted`
    (compat: подкласс `EmbeddingBudgetExhausted` для потребителей)."""
    _patch_keys(monkeypatch, primary="kA")
    llm = ScriptedLLM()
    llm.script = ["transport", "transport", "transport", "transport"]
    ex = EmbeddingExecutor(llm)
    stats = ExecutionStats()
    with pytest.raises(EmbeddingRetriesExhausted) as ei:
        await ex.embed(["x"], priority=Priority.P1_WRITE, stats=stats)
    assert llm.calls == 4                  # retry-семантика сохранена
    assert stats.attempts == 4
    assert isinstance(ei.value, ecp.EmbeddingBudgetExhausted)
    assert type(ei.value).__name__ == "EmbeddingRetriesExhausted"
    assert isinstance(ei.value.__cause__, ConnectionError)


@pytest.mark.asyncio
async def test_no_usable_credential_honest_class(fresh_ecp, monkeypatch):
    """(b2) Все ключи auth_failed при здоровых группах → честный
    `EmbeddingNoUsableCredential` (не «бюджет»): совместимый подкласс,
    имя состояния диагностично."""
    _patch_keys(monkeypatch, primary="kA")
    fresh_ecp.REGISTRY.mark_credential("primary", ecp.HEALTH_AUTH_FAILED)
    ex = EmbeddingExecutor(ScriptedLLM())
    with pytest.raises(EmbeddingNoUsableCredential) as ei:
        await ex.embed(["x"], priority=Priority.P1_WRITE)
    assert type(ei.value).__name__ == "EmbeddingNoUsableCredential"
    assert isinstance(ei.value, ecp.EmbeddingBudgetExhausted)


@pytest.mark.asyncio
async def test_rate_limit_defer_semantics_unchanged(fresh_ecp, monkeypatch):
    """429-путь НЕ изменён: defer по next_allowed_at, терминал одной группы —
    `EmbeddingGroupCoolingDown` с group_id/next_allowed_at (истинный
    quota-сигнал, единственный в системе)."""
    _patch_keys(monkeypatch, primary="kA")
    llm = ScriptedLLM()
    llm.script = ["rate_limit"]
    ex = EmbeddingExecutor(llm)
    with pytest.raises(EmbeddingGroupCoolingDown) as ei:
        await ex.embed(["x"], priority=Priority.P1_WRITE)
    assert ei.value.group_id == "primary"
    assert ei.value.next_allowed_at > 0
    assert fresh_ecp.REGISTRY.group_blocked("primary") is True


# ── честные reason-коды телеметрии (mca_events whitelist) ───────────────────


def test_embed_fail_reason_honest_codes():
    assert _embed_fail_reason(EmbeddingRetriesExhausted("x")) == \
        "provider_unavailable"
    assert _embed_fail_reason(EmbeddingNoUsableCredential("x")) == \
        "provider_unconfigured"
    # code_defect → честный код из whitelist mca_events (EVOL-010 follow-up)
    assert _embed_fail_reason(EmbeddingCodeDefect("x")) == "code_defect"
    assert _embed_fail_reason(EmbeddingGroupCoolingDown(
        group_id="g", next_allowed_at=1)) == "quota_group_cooling_down"


# ── (c) backfill: батч обрабатывается end-to-end (processed>0) ──────────────


@pytest.mark.asyncio
async def test_backfill_processes_batch_after_fix(vec_db, monkeypatch):
    """(c) Полный путь executor'а (адаптер → embed_once → success → запись
    vec-строки): graph-backfill продвигается, processed>0 — прод-столл
    «embed failed — deferred | processed=0» устранён."""
    _patch_keys(monkeypatch, primary="kA")
    llm = ScriptedLLM()
    llm.script = ["ok", "ok"]
    memory = MemoryManager(vec_db, llm)
    memory._vec_available = True
    memory._vec_dim = 8
    memory._vec_int8 = False
    async with vec_db.serialized():
        await vec_db.db.execute(memory._vec_table_sql(8))
        await vec_db.db.execute(memory._graph_vec_table_sql(8))
        await vec_db.db.commit()
    await vec_db.insert_graph_fact(
        -100, "evol010 факт один без вектора", "chat_history", None)
    await vec_db.insert_graph_fact(
        -100, "evol010 факт два без вектора", "chat_history", None)
    processed = await memory.backfill_graph_fact_vectors()
    assert processed == 2
    cursor = await vec_db.db.execute("SELECT COUNT(*) AS c FROM graph_facts_vec")
    assert (await cursor.fetchone())["c"] == 2
    assert ecp.BACKFILL_STATE["last_processed_graph"] == 2


# ── (d) детерминированный сбой embedder'а → честный СТОП, без вечного цикла ─


@pytest.mark.asyncio
async def test_backfill_deterministic_failure_honest_stop(vec_db, monkeypatch,
                                                          caplog):
    """(d) Детерминированный сбой (`EmbeddingCodeDefect`) → backfill
    завершается БЫСТРО (без вечного «deferred»-цикла), в логе — честный
    «code defect» с traceback, return 0."""
    memory = MemoryManager(vec_db, VectorLLM())
    memory._vec_available = True
    memory._vec_dim = 8
    memory._vec_int8 = False
    async with vec_db.serialized():
        await vec_db.db.execute(memory._vec_table_sql(8))
        await vec_db.db.execute(memory._graph_vec_table_sql(8))
        await vec_db.db.commit()
    await vec_db.insert_graph_fact(
        -100, "evol010 факт для детерминированного сбоя", "chat_history",
        None)

    async def _broken_embed(texts, *, priority=None):
        raise EmbeddingCodeDefect(
            "embedding code defect (NameError): name '_X' is not defined")

    monkeypatch.setattr(memory, "_embed", _broken_embed)
    with caplog.at_level(logging.ERROR, logger="services.summary_memory"):
        processed = await memory.backfill_graph_fact_vectors()
    assert processed == 0
    assert any("code defect" in r.message
               for r in caplog.records)      # честная причина, не «deferred»


# ── (e) F6: зомби-building при пустом источнике → честный hint + superseded ─


@pytest.mark.asyncio
async def test_source_empty_zombie_reconciled_and_hint_honest(vec_db):
    """(e) «build pending — durable job missing» (прод с 2.58.114): источник
    пуст, durable-джобы нет, в реестре зомби-`building` → hint честно говорит
    «source empty (nothing to vectorize)», строка реконслируется в
    `superseded` (векторы/строки не тронуты), НОВОЕ поколение под тем же
    fingerprint регистрируется штатно (будущие сборки не заблокированы)."""
    from services.graphrag_rebuild import latest_rebuild_job
    memory = MemoryManager(vec_db, VectorLLM())
    fp = "fp" + "0" * 60
    gen1 = await vec_db.register_embedding_target_generation("smart_archive",
                                                             fp)
    assert gen1
    # durable-джобы нет (источник пуст — планировщик честно не строит)
    assert await latest_rebuild_job(vec_db, "smart_archive", fp) is None
    latest = await vec_db.get_latest_embedding_generation("smart_archive")
    assert str(latest.get("status")) == "building"
    hint = await memory._generation_hint("smart_archive", latest,
                                         identity_changed=False, compat=None)
    assert "source empty" in hint
    assert "durable job missing" not in hint
    row = await vec_db.get_latest_embedding_generation("smart_archive")
    assert str(row.get("status")) == "superseded"      # зомби честно закрыт
    # появление фактов → новое building-поколение регистрируется штатно
    gen2 = await vec_db.register_embedding_target_generation("smart_archive",
                                                             fp)
    assert gen2 and gen2 != gen1
    row2 = await vec_db.get_latest_embedding_generation("smart_archive")
    assert str(row2.get("status")) == "building"


@pytest.mark.asyncio
async def test_nonempty_source_keeps_durable_job_missing_alarm(vec_db):
    """(e) Непустой источник без durable-джобы — РЕАЛЬНАЯ аномалия: тревога
    «durable job missing» сохраняется (не маскируется «source empty»)."""
    memory = MemoryManager(vec_db, VectorLLM())
    await vec_db.save_archive_fact(-100, "живой архивный факт", 1)
    fp = "fp" + "1" * 60
    await vec_db.register_embedding_target_generation("smart_archive", fp)
    latest = await vec_db.get_latest_embedding_generation("smart_archive")
    hint = await memory._generation_hint("smart_archive", latest,
                                         identity_changed=False, compat=None)
    assert "durable job missing" in hint
