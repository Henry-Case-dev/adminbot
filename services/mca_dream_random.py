"""mca-06 (ADR-1028-9 AM-2, spec §8.7) — T-4730: источник случайного выбора
материала для исследования менее изученных периодов глубокого сна.

Контракт узкий (стык с mca-10a Wave 3, БЕЗ fork):
    `pick(candidates, *, chat_id, purpose, k) -> (items, selection_meta)`

Инварианты (THR-9, spec §8.7):
  * случайность выбирает ТОЛЬКО материал/период; вердикт (written/
    insufficient_evidence/…) определяется исключительно доказательствами §5.3
    и НЕ зависит от выбора;
  * реализация по умолчанию — детерминированная равномерная (`random.Random`,
    seed = `(pipeline_run_id, chat_id)`) → воспроизводимость отчёта;
  * выборка (`selection_meta`) пишется в отчёт прогона §7.2 (R17-safe: только
    seed/счётчики/индексы, без сырого текста).

Kill-switch `MCA_DREAM_RANDOM_EXPLORE_ENABLED` (env-only, default ON):
OFF → выбор не вызывается, работает прежний ранжированный топ-k (бит-в-бит
2.58.48). Гейт проверяет вызывающий (dream_worker), модуль чистый.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Назначения выбора (узкий словарь; mca-10a может добавлять свои имена, не
# переписывая пайплайн).
PURPOSE_LESS_STUDIED = "less_studied_periods"

# Потолок хранимого в selection_meta списка индексов (bounded; R17-safe).
_SELECTION_META_CAP = 200


@runtime_checkable
class DreamRandomSource(Protocol):
    """Интерфейс выбора материала (AM-2). Реализуется core-источником mca-10a
    без переписывания пайплайна (не fork)."""

    def pick(self, candidates, *, chat_id, purpose: str, k: int
             ) -> tuple[list, dict]:  # pragma: no cover - протокол
        ...


@dataclass
class DeterministicUniformRandomSource:
    """Дефолтный источник: детерминированный равномерный выбор `k` из пула.

    seed = `(pipeline_run_id, chat_id)` (spec §8.7). Одинаковый seed →
    одинаковый выбор (`selection_meta` воспроизводим). Случайность здесь НЕ
    влияет на вердикт — downstream валидатор §5.3 работает по доказательствам.
    """

    pipeline_run_id: int | None = None

    def pick(self, candidates, *, chat_id, purpose: str, k: int
             ) -> tuple[list, dict]:
        pool = list(candidates or [])
        k = max(0, min(int(k), len(pool)))
        run_id = int(self.pipeline_run_id or 0)
        # seed = (pipeline_run_id, chat_id); `random.Random` принимает
        # int/str/bytes (с 3.11 кортеж не принимается) — стабильная строка.
        seed = f"{run_id}:{int(chat_id)}"
        meta_seed = [run_id, int(chat_id)]
        rng = random.Random(seed)
        if k <= 0:
            picked: list[int] = []
        else:
            picked = sorted(rng.sample(range(len(pool)), k))
        items = [pool[i] for i in picked]
        meta: dict[str, Any] = {
            "source": "deterministic_uniform",
            "purpose": str(purpose),
            "seed": meta_seed,
            "k": int(k),
            "pool": len(pool),
            "picked": [int(i) for i in picked][:_SELECTION_META_CAP],
        }
        return items, meta


def default_source(pipeline_run_id: int | None = None
                   ) -> DeterministicUniformRandomSource:
    """Источник по умолчанию для прогона (seed привязан к `pipeline_run_id`)."""
    return DeterministicUniformRandomSource(pipeline_run_id=pipeline_run_id)


def is_dream_random_source(obj) -> bool:
    """Узкая проверка контракта (duck-typing; для тестов/аудита)."""
    return callable(getattr(obj, "pick", None))
