"""Tests for services/youtube_prompts.py (T-289, R37-6, D132, Section 46.7.1/46.12).

Байт-в-байт с эталоном Section 46.7.1 (прецедент test_factcheck_prompts.py);
{max_symbols} — единственный плейсхолдер; .replace-подстановка без KeyError.
"""
import re
from pathlib import Path

from services.youtube_prompts import YOUTUBE_SYSTEM_PROMPT


def _arch_youtube_prompt() -> str:
    """Эталон из plans/ARCHITECTURE.md Section 46.7.1 (эталон-блок)."""
    lines = Path("plans/ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("YOUTUBE_SYSTEM_PROMPT = ")
    )
    end = next(
        i for i, line in enumerate(lines[start:], start) if line.endswith('"""')
    )
    block = lines[start : end + 1]
    block[0] = block[0][len('YOUTUBE_SYSTEM_PROMPT = """'):]
    block[-1] = block[-1][:-3]
    return "\n".join(block)


EXPECTED_PROMPT = _arch_youtube_prompt()


class TestYoutubePrompt:
    def test_byte_for_byte(self):
        assert YOUTUBE_SYSTEM_PROMPT == EXPECTED_PROMPT

    def test_max_symbols_is_the_only_placeholder(self):
        placeholders = set(re.findall(r"\{(\w+)\}", YOUTUBE_SYSTEM_PROMPT))
        assert placeholders == {"max_symbols"}
        assert YOUTUBE_SYSTEM_PROMPT.count("{max_symbols}") == 1

    def test_replace_substitution(self):
        formatted = YOUTUBE_SYSTEM_PROMPT.replace("{max_symbols}", "4000")
        assert "{max_symbols}" not in formatted
        assert "длина ответа строго до 4000 символов" in formatted

    def test_style_markers_from_tz(self):
        """R37-6: токсичный саркастичный участник чата, ленивая печать,
        запреты маркдауна/тире/ёлочек."""
        assert "токсичный, саркастичный участник чата" in YOUTUBE_SYSTEM_PROMPT
        assert "Имитируй ленивую печать" in YOUTUBE_SYSTEM_PROMPT
        assert "ЗАПРЕЩЕН любой маркдаун" in YOUTUBE_SYSTEM_PROMPT
        assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»)" in YOUTUBE_SYSTEM_PROMPT
        assert "сплошной текст с разделением на абзацы" in YOUTUBE_SYSTEM_PROMPT
        assert "едкую, плотную выжимку видео" in YOUTUBE_SYSTEM_PROMPT
        assert "о чем реально пиздит автор" in YOUTUBE_SYSTEM_PROMPT
