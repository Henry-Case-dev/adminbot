"""Tests for services/info_service.py (T-339-A/B #15-24, Sections 52.3/53.3/53.7).

ФС-моки: tmp_path + явный путь конструктора. Канон DEFAULT_INFO_TEXT —
байт-в-байт с Section 53.3 (python + html блоки, якорь «### 53.3»); суть —
verbatim R44-1 (strip-теги == fenced-блок backlog); инициализация дефолтом;
load/save/кэш; save_text переживает «рестарт» (новый инстанс на том же пути).
"""
import logging
import re
from pathlib import Path

import pytest

from services.info_service import DEFAULT_INFO_TEXT, InfoService

_ARCH_53_ANCHOR = "### 53.3 "


def _arch_default_info() -> str:
    """Эталон из plans/ARCHITECTURE.md Section 53.3 (python-блок КАНОНА)."""
    lines = Path("plans/ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
    anchor = next(i for i, line in enumerate(lines) if line.startswith(_ARCH_53_ANCHOR))
    start = next(
        i for i, line in enumerate(lines[anchor:], anchor)
        if line.startswith("DEFAULT_INFO_TEXT = ")
    )
    end = next(
        i for i, line in enumerate(lines[start:], start) if line.endswith('"""')
    )
    block = lines[start : end + 1]
    block[0] = block[0][len('DEFAULT_INFO_TEXT = """'):]
    block[-1] = block[-1][:-3]
    return "\n".join(block)


def _arch_info_html_block() -> str:
    """Кросс-эталон: html-блок Section 53.3 (ПЕРВЫЙ ```html ПОСЛЕ якоря)."""
    lines = Path("plans/ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
    anchor = next(i for i, line in enumerate(lines) if line.startswith(_ARCH_53_ANCHOR))
    start = next(
        i for i, line in enumerate(lines[anchor:], anchor) if line.strip() == "```html"
    )
    end = next(
        i for i, line in enumerate(lines[start + 1:], start + 1)
        if line.strip() == "```"
    )
    return "\n".join(lines[start + 1 : end])


def _backlog_r44_1_text() -> str:
    """Verbatim-эталон СУТИ: fenced-блок канона R44-1 в plans/backlog.md."""
    lines = Path("plans/backlog.md").read_text(encoding="utf-8").splitlines()
    anchor = next(i for i, line in enumerate(lines) if "Канон R44-1" in line)
    start = next(
        i for i, line in enumerate(lines[anchor:], anchor) if line.strip() == "```"
    ) + 1
    end = next(
        i for i, line in enumerate(lines[start:], start) if line.strip() == "```"
    )
    return "\n".join(lines[start:end])


class TestDefaultInfoText:
    """#20-24: DEFAULT_INFO_TEXT == канону 53.3 байт-в-байт; валидный HTML;
    суть verbatim R44-1."""

    def test_byte_for_byte_with_architecture(self):
        assert DEFAULT_INFO_TEXT == _arch_default_info()

    def test_byte_for_byte_with_html_block(self):
        assert DEFAULT_INFO_TEXT == _arch_info_html_block()

    def test_html_tags_balanced(self):
        assert DEFAULT_INFO_TEXT.count("<b>") == DEFAULT_INFO_TEXT.count("</b>")
        assert DEFAULT_INFO_TEXT.count("<code>") == DEFAULT_INFO_TEXT.count("</code>")
        assert DEFAULT_INFO_TEXT.count("<a ") == DEFAULT_INFO_TEXT.count("</a>")

    def test_no_unbalanced_special_chars(self):
        stripped = DEFAULT_INFO_TEXT.replace("<b>", "").replace("</b>", "")
        stripped = stripped.replace("<code>", "").replace("</code>", "")
        stripped = stripped.replace('<a href="https://youtu.be/">', "")
        stripped = stripped.replace('<a href="https://какой-то-сайт.ru">', "")
        stripped = stripped.replace("</a>", "")
        assert "&" not in stripped and "<" not in stripped and ">" not in stripped

    def test_covers_features(self):
        for marker in (
            "Гайд по фичам", "фактчек", "чекап", "кулдаун", "Checkup",
            "youtu.be", "какой-то-сайт.ru", "100500%", "пересаживается",
            "ботяра",
        ):
            assert marker in DEFAULT_INFO_TEXT

    def test_canon_matches_backlog_r44_1_essence(self):
        """#24: снятие всех тегов == verbatim-канону R44-1 (вопрос 6)."""
        assert re.sub(r"<[^>]+>", "", DEFAULT_INFO_TEXT) == _backlog_r44_1_text()


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
