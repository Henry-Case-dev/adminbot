"""Tests for services/checkup_prompts.py (T-326-B, R42-6, Section 51.4).

Байт-в-байт с эталоном Section 51.4 (прецедент test_factcheck_prompts) +
кросс-проверка с планом backlog R42-6; {max_symbols} — единственный
плейсхолдер; .replace-подстановка без KeyError; CHECKUP_FALLBACK_NOTICE
дословно (R42-2).
"""
import re
from pathlib import Path

from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE, CHECKUP_SYSTEM_PROMPT


def _arch_checkup_prompt() -> str:
    """Эталон из plans/ARCHITECTURE.md Section 51.4 (эталон-блок)."""
    lines = Path("plans/ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("CHECKUP_SYSTEM_PROMPT = ")
    )
    end = next(
        i for i, line in enumerate(lines[start:], start) if line.endswith('"""')
    )
    block = lines[start : end + 1]
    block[0] = block[0][len('CHECKUP_SYSTEM_PROMPT = """'):]
    block[-1] = block[-1][:-3]
    return "\n".join(block)


def _backlog_r42_6_prompt() -> str:
    """Кросс-эталон: ячейка R42-6 плана (литеральные \\n → переносы строк)."""
    lines = Path("plans/backlog.md").read_text(encoding="utf-8").splitlines()
    line = next(l for l in lines if "| **R42-6** |" in l)
    payload = line.split("): `", 1)[1]
    assert payload.endswith("` |"), payload[-10:]
    return payload[:-3].replace("\\n", "\n")


EXPECTED_NOTICE = (
    "[СИСТЕМНОЕ УВЕДОМЛЕНИЕ: API Betterstack недоступно, предоставлены "
    "локальные логи сервера. Обязательно поиздевайся над тем, что облачный "
    "мониторинг сдох и пришлось лезть в локальную файловую помойку]"
)


class TestCheckupPrompt:
    def test_byte_for_byte_with_architecture(self):
        assert CHECKUP_SYSTEM_PROMPT == _arch_checkup_prompt()

    def test_byte_for_byte_with_backlog(self):
        assert CHECKUP_SYSTEM_PROMPT == _backlog_r42_6_prompt()

    def test_max_symbols_is_the_only_placeholder(self):
        placeholders = set(re.findall(r"\{(\w+)\}", CHECKUP_SYSTEM_PROMPT))
        assert placeholders == {"max_symbols"}
        assert CHECKUP_SYSTEM_PROMPT.count("{max_symbols}") == 1

    def test_replace_substitution(self):
        formatted = CHECKUP_SYSTEM_PROMPT.replace("{max_symbols}", "3000")
        assert "{max_symbols}" not in formatted
        assert formatted.endswith(
            "ОГРАНИЧЕНИЕ: длина ответа строго до 3000 символов."
        )

    def test_no_trailing_newline(self):
        assert not CHECKUP_SYSTEM_PROMPT.endswith("\n")

    def test_style_markers_from_tz(self):
        assert "токсичный, саркастичный DevOps-инженер" in CHECKUP_SYSTEM_PROMPT
        assert "Имитируй ленивую печать" in CHECKUP_SYSTEM_PROMPT
        assert "ЗАПРЕЩЕН любой маркдаун" in CHECKUP_SYSTEM_PROMPT
        assert (
            "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»)"
            in CHECKUP_SYSTEM_PROMPT
        )
        assert "переводи техническую инфу на человеческо-токсичный язык" in CHECKUP_SYSTEM_PROMPT


class TestFallbackNotice:
    def test_verbatim(self):
        assert CHECKUP_FALLBACK_NOTICE == EXPECTED_NOTICE

    def test_no_placeholder(self):
        assert "{max_symbols}" not in CHECKUP_FALLBACK_NOTICE
