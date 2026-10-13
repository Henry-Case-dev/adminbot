"""asap7 F9 (help re-sync, релиз 2.58.74) — контент-покрытие справки после
Waves 1-3 и канон-инварианты бампа INFO 7→8 / GUIDE 4→5.

Фактическое поведение (runtime truth, Waves 1-3 в проде):
  * Direct: смысловое понимание коротких контекстных реплик («а этот?»,
    «и чё»), выбор формы/тона ответа (вплоть до уместно резкого отпора в
    перепалке), инструменты по смыслу задачи, смешанные источники (сеть +
    история чата); «бот, …» — гарантированный текстовый ответ; реакции и
    осознанное молчание (🗿) — нормальные исходы; при выключенных
    автономных ответах на реплай — всегда текст;
  * обложки саммари: сюжет растёт из выжимки (story-first); нет сцены —
    честный отказ/выпуск без картинки;
  * модули миниаппа: «Инициатива», «Истории и эпизоды», «Характер»,
    «Опыт и уроки», «Случайность»; в «Аналитике» видна фактическая сборка
    промпта обложки (админская фича — без внутреннего жаргона).

TEST-LIFECYCLE: CONTRACT owner=ASAP7/F9

Запрещено в пользовательском тексте: термины ResponsePlan/L1/L2/planner/
DAG/extent/SelfModel и обещания «никогда не ошибается/всегда понимает».
"""
import re
import types
from pathlib import Path

import pytest

from services.config_cache import ConfigCache
from services.info_service import (
    DEFAULT_INFO_TEXT,
    GUIDE_CANON_VERSION,
    INFO_CANON_VERSION,
    KNOWN_GUIDE_SNAPSHOTS,
    KNOWN_INFO_SNAPSHOTS,
    PREV_ASAP7_DEFAULT_INFO_TEXT,
    PREV_ASAP7_INTELLIGENCE_GUIDE,
    canon_drift,
    guide_version_for,
)
from tests.helpers.info_layout import between_adjacent_blockquotes

ROOT = Path(__file__).resolve().parent.parent
GUIDE_MD = (ROOT / "plans" / "docs" / "intelligence_user_guide.md").read_text(
    encoding="utf-8")
INFO_MD = (ROOT / "info_text.md").read_text(encoding="utf-8")
INFO_KEY = "content.info_how_it_works"
GUIDE_KEY = "content.intelligence_guide"
ADMIN_ID = 5885953495

# ── «Гайд по фичам» (INFO v8) ───────────────────────────────────────────────

INFO_ASAP7_MARKERS = (
    # §13: короткая контекстная реплика понимается по разговору;
    "короткая реплика вроде «а этот?» или «и чё» - не обрывок",
    "не меряет сообщение линейкой",
    # §13: форму можно заказать; бот выберет сам;
    "<blockquote><b><i>Бот, в двух словах</i></b></blockquote>",
    "<blockquote><b><i>Бот, распиши подробно со всеми деталями</i></b>"
    "</blockquote>",
    # §13: инструменты по смыслу задачи + смешанные источники;
    "подключаются по смыслу задачи, а не по приметам",
    "бот сходит и в сеть, и в историю чата",
    # §10: обложка растёт из выжимки; нет сцены — честный отказ;
    "Обложка растёт из выжимки, а не из шаблона",
    "бот честно откажется рисовать",
    # §7: гарантированный текстовый ответ + каменное молчание + тон;
    "гарантированный текстовый ответ",
    "не отделывается смайлом",
    "каменного молчания 🗿",
    "в перепалке может уместно огрызнуться",
)

# ── «Мозг бота» (GUIDE v5) ──────────────────────────────────────────────────

GUIDE_ASAP7_MARKERS = (
    # §11: три шага (решение до tools → дело → слово);
    "Теперь у бота перед ответом три шага",
    "**Сначала - план.**",
    "**Потом - дело.**",
    "**Потом - слово.**",
    "Решение созревает до походов за данными, а не после",
    # §11: смешанные источники и честные возможности;
    "сходит и туда, и туда",
    "Воображаемых инструментов у него нет",
    # §11: короткая контекстная реплика + форма + тон (отпор в перепалке);
    "Короткая реплика вроде «а этот?» или «и чё» - не обрывок",
    "в перепалке может уместно огрызнуться",
    # §11: гарантированный текстовый ответ на прямое обращение;
    "вообще гарантированный текстовый ответ",
    # §11: фоновая болтовня — вправе не тратить слов;
    "если бота не звали и вопрос явно не к нему",
    # §12: реакции/🗿/autonomous-off семантика;
    "вручив камень 🗿 - его способ сказать «нечего добавить»",
    "бот на реплай отвечает текстом всегда, без реакций и молчаний",
    # модули миниаппа: где искать (по строке на модуль);
    "модуль **«Истории и эпизоды»** в разделе **«Модули»**",
    "модуль **«Характер»** в разделе **«Модули»**",
    "карточка **«Инициатива»** в разделе **«Модули»**",
    "карточка модуля **«Случайность»** - в разделе **«Модули»**",
    "карточка модуля **«Опыт и уроки»** - в разделе **«Модули»**",
    # §18: прозрачность обложек (админская, без жаргона);
    "фактический текст, который ушёл рисовальщику",
    "сцена, контекст, стиль",
    "что собралось на сервере - то и уйдёт",
    # §19: словарик пополнен.
    "**План**",
    "**Обложка**",
    "**Реакция**",
    "**Каменное молчание**",
)

FORBIDDEN_JARGON = (
    "responseplan", "execution dag", "executiongraph", "delivery router",
    "force direct", "planner", "dag", "extent", "selfmodel",
    "run inspector", "неймспейс", "эмбеддинг", "namespace",
)

FORBIDDEN_PROMISES = (
    "никогда не путает", "никогда не ошибается", "безошибочн",
    "сознани", "читает недоступный архив", "обучается весам",
    "учит веса", "переобучает веса", "всегда прав",
    "всегда понимает", "никогда не врёт", "не врёт никогда",
)


class TestInfoV8Content:
    """«Гайд по фичам» v8: Direct-семантика + обложки из выжимки."""

    def test_markers(self):
        for marker in INFO_ASAP7_MARKERS:
            assert marker in INFO_MD, marker

    def test_sections_1_to_13_in_order(self):
        headings = [int(m.group(1))
                    for m in re.finditer(r"<h2>(\d+)\.", DEFAULT_INFO_TEXT)]
        assert headings == list(range(1, 14)), headings

    def test_section13_examples_gap_clean(self):
        i = INFO_MD.index("<h2>13.")
        gaps = between_adjacent_blockquotes(INFO_MD[i:])
        assert gaps, "нет групп соседних примеров в разделе 13"
        for gap in gaps:
            assert gap.strip() == "", repr(gap)
            assert "." not in gap and "," not in gap and " или " not in gap

    def test_section13_no_slash_commands(self):
        i = INFO_MD.index("<h2>13.")
        plain = re.sub(r"</?[a-z0-9]+[^>]*>", "", INFO_MD[i:])
        assert "/" not in plain

    def test_game_stub_not_advertised(self):
        # «Игру» в гайде упоминает только цитата-пример (§8), реклама
        # игровой заглушки как фичи запрещена (§0 current_task).
        low_info = INFO_MD.lower()
        for leak in ("игра", "поиграть", "запусти игру"):
            assert leak not in low_info, leak
        assert "поиграть" not in GUIDE_MD.lower()
        assert "запусти игру" not in GUIDE_MD.lower()


class TestGuideV5Content:
    """«Мозг бота» v5: три шага, реакции/молчание, модули, прозрачность."""

    def test_markers(self):
        for marker in GUIDE_ASAP7_MARKERS:
            assert marker in GUIDE_MD, marker

    def test_headings_in_order(self):
        headings = [int(m.group(1))
                    for m in re.finditer(r"^## (\d+)\.", GUIDE_MD, re.M)]
        assert headings == list(range(1, 20)), headings

    def test_core_sections_untouched(self):
        for marker in (
            "## 11. Как бот думает (System 2)",
            "## 12. Самостоятельность",
            "## 19. Словарик",
            "По умолчанию бот не спит",
            "Работает по умолчанию",
        ):
            assert marker in GUIDE_MD, marker

    def test_no_prompt_word_in_guide(self):
        # Жаргон-гейт mca-21: «промпт» в гайде запрещён (пользовательский
        # текст описывает сборку картинками, а не внутренними терминами).
        assert "промпт" not in GUIDE_MD.lower()


class TestNoJargonOrFalsePromises:
    """§0 current_task: справка — не dump терминов; обещаний нет."""

    def test_forbidden_jargon_absent(self):
        for text in (GUIDE_MD, INFO_MD):
            low = text.lower()
            for term in FORBIDDEN_JARGON:
                assert term not in low, term

    def test_forbidden_promises_absent(self):
        for text in (GUIDE_MD, INFO_MD):
            low = text.lower()
            for promise in FORBIDDEN_PROMISES:
                assert promise not in low, promise

    def test_r17_no_real_identifiers(self):
        for text in (GUIDE_MD, INFO_MD):
            assert "sk-" not in text.lower()
            assert "api_key" not in text.lower()
            assert "-100" not in text


class TestCanonInvariants:
    """Бампы 7→8 / 4→5: слепки заморожены чисто, лестница версий цела."""

    def test_versions_and_registries(self):
        assert INFO_CANON_VERSION == 9
        assert GUIDE_CANON_VERSION == 6
        assert len(KNOWN_INFO_SNAPSHOTS) == 8
        assert len(KNOWN_GUIDE_SNAPSHOTS) == 5
        assert KNOWN_INFO_SNAPSHOTS[-2] is PREV_ASAP7_DEFAULT_INFO_TEXT
        assert KNOWN_GUIDE_SNAPSHOTS[-2] is PREV_ASAP7_INTELLIGENCE_GUIDE

    def test_v7_snapshot_frozen_clean(self):
        # Слепок v7 = прод-канон mca-23 (2.58.71): БЕЗ asap7-блоков.
        assert "гарантированный текстовый ответ" \
            not in PREV_ASAP7_DEFAULT_INFO_TEXT
        assert "каменного молчания" not in PREV_ASAP7_DEFAULT_INFO_TEXT
        assert "Обложка растёт из выжимки" not in PREV_ASAP7_DEFAULT_INFO_TEXT
        assert "<h2>13. Просьбы посложнее" in PREV_ASAP7_DEFAULT_INFO_TEXT
        assert canon_drift(PREV_ASAP7_DEFAULT_INFO_TEXT) is True

    def test_v4_guide_snapshot_frozen_clean(self):
        # Слепок v4 = прод-гайд mca-23: БЕЗ asap7-блоков (два этапа, не три).
        assert "Теперь у бота перед ответом два этапа" \
            in PREV_ASAP7_INTELLIGENCE_GUIDE
        assert "три шага" not in PREV_ASAP7_INTELLIGENCE_GUIDE
        assert "вручив камень 🗿" not in PREV_ASAP7_INTELLIGENCE_GUIDE
        assert guide_version_for(PREV_ASAP7_INTELLIGENCE_GUIDE) == 4

    def test_current_canon_resolves_new(self):
        assert canon_drift(DEFAULT_INFO_TEXT) is False
        assert DEFAULT_INFO_TEXT == INFO_MD          # байт-зеркало
        assert guide_version_for(GUIDE_MD) == GUIDE_CANON_VERSION
        assert guide_version_for("") == GUIDE_CANON_VERSION

    def test_guide_version_ladder(self):
        for index, expected in enumerate((1, 2, 3, 4, 5)):
            assert guide_version_for(KNOWN_GUIDE_SNAPSHOTS[index]) == expected


# ── идемпотентная миграция v7→v8 / v4→v5 (generic-механизм) ────────────────

class _FakeConn:
    def __init__(self, settings_rows=()):
        self.queries = []
        self._settings_rows = list(settings_rows)

    async def execute(self, sql, *args):
        self.queries.append((sql, tuple(args)))
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        if "bot_settings" in sql:
            return self._settings_rows
        return []


class _FakePg:
    def __init__(self, conn):
        self._conn = conn

    @property
    def pool(self):
        return self

    async def connect(self):
        pass

    async def init(self, seed_settings=True):
        pass

    async def close(self):
        pass

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


def _row(key, value):
    return [{"key": key, "value": value, "category": "content"}]


def _cache(rows, monkeypatch, guide_seed=None):
    monkeypatch.setattr(
        "services.config_cache.settings",
        types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID,
                              INFO_TEXT_FILE="no_such_file_f9.md"))
    if guide_seed is not None:
        monkeypatch.setattr("services.config_cache._GUIDE_SEED_FILE",
                            guide_seed)
    conn = _FakeConn(rows)
    return ConfigCache(pg=_FakePg(conn), retry_attempts=1,
                       retry_delay=0), conn


def _inserts(conn, key):
    return [q for q in conn.queries
            if "INSERT INTO bot_settings" in q[0]
            and q[1] and q[1][0] == key]


class TestMigrations:
    @pytest.mark.asyncio
    async def test_info_v7_snapshot_migrated_to_v8(self, monkeypatch):
        cache, conn = _cache(_row(INFO_KEY, {
            "html": PREV_ASAP7_DEFAULT_INFO_TEXT, "updated_at": "t",
            "updated_by": 1}), monkeypatch)
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_version"] == INFO_CANON_VERSION == 9
        assert value["canon_delivered_version"] == INFO_CANON_VERSION
        assert len(_inserts(conn, INFO_KEY)) == 1

    @pytest.mark.asyncio
    async def test_info_migration_idempotent(self, monkeypatch):
        cache, conn = _cache(_row(INFO_KEY, {
            "html": PREV_ASAP7_DEFAULT_INFO_TEXT, "updated_at": "t",
            "updated_by": 1}), monkeypatch)
        await cache.init()
        before = len(_inserts(conn, INFO_KEY))
        await cache._migrate_info_how_it_works_v1015()
        await cache._migrate_info_how_it_works_v1015()
        assert len(_inserts(conn, INFO_KEY)) == before == 1
        assert cache.get(INFO_KEY)["html"] == DEFAULT_INFO_TEXT

    @pytest.mark.asyncio
    async def test_guide_v4_snapshot_migrated_to_v5(self, monkeypatch, tmp_path):
        seed = tmp_path / "guide_v5.md"
        seed.write_text(GUIDE_MD, encoding="utf-8")
        cache, conn = _cache(_row(GUIDE_KEY, {
            "markdown": PREV_ASAP7_INTELLIGENCE_GUIDE, "updated_at": "t",
            "updated_by": 1}), monkeypatch, guide_seed=str(seed))
        await cache.init()
        value = cache.get(GUIDE_KEY)
        assert value["markdown"] == GUIDE_MD
        assert value["guide_version"] == GUIDE_CANON_VERSION == 6
        assert value["guide_delivered_version"] == GUIDE_CANON_VERSION
        assert len(_inserts(conn, GUIDE_KEY)) == 1

    @pytest.mark.asyncio
    async def test_manual_drift_not_overwritten(self, monkeypatch):
        manual = "<h1>Моя ручная справка</h1>"
        cache, conn = _cache(_row(INFO_KEY, {
            "html": manual, "canon_version": INFO_CANON_VERSION,
            "canon_delivered_version": INFO_CANON_VERSION,
            "updated_at": "t", "updated_by": 1}), monkeypatch)
        await cache.init()
        assert cache.get(INFO_KEY)["html"] == manual
        assert _inserts(conn, INFO_KEY) == []
