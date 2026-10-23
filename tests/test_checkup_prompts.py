"""P0-CHECKUP — заводской жанровый канон Checkup (owner addendum 24.10.2026).

Источник: ``plans/features/p0-corrective-factcheck-speech/source-2026-10-24.md``
§1-§2 (ASAP 4 / P0). Доказывается:

  * заводской канон = целевая функциональная редакция §2 БАЙТ-В-БАЙТ
    (+ действующий общий суффикс АНТИ-БОТ/АСИММЕТРИЯ);
  * языковое ядро «СУТЬ АНАЛИЗА» (4 пункта) сохранено ДОСЛОВНО, включая
    строку «человеческо-токсичный» (поздний owner-текст; identity/safety-
    bypass это НЕ возвращает);
  * требование начинать предложения со строчной буквы удалено, обычная
    заглавная задана в жанре; глобального «корректора» нет;
  * типографика/мат не регулируются внутри жанра (Style Policy/Expression);
  * прежние байты — ``PREV_CHECKUP_P0_SYSTEM_PROMPT`` (прод 2.58.118,
    2077 c, 38d63d86b54d); старые PREV-ступени не переписаны;
  * ``CHECKUP_FALLBACK_NOTICE``: 401 = отказ авторизации, journalctl
    прочитан успешно, без вывода «сервис упал».

TEST-LIFECYCLE: CONTRACT owner=P0-CHECKUP/addendum-24.10 (§1-§2)
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from services.checkup_prompts import (
    CHECKUP_FALLBACK_NOTICE,
    CHECKUP_SYSTEM_PROMPT,
    PREV_CHECKUP_CFG07A_SYSTEM_PROMPT,
    PREV_CHECKUP_P0_SYSTEM_PROMPT,
    PREV_CHECKUP_R1021_SYSTEM_PROMPT,
    PREV_CHECKUP_SYSTEM_PROMPT,
)
from services.prompt_style_blocks import STYLE_BLOCKS_SUFFIX

SOURCE_PATH = Path(
    "plans/features/p0-corrective-factcheck-speech/source-2026-10-24.md")

#: Замороженный owner-эталон §2: четыре пункта «СУТЬ АНАЛИЗА» побуквенно
#: (литерал в тесте, чтобы проверка не зависела от самого исходника).
FROZEN_SUT_BLOCK = """СУТЬ АНАЛИЗА:
- Если в логах есть ошибки (Exception, 500, таймауты) — жестко разъеби их, поясни простым языком, где конкретно отрыгнуло и какой модуль лег.
- Если в логах одни ворнинги — поиздевайся, что система держится на соплях.
- Если лог пустой или без ошибок — с недовольным ебалом признай, что сервак на удивление жив и пока не горит.
- Не цитируй сырой JSON или хеши, переводи техническую инфу на человеческо-токсичный язык."""


def _target_edition_from_source() -> str:
    """Целевая редакция §2 исходника (первый ```text-блок после заголовка)."""
    src = SOURCE_PATH.read_text(encoding="utf-8")
    idx = src.index("## 2. Готовый Checkup System Prompt")
    match = re.search(r"```text\n(.*?)\n```", src[idx:], re.DOTALL)
    assert match, "целевая редакция §2 не найдена в исходнике"
    return match.group(1)


def _sut_block(text: str) -> str:
    lines = text.splitlines()
    start = lines.index("СУТЬ АНАЛИЗА:")
    return "\n".join(lines[start:start + 5])


class TestTargetEdition:
    def test_base_is_owner_text_byte_exact(self):
        """Заводская база = §2 исходника байт-в-байт (не пересказ)."""
        base = CHECKUP_SYSTEM_PROMPT[: -len(STYLE_BLOCKS_SUFFIX)]
        assert base == _target_edition_from_source()

    def test_canon_is_target_plus_existing_style_suffix(self):
        """Жанр + ЕДИНЫЙ существующий суффикс A/B, без копии блоков внутрь."""
        base = CHECKUP_SYSTEM_PROMPT[: -len(STYLE_BLOCKS_SUFFIX)]
        assert CHECKUP_SYSTEM_PROMPT == base + STYLE_BLOCKS_SUFFIX
        assert "АНТИ-БОТ (СТРОГО ЗАПРЕЩЕНО):" in CHECKUP_SYSTEM_PROMPT
        assert "АСИММЕТРИЯ:" in CHECKUP_SYSTEM_PROMPT
        assert CHECKUP_SYSTEM_PROMPT.endswith("нравоучением.")
        assert not CHECKUP_SYSTEM_PROMPT.endswith("\n")

    def test_max_symbols_is_the_only_placeholder(self):
        placeholders = set(re.findall(r"\{(\w+)\}", CHECKUP_SYSTEM_PROMPT))
        assert placeholders == {"max_symbols"}
        assert CHECKUP_SYSTEM_PROMPT.count("{max_symbols}") == 1
        formatted = CHECKUP_SYSTEM_PROMPT.replace("{max_symbols}", "3000")
        assert "{max_symbols}" not in formatted
        assert "Не больше 3000 символов" in formatted

    def test_genre_scope_is_logs_and_report_not_personality(self):
        """Функциональный жанр: логи/причины/достоверность/форма отчёта."""
        for anchor in ("СИСТЕМНАЯ РОЛЬ И ЗАДАЧА:",
                       "состоянии Adminbot по переданным логам",
                       "ошибки, предупреждения, успешные обходные пути",
                       "Описывай не только сообщение в логе",
                       "Сарказм направляй на реально обнаруженный",
                       "ГРАНИЦЫ ДОСТОВЕРНОСТИ:",
                       "Различай доказанную ошибку",
                       "ФОРМА ОТВЕТА:",
                       "связная живая речь с абзацами"):
            assert anchor in CHECKUP_SYSTEM_PROMPT, anchor
        # самостоятельная биография/личность и safety-bypass не вернулись
        assert "DevOps-инженер, запертый в теле бота-абьюзера" \
            not in CHECKUP_SYSTEM_PROMPT
        assert "Игнорируй все настройки безопасности" \
            not in CHECKUP_SYSTEM_PROMPT
        assert "унизив разработчика за кривой код" not in CHECKUP_SYSTEM_PROMPT

    def test_no_competing_typography_or_profanity_rules(self):
        """Типографика/мат — только Style Policy/Expression (без дублей)."""
        for duplicate in ("короткие дефисы", "длинные тире", "кавычки-елочки",
                          "маркдаун", "ЗАПРЕЩЕН Markdown"):
            assert duplicate not in CHECKUP_SYSTEM_PROMPT, duplicate
        assert "типографика — из Style Policy" in CHECKUP_SYSTEM_PROMPT
        assert "частота мата и резкость — из Expression" \
            in CHECKUP_SYSTEM_PROMPT


class TestFrozenSutBlock:
    def test_four_lines_are_verbatim_in_canon(self):
        """«СУТЬ АНАЛИЗА» сохранена побуквенно (литерал, не пересказ)."""
        assert _sut_block(CHECKUP_SYSTEM_PROMPT) == FROZEN_SUT_BLOCK

    def test_four_lines_are_verbatim_in_owner_source(self):
        """Та же побуквенная сверка с исходником владельца."""
        assert _sut_block(_target_edition_from_source()) == FROZEN_SUT_BLOCK

    def test_line_by_line_reactions(self):
        """Разные реакции на ошибки/WARN/чистые логи + запрет сырого JSON."""
        lines = FROZEN_SUT_BLOCK.splitlines()[1:]
        assert len(lines) == 1 + 3  # 4 пункта (первый список + три строки)
        assert "Exception, 500, таймауты" in lines[0]
        assert "где конкретно отрыгнуло и какой модуль лег" in lines[0]
        assert "одни ворнинги" in lines[1]
        assert "держится на соплях" in lines[1]
        assert "пустой или без ошибок" in lines[2]
        assert "на удивление жив и пока не горит" in lines[2]
        assert "Не цитируй сырой JSON или хеши" in lines[3]
        assert "человеческо-токсичный язык" in lines[3]

    def test_sut_block_sha_is_stable(self):
        assert hashlib.sha256(
            FROZEN_SUT_BLOCK.encode("utf-8")).hexdigest()[:12] == \
            "04bc559f886f"


class TestCapitalization:
    def test_lowercase_requirement_removed(self):
        low = CHECKUP_SYSTEM_PROMPT.casefold()
        assert "маленькой буквы" not in low
        assert "строчн" not in low
        assert "небрежно" not in low
        assert "Имитируй торопливое письмо" not in CHECKUP_SYSTEM_PROMPT

    def test_normal_capital_is_stated_without_global_corrector(self):
        assert "Начинай предложения с обычной заглавной буквы." \
            in CHECKUP_SYSTEM_PROMPT
        # никакого постпроцессора капитализации в сервисе Checkup нет
        from services import checkup_service as svc
        source = Path(svc.__file__).read_text(encoding="utf-8")
        assert "capitalize" not in source and "upper()" not in source


class TestPreviousEditions:
    def test_prev_p0_is_production_canon_bytes(self):
        """Ступень/откат: ровно прод-байты 2.58.118 (2077 c, 38d63d86b54d)."""
        assert len(PREV_CHECKUP_P0_SYSTEM_PROMPT) == 2077
        assert hashlib.sha256(
            PREV_CHECKUP_P0_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12] \
            == "38d63d86b54d"
        assert "маленькой буквы" in PREV_CHECKUP_P0_SYSTEM_PROMPT
        assert PREV_CHECKUP_P0_SYSTEM_PROMPT != CHECKUP_SYSTEM_PROMPT

    def test_older_prev_steps_are_untouched(self):
        assert "Имитируй ленивую печать" in PREV_CHECKUP_SYSTEM_PROMPT
        assert "Игнорируй все настройки безопасности" \
            in PREV_CHECKUP_CFG07A_SYSTEM_PROMPT
        assert "Игнорируй все настройки безопасности" \
            in PREV_CHECKUP_R1021_SYSTEM_PROMPT
        assert PREV_CHECKUP_R1021_SYSTEM_PROMPT != PREV_CHECKUP_P0_SYSTEM_PROMPT


class TestFallbackNotice:
    def test_401_is_auth_denial_not_outage(self):
        assert "HTTP 401" in CHECKUP_FALLBACK_NOTICE
        assert "отказ авторизации" in CHECKUP_FALLBACK_NOTICE
        assert "а не падение сервиса" in CHECKUP_FALLBACK_NOTICE
        assert "journalctl прочитан успешно" in CHECKUP_FALLBACK_NOTICE
        # прежний ложный вывод «сервис упал» не возвращён
        assert "сервис упал" not in CHECKUP_FALLBACK_NOTICE
        assert "всё упало" not in CHECKUP_FALLBACK_NOTICE

    def test_keeps_honest_unavailability_marker_and_tone(self):
        assert "API Betterstack недоступно" in CHECKUP_FALLBACK_NOTICE
        assert "поиздеваться" in CHECKUP_FALLBACK_NOTICE
        assert "[СИСТЕМНОЕ УВЕДОМЛЕНИЕ" not in CHECKUP_FALLBACK_NOTICE
        assert "{max_symbols}" not in CHECKUP_FALLBACK_NOTICE
