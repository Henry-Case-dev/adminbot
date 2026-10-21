# -*- coding: utf-8 -*-
"""FIX-CORRECTIVE-FOLLOWUP (21.10.2026, §1-2) — изоляция Expression.

Требование владельца: регулирование нецензурной лексики принадлежит ТОЛЬКО
слою ``<Expression_Settings>``. Personality Core (полная/компактная),
активные каноны Direct/Checkup/Summary/Factcheck/Search/Youtube/Web, канон
L1-планера и каноны ностальгии НЕ содержат инструкций о мате (разрешение/
запрет/частота/уместность/обязательность). Замороженные PREV/LEGACY-слепки
(источники лестницы миграций) сознательно НЕ проверяются — они вне
effective-слоя и нужны для распознавания прод-значений.

Директивы трёх режимов Expression зафиксированы байт-в-байт
(test_samples_fewshot::test_section2_texts_are_byte_exact).

TEST-LIFECYCLE: CONTRACT owner=FIX-CORRECTIVE-FOLLOWUP/Expression-isolation
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services import mca_expression as ex  # noqa: E402
from services import prompt_registry as pr  # noqa: E402
from services.chat_prompts import (  # noqa: E402
    CHAT_SYSTEM_PROMPT,
    DIRECT_L1_PLANNER_SYSTEM_PROMPT,
    DIRECT_VERBALIZER_SYSTEM_PROMPT,
    PERSONALITY_CORE_COMPACT_TEXT,
    PERSONALITY_CORE_FULL_TEXT,
)
from services.checkup_prompts import CHECKUP_SYSTEM_PROMPT  # noqa: E402
from services.factcheck_prompts import (  # noqa: E402
    FACTCHECK_SYSTEM_PROMPT,)
from services.nostalgia_prompts import (  # noqa: E402
    NOSTALGIA_CORE_CANON,
    NOSTALGIA_PROMPT,
)
from services.search_prompts import SEARCH_SYSTEM_PROMPT  # noqa: E402
from services.summary_prompts import SYSTEM_PROMPT  # noqa: E402
from services.web_prompts import WEBPAGE_SYSTEM_PROMPT  # noqa: E402
from services.youtube_prompts import (  # noqa: E402
    YOUTUBE_SYSTEM_PROMPT,
    YOUTUBE_VIDEO_SYSTEM_PROMPT,
)

#: Словесные формы мата (по границе слова: «форматный»/«материал» — нет).
_MAT_WORD_RE = re.compile(r"\bмат(а|у|е|ом|ов|ами|ах)?\b", re.IGNORECASE)

#: Явные мат-разрешения прежних канонов (не должны вернуться ни в каком виде).
_LEGACY_PERMISSIONS = (
    "Разрешен мат",
    "мат не вставляется насильно",
    "без мата» переопределяет",
)


def _active_speech_canons() -> dict[str, str]:
    """Активные пользовательские каноны (effective-слой, код-дефолты)."""
    canons: dict[str, str] = {
        "direct_chat": CHAT_SYSTEM_PROMPT,
        "direct_verbalizer": DIRECT_VERBALIZER_SYSTEM_PROMPT,
        "l1_planner": DIRECT_L1_PLANNER_SYSTEM_PROMPT,
        "checkup": CHECKUP_SYSTEM_PROMPT,
        "summary": SYSTEM_PROMPT,
        "factcheck": FACTCHECK_SYSTEM_PROMPT,
        "search": SEARCH_SYSTEM_PROMPT,
        "youtube": YOUTUBE_SYSTEM_PROMPT,
        "youtube_video": YOUTUBE_VIDEO_SYSTEM_PROMPT,
        "webpage": WEBPAGE_SYSTEM_PROMPT,
        "core_full": PERSONALITY_CORE_FULL_TEXT,
        "core_compact": PERSONALITY_CORE_COMPACT_TEXT,
        "nostalgia_prompt": NOSTALGIA_PROMPT,
        "nostalgia_core": NOSTALGIA_CORE_CANON,
        "expression_header": ex.EXPRESSION_HEADER,
    }
    return canons


def test_no_profanity_regulation_outside_expression():
    """В активных канонах нет ни слова о мате; правила частоты — только
    директивы Expression (тексты режимов проверены отдельно байт-в-байт)."""
    for name, text in _active_speech_canons().items():
        hit = _MAT_WORD_RE.search(text)
        assert hit is None, f"{name}: мат-регулирование вернулось: {hit.group(0)!r}"
        for legacy in _LEGACY_PERMISSIONS:
            assert legacy not in text, (name, legacy)


def test_expression_is_the_only_profanity_owner():
    """Единственный легальный носитель темы — слой Expression."""
    layer = ex.render_expression_text(
        ex.resolve_effective({"profanity": "frequent"}, None))
    assert _MAT_WORD_RE.search(layer) is not None  # директива на месте
    assert "Мат:" in layer
    # заводские значения остальных контролов не упоминают мат
    for control, modes in ex.CONTROL_INSTRUCTIONS.items():
        if control == "profanity":
            continue
        for instruction in modes.values():
            assert _MAT_WORD_RE.search(instruction) is None, control


def test_factory_texts_registered_set_has_no_mat_outside_expression():
    """Весь заводской набор реестра (factory_texts) чист от мат-регулирования.
    Исключения — МАШИННЫЕ стадии (речь не пишут; упоминание мата — граница
    юрисдикции/покрытия данных, не инструкция о речи):
      * ``memory.extract`` — JSON-экстрактор конфликтов («извлекай суть
        конфликтов даже если там мат» — покрытие данных, а не речь бота);
      * ``summary.recheck``-семантика живёт вне реестра, но аналогично:
        валидатору стилей предписано НЕ браковать мат (юрисдикция —
        Expression), это не мат-правило речи.
    Двойная проверка от «тихого» возврата темы в пользовательские каноны."""
    allowed_blocks = frozenset({"memory.extract"})
    for block_id, text in pr.factory_texts().items():
        if block_id in allowed_blocks:
            continue
        hit = _MAT_WORD_RE.search(text)
        assert hit is None, (block_id, hit.group(0) if hit else "")
        for legacy in _LEGACY_PERMISSIONS:
            assert legacy not in text, (block_id, legacy)


def test_fingerprint_constant_matches_recomputed_registry():
    """FACTORY_SET пересчитан после правки канонов (бампы задокументированы
    в prompt_registry: 037080375ac8 -> 21717a79dc67 -> 71c6a7b6c612 ->
    3e35aaa38e0c -> c19d35a1c093; итерации: Core/каноны речи, очистка
    search/youtube/web/summary/L2-writer/typography, канон ностальгии)."""
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12
    assert pr.FACTORY_SET_SHA256_12 == "c19d35a1c093"
