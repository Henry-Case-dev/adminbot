"""ASAP 8 F8 — Embeddings: честная rotation-семантика и recovery.

Контракт (`plans/features/asap8-reliability-truthfulness/architecture.md` §8,
ТЗ §15/§23 E1–E5/§28.18/§28.19):

* E1: genuinely-unknown пул (3 ключа без опознания групп) → панель честно
  говорит rotation=none / unknown (WARN-баннер + hint), WARN ≤1/10 мин;
* E2: независимые группы (auto §15.3) — 429 одной не блокирует остальные;
* E3: явная одна группа — group cooldown блокирует именно её;
* E4: text-only факты уходят в backfill после recovery БЕЗ read-трафика
  (периодический re-probe в maintenance tick);
* E5: нет WARN-флуда при неизменном cooldown;
* named slots (primary/fallback_1/fallback_2) получают стабильные auto
  group IDs; unknown для настроенного named slot — не сваливается (defect
  п.50 закрыт структурно);
* маскирование: панель/логи никогда не содержат значений ключей (R17).

TEST-LIFECYCLE: CONTRACT owner=ASAP8/F8
"""
import asyncio
import json
import logging
import time

import pytest
import pytest_asyncio

from services import embedding_control_plane as ecp
from services.database import DatabaseService
from services.embedding_control_plane import (
    EmbeddingExecutor, EmbeddingGroupCoolingDown, Priority,
    QuotaGroupRegistry, AdaptiveController, PriorityScheduler,
    build_credential_pool, provider_panel,
)
from services.llm_client import LLMRateLimitError
from services.memory_maintenance import MemoryMaintenanceService
from services.summary_memory import MemoryManager

pytestmark = pytest.mark.asap4      # control plane/cooldown/parking — прод-ON


# ── Fixtures / helpers ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_ecp(monkeypatch):
    """Чистые singleton'ы контрол-плейна + сброс панельного состояния
    backfill (изоляция in-memory счётчиков между тестами)."""
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
                lambda old=old2, inst=inst2: object.__setattr__(inst, name,
                                                                old))


def _patch_keys(monkeypatch, *, primary="key-primary", fb1=None, fb2=None,
                extra=None, labels=None):
    _patch_setting(monkeypatch, "EMBEDDING_API_KEY", primary or "")
    _patch_setting(monkeypatch, "EMBEDDING_FALLBACK_API_KEY", fb1 or "")
    _patch_setting(monkeypatch, "EMBEDDING_FALLBACK_API_KEY_2", fb2 or "")
    _patch_setting(monkeypatch, "EMBEDDING_EXTRA_API_KEYS", extra or "")
    _patch_setting(monkeypatch, "EMBEDDING_QUOTA_GROUP_LABELS", labels or "")


def _patch_hot_pool(monkeypatch, *, labels, primary="k1", fb1="k2",
                    fb2="k3", extra=None):
    """hot-слой поверх settings (панель/пул строятся с hot-приоритетом).
    Settings-слой для EMBEDDING_* гасится в "" (изоляция от env машины),
    остальные developer-дефолты (EMBED_CONCURRENCY_* и пр.) — честные
    default (CONTROLLER их читает через тот же резолвер)."""
    values = {
        "keys.embedding_api_key": primary,
        "keys.embedding_fallback_api_key": fb1,
        "keys.embedding_fallback_api_key_2": fb2,
        "keys.embedding_quota_group_labels": labels,
    }
    if extra is not None:
        values["keys.embedding_extra_api_keys"] = extra

    def _fake_hot(key, default=None):
        return values.get(key, default)

    def _fake_setting(name, default):
        if str(name).startswith("EMBEDDING_"):
            return ""
        return default

    monkeypatch.setattr(ecp, "_hot_get", _fake_hot)
    monkeypatch.setattr(ecp, "_settings_value", _fake_setting)


class FakeLLM:
    """embed_once-контракт адаптера: сценарий по вызовам — 'ok' |
    'rate_limit' (RA=20s). R17: ключ виден тесту через keys_called()."""

    def __init__(self, *, retry_after: float | None = 20.0, dim: int = 8):
        self._embed_model = "test-embed-model"
        self.script: list = []
        self.calls: list[dict] = []
        self.retry_after = retry_after
        self.dim = dim

    async def embed_once(self, texts, *, api_key, base_url=None, model=None,
                         max_retries=0, retry_statuses=()):
        self.calls.append({"n": len(texts), "key": api_key})
        behavior = self.script.pop(0) if self.script else "ok"
        if behavior == "rate_limit":
            exc = LLMRateLimitError("LLM rate limited (429)")
            if self.retry_after is not None:
                exc.headers = {"Retry-After": str(self.retry_after)}
            exc.body = ""
            raise exc
        return [[0.5] * self.dim for _ in texts]

    def keys_called(self) -> list[str]:
        return [c["key"] for c in self.calls]


class RecoveryLLM:
    """Для E4: legacy embed-контракт (пул пуст → executor делегирует
    llm.embed) + генерация не нужна."""

    def __init__(self, dim: int = 8):
        self.dim = dim
        self.embed_calls = 0

    async def embed(self, texts):
        self.embed_calls += 1
        return [[0.5] * self.dim for _ in texts]


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


@pytest_asyncio.fixture
async def vec_db(tmp_path):
    pytest.importorskip("sqlite_vec")
    d = DatabaseService(str(tmp_path / "f8.db"))
    await d.initialize()
    import sqlite_vec
    await d.db.enable_load_extension(True)
    await d.db.load_extension(sqlite_vec.loadable_path())
    await d.db.enable_load_extension(False)
    yield d
    await d.close()


# ── E1: unknown-пул → честный WARN-баннер (§28.18) ──────────────────────────


def test_e1_unknown_pool_panel_warn_banner(monkeypatch, caplog):
    """E1: 3 credentials без опознания групп (extra-алиасы) → панель явно
    говорит rotation none / unknown: warn-баннер (status/reason/hint) +
    единичный WARN (≤1/10 мин — не флуд)."""
    _patch_keys(monkeypatch, primary="", fb1="", fb2="", extra="k1;k2;k3")
    with caplog.at_level(logging.WARNING,
                         logger="services.embedding_control_plane"):
        panel = provider_panel()
        provider_panel()                       # повтор — WARN не дублируется
    rot = panel["rotation"]
    assert rot["status"] == "none"
    assert rot["warn"] is True
    assert rot["degenerate"] is True
    assert rot["reason"] == "unknown_group"
    assert rot["groups"] == ["unknown"]
    assert "EMBEDDING_QUOTA_GROUP_LABELS" in rot["hint"]
    assert "keys.embedding_quota_group_labels" in rot["hint"]
    records = [r for r in caplog.records if "rotation=none" in r.getMessage()]
    assert len(records) == 1
    # Per-credential строки показывают unknown-provenance честно.
    rows = panel["credential_rows"]
    assert [r["alias"] for r in rows] == ["extra_1", "extra_2", "extra_3"]
    assert all(r["quota_group"] == "unknown" and
               r["quota_group_source"] == "unknown" for r in rows)


def test_e1_named_slots_are_not_unknown(monkeypatch):
    """E1-семантика §15.3: настроенные named slots без label — НЕ unknown:
    независимые стабильные auto-group id (дефект п.50 закрыт структурно),
    rotation=grouped, баннера нет."""
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3")
    panel = provider_panel()
    rot = panel["rotation"]
    assert rot["status"] == "grouped"
    assert rot["warn"] is False and rot["degenerate"] is False
    assert rot["groups"] == ["fallback_1", "fallback_2", "primary"]
    rows = {r["alias"]: r for r in panel["credential_rows"]}
    assert rows["primary"]["quota_group"] == "primary"
    assert rows["primary"]["quota_group_source"] == "auto"
    assert rows["fallback_2"]["quota_group"] == "fallback_2"
    assert panel["quota_groups_total"] == 3
    # Явная ручная группировка остаётся возможной (label приоритетен).
    _patch_keys(monkeypatch, primary="k1", fb1="k2", fb2="k3",
                labels="primary:gX")
    rows = {r["alias"]: r for r in provider_panel()["credential_rows"]}
    assert rows["primary"]["quota_group"] == "gX"
    assert rows["primary"]["quota_group_source"] == "explicit"
    assert rows["fallback_1"]["quota_group_source"] == "auto"


# ── E2: независимые группы — 429 одной не блокирует остальные ───────────────


@pytest.mark.asyncio
async def test_e2_independent_groups_rotation(fresh_ecp, monkeypatch):
    """E2/§15.4: named slots без label — независимые pools; 429 primary →
    cooldown ТОЛЬКО группы primary; ротация уходит на fallback_1."""
    _patch_keys(monkeypatch, primary="kA", fb1="kB", fb2="kC")
    llm = FakeLLM(retry_after=20.0)
    llm.script = ["rate_limit", "ok"]
    ex = EmbeddingExecutor(llm)
    vectors = await ex.embed(["x", "y"], priority=Priority.P1_WRITE)
    assert len(vectors) == 2
    assert llm.keys_called() == ["kA", "kB"]
    # Cooldown у группы primary, fallback_1/fallback_2 не затронуты.
    assert fresh_ecp.REGISTRY.group_blocked("primary") is True
    assert fresh_ecp.REGISTRY.group_blocked("fallback_1") is False
    assert fresh_ecp.REGISTRY.group_blocked("fallback_2") is False
    # Повторный запрос идёт сразу на независимую группу.
    llm.script = ["ok"]
    await ex.embed(["z"], priority=Priority.P1_WRITE)
    assert llm.calls[-1]["key"] == "kB"
    # last-429 per-group (панель §15.3) — только у пострадавшей группы.
    assert fresh_ecp.REGISTRY.last_rate_limit_at("primary") > 0
    assert fresh_ecp.REGISTRY.last_rate_limit_at("fallback_1") == 0


# ── E3: одна группа — cooldown блокирует именно её ──────────────────────────


@pytest.mark.asyncio
async def test_e3_same_group_cooldown_blocks_exactly_it(fresh_ecp,
                                                        monkeypatch):
    """E3/§10: явная ручная группировка (primary+fallback_1 → gA) — 429
    primary замораживает ОБА ключа gA, независимая группа (fallback_2)
    продолжает работать."""
    _patch_keys(monkeypatch, primary="kA", fb1="kB", fb2="kC",
                labels="primary:gA, fallback_1:gA, fallback_2:gB")
    llm = FakeLLM(retry_after=20.0)
    llm.script = ["rate_limit", "ok"]
    ex = EmbeddingExecutor(llm)
    vectors = await ex.embed(["x"], priority=Priority.P1_WRITE)
    assert len(vectors) == 1
    # Ротация перескочила ОБА ключа gA → работающий ключ только kC (gB).
    assert llm.keys_called() == ["kA", "kC"]
    assert fresh_ecp.REGISTRY.group_blocked("gA") is True
    assert fresh_ecp.REGISTRY.group_blocked("gB") is False
    panel = provider_panel()
    lines = {g["quota_group"]: g for g in panel["groups"]}
    assert lines["gA"]["health"] in ("cooling", "exhausted")
    assert lines["gA"]["keys"] == 2
    assert lines["gB"]["health"] == "ok"
    assert lines["gA"]["last_429_at"] > 0


# ── E4: text-only backlog → backfill после recovery без read-трафика ────────


@pytest.mark.asyncio
async def test_e4_backfill_probe_without_read_traffic(vec_db, monkeypatch):
    """E4/§28.19: vec жив, факты сохранены text-only (деградация embed при
    живом vec) → `embed_recovery_tick` находит backlog и backfill'ит БЕЗ
    read-трафика; повторный тик — cadence-skip; панель видит счётчики."""
    monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
    _patch_keys(monkeypatch, primary="")           # пул пуст → llm.embed
    llm = RecoveryLLM()
    memory = MemoryManager(vec_db, llm)
    memory._vec_available = True
    memory._vec_dim = 8
    memory._vec_int8 = False
    # vec-таблицы должны существовать (healthy-vec сценарий).
    async with vec_db.serialized():
        await vec_db.db.execute(memory._vec_table_sql(8))
        await vec_db.db.execute(memory._graph_vec_table_sql(8))
        await vec_db.db.commit()
    fact_id = await vec_db.insert_graph_fact(
        -100, "уникальный f8 текстовый факт без вектора", "chat_history",
        None)
    status = await memory.embed_recovery_tick()
    assert status["backfilled"] == 1
    assert status["skipped"] == ""
    cursor = await vec_db.db.execute(
        "SELECT COUNT(*) AS c FROM graph_facts_vec WHERE fact_id = ?",
        (fact_id,))
    assert (await cursor.fetchone())["c"] == 1
    # Прогресс/счётчики — в панель (BACKFILL_STATE) и честный backlog=0.
    assert ecp.BACKFILL_STATE["last_processed_graph"] == 1
    assert ecp.BACKFILL_STATE["last_backfill_ts"] > 0
    # Повторный тик сразу — cadence-skip (не спамим embed-провайдера).
    status2 = await memory.embed_recovery_tick()
    assert status2["skipped"] == "cadence"
    assert status2["backfilled"] == 0


@pytest.mark.asyncio
async def test_e4_reprobe_recovers_vec_without_reads(vec_db, monkeypatch,
                                                     caplog):
    """E4: vec off ИЗ-ЗА embed → периодический re-probe (`_ensure_vec_retry`)
    через recovery tick реактивирует vec и запускает backfill — как раньше
    только по read-пути, теперь и без него."""
    monkeypatch.setattr("services.summary_memory._EMBED_RETRY_BACKOFF", 0)
    monkeypatch.setattr("services.summary_memory._VEC_REACTIVATE_INTERVAL",
                        0.0)
    _patch_keys(monkeypatch, primary="")
    memory = MemoryManager(vec_db, RecoveryLLM())
    memory._vec_available = False
    memory._vec_off_reason = "embed"
    memory._embed_degraded_at = time.monotonic() - 1.0
    # Фоновый graphrag-планировщик (_recover_runtime_jobs) — вне скоупа
    # этого теста: не оставляем repeating-ticker после себя в общем прогоне.
    async def _no_recover():
        return None
    monkeypatch.setattr(memory, "_recover_runtime_jobs", _no_recover)
    status = await memory.embed_recovery_tick()
    assert status["probed"] is True
    assert status["recovered"] is True
    assert memory._vec_available is True
    assert memory._vec_off_reason is None
    assert ecp.BACKFILL_STATE["last_recovery_ts"] > 0


@pytest.mark.asyncio
async def test_maintenance_tick_wires_embed_recovery(db):
    """F8: существующий maintenance tick вызывает `embed_recovery_tick`
    (re-probe без read-трафика); memory-двойник без метода → no-op."""
    class TickMemory:
        def __init__(self):
            self.calls = 0

        async def embed_recovery_tick(self):
            self.calls += 1
            return {"probed": True, "recovered": True, "backfilled": 3,
                    "backlog_archive": 0, "backlog_graph": 0, "skipped": ""}

    mem = TickMemory()
    svc = MemoryMaintenanceService(db, mem, None)
    await svc._tick_embed_recovery()
    assert mem.calls == 1
    svc2 = MemoryMaintenanceService(db, object(), None)   # метода нет → no-op
    await svc2._tick_embed_recovery()                     # не бросает


# ── E5: нет WARN-флуда при неизменном cooldown ──────────────────────────────


@pytest.mark.asyncio
async def test_e5_no_warn_flood_on_unchanged_cooldown(fresh_ecp, monkeypatch,
                                                      caplog):
    """E5: группа уже в cooldown → повторные попытки не плодят WARN
    (rotation-WARN ≤1/10 мин; уже-cooling группа чинится молча, fail-open
    по истечении — без логов на каждый чих)."""
    _patch_keys(monkeypatch, primary="", fb1="", fb2="", extra="k1;k2;k3")
    fresh_ecp.REGISTRY._set_group_local(
        "unknown", "cooling_down", int(time.time()) + 600, "429 kind=rpm")
    with caplog.at_level(logging.WARNING,
                         logger="services.embedding_control_plane"):
        for _ in range(5):
            assert fresh_ecp.REGISTRY.group_blocked("unknown") is True
        diag = {"keys": 3, "groups": ["unknown"], "known": False,
                "degenerate": True}
        assert ecp._maybe_warn_degenerate_rotation(diag) is True
        assert ecp._maybe_warn_degenerate_rotation(diag) is False
        provider_panel()
        provider_panel()
    warn_records = [r for r in caplog.records
                    if r.levelno >= logging.WARNING]
    rotation_warns = [r for r in warn_records
                      if "rotation=none" in r.getMessage()]
    assert len(rotation_warns) == 1        # rotation — 1/10 мин, не флуд
    # Повторные embed-попытки в уже-cooling группу → тот же терминал без
    # новых 429-WARN (rate_limits_last_10m не растёт без реальных 429).
    assert fresh_ecp.REGISTRY.rate_limits_last_10m() == 0


# ── Пересбор registry при runtime-добавлении labels + маскирование ──────────


def test_registry_rebuild_on_runtime_labels(monkeypatch):
    """F8: labels, добавленные в рантайме, подхватываются живьём (пул
    строится на вызов); устаревшая замороженная группа показывается, только
    пока у неё активный cooldown; истёкший cooldown → группа исчезает из
    панели; пул после конфигурации разморожен (backlog уходит в backfill)."""
    hot: dict = {
        "keys.embedding_api_key": "k1",
        "keys.embedding_fallback_api_key": "",
        "keys.embedding_fallback_api_key_2": "",
        "keys.embedding_quota_group_labels": "",
    }
    monkeypatch.setattr(ecp, "_hot_get",
                        lambda key, default: hot.get(key, default))
    monkeypatch.setattr(
        ecp, "_settings_value",
        lambda name, default: "" if str(name).startswith("EMBEDDING_")
        else default)
    fresh = ecp.REGISTRY
    # До labels: named slot в auto-группе "primary"; 429 её замораживает.
    pool = build_credential_pool()
    assert pool[0].quota_group_id == "primary"
    assert pool[0].quota_group_source == "auto"
    fresh._set_group_local("primary", "cooling_down",
                           int(time.time()) + 600, "429 kind=rpm")
    assert fresh.group_blocked("primary") is True
    # Владелец задал label (runtime, hot) — пул переезжает в новую группу
    # "alpha": она НЕ blocked (registry-пересбор живьём), пул разморожен.
    hot["keys.embedding_quota_group_labels"] = "primary:alpha"
    pool2 = build_credential_pool()
    assert pool2[0].quota_group_id == "alpha"
    assert pool2[0].quota_group_source == "explicit"
    assert fresh.group_blocked("alpha") is False
    panel = provider_panel()
    group_ids = {g["quota_group"] for g in panel["groups"]}
    assert "alpha" in group_ids
    assert "primary" in group_ids          # активный cooldown ещё показывается
    # Cooldown истёк → устаревшая группа из панели исчезает.
    fresh._set_group_local("primary", "cooling_down",
                           int(time.time()) - 1, "cooldown_expired")
    group_ids2 = {g["quota_group"] for g in provider_panel()["groups"]}
    assert "primary" not in group_ids2
    assert "alpha" in group_ids2


def test_panel_and_groups_r17_masking(monkeypatch):
    """R17: панель (provider/groups/credential_rows/backlog) не содержит
    значений ключей; auto-группа named slot — стабильный alias, не
    производная от значения ключа."""
    secret = "super-secret-f8-key-material"
    _patch_hot_pool(monkeypatch, labels="", primary=secret)
    panel = provider_panel()
    dumped = json.dumps(panel, ensure_ascii=False)
    assert secret not in dumped
    row = panel["credential_rows"][0]
    assert row["quota_group"] == "primary"
    assert row["quota_group_source"] == "auto"
    backlog = dict(ecp.BACKFILL_STATE)
    assert secret not in json.dumps(backlog)
