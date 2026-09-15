"""F2 `sleep-manual-cascade-badges` (spec §4.1, T-1714/T-1769) — идемпотентные
DML-миграции числовых настроек в PG.

Вынесено в отдельный модуль (spec §4.1 допускает `services/config_migrations.py`)
специально, чтобы НЕ трогать `services/prompt_migrations.py`: канон-дельта-тесты
раунда 10.13 (`test_webapp_round1013_ui.py`/`test_dream_prompts.py`) пиннят, что
модуль миграций промптов не знает про «dream» (правка промптов Личности не
требуется — причина 0 черт в флагах/порогах/read-path).

Принцип: заменяем PG-значение ТОЛЬКО если оно в точности равно ПРЕЖНЕМУ
дефолту; кастом владельца не перетираем (WARNING); отсутствующий ключ — skip
(сид ConfigCache поставит новый code-дефолт); PG down — skip. Прецедент —
`migrate_prompt_canons` / `migrate_direct_reply_ttl_default`.
"""
import logging

logger = logging.getLogger(__name__)

# Прежние (до F2) дефолты порогов дистилляции Сна → новые code-дефолты
# (config/settings.py: 2/8/2/10/60/300000/10).
DREAM_THRESHOLD_MIGRATIONS: dict[str, tuple[int, int]] = {
    # pg-key: (прежний дефолт, новый дефолт)
    "memory.dream_repeat_threshold": (3, 2),
    "memory.dream_importance_sum_threshold": (12, 8),
    "memory.dream_min_new_facts_per_chat": (5, 2),
    "memory.dream_max_clusters_per_run": (5, 10),
    "memory.dream_distillations_per_day": (30, 60),
    "memory.dream_tokens_per_day": (60000, 300000),
    "memory.dream_quiet_check_minutes": (30, 10),
}


def _threshold_int(value) -> int | None:
    """Приведение значения PG к int (bool/мусор → None).

    PG-слой может хранить число как str ("8"); bool («True»/1) не считаем
    числовым порогом, чтобы случайно не принять кастом за прежний дефолт."""
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


async def migrate_dream_thresholds(cache) -> dict[str, str]:
    """Идемпотентная миграция порогов Сна в PG.

    Заменяет значение, только если текущее == прежнему дефолту (3/12/5/5/30/
    60000/30). Возврат: dict обновлённых ключей (пусто — nothing to do).
    Вызывается из bot.py main() рядом с migrate_prompt_canons."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[threshold_migration] skip: PG недоступен")
        return report
    for key, (prev_default, new_default) in DREAM_THRESHOLD_MIGRATIONS.items():
        current = cache.get(key)
        if current is None:
            logger.info("[threshold_migration] ключ отсутствует — сид сделает "
                        "своё | key=%s", key)
            continue
        current_int = _threshold_int(current)
        if current_int == new_default:
            logger.info("[threshold_migration] уже новый дефолт | key=%s", key)
            continue
        if current_int == prev_default:
            await cache.set(key, new_default, "memory")
            report[key] = "updated"
            logger.info("[threshold_migration] порог обновлён | key=%s", key)
            continue
        logger.warning("[threshold_migration] кастом владельца — НЕ трогаем | "
                       "key=%s", key)
    return report
