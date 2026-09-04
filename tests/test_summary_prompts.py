"""T-182-A / T-217-B / T-223-D / T-230 / T-365-B: SYSTEM_PROMPT byte-for-byte
against the backlog requirement (R11 v4 + канон-инструкция R46-4, 55.7.1).
Раунд 5 (T-736): п.1 «торопливое письмо» + п.7 TYPO; PREV-слепки HEAD 68fb03e
(spec 5.3.2); запрещённые старые фразы отсутствуют (5.3.4); COMPRESS — тот же
фрагмент-клауза в нижнем регистре.
"""
import re
from pathlib import Path

import pytest

from services.summary_prompts import (
    COMPRESS_PROMPT,
    EXTRACT_PROMPT,
    PREV_COMPRESS_PROMPT,
    PREV_SUMMARY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)


def _backlog_system_prompt() -> str:
    """Extract the verbatim prompt from plans/docs/canon/backlog.md
    (блок R11, бывш. backlog.md 1518–1539; якорь «### Системный промпт (R11»)."""
    lines = Path("plans/docs/canon/backlog.md").read_text(encoding="utf-8").splitlines()
    header = next(i for i, line in enumerate(lines)
                  if line.startswith("### Системный промпт (R11"))
    fence = next(i for i, line in enumerate(lines[header:], header)
                 if line.strip() == "```")
    end = next(i for i, line in enumerate(lines[fence + 1:], fence + 1)
               if line.strip() == "```")
    return "\n".join(lines[fence + 1:end])


def _rag_instruction() -> str:
    """Канон R46-4 — инструкция (VERBATIM из plans/docs/canon/backlog.md, якорь
    «> «Если в блоке <bot_knowledge>», strip «> « и «»»)."""
    lines = Path("plans/docs/canon/backlog.md").read_text(encoding="utf-8").splitlines()
    for line in lines:
        if line.startswith("> «Если в блоке <bot_knowledge>"):
            return line[len("> «"):][:-1]
    raise AssertionError("канон R46-4 не найден в canon/backlog.md")


def _arch_extract_prompt() -> str:
    """Extract the verbatim EXTRACT_PROMPT from plans/docs/canon/architecture.md
    (блок EXTRACT_PROMPT, бывш. Section 35.3)."""
    lines = Path("plans/docs/canon/architecture.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("EXTRACT_PROMPT = "))
    end = next(
        i for i, line in enumerate(lines[start:], start) if line.endswith('"""')
    )
    block = lines[start : end + 1]
    block[0] = block[0][len('EXTRACT_PROMPT = """'):]
    block[-1] = block[-1][:-3]
    return "\n".join(block)


RAG_INSTRUCTION = _rag_instruction()
EXPECTED_SYSTEM_PROMPT = _backlog_system_prompt() + "\n\n" + RAG_INSTRUCTION
EXPECTED_EXTRACT_PROMPT = _arch_extract_prompt()


class TestSystemPrompt:
    def test_system_prompt_byte_for_byte(self):
        """R11: the constant must match the backlog text EXACTLY."""
        assert SYSTEM_PROMPT == EXPECTED_SYSTEM_PROMPT

    def test_system_prompt_ends_with_rag_instruction(self):
        """55.7.1: канон-инструкция R46-4 — последний абзац промпта (через \n\n)."""
        assert SYSTEM_PROMPT.endswith(RAG_INSTRUCTION)
        assert SYSTEM_PROMPT.endswith(
            "\n\n" + RAG_INSTRUCTION
        )

    def test_rag_instruction_canon_verbatim(self):
        """Канон R46-4 — инструкция ДОСЛОВНО из backlog (якорь «> «Если в блоке»)."""
        assert RAG_INSTRUCTION == (
            "Если в блоке <bot_knowledge> есть информация по текущей теме, "
            "используй её, чтобы унизить оппонента своими знаниями. Дай понять, "
            "что ты уже проверял эту инфу ранее или смотрел ролик на эту тему, "
            "и тебе не нужно повторять дважды."
        )
        assert "<bot_knowledge>" in SYSTEM_PROMPT

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

    def test_rules_5_6_present(self):
        """T-217/T-223/T-230: правила 5 (имена/алиасы из author) и 6 (репосты) живы в v4 (нумерация 1–7, D90 + раунд 5)."""
        assert "5. Имена участников:" in SYSTEM_PROMPT
        assert "6. Репосты:" in SYSTEM_PROMPT
        assert 'is_forward="true"' in SYSTEM_PROMPT
        assert "forward_source" in SYSTEM_PROMPT
        assert "используй СТРОГО дословное значение из атрибута author" in SYSTEM_PROMPT

    def test_rule_3_typography_removed(self):
        """D84: пункт 3 (типографика) удалён — её чинит cleanup_llm_text (37.6)."""
        assert "3. Типографика" not in SYSTEM_PROMPT

    def test_canon_point_5_markers(self):
        """D83: маркеры канона пользователя (пункт 5 — имена участников, v4)."""
        assert "чел с пейзажем в нике" in SYSTEM_PROMPT
        assert "склоняй его как обычно" in SYSTEM_PROMPT

    def test_numbering_sequential(self):
        """D90/T-230 + раунд 5 (T-736): последовательная нумерация 1–7
        (п.7 — типографика, следующий свободный номер без перенумерации)."""
        assert "1. Имитируй торопливое письмо:" in SYSTEM_PROMPT
        assert "2. Пунктуация:" in SYSTEM_PROMPT
        assert "3. Ограничения форматов" in SYSTEM_PROMPT
        assert "4. Структура:" in SYSTEM_PROMPT
        assert "5. Имена участников:" in SYSTEM_PROMPT
        assert "6. Репосты:" in SYSTEM_PROMPT
        assert "7. Типографика:" in SYSTEM_PROMPT
        # В блоке ПРАВИЛ пункта 8 больше нет
        assert "8. " not in SYSTEM_PROMPT.split("ЗАДАЧА:")[0]

    def test_round5_typo_and_casing(self):
        """Раунд 5 (T-736): п.7 TYPO (полная эталонная строка) + п.1
        «торопливое письмо»; старые формулировки отсутствуют (5.3.4)."""
        assert ("7. Типографика: только короткие дефисы (-) и обычные двойные "
                'кавычки (""). КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ длинные тире (—) и '
                "кавычки-елочки («»)." in SYSTEM_PROMPT)
        assert ("1. Имитируй торопливое письмо: иногда начинай предложения "
                "с маленькой буквы. Текст должен быть читаемым, но выглядеть "
                "небрежно." in SYSTEM_PROMPT)
        assert "чередуй заглавные и строчные" not in SYSTEM_PROMPT
        assert "Не пиши всё только с маленькой буквы" not in SYSTEM_PROMPT

    def test_prev_snapshots_are_before_round5(self):
        """PREV-слепки == HEAD 68fb03e (spec 5.3.2): старые фразы есть,
        новый канон от них отличается."""
        assert PREV_SUMMARY_SYSTEM_PROMPT != SYSTEM_PROMPT
        assert ("Имитируй ленивую печать: чередуй заглавные и строчные буквы "
                "в начале предложений случайным образом" in
                PREV_SUMMARY_SYSTEM_PROMPT)
        assert "Не пиши всё только с маленькой буквы" in PREV_SUMMARY_SYSTEM_PROMPT
        assert "7. Типографика:" not in PREV_SUMMARY_SYSTEM_PROMPT
        assert PREV_COMPRESS_PROMPT != COMPRESS_PROMPT
        assert "пиши с маленькой буквы." in PREV_COMPRESS_PROMPT


class TestCompressPrompt:
    def test_compress_prompt_not_empty(self):
        assert len(COMPRESS_PROMPT) > 50

    def test_compress_prompt_limits_facts(self):
        assert "не больше 10" in COMPRESS_PROMPT

    def test_compress_prompt_style(self):
        assert "с маленькой буквы" in COMPRESS_PROMPT
        assert "сжиматель истории чата" in COMPRESS_PROMPT

    def test_round5_typo_and_casing(self):
        """Раунд 5 (T-736): TYPO-клауза и «торопливое письмо» в нижнем
        регистре; старая строгая фраза «пиши с маленькой буквы» исчезла."""
        assert ("не используй нумерацию, маркдаун, смайлы, кавычки-елочки («»)"
                " и длинные тире (—)." in COMPRESS_PROMPT)
        assert ("иногда начинай предложения с маленькой буквы, имитируя "
                "торопливое письмо." in COMPRESS_PROMPT)
        assert "пиши с маленькой буквы" not in COMPRESS_PROMPT


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
