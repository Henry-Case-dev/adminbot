"""mca-23 guides (релиз 2.58.71, P2-C help) — контент-покрытие §50 current_task
и канон-инварианты после бампа INFO 6→7 / GUIDE 3→4.

Проверки:
  * Г1 («Мозг бота», plans/docs/intelligence_user_guide.md): §11 — объём по
    просьбе (фанфик как фанфик, короткий трёп остаётся коротким), гарантия
    ответа без гарантии краткости, один уточняющий вопрос, цепочка из
    нескольких инструментов, статья-оформление с тем же текстом в запасе;
    §1 — поиск по смыслу + (для хозяина) аккуратная смена модели поиска;
    словарик §19 пополнен;
  * Г2 («Гайд по фичам», info_text.md): раздел «13. Просьбы посложнее» —
    объём/пакет ссылок/статья/уточняющий вопрос; §7 — гарантия ответа;
  * запрещённые обещания и внутренний жаргон (ResponsePlan/Execution DAG/
    namespace) — 0 попаданий в обоих гайдах;
  * канон-инварианты: resolve после миграции даёт новый текст, слепки —
    прежний (v6/v3 заморожены), байт-зеркало, guide_version_for;
  * SC-R3c: канон-ключи content.* не читаются ботоведческим кодом.
"""
import re
from pathlib import Path

from services.info_service import (
    DEFAULT_INFO_TEXT,
    GUIDE_CANON_VERSION,
    INFO_CANON_VERSION,
    KNOWN_GUIDE_SNAPSHOTS,
    KNOWN_INFO_SNAPSHOTS,
    PREV_MCA23_DEFAULT_INFO_TEXT,
    PREV_MCA23_INTELLIGENCE_GUIDE,
    canon_drift,
    guide_version_for,
)

ROOT = Path(__file__).resolve().parent.parent
GUIDE_MD = (ROOT / "plans" / "docs" / "intelligence_user_guide.md").read_text(
    encoding="utf-8")
INFO_MD = (ROOT / "info_text.md").read_text(encoding="utf-8")

# ── §50: пункты «объяснить простыми словами» → места в гайдах ───────────────

GUIDE_MCA23_MARKERS = (
    # бот сам понимает, нужен короткий ответ или простыня;
    "Короткая болтовня простыни не требует",
    "«напиши фанфик» - это заказ на фанфик",
    # Force Direct — гарантия ответа, но не краткости (без термина);
    # asap7 (2.58.74): гарантия уточнена — текстовый ответ.
    "Прямая просьба с обращением - вообще гарантированный текстовый ответ",
    "гарантия касается самого ответа, а не его длины",
    # один уточняющий вопрос вместо угадывания;
    "Задаст один конкретный уточняющий вопрос",
    # несколько ссылок / несколько инструментов;
    "«Сравни эти две статьи»",
    "бот сам спланирует цепочку",
    # большой ответ может прийти статьёй;
    "может прийти оформленной статьёй",
    # если оформление не прошло — тот же текст обычным сообщением;
    "придёт тот же текст обычным сообщением",
    # историю можно искать в памяти (по смыслу, не только по буквам).
    "поищет по смыслу, а не только по буквам",
    # namespace-safety — одна строка в админском контексте (§1).
    "сменит модель, которой бот ищет по памяти",
    # словарик.
    "**Уточняющий вопрос**",
    "**Статья**",
    "**Цепочка**",
)

INFO_MCA23_MARKERS = (
    "<h2>13. Просьбы посложнее (объём и несколько дел за раз)</h2>",
    "короткая болтовня остаётся короткой",
    "«напиши фанфик» - это фанфик",
    "<blockquote><b><i>Бот, сравни эти две статьи</i></b></blockquote>",
    "<blockquote><b><i>Бот, прочитай обе ссылки и скажи, где правда"
    "</i></b></blockquote>",
    "честно доложит, какой именно",
    "может прийти оформленной статьёй",
    "придёт тот же текст обычным сообщением, ничего не теряется",
    "задаст один конкретный уточняющий вопрос",
    # §7: гарантия ответа на прямое обращение без гарантии краткости
    # (asap7 (2.58.74): уточнение — гарантированный текстовый ответ).
    "прямая просьба с обращением - гарантированный текстовый ответ",
    "Гарантия распространяется на сам ответ, а не на его длину",
)


class TestGuide1Mca23Content:
    """§50: «Мозг бота» объясняет самостоятельность/объём/цепочки."""

    def test_section11_markers(self):
        for marker in GUIDE_MCA23_MARKERS:
            assert marker in GUIDE_MD, marker

    def test_core_sections_untouched(self):
        # mca-21 покров не срезан: прежние маркеры на месте.
        for marker in (
            "## 11. Как бот думает (System 2)",
            "## 12. Самостоятельность",
            "## 19. Словарик",
            "По умолчанию бот не спит",
            "Работает по умолчанию",
        ):
            assert marker in GUIDE_MD, marker

    def test_headings_in_order(self):
        headings = [int(m.group(1))
                    for m in re.finditer(r"^## (\d+)\.", GUIDE_MD, re.M)]
        assert headings == list(range(1, 20)), headings


class TestGuide2Mca23Content:
    """§50: «Гайд по фичам» — раздел 13 и §7."""

    def test_section13_markers(self):
        for marker in INFO_MCA23_MARKERS:
            assert marker in INFO_MD, marker

    def test_sections_1_to_13_in_order(self):
        headings = [int(m.group(1))
                    for m in re.finditer(r"<h2>(\d+)\.", DEFAULT_INFO_TEXT)]
        assert headings == list(range(1, 14)), headings

    def test_no_slash_commands_in_new_section(self):
        i = INFO_MD.index("<h2>13.")
        section = INFO_MD[i:]
        plain = re.sub(r"</?[a-z0-9]+[^>]*>", "", section)
        assert "/" not in plain

    def test_examples_gap_clean(self):
        # Между соседними примерами-цитатами раздела 13 — пусто, без
        # точек/запятых/«или» (правило вёрстки канона, общий хелпер).
        from tests.helpers.info_layout import between_adjacent_blockquotes
        i = INFO_MD.index("<h2>13.")
        gaps = between_adjacent_blockquotes(INFO_MD[i:])
        assert gaps, "нет групп соседних примеров в разделе 13"
        for gap in gaps:
            assert gap.strip() == "", repr(gap)
            assert "." not in gap and "," not in gap and " или " not in gap

    def test_namespace_jargon_not_in_user_guide2(self):
        # namespace-safety — админская деталь: в «Гайде по фичам» термина нет.
        low = INFO_MD.lower()
        for leak in ("namespace", "неймспейс", "эмбеддинг"):
            assert leak not in low, leak


class TestHonestyAndNoJargon:
    """§50: не dump терминов; обещания из запрещённого списка — 0."""

    def test_forbidden_promises_absent(self):
        for text in (GUIDE_MD, INFO_MD):
            low = text.lower()
            for promise in (
                "никогда не путает", "никогда не ошибается", "безошибочн",
                "сознани", "читает недоступный архив", "обучается весам",
                "учит веса", "переобучает веса", "всегда прав",
                "никогда не врёт", "не врёт никогда",
            ):
                assert promise not in low, promise

    def test_no_internal_plan_terms(self):
        # §50: справка — не dump терминов ResponsePlan/Execution DAG.
        for text in (GUIDE_MD, INFO_MD):
            low = text.lower()
            for term in ("responseplan", "execution dag", "executiongraph",
                         "response document", "delivery router", "force direct"):
                assert term not in low, term

    def test_r17_no_real_identifiers(self):
        for text in (GUIDE_MD, INFO_MD):
            assert "sk-" not in text.lower()
            assert "api_key" not in text.lower()
            assert "-100" not in text


class TestCanonInvariants:
    """Бампы 6→7 / 3→4: слепки прежних канонов, resolve после миграции."""

    def test_versions_and_registries(self):
        # asap7 (2.58.74): бамп 7→8 / 4→5, слепки v7/v4 — PREV_ASAP7_*.
        assert INFO_CANON_VERSION == 8
        assert GUIDE_CANON_VERSION == 5
        assert len(KNOWN_INFO_SNAPSHOTS) == 7
        assert len(KNOWN_GUIDE_SNAPSHOTS) == 4
        assert KNOWN_INFO_SNAPSHOTS[-2] is PREV_MCA23_DEFAULT_INFO_TEXT
        assert KNOWN_GUIDE_SNAPSHOTS[-2] is PREV_MCA23_INTELLIGENCE_GUIDE

    def test_prev_v6_frozen_without_mca23_blocks(self):
        # Слепок v6 — прежний канон mca-21: без раздела 13 и §7-гарантии.
        assert "<h2>13." not in PREV_MCA23_DEFAULT_INFO_TEXT
        assert "гарантированный ответ" not in PREV_MCA23_DEFAULT_INFO_TEXT
        assert canon_drift(PREV_MCA23_DEFAULT_INFO_TEXT) is True

    def test_prev_v3_guide_frozen(self):
        # Слепок v3 — прежний гайд mca-21: без mca-23-абзацев.
        assert "«напиши фанфик» - это заказ на фанфик" \
            not in PREV_MCA23_INTELLIGENCE_GUIDE
        assert "**Уточняющий вопрос**" not in PREV_MCA23_INTELLIGENCE_GUIDE
        assert guide_version_for(PREV_MCA23_INTELLIGENCE_GUIDE) == 3

    def test_current_canon_resolves_new(self):
        assert canon_drift(DEFAULT_INFO_TEXT) is False
        assert DEFAULT_INFO_TEXT == INFO_MD          # байт-зеркало
        assert guide_version_for(GUIDE_MD) == GUIDE_CANON_VERSION
        assert guide_version_for("") == GUIDE_CANON_VERSION
