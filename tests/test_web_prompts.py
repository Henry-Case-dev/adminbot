"""Tests for services/web_prompts.py (T-289, R37-6, D132, Section 46.7.2/46.12).

Байт-в-байт с эталоном Section 46.7.2 (прецедент test_factcheck_prompts.py);
{max_symbols} — единственный плейсхолдер; .replace-подстановка без KeyError.
Раунд 5 (T-738): п.1 → «торопливое письмо»; PREV-слепок HEAD 68fb03e
(spec 5.3.2); запрещённые старые фразы отсутствуют (5.3.4).
"""
import re
from pathlib import Path

from services.web_prompts import PREV_WEBPAGE_SYSTEM_PROMPT, WEBPAGE_SYSTEM_PROMPT


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
        assert "Имитируй торопливое письмо" in WEBPAGE_SYSTEM_PROMPT
        assert "ЗАПРЕЩЕН любой маркдаун" in WEBPAGE_SYSTEM_PROMPT
        assert "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и кавычки-елочки («»)" in WEBPAGE_SYSTEM_PROMPT
        assert "сплошной текст с разделением на абзацы" in WEBPAGE_SYSTEM_PROMPT
        assert "выжимку содержимого веб-страницы" in WEBPAGE_SYSTEM_PROMPT
        assert "Саркастично оцени полезность материала" in WEBPAGE_SYSTEM_PROMPT

    def test_round5_casing_and_typography(self):
        """Раунд 5 (T-738): п.1 «торопливое письмо»; старые формулировки
        отсутствуют (spec 5.3.4)."""
        assert ("1. Имитируй торопливое письмо: иногда начинай предложения "
                "с маленькой буквы. Пиши небрежно." in WEBPAGE_SYSTEM_PROMPT)
        assert "Имитируй ленивую печать" not in WEBPAGE_SYSTEM_PROMPT
        assert "чередуй заглавные и строчные" not in WEBPAGE_SYSTEM_PROMPT

    def test_prev_snapshot_is_before_round5(self):
        """PREV-слепок == HEAD 68fb03e (spec 5.3.2)."""
        assert PREV_WEBPAGE_SYSTEM_PROMPT != WEBPAGE_SYSTEM_PROMPT
        assert ("1. Имитируй ленивую печать: чередуй заглавные и строчные "
                "буквы в начале предложений. Пиши небрежно."
                in PREV_WEBPAGE_SYSTEM_PROMPT)
        assert "Имитируй торопливое письмо" not in PREV_WEBPAGE_SYSTEM_PROMPT

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
