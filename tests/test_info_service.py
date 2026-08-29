"""Tests for services/info_service.py (T-339-A/B #15-24, Sections 52.3/53.3/53.7).

ФС-моки: tmp_path + явный путь конструктора. Канон DEFAULT_INFO_TEXT —
байт-в-байт с info_text.md (Epic 83, T-599/D306; 84.13: файл — сид-источник
для PG); rich-структура h1/h2/h4/h5 валидна; суть — R44-1 (полная структура
секций 1..9); инициализация дефолтом; load/save/кэш; save_text переживает
«рестарт» (новый инстанс на том же пути).
"""
import logging
from pathlib import Path

import pytest

from services.info_service import DEFAULT_INFO_TEXT, InfoService


class TestDefaultInfoText:
    """#20-24 (дельта Epic 83, T-599/D306): DEFAULT_INFO_TEXT == живой канон
    info_text.md байт-в-байт (84.13: он же — сид-источник для PG); валидный
    rich-HTML; полная структура секций 1..9."""

    def test_byte_for_byte_with_info_text_file(self):
        assert (
            DEFAULT_INFO_TEXT
            == Path("info_text.md").read_text(encoding="utf-8")
        )

    def test_rich_structure_complete(self):
        """#20: rich-разметка Epic 83: h1=1, h2=9, h4=30 (инлайн-акценты),
        h5=9 (тела секций) — счётчики сбалансированы."""
        assert DEFAULT_INFO_TEXT.count("<h1>") == DEFAULT_INFO_TEXT.count("</h1>") == 1
        assert DEFAULT_INFO_TEXT.count("<h2>") == DEFAULT_INFO_TEXT.count("</h2>") == 9
        assert DEFAULT_INFO_TEXT.count("<h4>") == DEFAULT_INFO_TEXT.count("</h4>") == 30
        assert DEFAULT_INFO_TEXT.count("<h5>") == DEFAULT_INFO_TEXT.count("</h5>") == 9

    def test_html_tags_balanced(self):
        """Epic 71 (T-550): счётчики rich-канона — b=32, i=32, u=0, a=2."""
        assert DEFAULT_INFO_TEXT.count("<b>") == DEFAULT_INFO_TEXT.count("</b>") == 32
        assert DEFAULT_INFO_TEXT.count("<i>") == DEFAULT_INFO_TEXT.count("</i>") == 32
        assert DEFAULT_INFO_TEXT.count("<u>") == 0
        assert DEFAULT_INFO_TEXT.count("</u>") == 0
        assert DEFAULT_INFO_TEXT.count("<a ") == DEFAULT_INFO_TEXT.count("</a>") == 2

    def test_no_unbalanced_special_chars(self):
        stripped = DEFAULT_INFO_TEXT
        for tag in ("<h1>", "</h1>", "<h2>", "</h2>", "<h4>", "</h4>",
                    "<h5>", "</h5>", "<b>", "</b>", "<i>", "</i>",
                    '<a href="https://youtu.be/">',
                    '<a href="https://какой-то-сайт.ru">', "</a>"):
            stripped = stripped.replace(tag, "")
        assert "&" not in stripped and "<" not in stripped and ">" not in stripped

    def test_covers_features(self):
        for marker in (
            "Гайд по фичам", "фактчек", "чекап", "кулдаун", "Checkup",
            "youtu.be", "какой-то-сайт.ru",
            "ботяра", "Богу Машине", "ботохуета",
        ):
            assert marker in DEFAULT_INFO_TEXT

    def test_canon_matches_backlog_r44_1_essence(self):
        """#24 (дельта Epic 83): снятие всех тегов сохраняет полную структуру
        секций 1..9 (суть R44-1; живой канон — info_text.md)."""
        for i in range(1, 10):
            assert f"<h2>{i}." in DEFAULT_INFO_TEXT


class TestInfoServiceFs:
    def test_existing_file_loaded(self, tmp_path):
        """#15: файл существует с текстом → кэш == содержимому."""
        path = tmp_path / "info_text.md"
        path.write_text("<b>своя справка</b>", encoding="utf-8")
        service = InfoService(file_path=str(path))
        service.load()
        assert service.get_text() == "<b>своя справка</b>"

    def test_missing_file_created_with_canon(self, tmp_path):
        """#16: файла нет → файл СОЗДАН, содержимое == DEFAULT_INFO_TEXT (UTF-8).

        Запись идёт в текстовом режиме (канон 52.3): на win32 питон подставляет
        \r\n — байтовая сверка с нормализацией переводов строк (прод-linux
        даёт ровное байтовое равенство; семантика канона сохранена)."""
        path = tmp_path / "info_text.md"
        service = InfoService(file_path=str(path))
        service.load()
        assert path.read_bytes().replace(b"\r\n", b"\n") == DEFAULT_INFO_TEXT.encode("utf-8")
        assert service.get_text() == DEFAULT_INFO_TEXT

    def test_empty_file_replaced_with_canon(self, tmp_path, caplog):
        """#17: пустой файл → канон записан + кэш = канон + WARNING."""
        path = tmp_path / "info_text.md"
        path.write_text("   \n", encoding="utf-8")
        service = InfoService(file_path=str(path))
        with caplog.at_level(logging.WARNING):
            service.load()
        assert path.read_text(encoding="utf-8") == DEFAULT_INFO_TEXT
        assert service.get_text() == DEFAULT_INFO_TEXT
        assert any("empty file" in r.message for r in caplog.records)

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

    def test_save_text_rewrites_file_and_cache(self, tmp_path):
        """#19: save_text → файл + кэш; переживает «рестарт» (новый инстанс)."""
        path = tmp_path / "info_text.md"
        path.write_text("старая справка", encoding="utf-8")
        service = InfoService(file_path=str(path))
        service.load()
        service.save_text("<b>новая справка</b>")
        assert path.read_text(encoding="utf-8") == "<b>новая справка</b>"
        assert service.get_text() == "<b>новая справка</b>"

        restarted = InfoService(file_path=str(path))
        restarted.load()
        assert restarted.get_text() == "<b>новая справка</b>"

    def test_save_text_oserror_propagates_cache_unchanged(self, tmp_path):
        """save_text OSError → НАВЕРХ, кэш остаётся старым (52.3)."""
        path = tmp_path / "info_text.md"
        path.write_text("старая", encoding="utf-8")
        service = InfoService(file_path=str(path))
        service.load()
        blocker = tmp_path / "blocker"
        blocker.write_text("я файл", encoding="utf-8")
        service._file_path = str(blocker / "sub" / "info.md")  # родитель — файл
        with pytest.raises(OSError):
            service.save_text("новая")
        assert service.get_text() == "старая"

    def test_get_text_before_load_returns_canon(self, tmp_path):
        service = InfoService(file_path=str(tmp_path / "never.md"))
        assert service.get_text() == DEFAULT_INFO_TEXT
