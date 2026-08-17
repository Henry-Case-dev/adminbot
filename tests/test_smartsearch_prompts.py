"""Tests for services/search_prompts.py (T-255-B, R33-6, D109 RESOLVED).

Байт-в-байт с эталоном Section 42.5.2; {max_symbols} — единственный
плейсхолдер; .replace-подстановка без KeyError.
"""
import re
from pathlib import Path

from services.search_prompts import SEARCH_SYSTEM_PROMPT


def _arch_search_prompt() -> str:
    """Эталон из plans/ARCHITECTURE.md Section 42.5.2 (эталон-блок)."""
    lines = Path("plans/ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("SEARCH_SYSTEM_PROMPT = ")
    )
    end = next(
        i for i, line in enumerate(lines[start:], start) if line.endswith('"""')
    )
    block = lines[start : end + 1]
    block[0] = block[0][len('SEARCH_SYSTEM_PROMPT = """'):]
    block[-1] = block[-1][:-3]
    return "\n".join(block)


EXPECTED_PROMPT = _arch_search_prompt()

# R36-2 (D120, Section 45.2): блок «ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА» — дословно
# (дефисные/звёздочные маркеры сохраняются, осознанное решение D120).
_VOLUME_BLOCK = (
    "ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА:\n"
    "- Максимальный жесткий потолок: {max_symbols} символов.\n"
    "- Длину ответа определяй сам по сложности темы:\n"
    "  * Простой вопрос, очевидный фейк или односложный факт -> короткий язвительный ответ на 2-4 предложения (без размазывания соплей).\n"
    "  * Сложная комплексная тема, спорный вброс или технический вопрос -> подробный разбор на пару абзацев с пруфами.\n"
    "- КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО лить воду, тянуть время и раздувать объем текста ради объема. Отвечай ровно столько, сколько нужно для сути."
)


class TestSearchPrompt:
    def test_byte_for_byte(self):
        assert SEARCH_SYSTEM_PROMPT == EXPECTED_PROMPT

    def test_max_symbols_is_the_only_placeholder(self):
        placeholders = set(re.findall(r"\{(\w+)\}", SEARCH_SYSTEM_PROMPT))
        assert placeholders == {"max_symbols"}
        assert SEARCH_SYSTEM_PROMPT.count("{max_symbols}") == 1

    def test_replace_substitution(self):
        formatted = SEARCH_SYSTEM_PROMPT.replace("{max_symbols}", "4000")
        assert "{max_symbols}" not in formatted
        assert "Максимальный жесткий потолок: 4000 символов." in formatted

    def test_volume_block_verbatim(self):
        """R36-2 (D120): блок «ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА» дословно,
        жёсткая строка «строго до» удалена."""
        assert _VOLUME_BLOCK in SEARCH_SYSTEM_PROMPT
        assert "ОГРАНИЧЕНИЕ: длина ответа строго до" not in SEARCH_SYSTEM_PROMPT

    def test_style_markers_from_tz(self):
        """R33-6: токсичный исследователь, ленивая печать, запреты."""
        assert "токсичный, циничный участник чата" in SEARCH_SYSTEM_PROMPT
        assert "выжимку сути, обоссав автора запроса за лень или тупость" in SEARCH_SYSTEM_PROMPT
        assert "Имитируй ленивую печать" in SEARCH_SYSTEM_PROMPT
        assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»)" in SEARCH_SYSTEM_PROMPT
        assert "Поясни тему глубоко и без воды" in SEARCH_SYSTEM_PROMPT
