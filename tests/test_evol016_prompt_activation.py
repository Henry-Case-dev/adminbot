"""EVOL-016 — автомат активации заводских ревизий (таблица переходов).

Матрица контракта ``plans/features/evol/arch/contracts.md`` §1.9 и
``plans/current_task.md`` §5 (EVOL-018, тесты обязательны):

  1. factory A → manual M → factory B (новая метка) — активен B, M в истории
     (origin=manual);
  2. рестарт без новой метки после M — активен M, новых ревизий нет;
  3. manual/restore A после B — активен A, рестарт не возвращает B;
  4. factory C (ещё одна новая метка) — активен C, A и M на месте;
  5. рестарт после C — C не сбрасывается и не дублируется;
  6. неизвестный legacy-текст — снимок origin=legacy (время = время импорта),
     затем cutover включает заводской; повторный старт no-op;
  7. два параллельных apply_release — одна активация, второй skipped_same;
  8. исключение на втором ключе пакета — ни один ключ пакета не изменён;
  9. global и два chat_id — override чата 1 не виден чату 2; новая метка
     снимает старые override обоих чатов в историю; override после метки
     рестарт не снимает;
 10. смена заводского текста без смены метки — план integrity_reject,
     запись значения не выполняется;
 11. снятый/переименованный ключ — старые ревизии читаются, retired=true;
 12. schema_compat вне «совместимо всё» — не активируется, просмотр доступен;
 13. резолв после cutover читает активный PG-текст, а не константу;
 14. дрейф журнала и bot_settings — ERROR activation_drift, без угадывания.

Без Telegram, без LLM, без реального PG: кэш — фейк с контрактом
``get``/``set``, журнал — ``MemoryPromptJournal`` (откат пакета, инъекция
сбоев, лок применения).

TEST-LIFECYCLE: CONTRACT owner=EVOL-016 (контракт §1.9)
"""
from __future__ import annotations

import asyncio
import datetime

import pytest

from services import prompt_factory as pf
from services import prompt_registry as pr
from services import prompt_release_policy as prp

BLOCK = "summary.base.narrator"
PG_KEY = "prompts.summary_narrator_system_prompt"

FACTORY_A = "ЗАВОДСКАЯ A: рассказчик саммари (байт-эталон теста).\n"
FACTORY_B = ("ЗАВОДСКАЯ B: рассказчик саммари, новая метка релиза — правка "
             "архитектуры.\n")
FACTORY_C = ("ЗАВОДСКАЯ C: рассказчик саммари, третья метка — снова новая "
             "заводская публикация.\n")
MANUAL_M = "РУЧНАЯ ПРАВКА M: владелец отредактировал рассказчика в админке.\n"
MANUAL_R = ("РУЧНОЕ ВОССТАНОВЛЕНИЕ R: владелец вернул прежнюю редакцию "
            "из истории.\n")
UNKNOWN_LEGACY = ("НЕИЗВЕСТНЫЙ СТАРЫЙ ТЕКСТ прод-значения (не равен ни "
                  "заводскому, ни одному из слепков; длина не зашита — "
                  "нормализация факта, не канона). " + "x" * 300) + "\n"


class FakeCache:
    """Контракт ConfigCache (sync get / async set) + optimistic-токен."""

    def __init__(self, values=None):
        self.pg_available = True
        self.values = dict(values or {})
        self.set_calls: list[tuple[str, object, str]] = []
        self._updated_at = "2026-10-29T10:00:00+00:00"

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))
        self.values[key] = value

    def get_updated_at(self, key):
        return self._updated_at


class FactoryEdition:
    """Патч кодовой заводской редакции блока: метка + печать + текст."""

    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self._texts: dict[str, str] = {}
        self._seals = dict(pr.FACTORY_REVISION_SEALS)
        self._labels = dict(pr.FACTORY_REVISION_LABELS)
        monkeypatch.setattr(pr, "factory_text", self._factory_text)
        monkeypatch.setattr(pr, "FACTORY_REVISION_SEALS", self._seals)
        monkeypatch.setattr(pr, "FACTORY_REVISION_LABELS", self._labels)

    def _factory_text(self, block_id: str) -> str:
        if block_id in self._texts:
            return self._texts[block_id]
        return _real_factory_text(block_id)

    def set_edition(self, block_id: str, label: str, text: str) -> None:
        self._texts[block_id] = text
        self._labels[block_id] = label
        self._seals[block_id] = (label, pr.sha12(text))

    def break_seal(self, block_id: str, text: str) -> None:
        """Сменить текст, оставив прежнюю печать (integrity-кейс)."""
        self._texts[block_id] = text


_real_factory_text = pr.factory_text


@pytest.fixture()
def edition(monkeypatch):
    """Заводская редакция A для тестового блока (+ сброс глобального состояния)."""
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


def _rows_by_outcome(result):
    return {(r.block_id, r.scope, r.chat_id): r for r in result["results"]}


def _revisions_of(store, origin=None):
    rows = [r for r in store.revisions.values() if r.block_id == BLOCK]
    if origin:
        rows = [r for r in rows if r.origin == origin]
    return rows


def _activation_rows(store, kind=None):
    rows = [a for a in store.activations if a.block_id == BLOCK]
    if kind:
        rows = [a for a in rows if a.kind == kind]
    return rows


# ── 1–5. Таблица переходов владельца ────────────────────────────────────────

@pytest.mark.asyncio
async def test_transition_table_owner_semantics(edition, store):
    cache = FakeCache({PG_KEY: FACTORY_A})
    # factory A: cutover активирует заводскую
    r1 = await _cutover(cache, store)
    assert r1["applied"] and cache.values[PG_KEY] == FACTORY_A
    assert pr.release_policy_active() and pf.history_frozen()
    # рестарт: no-op
    before = len(store.activations)
    r2 = await _cutover(cache, store, release_id="restart-1")
    assert len(store.activations) == before
    assert cache.values[PG_KEY] == FACTORY_A

    # manual M: правка владельца становится активной неизменяемой ревизией
    w = await prp.write_versioned_value(BLOCK, MANUAL_M, cache=cache,
                                        store=store, actor="owner")
    assert w["applied"] and cache.values[PG_KEY] == MANUAL_M
    assert w["factory_revision_applied"] == pr.sealed_factory_revision(BLOCK)
    # рестарт после M: правка не сбрасывается
    await _cutover(cache, store, release_id="restart-2")
    assert cache.values[PG_KEY] == MANUAL_M

    # factory B (новая метка): автоматическая активация ПОВЕРХ ручной правки
    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    r3 = await _cutover(cache, store, release_id="deploy-b")
    rows = _rows_by_outcome(r3)
    assert rows[(BLOCK, "global", None)].outcome == "applied"
    assert cache.values[PG_KEY] == FACTORY_B
    # M сохранён в истории как ручная ревизия
    manual = [r for r in _revisions_of(store, origin="manual")
              if r.content_sha12 == pr.sha12(MANUAL_M)]
    assert len(manual) == 1

    # рестарт после B: B остаётся, дублей нет
    before = len(store.activations)
    await _cutover(cache, store, release_id="restart-3")
    assert len(store.activations) == before
    assert cache.values[PG_KEY] == FACTORY_B

    # manual/restore A после B: активен A, рестарт НЕ возвращает B
    restored_a = await _activate_text_like_restore(cache, store, FACTORY_A)
    assert restored_a["applied"] and cache.values[PG_KEY] == FACTORY_A
    await _cutover(cache, store, release_id="restart-4")
    assert cache.values[PG_KEY] == FACTORY_A

    # factory C: снова автоматическая активация, A и M остаются в истории
    edition.set_edition(BLOCK, "narrator-c", FACTORY_C)
    r4 = await _cutover(cache, store, release_id="deploy-c")
    assert cache.values[PG_KEY] == FACTORY_C
    shas = {r.content_sha12 for r in _revisions_of(store)}
    assert pr.sha12(FACTORY_A) in shas and pr.sha12(MANUAL_M) in shas \
        and pr.sha12(FACTORY_B) in shas
    # рестарт после C: C не сбрасывается и не дублируется
    before = len(store.activations)
    await _cutover(cache, store, release_id="restart-5")
    assert len(store.activations) == before
    assert cache.values[PG_KEY] == FACTORY_C


async def _activate_text_like_restore(cache, store, text):
    """Владелец вернул прежний текст (запись активного текста через журнал)."""
    return await prp.write_versioned_value(
        BLOCK, text, cache=cache, store=store, actor="owner",
        reason="manual_restore", kind="manual_rollback")


@pytest.mark.asyncio
async def test_manual_restore_via_activate_revision(edition, store):
    """Откат/вперёд через activate_revision: история не удаляется."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    await prp.write_versioned_value(BLOCK, MANUAL_M, cache=cache, store=store,
                                    actor="owner")
    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    await _cutover(cache, store, release_id="deploy-b")
    manual = [r for r in _revisions_of(store, origin="manual")
              if r.content_sha12 == pr.sha12(MANUAL_M)][0]
    res = await prp.activate_revision(BLOCK, manual.revision_id, cache=cache,
                                      store=store, actor="owner")
    assert res["applied"] and cache.values[PG_KEY] == MANUAL_M
    assert res["activation_kind"] == "manual_rollback"
    # рестарт не возвращает B: factory_revision_applied сохранён
    await _cutover(cache, store, release_id="restart-after-rollback")
    assert cache.values[PG_KEY] == MANUAL_M
    # вперед: возврат к заводской B — тоже через журнал
    factory_b = [r for r in _revisions_of(store, origin="factory")
                 if r.content_sha12 == pr.sha12(FACTORY_B)][0]
    fwd = await prp.activate_revision(BLOCK, factory_b.revision_id,
                                      cache=cache, store=store, actor="owner")
    assert fwd["applied"] and fwd["activation_kind"] == "manual_forward"
    assert cache.values[PG_KEY] == FACTORY_B


# ── 6. Неизвестный legacy-текст: снимок + cutover, повтор no-op ─────────────

@pytest.mark.asyncio
async def test_unknown_legacy_text_snapshot_then_cutover(edition, store):
    cache = FakeCache({PG_KEY: UNKNOWN_LEGACY})
    result = await _cutover(cache, store)
    legacy = [r for r in _revisions_of(store, origin="legacy")
              if r.content_sha12 == pr.sha12(UNKNOWN_LEGACY)]
    assert len(legacy) == 1
    # время снимка = время импорта (UTC, сейчас), не выдуманная дата правки
    assert legacy[0].created_at
    stamp = datetime.datetime.fromisoformat(legacy[0].created_at)
    now = datetime.datetime.now(datetime.timezone.utc)
    assert abs((now - stamp).total_seconds()) < 120
    assert legacy[0].actor == "" and legacy[0].reason == "legacy_import"
    # cutover включил заводскую; неизвестный текст остался в истории
    assert cache.values[PG_KEY] == FACTORY_A
    rows = _rows_by_outcome(result)
    assert rows[(BLOCK, "global", None)].outcome == "applied"
    # повторный старт: no-op (ни строки, ни записи)
    before = (len(store.activations), len(store.revisions))
    await _cutover(cache, store, release_id="restart")
    assert (len(store.activations), len(store.revisions)) == before
    assert cache.values[PG_KEY] == FACTORY_A


@pytest.mark.asyncio
async def test_empty_key_skipped_empty_then_activated(edition, store):
    """Пустой ключ: skipped_empty (автор не выдумывается), затем активация."""
    cache = FakeCache({})
    result = await _cutover(cache, store)
    empty = [a for a in _activation_rows(store, kind="legacy_import")
             if a.outcome == "skipped_empty"]
    assert len(empty) == 1
    rows = _rows_by_outcome(result)
    assert rows[(BLOCK, "global", None)].outcome == "applied"
    assert cache.values[PG_KEY] == FACTORY_A


# ── 7. Параллельные воркеры ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parallel_apply_single_activation(edition, store):
    cache = FakeCache({PG_KEY: UNKNOWN_LEGACY})
    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    results = await asyncio.gather(
        prp.apply_release(cache, release_id="worker-1", store=store,
                          blocks=[BLOCK]),
        prp.apply_release(cache, release_id="worker-2", store=store,
                          blocks=[BLOCK]),
    )
    applied = sum(1 for r in results if r.get("applied"))
    assert applied == 2          # оба вызова завершились
    deploys = [a for a in _activation_rows(store, kind="deploy_activate")
               if a.outcome == "applied"]
    assert len(deploys) == 1     # активация одна
    assert cache.values[PG_KEY] == FACTORY_B
    legacy = [r for r in _revisions_of(store, origin="legacy")]
    assert len(legacy) == 1      # снимок не задвоился


# ── 8. Крэш mid-apply: пакет откатывается целиком ───────────────────────────

@pytest.mark.asyncio
async def test_crash_mid_apply_no_partial_state(edition, store):
    other = "search.base.system"
    other_key = "prompts.search_system_prompt"
    edition.set_edition(other, "search-a", "ПОИСК A: байт-эталон теста.\n")
    cache = FakeCache({PG_KEY: UNKNOWN_LEGACY, other_key: "старое значение\n"})
    # Сбой на вставке активации → исключение → откат всего пакета.
    store.fail_at = "insert_activation"
    with pytest.raises(prp.PromptJournalError):
        await prp.apply_release(cache, release_id="broken", store=store,
                                blocks=[BLOCK, other])
    store.fail_at = None
    # Ни один ключ пакета не изменён, журнал пуст (транзакция откатилась).
    assert cache.values[PG_KEY] == UNKNOWN_LEGACY
    assert cache.values[other_key] == "старое значение\n"
    assert not store.revisions and not store.activations
    # Повтор (после устранения сбоя) применяет пакет целиком.
    result = await prp.apply_release(cache, release_id="retry", store=store,
                                     blocks=[BLOCK, other])
    assert result["applied"]
    assert cache.values[PG_KEY] == FACTORY_A
    assert cache.values[other_key] == "ПОИСК A: байт-эталон теста.\n"


# ── 9. Scope: global + два чата ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scope_global_and_two_chats(edition, store):
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    # override'ы обоих чатов поверх старой метки
    store.chat_overrides[111] = {PG_KEY: "ОБЕТКАЙД ЧАТА 1 (старый)\n"}
    store.chat_overrides[222] = {PG_KEY: "ОВЕРРАЙД ЧАТА 2 (старый)\n"}

    # chat 1 не видит override чата 2
    assert await prp._read_override_value(store, 111, PG_KEY) == \
        "ОБЕТКАЙД ЧАТА 1 (старый)\n"
    assert await prp._read_override_value(store, 111, PG_KEY) != \
        store.chat_overrides[222][PG_KEY]

    # новая метка снимает старые override ОБОИХ чатов в историю
    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    result = await prp.apply_release(cache, release_id="deploy-b", store=store,
                                     blocks=[BLOCK])
    chat_rows = [r for r in result["results"] if r.scope == "chat"]
    assert {r.chat_id for r in chat_rows} == {111, 222}
    assert all(r.outcome == "applied" for r in chat_rows)
    assert PG_KEY not in store.chat_overrides[111]
    assert PG_KEY not in store.chat_overrides[222]
    # тексты override'ов сохранены как ревизии (legacy — первый импорт)
    chat_revs = {r.content_sha12 for r in store.revisions.values()
                 if r.scope == "chat"}
    assert pr.sha12("ОБЕТКАЙД ЧАТА 1 (старый)\n") in chat_revs
    assert pr.sha12("ОВЕРРАЙД ЧАТА 2 (старый)\n") in chat_revs
    # notify по обоим чатам (инвалидация кэша после commit)
    assert set(store.notified_chats) == {111, 222}

    # override, записанный ПОСЛЕ применения метки, рестарт не снимает
    await prp.write_versioned_value(BLOCK, "НОВЫЙ ЧАТОВЫЙ ТЕКСТ\n",
                                    cache=cache, store=store, scope="chat",
                                    chat_id=111, actor="owner")
    before = len(store.activations)
    await prp.apply_release(cache, release_id="restart", store=store,
                            blocks=[BLOCK])
    assert len(store.activations) == before
    assert store.chat_overrides[111][PG_KEY] == "НОВЫЙ ЧАТОВЫЙ ТЕКСТ\n"

    # следующая новая метка снимает и его (в историю)
    edition.set_edition(BLOCK, "narrator-c", FACTORY_C)
    await prp.apply_release(cache, release_id="deploy-c", store=store,
                            blocks=[BLOCK])
    assert PG_KEY not in store.chat_overrides[111]
    chat_revs = {r.content_sha12 for r in store.revisions.values()
                 if r.scope == "chat"}
    assert pr.sha12("НОВЫЙ ЧАТОВЫЙ ТЕКСТ\n") in chat_revs


# ── 10. Целостность: текст сменён без метки → fail-closed ──────────────────

@pytest.mark.asyncio
async def test_text_change_without_label_bump_rejected(edition, store):
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    set_calls_before = len(cache.set_calls)
    # текст сменился, метка/печать прежние
    edition.break_seal(BLOCK, FACTORY_A + "ТИХАЯ ПРАВКА БЕЗ БАМПА\n")
    result = await prp.apply_release(cache, release_id="deploy", store=store,
                                     blocks=[BLOCK])
    assert result["applied"] is False
    assert result["reason"] == "integrity_label_unchanged"
    assert result["integrity"][BLOCK] == "seal_text_changed"
    # запись значения не выполнялась, активный текст остался прежним
    assert len(cache.set_calls) == set_calls_before
    assert cache.values[PG_KEY] == FACTORY_A
    # план (чистая функция) тоже integrity_reject
    plan = pr.activation_plan(
        code_label="narrator-a", sealed_sha=pr.sha12(FACTORY_A),
        text_sha12=pr.sha12(FACTORY_A + "ТИХАЯ ПРАВКА БЕЗ БАМПА\n"),
        applied_factory_revision=pr.sealed_factory_revision(BLOCK),
        has_import=True)
    assert plan.action == pr.PLAN_INTEGRITY_REJECT
    assert plan.reason == "integrity_label_unchanged"


@pytest.mark.asyncio
async def test_label_bump_without_seal_rejected(edition, store):
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    # метка бампнута, печать не обновлена
    edition._seals[BLOCK] = ("narrator-broken", pr.sha12(FACTORY_A))
    result = await prp.apply_release(cache, release_id="deploy", store=store,
                                     blocks=[BLOCK])
    assert result["reason"] == "integrity_label_unchanged"
    assert cache.values[PG_KEY] == FACTORY_A


# ── 11. Снятый/переименованный ключ ────────────────────────────────────────

@pytest.mark.asyncio
async def test_removed_key_revisions_retired(edition, store, monkeypatch):
    cache = FakeCache({PG_KEY: UNKNOWN_LEGACY})
    await _cutover(cache, store)
    # блок снят с регистрации (переименован)
    real_all_blocks = pr.all_blocks

    def reduced():
        return tuple(b for b in real_all_blocks() if b.block_id != BLOCK)

    monkeypatch.setattr(pr, "all_blocks", reduced)
    result = await prp.apply_release(cache, release_id="deploy", store=store,
                                     blocks=[])
    assert BLOCK in result["retired_blocks"]
    rows = await store.list_revisions(BLOCK)  # старые ревизии читаются
    assert rows
    assert all(r.retired for r in rows)
    monkeypatch.setattr(pr, "all_blocks", real_all_blocks)
    # блок вернулся в реестр: следующее применение снимает пометку retired
    result2 = await prp.apply_release(cache, release_id="deploy-back",
                                      store=store, blocks=[])
    assert BLOCK not in result2["retired_blocks"]
    view = {row["block_id"]: row for row in pr.registry_view()}
    assert view[BLOCK]["retired"] is False


# ── 12. schema_compat: несовместимая ревизия не активируется ───────────────

@pytest.mark.asyncio
async def test_schema_incompatible_revision_not_activatable(edition, store):
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    old = prp.RevisionRow(
        revision_id=pr.revision_id_for(BLOCK, "global", None, "manual",
                                       pr.sha12("СОВСЕМ СТАРАЯ ВЕРСИЯ\n")),
        block_id=BLOCK, scope="global", origin="manual",
        content_sha12=pr.sha12("СОВСЕМ СТАРАЯ ВЕРСИЯ\n"),
        body="СОВСЕМ СТАРАЯ ВЕРСИЯ\n", schema_compat="pre-evol-schema-v1")
    await store.insert_revision(old)
    res = await prp.activate_revision(BLOCK, old.revision_id, cache=cache,
                                      store=store, actor="owner")
    assert res["applied"] is False
    assert res["reason"] == "schema_incompatible"
    assert cache.values[PG_KEY] == FACTORY_A      # активный не менялся
    # просмотр доступен (EVOL-017: читать/сравнивать можно)
    src = await prp.get_revision_source(old.revision_id, store=store)
    assert src["known"] and src["body"] == "СОВСЕМ СТАРАЯ ВЕРСИЯ\n"
    view = await prp.list_versions(BLOCK, store=store)
    row = [r for r in view["revisions"]
           if r["revision_id"] == old.revision_id][0]
    assert row["schema_compat"] == "pre-evol-schema-v1"


# ── 13. Пайплайн читает активный PG-текст после cutover ────────────────────

@pytest.mark.asyncio
async def test_resolver_uses_active_pg_text_after_cutover(edition, store,
                                                          monkeypatch):
    cache = FakeCache({PG_KEY: UNKNOWN_LEGACY})
    spec = pr.block(BLOCK)
    # ДО политики: незаписанное значение удерживается (прежний шлагбаум)
    res_before = pr.resolve_speech_value(PG_KEY, UNKNOWN_LEGACY,
                                         source="global", cache=cache)
    assert res_before.withheld is True
    await _cutover(cache, store)
    # ПОСЛЕ cutover: активный PG-текст и есть эффективный слой
    custom = FACTORY_A + "\nПравка владельца после релиза.\n"
    cache.values[PG_KEY] = custom
    res = pr.resolve_speech_value(PG_KEY, custom, source="global", cache=cache)
    assert res.withheld is False
    assert res.text == custom
    assert "release_policy_persisted_effective" in res.diagnostics
    # известный токсичный слепок по-прежнему удерживается (не отправляется):
    # классификация по точным байтам остаётся гейтом и после cutover.
    import services.prompt_registry as pr_mod

    def fake_class(block_id, value):
        if value == "СИНТЕТИЧЕСКИЙ ТОКСИЧНЫЙ СЛЕПОК\n":
            return {"class": pr.WITHHELD_LEGACY_CLASS, "reason": "test"}
        return None

    monkeypatch.setattr(pr_mod, "withheld_classification", fake_class)
    res_tox = pr.resolve_speech_value(PG_KEY, "СИНТЕТИЧЕСКИЙ ТОКСИЧНЫЙ СЛЕПОК\n",
                                      source="global", cache=cache)
    assert res_tox.withheld is True
    assert res_tox.withheld_class == pr.WITHHELD_LEGACY_CLASS


@pytest.mark.asyncio
async def test_history_frozen_after_cutover(edition, store):
    """character.prompt_history заморожен после одноразового импорта (§1.2)."""
    cache = FakeCache({PG_KEY: FACTORY_A,
                       pr.PROVENANCE_DOC_KEY: {"v": 1, "items": {
                           BLOCK: [{"revision": "act:aaa", "sha256_12": "aaa",
                                    "chars": 3, "text": "СТАРАЯ РЕДАКЦИЯ\n",
                                    "source": "global",
                                    "kind": "owner_edit",
                                    "at": "2026-10-01T00:00:00+00:00",
                                    "by": "owner"}]}, "provenance": {}}})
    await _cutover(cache, store)
    assert pf.history_frozen()
    # items перенесены в журнал: owner_edit → manual, время из поля at
    imported = [r for r in _revisions_of(store, origin="manual")
                if r.content_sha12 == pr.sha12("СТАРАЯ РЕДАКЦИЯ\n")]
    assert len(imported) == 1
    assert imported[0].created_at.startswith("2026-10-01")
    assert imported[0].actor == "owner"     # автор из записи, не выдуман
    # новые правки больше не дописывают старый JSON-журнал
    await prp.write_versioned_value(BLOCK, MANUAL_M, cache=cache, store=store,
                                    actor="owner")
    doc = cache.values[pr.PROVENANCE_DOC_KEY]
    assert len(doc["items"].get(BLOCK, [])) == 1   # не вырос


# ── 14. Дрейф журнала и активного значения ─────────────────────────────────

@pytest.mark.asyncio
async def test_activation_drift_honest_no_guess(edition, store):
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    # «чужая» SQL-правка активного значения мимо журнала (авария/restore)
    drifted = "ЗНАЧЕНИЕ ПОСЛЕ АВАРИЙНОГО ВОССТАНОВЛЕНИЯ\n"
    cache.values[PG_KEY] = drifted
    edition.set_edition(BLOCK, "narrator-b", FACTORY_B)
    result = await prp.apply_release(cache, release_id="deploy-b", store=store,
                                     blocks=[BLOCK])
    rows = _rows_by_outcome(result)
    assert rows[(BLOCK, "global", None)].detail_code == "activation_drift"
    # источник истины — PG-значение: заводской текст заново НЕ включён
    assert cache.values[PG_KEY] == drifted
    # дрейф снят в ревизию (origin=legacy, reason=drift_recovery)
    snap = [r for r in _revisions_of(store, origin="legacy")
            if r.reason == "drift_recovery"]
    assert len(snap) == 1
    # следующая НОВАЯ метка снова включает заводской текст
    edition.set_edition(BLOCK, "narrator-c", FACTORY_C)
    await prp.apply_release(cache, release_id="deploy-c", store=store,
                            blocks=[BLOCK])
    assert cache.values[PG_KEY] == FACTORY_C


# ── Автомат: чистая функция (пограничные решения) ──────────────────────────

def test_activation_plan_pure_decisions():
    # рестарт с той же ревизией → no-op даже при активной ручной правке
    plan = pr.activation_plan(code_label="l1", sealed_sha=pr.sha12("T"),
                              text_sha12=pr.sha12("T"),
                              applied_factory_revision=pr.FACTORY_PREFIX
                              + pr.sha12("l1"), has_import=True)
    assert plan.action == pr.PLAN_NOOP
    # первая активация → cutover
    plan = pr.activation_plan(code_label="l1", sealed_sha=pr.sha12("T"),
                              text_sha12=pr.sha12("T"),
                              applied_factory_revision="", has_import=False)
    assert plan.action == pr.PLAN_LEGACY_CUTOVER
    # новая метка → activate
    plan = pr.activation_plan(code_label="l2", sealed_sha=pr.sha12("T"),
                              text_sha12=pr.sha12("T"),
                              applied_factory_revision=pr.FACTORY_PREFIX
                              + pr.sha12("l1"), has_import=True)
    assert plan.action == pr.PLAN_ACTIVATE
    # блок без метки (managed message) → no-op вне релиза
    plan = pr.activation_plan(code_label="", sealed_sha="", text_sha12="",
                              applied_factory_revision="", has_import=False)
    assert plan.action == pr.PLAN_NOOP


# ── Hook полномочий сервисного API (EVOL-017) ──────────────────────────────

@pytest.mark.asyncio
async def test_permission_hook_enforced(edition, store, monkeypatch):
    cache = FakeCache({PG_KEY: FACTORY_A})
    await _cutover(cache, store)
    await prp.write_versioned_value(BLOCK, MANUAL_M, cache=cache, store=store,
                                    actor="owner")
    factory_rev = [r for r in _revisions_of(store, origin="factory")
                   if r.content_sha12 == pr.sha12(FACTORY_A)][0]
    # без checker'а пустой actor → отказ
    with pytest.raises(prp.PromptPermissionError):
        await prp.activate_revision(BLOCK, factory_rev.revision_id,
                                    cache=cache, store=store, actor="   ")
    # установленный checker отклоняет чужого актора
    monkeypatch.setattr(
        prp, "_permission_checker",
        lambda actor, action, ctx: actor == "admin")
    with pytest.raises(prp.PromptPermissionError):
        await prp.activate_revision(BLOCK, factory_rev.revision_id,
                                    cache=cache, store=store,
                                    actor="intruder")
    assert cache.values[PG_KEY] == MANUAL_M      # отказы ничего не изменили
    ok = await prp.activate_revision(BLOCK, factory_rev.revision_id,
                                     cache=cache, store=store, actor="admin")
    assert ok["applied"]
    assert ok["activation_kind"] == "manual_rollback"
    assert cache.values[PG_KEY] == FACTORY_A
