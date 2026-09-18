"""Tests for services/info_service.py (T-339-A/B #15-24, Sections 52.3/53.3/53.7).

ФС-моки: tmp_path + явный путь конструктора. Канон DEFAULT_INFO_TEXT —
байт-в-байт с info_text.md (Epic 83, T-599/D306; 84.13: файл — сид-источник
для PG); rich-структура h1/h2/h4/h5 валидна; суть — R44-1 (полная структура
секций 1..11 после H 10.20/БЛОК 8); инициализация дефолтом; load.

F2 10.16 (guide-delivery-round1016, ADR-1016-3):
  * `info_text.md` — read-only сид: load() НЕ создаёт/НЕ перезаписывает файл;
  * `save_text` — PG-only (файл не меняется, контент+mtime), PG down → исключение;
  * нормализация канона (`normalize_canon`/`canon_drift`), force-reset
    (`reset_canon`) с бэкапом `prev_html`/`prev_updated_at` и аудитом.
"""
import logging
from pathlib import Path

import pytest

from services.config_cache import ConfigCacheUnavailableError
from services.info_service import (
    DEFAULT_INFO_TEXT,
    INFO_CANON_VERSION,
    InfoService,
    canon_drift,
    normalize_canon,
)


class TestDefaultInfoText:
    """#20-24 (дельта Epic 83, T-599/D306): DEFAULT_INFO_TEXT == живой канон
    info_text.md байт-в-байт (байт-эталон); валидный rich-HTML; секции 1..9."""

    def test_byte_for_byte_with_info_text_file(self):
        assert (
            DEFAULT_INFO_TEXT
            == Path("info_text.md").read_text(encoding="utf-8")
        )

    def test_rich_structure_complete(self):
        """F9 10.23 (ADR-1023-9): rich-канон v5 — только h1/h2 для
        заголовков (никаких h3/h4/h5), команды — в blockquote.
        h1=1, h2=11 (v4 + «11. Генерация изображений»), blockquote=24, p=44."""
        assert DEFAULT_INFO_TEXT.count("<h1>") == DEFAULT_INFO_TEXT.count("</h1>") == 1
        assert DEFAULT_INFO_TEXT.count("<h2>") == DEFAULT_INFO_TEXT.count("</h2>") == 11
        assert DEFAULT_INFO_TEXT.count("<h3>") == 0
        assert DEFAULT_INFO_TEXT.count("<h4>") == 0
        assert DEFAULT_INFO_TEXT.count("<h5>") == 0
        assert DEFAULT_INFO_TEXT.count("<blockquote>") == \
            DEFAULT_INFO_TEXT.count("</blockquote>") == 24
        assert DEFAULT_INFO_TEXT.count("<p>") == DEFAULT_INFO_TEXT.count("</p>") == 44

    def test_html_tags_balanced(self):
        """F9 10.23: инлайн-акценты — b=39, i=39, u=0, a=2 (ссылки-примеры)."""
        assert DEFAULT_INFO_TEXT.count("<b>") == DEFAULT_INFO_TEXT.count("</b>") == 39
        assert DEFAULT_INFO_TEXT.count("<i>") == DEFAULT_INFO_TEXT.count("</i>") == 39
        assert DEFAULT_INFO_TEXT.count("<u>") == 0
        assert DEFAULT_INFO_TEXT.count("</u>") == 0
        assert DEFAULT_INFO_TEXT.count("<a ") == DEFAULT_INFO_TEXT.count("</a>") == 2

    def test_no_unbalanced_special_chars(self):
        stripped = DEFAULT_INFO_TEXT
        for tag in ("<h1>", "</h1>", "<h2>", "</h2>", "<p>", "</p>",
                    "<blockquote>", "</blockquote>",
                    "<b>", "</b>", "<i>", "</i>",
                    '<a href="https://youtu.be/">',
                    '<a href="https://какой-то-сайт.ru">', "</a>"):
            stripped = stripped.replace(tag, "")
        assert "&" not in stripped and "<" not in stripped and ">" not in stripped

    def test_covers_features(self):
        for marker in (
            "Гайд по фичам", "фактчек", "чекап", "кулдаун", "Checkup",
            "youtu.be", "какой-то-сайт.ru",
            "ботяра", "Богу Машине", "требуют обращения",
            # F7 10.22 (ADR-1022-7): транскрипт vs смысловая выжимка.
            "транскрипт", "поясни за видос", "о чем видео",
            # H 10.20 (БЛОК 8) сохранённое: актуальные фичи фаз B–G.
            "Летописец", "UPD (Свежак)", "Часовой пояс чата",
        ):
            assert marker in DEFAULT_INFO_TEXT

    def test_canon_matches_backlog_r44_1_essence(self):
        """F9 10.23: снятие всех тегов сохраняет структуру секций 1..11
        (v5 = v4 + «11. Генерация изображений»)."""
        for i in range(1, 12):
            assert f"<h2>{i}." in DEFAULT_INFO_TEXT


class TestCanonNormalization:
    """F2 10.16: нормализация сравнения канона (EOL/whitespace-дрейф)."""

    def test_normalize_collapses_eol_and_trailing_ws(self):
        assert normalize_canon("a\r\nb  \r\nc\t\r\n") == "a\nb\nc"

    def test_canon_not_drift_for_equal_text(self):
        assert canon_drift(DEFAULT_INFO_TEXT) is False

    def test_canon_drift_for_whitespace_variant(self):
        variant = DEFAULT_INFO_TEXT.replace("\n", "\r\n") + "\n\n  "
        assert canon_drift(variant) is False       # дрейф EOL/хвостов не считается

    def test_canon_drift_for_manual_text(self):
        assert canon_drift("<h1>ручная правка</h1>") is True
        assert canon_drift("") is True
        assert canon_drift(None) is True


class _FakeCache:
    """Минимальный sync-контракт ConfigCache для save_text/reset_canon."""

    def __init__(self, value=None, pg_available=True):
        self._value = value
        self.pg_available = pg_available
        self.set_calls = []

    def get(self, key, default=None):
        return self._value

    async def set(self, key, value, category):
        self.set_calls.append((key, value, category))
        self._value = value


class TestInfoServiceFs:
    def test_existing_file_loaded(self, tmp_path):
        """#15: файл существует с текстом → кэш == содержимому."""
        path = tmp_path / "info_text.md"
        path.write_text("<b>своя справка</b>", encoding="utf-8")
        service = InfoService(file_path=str(path))
        service.load()
        assert service.get_text() == "<b>своя справка</b>"

    def test_missing_file_not_created(self, tmp_path):
        """F2 10.16: файла нет → кэш = канон, файл НЕ создаётся (read-only сид)."""
        path = tmp_path / "info_text.md"
        service = InfoService(file_path=str(path))
        service.load()
        assert not path.exists()
        assert service.get_text() == DEFAULT_INFO_TEXT

    def test_empty_file_not_rewritten(self, tmp_path, caplog):
        """F2 10.16: пустой файл → кэш = канон, файл НЕ перезаписан + WARNING."""
        path = tmp_path / "info_text.md"
        path.write_text("   \n", encoding="utf-8")
        service = InfoService(file_path=str(path))
        with caplog.at_level(logging.WARNING):
            service.load()
        assert path.read_text(encoding="utf-8") == "   \n"
        assert service.get_text() == DEFAULT_INFO_TEXT
        assert any("empty seed" in r.message for r in caplog.records)

    def test_read_oserror_falls_back_to_inmemory_default(self, tmp_path, caplog):
        """#18: чтение OSError → WARNING; кэш = канон; файл НЕ перезаписан.

        Путь — существующая ДИРЕКТОРИЯ: open() на ней даёт PermissionError
        (подкласс OSError) на всех платформах, без monkeypatch builtins.open."""
        dir_path = tmp_path / "info_dir"
        dir_path.mkdir()
        service = InfoService(file_path=str(dir_path))
        with caplog.at_level(logging.WARNING):
            service.load()
        assert service.get_text() == DEFAULT_INFO_TEXT
        assert dir_path.is_dir()                       # файл не создан/не перезаписан
        assert any("read failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_save_text_pg_only_keeps_file_untouched(self, tmp_path):
        """F2 10.16 §8#7: save_text → PG обновлён; info_text.md НЕ изменён
        (контент + mtime), кэш сервиса = новый текст."""
        path = tmp_path / "info_text.md"
        path.write_text("старая справка", encoding="utf-8")
        before = path.read_bytes()
        before_mtime = path.stat().st_mtime
        service = InfoService(file_path=str(path))
        service.load()
        fake = _FakeCache()
        value = await service.save_text("<b>новая справка</b>",
                                        updated_by=4242, cache=fake)
        assert path.read_bytes() == before
        assert path.stat().st_mtime == before_mtime
        assert service._cache == "<b>новая справка</b>"
        assert fake.set_calls
        key, stored, category = fake.set_calls[0]
        assert key == "content.info_how_it_works"
        assert category == "content"
        assert stored["html"] == "<b>новая справка</b>"
        assert stored["updated_by"] == 4242
        assert stored["updated_at"]
        assert stored["canon_version"] == INFO_CANON_VERSION  # ручная правка не бампает
        assert value["html"] == "<b>новая справка</b>"

    @pytest.mark.asyncio
    async def test_save_text_pg_down_raises_cache_unchanged(self, tmp_path):
        """F2 10.16 §8#8: PG down → ConfigCacheUnavailableError; файл и кэш
        сервиса не разъезжаются (локально-только НЕ пишем)."""
        path = tmp_path / "info_text.md"
        path.write_text("старая", encoding="utf-8")
        service = InfoService(file_path=str(path))
        service.load()
        fake = _FakeCache(pg_available=False)
        with pytest.raises(ConfigCacheUnavailableError):
            await service.save_text("новая", cache=fake)
        assert path.read_text(encoding="utf-8") == "старая"
        assert service._cache == "старая"
        assert fake.set_calls == []

    @pytest.mark.asyncio
    async def test_reset_canon_backs_up_prev_and_audits(self):
        """F2 10.16 §8#6: force-reset пишет канон, бэкапит prev_html/prev_updated_at
        и проставляет updated_by (id, R16)."""
        prev = {"html": "<h1>ручная правка</h1>",
                "canon_version": INFO_CANON_VERSION,
                "updated_at": "2026-09-13T00:00:00+00:00",
                "updated_by": 1}
        fake = _FakeCache(value=prev)
        service = InfoService(file_path="unused.md")
        value = await service.reset_canon(updated_by=777, cache=fake)
        stored = fake.set_calls[0][1]
        assert stored["html"] == DEFAULT_INFO_TEXT
        assert stored["canon_version"] == INFO_CANON_VERSION
        assert stored["updated_by"] == 777
        assert stored["updated_at"]
        assert stored["prev_html"] == "<h1>ручная правка</h1>"
        assert stored["prev_updated_at"] == "2026-09-13T00:00:00+00:00"
        assert value["canon_version"] == INFO_CANON_VERSION

    @pytest.mark.asyncio
    async def test_reset_canon_without_current_value(self):
        """force-reset при отсутствии значения: без prev_* (нечего бэкапить)."""
        fake = _FakeCache(value=None)
        service = InfoService(file_path="unused.md")
        value = await service.reset_canon(updated_by=5, cache=fake)
        assert "prev_html" not in value
        assert value["html"] == DEFAULT_INFO_TEXT
        assert service._cache == DEFAULT_INFO_TEXT

    @pytest.mark.asyncio
    async def test_reset_canon_pg_down_raises(self):
        fake = _FakeCache(pg_available=False)
        service = InfoService(file_path="unused.md")
        with pytest.raises(ConfigCacheUnavailableError):
            await service.reset_canon(cache=fake)
        assert fake.set_calls == []

    def test_get_text_before_load_returns_canon(self, tmp_path):
        service = InfoService(file_path=str(tmp_path / "never.md"))
        assert service.get_text() == DEFAULT_INFO_TEXT
