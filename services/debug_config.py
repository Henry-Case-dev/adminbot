"""Epic 85 (84.18, T-656) — In-Memory State Dump: диагностика stale-cache.

Цель: показать ТЕКУЩИЕ значения из ОПЕРАТИВНОЙ ПАМЯТИ живого процесса
(ConfigCache), а НЕ из PostgreSQL — для инцидента «Mini App записал в PG,
а бот работает на старых значениях из кэша».

  * is_debug_admin(cache, telegram_id) — допуск (84.18.2): wildcard-роль
    или точечное право action.debug.config; при деградации (cache None /
    PG down / admins пуст) — фолбек на settings.ADMIN_USER_ID (паттерн
    admin_commands.py: бот диагностируем без PG).
  * build_dump(cache, key=None) — читает ТОЛЬКО RAM (cache.get_all() /
    get_updated_at()), НИКАКОГО SQL. meta доказывает, что это RAM живого
    процесса: keys_total, cache_loaded_at, pid, app_version.
    source ∈ {memory-cache, settings-fallback, missing}; секреты — ВСЕГДА
    только {configured, last4} (F10-политика, даже для wildcard-админа).

Тонкий слой ПОВЕРХ ConfigCache/param_catalog — те модули не трогаем.
"""
import datetime
import logging
import os

from config.settings import APP_VERSION, settings
from services.param_catalog import REGISTRY, get_by_pg_key
from services.permissions import requires_permission as match_permission

logger = logging.getLogger(__name__)

_TG_TRUNCATE_CHARS = 200   # 84.18.3: обрезка длинных значений в Telegram-выводе


def is_debug_admin(cache, telegram_id: int | None) -> bool:
    """84.18.2: wildcard-роль → да; action.debug.config → да; деградация
    (нет кэша/PG/админов) → фолбек settings.ADMIN_USER_ID."""
    if telegram_id is None:
        return False
    if cache is None or not cache.pg_available or not cache.admins():
        return telegram_id == settings.ADMIN_USER_ID
    if telegram_id not in cache.admins():
        return False
    perms = cache.get_permissions_by_telegram_id(telegram_id)
    if perms is None:
        return False
    if perms.wildcard:
        return True
    return match_permission(perms, "action.debug.config")


def _mask_secret(value) -> dict:
    """F10-политика: только configured/last4 — полное значение НИКОМУ."""
    text = "" if value is None else str(value).strip()
    return {"configured": bool(text), "last4": text[-4:] if text else None}


def _settings_value(spec) -> object | None:
    """settings-дефолт для ключа каталога (None — нет источника)."""
    if spec.settings_field is not None:
        return getattr(settings, spec.settings_field, None)
    return None


def _is_secret(spec, category: str) -> bool:
    if spec is not None:
        return bool(spec.secret)
    return category == "keys"


def _dump_item(cache, pg_key: str) -> dict:
    spec = get_by_pg_key(pg_key)
    category = spec.category if spec else pg_key.split(".")[0]
    in_ram = cache.get_all() if cache is not None else {}
    if cache is not None and pg_key in in_ram:
        source = "memory-cache"
        value = cache.get(pg_key)
    elif spec is not None and spec.category is not None:
        fallback = _settings_value(spec)
        if fallback is not None:
            source = "settings-fallback"
            value = fallback
        else:
            source = "missing"
            value = None
    else:
        source = "missing"
        value = None
    secret = _is_secret(spec, category)
    item = {
        "key": pg_key,
        "category": category,
        "source": source,
        "type": spec.type if spec else type(value).__name__,
        "secret": secret,
        "value": _mask_secret(value) if secret else value,
        "updated_at": cache.get_updated_at(pg_key)
        if cache is not None else None,
    }
    if not secret and isinstance(value, str) and len(value) > _TG_TRUNCATE_CHARS:
        item["value_len"] = len(value)   # полное значение только в JSON-пути
    return item


def build_dump(cache, key: str | None = None) -> dict:
    """84.18.3: дамп RAM-состояния. key=None — все ключи (RAM ∪ каталог);
    key задан — одна запись. НИКАКОГО SQL."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ram = cache.get_all() if cache is not None else {}
    meta = {
        "is_initialized": bool(cache is not None and cache.is_initialized),
        "pg_available": bool(cache is not None and cache.pg_available),
        "keys_total": len(ram),
        "cache_loaded_at": cache.loaded_at if cache is not None else None,
        "app_version": APP_VERSION,
        "pid": os.getpid(),
        "generated_at": now_iso,
    }
    if key is not None:
        return {"meta": meta, "item": _dump_item(cache, key)}
    pg_keys = set(ram.keys()) | {
        s.pg_key for s in REGISTRY.values() if s.category is not None}
    items = [_dump_item(cache, k) for k in sorted(pg_keys)]
    return {"meta": meta, "items": items}
