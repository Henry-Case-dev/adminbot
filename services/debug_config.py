"""Epic 85 (84.18/84.20, T-656/T-658) — In-Memory State Dump и /debug_config v2.

Цель: показать ТЕКУЩИЕ значения из ОПЕРАТИВНОЙ ПАМЯТИ живого процесса
(ConfigCache), а НЕ из PostgreSQL — для инцидента «Mini App записал в PG,
а бот работает на старых значениях из кэша».

  * is_debug_admin(cache, telegram_id) — допуск (84.18.2): wildcard-роль
    или точечное право action.debug.config; при деградации (cache None /
    PG down / admins пуст) — фолбек на settings.ADMIN_USER_ID.
  * resolve_param_key(raw) — резолв env-имени/settings_field (case-
    insensitive) или pg-ключа → ParamSpec | None (84.20.2).
  * display_name(spec) — env-стиль имя; для PG-only (prompts.*, content.*)
    — pg-ключ (в выводе помечается [pg]).
  * build_dump(cache, key=None) — читает ТОЛЬКО RAM; v2-формат списка:
    строки `KEY = value`; секреты — configured••••last4; значение ≤200
    символов + …[len=N]; недавно изменённый — маркер `*` + время.
  * format_meta()/format_line() — телеграм-рендер v2 (одна meta-строка,
    одна строка на ключ).

Тонкий слой ПОВЕРХ ConfigCache/param_catalog — те модули не трогаем.
"""
import datetime
import logging
import os

from config.settings import APP_VERSION, settings
from services.param_catalog import REGISTRY, ParamSpec, get_by_pg_key
from services.permissions import requires_permission as match_permission

logger = logging.getLogger(__name__)

_TG_TRUNCATE_CHARS = 200   # 84.18.3: обрезка длинных значений в Telegram-выводе
_PG_ONLY_MARK = "[pg]"     # 84.20.3: пометка pg-ключей в выводе


# ── Резолвер и display-имя (84.20.2) ────────────────────────────────────────

def _by_name_ci() -> dict[str, ParamSpec]:
    """name.lower() → spec (для settings_field/env_name; pg-ключи — отдельно)."""
    out: dict[str, ParamSpec] = {}
    for spec in REGISTRY.values():
        for name in (spec.settings_field, spec.env_name):
            if name:
                out[name.lower()] = spec
    return out


def resolve_param_key(raw: str) -> ParamSpec | None:
    """raw — env-имя (case-insensitive) | settings_field | pg-ключ → spec.
    Неизвестное → None (вызывающий рендерит «не найден: X»)."""
    if not raw or not raw.strip():
        return None
    name = raw.strip()
    spec = _by_name_ci().get(name.lower())
    if spec is not None:
        return spec
    return get_by_pg_key(name)


def display_name(spec: ParamSpec) -> str:
    """84.20.2: env-стиль имя; PG-only → pg-ключ."""
    return spec.env_name or spec.settings_field or spec.pg_key


def is_pg_only(spec: ParamSpec) -> bool:
    return spec.env_name is None and spec.settings_field is None


# ── v2-формат (84.20.3) ─────────────────────────────────────────────────────

def _format_value_text(value, secret: bool) -> str:
    """Значение строкой: секреты configured••••last4; обрезка ≤200 + [len=N].
    Секрет-dict с configured=False → 'not configured' (не пустая строка)."""
    if secret:
        if isinstance(value, dict):
            if not value.get("configured"):
                return "not configured"
            last4 = value.get("last4")
            return f"configured••••{last4}" if last4 else "configured"
        text = "" if value is None else str(value).strip()
        return f"configured••••{text[-4:]}" if text else "not configured"
    if value is None:
        return "None"
    if isinstance(value, str):
        text = value
        full_len = None
    else:
        text = repr(value)
        full_len = len(text)
    if len(text) > _TG_TRUNCATE_CHARS:
        return text[:_TG_TRUNCATE_CHARS] + f"…[len={full_len or len(text)}]"
    return text


def format_line(spec: ParamSpec | None, pg_key: str, item: dict) -> str:
    """84.20.3: одна строка `KEY = value`; PG-only — `KEY = [pg] value`."""
    if spec is not None:
        name = display_name(spec)
        prefix = f"{name}"
        if is_pg_only(spec):
            prefix += f" {_PG_ONLY_MARK}"
    else:
        prefix = pg_key
    value = _format_value_text(item.get("value"), item.get("secret", False))
    return f"{prefix} = {value}"


def format_meta(meta: dict) -> str:
    """84.20.3: ОДНА компактная meta-строка с префиксом `meta:` (обязательный
    след RAM-диагностики; generated_at — полнота сведений о снимке)."""
    loaded_at = (meta.get("cache_loaded_at") or "")[11:19] \
        if meta.get("cache_loaded_at") else "-"
    return (f"meta: pid={meta.get('pid')} | v={meta.get('app_version')} | "
            f"pg={1 if meta.get('pg_available') else 0} | "
            f"keys={meta.get('keys_total', 0)} | loaded_at={loaded_at} | "
            f"generated_at={meta.get('generated_at') or '-'}")


def recent_marker(items: list[dict]) -> tuple[str | None, str | None]:
    """84.20.3: (маркер-строка, pg-ключ) для max updated_at.
    None игнорируются; всё None/или нет updated_at → (None, None)."""
    best_item = None
    best_ts = None
    for item in items:
        ts = item.get("updated_at")
        if ts and (best_ts is None or ts > best_ts):
            best_ts = ts
            best_item = item
    if best_item is None:
        return None, None
    spec = get_by_pg_key(best_item["key"])
    line = format_line(spec, best_item["key"], best_item)
    return f"* {line} [updated {best_ts}]", best_item["key"]


def build_lines(cache, key: str | None = None) -> list[str]:
    """84.20.3: рендер v2. Без key — meta-строка, маркер `*`, затем все ключи;
    с key — meta-строка + одна строка; неизвестный ключ → ['не найден: X']."""
    dump = build_dump(cache, key=key)
    meta_line = format_meta(dump["meta"])
    if key is not None:
        item = dump["item"]
        if item["source"] == "missing" and \
                get_by_pg_key(item["key"]) is None:
            return [f"не найден: {key}"]
        spec = get_by_pg_key(item["key"])
        return [meta_line, format_line(spec, item["key"], item)]
    items = dump["items"]
    marker, marked_key = recent_marker(items)
    lines = [meta_line]
    if marker:
        lines.append(marker)
    # 4: сортировка по display_name (env-имя), не по pg-ключу
    for item in sorted(items, key=lambda i: (i.get("name") or i["key"])):
        if marked_key and item["key"] == marked_key:
            continue   # уже показан маркированным
        spec = get_by_pg_key(item["key"])
        lines.append(format_line(spec, item["key"], item))
    return lines


# ── Базовая диагностика (84.18) ─────────────────────────────────────────────

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
        "name": display_name(spec) if spec else pg_key,
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
    """84.18.3/84.20.4: дамп RAM-состояния. key=None — все ключи (RAM ∪
    каталог); key задан — одна запись (с name). НИКАКОГО SQL."""
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
