"""PVR-S2 — owner baseline как указатель на неизменяемую ревизию.

Контракт: ``plans/features/prompt-versioning-ux/arch/versioning-ux-contract.md``
§2 (baseline = событие существующего журнала, без DDL), §4 (заводская и
owner-базовая — разные сущности), §7.3 п.4–6 (что обязано быть опровергнуто).
Требования владельца: §4 ТЗ (все пункты) и §6 ТЗ (бэкенд).

Проверяется поведение, а не наличие строк:

  1. «Назначить базовой» меняет ТОЛЬКО указатель: активные байты и
     ``read_applied`` не двигаются, событие ``baseline_assign``/``recorded``;
  2. повторное назначение идемпотентно (новой строки журнала нет);
  3. «Снять назначение» пишет ``baseline_clear`` и НЕ меняет активный текст;
  4. закреплённый scope: новая заводская метка → ревизия в историю, значение
     не пишется (байтовое сравнение), следующий рестарт — истинный no-op без
     ``activation_drift``; незакреплённый — прежняя релизная политика (кроме
     chat scope с сохранённой ручной ревизией: её защищает guard
     SMART-CORRECTIVE-01 §8.1/AC-19);
  5. чатовый baseline действует ТОЛЬКО в своём чате; снятие override
     наследует global effective, а не чатовый baseline;
  6. чужой/retired/несовместимый revision — отказ, ни одного изменения;
  7. «Восстановить базовую» и «Вернуть исходную из кода» — разные явные
     активации; вторая требует подтверждения и не снимает baseline;
  8. копирование чатового текста «как новой глобальной версии» — новая
     ревизия с провенансом, без перепривязки ``revision_id``;
  9. миграция ничего не назначает: после cutover baseline нет ни у кого.

Дисциплина записи (тот же advisory-лок, одна транзакция, порядок
``lock → tx → insert_activation``) проверяется трассировкой стора, а не
чтением кода тестами.

TEST-LIFECYCLE: CONTRACT owner=EPIC-PROMPT-VERSIONING-UX-01
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services import prompt_factory as pf
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from tests.test_evol016_prompt_activation import FakeCache, FactoryEdition
from tests.test_meme_pipeline_api import _build
from tests.test_webapp_api import ADMIN_ID, _hdr
from web.api import routes as routes_mod

BLOCK = "summary.base.narrator"
PG_KEY = "prompts.summary_narrator_system_prompt"

CHAT_A = -1009001
CHAT_B = -1009002

FACTORY_A = "ЗАВОДСКАЯ A: рассказчик саммари (байт-эталон baseline-тестов).\n"
FACTORY_B = ("ЗАВОДСКАЯ B: новая метка релиза — этот текст НЕ должен заменить "
             "закреплённый владельцем.\n")
MANUAL_M = "РУЧНАЯ ПРАВКА M: владелец отредактировал рассказчика вручную.\n"
CHAT_A_TEXT = "ЧАТ A: собственный текст этого чата (baseline этого чата).\n"
CHAT_B_TEXT = "ЧАТ B: собственный текст другого чата.\n"

BASELINE_KINDS = ("baseline_assign", "baseline_clear")


# ═══════════════════════════════════════════════════════════════════════════
# Стенд: заводская редакция A + in-memory журнал
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def edition(monkeypatch):
    patch = FactoryEdition(monkeypatch)
    patch.set_edition(BLOCK, "narrator-a", FACTORY_A)
    yield patch
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()


@pytest.fixture()
def store():
    return prp.MemoryPromptJournal()


async def _cutover(cache, store, release_id="evol-016-cutover"):
    return await prp.apply_release(cache, release_id=release_id, store=store,
                                   blocks=[BLOCK])


async def _manual_global(cache, store, text=MANUAL_M):
    await prp.write_versioned_value(BLOCK, text, cache=cache, store=store,
                                    actor="owner")
    return await _revision_of(store, text, scope="global")


async def _chat_text(store, cache, chat_id, text):
    await prp.write_versioned_value(BLOCK, text, scope="chat", chat_id=chat_id,
                                    cache=cache, store=store, actor="owner")
    return await _revision_of(store, text, scope="chat", chat_id=chat_id)


async def _revision_of(store, text, *, scope, chat_id=None, origin=None):
    sha = pr.sha12(text)
    for row in store.revisions.values():
        if (row.block_id == BLOCK and row.scope == scope
                and row.content_sha12 == sha
                and (origin is None or row.origin == origin)
                and (row.chat_id or None) == (chat_id or None)):
            return row
    raise AssertionError(f"ревизия текста не найдена: scope={scope} "
                         f"origin={origin}")


def _result_row(result, scope="global", chat_id=None):
    for row in result["results"]:
        if (row.block_id, row.scope, row.chat_id) == (BLOCK, scope, chat_id):
            return row
    raise AssertionError("результат релиза для адресата не найден")


async def _baseline(store, cache, *, scope="global", chat_id=None):
    return await prp.read_baseline(BLOCK, scope=scope, chat_id=chat_id,
                                   cache=cache, store=store, actor="owner")


def _baseline_events(store):
    return [a for a in store.activations if a.kind in BASELINE_KINDS]


async def _stored_global(store, key=PG_KEY):
    """Фактическое значение в хранилище журнала (не память кэша)."""
    return await store.read_global(key)


class _RecordingJournal(prp.MemoryPromptJournal):
    """Стор с трассировкой порядка операций (лок → транзакция → событие)."""

    def __init__(self):
        super().__init__()
        self.trace: list[str] = []

    def apply_lock(self):
        outer = super().apply_lock()

        class _Lock:
            async def __aenter__(self):
                self_.trace.append("lock")
                return await outer.__aenter__()

            async def __aexit__(self, *exc):
                return await outer.__aexit__(*exc)

        self_ = self
        return _Lock()

    def transaction(self):
        inner = super().transaction()

        class _Tx:
            async def __aenter__(self):
                self_.trace.append("tx_enter")
                return await inner.__aenter__()

            async def __aexit__(self, *exc):
                self_.trace.append("tx_exit")
                return await inner.__aexit__(*exc)

        self_ = self
        return _Tx()

    async def insert_activation(self, row):
        self.trace.append(f"insert:{row.kind}:{row.outcome}")
        return await super().insert_activation(row)


# ═══════════════════════════════════════════════════════════════════════════
# 1–3. Указатель, а не активация
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_assign_baseline_is_pointer_only(edition, store):
    """§2.4 п.1: назначение меняет указатель, активный текст — нет."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    manual = await _manual_global(cache, store)
    before_applied = await store.read_applied(BLOCK, "global", None)
    before_events = len(store.activations)
    factory = await _revision_of(store, FACTORY_A, scope="global",
                                 origin="factory")

    res = await prp.assign_baseline(BLOCK, factory.revision_id, scope="global",
                                    actor="owner", cache=cache, store=store)

    assert res["applied"] is True and res["outcome"] == "recorded"
    assert res["active_text_changed"] is False
    assert res["reason"] == "ok"
    # Байтовое сравнение действующего текста — не изменился.
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()
    # ...и значение в самом хранилище (не память кэша) тоже прежнее.
    assert (await _stored_global(store)).encode() == MANUAL_M.encode()
    after_applied = await store.read_applied(BLOCK, "global", None)
    assert after_applied.revision_id == before_applied.revision_id
    assert after_applied.factory_revision_applied == \
        before_applied.factory_revision_applied
    assert len(store.activations) == before_events + 1
    event = store.activations[-1]
    assert (event.kind, event.outcome) == ("baseline_assign", "recorded")
    assert event.revision_id == factory.revision_id
    assert event.detail_code == "baseline:factory"
    assert event.actor == "owner"
    # Провенанс указателя читается отдельно и честно.
    state = await _baseline(store, cache)
    assert state["known"] is True
    assert state["source"] == "owner"
    assert state["baseline"]["revision_id"] == factory.revision_id
    assert state["baseline"]["origin"] == "factory"
    assert state["baseline"]["assigned_by"] == "owner"
    assert state["baseline"]["is_active"] is False   # активна ручная M


@pytest.mark.asyncio
async def test_assign_baseline_same_revision_is_idempotent(edition, store):
    """§2.4 п.2 ТЗ: повтор «назначить базовой» не растит журнал."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    manual = await _manual_global(cache, store)
    first = await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                                      cache=cache, store=store)
    assert first["applied"] is True
    events_after_first = len(store.activations)

    second = await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                                       cache=cache, store=store)

    assert second["applied"] is False
    assert second["reason"] == "baseline_same"
    assert second["outcome"] == "skipped_same"
    assert second["idempotent"] is True
    assert len(store.activations) == events_after_first
    assert len(_baseline_events(store)) == 1


@pytest.mark.asyncio
async def test_clear_baseline_keeps_active_text(edition, store):
    """§2.4 п.4: снятие назначения — не активация и не снятие override."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    manual = await _manual_global(cache, store)
    await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                              cache=cache, store=store)
    before_applied = await store.read_applied(BLOCK, "global", None)

    res = await prp.clear_baseline(BLOCK, actor="owner", cache=cache,
                                   store=store)

    assert res["applied"] is True and res["outcome"] == "recorded"
    assert res["cleared_revision_id"] == manual.revision_id
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()
    after_applied = await store.read_applied(BLOCK, "global", None)
    assert after_applied.revision_id == before_applied.revision_id
    assert store.activations[-1].kind == "baseline_clear"
    assert store.activations[-1].revision_id == ""
    state = await _baseline(store, cache)
    assert state["baseline"] is None
    assert state["source"] == "factory"       # снова встроенная из кода
    assert state["cleared_at"]
    # Повтор идемпотентен и журнал не растёт.
    events = len(store.activations)
    again = await prp.clear_baseline(BLOCK, actor="owner", cache=cache,
                                     store=store)
    assert again["applied"] is False and again["reason"] == "baseline_absent"
    assert len(store.activations) == events


# ═══════════════════════════════════════════════════════════════════════════
# 4. Закреплённый / незакреплённый scope и новая заводская поставка
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pinned_global_scope_survives_new_factory_release(edition, store):
    """§2.4 п.3 / §7.3 п.4: pin защищает текст, рестарт — истинный no-op."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    manual = await _manual_global(cache, store)
    await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                              cache=cache, store=store)

    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    release = await _cutover(cache, store, release_id="deploy-b")

    row = _result_row(release)
    assert row.outcome == "skipped_same"
    assert row.detail_code == "factory_superseded_pinned"
    # Действующий текст — байты ручной правки, НЕ заводской B.
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()
    assert (await _stored_global(store)).encode() == MANUAL_M.encode()
    # Заводская ревизия B всё же попала в историю (не потеряна).
    shas = {r.content_sha12 for r in store.revisions.values()
            if r.block_id == BLOCK}
    assert pr.sha12(FACTORY_B) in shas
    # Указатель применённой метки двигается → рестарт не повторит поставку.
    applied = await store.read_applied(BLOCK, "global", None)
    assert applied.factory_revision_applied == \
        pr.FACTORY_PREFIX + pr.sha12("narrator-b")
    assert applied.revision_id == manual.revision_id
    # Owner baseline не переписан.
    state = await _baseline(store, cache)
    assert state["baseline"]["revision_id"] == manual.revision_id

    # Рестарт с той же меткой: ни строки, ни дрейфа, ни изменения байтов.
    events = len(store.activations)
    revisions = len(store.revisions)
    await _cutover(cache, store, release_id="restart-2")
    assert len(store.activations) == events
    assert len(store.revisions) == revisions
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()
    assert [a for a in store.activations if a.detail_code ==
            "activation_drift"] == []


@pytest.mark.asyncio
async def test_unpinned_global_scope_keeps_release_policy(edition, store):
    """Для незакреплённых промптов сохраняется прежняя релизная политика."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    await _manual_global(cache, store)
    assert (await _baseline(store, cache))["baseline"] is None

    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    release = await _cutover(cache, store, release_id="deploy-b")

    row = _result_row(release)
    assert row.outcome == "applied" and row.detail_code == "factory_activate"
    assert cache.values[PG_KEY].encode() == FACTORY_B.encode()
    # Ручная правка остаётся историей (не удалена), baseline не появился.
    assert pr.sha12(MANUAL_M) in {r.content_sha12 for r in
                                  store.revisions.values()}
    assert (await _baseline(store, cache))["baseline"] is None


@pytest.mark.asyncio
async def test_pinned_chat_scope_keeps_override(edition, store):
    """§7.3 п.4 (R4): закреплённый чат не теряет свой override при релизе."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    chat_rev = await _chat_text(store, cache, CHAT_A, CHAT_A_TEXT)
    await prp.assign_baseline(BLOCK, chat_rev.revision_id, scope="chat",
                              chat_id=CHAT_A, actor="owner", cache=cache,
                              store=store)

    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    release = await _cutover(cache, store, release_id="deploy-b")

    row = _result_row(release, scope="chat", chat_id=CHAT_A)
    assert row.outcome == "skipped_same"
    assert row.detail_code == "factory_superseded_pinned"
    # Override НЕ снят, байты прежние.
    assert store.chat_overrides.get(CHAT_A, {}).get(PG_KEY).encode() == \
        CHAT_A_TEXT.encode()
    # Глобальный scope (незакреплён) получил заводской текст как обычно.
    assert cache.values[PG_KEY].encode() == FACTORY_B.encode()
    state = await _baseline(store, cache, scope="chat", chat_id=CHAT_A)
    assert state["baseline"]["revision_id"] == chat_rev.revision_id


@pytest.mark.asyncio
async def test_unpinned_chat_scope_without_saved_edition_keeps_previous_policy(
        edition, store):
    """Незакреплённый чат без сохранённой редакции: новая метка снимает override.

    Override без ручной ревизии — прежняя релизная политика (как EVOL-016).
    Сохранённую ручную редакцию чата новая метка уже не снимает
    (SMART-CORRECTIVE-01 §8.1/AC-19, guard в `_apply_scope_release`).
    """
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    store.chat_overrides[CHAT_A] = {PG_KEY: CHAT_A_TEXT}

    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    await _cutover(cache, store, release_id="deploy-b")

    assert PG_KEY not in store.chat_overrides.get(CHAT_A, {})
    # Байты снятого override сохранены в истории.
    assert pr.sha12(CHAT_A_TEXT) in {r.content_sha12
                                     for r in store.revisions.values()
                                     if r.scope == "chat"}


# ═══════════════════════════════════════════════════════════════════════════
# 5. Изоляция чатов и наследование global
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_chat_baseline_is_isolated_between_two_chats(edition, store):
    """§2.4 п.5: чатовый baseline относится только к своему чату."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    rev_a = await _chat_text(store, cache, CHAT_A, CHAT_A_TEXT)
    # У чата B — override без сохранённой ручной ревизии (обычная политика).
    store.chat_overrides[CHAT_B] = {PG_KEY: CHAT_B_TEXT}
    await prp.assign_baseline(BLOCK, rev_a.revision_id, scope="chat",
                              chat_id=CHAT_A, actor="owner", cache=cache,
                              store=store)

    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    await _cutover(cache, store, release_id="deploy-b")

    # Чат A закреплён — свой текст цел; чат B — обычная политика (override снят).
    assert store.chat_overrides.get(CHAT_A, {}).get(PG_KEY).encode() == \
        CHAT_A_TEXT.encode()
    assert PG_KEY not in store.chat_overrides.get(CHAT_B, {})
    assert (await _baseline(store, cache, scope="chat",
                            chat_id=CHAT_A))["baseline"]["revision_id"] == \
        rev_a.revision_id
    assert (await _baseline(store, cache, scope="chat",
                            chat_id=CHAT_B))["baseline"] is None
    # Глобальный baseline не возник «за компанию».
    assert (await _baseline(store, cache))["baseline"] is None


@pytest.mark.asyncio
async def test_removing_chat_override_inherits_global_not_chat_baseline(
        edition, store):
    """§2.4 п.5: снятие override — наследование global, а не своя базовая."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    chat_rev = await _chat_text(store, cache, CHAT_A, CHAT_A_TEXT)
    await prp.assign_baseline(BLOCK, chat_rev.revision_id, scope="chat",
                              chat_id=CHAT_A, actor="owner", cache=cache,
                              store=store)
    await _manual_global(cache, store)          # global effective = MANUAL_M
    before_chat_applied = await store.read_applied(BLOCK, "chat", CHAT_A)

    res = await prp.remove_prompt_override(BLOCK, chat_id=CHAT_A, actor="owner",
                                           cache=cache, store=store)

    assert res["applied"] is True
    assert PG_KEY not in store.chat_overrides.get(CHAT_A, {})
    # Активный указатель чата не сдвинут событием снятия.
    after_chat_applied = await store.read_applied(BLOCK, "chat", CHAT_A)
    assert after_chat_applied.revision_id == before_chat_applied.revision_id
    # Глобальное значение не тронуто: наследование даёт именно его.
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()
    # Своё значение чата исчезло — эффективный слой теперь глобальный.
    assert await prp._read_override_value(store, CHAT_A, PG_KEY) is None
    # Чатовый baseline сохранён в журнале, но НЕ применён самовольно:
    # его текст не появился ни в чате, ни в глобальном значении.
    state = await _baseline(store, cache, scope="chat", chat_id=CHAT_A)
    assert state["baseline"]["revision_id"] == chat_rev.revision_id
    assert CHAT_A_TEXT != cache.values[PG_KEY]
    assert store.activations[-1].kind == "chat_inherit_reset"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Отказы: чужой scope, retired, несовместимость
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_foreign_revision_cannot_be_baseline(edition, store):
    """§7.3 п.6: чужой чат/scope и чужой блок — отказ без изменений."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    rev_a = await _chat_text(store, cache, CHAT_A, CHAT_A_TEXT)
    rev_b = await _chat_text(store, cache, CHAT_B, CHAT_B_TEXT)
    manual = await _manual_global(cache, store)
    events_before = len(store.activations)

    # Чужая чатовая ревизия → этот чат.
    res = await prp.assign_baseline(BLOCK, rev_b.revision_id, scope="chat",
                                    chat_id=CHAT_A, actor="owner",
                                    cache=cache, store=store)
    assert res["applied"] is False and res["reason"] == "revision_foreign_scope"
    # Чатовая ревизия → global (перенос только через copy-to-global).
    res = await prp.assign_baseline(BLOCK, rev_a.revision_id, scope="global",
                                    actor="owner", cache=cache, store=store)
    assert res["applied"] is False and res["reason"] == "revision_foreign_scope"
    # Глобальная ревизия → чатовый scope.
    res = await prp.assign_baseline(BLOCK, manual.revision_id, scope="chat",
                                    chat_id=CHAT_A, actor="owner",
                                    cache=cache, store=store)
    assert res["applied"] is False and res["reason"] == "revision_foreign_scope"
    # Ревизия другого промпта.
    other = next(b for b in pr.all_blocks()
                 if b.pg_key and b.block_id != BLOCK)
    foreign_row = prp.RevisionRow(
        revision_id="rev:foreignblock0001", block_id=other.block_id,
        scope="global", origin="manual", content_sha12=pr.sha12("чужой блок"),
        body="чужой блок", pg_key=other.pg_key or "")
    store.revisions[foreign_row.revision_id] = foreign_row
    res = await prp.assign_baseline(BLOCK, foreign_row.revision_id,
                                    scope="global", actor="owner",
                                    cache=cache, store=store)
    assert res["applied"] is False and res["reason"] == "revision_unknown"

    # Ни одного baseline-события и никаких изменений текста/указателя.
    assert _baseline_events(store) == []
    assert len(store.activations) == events_before
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()


@pytest.mark.asyncio
async def test_retired_and_incompatible_revisions_are_read_but_not_baseline(
        edition, store):
    """§2.4 п.9: читать/сравнивать можно, назначать и включать — нельзя."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    manual = await _manual_global(cache, store)
    store.revisions[manual.revision_id].schema_compat = "schema-v2"

    res = await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                                    cache=cache, store=store)
    assert res["applied"] is False and res["reason"] == "schema_incompatible"
    assert res["schema_compat"] == "schema-v2"
    activate = await prp.activate_revision(BLOCK, manual.revision_id,
                                           actor="owner", cache=cache,
                                           store=store)
    assert activate["applied"] is False
    assert activate["reason"] == "schema_incompatible"

    store.revisions[manual.revision_id].schema_compat = ""
    store.revisions[manual.revision_id].retired = True
    res = await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                                    cache=cache, store=store)
    assert res["applied"] is False and res["reason"] == "revision_retired"

    # Чтение и сравнение несовместимой/retired ревизии остаются доступны.
    src = await prp.get_revision_source(manual.revision_id, cache=cache,
                                        store=store, actor="owner")
    assert src["known"] is True and src["body"] == MANUAL_M
    diff = await prp.diff_revisions(src["revision_id"],
                                    (await _revision_of(
                                        store, FACTORY_A, scope="global",
                                        origin="factory")).revision_id,
                                    cache=cache, store=store, actor="owner")
    assert diff["known"] is True and diff["diff"]
    assert _baseline_events(store) == []
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()


@pytest.mark.asyncio
async def test_baseline_of_retired_revision_is_shown_honestly(edition, store):
    """Смена схемы/релиза не уничтожает baseline, несовместимость видна."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    manual = await _manual_global(cache, store)
    await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                              cache=cache, store=store)
    store.revisions[manual.revision_id].schema_compat = "schema-v9"

    state = await _baseline(store, cache)

    assert state["baseline"]["revision_id"] == manual.revision_id
    assert state["baseline"]["available"] is True
    assert state["baseline"]["compatible"] is False
    assert state["baseline"]["schema_compat"] == "schema-v9"
    restore = await prp.restore_baseline(BLOCK, actor="owner", cache=cache,
                                        store=store)
    assert restore["applied"] is False
    assert restore["reason"] == "schema_incompatible"
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()


# ═══════════════════════════════════════════════════════════════════════════
# 7. Восстановление базовой и возврат исходной из кода
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_restore_baseline_is_explicit_activation(edition, store):
    """§2.4 п.6: «Восстановить базовую» = явная активация с своим видом."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    manual = await _manual_global(cache, store)
    factory = await _revision_of(store, FACTORY_A, scope="global",
                                 origin="factory")
    await prp.assign_baseline(BLOCK, factory.revision_id, actor="owner",
                              cache=cache, store=store)

    res = await prp.restore_baseline(BLOCK, actor="owner", cache=cache,
                                     store=store)

    assert res["applied"] is True
    assert res["activation_kind"] == "baseline_restore"
    assert res["restored_revision_id"] == factory.revision_id
    assert cache.values[PG_KEY].encode() == FACTORY_A.encode()
    state = await _baseline(store, cache)
    assert state["baseline"]["revision_id"] == factory.revision_id
    assert state["baseline"]["is_active"] is True
    # Без назначенной базовой восстанавливать нечего — честный отказ.
    await prp.clear_baseline(BLOCK, actor="owner", cache=cache, store=store)
    empty = await prp.restore_baseline(BLOCK, actor="owner", cache=cache,
                                      store=store)
    assert empty["applied"] is False and empty["reason"] == "baseline_absent"
    assert cache.values[PG_KEY].encode() == FACTORY_A.encode()


@pytest.mark.asyncio
async def test_restore_shipped_factory_requires_confirmation(edition, store):
    """§2.4 п.7: подтверждение обязательно, baseline не снимается."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    manual = await _manual_global(cache, store)
    await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                              cache=cache, store=store)

    refused = await prp.restore_shipped_factory(BLOCK, actor="owner",
                                               cache=cache, store=store)
    assert refused["applied"] is False
    assert refused["reason"] == "confirmation_required"
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()

    res = await prp.restore_shipped_factory(BLOCK, actor="owner", cache=cache,
                                            store=store, confirm=True)
    assert res["applied"] is True
    assert res["activation_kind"] == "factory_restore"
    assert cache.values[PG_KEY].encode() == FACTORY_A.encode()
    assert res["baseline_cleared"] is False
    state = await _baseline(store, cache)
    assert state["baseline"]["revision_id"] == manual.revision_id


@pytest.mark.asyncio
async def test_restore_shipped_factory_refuses_broken_seal(edition, store):
    """Сломанная печать: заводской текст не подтверждён — значение прежнее."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    await _manual_global(cache, store)
    edition.break_seal(BLOCK, "текст, не совпадающий с печатью реестра")

    res = await prp.restore_shipped_factory(BLOCK, actor="owner", cache=cache,
                                            store=store, confirm=True)

    assert res["applied"] is False and res["reason"] == "factory_unverifiable"
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()


# ═══════════════════════════════════════════════════════════════════════════
# 8. Копирование чатового текста как новой глобальной версии
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_copy_chat_revision_creates_new_global_revision(edition, store):
    """§2.4 п.8: новая ревизия global-scope, без перепривязки чужого id."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    source = await _chat_text(store, cache, CHAT_A, CHAT_A_TEXT)
    events_before = len(store.activations)

    res = await prp.copy_revision_to_global(BLOCK, source.revision_id,
                                            actor="owner", cache=cache,
                                            store=store)

    assert res["applied"] is True and res["created"] is True
    assert res["scope"] == "global" and res["chat_id"] is None
    assert res["origin"] == "restored"
    assert res["copy_reason"] == f"copied_from_chat:{source.revision_id}"
    copied = store.revisions[res["revision_id"]]
    assert copied.body.encode() == CHAT_A_TEXT.encode()
    assert copied.revision_id != source.revision_id
    assert copied.scope == "global" and copied.chat_id is None
    # Источник не перепривязан и не изменён.
    source_after = await store.get_revision(source.revision_id)
    assert source_after.scope == "chat" and source_after.chat_id == CHAT_A
    # Копирование — не активация: активный текст и указатель не двигаются.
    assert cache.values[PG_KEY].encode() == FACTORY_A.encode()
    assert len(store.activations) == events_before
    # Повтор идемпотентен: та же ревизия, без дубля.
    again = await prp.copy_revision_to_global(BLOCK, source.revision_id,
                                              actor="owner", cache=cache,
                                              store=store)
    assert again["created"] is False
    assert again["revision_id"] == res["revision_id"]


@pytest.mark.asyncio
async def test_copy_refuses_non_chat_source(edition, store):
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    factory = await _revision_of(store, FACTORY_A, scope="global")

    res = await prp.copy_revision_to_global(BLOCK, factory.revision_id,
                                            actor="owner", cache=cache,
                                            store=store)

    assert res["applied"] is False and res["reason"] == "copy_source_not_chat"
    copied = [r for r in store.revisions.values() if r.origin == "restored"]
    assert copied == []


# ═══════════════════════════════════════════════════════════════════════════
# 9. Миграция ничего не назначает
# ═══════════════════════════════════════════════════════════════════════════

def test_journal_ddl_gains_no_baseline_storage():
    """§2.1: baseline — событие; новой таблицы/колонки в DDL нет."""
    ddl = "\n".join(prp.JOURNAL_DDL).lower()
    assert ddl.count("create table if not exists") == 2
    assert "baseline" not in ddl
    baseline_sql = prp._BASELINE_SQL.lower()
    assert "select" in baseline_sql and "from prompt_activations" in baseline_sql
    for forbidden in ("insert into", "update ", "delete from", "create table",
                      "alter table"):
        assert forbidden not in baseline_sql


@pytest.mark.asyncio
async def test_release_migration_assigns_no_baseline(edition, store):
    """§2.1/§4: первый прогон политики не назначает baseline никому."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    pr.set_release_policy_active(False)

    release = await prp.apply_release(cache, release_id="evol-016-cutover",
                                      store=store)

    assert release["applied"] is True
    assert _baseline_events(store) == []
    kinds = {a.kind for a in store.activations}
    assert kinds <= {"legacy_import", "deploy_activate", "manual_edit",
                     "integrity_reject"}
    # Действующее значение не изменилось относительно заводского текста.
    assert cache.values[PG_KEY].encode() == FACTORY_A.encode()
    # Повторный прогон (рестарт) тоже не назначает baseline.
    await prp.apply_release(cache, release_id="restart", store=store)
    assert _baseline_events(store) == []
    for spec in (b for b in pr.all_blocks() if b.pg_key):
        assert await store.read_baseline_event(spec.block_id, "global",
                                               None) is None


# ═══════════════════════════════════════════════════════════════════════════
# 10. Дисциплина записи: один лок, одна транзакция, откат целиком
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_baseline_writes_under_same_lock_and_single_transaction(
        edition, store):
    """§2.3: лок релиза → транзакция → событие (и ничего вне транзакции)."""
    recorder = _RecordingJournal()
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, recorder)
    manual = await _manual_global(cache, recorder)
    recorder.trace.clear()

    await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                              cache=cache, store=recorder)

    assert recorder.trace[:3] == ["lock", "tx_enter",
                                  "insert:baseline_assign:recorded"]
    assert recorder.trace[-1] == "tx_exit"
    recorder.trace.clear()
    await prp.clear_baseline(BLOCK, actor="owner", cache=cache, store=recorder)
    assert recorder.trace[:3] == ["lock", "tx_enter",
                                  "insert:baseline_clear:recorded"]


@pytest.mark.asyncio
async def test_assign_failure_leaves_no_partial_state(edition, store):
    """Сбой посреди записи: ни события, ни изменения текста/указателя."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    manual = await _manual_global(cache, store)
    before_applied = await store.read_applied(BLOCK, "global", None)
    store.fail_at = "insert_activation"

    with pytest.raises(prp.PromptJournalError):
        await prp.assign_baseline(BLOCK, manual.revision_id, actor="owner",
                                  cache=cache, store=store)

    store.fail_at = None
    assert _baseline_events(store) == []
    after_applied = await store.read_applied(BLOCK, "global", None)
    assert after_applied.revision_id == before_applied.revision_id
    assert cache.values[PG_KEY].encode() == MANUAL_M.encode()


@pytest.mark.asyncio
async def test_read_baseline_reports_unavailable_journal(edition, monkeypatch):
    """Нет журнала — честный 503-путь, а не «baseline отсутствует»."""
    monkeypatch.setattr(prp, "default_journal", lambda cache: None)
    with pytest.raises(prp.JournalUnavailable):
        await prp.read_baseline(BLOCK, cache=None, actor="owner")
    with pytest.raises(prp.JournalUnavailable):
        await prp.assign_baseline(BLOCK, "rev:whatever", actor="owner",
                                  cache=None)


# ═══════════════════════════════════════════════════════════════════════════
# HTTP-слой: те же действия на существующих маршрутах промптов
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def env(monkeypatch):
    """Приложение с реальным RBAC-слоем и подставленным журналом (§5.2)."""
    patch = FactoryEdition(monkeypatch)
    patch.set_edition(BLOCK, "narrator-a", FACTORY_A)
    conn, cache, app = _build(monkeypatch)
    journal = prp.MemoryPromptJournal()
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache_: journal)
    monkeypatch.setattr(prp, "default_journal", lambda cache_: journal)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, conn=conn, cache=cache,
                              journal=journal, edition=patch)
    pr.set_release_policy_active(False)
    pr.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    pr.reset_cache()


def _headers(chat_id: int | None = None, user_id: int = ADMIN_ID):
    headers = _hdr(user_id)
    if chat_id is not None:
        headers["X-Chat-Id"] = str(chat_id)
    return headers


def _seed_revision(env, text: str, *, scope="global", chat_id=None,
                   origin="manual"):
    revision_id = pr.revision_id_for(BLOCK, scope, chat_id, origin,
                                     pr.sha12(text))
    env.journal.revisions[revision_id] = prp.RevisionRow(
        revision_id=revision_id, block_id=BLOCK, scope=scope, origin=origin,
        content_sha12=pr.sha12(text), body=text, pg_key=PG_KEY,
        chat_id=chat_id, created_at="2026-11-04T10:00:00+00:00")
    return env.journal.revisions[revision_id]


def test_api_baseline_assign_read_clear(env):
    """GET/POST/DELETE /api/prompts/{key}/baseline на существующих правах."""
    revision = _seed_revision(env, FACTORY_A, origin="factory")
    events_before = len(env.journal.activations)

    assign = env.client.post(f"/api/prompts/{PG_KEY}/baseline",
                             json={"revision_id": revision.revision_id},
                             headers=_headers())
    assert assign.status_code == 200, assign.text
    body = assign.json()
    assert body["applied"] is True and body["outcome"] == "recorded"
    assert body["active_text_changed"] is False
    assert body["reason_text"]
    assert body["source"] == "owner"
    assert body["baseline"]["revision_id"] == revision.revision_id
    assert body["capabilities"]["can_clear_baseline"] is True
    assert len(env.journal.activations) == events_before + 1

    read = env.client.get(f"/api/prompts/{PG_KEY}/baseline",
                          headers=_headers())
    assert read.status_code == 200, read.text
    state = read.json()
    assert state["source"] == "owner"
    assert state["baseline"]["revision_id"] == revision.revision_id
    assert state["capabilities"]["can_assign_baseline"] is True
    assert state["capabilities"]["can_clear_baseline"] is True
    assert "body" not in state["baseline"]      # тексты не отдаются списком

    cleared = env.client.delete(f"/api/prompts/{PG_KEY}/baseline",
                                headers=_headers())
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["applied"] is True
    after = env.client.get(f"/api/prompts/{PG_KEY}/baseline",
                           headers=_headers()).json()
    assert after["baseline"] is None and after["source"] == "factory"


def test_api_baseline_foreign_chat_is_refused(env):
    """Чужой чат: baseline другого чата не назначается и не виден."""
    foreign = _seed_revision(env, CHAT_B_TEXT, scope="chat", chat_id=CHAT_B)

    res = env.client.post(f"/api/prompts/{PG_KEY}/baseline",
                          json={"revision_id": foreign.revision_id},
                          headers=_headers(chat_id=CHAT_A))
    assert res.status_code == 200, res.text
    assert res.json()["applied"] is False
    assert res.json()["reason"] == "revision_foreign_scope"
    assert res.json()["reason_text"]
    assert [a for a in env.journal.activations
            if a.kind.startswith("baseline")] == []


def test_api_factory_restore_requires_confirmation(env):
    """«Вернуть исходную из кода» без confirm → 422, текст не изменён."""
    _seed_revision(env, FACTORY_A, origin="factory")
    refused = env.client.post(f"/api/prompts/{PG_KEY}/factory/restore",
                              json={}, headers=_headers())
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "confirmation_required"

    ok = env.client.post(f"/api/prompts/{PG_KEY}/factory/restore",
                         json={"confirm": True}, headers=_headers())
    assert ok.status_code == 200, ok.text
    assert ok.json()["activation_kind"] == "factory_restore"


def test_api_copy_to_global_from_chat(env):
    """Копирование чатовой ревизии в global доступно и не активирует."""
    source = _seed_revision(env, CHAT_A_TEXT, scope="chat", chat_id=CHAT_A)

    res = env.client.post(
        f"/api/prompts/revisions/{source.revision_id}/copy-to-global",
        json={}, headers=_headers(chat_id=CHAT_A))

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["revision_id"] != source.revision_id
    assert body["scope"] == "global"
    assert body["copy_reason"] == f"copied_from_chat:{source.revision_id}"
    assert env.journal.revisions[body["revision_id"]].body == CHAT_A_TEXT


def test_api_versions_exposes_baseline_and_capabilities(env):
    """UI-слой получает baseline в ТОМ ЖЕ ответе истории (§6.1)."""
    revision = _seed_revision(env, FACTORY_A, origin="factory")
    env.client.post(f"/api/prompts/{PG_KEY}/baseline",
                    json={"revision_id": revision.revision_id},
                    headers=_headers())

    res = env.client.get(f"/api/prompts/{PG_KEY}/versions", headers=_headers())

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["baseline"]["source"] == "owner"
    assert body["baseline"]["baseline"]["revision_id"] == revision.revision_id
    assert body["capabilities"]["can_assign_baseline"] is True
    assert body["capabilities"]["can_restore_baseline"] is True
    assert body["capabilities"]["can_restore_factory"] is True
