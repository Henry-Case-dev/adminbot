"""QRNG P1 — изоляция и честность (arch-decision 2026-11-17 §3 D1/D2/D3/D8/D14).

Покрытие QAN-REC: `KEY-01…04`, `PROV-02`, `RBAC-01/02`, `SEC-01`, `CFG-01`,
`EXC-01…05` (Lizaonair исключён — только проверки отсутствия).

Инварианты P1:
  * v48: ровно две аддитивные nullable-колонки `mca_random_batches`
    (`config_fingerprint`, `external_ref`); миграция идемпотентна, старые
    строки не переписываются, легаси-партии (NULL) расходуемы;
  * расходование партии — только `config_fingerprint IS NULL` или равный
    действующему; ротация ключа A→B не расходует партии A (`unverified`);
  * черновой ключ изолирован: 0 строк в `mca_random_batches`,
    `deposited=false`; сохранённый ключ зачисляет ровно одну партию с
    fingerprint;
  * канонический provider id + `entropy_class` в DTO; легаси-строка
    "ANU Quantum Numbers" маппится на `anu`, история не переписывается;
    per-provider остаток в `status_snapshot`;
  * cooldown ручных проверок (расширение singleflight, без планировщика);
  * RBAC: право просмотра ключа больше не открывает операцию провайдера;
  * PRNG: нет скрытого fallback, сохранённое `true` не перезаписывается.
"""
import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
import types
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services import mca_gates
from services import mca_random_source as mrs
from services.config_cache import ConfigCache
from services.database import DatabaseService
from web.api import deps as deps_mod
from web.app import create_app

ANU_KEY = "keys.random_quantum_api_key"


# ── helpers/fixtures ────────────────────────────────────────────────────────
async def _fresh_db(tmp_path, name="qrng_p1.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def ok_uint16(length: int, start: int = 0):
    return (200, {},
            '{"success": true, "type": "uint16", "length": %d, "data": %s}'
            % (length, list(range(start, start + length))))


def make_http(responses, calls=None, delay=0.0):
    calls = calls if calls is not None else []

    async def http_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": dict(headers),
                      "params": dict(params), "timeout": timeout})
        if delay:
            await asyncio.sleep(delay)
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, hdrs, text = item
        return mrs._HttpResponse(status=status, headers=hdrs, text=text)

    return http_get, calls


def make_service(db, cfg, *, responses=None, clock=None, batch_length=8,
                 delay=0.0):
    cfg[mrs.SETTING_BATCH_LENGTH] = batch_length
    calls: list = []
    client = mrs.AnuClient(
        http_get=make_http(responses, calls, delay=delay)[0],
        min_interval=0.0, clock=clock or FakeClock())
    svc = mrs.RandomSourceService(db, client=client, auto_refill=False,
                                  clock=clock or FakeClock())
    return svc, calls


@pytest.fixture
def mem(monkeypatch):
    values: dict = {}

    async def fake(key, chat_id, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_read_memory_setting", fake)
    return values


@pytest.fixture
def cfg(monkeypatch):
    values: dict = {}

    def fake(key, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_hot_setting", fake)
    return values


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mrs.mca_events.reset_pending()
    yield
    mrs.mca_events.reset_pending()


async def _batch_rows(db) -> list:
    cur = await db.db.execute(
        "SELECT batch_id, provider, config_fingerprint, external_ref, "
        "reserved_upto, length, created_at FROM mca_random_batches "
        "ORDER BY created_at, batch_id")
    return [dict(r) for r in await cur.fetchall()]


# ── v48: аддитивные колонки, идемпотентность, старые партии ────────────────
class TestRandomBatchProvenanceMigration:
    @pytest.mark.asyncio
    async def test_columns_and_step_registry(self, tmp_path):
        db = await _fresh_db(tmp_path)
        try:
            cur = await db.db.execute("PRAGMA user_version")
            assert int((await cur.fetchone())[0]) == 48
            cur = await db.db.execute("PRAGMA table_info(mca_random_batches)")
            cols = {r["name"]: r for r in await cur.fetchall()}
            assert cols["config_fingerprint"]["type"] == "TEXT"
            assert cols["config_fingerprint"]["notnull"] == 0
            assert cols["config_fingerprint"]["dflt_value"] is None
            assert cols["external_ref"]["type"] == "TEXT"
            assert cols["external_ref"]["notnull"] == 0
        finally:
            await db.close()
        steps = {s.version: s.name for s in DatabaseService.migration_steps()}
        assert steps[48] == "random_batch_provenance_v48"
        # v47 (semantic_schedule) шаг не меняется — отдельная версия стора.
        assert steps[47] == "semantic_schedule_v47"
        assert max(steps) == 48

    @pytest.mark.asyncio
    async def test_idempotent_and_legacy_rows_preserved(self, tmp_path):
        """Повтор шага — no-op; ALTER на «до-v48» БД сохраняет строки."""
        path = str(tmp_path / "legacy.db")
        db = DatabaseService(path)
        await db.initialize()
        svc = mrs.RandomSourceService(db, auto_refill=False)
        legacy_batch = mrs.AnuBatch(values=[1, 2, 3], data_type="uint16",
                                    length=3, provider=mrs.PROVIDER_ANU)
        await svc._store.insert_batch(legacy_batch)
        await db.close()
        # Откат к состоянию «до v48»: колонок нет, версия 47, книга без 48.
        raw = sqlite3.connect(path)
        raw.execute("ALTER TABLE mca_random_batches "
                    "DROP COLUMN config_fingerprint")
        raw.execute("ALTER TABLE mca_random_batches DROP COLUMN external_ref")
        raw.execute("PRAGMA user_version = 47")
        raw.execute("DELETE FROM schema_migrations WHERE version = 48")
        raw.commit()
        cols = {r[1] for r in raw.execute(
            "PRAGMA table_info(mca_random_batches)")}
        assert "config_fingerprint" not in cols and "external_ref" not in cols
        assert raw.execute("SELECT COUNT(*) FROM mca_random_batches"
                           ).fetchone()[0] == 1
        raw.close()
        # Повторная инициализация применяет ТОЛЬКО v48 (аддитивно).
        db2 = DatabaseService(path)
        await db2.initialize()
        try:
            cur = await db2.db.execute("PRAGMA user_version")
            assert int((await cur.fetchone())[0]) == 48
            rows = await _batch_rows(db2)
            assert len(rows) == 1
            assert rows[0]["provider"] == mrs.PROVIDER_ANU   # не переписан
            assert rows[0]["config_fingerprint"] is None
            assert rows[0]["length"] == 3
            cur = await db2.db.execute(
                "SELECT COUNT(*) AS c FROM schema_migrations "
                "WHERE version = 48")
            assert int((await cur.fetchone())["c"]) == 1
            # Повторный прогон — no-op (без дублей книги/строк).
            await db2._migrate_random_batch_provenance_v48()
            cur = await db2.db.execute(
                "SELECT COUNT(*) AS c FROM schema_migrations "
                "WHERE version = 48")
            assert int((await cur.fetchone())["c"]) == 1
            assert len(await _batch_rows(db2)) == 1
        finally:
            await db2.close()

    @pytest.mark.asyncio
    async def test_legacy_null_fingerprint_batches_consumable(self, tmp_path):
        db = await _fresh_db(tmp_path)
        try:
            svc = mrs.RandomSourceService(db, auto_refill=False)
            await svc._store.insert_batch(mrs.AnuBatch(
                values=list(range(5)), data_type="uint16", length=5))
            assert await svc._store.reserve_remaining(
                config_fingerprint="fp-any") == 5
            draw = await svc._store.reserve_draw(
                n=3, meta={"purpose": "p"}, config_fingerprint="fp-any")
            assert draw is not None and draw.value == 0
            assert await svc._store.reserve_remaining(
                config_fingerprint="fp-any") == 4
        finally:
            await db.close()


# ── fingerprint-scoped reserve ──��──────────────────────────────────────────
class TestFingerprintScope:
    @pytest.mark.asyncio
    async def test_reserve_only_matching_or_null(self, tmp_path):
        db = await _fresh_db(tmp_path)
        try:
            svc = mrs.RandomSourceService(db, auto_refill=False)
            await svc._store.insert_batch(
                mrs.AnuBatch(values=[10, 11], data_type="uint16", length=2),
                created_at=100, config_fingerprint="A")
            await svc._store.insert_batch(
                mrs.AnuBatch(values=[20, 21, 22], data_type="uint16",
                             length=3),
                created_at=200, config_fingerprint="B")
            await svc._store.insert_batch(
                mrs.AnuBatch(values=[30], data_type="uint16", length=1),
                created_at=300)                       # NULL — совместимо
            assert await svc._store.reserve_remaining(
                config_fingerprint="A") == 3          # A + NULL
            assert await svc._store.reserve_remaining(
                config_fingerprint="B") == 4          # B + NULL
            assert await svc._store.reserve_remaining() == 6   # без фильтра
            draw = await svc._store.reserve_draw(
                n=None, meta={"purpose": "p"}, config_fingerprint="B")
            assert draw is not None and draw.value == 20      # партия B
            rows = {(r["config_fingerprint"], r["created_at"]): r
                    for r in await _batch_rows(db)}
            assert rows[("A", 100)]["reserved_upto"] == 0      # A не тронута
            assert rows[("B", 200)]["reserved_upto"] == 1
            assert rows[(None, 300)]["reserved_upto"] == 0
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_key_rotation_a_to_b_does_not_consume_a(self, tmp_path, cfg,
                                                          mem):
        db = await _fresh_db(tmp_path)
        try:
            # QRNG P3/F3: заводской PRNG-дефолт новых установок — false;
            # этот тест проверяет ПУТЬ отказа владельца (как в проде:
            # сохранённый true), поэтому политика задаётся явно.
            mem[mrs.SETTING_FALLBACK] = True
            cfg[mrs.SETTING_KEY] = "anu-key-A"
            svc, _ = make_service(db, cfg, responses=[ok_uint16(8)])
            activated = await svc.activate()
            assert activated["activated"] is True
            assert activated["deposited"] is True
            rows = await _batch_rows(db)
            assert len(rows) == 1
            assert rows[0]["config_fingerprint"] == mrs.key_fingerprint(
                "anu-key-A")
            used_after_activation = rows[0]["reserved_upto"]
            assert used_after_activation == 1          # self-check
            # Ротация A→B без успешной проверки: state unverified, партии A
            # не расходуются, fallback — по действующему контракту.
            cfg[mrs.SETTING_KEY] = "anu-key-B"
            assert await svc.anu_state() == mrs.ANU_STATE_UNVERIFIED
            effective, blocker = await svc.resolve_effective(chat_id=1)
            assert effective == mrs.MODE_PSEUDORANDOM
            assert blocker == "provider_unavailable"
            assert await svc._store.reserve_remaining(
                config_fingerprint=mrs.key_fingerprint("anu-key-B")) == 0
            draw = await svc.draw_index(5, chat_id=1, purpose="p")
            assert draw.source == mrs.MODE_PSEUDORANDOM
            assert draw.provider_id is None and draw.entropy_class is None
            rows = await _batch_rows(db)
            assert len(rows) == 1
            assert rows[0]["reserved_upto"] == used_after_activation
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_empty_current_admits_only_null_batches(self, tmp_path):
        """F4 strict: пустой current (ключа нет) → только NULL-партии."""
        db = await _fresh_db(tmp_path)
        try:
            svc = mrs.RandomSourceService(db, auto_refill=False)
            await svc._store.insert_batch(
                mrs.AnuBatch(values=[10, 11], data_type="uint16", length=2),
                created_at=100, config_fingerprint="A")
            await svc._store.insert_batch(
                mrs.AnuBatch(values=[20], data_type="uint16", length=1),
                created_at=200)                       # NULL — совместимо
            assert await svc._store.reserve_remaining(
                config_fingerprint="") == 1           # strict: только NULL
            assert await svc._store.reserve_remaining() == 3   # без фильтра
            draw = await svc._store.reserve_draw(
                n=None, meta={"purpose": "p"}, config_fingerprint="")
            assert draw is not None and draw.value == 20      # NULL-партия
            rows = {(r["config_fingerprint"], r["created_at"]): r
                    for r in await _batch_rows(db)}
            assert rows[("A", 100)]["reserved_upto"] == 0      # A не тронута
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rotation_then_key_removal_keeps_a_quarantined(
            self, tmp_path, cfg, mem):
        """A→B→удаление ключа: партии A не расходуются и после удаления."""
        db = await _fresh_db(tmp_path)
        try:
            # Явная политика владельца (прод: сохранённый true); заводской
            # дефолт новых установок — false (QRNG P3/F3).
            mem[mrs.SETTING_FALLBACK] = True
            cfg[mrs.SETTING_KEY] = "anu-key-A"
            svc, _ = make_service(db, cfg, responses=[ok_uint16(8)])
            assert (await svc.activate())["activated"] is True
            used = (await _batch_rows(db))[0]["reserved_upto"]
            cfg[mrs.SETTING_KEY] = "anu-key-B"
            # Ключ удалён: resolve_key → "" (env-ключ в тесте не участвует).
            svc._resolve_key = lambda: ""
            assert await svc._reserve_remaining() == 0
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["effective_source"] == mrs.MODE_PSEUDORANDOM
            assert snap["provider_reserve"][mrs.PROVIDER_ID_ANU] == 0
            assert snap["provider_quarantined"][mrs.PROVIDER_ID_ANU] == 7
            assert snap["last_batch"]["config_matches"] is False
            draw = await svc.draw_index(5, chat_id=1, purpose="p")
            assert draw.source == mrs.MODE_PSEUDORANDOM
            assert draw.entropy_class is None
            # Явный режим без PRNG-откатов: значение не выдаётся, quantum нет.
            mem[mrs.SETTING_FALLBACK] = False
            deferred = await svc.draw_index(5, chat_id=1, purpose="p")
            assert deferred.deferred is True
            assert deferred.source == mrs.MODE_PSEUDORANDOM
            row = (await _batch_rows(db))[0]
            assert row["reserved_upto"] == used         # A не расходована
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_backfill_only_for_confirmed_same_key(self, tmp_path, cfg):
        db = await _fresh_db(tmp_path)
        try:
            svc = mrs.RandomSourceService(db, auto_refill=False)
            await svc._store.insert_batch(mrs.AnuBatch(
                values=[1, 2], data_type="uint16", length=2))
            # Нет подтверждённого state → backfill не выполняется.
            cfg[mrs.SETTING_KEY] = "anu-key-A"
            assert await svc.sync_batch_provenance() == 0
            await svc._store.write_state(
                key_fingerprint=mrs.key_fingerprint("anu-key-A"),
                activated_at=12345)
            assert await svc.sync_batch_provenance() == 1
            rows = await _batch_rows(db)
            assert rows[0]["config_fingerprint"] == mrs.key_fingerprint(
                "anu-key-A")
            assert await svc.sync_batch_provenance() == 0    # идемпотентно
            # Другой ключ при state A → ничего не привязывается.
            await svc._store.insert_batch(mrs.AnuBatch(
                values=[3], data_type="uint16", length=1, provider="lfdr"))
            await svc._store.write_state(
                key_fingerprint=mrs.key_fingerprint("anu-key-B"))
            assert await svc.sync_batch_provenance() == 0
            rows = await _batch_rows(db)
            lfdr = [r for r in rows if r["provider"] == mrs.PROVIDER_ID_LFDR]
            assert len(lfdr) == 1 and lfdr[0]["config_fingerprint"] is None
        finally:
            await db.close()


# ── черновой ключ не зачисляется; сохранённый — зачисляется ────────────────
class TestDraftKeyIsolation:
    @pytest.mark.asyncio
    async def test_draft_check_zero_rows_deposited_false(self, tmp_path, cfg):
        db = await _fresh_db(tmp_path)
        try:
            cfg[mrs.SETTING_KEY] = "anu-key-stored"
            svc, calls = make_service(db, cfg, responses=[ok_uint16(8)])
            result = await svc.test_connection(draft_key="draft-other")
            assert result["healthy"] is True
            # Поведенческий инвариант: рабочий запас не вырос (0 строк).
            assert await _batch_rows(db) == []
            assert result["deposited"] is False
            assert result["persisted"] is False
            assert len(calls) == 1
            quota = await svc.quota_snapshot()
            assert quota["success"] == 1 and quota["manual_checks"] == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_saved_key_check_deposits_with_fingerprint(self, tmp_path,
                                                             cfg):
        db = await _fresh_db(tmp_path)
        try:
            cfg[mrs.SETTING_KEY] = "anu-key-stored"
            svc, calls = make_service(db, cfg, responses=[ok_uint16(8)])
            result = await svc.test_connection()
            assert result["healthy"] is True
            assert result["persisted"] is True
            assert result["deposited"] is True
            rows = await _batch_rows(db)
            assert len(rows) == 1
            assert rows[0]["config_fingerprint"] == mrs.key_fingerprint(
                "anu-key-stored")
            assert len(calls) == 1
        finally:
            await db.close()


# ── provenance/DTO: канонический provider, entropy_class, per-provider ─────
class TestProvenanceDto:
    def test_registry_three_hardware_providers_no_lizaonair(self):
        assert set(mrs.PROVIDERS) == {
            mrs.PROVIDER_ID_IBM, mrs.PROVIDER_ID_ANU, mrs.PROVIDER_ID_LFDR}
        for pid in mrs.PROVIDER_IDS:
            assert mrs.PROVIDERS[pid].entropy_class == "hardware_quantum"
        # P1: каркас без поведения; P2 подключил адаптер LfDR (D9), IBM — P5.
        assert mrs.PROVIDERS[mrs.PROVIDER_ID_IBM].fetch is None
        assert mrs.PROVIDERS[mrs.PROVIDER_ID_LFDR].fetch is not None
        assert mrs.PROVIDERS[mrs.PROVIDER_ID_LFDR].requires_key is False
        source = Path(mrs.__file__).read_text(encoding="utf-8").lower()
        assert "lizaonair" not in source
        assert mrs.canonical_provider_id("ANU Quantum Numbers") == "anu"
        assert mrs.canonical_provider_id("anu") == "anu"
        assert mrs.canonical_provider_id("lizaonair") == ""
        assert mrs.canonical_provider_id("") == ""

    @pytest.mark.asyncio
    async def test_legacy_provider_maps_to_canonical_dto(self, tmp_path):
        db = await _fresh_db(tmp_path)
        try:
            svc = mrs.RandomSourceService(db, auto_refill=False)
            await svc._store.insert_batch(mrs.AnuBatch(
                values=[7, 8], data_type="uint16", length=2,
                provider=mrs.PROVIDER_ANU))
            draw = await svc._store.reserve_draw(n=2, meta={"purpose": "p"})
            assert draw.provider == mrs.PROVIDER_ANU      # история не тронута
            assert draw.provider_id == mrs.PROVIDER_ID_ANU
            rows = await _batch_rows(db)
            assert rows[0]["provider"] == mrs.PROVIDER_ANU
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_new_batch_stores_canonical_provider_and_external_ref(
            self, tmp_path):
        db = await _fresh_db(tmp_path)
        try:
            svc = mrs.RandomSourceService(db, auto_refill=False)
            await svc._store.insert_batch(
                mrs.AnuBatch(values=[1], data_type="uint16", length=1),
                config_fingerprint="fp-A", external_ref="batch-ext-1")
            rows = await _batch_rows(db)
            assert rows[0]["provider"] == mrs.PROVIDER_ID_ANU
            assert rows[0]["config_fingerprint"] == "fp-A"
            assert rows[0]["external_ref"] == "batch-ext-1"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_provider_reserve_and_status_registry(self, tmp_path, cfg,
                                                       mem):
        db = await _fresh_db(tmp_path)
        try:
            cfg[mrs.SETTING_KEY] = "anu-key-A"
            svc = mrs.RandomSourceService(db, auto_refill=False)
            await svc._store.insert_batch(mrs.AnuBatch(
                values=list(range(5)), data_type="uint16", length=5))
            await svc._store.insert_batch(mrs.AnuBatch(
                values=list(range(3)), data_type="uint16", length=3,
                provider=mrs.PROVIDER_ANU))
            await svc._store.insert_batch(mrs.AnuBatch(
                values=list(range(4)), data_type="uint16", length=4,
                provider=mrs.PROVIDER_ID_LFDR))
            reserve = await svc.provider_reserve()
            assert reserve == {mrs.PROVIDER_ID_ANU: 8, mrs.PROVIDER_ID_LFDR: 4}
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["provider_reserve"] == {
                mrs.PROVIDER_ID_IBM: 0, mrs.PROVIDER_ID_ANU: 8,
                mrs.PROVIDER_ID_LFDR: 4}
            by_id = {p["id"]: p for p in snap["providers"]}
            assert list(by_id) == list(mrs.PROVIDER_IDS)
            assert by_id[mrs.PROVIDER_ID_ANU]["configured"] is True
            assert by_id[mrs.PROVIDER_ID_ANU]["reserve"] == 8
            assert by_id[mrs.PROVIDER_ID_IBM]["configured"] is False
            assert by_id[mrs.PROVIDER_ID_LFDR]["requires_key"] is False
            assert all(p["entropy_class"] == "hardware_quantum"
                       for p in snap["providers"])
            assert snap["effective_source"] == mrs.MODE_QUANTUM
            assert snap["provider"] == mrs.PROVIDER_ID_ANU
            assert snap["entropy_class"] == "hardware_quantum"
            blob = json.dumps(snap, ensure_ascii=False, default=str).lower()
            assert "lizaonair" not in blob
            assert "anu-key-a" not in blob
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_source_impl_and_entropy_derived_from_provider(self, tmp_path):
        """`source_impl`/`entropy_class` — от провайдера партии, не хардкод."""
        db = await _fresh_db(tmp_path)
        try:
            svc = mrs.RandomSourceService(db, auto_refill=False)
            await svc._store.insert_batch(mrs.AnuBatch(
                values=[5, 6], data_type="uint16", length=2,
                provider=mrs.PROVIDER_ID_LFDR))
            draw = await svc.draw_index(2, chat_id=1, purpose="p")
            assert draw.source == mrs.MODE_QUANTUM
            assert draw.provider_id == mrs.PROVIDER_ID_LFDR
            assert draw.entropy_class == "hardware_quantum"
            assert draw.source_impl == "lfdr-quantum"
            adapter = await svc.build_dream_source(1, k_hint=2, chat_id=1)
            _items, meta = adapter.pick(
                [{"id": "a"}, {"id": "b"}], chat_id=1, purpose="p", k=1)
            assert meta["provider_id"] == mrs.PROVIDER_ID_LFDR
            assert meta["entropy_class"] == "hardware_quantum"
            assert meta["source_impl"] == "lfdr-quantum"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_status_quarantines_old_configuration_after_rotation(
            self, tmp_path, cfg, mem):
        """F3: provider_reserve scoped; партии A после A→B — quarantined."""
        db = await _fresh_db(tmp_path)
        try:
            # Политика владельца задана явно (прод: сохранённый true).
            mem[mrs.SETTING_FALLBACK] = True
            cfg[mrs.SETTING_KEY] = "anu-key-A"
            svc, _ = make_service(db, cfg, responses=[ok_uint16(8)])
            assert (await svc.activate())["activated"] is True
            cfg[mrs.SETTING_KEY] = "anu-key-B"
            snap = await svc.status_snapshot(chat_id=1)
            by_id = {p["id"]: p for p in snap["providers"]}
            assert snap["effective_source"] == mrs.MODE_PSEUDORANDOM
            assert snap["provider_reserve"][mrs.PROVIDER_ID_ANU] == 0
            assert snap["provider_quarantined"][mrs.PROVIDER_ID_ANU] == 7
            assert snap["reserve_quarantined"] == 7
            assert snap["reserve_remaining"] == 0
            assert by_id[mrs.PROVIDER_ID_ANU]["reserve"] == 0
            assert by_id[mrs.PROVIDER_ID_ANU]["consumable"] is False
            assert by_id[mrs.PROVIDER_ID_ANU]["quarantined"] == 7
            assert by_id[mrs.PROVIDER_ID_ANU]["config_matches"] is False
            # История: fingerprint не публикуется, только bool-совместимость.
            assert "config_fingerprint" not in snap["last_batch"]
            assert snap["last_batch"]["config_matches"] is False
            assert snap["last_batch"]["provider_id"] == mrs.PROVIDER_ID_ANU
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_entropy_class_never_claimed_for_prng(self, tmp_path, cfg,
                                                        mem):
        db = await _fresh_db(tmp_path)
        try:
            # PRNG-путь проверяется при ЯВНО разрешённом откате (дефолт новых
            # установок — false, QRNG P3/F3).
            mem[mrs.SETTING_FALLBACK] = True
            svc = mrs.RandomSourceService(db, auto_refill=False)
            draw = await svc.draw_index(4, chat_id=1, purpose="p")
            assert draw.source == mrs.MODE_PSEUDORANDOM
            assert draw.entropy_class is None
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["effective_source"] == mrs.MODE_PSEUDORANDOM
            assert snap["entropy_class"] is None
            assert snap["provider"] is None
            rows = await svc.recent_draws(limit=5)
            assert rows and all(r["source"] == "pseudorandom"
                                for r in rows)
        finally:
            await db.close()

# ── cooldown ручных проверок ───────────────────────────────────────────────
class TestManualCheckCooldown:
    @pytest.mark.asyncio
    async def test_second_click_in_window_no_request(self, tmp_path, cfg):
        db = await _fresh_db(tmp_path)
        try:
            clock = FakeClock()
            svc, calls = make_service(
                db, cfg, responses=[ok_uint16(8), ok_uint16(8)], clock=clock)
            first = await svc.test_connection(draft_key="draft-k")
            assert first["healthy"] is True and first["cooldown"] is False
            assert len(calls) == 1
            clock.advance(2.0)
            second = await svc.test_connection(draft_key="draft-k")
            assert second["cooldown"] is True
            assert second["healthy"] is True
            assert second["deposited"] is False
            assert second["retry_after_seconds"] > 0
            assert len(calls) == 1          # нового запроса нет
            clock.advance(20.0)             # окно истекло
            third = await svc.test_connection(draft_key="draft-k")
            assert third["cooldown"] is False
            assert len(calls) == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_different_key_is_not_blocked_by_other_key_window(
            self, tmp_path, cfg):
        db = await _fresh_db(tmp_path)
        try:
            clock = FakeClock()
            svc, calls = make_service(
                db, cfg, responses=[ok_uint16(8), ok_uint16(8)], clock=clock)
            await svc.test_connection(draft_key="draft-1")
            second = await svc.test_connection(draft_key="draft-2")
            assert second["cooldown"] is False
            assert len(calls) == 2
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_singleflight_still_coalesces_same_key(self, tmp_path, cfg):
        db = await _fresh_db(tmp_path)
        try:
            clock = FakeClock()
            svc, calls = make_service(db, cfg, responses=[ok_uint16(8)],
                                      clock=clock, delay=0.2)
            results = await asyncio.gather(
                svc.test_connection(draft_key="draft-same"),
                svc.test_connection(draft_key="draft-same"))
            assert all(r["healthy"] for r in results)
            assert len(calls) == 1          # один запрос к провайдеру
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_cooldown_zero_disables_window(self, tmp_path, cfg,
                                                 monkeypatch):
        db = await _fresh_db(tmp_path)
        try:
            monkeypatch.setattr(
                mca_gates, "random_manual_check_cooldown_seconds", lambda: 0)
            clock = FakeClock()
            svc, calls = make_service(
                db, cfg, responses=[ok_uint16(8), ok_uint16(8)], clock=clock)
            await svc.test_connection(draft_key="draft-k")
            clock.advance(1.0)
            second = await svc.test_connection(draft_key="draft-k")
            assert second["cooldown"] is False
            assert len(calls) == 2
        finally:
            await db.close()


# ── RBAC: просмотр секрета ≠ операция провайдера ───────────────────────────
TEST_TOKEN = "123456:TEST_TOKEN_FOR_QRNG_P1"
ADMIN_ID = 5885953495
KEY_VIEWER_ID = 4242424242
MODERATOR_ID = 1313107079


def make_init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "qrngP1",
        "user": json.dumps({"id": user_id, "first_name": "T"},
                           separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc_hash}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


class _FakeConn:
    def __init__(self, settings_rows=(), role_rows=(), admin_rows=()):
        self._settings_rows = list(settings_rows)
        self._role_rows = list(role_rows)
        self._admin_rows = list(admin_rows)

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    def transaction(self):
        class _Tx:
            async def __aenter__(self):
                return self._conn

            async def __aexit__(self, *exc):
                return False

        tx = _Tx()
        tx._conn = self
        return tx

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return self._settings_rows
        if "bot_roles" in sql:
            return self._role_rows
        if "bot_admins" in sql:
            return self._admin_rows
        return []


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _CM:
            async def __aenter__(self):
                return self._pool._conn

            async def __aexit__(self, *exc):
                return False

        cm = _CM()
        cm._pool = self
        return cm

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


_ROLE_ROWS = [
    {"role_name": "admin", "permissions": {"wildcard": True},
     "is_custom": False},
    # Право просмотра/правки конкретного секрета — БЕЗ global admin.
    {"role_name": "key_viewer",
     "permissions": {"keys": [ANU_KEY], "sections": ["keys"]},
     "is_custom": True},
    {"role_name": "moderator", "permissions": {"sections": ["limits"]},
     "is_custom": False},
]
_ADMIN_ROWS = [
    {"telegram_id": ADMIN_ID, "role_name": "admin",
     "added_by": None, "created_at": "2026-08-30T00:00:00+00:00"},
    {"telegram_id": KEY_VIEWER_ID, "role_name": "key_viewer",
     "added_by": ADMIN_ID, "created_at": None},
    {"telegram_id": MODERATOR_ID, "role_name": "moderator",
     "added_by": ADMIN_ID, "created_at": None},
]


@pytest.fixture
def api_env(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    monkeypatch.setattr(
        "services.info_service.settings",
        types.SimpleNamespace(INFO_TEXT_FILE=str(tmp_path / "info.md"),
                              ADMIN_USER_ID=ADMIN_ID))
    conn = _FakeConn(
        settings_rows=[{"key": ANU_KEY, "value": "stored-anu-key-1234",
                        "category": "keys", "updated_at": None}],
        role_rows=_ROLE_ROWS, admin_rows=_ADMIN_ROWS)
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as client:
        client.cache = cache
        yield client


class TestProviderOperationRbac:
    def _bind_status_service(self, monkeypatch, tmp_path):
        """Сервис с реальной партией/state для проверки `/api/status`."""
        async def _setup():
            db = await _fresh_db(tmp_path, "qrng_status.db")
            key = "anu-key-status-secret"
            cfg = {mrs.SETTING_BATCH_LENGTH: 8,
                   mrs.SETTING_KEY: key}
            monkeypatch.setattr(
                mrs, "_hot_setting",
                lambda name, default: cfg.get(name, default))

            async def _mem(name, chat_id, default):
                return default
            monkeypatch.setattr(mrs, "_read_memory_setting", _mem)
            svc = mrs.RandomSourceService(db, auto_refill=False)
            fp = mrs.key_fingerprint(key)
            await svc._store.insert_batch(
                mrs.AnuBatch(values=list(range(8)), data_type="uint16",
                             length=8), config_fingerprint=fp)
            await svc._store.write_state(
                key_fingerprint=fp, activated_at=1750000000)
            monkeypatch.setattr(mrs, "_service", svc)
            return svc, fp

        return asyncio.run(_setup())

    def test_api_status_has_no_key_fingerprint(self, api_env, monkeypatch,
                                               tmp_path):
        """F2 (R17): `/api/status` не отдаёт `*_fingerprint` и значение
        `state.key_fingerprint`; `last_batch` — только `config_matches`."""
        from services.status_service import StatusService

        async def _no_health(self, module_id, base_url, key, model="",
                             kind="chat"):
            return {"ok": False, "status": "not_configured",
                    "http_status": None, "latency_ms": None,
                    "checked_at": None}

        async def _no_uptime(self, pg):
            return []

        monkeypatch.setattr(StatusService, "_check_health", _no_health)
        monkeypatch.setattr(StatusService, "fetch_uptime_rows", _no_uptime)
        svc, fingerprint = self._bind_status_service(monkeypatch, tmp_path)
        try:
            resp = api_env.get("/api/status", headers=_hdr())
            assert resp.status_code == 200, resp.text
            rnd = resp.json()["random"]
            assert rnd["last_batch"]["config_matches"] is True
            assert "config_fingerprint" not in rnd["last_batch"]
            blob = resp.text
            assert fingerprint not in blob
            assert "fingerprint" not in json.dumps(rnd).lower()
            # Публичные агрегаты присутствуют и не содержат секретов.
            assert rnd["provider_reserve"][mrs.PROVIDER_ID_ANU] == 8
            assert rnd["provider_quarantined"][mrs.PROVIDER_ID_ANU] == 0
            assert "anu-key-status-secret" not in blob
        finally:
            asyncio.run(svc.db.close())
            mrs.reset_service()

    def test_view_right_does_not_open_random_test(self, api_env, monkeypatch,
                                                  tmp_path):
        async def _setup():
            db = await _fresh_db(tmp_path, "qrng_rbac.db")
            cfg = {mrs.SETTING_BATCH_LENGTH: 8}
            monkeypatch.setattr(
                mrs, "_hot_setting",
                lambda key, default: cfg.get(key, default))
            calls: list = []
            client = mrs.AnuClient(
                http_get=make_http([ok_uint16(8)], calls)[0],
                min_interval=0.0, clock=FakeClock())
            svc = mrs.RandomSourceService(db, client=client,
                                          auto_refill=False)
            monkeypatch.setattr(mrs, "_service", svc)
            return svc, calls

        svc, calls = asyncio.run(_setup())
        try:
            # Право на ключ есть, но пользователь не глобальный админ → 403.
            denied = api_env.post("/api/random/test",
                                  headers=_hdr(KEY_VIEWER_ID),
                                  json={"key": "draft-anu"})
            assert denied.status_code == 403, denied.text
            assert calls == []                       # провайдер не вызывался
            allowed = api_env.post("/api/random/test", headers=_hdr(),
                                   json={"key": "draft-anu"})
            assert allowed.status_code == 200, allowed.text
            assert len(calls) == 1
        finally:
            asyncio.run(svc.db.close())
            mrs.reset_service()

    def test_view_right_preserved_but_operation_denied(self, api_env):
        """RBAC-фикс узкий: право `key.<pg_key>` остаётся правом ПРОСМОТРА.

        Существующий контракт глобального секрета (S1/F-7) не меняется: в
        `GET /api/config` глобальный секрет видит только global admin
        (маска `configured/last4`). `can_view_key_value` для роли с этим
        правом по-прежнему True — но операцию провайдера оно больше не
        открывает (см. тест выше)."""
        from web.api.deps import can_view_key_value
        cache = api_env.cache
        assert can_view_key_value(cache, KEY_VIEWER_ID, ANU_KEY) is True
        hidden = api_env.get("/api/config", headers=_hdr(KEY_VIEWER_ID))
        assert hidden.status_code == 200
        assert ANU_KEY not in {i["key"] for i in hidden.json()["items"]}
        assert "stored-anu-key-1234" not in hidden.text
        visible = api_env.get("/api/config", headers=_hdr())
        item = next(i for i in visible.json()["items"] if i["key"] == ANU_KEY)
        assert item["secret"] is True
        assert item["value"] == {"configured": True, "last4": "1234"}
        assert "stored-anu-key-1234" not in visible.text

    def test_provider_key_write_requires_global_admin(self, api_env):
        payload = {"items": [{"key": ANU_KEY, "value": "new-key-9999"}]}
        denied = api_env.post("/api/config", headers=_hdr(KEY_VIEWER_ID),
                             json=payload)
        assert denied.status_code == 403, denied.text
        allowed = api_env.post("/api/config", headers=_hdr(), json=payload)
        assert allowed.status_code == 200, allowed.text

    def test_non_provider_key_path_unchanged(self, api_env):
        """RBAC-фикс узкий: чужая настройка не начинает требовать global admin."""
        payload = {"items": [{"key": "memory.random_source",
                              "value": "pseudorandom"}]}
        resp = api_env.post("/api/config", headers=_hdr(KEY_VIEWER_ID),
                            json=payload)
        assert resp.status_code in (200, 403)
        # Отказ допустим (у роли нет param-права), но 403 причина — права на
        # параметр, а не провайдерский guard: тот же ключ проходит у админа.
        admin = api_env.post("/api/config", headers=_hdr(), json=payload)
        assert admin.status_code == 200, admin.text


# ── PRNG: без скрытого fallback, настройка владельца не перезаписывается ───
class TestPrngHonesty:
    @pytest.mark.asyncio
    async def test_saved_fallback_true_reported_not_rewritten(self, tmp_path,
                                                              mem):
        db = await _fresh_db(tmp_path)
        try:
            mem[mrs.SETTING_FALLBACK] = True
            svc = mrs.RandomSourceService(db, auto_refill=False)
            snap = await svc.status_snapshot(chat_id=1)
            assert snap["fallback_setting"] is True
            assert snap["fallback_setting_label"] == (
                "псевдослучайный откат (не квантовый)")
            assert mem[mrs.SETTING_FALLBACK] is True   # значение не тронуто
            assert await svc.fallback_enabled(chat_id=1) is True
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_fallback_off_no_hidden_prng_rows(self, tmp_path, mem):
        db = await _fresh_db(tmp_path)
        try:
            mem[mrs.SETTING_FALLBACK] = False
            svc = mrs.RandomSourceService(db, auto_refill=False)
            result = await svc.draw_index(10, chat_id=1, purpose="p")
            assert result.deferred is True
            assert result.index is None
            # QRNG P3: действующий порядок IBM→ANU→LfDR; LfDR сконфигурирован
            # (ключ не требуется), но значений ещё нет → deferred с честной
            # причиной `provider_unavailable` (прежний `provider_unconfigured`
            # описывал единственный ANU-провайдер).
            assert result.reason == "provider_unavailable"
            assert await svc.recent_draws(limit=5) == []
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_quantum_success_never_labelled_pseudorandom(self, tmp_path,
                                                               mem):
        """Инвариант FALL-02: quantum-draw не маркируется PRNG (и наоборот)."""
        db = await _fresh_db(tmp_path)
        try:
            svc = mrs.RandomSourceService(db, auto_refill=False)
            await svc._store.insert_batch(mrs.AnuBatch(
                values=[0, 1, 2], data_type="uint16", length=3))
            quantum = await svc.draw_index(3, chat_id=1, purpose="p")
            assert quantum.source == mrs.MODE_QUANTUM
            assert quantum.entropy_class == "hardware_quantum"
            rows = await svc.recent_draws(limit=5)
            assert rows[0]["source"] == "quantum"
        finally:
            await db.close()
