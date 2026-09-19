"""Раунд 10.20 / Фаза H (БЛОК 8) — актуализация раздела «Справка» (T-1930).

Покрытие (ADR-1020-8, spec §19; актуализировано F7 10.22 / ADR-1022-7):
  * канон-версия ``INFO_CANON_VERSION == 4`` + ``KNOWN_INFO_SNAPSHOTS`` знает
    все прежние слепки (v1 … v3);
  * байт-зеркало ``DEFAULT_INFO_TEXT ↔ info_text.md``;
  * наличие блоков «Летописец»/«Фактчек», удаление п.11 «Безлимиты»;
  * tone of voice: дерзкий/ироничный, мат не переписан, нет канцелярита;
  * идемпотентная миграция прод-PG знает прежний (v2) слепок → канон v4;
  * снимок навигации: меню/структура вкладки «Справка» НЕ изменены.
"""
import re
import types
from pathlib import Path

import pytest

from services.config_cache import ConfigCache
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
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


# ── байт-зеркало и структура канона ─────────────────────────────────────────

class TestCanonV3:
    def test_version_bumped(self):
        # F9 10.23 (ADR-1023-9): канон бампнут 4 → 5 (секция изображений).
        assert INFO_CANON_VERSION == 5

    def test_known_snapshots_cover_all_prev_canons(self):
        assert PREV_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS          # v1
        assert PREV_R2020_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS    # v2
        assert PREV_R1022_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS    # v3
        assert PREV_R1023_DEFAULT_INFO_TEXT in KNOWN_INFO_SNAPSHOTS    # v4
        assert len(KNOWN_INFO_SNAPSHOTS) == 4

    def test_snapshots_distinct_from_current_canon(self):
        assert DEFAULT_INFO_TEXT != PREV_R1022_DEFAULT_INFO_TEXT
        assert DEFAULT_INFO_TEXT != PREV_R2020_DEFAULT_INFO_TEXT
        assert DEFAULT_INFO_TEXT != PREV_DEFAULT_INFO_TEXT
        assert PREV_R2020_DEFAULT_INFO_TEXT != PREV_DEFAULT_INFO_TEXT
        # v3-слепок — прошлый канон, не текущий (иначе миграция бессмысленна).
        assert canon_drift(DEFAULT_INFO_TEXT) is False
        assert normalize_canon(PREV_R1022_DEFAULT_INFO_TEXT) != \
            normalize_canon(DEFAULT_INFO_TEXT)

    def test_byte_for_byte_mirror(self):
        assert DEFAULT_INFO_TEXT == INFO_MD.read_text(encoding="utf-8")

    def test_structure_balanced(self):
        # F7 10.22: v4 использует только h1/h2 для заголовков + blockquote.
        for tag in ("h1", "h2", "b", "i", "p", "blockquote"):
            assert DEFAULT_INFO_TEXT.count(f"<{tag}>") == \
                DEFAULT_INFO_TEXT.count(f"</{tag}>") > 0
        assert DEFAULT_INFO_TEXT.count("<u>") == 0
        for tag in ("h3", "h4", "h5"):
            assert DEFAULT_INFO_TEXT.count(f"<{tag}>") == 0


# ── актуальность контента ───────────────────────────────────────────────────

class TestActualContent:
    def test_lore_compiler_block(self):
        text = DEFAULT_INFO_TEXT
        assert "Летописец" in text
        assert "UPD (Свежак)" in text
        assert "расскажи историю" in text
        # повторный запрос описан как «не пережёвывать старое заново».
        assert "второй раз" in text

    def test_factcheck_local_tools_and_smart_source(self):
        text = DEFAULT_INFO_TEXT
        assert "историю чата" in text
        assert "сам решает, где искать" in text
        assert "вердикт" in text
        assert "переслано: откуда" in text

    def test_limits_block_removed(self):
        # F7 10.22 (ADR-1022-7): п.11 «Безлимиты» удалён; F9 10.23 поставил
        # на п.11 «Генерацию изображений» (безлимиты так и не вернулись).
        text = DEFAULT_INFO_TEXT
        assert "Безлимит (∞)" not in text
        assert "Импорт: Вечно" not in text
        assert "Модули → Бюджеты" not in text
        assert "<h2>11. Безлимиты" not in text
        # прежний v3-текст (с безлимитами) сохранён как слепок-миграции.
        assert "Безлимит (∞)" in PREV_R1022_DEFAULT_INFO_TEXT

    def test_retired_mechanics_absent(self):
        # v2-формулировка фактчека «web-only» удалена при актуализации.
        assert "поднимет поисковики" not in DEFAULT_INFO_TEXT
        assert "поднимет поисковики" in PREV_R2020_DEFAULT_INFO_TEXT

    def test_tone_of_voice_preserved(self):
        text = DEFAULT_INFO_TEXT
        # фирменный дерзкий стиль и мат НЕ переписаны (политика владельца).
        assert "нахуй" in text
        assert "хуям" in text
        assert "<h1>" in text and "Никаких слеш-команд" in text
        assert text.count("<h2>") >= 10
        # канцелярит/корпоративный мануал — запрещён.
        low = text.lower()
        for stale in ("уважаемый пользователь", "пожалуйста, обратитесь",
                      "инструкция по эксплуатации", "опция недоступна"):
            assert stale not in low, stale


# ── идемпотентная миграция знает прежний слепок ─────────────────────────────

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
                              INFO_TEXT_FILE="no_such_file_h1020.md"))
    conn = _FakeConn(rows)
    return ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0), conn


def _info_inserts(conn):
    return [q for q in conn.queries
            if "INSERT INTO bot_settings" in q[0]
            and q[1] and q[1][0] == INFO_KEY]


class TestMigrationKnowsPrevSnapshot:
    @pytest.mark.asyncio
    async def test_v2_snapshot_migrated_to_current(self, monkeypatch):
        cache, conn = _cache(_settings_row(PREV_R2020_DEFAULT_INFO_TEXT),
                             monkeypatch)
        await cache.init()
        value = cache.get(INFO_KEY)
        assert value["html"] == DEFAULT_INFO_TEXT
        assert value["canon_version"] == INFO_CANON_VERSION == 5
        assert value["canon_delivered_version"] == INFO_CANON_VERSION
        assert len(_info_inserts(conn)) == 1

    @pytest.mark.asyncio
    async def test_v1_snapshot_still_migrated(self, monkeypatch):
        cache, _ = _cache(_settings_row(PREV_DEFAULT_INFO_TEXT), monkeypatch)
        await cache.init()
        assert cache.get(INFO_KEY)["html"] == DEFAULT_INFO_TEXT

    @pytest.mark.asyncio
    async def test_idempotent_second_run_noop(self, monkeypatch):
        cache, conn = _cache(_settings_row(PREV_R2020_DEFAULT_INFO_TEXT),
                             monkeypatch)
        await cache.init()
        before = len(_info_inserts(conn))
        await cache._migrate_info_how_it_works_v1015()
        await cache._migrate_info_how_it_works_v1015()
        assert len(_info_inserts(conn)) == before == 1


# ── снимок навигации / структура вкладки «Справка» ──────────────────────────

class TestNavigationUnchanged:
    EXPECTED_TABS = [
        "llm_providers", "prompts",
        "mod_summary", "mod_direct", "mod_factcheck", "mod_search",
        "mod_transcribe", "mod_video_summary", "mod_media_download", "mod_web",
        "mod_checkup", "mod_sleep", "mod_nostalgia", "mod_budgets",
        "mod_images",
        "modules", "memory_rag", "smart_cache", "people_names", "relations",
        "permsoc", "access", "chat_lore", "status", "info", "oversight",
    ]

    def test_tabs_ids_and_order_unchanged(self):
        start = APP_JS.index("var TABS = [")
        end = APP_JS.index("var LEVELS =", start)
        ids = re.findall(r"\{ id: '([a-z_0-9]+)'", APP_JS[start:end])
        assert ids == self.EXPECTED_TABS

    def test_info_tab_two_blocks_structure_kept(self):
        block = INDEX[INDEX.index("activeTab === 'info'"):]
        block = block[:block.index("</main>")]
        # ровно те же два редактируемых блока: «Справка» + «Гайд по возможностям».
        assert "Справка" in block
        assert "Гайд по возможностям" in block
        assert block.index("Гайд по возможностям") > block.index("Справка")
        assert block.count('class="card p-5') >= 2
