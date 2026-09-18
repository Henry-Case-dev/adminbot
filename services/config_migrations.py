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

from config.settings import settings

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

# S10.19-8 (F3/ADR-1019-2 D5): новые глобальные дефолты суточных бюджетов не
# доезжают до прода — сид bot_settings вставляет ключи `ON CONFLICT DO NOTHING`
# и НЕ перетирает уже сохранённые (старые) значения. Идемпотентная DML-миграция:
# заменяем PG-значение ТОЛЬКО если оно в точности равно прежнему дефолту
# (25/100000 direct, 35/100000 фон); кастом владельца не трогаем (WARNING);
# отсутствующий ключ — skip (сид поставит новый код-дефолт).
GLOBAL_BUDGET_MIGRATIONS: dict[str, tuple[int, int]] = {
    # direct-контур (общий ключ чата): 25→100 вызовов, 100000→500000 токенов.
    "limits.chat_global_key_budget_requests": (25, 100),
    "limits.chat_global_key_budget_tokens": (100000, 500000),
    # фон per-chat: 35→60 вызовов, 100000→300000 токенов.
    "limits.worker_daily_llm_calls_per_chat": (35, 60),
    "limits.worker_daily_llm_tokens_per_chat": (100000, 300000),
}

# F4 (10.19, ADR-1019-4 D3): расширение дефолтов контекста (5000/3000/16000).
# Прежние PG-значения (сид `ON CONFLICT DO NOTHING`) заменяем ТОЛЬКО если они
# в точности равны прежнему дефолту. `None`/null (было `CHAT_*_MAX_TOKENS=None`)
# → skip: hot.get отдаст новый code-дефолт. Кастом владельца — WARNING.
CONTEXT_LIMIT_MIGRATIONS: dict[str, tuple[int, int]] = {
    # прежние эффективные/глобальные дефолты → новые (UPD2 п.6 «869»).
    "limits.chat_global_context_max_tokens": (1000, 5000),
    "limits.chat_thread_max_tokens": (500, 3000),
    "limits.chat_context_budget_tokens": (4000, 16000),
}

# F4 (10.21, ADR-1021-4 §3.3/§5): принудительное снижение порога глубокого
# сна (cooldown между прогонами), РАЗРЕШЁННОЕ UPD (Д11=да) — идемпотентная
# обратимая PG/DML-миграция (прецедент `migrate_dream_thresholds`). Значение
# `6` (было 20) берётся из отчёта аудита T-1972 при ветке B; при ветке A
# (флаги OFF — текущий аудит) миграция НЕ применяется (env-рубильник
# `DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED`, default OFF). Обратимость:
# вернуть прежнее значение тем же механизмом (prev↔new).
DEEP_SLEEP_THRESHOLD_MIGRATIONS: dict[str, tuple[int, int]] = {
    # pg-key: (прежний дефолт, форсированный)
    "memory.deep_sleep_min_interval_hours": (20, 6),
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


async def migrate_global_budget_defaults(cache) -> dict[str, str]:
    """S10.19-8: идемпотентная миграция глобальных дефолтов бюджетов в PG.

    Заменяет значение, только если текущее == прежнему дефолту
    (`GLOBAL_BUDGET_MIGRATIONS`); кастом владельца не трогает (WARNING);
    PG down / ключ отсутствует → skip. Вызывается из `bot.py main()` рядом с
    `migrate_dream_thresholds` (fail-open)."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[budget_migration] skip: PG недоступен")
        return report
    for key, (prev_default, new_default) in GLOBAL_BUDGET_MIGRATIONS.items():
        current = cache.get(key)
        if current is None:
            logger.info("[budget_migration] ключ отсутствует — сид сделает "
                        "своё | key=%s", key)
            continue
        current_int = _threshold_int(current)
        if current_int == new_default:
            logger.info("[budget_migration] уже новый дефолт | key=%s", key)
            continue
        if current_int == prev_default:
            await cache.set(key, new_default, "limits")
            report[key] = "updated"
            logger.info("[budget_migration] бюджет обновлён | key=%s", key)
            continue
        logger.warning("[budget_migration] кастом владельца — НЕ трогаем | "
                       "key=%s", key)
    return report


async def migrate_deep_sleep_thresholds(cache, *,
                                        enabled: bool | None = None
                                        ) -> dict[str, str]:
    """F4 (ADR-1021-4): идемпотентная миграция порога глубокого сна.

    Принудительное снижение cooldown (`memory.deep_sleep_min_interval_hours`
    20→6) — только если PG-значение в точности равно прежнему дефолту (или
    ключа нет). Кастом владельца не трогаем (WARNING); PG down → skip.
    Обратимость: тот же путь с `(6, 20)`.

    `enabled=None` → env-only ClassVar
    `settings.DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED` (default **False**):
    аудит T-1972 — ветка A (флаги OFF), поэтому миграция по умолчанию НЕ
    применяется (Δ каталога = 0, прецедент MULTILAYER_EXTRACTION_ENABLED).
    Вызывается из `bot.py main()` (fail-open)."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[deep_sleep_migration] skip: PG недоступен")
        return report
    if enabled is None:
        enabled = bool(getattr(
            settings, "DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED", False))
    if not enabled:
        logger.info("[deep_sleep_migration] skip: выключено (ветка A аудита)")
        return report
    for key, (prev_default, new_default) in \
            DEEP_SLEEP_THRESHOLD_MIGRATIONS.items():
        current = cache.get(key)
        current_int = _threshold_int(current)
        if current_int == new_default:
            logger.info("[deep_sleep_migration] уже новый дефолт | key=%s",
                        key)
            continue
        if current is None or current_int == prev_default:
            await cache.set(key, new_default, "memory")
            report[key] = "updated"
            logger.info("[deep_sleep_migration] порог обновлён | key=%s", key)
            continue
        logger.warning("[deep_sleep_migration] кастом владельца — НЕ трогаем "
                       "| key=%s", key)
    return report


async def migrate_context_limit_defaults(cache) -> dict[str, str]:
    """F4 (10.19, ADR-1019-4 D3): идемпотентная миграция дефолтов контекста.

    Заменяет PG-значение, только если текущее == прежнему дефолту
    (`CONTEXT_LIMIT_MIGRATIONS`: 1000/500/4000 → 5000/3000/16000); кастом
    владельца не трогает (WARNING); PG down / ключ отсутствует / `null` → skip
    (hot.get отдаст новый code-дефолт). Вызывается из `bot.py main()` рядом с
    `migrate_global_budget_defaults` (fail-open)."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[context_migration] skip: PG недоступен")
        return report
    for key, (prev_default, new_default) in CONTEXT_LIMIT_MIGRATIONS.items():
        current = cache.get(key)
        if current is None:
            logger.info("[context_migration] ключ отсутствует/пуст — сид "
                        "сделает своё | key=%s", key)
            continue
        current_int = _threshold_int(current)
        if current_int == new_default:
            logger.info("[context_migration] уже новый дефолт | key=%s", key)
            continue
        if current_int == prev_default:
            await cache.set(key, new_default, "limits")
            report[key] = "updated"
            logger.info("[context_migration] лимит контекста обновлён | "
                        "key=%s", key)
            continue
        logger.warning("[context_migration] кастом владельца — НЕ трогаем | "
                       "key=%s", key)
    return report


# F2 (10.23, ADR-1023-2 §3.1): legacy-ключ окна фактчека
# `limits.factcheck_context_messages` — депрекейт. Активный код-путь читает
# только `limits.factcheck_context_before`/`_after`; legacy используется
# ИСКЛЮЧИТЕЛЬНО как источник одноразовой миграции значения в `before`
# (второго источника правды нет, legacy остаётся в реестре как внутренний).
FACTCHECK_CONTEXT_LEGACY_KEY = "limits.factcheck_context_messages"
FACTCHECK_CONTEXT_BEFORE_KEY = "limits.factcheck_context_before"


async def migrate_factcheck_context_defaults(cache) -> dict[str, str]:
    """F2 (10.23, ADR-1023-2): одноразовый перенос legacy-значения окна
    фактчека в `limits.factcheck_context_before`.

    Идемпотентна и осторожна (R1023F2-08):
      * legacy РАВЕН своему code-дефолту (`FACTCHECK_CONTEXT_MESSAGES`) →
        мигрировать нечего → skip (не трогаем `before`, в т.ч. env-дефолт);
      * `before` задан не-дефолтным значением (кастом владельца/PG-каст) →
        WARNING + skip;
      * `before` отсутствует или равен своему code-дефолту → переносим legacy,
        если значение отличается.
    Известное ограничение (зафиксировано в ADR): явный `before == дефолту`
    неотличим от сид-дефолта без отдельного маркера — в этом случае legacy
    считается намерением владельца и переносится. Legacy-значение НЕ удаляется
    (обратимость). PG down → skip. Вызывается из `bot.py main()` (fail-open)."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[factcheck_context_migration] skip: PG недоступен")
        return report
    legacy_raw = cache.get(FACTCHECK_CONTEXT_LEGACY_KEY)
    if legacy_raw is None:
        logger.info("[factcheck_context_migration] legacy-ключ отсутствует — "
                    "skip | key=%s", FACTCHECK_CONTEXT_LEGACY_KEY)
        return report
    legacy_int = _threshold_int(legacy_raw)
    if legacy_int is None:
        logger.warning("[factcheck_context_migration] legacy-значение не "
                       "число — skip | key=%s", FACTCHECK_CONTEXT_LEGACY_KEY)
        return report
    legacy_default = int(settings.FACTCHECK_CONTEXT_MESSAGES or 0)
    if legacy_int == legacy_default:
        logger.info("[factcheck_context_migration] legacy == дефолт — "
                    "мигрировать нечего | key=%s", FACTCHECK_CONTEXT_LEGACY_KEY)
        return report
    default_int = int(settings.FACTCHECK_CONTEXT_BEFORE or 0)
    before_raw = cache.get(FACTCHECK_CONTEXT_BEFORE_KEY)
    before_int = _threshold_int(before_raw)
    if before_int is not None and before_int != default_int:
        logger.warning("[factcheck_context_migration] before уже настроен "
                       "владельцем — НЕ трогаем | key=%s",
                       FACTCHECK_CONTEXT_BEFORE_KEY)
        return report
    if before_int is not None and legacy_int == before_int:
        logger.info("[factcheck_context_migration] уже перенесён — no-op | "
                    "key=%s", FACTCHECK_CONTEXT_BEFORE_KEY)
        return report
    await cache.set(FACTCHECK_CONTEXT_BEFORE_KEY, legacy_int, "limits")
    report[FACTCHECK_CONTEXT_BEFORE_KEY] = "updated"
    logger.info("[factcheck_context_migration] legacy-значение перенесено в "
                "before | value=%d", legacy_int)
    return report


# Раунд 10.23 (F5, ADR-1023-5 §D1/§D3): дефолтный провайдер изображений
# (Pollinations, flux, POST-режим). Сид `bot_settings` вставляет ключи
# `ON CONFLICT DO NOTHING` — уже существующий кастом владельца не перетираем.
# Ключ `keys.image_api_key` здесь СОЗНАТЕЛЬНО отсутствует: секрет пишется
# только из `.env`/UI (R17/R18).
IMAGE_PROVIDER_DEFAULTS_FROM_SETTINGS: tuple[tuple[str, str], ...] = (
    # pg-key → имя Settings-поля (значение берётся из code-дефолта).
    ("models.image_base_url", "IMAGE_BASE_URL"),
    ("models.image_model", "IMAGE_MODEL"),
    ("models.image_get_mode", "IMAGE_GET_MODE"),
)


async def migrate_image_provider_defaults(cache) -> dict[str, str]:
    """F5 (ADR-1023-5): идемпотентный сид дефолтного провайдера изображений.

    Записывает URL/модель/GET-флаг, ЕСЛИ ключ отсутствует или пуст; кастом
    владельца не трогает (WARNING); повторный запуск — no-op. Ключ
    `keys.image_api_key` НЕ записывается никогда (секрет — из `.env`/UI).
    PG down → skip. Вызывается из `bot.py main()` (fail-open)."""
    report: dict[str, str] = {}
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[image_migration] skip: PG недоступен")
        return report
    for key, field in IMAGE_PROVIDER_DEFAULTS_FROM_SETTINGS:
        default = getattr(settings, field, None)
        current = cache.get(key)
        if current is None or current == "":
            await cache.set(key, default, "models")
            report[key] = "seeded"
            logger.info("[image_migration] дефолт записан | key=%s", key)
            continue
        if current == default:
            logger.info("[image_migration] уже дефолт | key=%s", key)
            continue
        logger.warning("[image_migration] кастом владельца — НЕ трогаем | "
                       "key=%s", key)
    return report
