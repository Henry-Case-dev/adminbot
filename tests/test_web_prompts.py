"""Tests for services/web_prompts.py (T-289, R37-6, D132, Section 46.7.2/46.12).

Байт-в-байт с эталоном Section 46.7.2 (прецедент test_factcheck_prompts.py);
{max_symbols} — единственный плейсхолдер; .replace-подстановка без KeyError.
"""
import re
from pathlib import Path

from services.web_prompts import WEBPAGE_SYSTEM_PROMPT


def _arch_web_prompt() -> str:
    """Эталон из plans/docs/canon/architecture.md (блок WEBPAGE_SYSTEM_PROMPT после
    якоря «## Section 55:» — ловушка «первого вхождения» D167; бывш. Section 55.7.5)."""
    lines = Path("plans/docs/canon/architecture.md").read_text(encoding="utf-8").splitlines()
    anchor = next(i for i, line in enumerate(lines) if line.startswith("## Section 55:"))
    start = next(
        i for i, line in enumerate(lines[anchor:], anchor)
        if line.startswith("WEBPAGE_SYSTEM_PROMPT = ")
    )
    end = next(
        i for i, line in enumerate(lines[start:], start) if line.endswith('"""')
    )
    block = lines[start : end + 1]
    block[0] = block[0][len('WEBPAGE_SYSTEM_PROMPT = """'):]
    block[-1] = block[-1][:-3]
    return "\n".join(block)


def _rag_instruction() -> str:
    """Канон R46-4 — инструкция (VERBATIM из plans/docs/canon/backlog.md, якорь
    «> «Если в блоке <bot_knowledge>», strip «> « и «»»)."""
    lines = Path("plans/docs/canon/backlog.md").read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.startswith("> «Если в блоке <bot_knowledge>"):
            return line[len("> «"):][:-1]
    raise AssertionError("канон R46-4 не найден в canon/backlog.md")


EXPECTED_PROMPT = _arch_web_prompt()
RAG_INSTRUCTION = _rag_instruction()


class TestWebpagePrompt:
    def test_byte_for_byte(self):
        assert WEBPAGE_SYSTEM_PROMPT == EXPECTED_PROMPT

    def test_max_symbols_is_the_only_placeholder(self):
        placeholders = set(re.findall(r"\{(\w+)\}", WEBPAGE_SYSTEM_PROMPT))
        assert placeholders == {"max_symbols"}
        assert WEBPAGE_SYSTEM_PROMPT.count("{max_symbols}") == 1

    def test_replace_substitution(self):
        formatted = WEBPAGE_SYSTEM_PROMPT.replace("{max_symbols}", "4000")
        assert "{max_symbols}" not in formatted
        assert "длина ответа строго до 4000 символов" in formatted

    def test_style_markers_from_tz(self):
        """R37-6: токсичный ироничный участник чата, ленивая печать,
        запреты маркдауна/тире/ёлочек."""
        assert "токсичный, ироничный участник чата" in WEBPAGE_SYSTEM_PROMPT
        assert "Имитируй ленивую печать" in WEBPAGE_SYSTEM_PROMPT
        assert "ЗАПРЕЩЕН любой маркдаун" in WEBPAGE_SYSTEM_PROMPT
        assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»)" in WEBPAGE_SYSTEM_PROMPT
        assert "сплошной текст с разделением на абзацы" in WEBPAGE_SYSTEM_PROMPT
        assert "выжимку содержимого веб-страницы" in WEBPAGE_SYSTEM_PROMPT
        assert "Саркастично оцени полезность материала" in WEBPAGE_SYSTEM_PROMPT

    def test_ends_with_rag_instruction(self):
        """55.7.5: канон-инструкция R46-4 — последний абзац промпта."""
        assert WEBPAGE_SYSTEM_PROMPT.endswith(RAG_INSTRUCTION)

    def test_rag_instruction_canon_verbatim(self):
        """Канон R46-4 — инструкция ДОСЛОВНО из backlog."""
        assert RAG_INSTRUCTION == (
            "Если в блоке <bot_knowledge> есть информация по текущей теме, "
            "используй её, чтобы унизить оппонента своими знаниями. Дай понять, "
            "что ты уже проверял эту инфу ранее или смотрел ролик на эту тему, "
            "и тебе не нужно повторять дважды."
        )
        assert "<bot_knowledge>" in WEBPAGE_SYSTEM_PROMPT
