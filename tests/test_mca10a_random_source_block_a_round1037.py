"""MCA-10a `mca-10a-random-source-anu` — focused-тесты блока A (T-4970).

Покрытие (A18/R1/R2, spec §2/§3/§6/§7/§8):
  * rejection sampling без modulo bias (pure + e2e, журнал отвергнутых);
  * политика exploration: пул без основного, одна probability-проверка,
    `no_eligible_alternative`, недопустимые измерения, K4 OFF;
  * воспроизводимость выбора по журналу (без новых чисел);
  * режимы quantum/pseudorandom (hot-резолв per call; персистентность слоя);
  * PRNG — stdlib auto-seed, `source_impl` фиксирован, n=1 без расхода;
  * durable-запас: рестарт не обнуляет, reserved-диапазон не выдаётся дважды;
  * стык mca-06: K1 OFF = бит-в-бит `default_source`; K1 ON = core-адаптер
    с durably зарезервированным chunk; fallback OFF + пусто → None;
  * fallback ON → PRNG с видимой причиной; fallback OFF → отложено.
"""
import asyncio
import json

import pytest

from services import mca_dream_random, mca_events, mca_gates
from services import mca_random_source as mrs
from services.database import DatabaseService


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    """Не оставлять события в глобальном bounded-буфере mca-13 между тестами."""
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


# ── fixtures/helpers ────────────────────────────────────────────────────────
async def _fresh_db(tmp_path, name="mca10a_a.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


@pytest.fixture
def mem(monkeypatch):
    """Управляемый слой `memory.*`-настроек (без PG)."""
    values: dict = {}

    async def fake(key, chat_id, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_read_memory_setting", fake)
    return values


@pytest.fixture
def cfg(monkeypatch):
    """Управляемый глобальный слой `keys.random_quantum_*` (без PG)."""
    values: dict = {}

    def fake(key, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_hot_setting", fake)
    return values


@pytest.fixture
def events(monkeypatch):
    captured: list = []

    def fake_emit(event_name, *, outcome, **fields):
        captured.append({"event_name": event_name, "outcome": outcome,
                         **fields})
        return {}

    monkeypatch.setattr(mrs.mca_events, "emit_mca_event", fake_emit)
    return captured


class FakeSource:
    """Детерминированный источник для `ExplorationPolicy` (DI)."""

    def __init__(self, probability=0.0, index=0):
        self.probability = probability
        self.index = index
        self.prob_calls = 0
        self.index_calls = 0

    async def draw_probability(self, **kwargs):
        self.prob_calls += 1
        return mrs.DrawResult(value=self.probability, source="quantum",
                              draw_id="prob-draw")

    async def draw_index(self, n, **kwargs):
        self.index_calls += 1
        return mrs.DrawResult(index=self.index, source="quantum",
                              draw_id="sel-draw")


def _meta(**over):
    meta = {"chat_id": 1, "purpose": "less_studied_periods",
            "policy_version": "mca10a-v1", "probability": None,
            "pool_size": None, "candidates_json": None,
            "fallback_reason": None, "config_version": "test"}
    meta.update(over)
    return meta


# ── rejection sampling / равномерность ──────────────────────────────────────
def test_map_value_to_index_no_modulo_bias():
    """`limit=(range//n)*n`: значения ≥ limit отвергаются, < limit — v%n."""
    assert mrs.map_value_to_index(3, 3, 4) is None      # 3 >= (4//3)*3=3
    assert mrs.map_value_to_index(0, 3, 4) == 0
    assert mrs.map_value_to_index(2, 3, 4) == 2
    assert mrs.map_value_to_index(5, 7, 8) == 5         # 5 < (8//7)*7=7
    assert mrs.map_value_to_index(7, 7, 8) is None      # 7 >= 7
    assert mrs.map_value_to_index(6, 7, 8) == 6
    assert mrs.map_value_to_index(0, 1, 65536) == 0
    assert mrs.map_value_to_index(0, 10, 4) is None     # range < n — честный отказ
    assert mrs.map_value_to_index(0, 0, 4) is None


def test_rejection_uniformity_deterministic_fixture():
    """Детерминированная равномерность: 0..699 (range 65536), n=7 → ровно
    100 попаданий на индекс (700 = 100×7)."""
    counts = [0] * 7
    for value in range(700):
        index = mrs.map_value_to_index(value, 7, 65536)
        assert index is not None
        counts[index] += 1
    assert counts == [100] * 7


@pytest.mark.asyncio
async def test_draw_index_rejection_end_to_end_and_journal(tmp_path, mem):
    """65535 отвергнут (limit=65535), 65534 → индекс 2; оба — в журнале."""
    db = await _fresh_db(tmp_path)
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False)
        await svc._store.insert_batch(mrs.AnuBatch(
            values=[65535, 65534, 1], data_type="uint16", length=3))
        result = await svc.draw_index(3, chat_id=1,
                                      purpose="less_studied_periods")
        assert result.index == 2 and result.attempts == 2
        assert result.source == "quantum"
        assert result.batch_id is not None and result.draw_id is not None
        rows = await svc.recent_draws(limit=10)
        assert len(rows) == 2
        rejected = [r for r in rows if r["selected_id"] is None]
        selected = [r for r in rows if r["selected_id"] is not None]
        assert len(rejected) == 1 and rejected[0]["value"] == 65535.0
        assert len(selected) == 1 and selected[0]["value"] == 65534.0
        assert selected[0]["selected_id"] == "2"
        assert selected[0]["pool_size"] == 3
        # range 65536, limit=(65536//3)*3=65535: value 65534 → 65534 % 3 == 2
    finally:
        await db.close()


# ── политика exploration ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_choose_pool_without_primary_one_check():
    source = FakeSource(probability=0.01, index=0)
    policy = mrs.ExplorationPolicy(source=source)
    primary = {"id": "main"}
    choice = await policy.choose(
        primary, [primary, {"id": "a"}, {"id": "b"}], probability=0.05,
        chat_id=1, purpose="less_studied_periods")
    assert choice.explored is True
    assert choice.selected == {"id": "a"}          # index 0 → pool[0]
    assert choice.pool_ids == ["a", "b"]           # основной исключён
    assert choice.draw_ids == ["prob-draw", "sel-draw"]
    assert choice.policy_version == mrs.POLICY_VERSION
    assert source.prob_calls == 1                  # одна проверка на ситуацию
    assert source.index_calls == 1


@pytest.mark.asyncio
async def test_choose_primary_when_probability_miss():
    source = FakeSource(probability=0.9)
    policy = mrs.ExplorationPolicy(source=source)
    primary = {"id": "main"}
    choice = await policy.choose(primary, [{"id": "a"}], probability=0.05,
                                 chat_id=1, purpose="less_studied_periods")
    assert choice.explored is False and choice.selected is primary
    assert source.prob_calls == 1 and source.index_calls == 0


@pytest.mark.asyncio
async def test_choose_no_alternatives_reason():
    source = FakeSource()
    policy = mrs.ExplorationPolicy(source=source)
    primary = {"id": "main"}
    choice = await policy.choose(primary, [primary], probability=0.05,
                                 chat_id=1, purpose="less_studied_periods")
    assert choice.reason == "no_eligible_alternative"
    assert choice.selected is primary
    assert source.prob_calls == 0 and source.index_calls == 0


@pytest.mark.asyncio
async def test_choose_ineligible_measurements_and_purpose():
    source = FakeSource()
    policy = mrs.ExplorationPolicy(source=source)
    for measurement in ("truth", "identity", "source_assignment", "rights",
                        "deletion", "direct_request", "financial_settings"):
        choice = await policy.choose(
            {"id": "m"}, [{"id": "a"}], probability=0.05, chat_id=1,
            purpose="less_studied_periods", measurement=measurement)
        assert choice.reason == "no_eligible_alternative"
        assert choice.explored is False
    choice = await policy.choose({"id": "m"}, [{"id": "a"}],
                                 probability=0.05, chat_id=1,
                                 purpose="unknown_measurement")
    assert choice.reason == "no_eligible_alternative"
    assert source.prob_calls == 0


@pytest.mark.asyncio
async def test_choose_k4_off_returns_primary(monkeypatch):
    monkeypatch.setattr(mca_gates, "random_exploration_enabled",
                        lambda: False)
    source = FakeSource()
    policy = mrs.ExplorationPolicy(source=source)
    primary = {"id": "main"}
    choice = await policy.choose(primary, [{"id": "a"}], probability=0.05,
                                 chat_id=1, purpose="less_studied_periods")
    assert choice.reason == "disabled" and choice.selected is primary
    assert source.prob_calls == 0 and source.index_calls == 0


@pytest.mark.asyncio
async def test_choose_journal_reproducible(tmp_path, mem):
    """A18: по журналу выбор воспроизводим без новых чисел."""
    db = await _fresh_db(tmp_path)
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False)
        # probability-draw 0 → exploration; selection-draw 5 → 5 % 3 == 2.
        await svc._store.insert_batch(mrs.AnuBatch(
            values=[0, 5], data_type="uint16", length=2))
        primary = {"id": "main"}
        choice = await svc.choose(
            primary, [primary, {"id": "a"}, {"id": "b"}, {"id": "c"}],
            probability=0.05, chat_id=7, purpose="less_studied_periods")
        assert choice.explored is True
        assert choice.selected == {"id": "c"}
        rows = await svc.recent_draws(limit=10, chat_id=7)
        assert len(rows) == 2
        selection = [r for r in rows if r["selected_id"] is not None][0]
        assert selection["pool_size"] == 3
        assert selection["selected_id"] == str(
            int(selection["value"]) % int(selection["pool_size"]))
        assert selection["selected_id"] == "2"
        assert json.loads(selection["candidates_json"]) == ["a", "b", "c"]
        assert selection["policy_version"] == mrs.POLICY_VERSION
        assert selection["probability"] == 0.05     # порог воспроизводим
        probability_row = [r for r in rows if r["selected_id"] is None][0]
        assert probability_row["probability"] == 0.05
        assert probability_row["pool_size"] is None
        # R17-safe: только ID/числа/коды (bounded; без сырого контекста)
        expected_cols = {"draw_id", "created_at", "chat_id", "purpose",
                         "source", "provider", "batch_id", "value",
                         "candidates_json", "pool_size", "probability",
                         "policy_version", "selected_id", "fallback_reason",
                         "config_version"}
        for row in rows:
            assert set(row.keys()) == expected_cols
            assert all(not isinstance(v, str) or len(v) <= 200
                       for v in row.values())
    finally:
        await db.close()


# ── режимы/персистентность/PRNG ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_modes_hot_resolve_and_persistence(tmp_path, mem, cfg):
    db = await _fresh_db(tmp_path)
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False)
        # default: первый запуск — quantum (настройка отсутствует)
        assert await svc.selected_mode(1) == "quantum"
        # hot-смена без рестарта
        mem[mrs.SETTING_SOURCE] = "pseudorandom"
        assert await svc.selected_mode(1) == "pseudorandom"
        result = await svc.draw_index(10, chat_id=1, purpose="p")
        assert result.source == "pseudorandom"
        # мусорное значение → дефолт quantum (валидация на чтении)
        mem[mrs.SETTING_SOURCE] = "quantum-ish"
        assert await svc.selected_mode(1) == "quantum"
        # «рестарт»: тот же слой (bot_settings) → выбор сохраняется
        mem[mrs.SETTING_SOURCE] = "pseudorandom"
        svc2 = mrs.RandomSourceService(db, auto_refill=False)
        assert await svc2.selected_mode(1) == "pseudorandom"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prng_auto_seed_source_impl_and_probability(tmp_path, mem):
    db = await _fresh_db(tmp_path)
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False)
        result = await svc.draw_index(10, chat_id=1, purpose="p")
        assert result.source == "pseudorandom"
        assert result.source_impl == mrs.SOURCE_IMPL_PRNG
        assert result.fallback_reason == "provider_unconfigured"
        assert 0 <= result.index < 10
        prob = await svc.draw_probability(chat_id=1, purpose="p")
        assert prob.source == "pseudorandom"
        assert 0.0 <= float(prob.value) < 1.0
        rows = await svc.recent_draws(limit=10)
        assert {r["source"] for r in rows} == {"pseudorandom"}
        assert rows[0]["provider"] == mrs.PROVIDER_PRNG
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_draw_n1_does_not_consume(tmp_path, mem):
    db = await _fresh_db(tmp_path)
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False)
        await svc._store.insert_batch(mrs.AnuBatch(
            values=list(range(100)), data_type="uint16", length=100))
        before = await svc._store.reserve_remaining()
        result = await svc.draw_index(1, chat_id=1, purpose="p")
        assert result.index == 0 and result.draw_id is None
        assert await svc._store.reserve_remaining() == before
        assert await svc.recent_draws(limit=5) == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fallback_off_defers_optional(tmp_path, mem):
    db = await _fresh_db(tmp_path)
    try:
        mem[mrs.SETTING_FALLBACK] = False
        svc = mrs.RandomSourceService(db, auto_refill=False)
        result = await svc.draw_index(10, chat_id=1, purpose="p")
        assert result.deferred is True and result.index is None
        assert result.reason == "provider_unconfigured"
        assert await svc.recent_draws(limit=5) == []   # draw не состоялся
        # K2 OFF → причина disabled, PRNG не подставляется при fallback OFF
        svc2 = mrs.RandomSourceService(db, auto_refill=False)
        assert (await svc2.resolve_effective(1))[0] == "pseudorandom"
    finally:
        await db.close()


# ── durable-запас / crash-семантика ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_reserve_survives_restart_and_no_reissue(tmp_path):
    db = await _fresh_db(tmp_path)
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False)
        await svc._store.insert_batch(mrs.AnuBatch(
            values=list(range(1000)), data_type="uint16", length=1000))
        chunk = await svc._store.reserve_chunk(64)
        assert [c.value for c in chunk] == list(range(64))
        assert await svc._store.reserve_remaining() == 936
        await db.close()
        # «рестарт»: запас/watermark durable; выданный диапазон не повторяется
        db2 = await _fresh_db(tmp_path, name="mca10a_a.db")
        svc2 = mrs.RandomSourceService(db2, auto_refill=False)
        assert await svc2._store.reserve_remaining() == 936
        draw = await svc2._store.reserve_draw(n=7, meta=_meta())
        assert draw.value == 64 and draw.index == 64 % 7
        chunk2 = await svc2._store.reserve_chunk(3)
        assert [c.value for c in chunk2] == [65, 66, 67]
    finally:
        await db2.close()


@pytest.mark.asyncio
async def test_k2_off_effective_pseudorandom_reason_disabled(tmp_path, mem,
                                                             monkeypatch):
    """K2 OFF → ANU не используется; effective=pseudorandom с причиной
    `disabled`; квантовый запас не расходуется."""
    db = await _fresh_db(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "random_quantum_enabled", lambda: False)
        svc = mrs.RandomSourceService(db, auto_refill=False)
        await svc._store.insert_batch(mrs.AnuBatch(
            values=list(range(10)), data_type="uint16", length=10))
        result = await svc.draw_index(10, chat_id=1, purpose="p")
        assert result.source == "pseudorandom"
        assert result.fallback_reason == "disabled"
        assert await svc._store.reserve_remaining() == 10
        mem[mrs.SETTING_FALLBACK] = False
        deferred = await svc.draw_index(10, chat_id=1, purpose="p")
        assert deferred.deferred is True and deferred.reason == "disabled"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_k1_off_draws_disabled_no_new_records(tmp_path, mem,
                                                    monkeypatch):
    """K1 OFF → draw не выдаётся, новых записей/эффектов нет."""
    db = await _fresh_db(tmp_path)
    try:
        monkeypatch.setattr(mca_gates, "random_source_enabled", lambda: False)
        svc = mrs.RandomSourceService(db, auto_refill=False)
        result = await svc.draw_index(5, chat_id=1, purpose="p")
        assert result.deferred is True and result.reason == "disabled"
        assert await svc.recent_draws(limit=5) == []
    finally:
        await db.close()


# ── стык mca-06 (D7) ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_for_dream_k1_off_bit_for_bit_default(monkeypatch):
    monkeypatch.setattr(mca_gates, "random_source_enabled", lambda: False)
    candidates = [{"id": i} for i in range(30)]
    src = await mrs.for_dream(42, k_hint=5, chat_id=1)
    assert isinstance(src, mca_dream_random.DeterministicUniformRandomSource)
    items, meta = src.pick(candidates, chat_id=1,
                           purpose=mca_dream_random.PURPOSE_LESS_STUDIED, k=5)
    ref_items, ref_meta = mca_dream_random.default_source(42).pick(
        candidates, chat_id=1, purpose=mca_dream_random.PURPOSE_LESS_STUDIED,
        k=5)
    assert items == ref_items and meta == ref_meta


@pytest.mark.asyncio
async def test_for_dream_quantum_chunk_meta_and_flush(tmp_path, mem, cfg):
    db = await _fresh_db(tmp_path)
    try:
        mrs.reset_service()
        svc = mrs.bind_db(db)
        svc._auto_refill = False
        await svc._store.insert_batch(mrs.AnuBatch(
            values=list(range(100)), data_type="uint16", length=100))
        src = await mrs.for_dream(7, k_hint=3, chat_id=5)
        assert isinstance(src, mrs.CoreDreamRandomSource)
        assert src.source == "quantum" and src.batch_id is not None
        assert len(src.values) == 10          # min(max(2*3+4, 8), 64)
        candidates = [{"id": f"c{i}"} for i in range(20)]
        items, meta = src.pick(candidates, chat_id=5,
                               purpose="less_studied_periods", k=3)
        assert len(items) == 3
        assert len(set(meta["picked"])) == 3
        assert meta["source"] == "quantum" and meta["seed"] is None
        assert meta["provider"] == mrs.PROVIDER_ANU
        assert meta["batch_id"] == src.batch_id
        assert meta["fallback"] is False and meta["fallback_reason"] is None
        assert meta["draw_ids"] and meta["picked"] == sorted(meta["picked"])
        assert svc.journal_queue_depth() > 0
        await svc.flush_journal()
        assert svc.journal_queue_depth() == 0
        rows = await svc.recent_draws(limit=50)
        assert len(rows) == meta["used"]
        assert all(r["chat_id"] == 5 and r["source"] == "quantum"
                   for r in rows)
        assert all(r["purpose"] == "less_studied_periods" for r in rows)
    finally:
        mrs.reset_service()
        await db.close()


@pytest.mark.asyncio
async def test_for_dream_fallback_off_empty_returns_none(tmp_path, mem):
    db = await _fresh_db(tmp_path)
    try:
        mem[mrs.SETTING_FALLBACK] = False
        svc = mrs.RandomSourceService(db, auto_refill=False)
        mrs.reset_service()
        mrs._service = svc
        assert await mrs.for_dream(7, k_hint=3, chat_id=5) is None
        mem[mrs.SETTING_FALLBACK] = True
        src = await mrs.for_dream(7, k_hint=3, chat_id=5)
        assert isinstance(src, mrs.CoreDreamRandomSource)
        assert src.source == "pseudorandom" and src.fallback is True
        assert src.fallback_reason == "provider_unconfigured"
        _, meta = src.pick([{"id": i} for i in range(5)], chat_id=5,
                           purpose="less_studied_periods", k=2)
        assert meta["source"] == "pseudorandom"
        assert meta["fallback_reason"] == "provider_unconfigured"
        assert meta["source_impl"] == mrs.SOURCE_IMPL_PRNG
    finally:
        mrs.reset_service()
        await db.close()
