"""F9 `help-ui-v5-round1023` — Справка v5 и «Гайд по возможностям» v2.

Покрытие (ADR-1023-9, spec §6):
  * канон-версия ``INFO_CANON_VERSION == 5`` + ``PREV_R1023_DEFAULT_INFO_TEXT``
    (v4) в ``KNOWN_INFO_SNAPSHOTS``; цепочка v1/v2/v3/v4 сохранена;
  * байт-зеркало ``DEFAULT_INFO_TEXT ↔ info_text.md``;
  * секция «11. Генерация изображений»: команды в ``<blockquote>``, только
    ``<h1>``/``<h2>``, без точек/запятых/«или» между соседними примерами,
    без секретов/URL провайдера (R18);
  * идемпотентная PG-миграция справки v4 → v5 (слепок → канон; повтор → no-op;
    ручной дрейф → не затирается);
  * версионирование гайда: ``GUIDE_CANON_VERSION == 2`` +
    ``PREV_R1023_INTELLIGENCE_GUIDE`` (v1) в ``KNOWN_GUIDE_SNAPSHOTS``; контент
    v2 (манеры ответа, анти-штампы, System 2); идемпотентная миграция v1 → v2,
    ручная правка не затирается; ``get_guide`` отдаёт новый markdown.
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
    PREV_DEFAULT_INFO_TEXT,
    PREV_R1022_DEFAULT_INFO_TEXT,
    PREV_R1023_DEFAULT_INFO_TEXT,
    PREV_R1023_INTELLIGENCE_GUIDE,
    PREV_R2020_DEFAULT_INFO_TEXT,
    InfoService,
    canon_drift,
    normalize_canon,
)

ROOT = Path(__file__).resolve().parent.parent
INFO_KEY = "content.info_how_it_works"
GUIDE_KEY = "content.intelligence_guide"
ADMIN_ID = 5885953495
INFO_MD = ROOT / "info_text.md"
GUIDE_MD = ROOT / "plans" / "docs" / "intelligence_user_guide.md"


def _between_adjacent_blockquotes(text: str) -> list[str]:
    """Тексты-разделители, стоящие непосредственно между соседними
    ``</blockquote>`` и ``<blockquote>`` (без block-level прозы: если между ними
    начинается ``<p>``/``<h2>`` — это разные смысловые группы, не примеры)."""
    gaps = []
    for close in re.finditer(r"</blockquote>", text):
        nxt = text.find("<blockquote>", close.end())
        if nxt == -1:
            continue
        gap = text[close.end():nxt]
        if "<p>" in gap or "<h1>" in gap or "<h2>" in gap:
            continue
        gaps.append(gap)
    return gaps


# ── Справка v5: версия, снапшоты, байт-зеркало ─────────────────────────────

class TestInfoCanonV5:
    def test_version_is_5(self):
        assert INFO_CANON_VERSION == 5

    def test_v4_snapshot_registered_and_chain_kept(self):
        assert PREV_R1023_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS   # v4
        assert PREV_R1022_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS   # v3
        assert PREV_R2020_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS   # v2
        assert PREV_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS         # v1
        assert len(KNOWN_INFO_SNAPSHOTS) == 4

    def test_v4_snapshot_is_previous_not_current(self):
        assert normalize_canon(PREV_R1023_DEFAULT_INFO_TEXT) != \
            normalize_canon(DEFAULT_INFO_TEXT)
        assert canon_drift(PREV_R1023_DEFAULT_INFO_TEXT) is True
        assert canon_drift(DEFAULT_INFO_TEXT) is False
        # v5 = v4 + дописанная секция (секции 1–10 не тронуты).
        assert DEFAULT_INFO_TEXT.startswith(PREV_R1023_DEFAULT_INFO_TEXT)

    def test_byte_for_byte_mirror(self):
        assert DEFAULT_INFO_TEXT == INFO_MD.read_text(encoding="utf-8")


# ── Секция «11. Генерация изображений»: вёрстка + анти-секреты ──────────────

class TestImageSectionLayout:
    def test_section_11_present(self):
        assert "<h2>11. Генерация изображений</h2>" in DEFAULT_INFO_TEXT

    def test_only_h1_h2_headings(self):
        text = DEFAULT_INFO_TEXT
        assert text.count("<h1>") == text.count("</h1>") == 1
        assert text.count("<h2>") == text.count("</h2>") == 11
        for tag in ("h3", "h4", "h5", "h6"):
            assert text.count(f"<{tag}>") == 0, tag
            assert text.count(f"</{tag}>") == 0, tag

    def test_image_commands_in_blockquote(self):
        text = DEFAULT_INFO_TEXT
        for frag in (
            "<blockquote><b><i>Бот, нарисуй",
            "<blockquote><b><i>Бот, создай изображение",
            "<blockquote><b><i>Бот, создай мем",
        ):
            assert frag in text, frag
        assert text.count("<blockquote>") == text.count("</blockquote>") == 24

    def test_no_punctuation_or_conjunction_between_examples(self):
        gaps = _between_adjacent_blockquotes(DEFAULT_INFO_TEXT)
        assert gaps, "должны быть группы соседних примеров-цитат"
        for gap in gaps:
            assert gap.strip() == "", repr(gap)
            assert "." not in gap and "," not in gap
            assert " или " not in gap

    def test_tone_preserved_and_no_secrets(self):
        text = DEFAULT_INFO_TEXT
        assert "нахуй" in text and "хуям" in text
        assert "Никаких слеш-команд" in text
        low = text.lower()
        for leak in ("pollinations", "sk_", "https://gen.", "response_format",
                     "flux", "api key", "api_key"):
            assert leak not in low, leak


# ── идемпотентная PG-миграция справки v4 → v5 ──────────────────────────────

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


def _info_row(html, canon_version=None, delivered=None):
    value = {"html": html, "updated_at": "t", "updated_by": 1}
    if canon_version is not None:
        value["canon_version"] = canon_version
    if delivered is not None:
        value["canon_delivered_version"] = delivered
    return [{"key": INFO_KEY, "value": value, "category": "content"}]


def _guide_row(markdown, guide_version=None, delivered=None):
    value = {"markdown": markdown, "updated_at": "t", "updated_by": 1}
    if guide_version is not None:
        value["guide_version"] = guide_version
    if delivered is not None:
        value["guide_delivered_version"] = delivered
    return [{"key": GUIDE_KEY, "value": value, "category": "content"}]


def _cache(rows, monkeypatch, guide_seed=None):
    monkeypatch.setattr(
        "services.config_cache.settings",
        types.SimpleNamespace(ADMIN_USER_ID=ADMIN_ID,
                              INFO_TEXT_FILE="no_such_file_r1023.md"))
    if guide_seed is not None:
        monkeypatch.setattr("services.config_cache._GUIDE_SEED_FILE", guide_seed)
    conn = _FakeConn(rows)
    return ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0), conn


def _inserts(conn, key):
    return [q for q in conn.queries
            if "INSERT INTO bot_settings" in q[0]
            and q[1] and q[1][0] == key]


class TestInfoMigrationV4ToV5:
    @pytest.mark.asyncio
    async def test_v4_snapshot_migrated_to_v5(self, monkeypatch):
        cache, conn = _cache(_info_row(PREV_R1023_DEFAULT_INFO_TEXT),
                             monkeypatch)
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_version"] == INFO_CANON_VERSION == 5
        assert value["canon_delivered_version"] == INFO_CANON_VERSION
        assert len(_inserts(conn, INFO_KEY)) == 1

    @pytest.mark.asyncio
    async def test_idempotent_second_run_noop(self, monkeypatch):
        cache, conn = _cache(_info_row(PREV_R1023_DEFAULT_INFO_TEXT),
                             monkeypatch)
        await cache.init()
        before = len(_inserts(conn, INFO_KEY))
        await cache._migrate_info_how_it_works_v1015()
        await cache._migrate_info_how_it_works_v1015()
        assert len(_inserts(conn, INFO_KEY)) == before == 1
        assert cache.get(INFO_KEY)["html"] == DEFAULT_INFO_TEXT

    @pytest.mark.asyncio
    async def test_manual_drift_not_overwritten(self, monkeypatch, caplog):
        manual = "<h1>Моя ручная справка</h1>"
        rows = _info_row(manual, canon_version=INFO_CANON_VERSION,
                         delivered=INFO_CANON_VERSION)
        cache, conn = _cache(rows, monkeypatch)
        await cache.init()
        assert cache.get(INFO_KEY)["html"] == manual
        assert _inserts(conn, INFO_KEY) == []


# ── «Гайд по возможностям» v1 → v2: канон/контент ──────────────────────────

V2_CANON = "# Гайд по возможностям (v2, тестовый канон)\n\nНовое о боте.\n"


class TestGuideCanonV2:
    def test_version_is_2(self):
        assert GUIDE_CANON_VERSION == 2

    def test_v1_snapshot_registered(self):
        assert PREV_R1023_INTELLIGENCE_GUIDE in KNOWN_GUIDE_SNAPSHOTS
        assert len(KNOWN_GUIDE_SNAPSHOTS) == 1

    def test_v1_snapshot_differs_from_current_file(self):
        current = GUIDE_MD.read_text(encoding="utf-8")
        assert normalize_canon(PREV_R1023_INTELLIGENCE_GUIDE) != \
            normalize_canon(current)

    def test_v2_content_has_new_blocks(self):
        text = GUIDE_MD.read_text(encoding="utf-8")
        assert "## 11. Как бот думает (System 2)" in text
        assert "Быстрый трёп" in text
        assert "Обычный разговор" in text
        assert "Глубокий разбор" in text
        assert "фильтр против штампов" in text.lower()
        assert "Манера ответа" in text          # словарик пополнен
        assert "Анти-штампы" in text

    def test_v2_no_internal_jargon(self):
        text = GUIDE_MD.read_text(encoding="utf-8").lower()
        for leak in ("validator", "scrubber", "regex", "llm", "промпт",
                     "вербализатор", "синтезатор", "аналитик", "loop"):
            assert leak not in text, leak

    def test_get_guide_returns_new_markdown(self, monkeypatch):
        monkeypatch.setattr("services.info_service.hot.get",
                            lambda *a, **k: None)
        svc = InfoService(file_path=str(INFO_MD))
        got = svc.get_guide()
        assert got["markdown"] == GUIDE_MD.read_text(encoding="utf-8")


# ── идемпотентная PG-миграция гайда v1 → v2 ────────────────────────────────

class TestGuideMigrationV1ToV2:
    @staticmethod
    def _seed(tmp_path):
        seed = tmp_path / "guide_v2.md"
        seed.write_text(V2_CANON, encoding="utf-8")
        return str(seed)

    @pytest.mark.asyncio
    async def test_v1_snapshot_migrated_to_canon(self, monkeypatch, tmp_path):
        cache, conn = _cache(_guide_row(PREV_R1023_INTELLIGENCE_GUIDE),
                             monkeypatch, guide_seed=self._seed(tmp_path))
        await cache.init()
        value = cache.get(GUIDE_KEY)
        assert value["markdown"] == V2_CANON
        assert value["guide_version"] == GUIDE_CANON_VERSION == 2
        assert value["guide_delivered_version"] == GUIDE_CANON_VERSION
        assert len(_inserts(conn, GUIDE_KEY)) == 1

    @pytest.mark.asyncio
    async def test_idempotent_second_run_noop(self, monkeypatch, tmp_path):
        cache, conn = _cache(_guide_row(PREV_R1023_INTELLIGENCE_GUIDE),
                             monkeypatch, guide_seed=self._seed(tmp_path))
        await cache.init()
        before = len(_inserts(conn, GUIDE_KEY))
        await cache._migrate_intelligence_guide_r1023()
        await cache._migrate_intelligence_guide_r1023()
        assert len(_inserts(conn, GUIDE_KEY)) == before == 1
        assert cache.get(GUIDE_KEY)["markdown"] == V2_CANON

    @pytest.mark.asyncio
    async def test_manual_edit_after_delivery_not_overwritten(
            self, monkeypatch, tmp_path):
        manual = "# Моя ручная правка гайда"
        rows = _guide_row(manual, guide_version=GUIDE_CANON_VERSION,
                          delivered=GUIDE_CANON_VERSION)
        cache, conn = _cache(rows, monkeypatch, guide_seed=self._seed(tmp_path))
        await cache.init()
        assert cache.get(GUIDE_KEY)["markdown"] == manual
        assert _inserts(conn, GUIDE_KEY) == []

    @pytest.mark.asyncio
    async def test_unknown_before_delivery_force_delivered_with_backup(
            self, monkeypatch, tmp_path):
        manual = "# старая ручная правка"
        cache, conn = _cache(_guide_row(manual), monkeypatch,
                             guide_seed=self._seed(tmp_path))
        await cache.init()
        value = cache.get(GUIDE_KEY)
        assert value["markdown"] == V2_CANON
        assert value["guide_delivered_version"] == GUIDE_CANON_VERSION
        assert value["prev_markdown"] == manual
        assert len(_inserts(conn, GUIDE_KEY)) == 1

    @pytest.mark.asyncio
    async def test_missing_guide_key_is_noop(self, monkeypatch, tmp_path):
        cache, conn = _cache([], monkeypatch, guide_seed=self._seed(tmp_path))
        await cache._migrate_intelligence_guide_r1023()
        assert _inserts(conn, GUIDE_KEY) == []
