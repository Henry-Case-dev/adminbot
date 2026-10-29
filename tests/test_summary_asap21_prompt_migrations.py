"""ASAP-2.1 — T-3980: каноны L2 + Narrator + Legacy Single (§26).

EVOL-016/012 (30.10.2026): строковые ступени сняты — активацию решает
релизная политика (метка заводской ревизии + печать, журнал версий).
Проверяется здесь:
  (а) любое прежнее значение (слепки PREV_*) → снимок legacy в журнале,
      активной становится ТЕКУЩАЯ заводская редакция;
  (б) genuinely-custom → тоже снимок legacy (вечного иммунитета нет),
      заводская ревизия активна; лестница отката снята (отказ без записи),
      прежние байты возвращаются журналом (activate_revision);
  (в) ключ отсутствует → skipped_empty, затем активация заводской ревизии;
  рестарт без новой метки — no-op. Слепки PREV_* — байт-эталоны (ниже).
"""
import pytest

from services import prompt_migrations as pm
from services import prompt_registry as pr
from services import prompt_release_policy as prp
from services import summary_prompts as sp


@pytest.fixture()
def journal(monkeypatch):
    store = prp.MemoryPromptJournal()
    monkeypatch.setattr(prp, "default_journal", lambda cache=None: store)
    yield store
    pr.set_release_policy_active(False)
    from services import prompt_factory as _pf
    _pf._HISTORY_FROZEN = False
    pr.reset_cache()


class FakeCache:
    """Минимальный дубль ConfigCache-поведения (get/set + pg_available)."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.pg_available = True
        self.sets = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    async def set(self, key, value, category):
        self.sets.append((key, value, category))
        self.values[key] = value


# ── (а) canonical-old → canonical-new ──────────────────────────────────────

_L2 = "prompts.summary_l2_writer_system_prompt"
_NARR = "prompts.summary_narrator_system_prompt"
_SYS = "prompts.summary_system_prompt"

_CANON_CASES = [
    (_L2, "l2_r1027", lambda: sp.PREV_SUMMARY_L2_WRITER_R1027,
     lambda: sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT),
    (_L2, "l2_r1028", lambda: sp.PREV_SUMMARY_L2_WRITER_R1028,
     lambda: sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT),
    (_NARR, "narr_r1028", lambda: sp.PREV_SUMMARY_NARRATOR_R1028,
     lambda: sp.SUMMARY_NARRATOR_SYSTEM_PROMPT),
    (_NARR, "narr_r1023", lambda: sp.PREV_SUMMARY_NARRATOR_R1023,
     lambda: sp.SUMMARY_NARRATOR_SYSTEM_PROMPT),
    (_NARR, "narr_legfix", lambda: sp.PREV_SUMMARY_NARRATOR_LEGFIX,
     lambda: sp.SUMMARY_NARRATOR_SYSTEM_PROMPT),
    (_SYS, "sys_r1028", lambda: sp.PREV_SUMMARY_SYSTEM_R1028,
     lambda: sp.SYSTEM_PROMPT),
    (_SYS, "sys_r1021", lambda: sp.PREV_R1021_SUMMARY_SYSTEM_PROMPT,
     lambda: sp.SYSTEM_PROMPT),
]

_ROLLBACK_CASES = [
    # ASAP-4 волна D (ADR-1028-7 D4): откат prose-first → непосредственный
    # прежний прод-канон PREV_*_R1028_ASAP4 (с запретом цитат).
    # ASAP 4.1 волна 3 (T-4609, ADR-1028-8 D4/AM-4): откат блока источника →
    # канон R1029 (прод 2.58.46; parity с SUMMARY_WRITER_SOURCE_INPUT_
    # ENABLED=false).
    # SPEECH-P0-B2 (25.10.2026): первый откат снимает только P0-ступень →
    # прод-байты 2.58.130 (PREV_*_R1030_P0); второй — на R1029.
    (_L2, "l2", lambda: sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT,
     lambda: sp.PREV_SUMMARY_L2_WRITER_R1030_P0),
    (_NARR, "narr", lambda: sp.SUMMARY_NARRATOR_SYSTEM_PROMPT,
     # LEGFIX (22.10.2026): откат — на непосредственный прежний канон
     # (слепок ДО снятия identity-фразы; снимается только ступень LEGFIX).
     lambda: sp.PREV_SUMMARY_NARRATOR_LEGFIX),
    (_SYS, "sys", lambda: sp.SYSTEM_PROMPT,
     # CFG-07A-2 (ADR-1013-3): откат — на НЕПОСРЕДСТВЕННО прежний
     # прод-канон 2.58.100 (снимается только ступень CFG-07A).
     lambda: sp.PREV_SUMMARY_CFG07A_SYSTEM_PROMPT),
]

# id-шники короткие: тексты промптов в test-id НЕ попадают
# (PYTEST_CURRENT_TEST env имеет потолок 32767 символов).


@pytest.mark.parametrize("key,_name,old_fn,new_fn", _CANON_CASES,
                         ids=[f"{c[1]}->{c[0].rsplit('.', 1)[-1]}"
                              for c in _CANON_CASES])
@pytest.mark.asyncio
async def test_canonical_old_migrated_to_new(key, _name, old_fn, new_fn,
                                             journal):
    cache = FakeCache({key: old_fn()})
    report = await pm.migrate_prompt_canons(cache)
    assert report.get(key) == "updated"
    assert cache.values[key] == new_fn()
    # прежние байты — неизменяемая ревизия legacy в журнале
    spec = pr.by_pg_key(key)
    legacy = [r for r in journal.revisions.values()
              if r.block_id == spec.block_id and r.origin == "legacy"
              and r.content_sha12 == pr.sha12(old_fn())]
    assert len(legacy) == 1


# ── (а-2) ROLLBACK: лестница снята — прежние байты возвращает журнал ───────

@pytest.mark.parametrize("key,_name,new_fn,old_fn", _ROLLBACK_CASES,
                         ids=[c[1] for c in _ROLLBACK_CASES])
@pytest.mark.asyncio
async def test_rollback_returns_previous_canon(key, _name, new_fn, old_fn,
                                               journal, caplog):
    cache = FakeCache({key: new_fn()})
    with caplog.at_level("ERROR", logger="services.prompt_migrations"):
        report = await pm.rollback_prompt_canons(cache)
    assert report == {}
    assert cache.sets == []
    # журнал: прежние байты — восстанавливаемая ревизия (activate_revision)
    spec = pr.by_pg_key(key)
    await journal.insert_revision(prp.RevisionRow(
        revision_id=pr.revision_id_for(spec.block_id, "global", None,
                                       "manual", pr.sha12(old_fn())),
        block_id=spec.block_id, scope="global", origin="manual",
        content_sha12=pr.sha12(old_fn()), body=old_fn(), pg_key=key))
    rev = await journal.get_revision(
        pr.revision_id_for(spec.block_id, "global", None, "manual",
                           pr.sha12(old_fn())))
    res = await prp.activate_revision(spec.block_id, rev.revision_id,
                                      cache=cache, store=journal,
                                      actor="runbook")
    assert res["applied"]
    assert cache.values[key] == old_fn()


@pytest.mark.asyncio
async def test_l2_rollback_stack_retired_journal_restores(journal, caplog):
    """SPEECH-P0-B2: стек отката L2 существовал в лестнице; теперь лестница
    снята (отказ), а журнал возвращает любую сохранённую редакцию —
    включая байты 2.58.130 (PREV_*_R1030_P0) и R1029."""
    key = _L2
    cache = FakeCache({key: sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT})
    with caplog.at_level("ERROR", logger="services.prompt_migrations"):
        assert await pm.rollback_prompt_canons(cache) == {}
    assert cache.sets == []
    for prev in (sp.PREV_SUMMARY_L2_WRITER_R1030_P0,
                 sp.PREV_SUMMARY_L2_WRITER_R1029_ASAP41):
        await journal.insert_revision(prp.RevisionRow(
            revision_id=pr.revision_id_for("summary.base.l2_writer", "global",
                                           None, "manual", pr.sha12(prev)),
            block_id="summary.base.l2_writer", scope="global",
            origin="manual", content_sha12=pr.sha12(prev), body=prev,
            pg_key=key))
    rev = await journal.get_revision(
        pr.revision_id_for("summary.base.l2_writer", "global", None, "manual",
                           pr.sha12(sp.PREV_SUMMARY_L2_WRITER_R1030_P0)))
    res = await prp.activate_revision("summary.base.l2_writer", rev.revision_id,
                                      cache=cache, store=journal,
                                      actor="runbook")
    assert res["applied"]
    assert cache.values[key] == sp.PREV_SUMMARY_L2_WRITER_R1030_P0


# ── (б) genuinely-custom: снимок legacy, заводская активна (иммунитета нет) ─

@pytest.mark.parametrize("key", [
    "prompts.summary_l2_writer_system_prompt",
    "prompts.summary_narrator_system_prompt",
    "prompts.summary_system_prompt",
])
@pytest.mark.asyncio
async def test_custom_value_untouched(key, journal, caplog):
    custom = ("МОЙ СОБСТВЕННЫЙ ПРОМПТ владельца: " + key + " " + "x" * 100)
    cache = FakeCache({key: custom})
    with caplog.at_level("WARNING", logger="services.prompt_migrations"):
        report = await pm.migrate_prompt_canons(cache)
    assert report.get(key) == "updated"
    assert cache.values[key] == _factory_text(key)
    spec = pr.by_pg_key(key)
    legacy = [r for r in journal.revisions.values()
              if r.block_id == spec.block_id and r.origin == "legacy"
              and r.content_sha12 == pr.sha12(custom)]
    assert len(legacy) == 1
    assert not any("НЕ трогаем" in r.message for r in caplog.records)
    # ROLLBACK лестницей невозможен в принципе (отказ) — custom не «трогают»
    sets_before = len(cache.sets)
    with caplog.at_level("ERROR", logger="services.prompt_migrations"):
        report2 = await pm.rollback_prompt_canons(cache)
    assert report2 == {}
    assert len(cache.sets) == sets_before


def _factory_text(key: str) -> str:
    spec = pr.by_pg_key(key)
    assert spec is not None
    return pr.factory_text(spec.block_id)


# ── (в) ключ отсутствует → skipped_empty, затем активация заводской ────────

@pytest.mark.asyncio
async def test_missing_key_skipped(journal):
    cache = FakeCache({})
    report = await pm.migrate_prompt_canons(cache)
    assert report.get(_L2) in ("updated", "same")
    assert cache.values[_L2] == _factory_text(_L2)


# ── идемпотентность: рестарт с той же ревизией — no-op ─────────────────────

@pytest.mark.asyncio
async def test_already_new_canon_noop(journal):
    cache = FakeCache({
        "prompts.summary_l2_writer_system_prompt":
            sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT,
        "prompts.summary_narrator_system_prompt":
            sp.SUMMARY_NARRATOR_SYSTEM_PROMPT,
        "prompts.summary_system_prompt": sp.SYSTEM_PROMPT,
    })
    await pm.migrate_prompt_canons(cache)
    first = (len(journal.activations), len(journal.revisions))
    cache.sets.clear()
    report = await pm.migrate_prompt_canons(cache)
    assert all(v == "same" for v in report.values())
    assert (len(journal.activations), len(journal.revisions)) == first
    assert cache.sets == []


# ── снимки байт-в-байт: PREV_*_R1028 == прежний канон (2.58.33) ────────────

def test_prev_snapshots_byte_exact():
    # Прежние каноны (прод 2.58.33): base R1027/R1023/R1021-схемы + блоки.
    assert sp.PREV_SUMMARY_L2_WRITER_R1028 == (
        sp._SUMMARY_L2_WRITER_R1027_BASE + "\n\n" + sp.TARGET_INSTRUCTION_BLOCK)
    assert sp.PREV_SUMMARY_NARRATOR_R1028 == (
        sp._SUMMARY_NARRATOR_R1023_BASE + "\n\n" + sp.PREV_TYPOGRAPHY_BLOCK)
    assert sp.PREV_SUMMARY_SYSTEM_R1028 == (
        sp._SUMMARY_R1021_BASE + sp.PREV_SPEECH_STYLE_SUFFIX
        + "\n\n" + sp.BOT_KNOWLEDGE_INSTRUCTION)


# ── контракт (g): новый канон L2 содержит инструкции §15–§19/§21–§24 ───────

def test_new_l2_canon_has_required_instructions():
    canon = sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
    # §15 грамматика.
    assert "заглавной буквы" in canon
    assert "случайных строчных начал" in canon
    # §16 двачерский голос (инструкция владельца) — запрет сленга снят.
    # CORRECTIVE-FOLLOWUP (21.10.2026, §2): «и мат» удалено из списка —
    # режим мата задаёт только <Expression_Settings>.
    assert "Сарказм, интернет-сленг и двачерские обороты разрешены" in canon
    assert "мат разрешены" not in canon
    assert "не превращай текст в стерильную журналистику" in canon.lower() or \
        "Не превращай текст в стерильную журналистику" in canon
    assert "никакого сленга" not in canon       # запрет снят
    # §17 typography.
    assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире" in canon
    # §18–19 emphasis_spans, кап 4, никаких HTML/**.
    assert "emphasis_spans" in canon
    assert "НЕ БОЛЕЕ 4 спанов" in canon
    assert "Никакого HTML" in canon
    # §21–24 finale — выбор модели, опционально.
    assert '"finale"' in canon
    assert "твоё творческое решение" in canon
    # §97 (ASAP-4 волна D, ADR-1028-7 D4 SUPERSEDE): запрет цитат снят;
    # разрешение с доказанным source+speaker действует; абзац ≤900.
    assert "Не выдумывай цитаты" not in canon
    assert "Прямые цитаты НЕ запрещены" in canon
    assert "900 символов" in canon


def test_new_narrator_canon_model_choice():
    canon = sp.SUMMARY_NARRATOR_SYSTEM_PROMPT
    assert "твоё творческое решение" in canon
    # Прежнее «приписку добавит код» снято — код больше не дописывает.
    assert "добавит код" not in canon


def test_narrator_canon_has_no_identity_legacy():
    """LEGFIX (REGRESSION, 22.10.2026, backlog «narrator-канон identity-фраза»,
    bindings.cfg-final §6): активный канон Рассказчика не несёт
    identity-фразы старой личности (класс SF-07 корпуса 07A-2); жанровые
    контракты сохранены. TEST-LIFECYCLE: REGRESSION owner=FIX-SMALL-DEFECTS/narrator
    """
    canon = sp.SUMMARY_NARRATOR_SYSTEM_PROMPT
    for marker in ("бот-абьюзер", "двач", "токсичн"):
        assert marker not in canon.lower(), marker
    # Маркер-гейт реестра (persona.identity_sentence-семейство) молчит.
    from services.prompt_registry import legacy_persona_present
    assert legacy_persona_present(canon) is False
    # Жанровые контракты не потеряны при чистке.
    assert "допускай сарказм" in canon
    assert "{max_symbols}" in canon
    assert "Ты получаешь ТОЛЬКО готовую выжимку" in canon
    # Слепок ДО правки честный: несёт снятую фразу (ступень LEGFIX узнаёт
    # именно прод-байты) и отличается от нового канона.
    assert "бот-абьюзер" in sp.PREV_SUMMARY_NARRATOR_LEGFIX
    assert sp.PREV_SUMMARY_NARRATOR_LEGFIX != canon


def test_new_single_canon_model_choice_optional():
    canon = sp.SYSTEM_PROMPT
    assert "твоё творческое решение" in canon
    assert "Обязательно заверши" not in canon
    # placeholders не сломаны ({max_symbols} — подстановка, {username} — literal).
    assert canon.count("{max_symbols}") == 1


# ── L1-канон мигрирован на semantic map v1 (ASAP 4.1 волна 3, T-4607,
# ADR-1028-8 D3 SUPERSEDE) — прежний прод-канон 2.58.46 закреплён в PREV. ───

def test_l1_canon_untouched():
    # T-4607: канон = map v1; PREV-слепок = байт-в-байт прод 2.58.46.
    assert sp.PREV_SUMMARY_L1_CLUSTERIZER_R1027_ASAP41 == (
        sp._SUMMARY_L1_CLUSTERIZER_R1027_BASE
        + "\n\n" + sp.TARGET_INSTRUCTION_BLOCK)
    canon = sp.SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT
    assert '"schema_version": 1' in canon
    assert "semantic map" in canon.lower() or "СЕМАНТИЧЕСКУЮ КАРТУ" in canon
    # Суперседа-слепок ≠ новый канон (двух активных канонов нет).
    assert canon != sp.PREV_SUMMARY_L1_CLUSTERIZER_R1027_ASAP41


# ── cover style — без миграций (§26:3495) ─────────────────────────────────

def test_cover_style_not_in_migrations():
    assert "prompts.summary_cover_style" not in pm.PROMPT_MIGRATIONS
    assert "prompts.summary_cover_style" not in pm.ROLLBACK_MIGRATIONS
