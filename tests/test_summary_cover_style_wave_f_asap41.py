"""ASAP 4.1 волны 5–6 (эпик asap-4-1-durable-whole-window-summary) —
T-4617 fixture / T-4618 / T-4619 / T-4620.

Покрытие:
  * T-4617 (spec §5 E.2, ADR-1028-8 D6.2): fixture «kill в PUBLISHING →
    рестарт → ровно одна публикация» — publication gate уровня генератора:
    kill ДО send (publication_status=publishing, ledger пуст) → retry-лег;
    kill ПОСЛЕ send, до checkpoint'а (ledger-факт есть) → reconcile → skip;
    published → второй финал невозможен;
  * T-4618 (spec §6 F.1): durable checkpoints TEXT_READY/BASE_COVER/
    STYLE_EDIT; cover-ветка не отматывает text-checkpoint (rank-guard);
    fallback-cover строится из финального документа (контракт;
    регресс ladder R4-B-003 — соседние тесты, см. evidence.md);
  * T-4619 (spec §6 F.2): лестница наследования Style-слота §35 —
    Connections default (leg 3a) → models.image_* (leg 3c) → честный
    not_configured; явный custom-профиль — байт-в-бит; capability gate;
    kill-switch OFF → ровно resolve_style_slot;
  * T-4620 (spec §6 F.3): capabilities по ФИНАЛЬНОМУ (унаследованному)
    слоту через capability registry (никаких провайдер-хардкодов в ветке);
    событие COVER_STYLE_RESOLVE с источником резолва (R17: enum/id/bool);
    api-ключ наследованного global-image слота — keys.image_api_key.
"""
from types import SimpleNamespace

import pytest

from config.settings import Settings
from services import hot_config as hot
from services import summary_run_store as srs
from services import bot_output_ledger as bol
from services.cover_style_pipeline import (
    SLOT_SOURCE_CONNECTIONS_DEFAULT,
    SLOT_SOURCE_GLOBAL_IMAGE,
    SLOT_SOURCE_GLOBAL_STYLE,
    SLOT_SOURCE_PROFILE_CONNECTION,
    resolve_style_slot,
    resolve_style_slot_inherited,
    style_global_default_enabled,
)
from services.summary_generator import SummaryGenerator
from services.summary_run_log import RunContext

pytestmark = pytest.mark.asap41


@pytest.fixture(autouse=True)
def _env_on(monkeypatch):
    """Kill-switch'и зон E/F — прод-дефолты ON; ledger ON."""
    monkeypatch.setattr(Settings, "SUMMARY_RUN_DURABLE_ENABLED", True,
                        raising=False)
    monkeypatch.setattr(Settings, "SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED",
                        True, raising=False)
    monkeypatch.setattr(Settings, "MCA_BOT_OUTPUT_LEDGER_ENABLED", True,
                        raising=False)


async def _fresh(tmp_path, name="wave6.db") -> SimpleNamespace:
    from services.database import DatabaseService
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


# ── T-4617: fixture «kill в PUBLISHING → ровно одна публикация» ─────────

def _gen_with_db(db) -> SummaryGenerator:
    gen = object.__new__(SummaryGenerator)     # без __init__ — только _run_db
    gen.memory = SimpleNamespace(db=db)
    return gen


@pytest.mark.asyncio
async def test_kill_in_publishing_after_send_ledger_reconcile_single_publication(
        tmp_path):
    """Kill ПОСЛЕ успешного send (до complete_publication): рестарт →
    PUBLISHING-stuck, ledger доказывает доставку → gate=skip, run закрывается
    фактом доставки — второй финальный месседж невозможен."""
    d = await _fresh(tmp_path, "kill1.db")
    rid = "run-kill-after-send"
    chat_id = -77
    await srs.create_run(d, rid, chat_id)
    # Первая попытка: PUBLISHING зафиксирован ДО отправки...
    proceed, _ = await srs.mark_publishing(d, rid)
    assert proceed is True
    # ...send удался (ledger-факт), checkpoint не успел записаться — kill.
    output_id = await bol.record_delivered_output(
        d, chat_id=chat_id, tg_message_id=777,
        text="итоговый текст summary", output_kind="rich_message",
        correlation_id=rid, source_feature="summary")
    assert output_id
    # Рестарт: докат — gate видит delivery-факт → ПУБЛИКАЦИЯ ПРОПУЩЕНА.
    gen = _gen_with_db(d)
    gate = await gen._publication_gate(chat_id, rid,
                                       {"paragraphs": [{"text": "x"}]})
    assert gate == "skip"
    run = await srs.get_run(d, rid)
    assert run["publication_status"] == "published"
    assert run["publication_result_ref"] == f"bot_output:{output_id}"
    # Повторный заход — всё ещё skip (идемпотентность: ровно одна публикация).
    assert await gen._publication_gate(
        chat_id, rid, {"paragraphs": [{"text": "x"}]}) == "skip"
    await d.close()


@pytest.mark.asyncio
async def test_kill_in_publishing_before_send_retry_leg_then_once(tmp_path):
    """Kill ДО send (publication_status=publishing, ledger пуст): исход
    прошлой попытки неизвестен → reconcile-лег возвращает proceed → ровно
    одна отправка; после доставки повторный заход — skip."""
    d = await _fresh(tmp_path, "kill2.db")
    rid = "run-kill-before-send"
    chat_id = -78
    await srs.create_run(d, rid, chat_id)
    await srs.mark_publishing(d, rid)          # kill до отправки
    gen = _gen_with_db(d)
    document = {"paragraphs": [{"text": "final"}]}
    # Рестарт: доставки нет → отправлять (retry-лег R4-D-051).
    assert await gen._publication_gate(chat_id, rid, document) is None
    # Отправка удалась → checkpoint published (путь _record_published_output).
    output_id = await bol.record_delivered_output(
        d, chat_id=chat_id, tg_message_id=778,
        text="итоговый текст summary", output_kind="rich_message",
        correlation_id=rid, source_feature="summary")
    from services.summary_run_log import RunContext as _RC
    gen.bot = SimpleNamespace(id=42)
    await gen._record_published_output(chat_id, 778, "итоговый текст summary",
                                       correlation_id=rid)
    del output_id, _RC
    # Ещё рестарт/докат — публикация уже зафиксирована → skip.
    assert await gen._publication_gate(chat_id, rid, document) == "skip"
    run = await srs.get_run(d, rid)
    assert run["publication_status"] == "published"
    await d.close()


@pytest.mark.asyncio
async def test_publication_status_published_blocks_second_send(tmp_path):
    """publication_status=published → gate=skip даже на другой лестнице
    (rich → plain fallback не дублирует финал)."""
    d = await _fresh(tmp_path, "kill3.db")
    rid = "run-pub-block"
    await srs.create_run(d, rid, -79)
    await srs.complete_publication(d, rid, result_ref="bot_output:9")
    gen = _gen_with_db(d)
    assert await gen._publication_gate(-79, rid,
                                       {"paragraphs": []}) == "skip"
    await d.close()


@pytest.mark.asyncio
async def test_content_hash_barrier_skips_identical_delivered_content(
        tmp_path):
    """T-4617 content-hash барьер (bot_output_ledger REUSE): kill в
    PUBLISHING, correlation-reconcile не нашёл запись, НО тот же контент
    уже доставлен (запись под другим correlation) → идентичный финал не
    дублируется; run закрывается фактом доставки."""
    d = await _fresh(tmp_path, "hash1.db")
    rid = "run-hash-skip"
    chat_id = -88
    await srs.create_run(d, rid, chat_id)
    await srs.mark_publishing(d, rid)          # kill в PUBLISHING до send
    # Тот же контент доставлен прошлой попыткой под ДРУГИМ correlation.
    from services import bot_output_ledger as _bol
    text = "итоговый текст summary"
    await _bol.record_delivered_output(
        d, chat_id=chat_id, tg_message_id=800, text=text,
        output_kind="rich_message", correlation_id="run-other",
        source_feature="summary")
    gen = _gen_with_db(d)
    document = {"paragraphs": [{"text": text}]}
    assert await gen._publication_gate(chat_id, rid, document) == "skip"
    run = await srs.get_run(d, rid)
    assert run["publication_status"] == "published"
    assert str(run["publication_result_ref"] or "").startswith("bot_output:")
    await d.close()


@pytest.mark.asyncio
async def test_content_hash_barrier_different_content_retry_leg(tmp_path):
    """Контрпример: kill в PUBLISHING, доставки ТОГО ЖЕ контента нет →
    retry-лег (gate=None → отправлять); hash другого текста не блокирует."""
    d = await _fresh(tmp_path, "hash2.db")
    rid = "run-hash-retry"
    chat_id = -89
    await srs.create_run(d, rid, chat_id)
    await srs.mark_publishing(d, rid)
    from services import bot_output_ledger as _bol
    await _bol.record_delivered_output(
        d, chat_id=chat_id, tg_message_id=801, text="другой текст",
        output_kind="rich_message", correlation_id="run-other",
        source_feature="summary")
    gen = _gen_with_db(d)
    document = {"paragraphs": [{"text": "новый финальный текст"}]}
    assert await gen._publication_gate(chat_id, rid, document) is None
    await d.close()


# ── T-4618: durable checkpoints зоны F (cover не отматывает text) ───────

@pytest.mark.asyncio
async def test_zone_f_checkpoints_state_machine_no_rewind_on_cover(tmp_path):
    """TEXT_READY → BASE_COVER → STYLE_EDIT checkpoints пишутся; повторный
    checkpoint text/структуры (например, cover/style failure → retry) не
    отматывает state (cover-ветка не трогает text pipeline)."""
    d = await _fresh(tmp_path, "checkpoints.db")
    rid = "run-zone-f"
    ctx = RunContext(run_id=rid, chat_id=-80)
    ctx.provider = "host.example"
    ctx.model = "m-1"
    gen = _gen_with_db(d)
    await srs.create_run(d, rid, -80)
    await gen._durable_mark(ctx, srs.STATE_TEXT_READY, stage="text_ready")
    assert (await srs.get_run(d, rid))["state"] == "TEXT_READY"
    await gen._durable_mark(ctx, srs.STATE_BASE_COVER, stage="cover_base")
    await gen._durable_mark(ctx, srs.STATE_STYLE_EDIT, stage="cover_style")
    assert (await srs.get_run(d, rid))["state"] == "STYLE_EDIT"
    # Cover-ветка упала и retry докаывает текст — rewind запрещён rank-guard'ом.
    await gen._durable_mark(ctx, srs.STATE_TEXT_READY)
    assert (await srs.get_run(d, rid))["state"] == "STYLE_EDIT"
    # Stage-история append-only (BASE_COVER/STYLE_EDIT зафиксированы).
    stages = [r["stage"] for r in await srs.stage_history(d, rid)]
    assert stages == ["text_ready", "cover_base", "cover_style"]
    await d.close()


# ── T-4619: лестница наследования Style-слота §35 ───────────────────────

@pytest.fixture(autouse=True)
def _clean_slots(monkeypatch):
    """Пустые глобальные слоты по умолчанию (hot-config байпас → settings)."""
    def _passthrough(key, default=None):
        return default
    monkeypatch.setattr(hot, "get", _passthrough)
    _set_settings(monkeypatch, IMAGE_STYLE_BASE_URL="", IMAGE_STYLE_MODEL="",
                  IMAGE_BASE_URL="", IMAGE_MODEL="")


_patch_restore: list = []


@pytest.fixture(autouse=True)
def _restore_settings_patches():
    """Восстановление instance-патчей frozen-Settings после каждого теста
    (прецедент tests/test_embedding_control_plane_asap4.py:63-71)."""
    yield
    while _patch_restore:
        _patch_restore.pop()()


def _set_settings(monkeypatch, **values):
    """Патч атрибутов singleton'а settings: класс + ФАКТИЧЕСКИЙ инстанс
    сервиса (часть полей — frozen-instance-атрибуты, затеняющие класс;
    патч через object.__setattr__ с авто-восстановлением — прецедент
    test_embedding_control_plane_asap4.py:63-71).

    Прецедент conftest `_system2_flags_off_by_default` (tests/conftest.py:
    28-30): часть тестов делает ``importlib.reload(config.settings)`` —
    тогда ``config.settings.settings`` — НОВЫЙ инстанс, а сервисы
    (cover_style_pipeline) держат исходный. Патчим и его класс, и оба
    инстанса, иначе патч не долетает до резолвера."""
    import config.settings as cs
    import services.cover_style_pipeline as csp
    targets = [cs.settings, getattr(csp, "settings", None)]
    seen: set[int] = set()
    targets = [t for t in targets
               if t is not None and id(t) not in seen
               and not seen.add(id(t))]
    for name, value in values.items():
        monkeypatch.setattr(Settings, name, value, raising=False)
        for inst in targets:
            if name in vars(inst):
                old = vars(inst)[name]
                object.__setattr__(inst, name, value)
                _patch_restore.append(
                    lambda old=old, inst=inst, name=name:
                        object.__setattr__(inst, name, old))


@pytest.mark.asyncio
async def test_leg3a_connections_default_inherits(monkeypatch):
    """Пустой глобальный слот + Connections default-подключение → слот
    наследуется (leg 3a), resolve_source=connections_default."""
    monkeypatch.setattr(
        "services.cover_style_pipeline.default_edit_connection",
        _conn_stub({"connection_id": "conn-1",
                    "base_url": "https://edit.example.com"}))
    slot = await resolve_style_slot_inherited(
        profile={"model_mode": "default", "model_id": "edit-model-x"})
    assert slot["resolve_source"] == SLOT_SOURCE_CONNECTIONS_DEFAULT
    assert slot["configured"] is True
    assert slot["base_url"] == "https://edit.example.com"
    assert slot["model"] == "edit-model-x"


@pytest.mark.asyncio
async def test_leg3c_global_image_slot_inherits(monkeypatch):
    """Ни Connections default, ни глобального style-слота → global default
    image provider+model (leg 3c) — прод-инцидент Medved Press закрыт."""
    monkeypatch.setattr(
        "services.cover_style_pipeline.default_edit_connection",
        _conn_stub(None))
    _set_settings(monkeypatch, IMAGE_BASE_URL="https://img.example.com",
                  IMAGE_MODEL="img-model")
    slot = await resolve_style_slot_inherited(profile={"model_mode": "default"})
    assert slot["resolve_source"] == SLOT_SOURCE_GLOBAL_IMAGE
    assert slot["configured"] is True
    assert slot["model"] == "img-model"


@pytest.mark.asyncio
async def test_leg4_honest_not_configured_when_nothing_resolves(monkeypatch):
    """Ничего не разрешилось → configured=False → честный reason (не
    «успех без стиля»)."""
    monkeypatch.setattr(
        "services.cover_style_pipeline.default_edit_connection",
        _conn_stub(None))
    slot = await resolve_style_slot_inherited(profile={"model_mode": "default"})
    assert slot["configured"] is False
    assert slot["resolve_source"] == SLOT_SOURCE_GLOBAL_STYLE


@pytest.mark.asyncio
async def test_explicit_style_connection_regression_byte_identical(monkeypatch):
    """Регресс: явно настроенный custom-профиль — байт-в-бит прежнего
    resolve_style_slot (наследование не вмешивается)."""
    conn = {"base_url": "https://custom.example.com"}
    direct = resolve_style_slot(
        profile={"model_mode": "custom", "connection_id": "c1",
                 "model_id": "style-model"},
        connection=conn)
    inherited = await resolve_style_slot_inherited(
        profile={"model_mode": "custom", "connection_id": "c1",
                 "model_id": "style-model"},
        connection=conn)
    assert {k: v for k, v in inherited.items() if k != "_connection"} == \
        {k: v for k, v in direct.items() if k != "_connection"}
    assert inherited["resolve_source"] == SLOT_SOURCE_PROFILE_CONNECTION


@pytest.mark.asyncio
async def test_configured_global_slot_unchanged_25846(monkeypatch):
    """Настроенный глобальный style-слот — прежний контур (leg 1/2, бит-в-бит
    2.58.46; наследование не активируется)."""
    _set_settings(monkeypatch, IMAGE_STYLE_BASE_URL="https://style.example.com",
                  IMAGE_STYLE_MODEL="style-model")
    monkeypatch.setattr(
        "services.cover_style_pipeline.default_edit_connection",
        _conn_stub({"connection_id": "conn-x",
                    "base_url": "https://other.example.com"}))
    slot = await resolve_style_slot_inherited(profile={"model_mode": "default"})
    assert slot["resolve_source"] == SLOT_SOURCE_GLOBAL_STYLE
    assert slot["base_url"] == "https://style.example.com"


@pytest.mark.asyncio
async def test_capability_false_blocks_inheritance(monkeypatch):
    """Capability image_edit=FALSE на наследуемом слоте блокирует лег
    наследования (§36/§58); UNKNOWN не блокирует (честная попытка → fail-soft)."""
    from services import image_capabilities as cap

    monkeypatch.setattr(
        "services.cover_style_pipeline.default_edit_connection",
        _conn_stub({"connection_id": "conn-1",
                    "base_url": "https://edit.example.com"}))
    caps_false = cap.conservative_unknown()
    caps_false.image_edit = cap.FALSE
    caps_unknown = cap.conservative_unknown()

    async def _caps_auto(provider, base_url, model):
        return caps_false if base_url == "https://edit.example.com" \
            else caps_unknown
    monkeypatch.setattr(cap, "resolve_capabilities_auto", _caps_auto)
    slot = await resolve_style_slot_inherited(profile={"model_mode": "default"})
    assert slot["configured"] is False       # leg 3a заблокирован FALSE
    # UNKNOWN не блокирует:
    async def _caps_unknown(provider, base_url, model):
        return caps_unknown
    monkeypatch.setattr(cap, "resolve_capabilities_auto", _caps_unknown)
    slot = await resolve_style_slot_inherited(
        profile={"model_mode": "default", "model_id": "edit-model-x"})
    assert slot["resolve_source"] == SLOT_SOURCE_CONNECTIONS_DEFAULT
    assert slot["configured"] is True        # leg 3a прошёл (unknown не блок)


@pytest.mark.asyncio
async def test_kill_switch_off_resolver_byte_identical(monkeypatch):
    """Kill-switch `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED=false` → ровно
    resolve_style_slot (текущий resolver, байт-в-бит 2.58.46)."""
    monkeypatch.setattr(Settings, "SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED",
                        False, raising=False)
    assert style_global_default_enabled() is False
    monkeypatch.setattr(
        "services.cover_style_pipeline.default_edit_connection",
        _conn_stub({"connection_id": "conn-1",
                    "base_url": "https://edit.example.com"}))
    slot = await resolve_style_slot_inherited(profile={"model_mode": "default"})
    baseline = resolve_style_slot(profile={"model_mode": "default"})
    assert {k: v for k, v in slot.items() if k != "_connection"} == baseline
    assert slot["configured"] is False


# ── T-4620: capability registry + события + ключ наследованного слота ──

@pytest.mark.asyncio
async def test_capabilities_resolved_by_final_inherited_slot(monkeypatch):
    """Capabilities резолвятся по ФИНАЛЬНОМУ (унаследованному) слоту через
    capability registry (§36) — не по базовому глобальному (никаких
    провайдер-хардкодов: аргументы registry — фактический слот)."""
    from services import image_capabilities as cap
    seen = []

    async def _caps_auto(provider, base_url, model):
        seen.append((provider, base_url, model))
        return cap.conservative_unknown()
    monkeypatch.setattr(cap, "resolve_capabilities_auto", _caps_auto)
    _set_settings(monkeypatch, IMAGE_BASE_URL="https://img.example.com",
                  IMAGE_MODEL="img-model")
    slot = await resolve_style_slot_inherited(profile={"model_mode": "default"})
    assert slot["resolve_source"] == SLOT_SOURCE_GLOBAL_IMAGE
    assert seen and seen[-1] == ("img.example.com", "https://img.example.com",
                                 "img-model")


@pytest.mark.asyncio
async def test_cover_style_resolve_event_contract(monkeypatch):
    """Контракт события COVER_STYLE_RESOLVE (T-4619/T-4620): имя
    экспортируется, поле `resolve_source` — в R17-allowlist (SAFE_LOG_
    FIELDS), значения лестницы §35 — закрытый набор enum (не generic
    `style_failed`; правило ADR-1028-7 D6.3)."""
    import services.cover_style_jobs as csj
    assert "COVER_STYLE_RESOLVE" in csj.__all__
    assert "resolve_source" in csj.SAFE_LOG_FIELDS
    sources = {SLOT_SOURCE_GLOBAL_STYLE, SLOT_SOURCE_PROFILE_CONNECTION,
               SLOT_SOURCE_CONNECTIONS_DEFAULT, SLOT_SOURCE_GLOBAL_IMAGE}
    assert len(sources) == 4                 # лестница §35 полностью enum'ом


@pytest.mark.asyncio
async def test_run_style_job_emits_resolve_before_start(tmp_path, monkeypatch):
    """run_style_job: COVER_STYLE_RESOLVE (источник резолва) эмитится ДО
    COVER_STYLE_START (лестница §35 видима в событиях); не-настроенный слот
    → детерминированный ранний выход `not_configured` (без API/сети)."""
    import services.cover_style_jobs as csj

    events = []
    monkeypatch.setattr(csj, "emit_cover_event",
                        lambda name, **fields: events.append(
                            (name, dict(fields))))

    async def _slot(*, profile, connection, pg):
        return {"base_url": "", "model": "", "provider": "",
                "connection_id": "default", "custom_unresolved": False,
                "configured": False,
                "resolve_source": SLOT_SOURCE_GLOBAL_STYLE}
    monkeypatch.setattr(csj, "resolve_style_slot_inherited", _slot)
    # Волна B: ON — конфигурационная проверка до submission (ранний выход).
    monkeypatch.setattr(Settings, "COVER_STYLE_SNAPSHOT_ENABLED", True,
                        raising=False)
    meta = await csj.run_style_job(
        chat_id=-81, base_image_path=str(tmp_path / "base.png"),
        profile={"enabled": True, "profile_id": "p1", "model_mode": "default"},
        summary_run_id="run-resolve", correlation_id="run-resolve",
        db=None, job_id="j1", state=None, summary_text="",
        base_style_prompt="")
    names = [name for name, _ in events]
    assert "COVER_STYLE_RESOLVE" in names
    assert names.index("COVER_STYLE_RESOLVE") < names.index(
        "COVER_STYLE_START")
    resolve = dict(events[names.index("COVER_STYLE_RESOLVE")][1])
    assert resolve["resolve_source"] == SLOT_SOURCE_GLOBAL_STYLE
    assert resolve["configured"] is False
    assert meta["fail_reason"] == "not_configured"


def _conn_stub(value):
    async def _stub(pg):
        return value
    return _stub
