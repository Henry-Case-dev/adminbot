"""F4 (T-2127, ADR-1023-4 D2/D3) — динамический анти-клише кэш: чтение/резолв.

Кэш живёт в PG-таблице ``anticliche_cache`` (singleton id=1, JSONB-список
паттернов + метаданные). Детектор ``find_forbidden_cliches`` — синхронная
чистая функция, PG-I/O на каждый ответ НЕ делает: оркестраторы Stage-2
получают правила из in-process memoized ``get_rules()`` (резолв из PG один
раз — при старте и после записи/ручной правки).

Fail-open: нет PG / пустая/битая строка → ``get_rules()`` = ``()``; детектор
работает только на захардкоженном списке (байт-в-байт 10.22). R17: наружу
отдаются коды и метаданные, фразы в логи не пишутся.
"""
from __future__ import annotations

import logging

from config.settings import settings
from services.negative_constraints import (
    DynamicClicheRule,
    build_dynamic_rule,
)

logger = logging.getLogger(__name__)

# Лимит динамических правил (ADR-1023-4 D2; Δ каталога = 0 — код-константа).
ANTICLICHE_MAX_PATTERNS = 20

# R17-safe whitelist статусов (review iter1 L1): применяется в записи.
ALLOWED_STATUSES: frozenset[str] = frozenset({
    "never", "ok", "fetch_error", "llm_error", "parse_error", "empty",
})

_SELECT_SQL = (
    "SELECT patterns, source, source_url, version, fetched_at, updated_at, "
    "last_status FROM anticliche_cache WHERE id = 1"
)
# Review iter1 (L3): `fetched_at` («время забора источника», spec §2.2) —
# обновляется только при реальном заборе; при ручной правке передаётся None
# и COALESCE сохраняет прежнее значение. `mark_status` updated_at НЕ двигает.
_UPSERT_SQL = (
    "INSERT INTO anticliche_cache (id, patterns, source, source_url, version, "
    "fetched_at, updated_at, last_status) "
    "VALUES (1, $1, $2, $3, 1, COALESCE($5::timestamptz, now()), now(), $4) "
    "ON CONFLICT (id) DO UPDATE SET "
    "patterns = EXCLUDED.patterns, "
    "source = EXCLUDED.source, "
    "source_url = EXCLUDED.source_url, "
    "version = anticliche_cache.version + 1, "
    "fetched_at = COALESCE($5::timestamptz, anticliche_cache.fetched_at), "
    "updated_at = now(), "
    "last_status = EXCLUDED.last_status "
    "RETURNING version"
)
_STATUS_SQL = "UPDATE anticliche_cache SET last_status = $1 WHERE id = 1"

# Runtime-PG (DI из bot.py; прецедент worker_budget.set_worker_budget_pg).
_runtime_pg = None
# In-process memoized правила (инвалидация после записи/ручной правки).
_cached_rules: tuple[DynamicClicheRule, ...] = ()


def enabled() -> bool:
    """Включён ли динамический кэш (env-only kill-switch, default ON)."""
    return bool(getattr(settings, "DYNAMIC_ANTICLICHE_ENABLED", True))


def set_runtime_pg(pg) -> None:
    global _runtime_pg
    _runtime_pg = pg


def get_runtime_pg():
    return _runtime_pg


def _pool(pg=None):
    target = pg if pg is not None else _runtime_pg
    return getattr(target, "pool", None) if target is not None else None


def _rules_from_patterns(patterns) -> tuple[DynamicClicheRule, ...]:
    """JSONB-список → кортеж правил (нормализация/лимит/дедуп по коду)."""
    if not isinstance(patterns, (list, tuple)):
        return ()
    rules: list[DynamicClicheRule] = []
    seen: set[str] = set()
    for item in patterns:
        phrase = item.get("phrase") if isinstance(item, dict) else item
        rule = build_dynamic_rule(phrase)
        if rule is None or rule.code in seen:
            continue
        seen.add(rule.code)
        rules.append(rule)
        if len(rules) >= ANTICLICHE_MAX_PATTERNS:
            break
    return tuple(rules)


def get_rules() -> tuple[DynamicClicheRule, ...]:
    """Memoized динамические правила (без I/O). ``()`` при флаге OFF/пустом кэше."""
    if not enabled():
        return ()
    return _cached_rules


def set_rules(patterns) -> tuple[DynamicClicheRule, ...]:
    """Установить in-process правила из списка паттернов (без PG)."""
    global _cached_rules
    _cached_rules = _rules_from_patterns(patterns) if enabled() else ()
    return _cached_rules


def invalidate() -> None:
    """Сбросить in-process кэш (после записи/ручной правки)."""
    global _cached_rules
    _cached_rules = ()


async def fetch_cache(pg=None) -> dict:
    """Прочитать singleton-строку кэша. Fail-open: нет PG/ошибка → ``{}``.

    Возвращает ``{patterns, source, source_url, version, fetched_at,
    updated_at, last_status}`` (последние три — как пришли из PG)."""
    pool = _pool(pg)
    if pool is None:
        return {}
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_SELECT_SQL)
    except Exception:
        logger.warning("[anticliche] cache read failed — fail-open (empty)",
                       exc_info=True)
        return {}
    if row is None:
        return {}
    try:
        data = dict(row)
    except (TypeError, ValueError):
        return {}
    return data


async def load_rules(pg=None) -> tuple[DynamicClicheRule, ...]:
    """Прочитать PG и обновить memoized правила (fail-open → текущее/пусто)."""
    if not enabled():
        invalidate()
        return ()
    data = await fetch_cache(pg)
    if not data:
        # PG недоступен/строки нет — не затираем уже загруженные правила.
        return _cached_rules
    return set_rules(data.get("patterns"))


async def write_patterns(pg, patterns, *, source: str, source_url: str,
                         last_status: str = "ok", fetched_at=None) -> int:
    """Upsert списка паттернов (version+1) + обновление in-process правил.

    ``fetched_at`` — время реального забора источника (None → сохранить
    прежнее значение, напр. при ручной правке). Бросает исключение при
    недоступном PG (вызывающий решает, что вернуть). Возвращает новую версию.
    """
    pool = _pool(pg)
    if pool is None:
        raise RuntimeError("anticliche_cache: PostgreSQL недоступен")
    safe_status = _safe_status(last_status)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _UPSERT_SQL, list(patterns or []), str(source or ""),
            str(source_url or ""), safe_status, fetched_at)
    version = int(row["version"]) if row and row.get("version") is not None else 0
    set_rules(patterns)
    logger.info("[anticliche] cache written | n=%d | source=%s | version=%d",
                len(list(patterns or [])), source, version)
    return version


def _safe_status(status) -> str:
    """Whitelist R17-safe статусов (review iter1 L1)."""
    value = str(status or "never")
    return value if value in ALLOWED_STATUSES else "never"


async def mark_status(pg, status: str) -> None:
    """R17-safe запись статуса без изменения паттернов/fetched_at. Fail-open.

    `updated_at` не двигается (status-only апдейт; review iter1 L3)."""
    pool = _pool(pg)
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(_STATUS_SQL, _safe_status(status))
    except Exception:
        logger.warning("[anticliche] status write failed | status=%s", status)
