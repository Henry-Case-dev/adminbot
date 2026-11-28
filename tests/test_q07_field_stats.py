"""Q-07 (VMQ-Q0) — статистический слой поля допустимых фокусов.

Контракт: `plans/features/vmq-onto-01/evidence/q-07-contract-2026-11-27.md`
(sha256 `6beab458…c0688`), §2/§3/§7.4/§8. Прод-база: `aa4e9098a` (2.58.274).

Проверяется ровно то, что объявлено в контракте:
  * T1 стабильность карты/fingerprint/классификации к порядку строк;
  * T2/T3 негативные контроли: пустая и некалиброванная база не дают аномалии
    (в т.ч. запрет подставлять «порог по памяти» 1.96/2.58);
  * T4 гейт `expected >= 5` → `insufficient_history`;
  * T5 `void` только для реальной допустимой ячейки с `expected >= 5`;
  * T6 порог — max-statistic, а не per-cell z (мутация M1 убивается);
  * T7 свойства нуль-модели: доля ложных аномалий, монотонность, репро;
  * T8 битые/усечённые строки видны в `records.skipped_*`, не в `N`;
  * T9 снимок read-only, bounded по payload и по времени;
  * T10 fail-open `/api/status`: сбой блока не ломает остальной ответ.

Случайность в тестах — только локальный `random.Random(seed).random()`
(как и в калибровке): никаких сетевых провайдеров и записей в журнал.
"""
import asyncio
import json
import random
import time

import pytest

from services import mca_events
from services import mca_gates
from services import mca_random_source as mrs
from services.database import DatabaseService
from services.status_service import StatusService

CELLS_10 = tuple("ep:%03d" % i for i in range(10))


# ── helpers ────────────────────────────────────────────────────────────────
async def _fresh_db(tmp_path, name="q07.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


def _cells(count: int, prefix: str = "ep") -> tuple:
    return tuple("%s:%03d" % (prefix, i) for i in range(count))


def _spread(total: int, cells: int) -> list:
    """Равномерно распределить `total` наблюдений по `cells` ячейкам."""
    base, extra = divmod(total, cells)
    return [base + (1 if i < extra else 0) for i in range(cells)]


def _rows(cells, counts, *, chat_id=1, source="quantum",
          purpose="memory_recall", created=1795820000, prefix="d",
          candidates=None) -> list:
    """Строки журнала: одна строка = одна выборка индекса в `cells`."""
    pool = list(candidates) if candidates is not None else list(cells)
    raw = json.dumps(pool, ensure_ascii=False)
    out = []
    for position, (ref, count) in enumerate(zip(cells, counts)):
        for index in range(count):
            out.append({
                "draw_id": "%s-%s-%d-%d" % (prefix, ref, position, index),
                "created_at": created,
                "chat_id": chat_id,
                "purpose": purpose,
                "source": source,
                "provider": "python-random",
                "batch_id": None,
                "value": float(index),
                "candidates_json": raw,
                "pool_size": len(pool),
                "probability": None,
                "policy_version": "mca10a-v1",
                "selected_id": str(position),
                "fallback_reason": None,
                "config_version": "2.58.274",
            })
    return out


def _raw_row(**over) -> dict:
    row = {
        "draw_id": "raw-default",
        "created_at": 1795820000,
        "chat_id": 1,
        "purpose": "memory_recall",
        "source": "quantum",
        "provider": "python-random",
        "batch_id": None,
        "value": 0.0,
        "candidates_json": json.dumps(["a", "b", "c"]),
        "pool_size": 3,
        "probability": None,
        "policy_version": "mca10a-v1",
        "selected_id": "0",
        "fallback_reason": None,
        "config_version": "2.58.274",
    }
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def _clean_field_cache():
    mrs._FIELD_NULL_CACHE.clear()
    mca_events.reset_pending()
    yield
    mrs._FIELD_NULL_CACHE.clear()
    mca_events.reset_pending()


# ── T1: стабильность карты и классификации ─────────────────────────────────
@pytest.mark.asyncio
async def test_map_fingerprint_order_independent(tmp_path):
    cells = _cells(6)
    counts = [30, 25, 20, 15, 10, 5]          # N = 105, expected = 17.5

    # База 1: кандидаты в прямом порядке, строки перемешаны по времени.
    now = int(time.time())
    db1 = await _fresh_db(tmp_path, "q07_t1_a.db")
    rows_a = _rows(cells, counts, created=now - 3600)
    random.Random(41).shuffle(rows_a)
    await mrs.RandomStore(db1).journal_many(rows_a)

    # База 2: кандидаты в обратном порядке, другие created_at/chat_id,
    # строки вставлены в обратном порядке (счётчики остаются за своими refs).
    db2 = await _fresh_db(tmp_path, "q07_t1_b.db")
    pairs = list(reversed(list(zip(cells, counts))))
    rows_b = _rows([ref for ref, _ in pairs], [count for _, count in pairs],
                   created=now - 7200, chat_id=777)
    rows_b.reverse()
    await mrs.RandomStore(db2).journal_many(rows_b)

    snap_a = await mrs.RandomSourceService(db1).field_snapshot()
    snap_b = await mrs.RandomSourceService(db2).field_snapshot()
    assert snap_a["primary"]["cells"] == snap_b["primary"]["cells"] == 6
    assert snap_a["primary"]["observations"] == 105
    assert (snap_a["primary"]["map_fingerprint"]
            == snap_b["primary"]["map_fingerprint"])
    assert snap_a["primary"] == snap_b["primary"]

    # Прямое свойство функций: порядок входа не меняет ни карту, ни вердикт.
    assert (mrs.canonical_cells(list(cells))
            == mrs.canonical_cells(list(reversed(cells)) + list(cells)))
    forward = mrs.classify_field(cells=list(cells),
                                 observed=dict(zip(cells, counts)))
    backward = mrs.classify_field(
        cells=list(reversed(cells)),
        observed=dict(reversed(list(zip(cells, counts)))))
    assert forward == backward
    assert forward["map_fingerprint"] == mrs.map_fingerprint(cells)
    await db1.close()
    await db2.close()


# ── T2: пустая база никогда не даёт аномалию ───────────────────────────────
@pytest.mark.asyncio
async def test_no_data_never_anomaly(tmp_path):
    for result in (
            mrs.classify_field(cells=(), observed={}),
            mrs.classify_field(cells=list(CELLS_10), observed={}),
            mrs.classify_field(cells=list(CELLS_10),
                               observed={ref: 0 for ref in CELLS_10})):
        assert result["state"] == "no_data"
        assert result["anomaly_kind"] == "none"
        assert result["anomaly_score"] is None
        assert result["null_quantile"] is None
        assert result["qualifying_cells"] == 0
        assert result["anomaly_kind"] not in ("attractor", "void", "power")

    db = await _fresh_db(tmp_path, "q07_t2.db")
    snap = await mrs.RandomSourceService(db).field_snapshot()
    assert snap["ready"] is True
    assert snap["maps"] == 0
    assert snap["primary"]["state"] == "no_data"
    assert snap["primary"]["anomaly_kind"] == "none"
    assert snap["primary"]["observations"] == 0
    assert snap["records"]["rows"] == 0
    await db.close()


# ── T3: некалиброванная нуль-модель отказывается от утверждения ────────────
def test_uncalibrated_baseline_refuses_claim(monkeypatch):
    cells = list(CELLS_10)
    counts = _spread(100, 10)                 # expected = 10 на ячейку
    counts[0] += 9                            # 19 → z = +3.0
    counts[1] -= 9                            # 1  → z = −3.0
    observed = dict(zip(cells, counts))
    assert (observed["ep:000"] - 10) / 3.0 == pytest.approx(3.0)

    def boom(**kwargs):
        raise RuntimeError("calibration unavailable")

    monkeypatch.setattr(mrs, "null_thresholds", boom)
    result = mrs.classify_field(cells=cells, observed=observed)
    assert result["state"] == "baseline_uncalibrated"
    assert result["anomaly_kind"] == "none"
    assert result["anomaly_score"] is None
    assert result["null_quantile"] is None
    assert result["qualifying_cells"] == 0

    monkeypatch.undo()
    mrs._FIELD_NULL_CACHE.clear()
    # sims = 0 — калибровка не выполнена, порог не выдумывается.
    result = mrs.classify_field(cells=cells, observed=observed, sims=0)
    assert result["state"] == "baseline_uncalibrated"
    assert result["anomaly_kind"] == "none"
    assert result["null_quantile"] is None


# ── T4: гейт expected >= 5 ─────────────────────────────────────────────────
def test_small_expected_not_anomaly(monkeypatch):
    cells = list(CELLS_10)

    def must_not_run(**kwargs):
        raise AssertionError("calibration ran below min_expected")

    monkeypatch.setattr(mrs, "null_thresholds", must_not_run)
    counts = _spread(40, 10)                  # expected = 4
    counts[0] = 0                             # observed = 0 при малом expected
    for index, extra in enumerate(_spread(4, 9), start=1):
        counts[index] += extra                # N остаётся 40
    result = mrs.classify_field(cells=cells,
                                observed=dict(zip(cells, counts)))
    assert result["state"] == "insufficient_history"
    assert result["anomaly_kind"] == "none"
    assert result["null_quantile"] is None
    assert result["anomaly_score"] is None
    assert result["note"] == "expected_per_cell_below_min"


# ── T5: void только для реальной допустимой ячейки с данными ───────────────
def test_void_requires_eligible_cell_with_data():
    cells = list(CELLS_10)
    counts = _spread(500, 10)                 # expected = 50
    counts[0] = 0                             # observed = 0
    for index, extra in enumerate(_spread(50, 9), start=1):
        counts[index] += extra                # N остаётся 500
    observed = dict(zip(cells, counts))
    result = mrs.classify_field(cells=cells, observed=observed)
    assert result["state"] == "ok"
    assert result["anomaly_kind"] == "void"
    assert result["qualifying_cells"] == 1
    assert result["null_quantile"] is not None
    assert result["anomaly_score"] > result["null_quantile"]
    assert result["top_cells"][0]["ref"] == "ep:000"
    assert result["top_cells"][0]["observed"] == 0
    assert result["top_cells"][0]["z"] < 0

    # Та же ячейка при expected < 5 — не «void», а честная нехватка истории.
    small = _spread(40, 10)
    small[1] += small[0]
    small[0] = 0
    result_small = mrs.classify_field(cells=cells,
                                      observed=dict(zip(cells, small)))
    assert result_small["state"] == "insufficient_history"
    assert result_small["anomaly_kind"] == "none"

    # Ячейка, отсутствующая в карте, не может стать void: чужие refs не
    # входят ни в N, ни в классификацию.
    foreign = mrs.classify_field(cells=cells,
                                 observed={"ep:foreign": 500})
    assert foreign["observations"] == 0
    assert foreign["state"] == "no_data"
    assert foreign["anomaly_kind"] == "none"
    mixed = dict(observed)
    mixed["ep:foreign"] = 500
    assert mrs.classify_field(cells=cells, observed=mixed) == result


# ── T6: порог — max-statistic, а не per-cell 1.96/2.58 (мутация M1) ────────
def test_multiple_comparisons_not_per_cell():
    cells = list(CELLS_10)
    fingerprint = mrs.map_fingerprint(cells)
    threshold = mrs.null_thresholds(
        observations=100, cells=10, fingerprint=fingerprint)["quantile"]
    assert 3.0 <= threshold <= 3.6          # контрольная полоса §3

    # Одна ячейка ровно на `threshold - 0.25` (z-сетка шагом 1/3 при N=100).
    target = threshold - 0.25
    counts = _spread(100, 10)
    counts[0] = int(round(10 + 3.0 * target))
    counts[1:] = _spread(100 - counts[0], 9)
    max_z = (counts[0] - 10.0) / 3.0
    assert 2.58 < max_z < threshold          # per-cell 2.58 «увидел бы» аномалию

    result = mrs.classify_field(cells=cells,
                                observed=dict(zip(cells, counts)))
    assert result["anomaly_kind"] == "blind"
    assert result["qualifying_cells"] == 0
    assert result["null_quantile"] == round(threshold, 3)

    # Настоящая аномалия при том же пороге всё ещё видна (не «всё blind»).
    boosted = [25, 9, 9, 9, 9, 9, 8, 8, 7, 7]     # N = 100, z = +5.0
    assert sum(boosted) == 100
    assert mrs.classify_field(cells=cells, observed=dict(
        zip(cells, boosted)))["anomaly_kind"] == "attractor"


# ── T7: свойства нуль-модели ───────────────────────────────────────────────
def test_null_baseline_property():
    cells = list(CELLS_10)
    # (а) ложные аномалии при alpha = 0.99 на равномерном генераторе.
    false_positives = 0
    for run in range(200):
        rng = random.Random(9000 + run)
        counts = [0] * 10
        for _ in range(100):
            counts[int(rng.random() * 10)] += 1
        verdict = mrs.classify_field(
            cells=cells, observed=dict(zip(cells, counts)),
            fingerprint="prop:%03d" % run)
        if verdict["anomaly_kind"] != "blind":
            false_positives += 1
    assert false_positives <= 6, false_positives

    # (б) монотонность по M при фиксированном expected = 10. Квантиль
    # max|z| ступенчатый (счётчики целые), поэтому свойство проверяется по
    # среднему на 8 детерминированных сидах: одиночный сид при 1000 репликах
    # может «перескочить» на соседнюю ступень.
    means = []
    for size in (3, 5, 10, 20):
        sample = [mrs.null_thresholds(
            observations=10 * size, cells=size,
            fingerprint="mono:%d:%d" % (size, seed))["quantile"]
            for seed in range(8)]
        means.append(sum(sample) / len(sample))
    for earlier, later in zip(means, means[1:]):
        assert later >= earlier, means

    # (в) контрольная полоса §3 для M=10, N=100 и (г) воспроизводимость.
    mrs._FIELD_NULL_CACHE.clear()
    first = mrs.null_thresholds(observations=100, cells=10,
                                fingerprint=mrs.map_fingerprint(cells))
    mrs._FIELD_NULL_CACHE.clear()
    second = mrs.null_thresholds(observations=100, cells=10,
                                 fingerprint=mrs.map_fingerprint(cells))
    assert 3.0 <= first["quantile"] <= 3.6
    assert first == second


# ── T8: битые и усечённые строки учтены, но не в N ─────────────────────────
@pytest.mark.asyncio
async def test_truncated_and_malformed_rows_are_counted(tmp_path):
    db = await _fresh_db(tmp_path, "q07_t8.db")
    store = mrs.RandomStore(db)
    cells = _cells(5, "ep")
    await store.journal_many(_rows(cells, [6, 6, 6, 6, 6], prefix="ok"))
    pool = json.dumps(list(cells))
    # Усечённый пул: selected_id за пределами сохранённых кандидатов.
    await store.journal_many([
        _raw_row(draw_id="trunc-1", selected_id="7", candidates_json=pool),
        _raw_row(draw_id="trunc-2", selected_id="9", candidates_json=pool)])
    # Битые пулы: null, дубли, не-JSON, не-список.
    await store.journal_many([
        _raw_row(draw_id="bad-1", candidates_json=None),
        _raw_row(draw_id="bad-2", candidates_json=json.dumps(["a", "b", "a"])),
        _raw_row(draw_id="bad-3", candidates_json="not-json"),
        _raw_row(draw_id="bad-4", candidates_json=json.dumps({"a": 1}))])
    # Строка без выбора (probability draw) и внутренний self-check.
    await store.journal_many([_raw_row(
        draw_id="noselect-1", selected_id=None, candidates_json=pool)])
    await store.journal_many([_raw_row(
        draw_id="internal-1", purpose="activation_selfcheck")])

    snap = await mrs.RandomSourceService(db).field_snapshot()
    records = snap["records"]
    assert records["used"] == 30
    assert records["skipped_unmappable"] == 2
    assert records["skipped_malformed"] == 4
    assert records["skipped_no_selection"] == 1
    assert records["rows"] == (records["used"] + records["skipped_unmappable"]
                               + records["skipped_malformed"]
                               + records["skipped_no_selection"])
    # Синтетические ячейки 0..n-1 не добавлены: карта — ровно 5 реальных refs.
    assert snap["primary"]["observations"] == 30
    assert snap["primary"]["cells"] == 5
    assert snap["primary"]["state"] == "ok"
    assert snap["primary"]["anomaly_kind"] == "blind"
    await db.close()


# ── T9: снимок read-only, bounded и укладывается во время ──────────────────
@pytest.mark.asyncio
async def test_snapshot_is_read_only_and_bounded(tmp_path, monkeypatch):
    db = await _fresh_db(tmp_path, "q07_t9.db")
    store = mrs.RandomStore(db)
    rows = []
    now = int(time.time())
    for index in range(6):
        cells = _cells(40, "m%d" % index)
        rows.extend(_rows(cells, _spread(400, 40), prefix="g%d" % index,
                          created=now - 3600 - index))
    # 2600 probability draw без пула — ровно до границы LIMIT 5000.
    for index in range(2600):
        rows.append(_raw_row(draw_id="prob-%d" % index, selected_id=None,
                             candidates_json=None, created=now - 7200))
    await store.journal_many(rows)
    assert len(rows) == 5000

    service = mrs.RandomSourceService(db)
    writes = []

    async def _no_write(*args, **kwargs):
        writes.append(args)
        raise AssertionError("field_snapshot must not write")

    monkeypatch.setattr(db, "write_transaction", _no_write)
    emitted = []
    monkeypatch.setattr(mrs.mca_events, "emit_mca_event",
                        lambda *a, **k: emitted.append(a))
    for name in ("_get_client", "_get_lfdr_client", "_get_ibm_client"):
        monkeypatch.setattr(
            service, name,
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("provider call in field_snapshot")))

    started = time.perf_counter()
    snap = await service.field_snapshot()
    cold = time.perf_counter() - started
    assert writes == []
    assert emitted == []
    assert snap["records"]["rows"] == 5000
    assert snap["records"]["used"] == 2400
    assert snap["records"]["skipped_no_selection"] == 2600
    assert snap["records"]["by_source"]["quantum"] == 2400
    assert snap["maps"] == 6
    assert len(snap["others"]) == 4                 # ≤ 4 карт помимо primary
    assert len(snap["primary"]["top_cells"]) <= 3

    durations = []
    for _ in range(20):
        began = time.perf_counter()
        await service.field_snapshot()
        durations.append(time.perf_counter() - began)
    durations.sort()
    p95 = durations[int(0.95 * (len(durations) - 1))]
    assert p95 < 0.5, (p95, cold)
    assert cold < 5.0, cold
    await db.close()


# ── T10: fail-open /api/status ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_status_block_fail_open(tmp_path, monkeypatch):
    db = await _fresh_db(tmp_path, "q07_t10.db")
    service = mrs.RandomSourceService(db)
    monkeypatch.setattr(mca_gates, "random_source_enabled", lambda: True)
    monkeypatch.setattr(mrs, "get_service", lambda db=None: service)

    healthy = await StatusService().random_source_snapshot(
        chat_id=None, is_global_admin=True)
    assert healthy["field"]["ready"] is True
    assert healthy["field"]["primary"]["state"] == "no_data"

    async def _boom(**kwargs):
        raise RuntimeError("journal unreadable")

    monkeypatch.setattr(service, "field_snapshot", _boom)
    broken = await StatusService().random_source_snapshot(
        chat_id=None, is_global_admin=True)
    assert broken["field"] == {"ready": False, "state": "unavailable"}
    assert broken["available"] is True
    assert broken["recent_draws"] == []
    # Остальные поля `random` не зависят от блока `field`.
    assert ({k: v for k, v in broken.items() if k != "field"}
            == {k: v for k, v in healthy.items() if k != "field"})
    await db.close()
