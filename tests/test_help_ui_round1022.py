"""F7 `help-ui-system2-round1022` — Справка v4 (ADR-1022-7, UPD3 §4).

Покрытие:
  * канон-версия ``INFO_CANON_VERSION == 4`` + ``PREV_R1022_DEFAULT_INFO_TEXT``
    (v3) в ``KNOWN_INFO_SNAPSHOTS``;
  * байт-зеркало ``DEFAULT_INFO_TEXT ↔ info_text.md`` (D224);
  * правила вёрстки ТЗ: только ``<h1>``/``<h2>`` (без h3+), каждая команда —
    в ``<blockquote>``, между соседними примерами-цитатами нет точек/запятых/
    союза «или»;
  * транскрипт vs смысловая выжимка (КРИТИЧНО);
  * п.11 «Безлимиты» удалён;
  * блок «Как бот думает (System 2)» в «Гайде по возможностям»;
  * идемпотентная PG-миграция v3 → v4;
  * рендер: DOMPurify default пропускает blockquote/h1/h2, CSS оформляет
    цитаты, санитайз не обойдён (v-html только через sanitized*).
"""
import types
from pathlib import Path

import pytest

from services.config_cache import ConfigCache
from tests.helpers.info_layout import between_adjacent_blockquotes
from services.info_service import (
    DEFAULT_INFO_TEXT,
    INFO_CANON_VERSION,
    KNOWN_INFO_SNAPSHOTS,
    PREV_DEFAULT_INFO_TEXT,
    PREV_R1022_DEFAULT_INFO_TEXT,
    PREV_R1023_DEFAULT_INFO_TEXT,
    PREV_R2020_DEFAULT_INFO_TEXT,
    canon_drift,
    normalize_canon,
)

ROOT = Path(__file__).resolve().parent.parent
INFO_KEY = "content.info_how_it_works"
ADMIN_ID = 5885953495
INFO_MD = ROOT / "info_text.md"
GUIDE_MD = ROOT / "plans" / "docs" / "intelligence_user_guide.md"
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
APP_CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
DOMPURIFY = (ROOT / "web" / "static" / "vendor"
             / "dompurify-3.4.15.min.js").read_text(encoding="utf-8")


def _between_adjacent_blockquotes(text: str) -> list[str]:
    """Совместимость: делегирует в общий util
    `tests.helpers.info_layout.between_adjacent_blockquotes`."""
    return between_adjacent_blockquotes(text)


# ── канон v4: версия, слепки, байт-зеркало ─────────────────────────────────

class TestCanonV4:
    def test_version_bumped(self):
        # F9 10.23 (ADR-1023-9): канон бампнут 4 → 5. v4-текст заморожен как
        # PREV_R1023_DEFAULT_INFO_TEXT (слепок миграции).
        assert INFO_CANON_VERSION == 5

    def test_v3_snapshot_registered(self):
        assert PREV_R1022_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS
        assert PREV_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS
        assert PREV_R2020_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS
        assert PREV_R1023_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS
        assert len(KNOWN_INFO_SNAPSHOTS) == 4

    def test_v3_snapshot_is_previous_canon_not_current(self):
        # v3-слепок — прошлый текст (h4/h5 + безлимиты), а не текущий канон.
        assert PREV_R1022_DEFAULT_INFO_TEXT.count("<h4>") > 0
        assert PREV_R1022_DEFAULT_INFO_TEXT.count("<h5>") > 0
        assert "Безлимит (∞)" in PREV_R1022_DEFAULT_INFO_TEXT
        assert normalize_canon(PREV_R1022_DEFAULT_INFO_TEXT) != \
            normalize_canon(DEFAULT_INFO_TEXT)
        assert canon_drift(PREV_R1022_DEFAULT_INFO_TEXT) is True
        assert canon_drift(DEFAULT_INFO_TEXT) is False

    def test_byte_for_byte_mirror(self):
        assert DEFAULT_INFO_TEXT == INFO_MD.read_text(encoding="utf-8")


# ── правила вёрстки ТЗ ─────────────────────────────────────────────────────

class TestLayoutRules:
    def test_only_h1_h2_headings(self):
        text = DEFAULT_INFO_TEXT
        assert text.count("<h1>") == text.count("</h1>") == 1
        # F9 10.23 добавил секцию «11. Генерация изображений» → h2 == 11.
        assert text.count("<h2>") == text.count("</h2>") == 11
        for tag in ("h3", "h4", "h5", "h6"):
            assert text.count(f"<{tag}>") == 0, tag
            assert text.count(f"</{tag}>") == 0, tag

    def test_every_command_group_in_blockquote(self):
        text = DEFAULT_INFO_TEXT
        # F9 10.23 добавил 3 команды изображений → blockquote == 24.
        assert text.count("<blockquote>") == text.count("</blockquote>") == 24
        # ключевые команды — в цитате (выделенная цитата/код в UI).
        for cmd in ("Бот, транскрипт", "Бот, поясни за видос", "Бот, о чем видео",
                    "Бот, загугли", "Бот, скачай", "фактчек"):
            assert f"<blockquote>" in text
            assert cmd in text, cmd

    def test_no_punctuation_or_conjunction_between_examples(self):
        gaps = _between_adjacent_blockquotes(DEFAULT_INFO_TEXT)
        assert gaps, "должны быть группы соседних примеров-цитат"
        for gap in gaps:
            assert gap.strip() == "", repr(gap)
            assert "." not in gap and "," not in gap
            assert " или " not in gap


# ── содержание ─────────────────────────────────────────────────────────────

class TestContent:
    def test_transcript_command_present(self):
        text = DEFAULT_INFO_TEXT
        assert "Дословное распознавание" in text
        assert "<blockquote><b><i>Бот, транскрипт</i></b></blockquote>" in text
        assert "голосовых" in text and "кружков" in text and "YouTube" in text

    def test_summary_commands_present(self):
        text = DEFAULT_INFO_TEXT
        assert "Смысловая выжимка" in text
        assert "<blockquote><b><i>Бот, поясни за видос</i></b></blockquote>" in text
        assert "<blockquote><b><i>Бот, о чем видео</i></b></blockquote>" in text

    def test_limits_section_removed(self):
        text = DEFAULT_INFO_TEXT
        assert "Безлимит (∞)" not in text
        assert "Импорт: Вечно" not in text
        assert "Модули → Бюджеты" not in text
        # F9 10.23: п.11 теперь «Генерация изображений» (а не «Безлимиты»).
        assert "<h2>11. Безлимиты" not in text
        assert text.count("<h2>") == 11

    def test_tone_of_voice_preserved(self):
        text = DEFAULT_INFO_TEXT
        assert "нахуй" in text
        assert "хуям" in text
        assert "Никаких слеш-команд" in text
        low = text.lower()
        for stale in ("уважаемый пользователь", "пожалуйста, обратитесь",
                      "инструкция по эксплуатации"):
            assert stale not in low, stale


# ── «Гайд по возможностям»: блок System 2 ──────────────────────────────────

class TestGuideSystem2:
    def test_system2_block_present_in_guide(self):
        text = GUIDE_MD.read_text(encoding="utf-8")
        assert "## 11. Как бот думает (System 2)" in text
        assert "Сначала - подумать" in text
        assert "Потом - сказать" in text
        # словарик сдвинут на 12 (нумерация без дыр).
        assert "## 12. Словарик" in text

    def test_guide_avoids_impl_details(self):
        # F9 10.23: запрет на внутренний жаргон сохранён и ужесточён
        # (validator-loop/scrubber/regex/имена слоёв). Человеческие описания
        # новых возможностей (манеры ответа, анти-штампы) при этом допустимы.
        text = GUIDE_MD.read_text(encoding="utf-8").lower()
        for leak in ("validator", "scrubber", "regex", "вербализатор",
                     "аналитик", "синтезатор", "loop", "промпт", "llm"):
            assert leak not in text, leak


# ── идемпотентная PG-миграция v3 → v4 ──────────────────────────────────────

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


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _CM()


class _FakePg:
    def __init__(self, conn):
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings=True):
        pass

    async def close(self):
        pass


def _settings_row(html, canon_version=None, delivered=None):
    value = {"html": html, "updated_at": "t", "updated_by": 1}
    if canon_version is not None:
        value["canon_version"] = canon_version
    if delivered is not None:
        value["canon_delivered_version"] = delivered
    return [{"key": INFO_KEY, "value": value, "category": "content"}]


def _cache(rows, monkeypatch):
    monkeypatch.setattr(
        "services.config_cache.settings",
        types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID,
                              INFO_TEXT_FILE="no_such_file_r1022.md"))
    conn = _FakeConn(rows)
    return ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0), conn


def _info_inserts(conn):
    return [q for q in conn.queries
            if "INSERT INTO bot_settings" in q[0]
            and q[1] and q[1][0] == INFO_KEY]


class TestMigrationV3ToV4:
    @pytest.mark.asyncio
    async def test_v3_snapshot_migrated_to_current(self, monkeypatch):
        cache, conn = _cache(_settings_row(PREV_R1022_DEFAULT_INFO_TEXT),
                             monkeypatch)
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_version"] == INFO_CANON_VERSION == 5
        assert value["canon_delivered_version"] == INFO_CANON_VERSION
        assert len(_info_inserts(conn)) == 1

    @pytest.mark.asyncio
    async def test_idempotent_second_run_noop(self, monkeypatch):
        cache, conn = _cache(_settings_row(PREV_R1022_DEFAULT_INFO_TEXT),
                             monkeypatch)
        await cache.init()
        before = len(_info_inserts(conn))
        await cache._migrate_info_how_it_works_v1015()
        await cache._migrate_info_how_it_works_v1015()
        assert len(_info_inserts(conn)) == before == 1
        assert cache.get(INFO_KEY)["html"] == DEFAULT_INFO_TEXT

    @pytest.mark.asyncio
    async def test_unknown_manual_text_not_overwritten_after_delivery(
            self, monkeypatch):
        manual = "<h1>Моя ручная справка</h1>"
        rows = _settings_row(manual, canon_version=INFO_CANON_VERSION,
                             delivered=INFO_CANON_VERSION)
        cache, conn = _cache(rows, monkeypatch)
        await cache.init()
        assert cache.get(INFO_KEY)["html"] == manual
        assert _info_inserts(conn) == []


# ── рендер / санитайзер ────────────────────────────────────────────────────

class TestRender:
    def test_dompurify_default_allows_needed_tags(self):
        # DOMPurify default allowlist (self-host 3.4.15) знает нужные теги.
        seg = DOMPURIFY[DOMPURIFY.find('"a","abbr"'):][:600]
        for tag in ("blockquote", "h1", "h2", "p"):
            assert f'"{tag}"' in seg, tag

    def test_sanitize_html_uses_dompurify_default_no_allowlist(self):
        block = APP_JS[APP_JS.index("sanitizeHtml: function"):]
        block = block[:block.index("saveInfo: async function")]
        assert "window.DOMPurify.sanitize(raw)" in block
        assert "ALLOWED_TAGS" not in block
        assert "INVALID_TAGS" not in block

    def test_info_rendered_only_through_sanitized_computed(self):
        # F1 (T-2400): рендер идёт через helpContent.infoHtml (агрегат,
        # построенный на sanitizedInfoHtml + id-анкеры заголовков).
        assert 'v-html="helpContent.infoHtml"' in INDEX
        assert "sanitizedInfoHtml: function" in APP_JS
        assert "helpContent: function" in APP_JS
        assert "this._anchorHtml(this.sanitizedInfoHtml" in APP_JS
        # предпросмотр редактора тоже через санитайз.
        assert "sanitizeHtml(infoDraft)" in INDEX

    def test_css_styles_info_html_blockquote_and_headings(self):
        assert ".info-html h2" in APP_CSS
        assert ".info-html blockquote" in APP_CSS
        assert "border-left" in APP_CSS[APP_CSS.index(".info-html blockquote"):][:200]

    def test_js_gate_present(self):
        gate = ROOT / "tests" / "js" / "round1022_help_test.js"
        assert gate.exists()
        assert "help-ui-system2-round1022" in gate.read_text(encoding="utf-8")
