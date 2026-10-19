"""asap8-v6 D14 (help re-sync, релиз 2.58.77) — контент-покрытие справки
после волн v6 и канон-инварианты бампа INFO 8→9 / GUIDE 5→6.

Фактическое поведение (runtime truth, волны v6):
  * C03/C03A: стиль обложки меняет внешность, а не сюжет; стилизованная
    версия, потерявшая сюжет, не публикуется — выходит базовая
    (`services/cover_style_jobs.py`: base_fallback/semantic_preservation_failed);
  * C06A: у Инициативы живая воронка «Возможности → Намерения → Решения →
    Отправлено» + top blocker + тик пульса (status_service/web/app.js),
    hot-toggle без перезапуска;
  * D01: правка досье — черновик переживает закрытие, устаревший ответ
    не переписывает правку (capture-до-await, request_token);
  * D05: цепочка «заметил→урок→…→помогло/не помогло» + usefulness
    known/(pos+neg), «Недостаточно данных» вместо 0% (web/app.js);
  * D07: у глобальной настройки видно переопределившие чаты (overrides map);
  * D08: тумблер «Случайности» работает и переживает перезапуск
    (config_cache.get_all() синтезирует PG-only ключи);
  * D12: у саммари видно покрытие («покрыто сообщений: N»);
  * D13: мобильная навигация сверху, кнопка «Сохранить» только при
    изменениях, dirty-leave guard.

TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/D14

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
    PREV_ASAP8V6_DEFAULT_INFO_TEXT,
    PREV_ASAP8V6_INTELLIGENCE_GUIDE,
    canon_drift,
    guide_version_for,
)

ROOT = Path(__file__).resolve().parent.parent
GUIDE_MD = (ROOT / "plans" / "docs" / "intelligence_user_guide.md").read_text(
    encoding="utf-8")
INFO_MD = (ROOT / "info_text.md").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
INFO_KEY = "content.info_how_it_works"
GUIDE_KEY = "content.intelligence_guide"
ADMIN_ID = 5885953495

# ── «Гайд по фичам» (INFO v9) ───────────────────────────────────────────────

INFO_V6_MARKERS = (
    # §10: стиль сохраняет сюжет; потеря сюжета → базовая, не публикация.
    "И про стиль: он меняет внешность, а не сюжет",
    "Стильная обложка обязана остаться картинкой про ваше саммари",
    "красивая, но чужая картинка публикуемой не считается",
)

# ── «Мозг бота» (GUIDE v6) ──────────────────────────────────────────────────

GUIDE_V6_MARKERS = (
    # §5: черновик досье защищён, stale-ответ не переписывает правку (D01);
    "Правишь карточку - правка под охраной",
    "не перепишет то, что ты уже поменял",
    # §10: карта переопределений (D07);
    "какие чаты переопределили её под себя и чем именно",
    # §12: воронка Инициативы + hot-тумблер (C06A);
    "у **«Инициативы»** теперь живая воронка",
    "сколько решений он принял и что реально отправлено",
    "тикает ли фоновый пульс вообще",
    "Рубильник модуля срабатывает без перезапуска бота",
    # §13: тумблер «Случайности» настоящий (D08);
    "Сам тумблер модуля в разделе **«Модули»** - не декорация",
    # §14: цепочка + честная полезность (D05);
    "заметил - выделил урок - проверил - применил - помогло или не помогло",
    "так и написано «недостаточно данных», а не нарисованные проценты",
    # §18: покрытие саммари (D12) + стиль/recovery (C03/C03A);
    "У саммари, к слову, видно покрытие",
    "она обязана сохранить сюжет выжимки - потеряла, публикуется базовая",
    "базовая картинка заново не генерируется и дублей выпуск не плодит",
    # §18: верхняя навигация + dirty-only кнопка сохранения (D13).
    "На телефоне меню теперь сверху: компактная панель вместо нижней",
    "Кнопка «Сохранить» появляется только тогда, когда есть что сохранять",
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


class TestInfoV9Content:
    """«Гайд по фичам» v9: стиль обложки сохраняет сюжет (C03/C03A)."""

    def test_markers(self):
        for marker in INFO_V6_MARKERS:
            assert marker in INFO_MD, marker

    def test_style_paragraph_after_story_paragraph(self):
        # Новый абзац стоит в §10 сразу за «Обложка растёт из выжимки».
        i = INFO_MD.index("Обложка растёт из выжимки")
        tail = INFO_MD[i:i + 600]
        assert "И про стиль: он меняет внешность, а не сюжет" in tail

    def test_sections_1_to_13_untouched(self):
        headings = [int(m.group(1))
                    for m in re.finditer(r"<h2>(\d+)\.", DEFAULT_INFO_TEXT)]
        assert headings == list(range(1, 14)), headings


class TestGuideV6Content:
    """«Мозг бота» v6: воронка, тумблеры, полезность, черновики, шелл."""

    def test_markers(self):
        for marker in GUIDE_V6_MARKERS:
            assert marker in GUIDE_MD, marker

    def test_headings_1_to_19_untouched(self):
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


class TestHelpMatchesShippedRuntime:
    """Каждое новое help-утверждение имеет живой носитель в коде UI."""

    def test_initiative_funnel_labels_exist(self):
        # C06A: воронка «Возможности → Намерения → Решения → Отправлено».
        for label in ("'Возможности'", "'Намерения'", "'Решения'",
                      "'Отправлено'"):
            assert label in APP_JS, label

    def test_usefulness_insufficient_label_exists(self):
        # D05: «Недостаточно данных» вместо 0%.
        assert "'Недостаточно данных'" in APP_JS

    def test_summary_coverage_line_exists(self):
        # D12: покрытие саммари в run-карточке.
        assert "покрыто сообщений: " in APP_JS

    def test_sticky_save_dirty_only_labels_exist(self):
        # D13 / CFG-04 (2428768): чип сохранения — честный индикатор (не кнопка),
        # подписи dirty/saving как в отгруженном runtime (review e27216d3).
        assert "dirty: 'не сохранено'" in APP_JS
        assert "saving: 'сохранение…'" in APP_JS

    def test_bottom_nav_removed(self):
        # D13: мобильная нижняя навигация удалена (верхняя вместо неё).
        assert 'class="bottom-nav' not in INDEX_HTML
        assert 'id="bottom-nav' not in INDEX_HTML

    def test_style_fallback_reasons_exist(self):
        # C03A: честные причины base-fallback зафиксированы в коде.
        cover_jobs = (ROOT / "services" / "cover_style_jobs.py").read_text(
            encoding="utf-8")
        for reason in ("semantic_preservation_failed", "style_disabled",
                       "invalid_image_payload"):
            assert reason in cover_jobs, reason


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
    """Бампы 8→9 / 5→6: слепки заморожены чисто, лестница версий цела."""

    def test_versions_and_registries(self):
        assert INFO_CANON_VERSION == 9
        assert GUIDE_CANON_VERSION == 6
        assert len(KNOWN_INFO_SNAPSHOTS) == 8
        assert len(KNOWN_GUIDE_SNAPSHOTS) == 5
        assert KNOWN_INFO_SNAPSHOTS[-1] is PREV_ASAP8V6_DEFAULT_INFO_TEXT
        assert KNOWN_GUIDE_SNAPSHOTS[-1] is PREV_ASAP8V6_INTELLIGENCE_GUIDE

    def test_v8_snapshot_frozen_clean(self):
        # Слепок v8 = прод-канон asap7 (2.58.74): БЕЗ v6-абзаца про стиль.
        assert "И про стиль: он меняет внешность, а не сюжет" \
            not in PREV_ASAP8V6_DEFAULT_INFO_TEXT
        assert "Обложка растёт из выжимки" in PREV_ASAP8V6_DEFAULT_INFO_TEXT
        assert canon_drift(PREV_ASAP8V6_DEFAULT_INFO_TEXT) is True

    def test_v5_guide_snapshot_frozen_clean(self):
        # Слепок v5 = прод-гайд asap7: БЕЗ v6-блоков (нет воронки/шелла).
        assert "теперь живая воронка" not in PREV_ASAP8V6_INTELLIGENCE_GUIDE
        assert "не декорация" not in PREV_ASAP8V6_INTELLIGENCE_GUIDE
        assert "компактная панель вместо нижней" \
            not in PREV_ASAP8V6_INTELLIGENCE_GUIDE
        assert guide_version_for(PREV_ASAP8V6_INTELLIGENCE_GUIDE) == 5

    def test_current_canon_resolves_new(self):
        assert canon_drift(DEFAULT_INFO_TEXT) is False
        assert DEFAULT_INFO_TEXT == INFO_MD          # байт-зеркало
        assert guide_version_for(GUIDE_MD) == GUIDE_CANON_VERSION
        assert guide_version_for("") == GUIDE_CANON_VERSION

    def test_guide_version_ladder(self):
        for index, expected in enumerate((1, 2, 3, 4, 5)):
            assert guide_version_for(KNOWN_GUIDE_SNAPSHOTS[index]) == expected


# ── идемпотентная миграция v8→v9 / v5→v6 (generic-механизм) ────────────────

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
                              INFO_TEXT_FILE="no_such_file_d14.md"))
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
    async def test_info_v8_snapshot_migrated_to_v9(self, monkeypatch):
        cache, conn = _cache(_row(INFO_KEY, {
            "html": PREV_ASAP8V6_DEFAULT_INFO_TEXT, "updated_at": "t",
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
            "html": PREV_ASAP8V6_DEFAULT_INFO_TEXT, "updated_at": "t",
            "updated_by": 1}), monkeypatch)
        await cache.init()
        before = len(_inserts(conn, INFO_KEY))
        await cache._migrate_info_how_it_works_v1015()
        await cache._migrate_info_how_it_works_v1015()
        assert len(_inserts(conn, INFO_KEY)) == before == 1
        assert cache.get(INFO_KEY)["html"] == DEFAULT_INFO_TEXT

    @pytest.mark.asyncio
    async def test_guide_v5_snapshot_migrated_to_v6(
            self, monkeypatch, tmp_path):
        seed = tmp_path / "guide_v6.md"
        seed.write_text(GUIDE_MD, encoding="utf-8")
        cache, conn = _cache(_row(GUIDE_KEY, {
            "markdown": PREV_ASAP8V6_INTELLIGENCE_GUIDE, "updated_at": "t",
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
