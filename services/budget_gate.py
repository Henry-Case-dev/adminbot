"""F21 (раунд 10.24, ADR-1024-22) — единый master-рубильник бюджетов.

Ключ `flags.budgets_enabled` (каталоговый, default ON) выключает
enforcement бюджетов ЦЕЛИКОМ — глобально ИЛИ per-chat. OFF = лимиты не
ограничивают (direct и фон), контекст не режется; УЧЁТ статистики при этом
продолжается (счётчики пишутся всегда). OFF НЕ отменяет права доступа
(`keys.allow_global=false`), BYOK-ключи, выбор провайдера/модели.

Контракт резолва (единственная точка): `chat → global → default(True)`.
Fail-open: любая ошибка резолва → True (поведение как прежде, enforcement
остаётся включённым — безопасный дефолт для продукта).

R17/R18-safe: логируется только `key`/`chat`/`source`, значений нет.
"""
import logging

from config.settings import settings

logger = logging.getLogger(__name__)

# pg-ключ master-рубильника (каталог `param_catalog`, группа flags_module_budgets).
KEY_BUDGETS_ENABLED = "flags.budgets_enabled"


async def budgets_enabled(chat_id: int | None = None) -> bool:
    """Master-рубильник бюджетов.

    Приоритет: chat override → global (hot) → default `settings.BUDGETS_ENABLED`
    (True). `chat_id=None` (фон-скоп `'global'`) видит только глобальный слой.

    Fail-open: ошибка резолва (PG/кэш/каст) → `True` (бюджеты как прежде).
    Возвращает `True` = бюджеты включены, `False` = master OFF.
    """
    default = bool(getattr(settings, "BUDGETS_ENABLED", True))
    try:
        from services.worker_settings import resolve_setting_cached
        value = await resolve_setting_cached(
            KEY_BUDGETS_ENABLED, chat_id=chat_id, default=default)
        return bool(value)
    except Exception:
        logger.warning(
            "[budget_gate] master flag resolve failed — fail-open ON | chat=%s",
            chat_id, exc_info=True)
        return True
