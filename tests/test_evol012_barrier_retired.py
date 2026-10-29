"""EVOL-012 — барьер «кастом юзера — НЕ трогаем» снят (регрессия).

Решение владельца 29.10.2026 (``plans/current_task.md`` EVOL-012):
  * ручные изменения промптов НЕ обладают вечным иммунитетом — новая
    заводская ревизия релиза активируется независимо от правок;
  * рестарт без новой заводской ревизии активную правку не сбрасывает;
  * строковые сравнения с канонами запрещены как механизм миграции;
  * WARN «кастом юзера — НЕ трогаем» больше не возникает как барьер;
  * сохранённые слепки ``PREV_*``/лестницы остаются как байт-эталоны, но
    не участвуют в активации; ``rollback_prompt_canons`` /
    ``migrate_core_owner_patch`` при прямом вызове отказывают (без записи).

TEST-LIFECYCLE: REGRESSION owner=EVOL-012
"""
from __future__ import annotations

import logging

import pytest

from services import prompt_migrations as pm
from services import prompt_registry as pr
from services import prompt_release_policy as prp

BLOCK = "summary.base.narrator"
PG_KEY = "prompts.summary_narrator_system_prompt"

FACTORY_A = "ЗАВОДСКАЯ A (EVOL-012 регрессия): рассказчик саммари.\n"
FACTORY_B = "ЗАВОДСКАЯ B (EVOL-012 регрессия): новая метка релиза.\n"
CUSTOM = ("СТАРАЯ НЕИЗВЕСТНАЯ РЕДАКЦИЯ прод-значения (1788-подобный кейс: "
          "длина не зашита, байты не совпадают ни с каким каноном). "
          + "y" * 200) + "\n"
real_factory_text = pr.factory_text


class FakeCache:
    def __init__(self, values=None):
        self.pg_available = True
        self.values = dict(values or {})
        self.set_calls: list[tuple[str, object, str]] = []
        self.warnings_seen = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))
        self.values[key] = value


@pytest.fixture()
def edition(monkeypatch):
    state = {"text": FACTORY_A, "label": "narrator-a"}
    seals = dict(pr.FACTORY_REVISION_SEALS)
    labels = dict(pr.FACTORY_REVISION_LABELS)

    def _patched(block_id):
        if block_id == BLOCK:
            return state["text"]
        return real_factory_text(block_id)

    monkeypatch.setattr(pr, "factory_text", _patched)
    monkeypatch.setattr(pr, "FACTORY_REVISION_SEALS", seals)
    monkeypatch.setattr(pr, "FACTORY_REVISION_LABELS", labels)
    seals[BLOCK] = ("narrator-a", pr.sha12(FACTORY_A))
    labels[BLOCK] = "narrator-a"

    def set_edition(label, text):
        state["text"] = text
        state["label"] = label
        seals[BLOCK] = (label, pr.sha12(text))
        labels[BLOCK] = label

    yield set_edition
    pr.set_release_policy_active(False)
    pr.reset_cache()


@pytest.fixture()
def journal(monkeypatch):
    """Memory-стор как default_journal (юнит-контур без реального PG)."""
    from services import prompt_factory as _pf
    store = prp.MemoryPromptJournal()
    monkeypatch.setattr(prp, "default_journal", lambda cache=None: store)
    yield store
    pr.set_release_policy_active(False)
    _pf._HISTORY_FROZEN = False
    pr.reset_cache()


@pytest.mark.asyncio
async def test_custom_no_longer_blocks_new_factory_revision(edition, journal):
    """Приёмка EVOL-012: старый ручной/неизвестный промпт не блокирует релиз."""
    cache = FakeCache({PG_KEY: CUSTOM})
    report = await pm.migrate_prompt_canons(cache)
    # первый старт: снимок неизвестного текста + активация заводской A
    assert cache.values[PG_KEY] == FACTORY_A
    assert report.get(PG_KEY) in ("updated", "same", "applied",
                                  "skipped_same")
    # новая заводская ревизия в следующем релизе — активна без спроса
    edition("narrator-b", FACTORY_B)
    await pm.migrate_prompt_canons(cache)
    assert cache.values[PG_KEY] == FACTORY_B
    # прежняя редакция (неизвестный прод-текст) осталась в истории журнала
    legacy = [r for r in journal.revisions.values()
              if r.block_id == BLOCK and r.origin == "legacy"
              and r.content_sha12 == pr.sha12(CUSTOM)]
    assert len(legacy) == 1


@pytest.mark.asyncio
async def test_warning_barrier_gone(edition, journal, caplog):
    """WARN «кастом юзера — НЕ трогаем» больше не возникает как барьер."""
    cache = FakeCache({PG_KEY: CUSTOM})
    with caplog.at_level(logging.WARNING, logger="services.prompt_migrations"):
        await pm.migrate_prompt_canons(cache)
        edition("narrator-b", FACTORY_B)
        await pm.migrate_prompt_canons(cache)
    assert cache.values[PG_KEY] == FACTORY_B
    barrier_warnings = [r for r in caplog.records
                        if "НЕ трогаем" in r.getMessage()
                        or "кастом" in r.getMessage()]
    assert barrier_warnings == [], (
        "барьерная риторика не должна возвращаться в логи старта")


@pytest.mark.asyncio
async def test_restart_without_new_release_keeps_active(edition, journal):
    """Рестарт с той же заводской ревизией ничего не меняет (в т.ч. правку)."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await pm.migrate_prompt_canons(cache)
    # правка владельца после релиза
    w = await prp.write_versioned_value(BLOCK, "ПРАВКА ВЛАДЕЛЬЦА\n",
                                        cache=cache, store=journal,
                                        actor="owner")
    assert w["applied"]
    before = (len(journal.activations), len(journal.revisions),
              len(cache.set_calls))
    await pm.migrate_prompt_canons(cache)
    after = (len(journal.activations), len(journal.revisions),
             len(cache.set_calls))
    assert before == after          # ни строки, ни записи
    assert cache.values[PG_KEY] == "ПРАВКА ВЛАДЕЛЬЦА\n"


@pytest.mark.asyncio
async def test_no_string_comparison_against_canons(edition, journal):
    """Значение, совпавшее со слепком PREV_*, больше НЕ ведёт лестницей.

    Строковые канон-цепочки сняты: активацию решает метка+печать, а не
    равенство байт слепку. Прежняя ступень «PREV → канон» заменена
    журналом ревизий (слепок — просто историческое значение).
    """
    from services.summary_prompts import PREV_SUMMARY_NARRATOR_LEGFIX
    cache = FakeCache({PG_KEY: PREV_SUMMARY_NARRATOR_LEGFIX})
    await pm.migrate_prompt_canons(cache)
    # активна ЗАВОДСКАЯ ревизия по метке, а не «следующая ступень лестницы»
    assert cache.values[PG_KEY] == FACTORY_A
    legacy = [r for r in journal.revisions.values()
              if r.origin == "legacy"
              and r.content_sha12 == pr.sha12(PREV_SUMMARY_NARRATOR_LEGFIX)]
    assert len(legacy) == 1         # слепок сохранён как ревизия


@pytest.mark.asyncio
async def test_rollback_prompt_canons_refuses(edition, caplog):
    """rollback_prompt_canons: ERROR и отказ, БД не пишется."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    with caplog.at_level(logging.ERROR, logger="services.prompt_migrations"):
        report = await pm.rollback_prompt_canons(cache)
    assert report == {}
    assert cache.set_calls == []
    assert any("отказ" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_migrate_core_owner_patch_refuses(edition, caplog):
    """Стартовый owner-patch Core снят: ERROR и отказ, БД не пишется.

    Абзацы владельца входят в заводскую редакцию Core v4 (проверено ниже) —
    их доезжает cutover-активация, а не правка каждого старта.
    """
    from services import chat_prompts as cp
    full = real_factory_text("core.personality")
    assert cp.CORE_REAL_EVENTS_PARAGRAPH in full
    assert cp.CORE_FREE_SPEECH_PARAGRAPH in full
    cache = FakeCache({"character.core": {"full_text": "текст владельца\n",
                                          "detail_level": "full"}})
    with caplog.at_level(logging.ERROR, logger="services.prompt_migrations"):
        report = await pm.migrate_core_owner_patch(cache)
    assert report == {}
    assert cache.set_calls == []
    assert any("отказ" in r.getMessage() for r in caplog.records)


def test_chain_constants_preserved_as_byte_etalons():
    """Слепки/лестницы не удаляются (байт-эталоны тестов и откатных ревизий),
    но они больше не механизм активации."""
    assert pm.PROMPT_MIGRATIONS, "слепки PREV_* должны остаться"
    assert pm.ROLLBACK_MIGRATIONS, "карта отката должна остаться"
    from services.chat_prompts import (CHAT_SYSTEM_PROMPT,
                                       PREV_CHAT_W2_SYSTEM_PROMPT)
    assert PREV_CHAT_W2_SYSTEM_PROMPT != CHAT_SYSTEM_PROMPT
    # единственный активный путь старта — делегатор релизной политики
    import inspect
    src = inspect.getsource(pm.migrate_prompt_canons)
    assert "prompt_release_policy" in src or "prp" in src
    assert "PROMPT_MIGRATIONS" not in src


@pytest.mark.asyncio
async def test_no_warn_per_read_for_custom_text(edition, journal, caplog):
    """После cutover чтение кастомного текста не WARN-ит «текст другой»."""
    cache = FakeCache({PG_KEY: FACTORY_A})
    await pm.migrate_prompt_canons(cache)
    custom = FACTORY_A + "\nСпокойная правка владельца.\n"
    cache.values[PG_KEY] = custom
    with caplog.at_level(logging.WARNING, logger="services.prompt_registry"):
        for _ in range(3):
            res = pr.resolve_speech_value(PG_KEY, custom, source="global",
                                          cache=cache)
    assert res.withheld is False and res.text == custom
    per_read_warnings = [r for r in caplog.records if "withheld" in
                         r.getMessage()]
    assert per_read_warnings == [], (
        "правка владельца после релиза не является предупреждением")
