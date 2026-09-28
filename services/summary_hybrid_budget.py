"""ASAP-2 round1027 (ADR-1027-10 D7, spec Q5/контракт (g)) — единая точка
бюджета контекста HYBRID-контура: ``limits.summary_hybrid_context_tokens``/
``_chars``.

Полное разделение (§11:2344–2356): Hybrid (упаковка L1 ``pack_l1_input``,
FactPackage-бюджет, S1/S2-фильтр в hybrid-режиме) читает ТОЛЬКО эти ключи;
Legacy — только старые ``limits.summary_max_context_*``. Hot-first
(PG-каталог → env ClassVar), масштаб дефолтов паритетен общим
(30000 токенов / 120000 симв.), но значения НЕ перетекают между контурами.

Формула входа (Q5):

    L1: available = safe_budget(hybrid_tokens) − tokens(L1 system prompt)
                        − marker_overhead(§93) − SUMMARY_L1_OUTPUT_RESERVE_TOKENS
    L2: package_budget = safe_budget(hybrid_tokens) − tokens(L2 system prompt)
                        − SUMMARY_L2_OUTPUT_RESERVE_TOKENS

margin = существующий ``models.token_safety_multiplier`` (~1.15, деление в
``safe_budget``) — НЕ 50 % окна (§11:2367–2368). chars-режим симметричен:
резервы/система пересчитываются в символы ×4. Output reserve — env-only
ClassVar (Δ каталога=0): инфраструктурная защита окна ответа.
"""
from __future__ import annotations

import logging

from config.settings import settings
from services.token_counter import (
    count_tokens,
    resolve_chat_limit,
    safe_budget,
)

logger = logging.getLogger(__name__)

MODULE = "summary"

# Дефолты паритетны общим ключам (§5.6/_SUMMARY_CONTEXT_TOKEN_DEFAULT=30000,
# SUMMARY_MAX_CONTEXT_CHARS=120000), но ключи независимы.
HYBRID_CONTEXT_TOKEN_DEFAULT = 30000
HYBRID_CONTEXT_CHARS_DEFAULT = 120000
# Символьный эквивалент токена для симметричного chars-режима (Q5: «резервы в
# символах ×4»).
CHARS_PER_TOKEN = 4


def resolve_hybrid_context_budget(*, hot_get=None,
                                  settings_obj=None) -> tuple[str, int]:
    """``(kind, limit)`` из ``limits.summary_hybrid_context_*`` (hot-first).

    Штатная семантика ``resolve_chat_limit`` (токенный приоритет +
    аварийный chars-fallback + sentinel-клампы). Никогда не бросает:
    любая ошибка резолва → дефолтный токенный бюджет.
    """
    if hot_get is None:
        from services import hot_config as hot
        hot_get = hot.get
    st = settings_obj or settings
    try:
        token_value = hot_get(
            "limits.summary_hybrid_context_tokens",
            getattr(st, "SUMMARY_HYBRID_CONTEXT_TOKENS", None))
        chars_value = hot_get(
            "limits.summary_hybrid_context_chars",
            getattr(st, "SUMMARY_HYBRID_CONTEXT_CHARS",
                    HYBRID_CONTEXT_CHARS_DEFAULT))
        return resolve_chat_limit(
            token_value, HYBRID_CONTEXT_TOKEN_DEFAULT,
            "SUMMARY_HYBRID_CONTEXT_CHARS", int(chars_value or 0),
            "SUMMARY_HYBRID")
    except Exception:  # pragma: no cover - защитная ветка (fail-closed дефолт)
        logger.warning("hybrid budget: resolve failed — default tokens",
                       exc_info=True)
        return ("tokens", HYBRID_CONTEXT_TOKEN_DEFAULT)


def hybrid_input_budget(kind: str, limit: int, *, system_text: str = "",
                        marker_overhead: int = 0,
                        output_reserve: int = 0) -> int:
    """Эффективный бюджет ВХОДА (Q5): safe-маржа − system − маркеры − резерв.

    ``kind``: ``tokens`` — все величины в токенах; ``chars`` — system/резерв
    пересчитываются из токенов в символы (×4), ``marker_overhead`` уже в
    символах. Результат клампится минимумом 1 (нулевой вход невозможен:
    run_l1/run_l2 не зовут LLM на пустом payload; отрицательный остаток —
    вырожденный конфиг, оставляем 1 без паники).
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return 0                       # «безлимита» здесь не бывает: resolve
    if kind == "tokens":
        available = safe_budget(limit)
        available -= int(count_tokens(system_text or ""))
        available -= int(marker_overhead or 0)
        available -= int(output_reserve or 0)
    else:
        # chars-режим симметрично: токенные компоненты ×4 в символы.
        scale = CHARS_PER_TOKEN
        available = limit
        available -= int(count_tokens(system_text or "")) * scale
        available -= int(marker_overhead or 0)
        available -= int(output_reserve or 0) * scale
    return max(1, available)


def hybrid_output_reserve_tokens(*, kind: str = "l1", settings_obj=None) -> int:
    """Output reserve env-слоя: L1 4000 / L2 6000 токенов (инфраструктурная
    защита окна ответа, Δ каталога=0)."""
    st = settings_obj or settings
    field = ("SUMMARY_L1_OUTPUT_RESERVE_TOKENS" if kind == "l1"
             else "SUMMARY_L2_OUTPUT_RESERVE_TOKENS")
    try:
        return max(0, int(getattr(st, field, 0)))
    except (TypeError, ValueError):  # pragma: no cover - защитная ветка
        return 0
