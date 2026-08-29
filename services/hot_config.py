"""Epic 85 (84.4/84.9 Фаза 2, T-619) — единая sync-точка чтения горячих параметров.

Сервисы бота читают регулируемые параметры (промпты/лимиты/кулдауны/флаги/
ключи/реакции) через hot.get(pg_key, settings_значение):
  * кэш НЕ инициализирован (тесты, ранний старт) → settings-дефолт (R1);
  * ключа нет в БД → settings-дефолт (поведение == старому до миграции T-637);
  * ключ есть в БД → значение из ConfigCache; POST /api/config обновляет кэш →
    следующее обращение бота уже с новым значением (hot-reload, 84.4).

Правило R1: каждый параметр переводится независимо; `settings` остаётся
источником дефолтов. Глобальный объект кэша внедряется из bot.py после
`cache.init()` (set_config_cache). Модуль НИКОГО не импортирует — циклических
зависимостей нет.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

_cache: Any = None  # ConfigCache | None (тип намеренно без импорта — no-cycle)


def set_config_cache(cache: Any) -> None:
    """Внедрение ConfigCache (bot.py после init). None → чистый фолбек на settings."""
    global _cache
    _cache = cache


def get_config_cache() -> Any:
    return _cache


def get(key: str, default: Any = None) -> Any:
    """Значение параметра: кэш при наличии ключа, иначе settings-дефолт."""
    if _cache is None:
        return default
    return _cache.get(key, default)
