"""F-01 (delta-review 2.58.217): self-check активации расходует ТОЛЬКО
зачисленную партию (`batch_id`), а журнал/state называют именно её.

Контракт:
  * self-check активации не берёт значение из более старой LfDR/NULL-партии;
    `activation_batch_id` = партия, из которой реально израсходовано значение;
  * если в целевой партии нет расходуемого значения — честный отказ
    (`_confirm_activation` False), без расхода чужой партии и без записи
    ложного activation state;
  * одиночная партия — прежнее поведение (регрессия отсутствует);
  * `reserve_chunk(batch_id=None)` сохраняет прежний порядок выбора для
    существующих вызовов (refill/dream chunk); пустой/неизвестный batch_id
    не расходует ничего.
"""
import pytest

from services import mca_random_source as mrs
from services.database import DatabaseService


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    mrs.mca_events.reset_pending()
    yield
    mrs.mca_events.reset_pending()


async def _fresh_db(tmp_path, name="qrng_f01.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


@pytest.fixture
def mem(monkeypatch):
    values: dict = {}

    async def fake(key, chat_id, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_read_memory_setting", fake)
    return values


@pytest.fixture
def cfg(monkeypatch):
    values: dict = {"keys.random_quantum_batch_length": 8}

    def fake(key, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_hot_setting", fake)
    return values


def ok_uint16(length: int, start: int = 0):
    return (200, {}, '{"success": true, "type": "uint16", "length": %d, '
                     '"data": %s}' % (length, list(range(start, start + length))))


def make_service(db):
    calls: list = []

    async def http_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": dict(headers),
                      "params": dict(params)})
        item = _RESPONSES.pop(0)
        return mrs._HttpResponse(status=item[0], headers=item[1],
                                 text=item[2])

    client = mrs.AnuClient(http_get=http_get, min_interval=0.0)
    svc = mrs.RandomSourceService(db, client=client, auto_refill=False)
    return svc, calls


_RESPONSES: list = []


async def _batch_row(db, batch_id: str) -> dict | None:
    cursor = await db.db.execute(
        "SELECT batch_id, provider, data_type, length, reserved_upto, "
        "consumed_upto, config_fingerprint FROM mca_random_batches "
        "WHERE batch_id = ?", (batch_id,))
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def _exhaust_batch(db, batch_id: str) -> None:
    """Смоделировать партию без расходуемого значения (crash/повтор)."""

    async def _body(conn):
        await conn.execute(
            "UPDATE mca_random_batches SET reserved_upto = length "
            "WHERE batch_id = ?", (batch_id,))
        return True

    await db.write_transaction(_body, op_name="test_exhaust_batch")


async def _insert_lfdr_batch(store) -> str:
    return await store.insert_batch(
        mrs.AnuBatch(values=[10, 11, 12, 13, 14, 15, 16, 17],
                     data_type="uint8", length=8,
                     provider=mrs.PROVIDER_ID_LFDR),
        created_at=100, config_fingerprint=None)


@pytest.mark.asyncio
async def test_activation_selfcheck_consumes_only_new_anu_batch(
        tmp_path, cfg, mem):
    """Смешанные партии: старая LfDR (NULL) не расходуется self-check'ом."""
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        store = mrs.RandomStore(db)
        lfdr_id = await _insert_lfdr_batch(store)
        _RESPONSES[:] = [ok_uint16(8)]
        svc, calls = make_service(db)

        result = await svc.activate()

        assert result["activated"] is True
        assert result["state"] == mrs.ANU_STATE_ACTIVE
        anu_id = result["batch_id"]
        assert anu_id and anu_id != lfdr_id
        state = await svc._store.get_state()
        assert state is not None
        assert state["activation_batch_id"] == anu_id
        assert state["key_fingerprint"] == mrs.key_fingerprint("anu-key-A")

        anu = await _batch_row(db, anu_id)
        old = await _batch_row(db, lfdr_id)
        assert (anu["reserved_upto"], anu["consumed_upto"]) == (1, 1)
        assert (old["reserved_upto"], old["consumed_upto"]) == (0, 0)

        rows = await svc.recent_draws(limit=10)
        assert len(rows) == 1
        assert rows[0]["purpose"] == mrs.PURPOSE_ACTIVATION_SELFCHECK
        assert rows[0]["batch_id"] == anu_id
        assert rows[0]["provider"] == mrs.PROVIDER_ID_ANU
        assert rows[0]["source"] == mrs.MODE_QUANTUM
        assert len(calls) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_activation_no_value_in_target_batch_is_honest_failure(
        tmp_path, cfg, mem):
    """Нет значения в новой партии → отказ, чужая партия не расходуется."""
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        fingerprint = mrs.key_fingerprint("anu-key-A")
        store = mrs.RandomStore(db)
        lfdr_id = await _insert_lfdr_batch(store)
        anu_id = await store.insert_batch(
            mrs.AnuBatch(values=list(range(8)), data_type="uint16", length=8),
            created_at=200, config_fingerprint=fingerprint)
        await _exhaust_batch(db, anu_id)
        _RESPONSES[:] = []
        svc, calls = make_service(db)

        activated = await svc._confirm_activation(anu_id)

        assert activated is False
        assert await svc._store.get_state() is None
        old = await _batch_row(db, lfdr_id)
        anu = await _batch_row(db, anu_id)
        assert (old["reserved_upto"], old["consumed_upto"]) == (0, 0)
        assert anu["consumed_upto"] == 0
        assert await svc.recent_draws(limit=5) == []
        assert calls == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_single_batch_activation_journal_and_state_agree(tmp_path, cfg,
                                                               mem):
    """Одиночная партия: прежнее поведение, журнал = state = партия."""
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        _RESPONSES[:] = [ok_uint16(8)]
        svc, _calls = make_service(db)

        result = await svc.activate()

        assert result["activated"] is True
        batch_id = result["batch_id"]
        state = await svc._store.get_state()
        assert state["activation_batch_id"] == batch_id
        rows = await svc.recent_draws(limit=10)
        self_check = [r for r in rows
                      if r["purpose"] == mrs.PURPOSE_ACTIVATION_SELFCHECK]
        assert len(self_check) == 1
        assert self_check[0]["batch_id"] == batch_id
        anu = await _batch_row(db, batch_id)
        assert (anu["reserved_upto"], anu["consumed_upto"]) == (1, 1)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reserve_chunk_batch_scope_exact_and_empty_safe(tmp_path):
    """Store API: точный batch_id; пустой/неизвестный — без расхода."""
    db = await _fresh_db(tmp_path)
    try:
        fingerprint = mrs.key_fingerprint("anu-key-A")
        store = mrs.RandomStore(db)
        lfdr_id = await _insert_lfdr_batch(store)
        anu_id = await store.insert_batch(
            mrs.AnuBatch(values=list(range(8)), data_type="uint16", length=8),
            created_at=200, config_fingerprint=fingerprint)

        chunk = await store.reserve_chunk(1, config_fingerprint=fingerprint,
                                          batch_id=anu_id)
        assert [c.batch_id for c in chunk] == [anu_id]
        old = await _batch_row(db, lfdr_id)
        assert (old["reserved_upto"], old["consumed_upto"]) == (0, 0)

        assert await store.reserve_chunk(
            1, config_fingerprint=fingerprint, batch_id="") == []
        assert await store.reserve_chunk(
            1, config_fingerprint=fingerprint, batch_id="missing") == []
        old = await _batch_row(db, lfdr_id)
        assert (old["reserved_upto"], old["consumed_upto"]) == (0, 0)

        # прежний вызов без batch_id не изменил порядок (самая старая партия)
        legacy = await store.reserve_chunk(1, config_fingerprint=fingerprint)
        assert [c.batch_id for c in legacy] == [lfdr_id]
    finally:
        await db.close()
