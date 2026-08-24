"""Epic 51 — Exact Match Cache (R51-1/R51-3, Section 59.2, D208/D209/D210).

SQLite-кэш (таблица smart_cache, аддитивная — user_version НЕ поднимается):
ключ MD5(slug + "\\x00" + нормализованный ввод) → СГЕНЕРИРОВАННЫЙ ответ бота.
TTL 1800с, лимит SMART_CACHE_MAX_ROWS (1000), ленивая очистка на каждом set.
Кэшируются ТОЛЬКО успешные финальные тексты (пулы кулдауна/ошибок/фолбеков и
исключения НИКОГДА не пишутся). SMART_CACHE_ENABLED=False → get() всегда None,
set() — no-op (аварийный рубильник, R51-3). Ошибки БД — WARNING + miss
(кэш НЕ роняет хендлер).

Ленивый синглтон без DI-хендлеров (прецедент MediaGroupCaptionBuffer);
close() вызывается в on_shutdown (bot.py).
"""
import hashlib
import logging
import re
import time
import urllib.parse

import aiosqlite

from config.settings import settings

logger = logging.getLogger(__name__)

_NORMALIZERS = {
    "factcheck": "text",
    "search": "text",
    "youtube": "url",
    "web": "url",
    # Epic 60 (67.4, T-499): дедуп одинаковых текстов подряд direct_chat.
    "direct_dedup": "text",
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


class SmartCache:
    """Собственное ленивое aiosqlite-соединение к settings.DB_PATH
    (WAL допускает несколько соединений; close() в on_shutdown)."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or settings.DB_PATH
        self._db: aiosqlite.Connection | None = None

    def build_key(self, slug: str, raw_input: str) -> str:
        """Метод-обёртка над модульной build_key (удобный доступ из хендлеров)."""
        return build_key(slug, raw_input)

    async def _ensure_db(self) -> aiosqlite.Connection | None:
        if self._db is None:
            try:
                self._db = await aiosqlite.connect(self.db_path)
                self._db.row_factory = aiosqlite.Row
                await self._db.execute(
                    "CREATE TABLE IF NOT EXISTS smart_cache ("
                    "key TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                    "created_at REAL NOT NULL)"
                )
                await self._db.commit()
            except Exception:
                logger.warning("smart cache: DB init failed — cache disabled", exc_info=True)
                self._db = None
        return self._db

    def _sweep_ttl(self) -> int:
        """Порог ленивой чистки: максимум TTL АКТИВНЫХ фич (67.4) —
        дедуп-строки не выметаются раньше своего TTL при маленьком
        SMART_CACHE_TTL_SECONDS."""
        ttls = []
        if settings.SMART_CACHE_ENABLED:
            ttls.append(settings.SMART_CACHE_TTL_SECONDS)
        if settings.CHAT_DEDUP_ENABLED:
            ttls.append(settings.CHAT_DEDUP_TTL_SECONDS)
        return max(ttls) if ttls else settings.SMART_CACHE_TTL_SECONDS

    def _active(self, dedup: bool) -> bool:
        """Какой рубильник гейтит операцию: у дедупа — СВОЙ (67.4),
        SMART_CACHE_ENABLED на него не влияет."""
        return (settings.CHAT_DEDUP_ENABLED if dedup
                else settings.SMART_CACHE_ENABLED)

    async def _read(self, key: str, ttl_seconds: int) -> str | None:
        db = await self._ensure_db()
        if db is None:
            return None
        try:
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
        except Exception:
            logger.warning("smart cache: get failed | key=%s", key, exc_info=True)
            return None

    async def _write(self, key: str, payload: str, ttl_seconds: int) -> None:
        db = await self._ensure_db()
        if db is None:
            return
        try:
            now = time.monotonic()
            await db.execute(
                "DELETE FROM smart_cache WHERE created_at < ?",
                (now - ttl_seconds,),
            )
            await db.execute(
                "INSERT OR REPLACE INTO smart_cache (key, payload, created_at) "
                "VALUES (?, ?, ?)",
                (key, payload, now),
            )
            cursor = await db.execute("SELECT COUNT(*) AS c FROM smart_cache")
            row = await cursor.fetchone()
            if row["c"] > settings.SMART_CACHE_MAX_ROWS:
                await db.execute(
                    "DELETE FROM smart_cache WHERE key IN ("
                    "SELECT key FROM smart_cache ORDER BY created_at ASC LIMIT ?)",
                    (row["c"] - settings.SMART_CACHE_MAX_ROWS,),
                )
            await db.commit()
            logger.info("smart cache: set | key=%s", key)
        except Exception:
            logger.warning("smart cache: set failed | key=%s", key, exc_info=True)

    async def get(self, key: str) -> str | None:
        """None = miss/просрочен/выключен. Просроченный → DELETE + None.
        Ошибки БД — WARNING + miss (кэш НЕ роняет хендлер)."""
        if not settings.SMART_CACHE_ENABLED:
            return None
        return await self._read(key, settings.SMART_CACHE_TTL_SECONDS)

    async def set(self, key: str, payload: str) -> None:
        """INSERT OR REPLACE + ленивая очистка: (1) истёкшие по TTL,
        (2) > SMART_CACHE_MAX_ROWS → старейшие. Ошибки БД — WARNING + no-op."""
        if not settings.SMART_CACHE_ENABLED:
            return
        await self._write(key, payload, self._sweep_ttl())

    # ── Epic 60 (67.4, T-499): дедуп direct_chat ─────────────────
    # Свой рубильник CHAT_DEDUP_ENABLED и свой TTL; SMART_CACHE_ENABLED=False
    # дедуп НЕ выключает (разные фичи). Payload — сохранённый ответ;
    # "" — маркер «в прошлый раз ответа не было» → молчание.

    async def get_dedup(self, key: str) -> str | None:
        """Чтение дедуп-записи. None — первый раз/просрочено; "" — прошлый
        раз без ответа (молчание); непустая строка — прошлый ответ."""
        if not settings.CHAT_DEDUP_ENABLED:
            return None
        return await self._read(key, settings.CHAT_DEDUP_TTL_SECONDS)

    async def set_dedup(self, key: str, payload: str) -> None:
        if not settings.CHAT_DEDUP_ENABLED:
            return
        await self._write(key, payload, self._sweep_ttl())

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None


_cache_instance: SmartCache | None = None


def get_smart_cache() -> SmartCache:
    """Ленивый синглтон (прецедент MediaGroupCaptionBuffer — класс без
    DI-хендлеров). SMART_CACHE_ENABLED=False → методы no-op БЕЗ открытия БД."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = SmartCache()
    return _cache_instance


async def close_smart_cache() -> None:
    global _cache_instance
    if _cache_instance is not None:
        await _cache_instance.close()
        _cache_instance = None
