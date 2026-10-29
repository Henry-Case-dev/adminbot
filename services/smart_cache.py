"""Smart Cache storage — технические TTL-маркеры в общей таблице smart_cache.

EVOL-031 (30.10.2026): replay готовых LLM-ответов выведен из эксплуатации.
Раньше модуль был Exact Match Cache (Epic 51/60): слаги `search` / `web` /
`youtube` / `factcheck` / `direct_dedup` кешировали финальные ответы бота и
воспроизводили их на точные повторы. Consult+store на ответном пути удалён
(handlers/search.py, handlers/web.py, handlers/youtube.py, ветка direct_dedup
в services/direct_chat_service.py), UI-карточка/рубильники сняты; ответы
модели здесь больше НЕ хранятся и НЕ воспроизводятся, восстановить replay
через env/PG-ключи или старый UI невозможно. Семантический/векторный кеш
ответов взамен НЕ вводится.

Таблица `smart_cache` СОХРАНЕНА (аддитивно, без деструктивной миграции и без
сброса данных) — в ней живут защищённые технические механизмы:

* update-identity маркеры Telegram (MCA-22 C7, префикс `direct_update`,
  TTL 24 h, потребитель services/response_freshness.py) — дедупликация
  СОБЫТИЙ, не ответов;
* широкий контекст-срез фактчека (CFG-06, slug `factcheck_wide_context`,
  TTL ~120 с, потребитель services/factcheck_context.py).

Legacy-строки удалённых ответных кешей остаются инертными: читателей нет,
записей нет, выметаются ленивой чисткой/вытеснением по потолку строк.

Ключи: `build_key` = MD5(slug + "\\x00" + нормализованный ввод); slug-словарь
закрытый (неизвестный slug → ValueError). Утилиты normalize_url/normalize_text
— общие (lore_compiler_service, temporal_factcheck, direct_chat_service,
factcheck_context и др.). Маркерные методы принимают ЯВНЫЙ TTL вызывающего;
ленивая чистка при записи использует порог НЕ НИЖЕ самого долгого активного
TTL (24 h маркеров), чтобы коротко-TTL запись не выметала долгоживущие
маркеры. Ошибки БД — WARNING + miss/no-op (кеш НЕ роняет потребителя).
Ленивый синглтон без DI-хендлеров (прецедент MediaGroupCaptionBuffer);
close() вызывается в on_shutdown (bot.py).
"""
import asyncio
import hashlib
import logging
import re
import sqlite3
import time
import urllib.parse
from typing import Any, Awaitable, Callable

import aiosqlite

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# F17 (раунд 10.24, ADR-1024-18): паритет настроек соединения с
# services/database.py:48,516-520 и bounded retry на `database is locked`
# (зеркало services/memory_rebuild.py:71-72). Значения — локальные константы.
_BUSY_TIMEOUT_MS = 5000     # зеркало services/database.py:48 (_BUSY_TIMEOUT_MS)
_LOCK_RETRIES = 3           # зеркало services/memory_rebuild.py:71
_LOCK_BACKOFF = 0.1         # зеркало services/memory_rebuild.py:72

# MCA-22 (C7, fix round-1 M-1): TTL update-identity маркеров — зеркалит
# `response_freshness.UPDATE_DEDUP_TTL_SECONDS` (= 24 h; drift-guard тест).
# Нужен здесь БЕЗ импорта response_freshness: порог ленивой чистки
# (`_sweep_ttl`) обязан учитывать 24-часовые маркеры при любых флагах.
_UPDATE_MARKER_SWEEP_TTL = 24 * 3600

# In-process счётчик исчерпаний (Δ DDL = 0: метрика = лог + счётчик; сброс
# процесса = сброс счётчика — событие остаётся в логе).
_lock_exhausted_total = 0

# EVOL-031: слаги ответных кешей (`search`/`web`/`youtube`/`factcheck_temporal`
#/`direct_dedup`) сняты. `factcheck` остаётся зарегистрированным как
# provenance-метка оркестратора фактчека (FC-06C: вердикт-кеш удалён,
# FactCheckPlan.cache_slug — только ярлык; внешних читателей нет). Остальные:
# CFG-06 W1 — кеш широкого контекст-среза (services/factcheck_context.py).
_NORMALIZERS = {
    "factcheck": "text",
    "factcheck_wide_context": "text",
}

_UTM_PREFIX = "utm_"
_TRACKING_KEYS = {"fbclid", "gclid"}


def normalize_url(url: str) -> str:
    """D208: strip → urlparse; netloc → lower; ОДИН trailing '/' срезается
    (если не корень); query: удалить ключи utm_* + fbclid + gclid (остальные
    сохранить); fragment отбрасывается."""
    parsed = urllib.parse.urlparse(str(url).strip())
    host = parsed.netloc.lower()
    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    kept = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith(_UTM_PREFIX) and k.lower() not in _TRACKING_KEYS
    ]
    query = urllib.parse.urlencode(kept) if kept else ""
    rebuilt = urllib.parse.urlunparse(
        (parsed.scheme, host, path, parsed.params, query, "")
    )
    return rebuilt


def normalize_text(query: str) -> str:
    """D209: casefold + strip + схлопывание пробелов."""
    return re.sub(r"\s+", " ", str(query).casefold().strip())


def build_key(slug: str, raw_input: str) -> str:
    """D208: slug ∈ фиксированный словарь (неизвестный → ValueError);
    key = MD5(slug + "\\x00" + нормализованный ввод) — команда в ключе
    исключает межсервисные коллизии."""
    if slug not in _NORMALIZERS:
        raise ValueError(f"unknown cache slug: {slug!r}")
    normalize = normalize_url if _NORMALIZERS[slug] == "url" else normalize_text
    norm = normalize(raw_input)
    return hashlib.md5(f"{slug}\x00{norm}".encode("utf-8")).hexdigest()


def smart_cache_lock_exhausted_total() -> int:
    """F17: число исчерпаний retry на `database is locked` в этом процессе.

    Δ DDL = 0 (PG-таблиц/миграций нет). Сброс процесса = сброс счётчика;
    само событие остаётся в логе (`event=smart_cache_lock_exhausted`)."""
    return _lock_exhausted_total


def _resilience_enabled() -> bool:
    """F17: флаг ON/OFF (env-only ClassVar, default ON). OFF → байт-в-байт
    прежнее поведение: без PRAGMA и без повторов."""
    return bool(getattr(settings, "SMART_CACHE_LOCK_RESILIENCE_ENABLED", True))


def _is_locked(exc: BaseException) -> bool:
    """F17: True только для `OperationalError` с `locked` в тексте.

    Прочие исключения (в т.ч. OperationalError по другим причинам) не
    ретраятся — прежнее поведение."""
    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()


def _note_lock_exhausted(op_name: str, key: str, attempts: int,
                         exc: BaseException) -> None:
    """F17: явный структурный WARNING при исчерпании попыток + счётчик.

    R17: логируем только MD5-ключ и текст ошибки — payload/сырой ввод НЕ
    попадают в лог. `exc_info=True` сохраняет реальную причину в трейсе."""
    global _lock_exhausted_total
    _lock_exhausted_total += 1
    logger.warning(
        "smart cache: lock exhausted | event=smart_cache_lock_exhausted | "
        "op=%s | key=%s | attempts=%d | error=%s",
        op_name, key, attempts, exc, exc_info=True)


async def _apply_pragmas(db: aiosqlite.Connection) -> None:
    """F17: паритет настроек соединения с `services/database.py:516-520`.

    Тот же порядок и значения: `journal_mode=WAL` → `busy_timeout` →
    `synchronous=NORMAL`. `journal_mode=WAL` — свойство БД (уже активно
    основным соединением), повторное применение безвредно."""
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    await db.execute("PRAGMA synchronous=NORMAL")


class SmartCache:
    """Собственное ленивое aiosqlite-соединение к settings.DB_PATH
    (WAL допускает несколько соединений; close() в on_shutdown).

    EVOL-031: публичный API — только маркерные методы с явным TTL
    (`get_update_marker`/`set_update_marker`) и утилита `build_key`.
    Ответный кеш (`get`/`set`) и legacy-дедуп (`get_dedup`/`set_dedup`)
    удалены вместе с их рубильниками."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or settings.DB_PATH
        self._db: aiosqlite.Connection | None = None

    def build_key(self, slug: str, raw_input: str) -> str:
        """Метод-обёртка над модульной build_key (удобный доступ из хендлеров)."""
        return build_key(slug, raw_input)

    async def _ensure_db(self) -> aiosqlite.Connection | None:
        if self._db is None:
            db: aiosqlite.Connection | None = None
            try:
                db = await aiosqlite.connect(self.db_path)
                db.row_factory = aiosqlite.Row
                # F17: паритет PRAGMA с основным клиентом под флагом.
                if _resilience_enabled():
                    await _apply_pragmas(db)
                await db.execute(
                    "CREATE TABLE IF NOT EXISTS smart_cache ("
                    "key TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                    "created_at REAL NOT NULL)"
                )
                await db.commit()
                self._db = db
            except Exception:
                logger.warning("smart cache: DB init failed — cache disabled", exc_info=True)
                # F17: best-effort close при провале инициализации (утечка fd).
                if db is not None:
                    try:
                        await db.close()
                    except Exception:
                        pass
                self._db = None
        return self._db

    def _sweep_ttl(self) -> int:
        """Порог ленивой чистки (нижняя граница): максимум TTL АКТИВНЫХ фич.

        MCA-22 (fix round-1 M-1): update-identity маркеры живут 24 h — порог
        чистки учитывает их БЕЗУСЛОВНО. EVOL-031: ответные TTL
        (`limits.smart_cache_ttl_seconds`/`limits.chat_dedup_ttl_seconds`)
        удалены вместе с фичами; порог = константа 24 h. Порог — только
        ЛЕНИВАЯ чистка: срок жизни конкретной записи определяет её
        собственный TTL при чтении (маркерные методы)."""
        return _UPDATE_MARKER_SWEEP_TTL

    async def _run_with_lock_retry(
        self,
        op: Callable[[], Awaitable[Any]],
        *,
        op_name: str,
        key: str,
        on_exhausted: Callable[[BaseException], Any],
    ) -> Any:
        """F17: bounded retry только на `database is locked`.

        - Флаг OFF → ровно одна попытка (прежнее поведение, исключение наружу).
        - `locked`: не более `_LOCK_RETRIES` повторов с экспоненциальным
          backoff; перед повтором — best-effort `rollback` (ошибки игнорируются).
        - исчерпание → структурный WARNING + счётчик (`_note_lock_exhausted`)
          и `on_exhausted(exc)` (fail-open семантика вызывающего).
        - не-`locked` исключения не ретраятся — пробрасываются как есть."""
        if not _resilience_enabled():
            return await op()
        attempt = 0
        while True:
            try:
                return await op()
            except Exception as exc:
                if not _is_locked(exc):
                    raise
                if attempt >= _LOCK_RETRIES:
                    _note_lock_exhausted(op_name, key, attempt + 1, exc)
                    return on_exhausted(exc)
                attempt += 1
                db = self._db
                if db is not None:
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                await asyncio.sleep(_LOCK_BACKOFF * (2 ** (attempt - 1)))

    async def _read_once(self, db: aiosqlite.Connection, key: str,
                         ttl_seconds: int) -> str | None:
        cursor = await db.execute(
            "SELECT payload, created_at FROM smart_cache WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row is None:
            logger.info("smart cache: miss | key=%s", key)
            return None
        age = time.monotonic() - row["created_at"]
        if age > ttl_seconds:
            await db.execute("DELETE FROM smart_cache WHERE key = ?", (key,))
            await db.commit()
            logger.info("smart cache: expired | key=%s", key)
            return None
        logger.info("smart cache: hit | key=%s | age=%.0fs", key, age)
        return row["payload"]

    async def _read(self, key: str, ttl_seconds: int) -> str | None:
        db = await self._ensure_db()
        if db is None:
            return None
        try:
            return await self._run_with_lock_retry(
                lambda: self._read_once(db, key, ttl_seconds),
                op_name="get", key=key,
                on_exhausted=lambda exc: None)
        except Exception:
            logger.warning("smart cache: get failed | key=%s", key, exc_info=True)
            return None

    async def _write_once(self, db: aiosqlite.Connection, key: str,
                          payload: str, ttl_seconds: int) -> None:
        now = time.monotonic()
        # Ленивая чистка порогом НЕ НИЖЕ `_sweep_ttl` (24 h): коротко-TTL
        # запись (например, wide-context срез, ~120 с) НЕ выметает
        # 24-часовые update-маркеры (fix: раньше порогом был «сырой» TTL
        # вызывающего). Срок жизни самой записи определяет её TTL при
        # чтении; порог тут — только фоновая уборка.
        sweep_threshold = max(int(ttl_seconds), self._sweep_ttl())
        await db.execute(
            "DELETE FROM smart_cache WHERE created_at < ?",
            (now - sweep_threshold,),
        )
        await db.execute(
            "INSERT OR REPLACE INTO smart_cache (key, payload, created_at) "
            "VALUES (?, ?, ?)",
            (key, payload, now),
        )
        cursor = await db.execute("SELECT COUNT(*) AS c FROM smart_cache")
        row = await cursor.fetchone()
        if row["c"] > hot.get("limits.smart_cache_max_rows", settings.SMART_CACHE_MAX_ROWS):
            await db.execute(
                "DELETE FROM smart_cache WHERE key IN ("
                "SELECT key FROM smart_cache ORDER BY created_at ASC LIMIT ?)",
                (row["c"] - hot.get("limits.smart_cache_max_rows", settings.SMART_CACHE_MAX_ROWS),),
            )
        await db.commit()
        logger.info("smart cache: set | key=%s", key)

    async def _write(self, key: str, payload: str, ttl_seconds: int) -> None:
        db = await self._ensure_db()
        if db is None:
            return
        try:
            await self._run_with_lock_retry(
                lambda: self._write_once(db, key, payload, ttl_seconds),
                op_name="set", key=key,
                on_exhausted=lambda exc: None)
        except Exception:
            logger.warning("smart cache: set failed | key=%s", key, exc_info=True)

    # ── MCA-22 (C7, T-4307; fix round-1 M-1): update-identity маркер ────
    # Специальное хранилище для дедупа Telegram-update'ов (identity-ключ
    # `(chat, tg, revision, user)` из response_freshness). Политика:
    #   * единственный гейт фичи — `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED`
    #     (проверяется вызывающим `response_freshness`);
    #   * TTL — явный аргумент вызывающего (`UPDATE_DEDUP_TTL_SECONDS`
    #     = 24 h);
    #   * `_sweep_ttl` учитывает 24 h безусловно (см. выше); cap
    #     `SMART_CACHE_MAX_ROWS` — существующая политика кеша (вытеснение
    #     старейших — приемлемый компромисс, задокументирован).
    # Синхронизация констант с `response_freshness.UPDATE_DEDUP_TTL_
    # SECONDS` охраняется drift-guard тестом.
    # EVOL-031: маркеры — дедуп СОБЫТИЙ Telegram, не replay ответов;
    # механизм сохранён полностью.

    async def get_update_marker(self, key: str, *,
                                ttl_seconds: int) -> str | None:
        """Чтение маркера с явным TTL. None — не виден/TTL истёк."""
        return await self._read(key, ttl_seconds)

    async def set_update_marker(self, key: str, payload: str, *,
                                ttl_seconds: int) -> None:
        """Запись маркера с явным TTL (24 h для MCA-22 C7)."""
        await self._write(key, payload, ttl_seconds)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None


_cache_instance: SmartCache | None = None


def get_smart_cache() -> SmartCache:
    """Ленивый синглтон (прецедент MediaGroupCaptionBuffer — класс без
    DI-хендлеров). Используется маркерными потребителями: update-дедуп
    (response_freshness), wide-context срез фактчека (factcheck_context)."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SmartCache()
    return _cache_instance


async def close_smart_cache() -> None:
    global _cache_instance
    if _cache_instance is not None:
        await _cache_instance.close()
        _cache_instance = None
