"""Tests for services/factcheck_prompts.py (T-255-B, R33-6, D109 RESOLVED).

Байт-в-байт с эталоном Section 42.5.1 (прецедент test_system_prompt_byte_for_byte);
{max_symbols} — единственный плейсхолдер; .replace-подстановка без KeyError.
"""
import re
from pathlib import Path

from services.factcheck_prompts import FACTCHECK_SYSTEM_PROMPT


def _arch_factcheck_prompt() -> str:
    """Эталон из plans/ARCHITECTURE.md Section 55.7.3 (эталон-блок; якорь
    «## Section 55:» — ловушка «первого вхождения» D167)."""
    lines = Path("plans/ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
    anchor = next(i for i, line in enumerate(lines) if line.startswith("## Section 55:"))
    start = next(
        i for i, line in enumerate(lines[anchor:], anchor)
        if line.startswith("FACTCHECK_SYSTEM_PROMPT = ")
    )
    end = next(
        i for i, line in enumerate(lines[start:], start) if line.endswith('"""')
    )
    block = lines[start : end + 1]
    block[0] = block[0][len('FACTCHECK_SYSTEM_PROMPT = """'):]
    block[-1] = block[-1][:-3]
    return "\n".join(block)


def _rag_instruction() -> str:
    """Канон R46-4 — инструкция (VERBATIM из backlog, якорь «> «Если в блоке
    <bot_knowledge>», strip «> « и «»»)."""
    lines = Path("plans/backlog.md").read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.startswith("> «Если в блоке <bot_knowledge>"):
            return line[len("> «"):][:-1]
    raise AssertionError("канон R46-4 не найден в backlog")


EXPECTED_PROMPT = _arch_factcheck_prompt()
RAG_INSTRUCTION = _rag_instruction()

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


class TestFactcheckPrompt:
    def test_byte_for_byte(self):
        assert FACTCHECK_SYSTEM_PROMPT == EXPECTED_PROMPT

    def test_max_symbols_is_the_only_placeholder(self):
        placeholders = set(re.findall(r"\{(\w+)\}", FACTCHECK_SYSTEM_PROMPT))
        assert placeholders == {"max_symbols"}
        assert FACTCHECK_SYSTEM_PROMPT.count("{max_symbols}") == 1

    def test_replace_substitution(self):
        formatted = FACTCHECK_SYSTEM_PROMPT.replace("{max_symbols}", "4000")
        assert "{max_symbols}" not in formatted
        assert "Максимальный жесткий потолок: 4000 символов." in formatted

    def test_volume_block_verbatim(self):
        """R36-2 (D120): блок «ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА» дословно,
        жёсткая строка «строго до» удалена."""
        assert _VOLUME_BLOCK in FACTCHECK_SYSTEM_PROMPT
        assert "ОГРАНИЧЕНИЕ: длина ответа строго до" not in FACTCHECK_SYSTEM_PROMPT

    def test_style_markers_from_tz(self):
        """R33-6: токсичный фактчекер, ленивая печать, запреты маркдауна/тире/ёлочек."""
        assert "токсичный, ироничный фактчекер" in FACTCHECK_SYSTEM_PROMPT
        assert "Имитируй ленивую печать" in FACTCHECK_SYSTEM_PROMPT
        assert "ЗАПРЕЩЕН любой маркдаун" in FACTCHECK_SYSTEM_PROMPT
        assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»)" in FACTCHECK_SYSTEM_PROMPT
        assert "сплошной текст с разделением на абзацы" in FACTCHECK_SYSTEM_PROMPT

    def test_ends_with_rag_instruction(self):
        """55.7.3: канон-инструкция R46-4 — последний абзац промпта."""
        assert FACTCHECK_SYSTEM_PROMPT.endswith(RAG_INSTRUCTION)

    def test_rag_instruction_canon_verbatim(self):
        """Канон R46-4 — инструкция ДОСЛОВНО из backlog."""
        assert RAG_INSTRUCTION == (
            "Если в блоке <bot_knowledge> есть информация по текущей теме, "
            "используй её, чтобы унизить оппонента своими знаниями. Дай понять, "
            "что ты уже проверял эту инфу ранее или смотрел ролик на эту тему, "
            "и тебе не нужно повторять дважды."
        )
        assert "<bot_knowledge>" in FACTCHECK_SYSTEM_PROMPT
