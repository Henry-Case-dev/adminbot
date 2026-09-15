"""Раунд 10.18 (F7 settings-worker-sync, T-1759) — единый accessor резолва
настроек воркеров и статус-API.

Приоритет значения (ADR-1018-7 D1 — ровно семантика
`chat_params.get_chat_param`/`_resolve_from_root`):
    chat_params.overrides[key] (каст по каталогу)
        → hot.get(key) (глобальный слой БД, bot_settings)
        → default (env-дефолт settings).

Это закрывает симптом владельца: UI-тумблер пишется в слой ЧАТА
(`chat_profiles.chat_params.overrides`), а воркер/статус читали только
глобальный слой и показывали OFF.

Fail-open: ошибка PG/кэша → глобальный слой/дефолт (бот жив), WARNING.
R17-safe: логируем ТОЛЬКО key/chat_id/source — значения (в т.ч. возможные
секреты/свободный текст) в лог НЕ попадают.
"""
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Сентинел «ключа нет»: отличает отсутствие ключа в слое от явного значения.
_SENTINEL = object()


def _global_with_source(key: str, default: Any) -> tuple[Any, str]:
    """(значение, 'global'|'default') — глобальный слой через hot.get.

    `hot.get(key, _SENTINEL)` возвращает сентинел, если ключа нет ни в кэше,
    ни в env-дефолте (в т.ч. при отсутствии ConfigCache) → source='default'.
    Сентинел проходит `_coerce` без изменений (ни один тип каталога его не
    кастует)."""
    from services import hot_config as hot
    try:
        raw = hot.get(key, _SENTINEL)
    except Exception:
        logger.warning("[settings] global read failed — default | key=%s", key)
        return default, "default"
    if raw is _SENTINEL:
        return default, "default"
    return raw, "global"


def _chat_with_source(root: dict | None, key: str) -> tuple[Any, str] | None:
    """(значение, 'chat') из overrides с кастом по каталогу; None — нет
    валидного chat-override (идём на глобальный слой).

    Каст/валидация повторяют `chat_params._resolve_from_root` (мусор/NaN/inf
    → None → глобальный фолбэк)."""
    from services import chat_params as cp
    from services.param_catalog import get_by_pg_key, normalize_value
    overrides = (root or {}).get("overrides") or {}
    if key not in overrides:
        return None
    try:
        value = overrides.get(key)
    except Exception:
        return None
    spec = get_by_pg_key(key)
    if spec is None:
        return value, "chat"
    try:
        casted = normalize_value(key, value)
        if cp._cast_type_ok(spec.type, casted) and not (
                spec.type == "float" and isinstance(casted, float)
                and not math.isfinite(casted)):
            return casted, "chat"
    except Exception:
        logger.warning("[settings] chat cast failed — global fallback | "
                       "key=%s", key)
    return None


async def _chat_root(chat_id: int | None) -> tuple[dict, bool]:
    """(root, ok) — root-лейаут chat_params чата. `ok=False` ⇔ chat-слой
    НЕдоступен (нет `ChatParamsPool`/ошибка чтения) — D-1: «пустой слой» и
    «нечитаемый слой» различимы для fail-closed decision-path'ов.
    chat_id=None → ({}, True) (слой не участвует)."""
    if chat_id is None:
        return {}, True
    from services import chat_params as cp
    cache = cp.get_chat_params_cache()
    if cache is None:
        return {}, False
    checked = getattr(cache, "get_chat_params_checked", None)
    try:
        if callable(checked):
            root, ok = await checked(int(chat_id))
            return root or {}, bool(ok)
        # fake/legacy-кэш без ok-контракта: value-only, считаем доступным.
        return await cache.get_chat_params(int(chat_id)) or {}, True
    except Exception:
        logger.warning("[settings] chat layer load failed — global | "
                       "chat=%s", chat_id)
        return {}, False


async def _resolve_full(key: str, *, chat_id: int | None,
                        default: Any) -> tuple[Any, str]:
    root, ok = await _chat_root(chat_id)
    if ok:
        chat = _chat_with_source(root, key)
        if chat is not None:
            return chat
        return _global_with_source(key, default)
    # D-1 (Critical, ревью Батча E): chat-слой НЕ читается → значение
    # fail-open (глобал/дефолт — бот жив), но источник помечаем 'error':
    # decision-path'ы (retention purge) обязаны трактовать это как
    # недоступность данных чата, а не как «override отсутствует».
    value, _src = _global_with_source(key, default)
    logger.warning("[settings] chat layer unavailable — source=error | "
                   "key=%s | chat=%s", key, chat_id)
    return value, "error"


def _log(key: str, chat_id: int | None, source: str) -> None:
    logger.debug("[settings] key=%s | chat=%s | source=%s",
                 key, chat_id, source)


async def resolve_setting_with_source(key: str, *, chat_id: int | None = None,
                                      default: Any = None) -> tuple[Any, str]:
    """(значение, source) — для статус-API (R16-аддитивность)."""
    return await _resolve_full(key, chat_id=chat_id, default=default)


async def resolve_setting(key: str, *, chat_id: int | None = None,
                          default: Any = None, log_source: bool = False) -> Any:
    """ЕДИНСТВЕННЫЙ публичный read-path значения: chat → global → default.

    chat_id=None → только глобальный слой/дефолт. Fail-open.
    `log_source=True` добавляет R17-safe debug-лог `[settings] key/chat/source`
    (ADR-1018-7 D9)."""
    value, source = await _resolve_full(key, chat_id=chat_id, default=default)
    if log_source:
        _log(key, chat_id, source)
    return value


async def resolve_setting_cached(key: str, *, chat_id: int | None = None,
                                 default: Any = None) -> Any:
    """Входная точка воркеров (ADR-1018-7 D2) — тонкая обёртка над
    `resolve_setting`: overrides берутся из `ChatParamsCache` (TTL 120с +
    локальная/NOTIFY-инвалидация), global — из `ConfigCache` (in-memory), без
    PG-раундтрипа в горячем цикле. Отличие от `resolve_setting` — всегда
    пишет debug-лог `source` (диагностика D9)."""
    return await resolve_setting(key, chat_id=chat_id, default=default,
                                 log_source=True)


def setting_source(key: str, *, chat_id: int | None = None) -> str:
    """'chat' | 'global' | 'default' — best-effort, БЕЗ I/O.

    НАЗНАЧЕНИЕ: дешёвая диагностика (лог/health/ассерты), когда значение НЕ
    нужно. НЕ decision-path: смотрит только уже прогретые in-memory слои
    (overrides из `ChatParamsCache._items`, затем `ConfigCache`); непрогретый
    слой → 'default'. Если нужно И значение, И источник — использовать
    `resolve_setting_with_source`."""
    from services import hot_config as hot
    if chat_id is not None:
        from services import chat_params as cp
        cache = cp.get_chat_params_cache()
        items = getattr(cache, "_items", None) if cache is not None else None
        entry = items.get(int(chat_id)) if isinstance(items, dict) else None
        root = entry[1] if entry is not None else None
        if key in ((root or {}).get("overrides") or {}):
            return "chat"
    if hot.get(key, _SENTINEL) is not _SENTINEL:
        return "global"
    return "default"
