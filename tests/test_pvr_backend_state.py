"""PVR-BACKEND — однозначная модель состояния версионирования промптов.

Контракт: ``plans/features/pvr-fc-corrective-01/requirements-map.json`` срез
PVR-BACKEND (строки L00051–L00244 исходника) + дословный источник
``plans/owner_inputs/2026-11-05-pvr-fc-corrective-01.md`` (§PVR-01/02/03/05,
A3.2, C3.1–C3.4, C3.7–C3.9).

Проверяется НАБЛЮДАЕМОЕ поведение приёмочных примеров, а не внутренности:

  * PVR-01/01.1–01.5: HTTP-ответ состояния содержит ЕДИНЫЙ набор плоских
    полей (effective_origin/content_hash/revision_id, journal_*,
    baseline_revision_id, factory_revision_id, draft_dirty); origin —
    chat_override|global|code, совпадает с резолвером LLM-payload; hash
    сопоставляется журналу по байтам, несопоставленный текст — честный
    статус «Не сопоставлено с историей», drift — отдельный статус без
    метки активной карточки; journal_* остаются журнальными; baseline ≠
    active ≠ factory; draft_dirty — только поле редактора.
  * PVR-02/C3.1/C3.2: ревизия и событие — разные сущности; два applied
    события одной ревизии → ровно одна активная карточка; две ревизии с
    одинаковыми байтами → один эффективный выбор.
  * PVR-03/C3.3: Save/retry/double-click/два редактора — без дублей
    ревизий, без silent overwrite (CAS-конфликт), идемпотентность по
    operation ID.
  * C3.4: наследование global помечается честно, два чата не путаются.
  * C3.7: рестарт/release не создают ручных версий и не трогают pinned.
  * C3.8: retired читается/сравнивается, но не применяется.
  * C3.9: 1000+ ревизий и 200+ событий проходятся курсором без тел.
  * A3.2: история только дописывается; rollback/forward работают.

TEST-LIFECYCLE: CONTRACT owner=PVR-FC-CORRECTIVE-01 (slice PVR-BACKEND)
"""
from __future__ import annotations

import asyncio
import datetime
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services import chat_params
from services import prompt_factory as pf
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from tests.test_evol016_prompt_activation import FakeCache, FactoryEdition
from tests.test_meme_pipeline_api import _build
from tests.test_webapp_api import ADMIN_ID, _hdr
from web.api import routes as routes_mod

BLOCK = "summary.base.narrator"
PG_KEY = "prompts.summary_narrator_system_prompt"

FACTORY_A = "ЗАВОДСКАЯ A: рассказчик саммари (эталон состояния PVR-BACKEND).\n"
FACTORY_B = ("ЗАВОДСКАЯ B: новая метка релиза для проверки pinned и рестарта.\n")
MANUAL_M = "РУЧНАЯ M: правка владельца поверх заводской редакции.\n"
CHAT_A_TEXT = "ЧАТ A: собственный текст этого чата.\n"
CHAT_B_TEXT = "ЧАТ B: другой текст другого чата (перепутать нельзя).\n"
UNSAVED_TEXT = "НЕЗАПИСАННЫЙ ТЕКСТ: байтов таких нет в журнале вообще.\n"

CHAT_A = -1009001
CHAT_B = -1009002
CHAT_C = -1009003


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def edition(monkeypatch):
    patch = FactoryEdition(monkeypatch)
    patch.set_edition(BLOCK, "narrator-a", FACTORY_A)
    chat_params.set_chat_params_cache(None)
    yield patch
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    chat_params.set_chat_params_cache(None)
    pr.reset_cache()


@pytest.fixture()
def store():
    journal = prp.MemoryPromptJournal()
    yield journal
    routes_mod._PROMPT_OP_RESULTS.clear()


def _cutover(cache, store, release_id="evol-016-cutover"):
    return _run(prp.apply_release(cache, release_id=release_id, store=store,
                                  blocks=[BLOCK]))


def _save_global(cache, store, text, *, actor="owner"):
    return _run(prp.write_versioned_value(BLOCK, text, cache=cache,
                                          store=store, actor=actor))


def _save_chat(store, chat_id, text, *, actor="owner"):
    return _run(prp.write_prompt_values(
        [prp.PromptWriteItem(block_id=BLOCK, text=text)], scope="chat",
        chat_id=chat_id, store=store, cache=None, actor=actor))


def _state(store, *, scope="global", chat_id=None):
    return _run(prp.list_versions(BLOCK, scope=scope, chat_id=chat_id,
                                  store=store, actor="owner"))


def _revision_of(store, text):
    return next(r for r in store.revisions.values()
                if r.content_sha12 == pr.sha12(text))


def _active_entries(view):
    return [e for e in view["entries"] if e.get("status") == "active"]


# ═══════════════════════════════════════════════════════════════════════════
# PVR-01: единый контракт состояния (плоские поля одного ответа)
# ═══════════════════════════════════════════════════════════════════════════

PVR01_FIELDS = (
    "effective_origin", "effective_content_hash", "effective_revision_id",
    "journal_last_activation_id", "journal_active_revision_id",
    "baseline_revision_id", "factory_revision_id", "draft_dirty",
)


def test_pvr01_state_contract_fields_present(edition, store):
    """PVR-01 (L00060): один ответ несёт ВСЕ поля состояния; подмена одного
    поля другим обнаруживается: при drift effective_* и journal_* различны."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _cutover(cache, store)
    _save_global(cache, store, MANUAL_M)
    view = _state(store)
    for field in PVR01_FIELDS:
        assert field in view, f"поле {field} отсутствует в ответе состояния"
    assert view["draft_dirty"] is False
    manual = _revision_of(store, MANUAL_M)
    assert view["effective_origin"] == "global"
    assert view["effective_content_hash"] == pr.sha12(MANUAL_M)
    assert view["effective_revision_id"] == manual.revision_id
    assert view["journal_active_revision_id"] == manual.revision_id
    assert isinstance(view["journal_last_activation_id"], int)
    assert view["baseline_revision_id"] is None
    assert view["factory_revision_id"] == pr.sealed_factory_revision(BLOCK)
    assert view["factory_revision_id"] != view["baseline_revision_id"]

    # Drift: байты слоя меняются МИМО журнала → журнал остаётся журналом,
    # effective_* показывает правду; подмена полей ловится этим тестом.
    _run(store.write_global(PG_KEY, UNSAVED_TEXT))
    drifted = _state(store)
    assert drifted["effective_origin"] == "global"
    assert drifted["effective_content_hash"] == pr.sha12(UNSAVED_TEXT)
    assert drifted["effective_revision_id"] is None
    assert drifted["effective_status"] == "drift"
    assert drifted["journal_active_revision_id"] == manual.revision_id, \
        "журнальный указатель подменён эффективным полем"
    assert drifted["journal_last_activation_id"] == \
        view["journal_last_activation_id"]
    # Ни одна карточка не помечена действующей до разрешения расхождения.
    assert _active_entries(drifted) == []


def test_pvr01_1_effective_origin_matrix_matches_payload_resolver(
        edition, store):
    """PVR-01.1 (L00064): origin ∈ {chat_override, global, code} и совпадает
    с источником того же резолвера, что собирает LLM-payload."""
    cache = FakeCache()
    # 1) слоёв нет → действует код (заводская константа).
    state = _state(store)
    assert state["effective_origin"] == "code"
    # 2) глобальный слой → global.
    _cutover(cache, store)
    assert _state(store)["effective_origin"] == "global"
    # 3) чатовый override → chat_override только для этого чата.
    _save_chat(store, CHAT_A, CHAT_A_TEXT)
    chat_state = _state(store, scope="chat", chat_id=CHAT_A)
    assert chat_state["effective_origin"] == "chat_override"
    # Паритет с резолвером payload: та же функция, те же значения слоёв.
    pg_value = _run(store.read_global(PG_KEY))
    chat_value = (_run(store.read_chat_state(CHAT_A)) or {}).get(
        "overrides", {}).get(PG_KEY)
    eff = pr.effective_prompt(PG_KEY, pg_value=pg_value, chat_value=chat_value)
    assert eff.source == "chat"
    assert chat_state["effective_content_hash"] == pr.sha12(CHAT_A_TEXT)
    # Другой чат без override наследует global — не путается с чатом A.
    inherited = _state(store, scope="chat", chat_id=CHAT_B)
    assert inherited["effective_origin"] == "global"
    assert inherited["effective_content_hash"] == pr.sha12(FACTORY_A)


def test_pvr01_2_unmatched_text_is_honest_not_nearest_revision(
        edition, store):
    """PVR-01.2 (L00065): действует текст без ревизии → effective_revision_id
    is None и статус «Не сопоставлено с историей», НЕ визуально ближайшая
    ревизия. Указатель журнала на другие байты даёт строго честный drift."""
    # A) Указателя журнала нет: текст действует из глобального слоя и не
    #    сопоставлен истории.
    bare = prp.MemoryPromptJournal()
    _run(bare.write_global(PG_KEY, UNSAVED_TEXT))
    pr.set_release_policy_active(True)
    try:
        view = _state(bare)
        assert view["effective_origin"] == "global"
        assert view["effective_content_hash"] == pr.sha12(UNSAVED_TEXT)
        assert view["effective_revision_id"] is None
        assert view["effective_status"] == "unmatched"
        assert view["effective_status_label"] == "Не сопоставлено с историей"
        assert view["journal_active_revision_id"] is None
    finally:
        pr.set_release_policy_active(False)
    # B) Указатель журнала указывает на другие байты → drift (строже):
    #    revision_id по-прежнему None, ближайшая ревизия НЕ подставляется.
    cache = FakeCache()
    _cutover(cache, store)
    _run(store.write_global(PG_KEY, UNSAVED_TEXT))
    drifted = _state(store)
    assert drifted["effective_revision_id"] is None
    assert drifted["effective_status"] == "drift"
    # Сопоставленный текст отдаёт конкретную ревизию.
    _run(store.write_global(PG_KEY, FACTORY_A))
    matched = _state(store)
    factory_rev = _revision_of(store, FACTORY_A)
    assert matched["effective_status"] == "matched"
    assert matched["effective_revision_id"] == factory_rev.revision_id
    assert matched["effective_content_hash"] == pr.sha12(FACTORY_A)


def test_pvr01_3_journal_fields_remain_journal_under_drift(edition, store):
    """PVR-01.3 (L00066): journal_last_activation_id/journal_active_revision_id
    — отдельные журнальные поля; при расхождении с рантаймом не становятся
    «действующими»."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _cutover(cache, store)
    _save_global(cache, store, MANUAL_M)
    before = _state(store)
    manual = _revision_of(store, MANUAL_M)
    assert before["journal_active_revision_id"] == manual.revision_id
    _run(store.write_global(PG_KEY, UNSAVED_TEXT))
    drifted = _state(store)
    # Журнальные поля остались указателем журнала (на MANUAL_M)...
    assert drifted["journal_active_revision_id"] == manual.revision_id
    assert isinstance(drifted["journal_last_activation_id"], int)
    # ...а эффективные поля показывают фактический расхождение, не журнал.
    assert drifted["effective_revision_id"] is None
    assert drifted["effective_status"] == "drift"
    assert "journal_active_differs" in drifted["effective_diagnostics"]


def test_pvr01_4_baseline_and_factory_are_separate_pointers(edition, store):
    """PVR-01.4 (L00067): baseline_revision_id ≠ действующий текст;
    factory_revision_id ≠ baseline; оба в одном ответе. Назначение базовой
    не активирует ревизию."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _cutover(cache, store)
    _save_global(cache, store, MANUAL_M)
    factory_rev = _revision_of(store, FACTORY_A)
    assigned = _run(prp.assign_baseline(BLOCK, factory_rev.revision_id,
                                        cache=cache, store=store,
                                        actor="owner"))
    assert assigned["applied"] is True
    view = _state(store)
    assert view["baseline_revision_id"] == factory_rev.revision_id
    assert view["effective_revision_id"] == _revision_of(
        store, MANUAL_M).revision_id
    assert view["baseline_revision_id"] != view["effective_revision_id"]
    assert view["factory_revision_id"] == pr.sealed_factory_revision(BLOCK)
    assert view["factory_revision_id"] != view["baseline_revision_id"]
    # Назначение базовой НЕ активирует: значение и указатель не тронуты.
    assert _run(store.read_global(PG_KEY)) == MANUAL_M
    applied = _run(store.read_applied(BLOCK, "global", None))
    assert applied.revision_id == _revision_of(store, MANUAL_M).revision_id
    # Карточка baseline помечена «базовая», не «активная».
    baseline_cards = [e for e in view["entries"]
                      if e.get("status") == "baseline"]
    assert [e["revision_id"] for e in baseline_cards] == \
        [factory_rev.revision_id]


def test_pvr01_5_draft_dirty_is_editor_field_only(edition, store):
    """PVR-01.5 (L00068): draft_dirty — несохранённое поле редактора: в
    состоянии сервера всегда False и не участвует в выборе активной
    редакции (черновик в кэше не меняет состояние)."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _cutover(cache, store)
    _save_global(cache, store, MANUAL_M)
    view = _state(store)
    assert view["draft_dirty"] is False
    assert view["effective_revision_id"] == _revision_of(
        store, MANUAL_M).revision_id
    # «Черновик» (незаписанное значение в кэше памяти) не влияет на
    # состояние: сервер считает по персистентному слою, не по черновику.
    cache.values[PG_KEY] = "ЧЕРНОВИК: несохранённый текст редактора.\n"
    after = _state(store)
    assert after["draft_dirty"] is False
    assert after["effective_content_hash"] == pr.sha12(MANUAL_M)
    assert after["effective_revision_id"] == view["effective_revision_id"]


# ═══════════════════════════════════════════════════════════════════════════
# PVR-02 / C3.1 / C3.2: ревизия ≠ событие; дубли представлений исчезают
# ═══════════════════════════════════════════════════════════════════════════

def _insert_activation(store, revision_id, outcome="applied", *,
                       created_at=None, kind="manual_edit"):
    store.activations.append(prp.ActivationRow(
        block_id=BLOCK, scope="global", chat_id=None,
        revision_id=revision_id, kind=kind, outcome=outcome,
        actor="owner", created_at=created_at
        or datetime.datetime.now(datetime.timezone.utc).isoformat()))


def test_c31_two_applied_events_of_one_revision_one_active_card(
        edition, store):
    """C3.1 (L00236): два исторических события applied одной ревизии → ровно
    одна активная запись; события видны только как события."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _cutover(cache, store)
    _save_global(cache, store, MANUAL_M)
    manual = _revision_of(store, MANUAL_M)
    # Второе историческое событие applied той же ревизии (двойное apply).
    _insert_activation(store, manual.revision_id, "applied",
                       created_at="2026-11-05T12:00:00+00:00")
    view = _state(store)
    active = _active_entries(view)
    assert len(active) == 1, "ожидаена ровно одна активная карточка"
    assert active[0]["entry_type"] == prp.ENTRY_REVISION
    assert active[0]["revision_id"] == manual.revision_id
    # События NEVER «active»: и в объединённой ленте, и во вторичной.
    event_entries = [e for e in view["entries"]
                     if e.get("entry_type") == prp.ENTRY_ACTIVATION]
    assert event_entries, "события должны остаться в ленте"
    assert all(e["status"] != "active" for e in event_entries)
    assert all(e["status"] == "was_applied" for e in event_entries)
    assert all(e["status"] != "active" for e in view["activations"])
    assert all(e["status"] == "was_applied" for e in view["activations"])


def test_c32_same_bytes_two_revisions_one_effective_choice(edition, store):
    """C3.2 (L00237): две разные ревизии с одинаковыми байтами + два события
    применения → ровно один актуальный эффективный выбор."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _cutover(cache, store)
    _save_global(cache, store, MANUAL_M)
    manual = _revision_of(store, MANUAL_M)
    # Вторая ревизия с теми же байтами (другое происхождение → другой id).
    twin = prp.RevisionRow(
        revision_id=pr.revision_id_for(BLOCK, "global", None, "restored",
                                       pr.sha12(MANUAL_M)),
        block_id=BLOCK, scope="global", origin="restored",
        content_sha12=pr.sha12(MANUAL_M), body=MANUAL_M, pg_key=PG_KEY,
        actor="owner", reason="copy",
        created_at="2026-11-05T13:00:00+00:00")
    store.revisions[twin.revision_id] = twin
    _insert_activation(store, manual.revision_id, "applied",
                       created_at="2026-11-05T12:30:00+00:00")
    view = _state(store)
    active = _active_entries(view)
    assert len(active) == 1, "дубли байтов не должны плодить «активные»"
    # Эффективный выбор один и детерминированный (новейшая сопоставленная).
    assert view["effective_revision_id"] == active[0]["revision_id"]
    assert view["effective_content_hash"] == pr.sha12(MANUAL_M)
    assert view["effective_status"] == "matched"
    # Обе ревизии остались в истории (данные не удалялись), но «активна»
    # только одна; события — не активные карточки.
    assert len({r.revision_id for r in store.revisions.values()
                if r.content_sha12 == pr.sha12(MANUAL_M)}) == 2
    assert all(e["status"] != "active" for e in view["activations"])


# ═══════════════════════════════════════════════════════════════════════════
# PVR-03 / C3.3: атомарность и идемпотентность сохранения
# ═══════════════════════════════════════════════════════════════════════════

def test_c33_retry_and_double_click_create_no_duplicate_revision(
        edition, store):
    """C3.3 (L00238): один Save, retry POST, двойной клик — без дублей
    ревизий; повтор тех же байтов не создаёт новую редакцию."""
    cache = FakeCache()
    _cutover(cache, store)
    first = _save_global(cache, store, MANUAL_M)
    assert first["applied"] is True
    revisions_before = set(store.revisions)
    second = _save_global(cache, store, MANUAL_M)
    assert second["outcome"] == "skipped_same"
    assert set(store.revisions) == revisions_before, \
        "повторное сохранение тех же байтов создало дубль ревизии"
    third = _save_global(cache, store, MANUAL_M)
    assert third["outcome"] == "skipped_same"
    assert set(store.revisions) == revisions_before


def test_c33_operation_id_replays_same_response_without_second_write(
        edition, store, monkeypatch):
    """PVR-02: повтор POST с тем же operation ID (retry/double-click)
    возвращает тот же ответ без второй записи: ни ревизии, ни события."""
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache_: store)
    cache = FakeCache()
    _cutover(cache, store)
    items = [prp.PromptWriteItem(block_id=BLOCK, text=MANUAL_M)]
    first = _run(routes_mod._write_prompt_items(
        cache, items, scope="global", actor="owner", reason="owner_edit",
        operation_id="op-save-1"))
    assert first["applied"] == [PG_KEY]
    revs = set(store.revisions)
    acts = len(store.activations)
    replay = _run(routes_mod._write_prompt_items(
        cache, items, scope="global", actor="owner", reason="owner_edit",
        operation_id="op-save-1"))
    assert replay == first, "retry с тем же operation ID изменил ответ"
    assert set(store.revisions) == revs and len(store.activations) == acts
    # Другой operation ID с теми же байтами — честный второй прогон:
    # skipped_same, ревизии по-прежнему без дублей.
    other = _run(routes_mod._write_prompt_items(
        cache, items, scope="global", actor="owner", reason="owner_edit",
        operation_id="op-save-2"))
    assert other["skipped_same"] == [PG_KEY]
    assert set(store.revisions) == revs
    # Та же операция в другом scope — другой адресат, идемпотентность не
    # смешивает ключи: чат-запись выполняется реально.
    chat_result = _run(routes_mod._write_prompt_items(
        cache, items, scope="chat", chat_id=CHAT_A, actor="owner",
        reason="owner_edit", operation_id="op-save-1"))
    assert chat_result["applied"] == [PG_KEY]


def test_c33_conflicting_write_does_not_silently_overwrite(edition, store):
    """C3.3: два редактора — устаревший CAS-токен → конфликт, чужая правка
    НЕ перетирается молча, значение остаётся от первой правки."""
    cache = FakeCache()
    _cutover(cache, store)
    _save_global(cache, store, MANUAL_M)
    store.settings_updated_at[PG_KEY] = "2026-11-05T10:00:00+00:00"
    from services.prompt_factory import FactoryConflict
    stale = prp.PromptWriteItem(block_id=BLOCK, text="ВТОРОЙ РЕДАКТОР.\n",
                                expected_updated_at="2026-11-05T09:00:00+00:00")
    with pytest.raises(FactoryConflict):
        _run(prp.write_prompt_values([stale], scope="global", cache=cache,
                                     store=store, actor="editor-2"))
    # Чужая правка не перетёрта, дублей ревизии нет.
    assert _run(store.read_global(PG_KEY)) == MANUAL_M
    assert not any(r.body == "ВТОРОЙ РЕДАКТОР.\n"
                   for r in store.revisions.values())


# ═══════════════════════════════════════════════════════════════════════════
# C3.4: наследование global и два чата с разными override
# ═══════════════════════════════════════════════════════════════════════════

def test_c34_two_chats_with_different_overrides_not_confused(edition, store):
    """C3.4 (L00239): global действует без override → метка наследования;
    два чата с разными override дают разные origin/hash и не путаются."""
    cache = FakeCache()
    _cutover(cache, store)   # заводской текст попадает в персистентный слой
    _save_chat(store, CHAT_A, CHAT_A_TEXT)
    _save_chat(store, CHAT_B, CHAT_B_TEXT)
    a = _state(store, scope="chat", chat_id=CHAT_A)
    b = _state(store, scope="chat", chat_id=CHAT_B)
    c = _state(store, scope="chat", chat_id=CHAT_C)
    assert a["effective_origin"] == "chat_override"
    assert a["effective_content_hash"] == pr.sha12(CHAT_A_TEXT)
    assert b["effective_origin"] == "chat_override"
    assert b["effective_content_hash"] == pr.sha12(CHAT_B_TEXT)
    assert a["effective_content_hash"] != b["effective_content_hash"]
    assert a["effective_revision_id"] == _run(
        store.find_revision_by_sha(BLOCK, pr.sha12(CHAT_A_TEXT),
                                   chat_id=CHAT_A)).revision_id
    assert b["effective_revision_id"] == _run(
        store.find_revision_by_sha(BLOCK, pr.sha12(CHAT_B_TEXT),
                                   chat_id=CHAT_B)).revision_id
    # Чат C без override: честное наследование global, локальной активной
    # карточки нет (запись другого scope не изображается как локальная).
    assert c["effective_origin"] == "global"
    assert c["effective_content_hash"] == pr.sha12(FACTORY_A)
    assert _active_entries(c) == []


# ═══════════════════════════════════════════════════════════════════════════
# C3.7: рестарт/release не создают ручные версии и не трогают pinned
# ═══════════════════════════════════════════════════════════════════════════

def test_c37_restart_creates_no_versions_and_keeps_pinned_text(
        edition, store):
    """C3.7 (L00242): рестарт с той же меткой — ни строки; release с новой
    меткой при закреплённом владельцем тексте пишет заводскую ревизию в
    историю, но НЕ подменяет текст."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _cutover(cache, store)
    _save_global(cache, store, MANUAL_M)
    manual = _revision_of(store, MANUAL_M)
    factory_rev = _revision_of(store, FACTORY_A)
    _run(prp.assign_baseline(BLOCK, manual.revision_id, cache=cache,
                             store=store, actor="owner"))
    revs_before = set(store.revisions)
    acts_before = len(store.activations)
    # Рестарт с той же меткой — истинный no-op.
    restart = _cutover(cache, store, release_id="restart-pinned")
    assert set(store.revisions) == revs_before
    assert len(store.activations) == acts_before
    assert _run(store.read_global(PG_KEY)) == MANUAL_M
    # Новая метка релиза: заводская ревизия записана, pinned текст цел.
    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    deployed = _cutover(cache, store, release_id="deploy-b")
    row = next(r for r in deployed["results"]
               if r.scope == "global" and r.chat_id is None)
    assert row.detail_code == "factory_superseded_pinned"
    assert row.outcome == "skipped_same"
    assert _run(store.read_global(PG_KEY)) == MANUAL_M
    assert manual.revision_id in store.revisions
    assert factory_rev.revision_id in store.revisions
    new_factory = _revision_of(store, FACTORY_B)
    assert new_factory.revision_id in store.revisions
    # Повторный рестарт после выпуска — снова no-op.
    revs_after = set(store.revisions)
    _cutover(cache, store, release_id="restart-b")
    assert set(store.revisions) == revs_after
    assert _run(store.read_global(PG_KEY)) == MANUAL_M
    # Состояние: origin остаётся global-правкой владельца, factory-ревизия
    # не стала «активной».
    view = _state(store)
    assert view["effective_content_hash"] == pr.sha12(MANUAL_M)
    assert _active_entries(view)[0]["revision_id"] == manual.revision_id


# ═══════════════════════════════════════════════════════════════════════════
# C3.8: retired читается/сравнивается, но не применяется
# ═══════════════════════════════════════════════════════════════════════════

def test_c38_retired_viewable_diffable_but_not_applicable(edition, store):
    """C3.8 (L00243): retired-ревизия доступна для просмотра и сравнения;
    активация запрещена с указанной причиной; указатель не меняется."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _cutover(cache, store)
    _save_global(cache, store, MANUAL_M)
    manual = _revision_of(store, MANUAL_M)
    _run(store.mark_retired([BLOCK]))
    # Просмотр: тело доступно, статус и причина честные.
    source = _run(prp.get_revision_source(manual.revision_id, store=store,
                                          actor="owner"))
    assert source["known"] is True
    assert source["body"] == MANUAL_M
    assert source["status"] == "retired"
    assert source["actionable"] is False
    # Сравнение: diff работает для retired-пары.
    factory = _revision_of(store, FACTORY_A)
    diff = _run(prp.diff_revisions(factory.revision_id, manual.revision_id,
                                   store=store, actor="owner"))
    assert diff.get("known") is True
    assert diff.get("diff")
    # Применение запрещено с причиной; активный текст не изменился.
    result = _run(prp.activate_revision(BLOCK, manual.revision_id,
                                        cache=cache, store=store,
                                        actor="owner"))
    assert result["applied"] is False
    assert result["reason"] == "revision_retired"
    assert _run(store.read_global(PG_KEY)) == MANUAL_M
    applied = _run(store.read_applied(BLOCK, "global", None))
    assert applied.revision_id == manual.revision_id
    # Baseline на retired тоже запрещён.
    baseline = _run(prp.assign_baseline(BLOCK, manual.revision_id,
                                        cache=cache, store=store,
                                        actor="owner"))
    assert baseline["applied"] is False
    assert baseline["reason"] == "revision_retired"
    # В списке карточка retired видна с причиной и actionable=False.
    view = _state(store)
    card = next(e for e in view["entries"]
                if e["revision_id"] == manual.revision_id)
    assert card["status"] == "retired"
    assert card["actionable"] is False
    assert "retired" in (card.get("reason_text") or "")


# ═══════════════════════════════════════════════════════════════════════════
# C3.9: 1000+ ревизий и 200+ событий курсором, без загрузки всех тел
# ═══════════════════════════════════════════════════════════════════════════

def _seed_bulk(store, *, revisions: int, activations: int):
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    for idx in range(revisions):
        text = f"РЕВИЗИЯ {idx:04d}: текст версии номер {idx}.\n"
        ts = (base + datetime.timedelta(seconds=idx)).isoformat()
        revision_id = pr.revision_id_for(BLOCK, "global", None, "manual",
                                         pr.sha12(text))
        store.revisions[revision_id] = prp.RevisionRow(
            revision_id=revision_id, block_id=BLOCK, scope="global",
            origin="manual", content_sha12=pr.sha12(text), body=text,
            pg_key=PG_KEY, actor="owner", reason="owner_edit", created_at=ts)
    for idx in range(activations):
        ts = (base + datetime.timedelta(seconds=idx, microseconds=500000)
              ).isoformat()
        store.activations.append(prp.ActivationRow(
            block_id=BLOCK, scope="global", chat_id=None,
            kind="manual_edit", outcome="applied", revision_id="",
            actor="owner", created_at=ts))


def test_c39_scale_cursor_pagination_no_full_body_loads(edition, store):
    """C3.9 (L00244): 1000+ ревизий и 200+ событий проходятся курсором без
    утрат и дублей; ни один запрос не загружает все тела одновременно."""
    _seed_bulk(store, revisions=1050, activations=220)
    total_rows = len(store.revisions) + len(store.activations)
    assert total_rows >= 1200

    get_revision_calls = {"n": 0}
    real_get_revision = store.get_revision

    async def _counting_get_revision(revision_id):
        get_revision_calls["n"] += 1
        return await real_get_revision(revision_id)

    store.get_revision = _counting_get_revision

    seen = []
    cursor = None
    pages = 0
    while True:
        view = _run(prp.list_versions(BLOCK, store=store, actor="owner",
                                      page_size=200, cursor=cursor))
        seen.extend(view["entries"])
        pages += 1
        if not view["page"]["has_more"]:
            break
        cursor = view["page"]["next_cursor"]
        assert pages < 50, "курсор не доходит до конца истории"

    assert pages >= 7, f"слишком крупные страницы: {pages}"
    assert len(seen) == total_rows, "история потеряна или продублирована"
    keys = [(e["entry_type"], e["revision_id"], e.get("event_id"))
            for e in seen]
    assert len(set(keys)) == total_rows, "дубли записей в ленте"
    # Ни один запрос не тянет все тела: get_revision зовётся точечно.
    assert get_revision_calls["n"] < 30, \
        f"полная загрузка тел: {get_revision_calls['n']} вызовов"
    # И сами ленты не содержат тел.
    assert all("body" not in e for e in seen)
    raw = json.dumps(seen, ensure_ascii=False)
    assert "РЕВИЗИЯ 0000" not in raw
    assert "РЕВИЗИЯ 1049" not in raw


# ═══════════════════════════════════════════════════════════════════════════
# A3.2: история сохраняется, журнал только дописывается
# ═══════════════════════════════════════════════════════════════════════════

def test_a32_history_preserved_and_journal_append_only(edition, store):
    """A3.2 (L00051): версии/активации/baseline сохраняются; коррективы —
    только дополнительные записи; rollback и forward работают."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    _cutover(cache, store)
    factory = _revision_of(store, FACTORY_A)
    _save_global(cache, store, MANUAL_M)
    manual = _revision_of(store, MANUAL_M)
    _run(prp.assign_baseline(BLOCK, factory.revision_id, cache=cache,
                             store=store, actor="owner"))
    snapshot_revs = {rid: (row.body, row.content_sha12)
                     for rid, row in store.revisions.items()}
    snapshot_acts = [(a.block_id, a.kind, a.outcome, a.revision_id)
                     for a in store.activations]

    # Rollback к заводской, затем forward к ручной — оба работают.
    back = _run(prp.activate_revision(BLOCK, factory.revision_id,
                                      cache=cache, store=store,
                                      actor="owner"))
    assert back["applied"] is True
    assert _run(store.read_global(PG_KEY)) == FACTORY_A
    forward = _run(prp.activate_revision(BLOCK, manual.revision_id,
                                         cache=cache, store=store,
                                         actor="owner"))
    assert forward["applied"] is True
    assert _run(store.read_global(PG_KEY)) == MANUAL_M
    # Снятие baseline — дополнительное событие, история не переписана.
    cleared = _run(prp.clear_baseline(BLOCK, cache=cache, store=store,
                                      actor="owner"))
    assert cleared["applied"] is True
    # Все прежние строки журнала на месте и байт-в-байт те же.
    for rid, (body, sha) in snapshot_revs.items():
        row = store.revisions.get(rid)
        assert row is not None, f"ревизия {rid} удалена из истории"
        assert (row.body, row.content_sha12) == (body, sha)
    current_acts = [(a.block_id, a.kind, a.outcome, a.revision_id)
                    for a in store.activations]
    assert current_acts[:len(snapshot_acts)] == snapshot_acts, \
        "существующие события журнала переписаны"
    assert len(current_acts) > len(snapshot_acts)
    # Полный набор сущностей сохранился.
    assert {r.origin for r in store.revisions.values()} >= \
        {"factory", "manual"}
    kinds = {a.kind for a in store.activations}
    assert {"deploy_activate", "baseline_assign", "baseline_clear"} <= kinds
    view = _state(store)
    assert view["effective_revision_id"] == manual.revision_id


# ═══════════════════════════════════════════════════════════════════════════
# HTTP: плоские поля проходят через GET /api/prompts/{key}/versions;
# POST /api/config идемпотентен по operation_id (PVR-02/PVR-03)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def env(monkeypatch):
    patch = FactoryEdition(monkeypatch)
    patch.set_edition(BLOCK, "narrator-a", FACTORY_A)
    conn, cache, app = _build(monkeypatch)
    journal = prp.MemoryPromptJournal()
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache_: journal)
    monkeypatch.setattr(prp, "default_journal", lambda cache_: journal)
    # Тот же wiring чтения чат-профиля, что в проде (bot.py ставит кэш на пул).
    chat_params.set_chat_params_cache(chat_params.ChatParamsCache(cache.pg))
    # Активируем релизную политику (как в проде): иначе резолвер payload
    # честно удерживает незаписанное через журнал значение как pre-cutover.
    asyncio.run(prp.apply_release(cache, release_id="evol-016-cutover",
                                  store=journal, blocks=[BLOCK]))
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, cache=cache, journal=journal)
    chat_params.set_chat_params_cache(None)
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()
    routes_mod._PROMPT_OP_RESULTS.clear()


def test_api_versions_exposes_full_state_contract(env):
    """PVR-01: HTTP-ответ состояния содержит все плоские поля контракта и
    честные значения после сохранения владельцем."""
    text = "Глобальная правка владельца через HTTP.\n"
    saved = env.client.post(
        "/api/config", json={"items": [{"key": PG_KEY, "value": text}]},
        headers=_hdr(ADMIN_ID))
    assert saved.status_code == 200, saved.text
    resp = env.client.get(f"/api/prompts/{PG_KEY}/versions",
                          headers=_hdr(ADMIN_ID))
    assert resp.status_code == 200, resp.text
    view = resp.json()
    for field in PVR01_FIELDS:
        assert field in view, f"HTTP-ответ без поля {field}"
    assert view["draft_dirty"] is False
    assert view["effective_origin"] == "global"
    assert view["effective_content_hash"] == pr.sha12(text)
    assert view["effective_revision_id"] == view["journal_active_revision_id"]
    assert view["journal_last_activation_id"] is not None
    assert view["baseline_revision_id"] is None
    assert view["factory_revision_id"] == pr.sealed_factory_revision(BLOCK)
    assert view["effective_status"] == "matched"
    active = [e for e in view["entries"] if e.get("status") == "active"]
    assert len(active) == 1
    assert active[0]["revision_id"] == view["effective_revision_id"]


def test_api_config_save_is_idempotent_by_operation_id(env):
    """PVR-02/PVR-03: retry POST с тем же operation_id возвращает тот же
    ответ и не создаёт вторую запись журнала."""
    text = "Идемпотентное сохранение по operation_id.\n"
    body = {"items": [{"key": PG_KEY, "value": text}],
            "operation_id": "op-http-1"}
    first = env.client.post("/api/config", json=body, headers=_hdr(ADMIN_ID))
    assert first.status_code == 200, first.text
    revs = set(env.journal.revisions)
    acts = len(env.journal.activations)
    retry = env.client.post("/api/config", json=body, headers=_hdr(ADMIN_ID))
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert set(env.journal.revisions) == revs
    assert len(env.journal.activations) == acts
    # Другой operation_id — честный второй прогон (skipped_same, без дубля).
    body2 = {"items": [{"key": PG_KEY, "value": text}],
             "operation_id": "op-http-2"}
    second = env.client.post("/api/config", json=body2, headers=_hdr(ADMIN_ID))
    assert second.status_code == 200, second.text
    assert second.json()["skipped_same"] == [PG_KEY]
    assert set(env.journal.revisions) == revs
