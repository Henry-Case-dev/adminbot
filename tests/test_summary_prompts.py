"""T-182-A / T-217-B: SYSTEM_PROMPT byte-for-byte against the backlog requirement (R11 v3)."""
import re
from pathlib import Path

import pytest

from services.summary_prompts import COMPRESS_PROMPT, EXTRACT_PROMPT, SYSTEM_PROMPT


def _backlog_system_prompt() -> str:
    """Extract the verbatim prompt from plans/backlog.md Epic 28 (lines 1518-1540)."""
    lines = Path("plans/backlog.md").read_text(encoding="utf-8").splitlines()
    # Lines are 1-indexed: 1518..1540 (23 lines, R11 v3 — Epic 28)
    return "\n".join(lines[1517:1540])


def _arch_extract_prompt() -> str:
    """Extract the verbatim EXTRACT_PROMPT from plans/ARCHITECTURE.md Section 35.3."""
    lines = Path("plans/ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("EXTRACT_PROMPT = "))
    end = next(
        i for i, line in enumerate(lines[start:], start) if line.endswith('"""')
    )
    block = lines[start : end + 1]
    block[0] = block[0][len('EXTRACT_PROMPT = """'):]
    block[-1] = block[-1][:-3]
    return "\n".join(block)


EXPECTED_SYSTEM_PROMPT = _backlog_system_prompt()
EXPECTED_EXTRACT_PROMPT = _arch_extract_prompt()


class TestSystemPrompt:
    def test_system_prompt_byte_for_byte(self):
        """R11: the constant must match the backlog text EXACTLY."""
        assert SYSTEM_PROMPT == EXPECTED_SYSTEM_PROMPT

    def test_max_symbols_is_the_only_placeholder(self):
        """D72: unique placeholders are exactly {max_symbols, username} (3 brace pairs)."""
        placeholders = set(re.findall(r"\{(\w+)\}", SYSTEM_PROMPT))
        assert placeholders == {"max_symbols", "username"}

    def test_format_max_symbols(self):
        formatted = SYSTEM_PROMPT.replace("{max_symbols}", "3800")
        assert "3800 символов" in formatted
        assert "{max_symbols}" not in formatted
        assert "{username}" in formatted  # username stays literal for the LLM

    def test_shiz_marker_present(self):
        assert "самым главным шизом объявляется" in SYSTEM_PROMPT

    def test_rules_6_7_present(self):
        """T-217: правила 6 (имена/алиасы из author) и 7 (репосты) в v3."""
        assert "6. Имена участников:" in SYSTEM_PROMPT
        assert "7. Репосты:" in SYSTEM_PROMPT
        assert 'is_forward="true"' in SYSTEM_PROMPT
        assert "forward_source" in SYSTEM_PROMPT
        assert "имя участника из атрибута author" in SYSTEM_PROMPT


class TestCompressPrompt:
    def test_compress_prompt_not_empty(self):
        assert len(COMPRESS_PROMPT) > 50

    def test_compress_prompt_limits_facts(self):
        assert "не больше 10" in COMPRESS_PROMPT

    def test_compress_prompt_style(self):
        assert "с маленькой буквы" in COMPRESS_PROMPT
        assert "сжиматель истории чата" in COMPRESS_PROMPT


class TestExtractPrompt:
    """Epic 26 (T26.5-A): EXTRACT_PROMPT байт-в-байт = текст 35.3."""

    def test_extract_prompt_byte_for_byte(self):
        assert EXTRACT_PROMPT == EXPECTED_EXTRACT_PROMPT

    def test_extract_prompt_requires_json_array(self):
        assert "JSON-массива объектов" in EXTRACT_PROMPT
        assert "валидного JSON" in EXTRACT_PROMPT

    def test_extract_prompt_fields(self):
        for field in ("subject", "subject_type", "predicate", "object", "object_type"):
            assert field in EXTRACT_PROMPT
        assert "user или topic" in EXTRACT_PROMPT

    def test_system_and_compress_prompts_untouched(self):
        """Epic 26 не трогает SYSTEM_PROMPT/COMPRESS_PROMPT (R11)."""
        assert SYSTEM_PROMPT == EXPECTED_SYSTEM_PROMPT
        assert "не больше 10" in COMPRESS_PROMPT
