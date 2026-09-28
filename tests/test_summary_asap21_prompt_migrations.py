"""ASAP-2.1 — T-3980: миграции канонов L2 + Narrator + Legacy Single
(§26, контракт (g), механика ADR-1013-3).

  (а) canonical-old → canonical-new;
  (б) genuinely-custom → не тронут;
  (в) ключ отсутствует → code default (сид);
  ROLLBACK на PREV_*_R1028 возвращает прежний текст.
"""
import pytest

from services import prompt_migrations as pm
from services import summary_prompts as sp


class FakeCache:
    """Минимальный дубль ConfigCache-поведения (get/set + pg_available)."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.pg_available = True
        self.sets = []

    def get(self, key):
        return self.values.get(key)

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
    (_SYS, "sys_r1028", lambda: sp.PREV_SUMMARY_SYSTEM_R1028,
     lambda: sp.SYSTEM_PROMPT),
    (_SYS, "sys_r1021", lambda: sp.PREV_R1021_SUMMARY_SYSTEM_PROMPT,
     lambda: sp.SYSTEM_PROMPT),
]

_ROLLBACK_CASES = [
    (_L2, "l2", lambda: sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT,
     lambda: sp.PREV_SUMMARY_L2_WRITER_R1028),
    (_NARR, "narr", lambda: sp.SUMMARY_NARRATOR_SYSTEM_PROMPT,
     lambda: sp.PREV_SUMMARY_NARRATOR_R1028),
    (_SYS, "sys", lambda: sp.SYSTEM_PROMPT,
     lambda: sp.PREV_SUMMARY_SYSTEM_R1028),
]

# id-шники короткие: тексты промптов в test-id НЕ попадают
# (PYTEST_CURRENT_TEST env имеет потолок 32767 символов).


@pytest.mark.parametrize("key,_name,old_fn,new_fn", _CANON_CASES,
                         ids=[f"{c[1]}->{c[0].rsplit('.', 1)[-1]}"
                              for c in _CANON_CASES])
@pytest.mark.asyncio
async def test_canonical_old_migrated_to_new(key, _name, old_fn, new_fn):
    cache = FakeCache({key: old_fn()})
    report = await pm.migrate_prompt_canons(cache)
    assert report.get(key) == "updated"
    assert cache.values[key] == new_fn()


# ── (а-2) ROLLBACK: новый канон → непосредственный прежний (PREV_*_R1028) ──

@pytest.mark.parametrize("key,_name,new_fn,old_fn", _ROLLBACK_CASES,
                         ids=[c[1] for c in _ROLLBACK_CASES])
@pytest.mark.asyncio
async def test_rollback_returns_previous_canon(key, _name, new_fn, old_fn):
    cache = FakeCache({key: new_fn()})
    report = await pm.rollback_prompt_canons(cache)
    assert report.get(key) == "rolled_back"
    assert cache.values[key] == old_fn()


# ── (б) genuinely-custom не трогается ──────────────────────────────────────

@pytest.mark.parametrize("key", [
    "prompts.summary_l2_writer_system_prompt",
    "prompts.summary_narrator_system_prompt",
    "prompts.summary_system_prompt",
])
@pytest.mark.asyncio
async def test_custom_value_untouched(key):
    custom = ("МОЙ СОБСТВЕННЫЙ ПРОМПТ владельца: " + key + " " + "x" * 100)
    cache = FakeCache({key: custom})
    report = await pm.migrate_prompt_canons(cache)
    assert key not in report
    assert cache.values[key] == custom
    # ROLLBACK тоже не трогает custom.
    report2 = await pm.rollback_prompt_canons(cache)
    assert key not in report2
    assert cache.values[key] == custom


# ── (в) ключ отсутствует → skip (сид поставит канон) ───────────────────────

@pytest.mark.asyncio
async def test_missing_key_skipped():
    cache = FakeCache({})
    report = await pm.migrate_prompt_canons(cache)
    assert report == {}
    assert cache.sets == []


# ── идемпотентность: уже новый канон → no-op ───────────────────────────────

@pytest.mark.asyncio
async def test_already_new_canon_noop():
    cache = FakeCache({
        "prompts.summary_l2_writer_system_prompt":
            sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT,
        "prompts.summary_narrator_system_prompt":
            sp.SUMMARY_NARRATOR_SYSTEM_PROMPT,
        "prompts.summary_system_prompt": sp.SYSTEM_PROMPT,
    })
    report = await pm.migrate_prompt_canons(cache)
    assert report == {}
    assert cache.sets == []


# ── снимки байт-в-байт: PREV_*_R1028 == прежний канон (2.58.33) ────────────

def test_prev_snapshots_byte_exact():
    # Прежние каноны (прод 2.58.33): base R1027/R1023/R1021-схемы + блоки.
    assert sp.PREV_SUMMARY_L2_WRITER_R1028 == (
        sp._SUMMARY_L2_WRITER_R1027_BASE + "\n\n" + sp.TARGET_INSTRUCTION_BLOCK)
    assert sp.PREV_SUMMARY_NARRATOR_R1028 == (
        sp._SUMMARY_NARRATOR_R1023_BASE + "\n\n" + sp.TYPOGRAPHY_BLOCK)
    assert sp.PREV_SUMMARY_SYSTEM_R1028 == (
        sp._SUMMARY_R1021_BASE + sp.STYLE_BLOCKS_SUFFIX
        + "\n\n" + sp.BOT_KNOWLEDGE_INSTRUCTION)


# ── контракт (g): новый канон L2 содержит инструкции §15–§19/§21–§24 ───────

def test_new_l2_canon_has_required_instructions():
    canon = sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT
    # §15 грамматика.
    assert "заглавной буквы" in canon
    assert "случайных строчных начал" in canon
    # §16 двачерский голос (инструкция владельца) — запрет сленга снят.
    assert "Сарказм, интернет-сленг, двачерские обороты и мат разрешены" in canon
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
    # §97 жёсткие правила сохранены.
    assert "Не выдумывай цитаты" in canon
    assert "900 символов" in canon


def test_new_narrator_canon_model_choice():
    canon = sp.SUMMARY_NARRATOR_SYSTEM_PROMPT
    assert "твоё творческое решение" in canon
    # Прежнее «приписку добавит код» снято — код больше не дописывает.
    assert "добавит код" not in canon


def test_new_single_canon_model_choice_optional():
    canon = sp.SYSTEM_PROMPT
    assert "твоё творческое решение" in canon
    assert "Обязательно заверши" not in canon
    # placeholders не сломаны ({max_symbols} — подстановка, {username} — literal).
    assert canon.count("{max_symbols}") == 1


# ── L1-канон НЕ меняется (§7:3062–3066) ───────────────────────────────────

def test_l1_canon_untouched():
    assert sp.SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT == (
        sp._SUMMARY_L1_CLUSTERIZER_R1027_BASE
        + "\n\n" + sp.TARGET_INSTRUCTION_BLOCK)


# ── cover style — без миграций (§26:3495) ─────────────────────────────────

def test_cover_style_not_in_migrations():
    assert "prompts.summary_cover_style" not in pm.PROMPT_MIGRATIONS
    assert "prompts.summary_cover_style" not in pm.ROLLBACK_MIGRATIONS
