"""Tests for services/factcheck_prompts.py (Epic 68, T-535, D269).

Байт-в-байт с эталоном Section 72.1 (прецедент test_system_prompt_byte_for_byte);
{max_symbols} — единственный плейсхолдер; .replace-подстановка без KeyError.
"""
import re
from pathlib import Path

from services.factcheck_prompts import FACTCHECK_SYSTEM_PROMPT


def _arch_factcheck_prompt() -> str:
    """Эталон из plans/docs/canon/architecture.md (фенс-блок ```text после
    якоря «## Section 72» — ловушка «первого вхождения» D167; бывш. Section 72.1,
    Epic 68)."""
    lines = Path("plans/docs/canon/architecture.md").read_text(encoding="utf-8").splitlines()
    anchor = next(i for i, line in enumerate(lines) if line.startswith("## Section 72"))
    fence_start = next(
        i for i, line in enumerate(lines[anchor:], anchor)
        if line.strip() == "```text"
    )
    fence_end = next(
        i for i, line in enumerate(lines[fence_start + 1:], fence_start + 1)
        if line.strip() == "```"
    )
    return "\n".join(lines[fence_start + 1 : fence_end])


def _rag_instruction() -> str:
    """Канон R46-4 — инструкция (VERBATIM из plans/docs/canon/backlog.md, якорь
    «> «Если в блоке <bot_knowledge>», strip «> « и «»»)."""
    lines = Path("plans/docs/canon/backlog.md").read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.startswith("> «Если в блоке <bot_knowledge>"):
            return line[len("> «"):][:-1]
    raise AssertionError("канон R46-4 не найден в canon/backlog.md")


EXPECTED_PROMPT = _arch_factcheck_prompt()
RAG_INSTRUCTION = _rag_instruction()

# Epic 68 (D269, Section 72.1): блок «ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА» — дословно
# (дефисные/звёздочные маркеры сохраняются, осознанное решение D120).
_VOLUME_BLOCK = (
    "ОБЪЕМ И ДИНАМИЧЕСКИЙ РАЗМЕР ОТВЕТА:\n"
    "- Максимальный жесткий потолок: {max_symbols} символов.\n"
    "- Длину ответа определяй сам по сложности темы:\n"
    "  * Простой наброс или очевидный бред -> короткий язвительный ответ на 2-4 предложения (без размазывания соплей).\n"
    "  * Сложный философский спор или комплексный тейк -> подробный разбор на пару абзацев с железобетонной аргументацией.\n"
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

    def test_new_system_role_from_epic68(self):
        """Epic 68 (T-535): новая роль — третейский судья срачей."""
        assert "третейский судья в интернет-срачах" in FACTCHECK_SYSTEM_PROMPT
        assert "циничным арбитром в спорах" in FACTCHECK_SYSTEM_PROMPT

    def test_old_canon_removed(self):
        """Epic 68 (72.2): старый канон фактчекера удалён."""
        assert "объективно проверить достоверность" not in FACTCHECK_SYSTEM_PROMPT
        assert "фейк, правда, полуправда" not in FACTCHECK_SYSTEM_PROMPT
        assert "бот-абьюзер" not in FACTCHECK_SYSTEM_PROMPT
        assert "СУТЬ АНАЛИЗА:" not in FACTCHECK_SYSTEM_PROMPT

    def test_analysis_block_verbatim(self):
        """Epic 68 (72.1): блок «СУТЬ АНАЛИЗА (СУДЕЙСТВО СРАЧЕЙ)» и его пункты."""
        assert "СУТЬ АНАЛИЗА (СУДЕЙСТВО СРАЧЕЙ):" in FACTCHECK_SYSTEM_PROMPT
        for marker in (
            "- Принятие тейка:",
            "- Анализ тезиса и логики:",
            "- Умная фильтрация интернета (КРИТИЧНО):",
            "- Вердикт:",
            "- Аргументация:",
        ):
            assert marker in FACTCHECK_SYSTEM_PROMPT
        assert "признай утверждение \"базой\"" in FACTCHECK_SYSTEM_PROMPT
        assert "жидко обосрался" in FACTCHECK_SYSTEM_PROMPT

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
