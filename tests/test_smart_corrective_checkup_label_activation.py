"""SMART-CORRECTIVE-01 §8.5 / S6-ACTIVATION — метка заводской ревизии чекапа.

Срез S6-PROMPT исправил заводской жанр чекапа (удалён Betterstack и пример
401, добавлена смысловая граница смешанного состояния), но оставил прежнюю
метку `checkup-p0-24-10`. Релизная политика EVOL-016 решает активацию по
МЕТКЕ: тот же ``fac:<sha12(метки)>`` → ``PLAN_NOOP``, поэтому исправленный
текст не доходил до действующего глобального слоя, а промпт с устаревшим
Betterstack оставался активным. Сторож сохранённой ручной редакции чата
(owner §8.1) выпущен в 2.58.202, поэтому метка бампнута. Этот файл доказывает
наблюдаемый контракт шага активации:

  * метка и печать согласованы, байты заводской редакции не изменились;
  * поставка с новой меткой активирует исправленный заводской текст в
    глобальном слое — устаревшего Betterstack/401 в активном контуре нет;
  * чат без сохранённой ручной ревизии получает заводской текст обычным
    путём (override снимается), прежние байты остаются в истории;
  * чат с живой ручной ревизией сохраняет свои байты БАЙТ-В-БАЙТ, получает
    диагностику ``factory_superseded_manual``, а заводская ревизия остаётся в
    истории (поставка не потеряна); клонов/переписывания значений нет;
  * явный owner ``baseline_assign`` сохраняет приоритет;
  * рестарт/повтор той же метки — истинный no-op;
  * чатовая изоляция: защита ручной редакции не распространяется на другие
    чаты.

TEST-LIFECYCLE: CONTRACT owner=smart-corrective-01 §8.5 + §8.1 (S6-ACTIVATION)
"""
from __future__ import annotations

import asyncio

import pytest

from services import hot_config as hot
from services import prompt_factory as pf
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from services.checkup_prompts import (
    CHECKUP_SYSTEM_PROMPT,
    PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT,
)
from tests.test_evol016_prompt_activation import FactoryEdition, FakeCache

BLOCK = "checkup.base.system"
KEY = "prompts.checkup_system_prompt"

#: Метка, под которой работал прод до S6-ACTIVATION (2.58.200–2.58.202).
PREVIOUS_LABEL = "checkup-p0-24-10"
#: Метка этой поставки (читается из кода модуля при импорте, без патчей).
ACTIVE_LABEL = pr.FACTORY_REVISION_LABELS[BLOCK]
PREVIOUS_FACTORY_REVISION = pr.FACTORY_PREFIX + pr.sha12(PREVIOUS_LABEL)

CHAT_MANUAL = -1002201
CHAT_OVERRIDE = -1002202

#: Редакция владельца масштаба production C2 (12 469 chars) — байты, которые
#: новая заводская поставка не имеет права перетереть.
OWNER_TEXT = (
    "СИСТЕМНАЯ РОЛЬ И ЗАДАЧА:\n"
    "Владельческая редакция чекапа этого чата.\n\n"
    + "Авторский абзац разбора без Betterstack. " * 320
    + "\n\nОБЪЁМ:\nНе больше {max_symbols} символов.")


def _release(cache, store, release_id: str):
    return asyncio.run(prp.apply_release(cache, release_id=release_id,
                                         store=store, blocks=[BLOCK]))


def _row(result, *, scope: str, chat_id: int | None = None):
    for row in result["results"]:
        if (row.block_id, row.scope, row.chat_id) == (BLOCK, scope, chat_id):
            return row
    raise AssertionError(
        f"результат релиза для {BLOCK}/{scope}/{chat_id} не найден")


def _manual_revision(store, chat_id: int = CHAT_MANUAL):
    rows = [r for r in store.revisions.values()
            if r.block_id == BLOCK and r.origin == "manual"
            and r.scope == "chat" and (r.chat_id or None) == chat_id]
    assert len(rows) == 1, rows
    return rows[0]


def _factory_revision(store, *, scope: str, chat_id: int | None):
    rows = [r for r in store.revisions.values()
            if r.block_id == BLOCK and r.origin == "factory"
            and r.scope == scope and (r.chat_id or None) == chat_id
            and r.content_sha12 == pr.sha12(CHECKUP_SYSTEM_PROMPT)]
    assert len(rows) == 1, rows
    return rows[0]


@pytest.fixture(autouse=True)
def _reset_release_state():
    # Явное состояние процесса на входе И на выходе: релизный проход включает
    # политику и замораживает ``character.prompt_history``, а тесты провенанса
    # ниже проверяют именно pre-cutover контракт.
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()
    yield
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()


@pytest.fixture()
def store():
    return prp.MemoryPromptJournal()


@pytest.fixture()
def previous_deploy(monkeypatch, store):
    """Состояние прода до S6-ACTIVATION: та же метка, прежние байты (3 030).

    Активная заводская ревизия — ``fac:sha12("checkup-p0-24-10")``,
    глобальное значение — редакция 2.58.200 с устаревшим Betterstack.
    """
    edition = FactoryEdition(monkeypatch)
    edition.set_edition(BLOCK, PREVIOUS_LABEL,
                        PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT)
    cache = FakeCache({KEY: PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT})
    _release(cache, store, "deploy-2.58.202")
    state = asyncio.run(store.read_applied(BLOCK, "global", None))
    assert state.factory_revision_applied == PREVIOUS_FACTORY_REVISION
    assert cache.values[KEY] == PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT
    return edition, cache


def _switch_to_this_release(edition) -> None:
    """Код этой поставки: реальные метка, печать и байты из реестра."""
    edition.set_edition(BLOCK, ACTIVE_LABEL, CHECKUP_SYSTEM_PROMPT)


def _manual_owner_edition(cache, store, chat_id: int = CHAT_MANUAL):
    """Сохранённая владельцем ручная редакция чата (как CHAT_C2 в проде)."""
    written = asyncio.run(prp.write_versioned_value(
        BLOCK, OWNER_TEXT, scope="chat", chat_id=chat_id, cache=cache,
        store=store, actor="owner"))
    assert written["applied"] is True
    assert store.chat_overrides[chat_id][KEY] == OWNER_TEXT
    return _manual_revision(store, chat_id)


# ═══ 1. Метка/печать/текст: согласованность ревизии ═════════════════════════

def test_label_bumped_with_intact_seal_and_unchanged_text():
    label, sealed_sha = pr.FACTORY_REVISION_SEALS[BLOCK]
    assert label == ACTIVE_LABEL == pr.FACTORY_REVISION_LABELS[BLOCK]
    assert label == "checkup-p0-24-10-mixed-state"
    assert label != PREVIOUS_LABEL
    assert pr.seal_integrity() == {}
    # Байты заводской редакции — те же, что выпустил S6-PROMPT.
    assert sealed_sha == pr.sha12(CHECKUP_SYSTEM_PROMPT) == "3140bb364044"
    assert len(CHECKUP_SYSTEM_PROMPT) == 3462
    assert pr.sealed_factory_revision(BLOCK) == pr.FACTORY_PREFIX + \
        pr.sha12(ACTIVE_LABEL)
    assert pr.sealed_factory_revision(BLOCK) != PREVIOUS_FACTORY_REVISION
    # Новая метка = новая заводская ревизия для когда-то применённой старой.
    plan = pr.activation_plan(
        code_label=label, sealed_sha=sealed_sha,
        text_sha12=pr.sha12(CHECKUP_SYSTEM_PROMPT),
        applied_factory_revision=PREVIOUS_FACTORY_REVISION, has_import=True)
    assert plan.action == pr.PLAN_ACTIVATE
    assert plan.reason == "new_factory_revision"
    # Устаревшего Betterstack/401 в активном заводском тексте нет, прежние
    # байты не переписаны — они остаются историческим слепком.
    lowered = CHECKUP_SYSTEM_PROMPT.casefold()
    assert "betterstack" not in lowered
    assert "401" not in CHECKUP_SYSTEM_PROMPT
    assert "Betterstack" in PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT


# ═══ 2. Новая метка активирует исправленный заводской текст глобально ═══════

def test_new_label_activates_factory_in_global_layer(previous_deploy, store):
    edition, cache = previous_deploy
    assert "Betterstack" in cache.values[KEY]

    _switch_to_this_release(edition)
    release = _release(cache, store, "deploy-2.58.203")

    row = _row(release, scope="global")
    assert row.action == pr.PLAN_ACTIVATE
    assert (row.outcome, row.detail_code) == ("applied", "factory_activate")
    assert row.factory_revision_applied == pr.sealed_factory_revision(BLOCK)
    # Действующий глобальный слой — исправленная фабрика без stale-текста.
    assert cache.values[KEY] == CHECKUP_SYSTEM_PROMPT
    assert "betterstack" not in cache.values[KEY].casefold()
    assert "401" not in cache.values[KEY]
    # Прежние байты не переписаны: они лежат в истории как ревизия.
    shas = {r.content_sha12 for r in store.revisions.values()
            if r.block_id == BLOCK}
    assert pr.sha12(PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT) in shas
    _factory_revision(store, scope="global", chat_id=None)


# ═══ 3. Чат без ручной ревизии получает новую фабрику ══════════════════════

def test_chat_without_manual_revision_gets_new_factory(previous_deploy, store):
    edition, cache = previous_deploy
    # У чата есть прежний override, но сохранённой ручной ревизии нет.
    store.chat_overrides[CHAT_OVERRIDE] = {
        KEY: PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT}

    _switch_to_this_release(edition)
    release = _release(cache, store, "deploy-2.58.203")

    row = _row(release, scope="chat", chat_id=CHAT_OVERRIDE)
    assert row.outcome == "applied"
    assert row.detail_code == "factory_activate"
    assert row.factory_revision_applied == pr.sealed_factory_revision(BLOCK)
    # Заводская политика прежняя: старый override снят, чат читает новый
    # глобальный слой; байты снятого override сохранены в истории.
    assert KEY not in store.chat_overrides.get(CHAT_OVERRIDE, {})
    assert CHAT_OVERRIDE in store.notified_chats
    chat_shas = {r.content_sha12 for r in store.revisions.values()
                 if r.scope == "chat" and r.chat_id == CHAT_OVERRIDE}
    assert pr.sha12(PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT) in chat_shas
    assert pr.sha12(CHECKUP_SYSTEM_PROMPT) in chat_shas
    assert cache.values[KEY] == CHECKUP_SYSTEM_PROMPT


# ═══ 4. Чат с ручной ревизией сохраняет байты ══════════════════════════════

def test_manual_chat_edition_survives_label_bump(previous_deploy, store):
    edition, cache = previous_deploy
    manual = _manual_owner_edition(cache, store)
    bytes_before = manual.body
    sha_before = manual.content_sha12
    assert len(bytes_before) > 12000        # масштаб production C2
    notified_before = len(store.notified_chats)
    revisions_before = len(store.revisions)

    _switch_to_this_release(edition)
    release = _release(cache, store, "deploy-2.58.203")

    row = _row(release, scope="chat", chat_id=CHAT_MANUAL)
    assert row.action == pr.PLAN_ACTIVATE
    assert (row.outcome, row.detail_code) == ("skipped_same",
                                              "factory_superseded_manual")
    # Действующие байты чата — сохранённая редакция; override не снят.
    assert store.chat_overrides[CHAT_MANUAL][KEY] == OWNER_TEXT
    # Байты ручной ревизии не изменились, клонов/снимков не появилось.
    assert store.revisions[manual.revision_id].body == bytes_before
    assert store.revisions[manual.revision_id].content_sha12 == sha_before
    assert store.revisions[manual.revision_id].origin == "manual"
    # Поставка не потеряна: заводская ревизия записана в историю этого чата.
    chat_factory = _factory_revision(store, scope="chat", chat_id=CHAT_MANUAL)
    assert chat_factory.factory_revision == pr.sealed_factory_revision(BLOCK)
    # Ровно две новые ревизии: заводская для global и для этого чата.
    assert len(store.revisions) == revisions_before + 2
    # Значение чата не менялось — уведомления чату не было.
    assert len(store.notified_chats) == notified_before
    # Диагностика записана в журнал активаций.
    event = store.activations[-1]
    assert (event.kind, event.outcome, event.detail_code) == (
        "deploy_activate", "skipped_same", "factory_superseded_manual")
    assert event.factory_revision_applied == pr.sealed_factory_revision(BLOCK)
    # Незакреплённый глобальный слой получил исправленный заводской текст.
    assert cache.values[KEY] == CHECKUP_SYSTEM_PROMPT


# ═══ 5. Явный owner baseline сохраняет приоритет ═══════════════════════════

def test_explicit_baseline_assign_still_wins(previous_deploy, store):
    edition, cache = previous_deploy
    manual = _manual_owner_edition(cache, store)
    asyncio.run(prp.assign_baseline(BLOCK, manual.revision_id, scope="chat",
                                    chat_id=CHAT_MANUAL, actor="owner",
                                    cache=cache, store=store))

    _switch_to_this_release(edition)
    release = _release(cache, store, "deploy-2.58.203")

    row = _row(release, scope="chat", chat_id=CHAT_MANUAL)
    assert row.action == pr.PLAN_ACTIVATE_PINNED
    assert (row.outcome, row.detail_code) == ("skipped_same",
                                              "factory_superseded_pinned")
    assert store.chat_overrides[CHAT_MANUAL][KEY] == OWNER_TEXT
    state = asyncio.run(store.read_applied(BLOCK, "chat", CHAT_MANUAL))
    assert state.revision_id == manual.revision_id
    assert state.factory_revision_applied == pr.sealed_factory_revision(BLOCK)


# ═══ 6. Рестарт/повтор — истинный no-op ═════════════════════════════════════

def test_restart_after_label_bump_is_true_noop(previous_deploy, store):
    edition, cache = previous_deploy
    _manual_owner_edition(cache, store)
    _switch_to_this_release(edition)
    _release(cache, store, "deploy-2.58.203")

    before = (len(store.activations), len(store.revisions))
    cache.set_calls.clear()
    _release(cache, store, "restart-2.58.203")

    assert (len(store.activations), len(store.revisions)) == before
    assert cache.set_calls == []
    assert store.chat_overrides[CHAT_MANUAL][KEY] == OWNER_TEXT
    assert [a for a in store.activations
            if a.detail_code == "activation_drift"] == []


# ═══ 7. Чатовая изоляция ════════════════════════════════════════════════════

def test_manual_guard_is_isolated_to_its_chat(previous_deploy, store):
    edition, cache = previous_deploy
    manual = _manual_owner_edition(cache, store)
    store.chat_overrides[CHAT_OVERRIDE] = {
        KEY: PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT}

    _switch_to_this_release(edition)
    release = _release(cache, store, "deploy-2.58.203")

    own = _row(release, scope="chat", chat_id=CHAT_MANUAL)
    assert (own.outcome, own.detail_code) == ("skipped_same",
                                              "factory_superseded_manual")
    assert store.chat_overrides[CHAT_MANUAL][KEY] == OWNER_TEXT
    other = _row(release, scope="chat", chat_id=CHAT_OVERRIDE)
    assert (other.outcome, other.detail_code) == ("applied",
                                                  "factory_activate")
    assert KEY not in store.chat_overrides.get(CHAT_OVERRIDE, {})
    # Ручная ревизия осталась ровно одна и с прежними байтами.
    assert _manual_revision(store).revision_id == manual.revision_id
    assert _manual_revision(store).content_sha12 == pr.sha12(OWNER_TEXT)


# ═══ 8. Провенанс: новая метка = аттестованная фабрика, чужое — withheld ════
#
# Метка входит в идентичность заводской ревизии (``factory_revision`` /
# ``sealed_factory_revision``). Проверяем, что исправленная редакция под новой
# меткой остаётся АТТЕСТОВАННОЙ для effective-слоя, а незарегистрированное
# значение по-прежнему удерживается (шлагбаум не ослаблен).

class DictCache:
    """Контракт ConfigCache (sync get / async set) для effective-пути."""

    def __init__(self, values=None):
        self.pg_available = True
        self.values = dict(values or {})
        self.set_calls: list[tuple[str, object, str]] = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_updated_at(self, key):
        return None

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))
        self.values[key] = value


def _effective(cache, value):
    hot.set_config_cache(cache)
    try:
        return pr.effective_prompt(BLOCK, pg_value=value)
    finally:
        hot.set_config_cache(None)


@pytest.mark.usefixtures("prompt_journal")
def test_new_label_factory_value_is_attested_for_effective_prompt():
    cache = DictCache()
    written = asyncio.run(pf.write_speech_value(
        BLOCK, CHECKUP_SYSTEM_PROMPT, cache=cache, actor="test",
        reason="owner_edit:contract"))
    assert written["applied"] is True
    assert written["provenance_persisted"] is True

    eff = _effective(cache, cache.values[KEY])

    assert eff.source == "global"
    assert eff.withheld is False
    assert eff.withheld_revision == ""
    assert eff.provenance_reason == "attested"
    assert eff.revision == pr.ACTIVE_PREFIX + pr.sha12(CHECKUP_SYSTEM_PROMPT)
    # Идентичность заводской редакции в effective-виде — с НОВОЙ меткой и
    # печатью содержимого (``fac:<sha12 текста>(<метка>)``).
    assert eff.factory_revision == pr.factory_revision(BLOCK)
    assert eff.factory_revision == (
        pr.FACTORY_PREFIX + pr.sha12(CHECKUP_SYSTEM_PROMPT)
        + f"({ACTIVE_LABEL})")
    assert eff.text == CHECKUP_SYSTEM_PROMPT


def test_unregistered_value_is_still_withheld():
    custom = "Своя редакция чекапа без записи через реестр. " * 60
    cache = DictCache({KEY: custom})

    eff = _effective(cache, custom)

    assert eff.withheld is True
    assert eff.source == "default"
    assert eff.provenance_reason == "provenance_missing"
    assert eff.withheld_sha256_12 == pr.sha12(custom)
    # Действует заводская редакция этой поставки, а не чужой persisted-текст.
    assert eff.text == CHECKUP_SYSTEM_PROMPT
