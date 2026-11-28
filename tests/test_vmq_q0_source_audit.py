"""VMQ-ONTO-01 Q-01 — source audit контура случайности (`mca_random_source`).

Инкремент A (`vmq-q0`): закрываем НЕДОСТАЮЩИЙ evidence строки Q-01
(«один RandomSourceService, реестр провайдеров, mapping legacy-настроек»),
не меняя продукт.

Что проверяется на наблюдаемом контракте:
  1. Реестр закрыт ровно тремя действующими id `ibm_quantum`/`anu`/`lfdr`;
     снятых/неизвестных имён (`lizaonair`, `ibm_qiskit`, свободный текст) в
     реестре нет, они не подменяются молча (`canonical_provider_id` → `""`,
     сохранённое значение → `requires_resolution`).
  2. У каждого провайдера есть конкретный адаптер и он достижим из ОДНОГО
     сервиса: `AnuClient` (ANU), `LfdrClient` (`lfdr_fetch`/`lfdr_check` в
     реестре), `IbmQuantumRuntimeClient` (`ibm_fetch`/`ibm_check` в реестре).
     `_fetch_batch` диспетчеризует все три без сети (fake-клиенты).
  3. Единственный `RandomSourceService`: один класс-сервис в модуле и
     модульный синглтон `get_service()`; PRNG — не провайдер реестра.
  4. Legacy-mapping без потери: `memory.random_source`,
     `keys.random_quantum_*` читаются теми же ключами и возвращают
     сохранённые значения; легаси-подпись партии `ANU Quantum Numbers`
     расходуется и канонизируется в `anu` без перезаписи истории.

Границы: без сети/провайдеров; только tmp SQLite.
"""
from __future__ import annotations

import pytest

from services import mca_random_source as mrs
from services import param_catalog as pc
from services.database import DatabaseService


LEGACY_ANU_LABEL = "ANU Quantum Numbers"


async def _fresh_db(tmp_path, name="vmq_q0_audit.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


# ── 1. Реестр: закрытый набор, без снятых/свободных имён ────────────────────
def test_registry_is_closed_to_three_canonical_ids():
    assert set(mrs.PROVIDERS) == {
        mrs.PROVIDER_ID_IBM, mrs.PROVIDER_ID_ANU, mrs.PROVIDER_ID_LFDR}
    assert mrs.PROVIDER_IDS == (
        mrs.PROVIDER_ID_IBM, mrs.PROVIDER_ID_ANU, mrs.PROVIDER_ID_LFDR)
    assert mrs.PROVIDER_IDS == ("ibm_quantum", "anu", "lfdr")

    for pid, spec in mrs.PROVIDERS.items():
        assert spec.id == pid
        assert pid == pid.strip().lower()
        assert " " not in pid                      # id — не свободный текст
        assert all(ch.isalnum() or ch == "_" for ch in pid)
        assert str(spec.title or "").strip()       # человекочитаемое имя есть
        assert spec.entropy_class == mrs.ENTROPY_CLASS_HARDWARE

    # UI-селектор предлагает ровно действующий закрытый набор.
    selector = pc.get_by_pg_key(mrs.SETTING_PRIMARY_PROVIDER)
    assert selector is not None
    assert tuple(selector.select_options) == mrs.PROVIDER_IDS


def test_removed_and_unknown_providers_are_not_silently_substituted():
    for removed in ("lizaonair", "Lizaonair", "lizaonair_qrng",
                    "ibm_qiskit", "ibm", "qiskit", ""):
        assert mrs.canonical_provider_id(removed) == ""
        assert mrs.entropy_class_for(removed) is None

    # Сохранённое снятое значение не действует и не переписывается молча.
    assert (mrs.primary_setting_state("lizaonair")
            == mrs.PRIMARY_SETTING_REQUIRES_RESOLUTION)
    assert (mrs.primary_setting_state("ibm_qiskit")
            == mrs.PRIMARY_SETTING_REQUIRES_RESOLUTION)
    # Нормализация порядка только читает: мусор отбрасывается, не пишется.
    assert mrs.normalize_fallback_order(
        ["lizaonair", "anu", "anu", "", 42]) == [mrs.PROVIDER_ID_ANU]
    assert mrs.PROVIDERS.get("lizaonair") is None


# ── 2. Адаптер у каждого провайдера под общим сервисом ─────────────────────
def test_every_provider_has_a_concrete_adapter():
    adapters = {
        mrs.PROVIDER_ID_ANU: mrs.AnuClient,
        mrs.PROVIDER_ID_LFDR: mrs.LfdrClient,
        mrs.PROVIDER_ID_IBM: mrs.IbmQuantumRuntimeClient,
    }
    assert set(adapters) == set(mrs.PROVIDERS)
    for pid, adapter in adapters.items():
        assert pid in mrs.PROVIDERS
        assert callable(getattr(adapter, "fetch"))

    # Реестровые точки входа (P2/P5) — тот же адаптер, не второй контур.
    assert mrs.PROVIDERS[mrs.PROVIDER_ID_LFDR].fetch is mrs.lfdr_fetch
    assert mrs.PROVIDERS[mrs.PROVIDER_ID_LFDR].check is mrs.lfdr_check
    assert mrs.PROVIDERS[mrs.PROVIDER_ID_IBM].fetch is mrs.ibm_fetch
    assert mrs.PROVIDERS[mrs.PROVIDER_ID_IBM].check is mrs.ibm_check


@pytest.mark.asyncio
async def test_single_service_dispatches_every_provider_to_its_adapter(
        monkeypatch):
    """Один сервис реально достаёт батч у каждого из трёх адаптеров."""
    monkeypatch.setattr(
        mrs, "_hot_setting", lambda key, default: default)
    svc = mrs.RandomSourceService(None, auto_refill=False)
    calls: dict = {}

    class FakeAnu:
        async def fetch(self, **kwargs):
            calls["anu"] = dict(kwargs)
            return mrs.AnuBatch(values=[7], data_type="uint16", length=1,
                                provider=mrs.PROVIDER_ID_ANU)

    class FakeLfdr:
        async def fetch(self, *, length=0):
            calls["lfdr"] = {"length": length}
            return mrs.AnuBatch(values=[3], data_type="uint8", length=1,
                                provider=mrs.PROVIDER_ID_LFDR)

    class FakeIbm:
        async def fetch(self, **kwargs):
            calls["ibm"] = dict(kwargs)
            return mrs.AnuBatch(values=[5], data_type="uint16", length=1,
                                provider=mrs.PROVIDER_ID_IBM)

    anu, lfdr, ibm = FakeAnu(), FakeLfdr(), FakeIbm()
    svc.set_client(anu)
    svc.set_lfdr_client(lfdr)
    svc.set_ibm_client(ibm)
    assert svc._get_client() is anu
    assert svc._get_lfdr_client() is lfdr
    assert svc._get_ibm_client() is ibm

    batches = [
        await svc._fetch_batch(key="k", manual=False,
                              provider=mrs.PROVIDER_ID_ANU),
        await svc._fetch_batch(key="k", manual=False,
                              provider=mrs.PROVIDER_ID_LFDR),
        await svc._fetch_batch(key="k", manual=False,
                              provider=mrs.PROVIDER_ID_IBM),
    ]
    assert [batch.provider for batch in batches] == [
        mrs.PROVIDER_ID_ANU, mrs.PROVIDER_ID_LFDR, mrs.PROVIDER_ID_IBM]
    assert set(calls) == {"anu", "lfdr", "ibm"}
    assert calls["anu"].get("key") == "k"
    assert "api_key" in calls["ibm"]


# ── 3. Единственный RandomSourceService; PRNG — не провайдер ───────────────
def test_single_random_source_service_class_and_singleton():
    service_classes = [name for name, value in vars(mrs).items()
                       if isinstance(value, type) and name.endswith("Service")]
    assert service_classes == ["RandomSourceService"]

    mrs.reset_service()
    try:
        first = mrs.get_service()
        second = mrs.get_service()
        assert isinstance(first, mrs.RandomSourceService)
        assert first is second
        assert mrs.bind_db(None) is first
    finally:
        mrs.reset_service()


def test_prng_is_not_a_registry_provider_and_modes_stay_two():
    assert mrs.MODES == (mrs.MODE_QUANTUM, mrs.MODE_PSEUDORANDOM)
    assert mrs.PROVIDER_PRNG not in mrs.PROVIDER_IDS
    assert mrs.PROVIDER_PRNG not in mrs.PROVIDERS
    assert mrs.PROVIDER_PRNG not in mrs.DEFAULT_FALLBACK_ORDER
    assert mrs.PROVIDER_PRNG not in mrs.CANONICAL_PROVIDER_ORDER
    assert mrs.SOURCE_IMPL_PRNG == "python-random-mt19937"


# ── 4. Legacy-mapping `keys.random_quantum_*` без потери ────────────────────
def test_legacy_setting_keys_are_mapped_and_read_without_loss(monkeypatch):
    assert mrs.SETTING_SOURCE == "memory.random_source"
    assert mrs.SETTING_KEY == "keys.random_quantum_api_key"
    assert mrs.SETTING_ENDPOINT == "keys.random_quantum_endpoint"
    assert mrs.SETTING_PLAN == "keys.random_quantum_plan"
    assert mrs.SETTING_BATCH_LENGTH == "keys.random_quantum_batch_length"
    assert mrs.SETTING_DATA_TYPE == "keys.random_quantum_data_type"
    assert mrs.SETTING_TIMEOUT == "keys.random_quantum_request_timeout_seconds"
    assert (mrs.SETTING_LOW_WATERMARK
            == "keys.random_quantum_refill_low_watermark")
    assert mrs.SETTING_BUFFER_MAX == "keys.random_quantum_buffer_max_values"

    legacy_keys = {
        mrs.SETTING_KEY, mrs.SETTING_ENDPOINT, mrs.SETTING_PLAN,
        mrs.SETTING_BATCH_LENGTH, mrs.SETTING_DATA_TYPE, mrs.SETTING_TIMEOUT,
        mrs.SETTING_LOW_WATERMARK, mrs.SETTING_BUFFER_MAX,
    }
    assert legacy_keys <= set(mrs.PROVIDER_KEY_SETTINGS)

    values = {
        mrs.SETTING_KEY: "legacy-anu-key-abc123",
        mrs.SETTING_ENDPOINT: mrs.ANU_ENDPOINT,
        mrs.SETTING_PLAN: "Trial",
        mrs.SETTING_BATCH_LENGTH: 64,
        mrs.SETTING_DATA_TYPE: "uint16",
        mrs.SETTING_TIMEOUT: 7,
        mrs.SETTING_LOW_WATERMARK: 128,
        mrs.SETTING_BUFFER_MAX: 1024,
    }
    monkeypatch.setattr(
        mrs, "_hot_setting", lambda key, default: values.get(key, default))

    svc = mrs.RandomSourceService(None, auto_refill=False)
    assert svc._resolve_key() == "legacy-anu-key-abc123"
    assert svc._endpoint() == mrs.ANU_ENDPOINT
    assert svc._plan() == "Trial"
    assert svc._batch_length() == 64
    assert svc._data_type() == "uint16"
    assert svc._timeout_seconds() == 7.0
    assert svc._low_watermark() == 128
    assert svc._buffer_max() == 1024
    assert svc.provider_configured(mrs.PROVIDER_ID_ANU) is True


@pytest.mark.asyncio
async def test_legacy_mode_and_fallback_settings_are_read(monkeypatch):
    values = {mrs.SETTING_SOURCE: "pseudorandom",
              mrs.SETTING_FALLBACK: True}

    async def fake(key, chat_id, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_read_memory_setting", fake)
    svc = mrs.RandomSourceService(None, auto_refill=False)
    assert await svc.selected_mode(chat_id=1) == mrs.MODE_PSEUDORANDOM
    assert await svc.fallback_enabled(chat_id=1) is True

    values.clear()
    assert await svc.selected_mode(chat_id=1) == mrs.DEFAULT_SOURCE
    assert mrs.DEFAULT_SOURCE == mrs.MODE_QUANTUM
    assert await svc.fallback_enabled(chat_id=1) is mrs.DEFAULT_FALLBACK


# ── 5. Легаси-подпись партии расходуется и канонизируется ──────────────────
@pytest.mark.asyncio
async def test_legacy_provider_label_batch_is_consumed_without_rewrite(
        tmp_path, monkeypatch):
    async def fake_setting(key, chat_id, default):
        return default

    monkeypatch.setattr(mrs, "_read_memory_setting", fake_setting)
    monkeypatch.setattr(
        mrs, "_hot_setting", lambda key, default: default)

    db = await _fresh_db(tmp_path, "vmq_q0_legacy.db")
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False)
        # История 2.58.x писала человекочитаемый provider, не канонический id.
        batch_id = await svc._store.insert_batch(mrs.AnuBatch(
            values=[0, 1, 2], data_type="uint8", length=3,
            provider=LEGACY_ANU_LABEL))
        assert mrs.canonical_provider_id(LEGACY_ANU_LABEL) == (
            mrs.PROVIDER_ID_ANU)
        assert mrs.PROVIDER_ANU in mrs.PROVIDER_STORAGE_IDS[
            mrs.PROVIDER_ID_ANU]
        assert mrs.PROVIDER_ANU in mrs.ANU_PROVIDER_IDS

        result = await svc.draw_index(3, chat_id=1, purpose="vmq_q0")
        assert result.index in (0, 1, 2)
        assert result.source == mrs.MODE_QUANTUM
        assert result.provider == LEGACY_ANU_LABEL   # история не переписана
        assert result.provider_id == mrs.PROVIDER_ID_ANU
        assert result.entropy_class == mrs.ENTROPY_CLASS_HARDWARE
        assert result.source_impl == "anu-quantum"
        assert result.batch_id == batch_id

        cursor = await db.db.execute(
            "SELECT provider, reserved_upto FROM mca_random_batches "
            "WHERE batch_id = ?", (batch_id,))
        row = await cursor.fetchone()
        assert row["provider"] == LEGACY_ANU_LABEL
        assert int(row["reserved_upto"]) == 1
    finally:
        await db.close()
