"""T-182-A: SYSTEM_PROMPT byte-for-byte against the backlog requirement (R11)."""
from pathlib import Path

import pytest

from services.summary_prompts import COMPRESS_PROMPT, SYSTEM_PROMPT


def _backlog_system_prompt() -> str:
    """Extract the verbatim prompt from plans/backlog.md Epic 24 (lines 1518-1523)."""
    lines = Path("plans/backlog.md").read_text(encoding="utf-8").splitlines()
    # Lines are 1-indexed: 1518..1523
    return "\n".join(lines[1517:1523])


EXPECTED_SYSTEM_PROMPT = _backlog_system_prompt()


class TestSystemPrompt:
    def test_system_prompt_byte_for_byte(self):
        """R11: the constant must match the backlog text EXACTLY."""
        assert SYSTEM_PROMPT == EXPECTED_SYSTEM_PROMPT

    def test_max_symbols_is_the_only_placeholder(self):
        assert SYSTEM_PROMPT.count("{") == 2
        assert SYSTEM_PROMPT.count("}") == 2
        assert "{max_symbols}" in SYSTEM_PROMPT
        assert "{username}" in SYSTEM_PROMPT

    def test_format_max_symbols(self):
        formatted = SYSTEM_PROMPT.replace("{max_symbols}", "3800")
        assert "3800 символов" in formatted
        assert "{max_symbols}" not in formatted
        assert "{username}" in formatted  # username stays literal for the LLM

    def test_shiz_marker_present(self):
        assert "самым главным шизом объявляется" in SYSTEM_PROMPT


class TestCompressPrompt:
    def test_compress_prompt_not_empty(self):
        assert len(COMPRESS_PROMPT) > 50

    def test_compress_prompt_limits_facts(self):
        assert "не больше 10" in COMPRESS_PROMPT

    def test_compress_prompt_style(self):
        assert "с маленькой буквы" in COMPRESS_PROMPT
        assert "сжиматель истории чата" in COMPRESS_PROMPT
