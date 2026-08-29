"""Epic 85 (84.4/84.9 Фаза 2, T-619) — единая sync-точка чтения горячих параметров.

Сервисы бота читают регулируемые параметры (промпты/лимиты/кулдауны/флаги/
ключи/реакции) через hot.get(pg_key, settings_значение):
  * кэш НЕ инициализирован (тесты, ранний старт) → settings-дефолт (R1);
  * ключа нет в БД → settings-дефолт (поведение == старому до миграции T-637);
  * ключ есть в БД → значение из ConfigCache; POST /api/config обновляет кэш →
    следующее обращение бота уже с новым значением (hot-reload, 84.4).

ХОТФИКС (прод-инцидент 86b3d3a): второй рубеж типизации — даже если в кэш
каким-то путём попало СТРОКОВОЕ значение (asyncpg jsonb → str), hot.get
кастует его по типу param_catalog (int/float/bool/json). Это защищает все
точки сравнений/арифметики (alan_reply_interval, budget*, cooldown'ы…)
от TypeError str/int.

Правило R1: каждый параметр переводится независимо; `settings` остаётся
источником дефолтов. Глобальный объект кэша внедряется из bot.py после
`cache.init()` (set_config_cache).
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

_cache: Any = None  # ConfigCache | None (тип намеренно без импорта — no-cycle)

# Ленивый кэш каталога (заполняется при первом get): {pg_key: ParamSpec}
# — dict-поиск в горячем пути, импорт param_catalog один раз.
_spec_by_key: dict | None = None


def set_config_cache(cache: Any) -> None:
    """Внедрение ConfigCache (bot.py после init). None → чистый фолбек на settings."""
    global _cache
    _cache = cache


def get_config_cache() -> Any:
    return _cache


def _catalog_spec(pg_key: str):
    global _spec_by_key
    if _spec_by_key is None:
        try:
            from services.param_catalog import REGISTRY
            _spec_by_key = {s.pg_key: s for s in REGISTRY.values()}
        except Exception:  # pragma: no cover — каталог не должен ронять горячий путь
            logger.warning("[hot_config] каталог параметров недоступен",
                           exc_info=True)
            _spec_by_key = {}
    return _spec_by_key.get(pg_key)


def _coerce(key: str, value: Any) -> Any:
    """Defense-in-depth: строковое значение кастуется по типу каталога."""
    if value is None:
        return None
    spec = _catalog_spec(key)
    if spec is None:
        return value
    try:
        from services.param_catalog import _cast_to_type
        return _cast_to_type(spec, value)
    except Exception:
        logger.warning("[hot_config] каст не удался | key=%s", key,
                       exc_info=True)
        return value


def get(key: str, default: Any = None) -> Any:
    """Значение параметра: кэш при наличии ключа, иначе settings-дефолт.
    Второй рубеж: значение из кэша нормализуется по типу каталога."""
    if _cache is None:
        return default
    return _coerce(key, _cache.get(key, default))
