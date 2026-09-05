import asyncio
import datetime
import json
import logging
import re
import time
import aiosqlite
from pathlib import Path

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# ── Тумблер memory.infinite_retention (фаза 2, T-756): гейты TTL/retention ──
# ON = «сырьё и факты памяти не удаляются и не сжимаются по TTL/ретенции»
# (для исторического импорта). Список точек-гейтов (самодокументация):
#   G1 summary_memory.compress_and_purge — extract-only ветка (без сжатия/
#      удаления/архива); пачки импортированных строк (import_key IS NOT NULL)
#      исключаются из extract (get_smart_raw exclude_imported=True);
#      обработанные live-строки помечаются history_processed=1
#      (mark_smart_messages_processed) — повторный крон не пере-экстрактит;
#   G2 summary_memory._purge_archive — skip (архив живёт до OFF);
#   G3 database.purge_expired_graph_facts (:1261) — return 0 без SQL;
#   G4 database.purge_unconfirmed_graph_facts (:1792) — return 0;
#   G5 database.trim_compression_log (:1814) — return 0;
#   G6 memory_maintenance.review — фазы expired/unconfirmed/trim скипаются
#      самими гейтами G3-G5 (merge-фазы — слияние, не удаление — работают).
# Явные команды «забудь»/«/clear» работают всегда (гейтов не имеют).
# Чтение: hot.get("memory.infinite_retention", settings.INFINITE_RETENTION).
# Импорт hot_config циклов не создаёт: hot_config → param_catalog →
# config.settings; param_catalog не импортирует database.py.

_RETENTION_PG_KEY = "memory.infinite_retention"


def _infinite_retention_on() -> bool:
    """ON-состояние тумблера бессрочного хранения (фолбэк False без кэша)."""
    return bool(hot.get(_RETENTION_PG_KEY, settings.INFINITE_RETENTION))

_BUSY_TIMEOUT_MS = 5000          # R46-8: «database is locked» → ждём до 5с
_SCHEMA_VERSION = 1              # PRAGMA user_version; 0 = до Epic 46 (R46-8)
_SCHEMA_VERSION_DIRECT_CHAT = 2  # Epic 50 (58.7): user_version 1→2
_SCHEMA_VERSION_EPIC60 = 3       # Epic 60 (63.3): user_version 2→3
_SCHEMA_VERSION_VIDEO_ORIGINS = 4  # Раунд 3 (3.6/B7): user_version 3→4
_SCHEMA_VERSION_USER_MEMORY = 5  # Раунд 4 (T-713, 3.4.3): user_version 4→5
_SCHEMA_VERSION_CHAT_PROTECTED_FACTS = 6  # Раунд 5 (T-731, 3.2.1): 5→6
_SCHEMA_VERSION_HISTORY_IMPORT = 7  # Фаза 2 (T-758): 6→7 (message_timestamp +
                                    # history_import + smart_messages.import_key)

# Раунд 3 (3.6/B7, T-693): полный список origin для CHECK graph_facts — в ОДНОМ
# месте (CREATE TABLE + пересоздание в _migrate_direct_chat_v2 + миграции v4/v5).
# Включает ВНЕШНИЕ скобки списка IN (формат вставки в «CHECK (origin IN %s)»).
# user_memory (раунд 4, T-713/FR-D2): память-команды «запомни» — явные факты
# юзера/чата, без LLM-экстракции (graph_facts достаточно, nodes/edges НЕ
# создаются — см. spec 3.4.3 п.5).
# history_import (фаза 2, T-758): импортированные GraphRAG-факты истории —
# вес 0.3, expires_at NULL (вечно), message_timestamp = дата сообщения.
_GRAPH_FACT_ORIGINS_SQL = (
    "('chat_history', 'search_fact', 'youtube_content', 'web_content', "
    "'bot_direct_reply', 'voice_transcript', 'video_transcript', 'user_memory', "
    "'history_import')"
)

_EDGE_WEIGHT_CAP = 5             # Epic 60 (66.3/T-459 тема 5): подтверждение
                                 # связи +инкремент, cap 5 — вес не растёт вечно


def row_get(row, key, default=None):
    """Field accessor: if row has .get (dict) — row.get(key, default);
    otherwise row[key], falling back to default on KeyError/IndexError/TypeError."""
    if hasattr(row, "get"):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


class DatabaseService:
    """Async SQLite wrapper using aiosqlite. Manages schema, connections, and all queries."""
    
    _SCHEMA_SQL = """
        CREATE TABLE IF NOT EXISTS user_presence (
            user_id    INTEGER NOT NULL,
            chat_id    INTEGER NOT NULL,
            is_present INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (user_id, chat_id)
        );
        
        CREATE TABLE IF NOT EXISTS message_counters (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            count   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        );
        
        CREATE TABLE IF NOT EXISTS dead_page_posts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            slot      TEXT    NOT NULL,
            date      TEXT    NOT NULL,
            timestamp INTEGER
        );

        CREATE TABLE IF NOT EXISTS channel_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS relay_album_map (
            message_id INTEGER PRIMARY KEY,
            media_group_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_relay_album_media_group ON relay_album_map(media_group_id);

        -- ── SmartModule: Summary (Epic 24) ─────────────────────────
        -- R1: сырьё всех сообщений чата (+author_name — резолв A8 на момент сохранения;
        -- Epic 28: is_forward/forward_source — forward-маркировка, R28-1;
        -- Epic 50 (58.7): tg_message_id — id TG-сообщения для цепочек <Conversation_Thread>)
        CREATE TABLE IF NOT EXISTS smart_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            chat_id         INTEGER NOT NULL,
            text            TEXT,
            reply_to_id     INTEGER,
            timestamp       INTEGER NOT NULL,
            media_type      TEXT NOT NULL DEFAULT 'text',
            author_name     TEXT NOT NULL DEFAULT '',
            is_forward      INTEGER NOT NULL DEFAULT 0,
            forward_source  TEXT NOT NULL DEFAULT '',
            tg_message_id   INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_smart_messages_chat_ts ON smart_messages(chat_id, timestamp);
        -- idx_smart_messages_tg создаётся в _migrate_direct_chat_v2 (старые БД
        -- не имеют колонки tg_message_id до ALTER — индекс тут упал бы)

        -- FTS5 над сырьём L1/L2 (встроенный, без расширений) — L2-RAG + фоллбек
        CREATE VIRTUAL TABLE IF NOT EXISTS smart_messages_fts USING fts5(
            text, content='smart_messages', content_rowid='id', tokenize='unicode61'
        );

        -- L3: архивные факты — обычная таблица (пишется ВСЕГДА при сжатии)
        CREATE TABLE IF NOT EXISTS smart_archive_facts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id   INTEGER NOT NULL,
            fact      TEXT NOT NULL,
            timestamp INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_archive_facts_chat_ts ON smart_archive_facts(chat_id, timestamp);
        CREATE VIRTUAL TABLE IF NOT EXISTS smart_archive_facts_fts USING fts5(
            fact, content='smart_archive_facts', content_rowid='id', tokenize='unicode61'
        );

        -- L3: векторы создаются ЛЕНИВО из MemoryManager.initialize()
        -- (только если sqlite-vec загрузился; dim из конфига EMBEDDING_DIM)

        -- ── GraphRAG: граф знаний (Epic 26/46) ──────────────────
        CREATE TABLE IF NOT EXISTS nodes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER NOT NULL,
            entity_name TEXT NOT NULL,
            entity_type TEXT NOT NULL CHECK (entity_type IN ('user', 'topic', 'event', 'fact')),
            origin      TEXT NOT NULL DEFAULT 'chat_history',
            expires_at  INTEGER,
            UNIQUE (chat_id, entity_name)
        );
        CREATE INDEX IF NOT EXISTS idx_nodes_chat_type ON nodes(chat_id, entity_type);

        CREATE TABLE IF NOT EXISTS edges (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER NOT NULL,
            source_id     INTEGER NOT NULL REFERENCES nodes(id),
            target_id     INTEGER NOT NULL REFERENCES nodes(id),
            relation_type TEXT NOT NULL,
            weight        INTEGER NOT NULL DEFAULT 1,
            last_updated  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            origin        TEXT NOT NULL DEFAULT 'chat_history',
            expires_at    INTEGER,
            UNIQUE (source_id, target_id, relation_type)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
        CREATE INDEX IF NOT EXISTS idx_edges_chat_weight ON edges(chat_id, weight);

        -- GraphRAG v2 (Epic 46, Section 55.3): факты гибридного RAG
        -- (origin/expires_at — ТЗ R46-1; TTL-исключение — ленивое WHERE, D175;
        -- Epic 50 (58.7): CHECK + 'bot_direct_reply' и target_user — пересоздание
        -- в _migrate_direct_chat_v2 для старых БД;
        -- Раунд 3 (3.6/B7): + 'voice_transcript'/'video_transcript' (Epic 67
        -- кружочки и видео-инъекции молча скипались — CHECK их не пускал))
        CREATE TABLE IF NOT EXISTS graph_facts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id    INTEGER NOT NULL,
            fact       TEXT NOT NULL,
            origin     TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN
                       ('chat_history', 'search_fact', 'youtube_content', 'web_content',
                        'bot_direct_reply', 'voice_transcript', 'video_transcript')),
            expires_at INTEGER,
            created_at INTEGER NOT NULL,
            target_user TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin ON graph_facts(chat_id, origin);
        -- idx_graph_facts_target_user создаётся в _migrate_direct_chat_v2
        -- (старые БД не имеют колонки target_user до пересоздания)
        CREATE VIRTUAL TABLE IF NOT EXISTS graph_facts_fts USING fts5(
            fact, content='graph_facts', content_rowid='id', tokenize='unicode61'
        );

        -- ── Smart Cache (Epic 51, Section 59.2, D209) ────────────
        -- Аддитивное хранилище Exact Match Cache; user_version НЕ поднимается
        -- (кэш — новое хранилище, не миграция, R51-5).
        CREATE TABLE IF NOT EXISTS smart_cache (
            key        TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,
            created_at REAL NOT NULL
        );

        -- ── Dead page repost map (Epic 52, Section 61.6.2, T-417) ──
        -- Маппинг «репост Славика (в группе) → dead page бота (id в группе)»
        -- для детекта удаления репоста через InaccessibleMessage. Аддитивно,
        -- CREATE IF NOT EXISTS (миграций нет, R52-8).
        -- Индекс по (chat_id, repost_msg_id) НЕ создаём отдельно — UNIQUE
        -- авто-создаёт его (sqlite_autoindex, L4 review-fix).
        CREATE TABLE IF NOT EXISTS dead_page_repost_map (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id       INTEGER NOT NULL,
            repost_msg_id INTEGER NOT NULL,          -- message_id репоста Славика в группе
            bot_msg_ids   TEXT    NOT NULL,          -- JSON-массив id dead page бота в группе
            created_at    REAL    NOT NULL,          -- time.time()
            UNIQUE (chat_id, repost_msg_id)
        );

        -- ── Раунд 8 (Context-Layer X-Features, spec §3.G1, T-800/T-804) ──
        -- Аддитивные структуры, user_version НЕ поднимается (RUNTIME WARNING,
        -- NFR-4). bot_reply_parents: parent-линк «бот-ответ → на какое сообщение
        -- отвечал» — Conversation_Thread ходит СКВОЗЬ бот-сообщения без
        -- миграции v8; TTL/LRU — тот же паттерн, что bot_replies (63.1).
        CREATE TABLE IF NOT EXISTS bot_reply_parents (
            chat_id INTEGER NOT NULL,
            tg_message_id INTEGER NOT NULL,
            parent_tg_message_id INTEGER,
            last_used_at REAL NOT NULL,
            PRIMARY KEY (chat_id, tg_message_id)
        );
        -- chat_summary_levels (E2/T-804): уровни конспекта — level 1 =
        -- chat_running_summary (широкий не строится из него), level 2 =
        -- «широкий фон» (сжатие ПРЕДЫДУЩЕГО L1 тем же COMPRESS_PROMPT).
        -- msg_count_highwater — raw_count prev-L1 на момент сборки; перезапись
        -- L2 меньшим окном запрещена (highwater-условие). TTL уровня не вводится.
        CREATE TABLE IF NOT EXISTS chat_summary_levels (
            chat_id INTEGER NOT NULL,
            level INTEGER NOT NULL,
            summary TEXT NOT NULL,
            updated_at REAL NOT NULL,
            msg_count_highwater INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (chat_id, level)
        );
    """
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Open connection, create tables, enable WAL mode."""
        self.db = await aiosqlite.connect(str(self.db_path))
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        # Epic 60 (63.1, T-459 тема 9): single-writer — synchronous=NORMAL
        # (WAL-журнал уже есть).
        await self.db.execute("PRAGMA synchronous=NORMAL")
        await self.db.executescript(self._SCHEMA_SQL)
        await self.db.commit()
        await self._migrate_graphrag_v2()
        await self._migrate_direct_chat_v2()   # Epic 50 (58.7): user_version 1→2
        await self._migrate_epic60_v3()        # Epic 60 (63.3): user_version 2→3
        await self._migrate_video_origins_v4() # Раунд 3 (3.6/B7): user_version 3→4
        await self._migrate_user_memory_v5()   # Раунд 4 (T-713): user_version 4→5
        await self._migrate_chat_protected_facts_v6()  # Раунд 5 (T-731): 5→6
        await self._migrate_history_import_v7()  # Фаза 2 (T-758): 6→7

        # Migration: add timestamp column if missing (Dead Page V2)
        try:
            await self.db.execute("ALTER TABLE dead_page_posts ADD COLUMN timestamp INTEGER")
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # Epic 28 (R28-1): forward-marking columns for existing smart_messages tables
        try:
            await self.db.execute(
                "ALTER TABLE smart_messages ADD COLUMN is_forward INTEGER NOT NULL DEFAULT 0"
            )
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists
        try:
            await self.db.execute(
                "ALTER TABLE smart_messages ADD COLUMN forward_source TEXT NOT NULL DEFAULT ''"
            )
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass  # Column already exists

        # GraphRAG (Epic 26): log the actual FK pragma state (Q4).
        # FK constraints are declared as documentation only — we never enable
        # the pragma because it would change semantics of the existing connection.
        try:
            cursor = await self.db.execute("PRAGMA foreign_keys")
            row = await cursor.fetchone()
            logger.debug("PRAGMA foreign_keys = %s (declared as docs, not enforced — Q4)",
                         row[0] if row is not None else None)
        except Exception:
            logger.debug("PRAGMA foreign_keys check failed", exc_info=True)
    
    async def _migrate_graphrag_v2(self) -> None:
        """Идемпотентная миграция Epic 46 (55.3): origin/expires_at в nodes/edges,
        CHECK entity_type + 'fact' (пересоздание nodes с сохранением id),
        PRAGMA user_version = 1. Повторный запуск — no-op."""
        for table in ("nodes", "edges"):
            for sql in (
                f"ALTER TABLE {table} ADD COLUMN origin TEXT NOT NULL DEFAULT 'chat_history'",
                f"ALTER TABLE {table} ADD COLUMN expires_at INTEGER",
            ):
                try:
                    await self.db.execute(sql)
                    await self.db.commit()
                except aiosqlite.OperationalError:
                    pass                        # колонка уже есть
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='nodes'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "'fact'" not in row["sql"]:
            # SQLite не умеет ALTER CHECK — пересоздание с сохранением id (55.1 #4)
            await self.db.executescript(
                "ALTER TABLE nodes RENAME TO nodes_old; "
                "CREATE TABLE nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "chat_id INTEGER NOT NULL, entity_name TEXT NOT NULL, "
                "entity_type TEXT NOT NULL CHECK (entity_type IN "
                "('user','topic','event','fact')), "
                "origin TEXT NOT NULL DEFAULT 'chat_history', expires_at INTEGER, "
                "UNIQUE (chat_id, entity_name)); "
                "INSERT INTO nodes (id, chat_id, entity_name, entity_type, origin, expires_at) "
                "SELECT id, chat_id, entity_name, entity_type, 'chat_history', NULL "
                "FROM nodes_old; "
                "DROP TABLE nodes_old; "
                "CREATE INDEX IF NOT EXISTS idx_nodes_chat_type ON nodes(chat_id, entity_type);"
            )
            await self.db.commit()
        await self.db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        await self.db.commit()

    async def _migrate_direct_chat_v2(self) -> None:
        """Идемпотентная миграция Epic 50 (58.7, D201): (а) graph_facts —
        CHECK-расширение 'bot_direct_reply' + target_user через пересоздание
        (SQLite не умеет ALTER CHECK; id сохраняются → FTS/vec валидны БЕЗ
        пересоздания); (б) smart_messages.tg_message_id + индекс; (в)
        PRAGMA user_version = 2. Повторный запуск — no-op (guard + PRAGMA).
        Прецедент _migrate_graphrag_v2 (55.3)."""
        # (б) tg_message_id — ALTER для старых БД (новая схема уже имеет колонку)
        try:
            await self.db.execute("ALTER TABLE smart_messages ADD COLUMN tg_message_id INTEGER")
            await self.db.commit()
        except aiosqlite.OperationalError:
            pass                        # колонка уже есть
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_smart_messages_tg ON smart_messages(chat_id, tg_message_id)")
        await self.db.commit()
        # (а) graph_facts: CHECK-расширение через пересоздание
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "bot_direct_reply" not in row["sql"]:
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_old; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, created_at, target_user) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, NULL FROM graph_facts_old; "
                "DROP TABLE graph_facts_old; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user ON graph_facts(chat_id, target_user);"
            )
            await self.db.commit()
        # (в)
        await self.db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION_DIRECT_CHAT}")
        await self.db.commit()

    async def _migrate_epic60_v3(self) -> None:
        """Идемпотентная миграция Epic 60 (63.3, D245): user_version 2→3.
        ТОЛЬКО CREATE/ALTER (никаких пересозданий с потерей данных; guard по
        CREATE IF NOT EXISTS + try/except OperationalError на ALTER):
        1. throttle_state (63.1) + индекс;
        2. bot_replies (63.1 — персистентный _bot_replies, TTL+LRU);
        3. user_prefs (65.5: tone-пресет; стачка живёт в throttle_state
           scope='direct_silence' — 65.3);
        4. embedding_cache (64.4);
        5. chat_running_summary (64.6);
        6. graph_fact_compressions (64.2 — лог сжатий);
        7. protected_facts (65.10);
        8. graph_facts: weight/status/last_confirmed_at (backfill=created_at,
           66.3)/supersedes — НЕ пересоздавать CHECK (origins не меняются);
        9. edges: created_at (backfill из strftime('%s', last_updated) — 66.3);
        10. PRAGMA user_version = 3.
        Повторный запуск — no-op. Прецеденты _migrate_graphrag_v2 /
        _migrate_direct_chat_v2."""
        await self.db.executescript(
            "CREATE TABLE IF NOT EXISTS throttle_state ("
            "scope TEXT NOT NULL, chat_id INTEGER NOT NULL, "
            "user_id INTEGER NOT NULL, burst_left INTEGER, "
            "last_ts REAL NOT NULL, "
            "PRIMARY KEY (scope, chat_id, user_id)); "
            "CREATE INDEX IF NOT EXISTS idx_throttle_state_ts "
            "ON throttle_state(last_ts); "
            "CREATE TABLE IF NOT EXISTS bot_replies ("
            "chat_id INTEGER, tg_message_id INTEGER, text TEXT NOT NULL, "
            "last_used_at REAL NOT NULL, "
            "PRIMARY KEY (chat_id, tg_message_id)); "
            "CREATE TABLE IF NOT EXISTS user_prefs ("
            "chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
            "tone_preset TEXT, PRIMARY KEY (chat_id, user_id)); "
            "CREATE TABLE IF NOT EXISTS embedding_cache ("
            "text_hash TEXT PRIMARY KEY, text TEXT NOT NULL, "
            "vector TEXT NOT NULL, dim INTEGER NOT NULL, "
            "created_at REAL NOT NULL, last_used_at REAL NOT NULL); "
            "CREATE INDEX IF NOT EXISTS idx_embedding_cache_lru "
            "ON embedding_cache(last_used_at); "
            "CREATE TABLE IF NOT EXISTS chat_running_summary ("
            "chat_id INTEGER PRIMARY KEY, summary TEXT NOT NULL, "
            "window_start_ts INTEGER NOT NULL, window_end_ts INTEGER NOT NULL, "
            "raw_count INTEGER NOT NULL, created_at REAL NOT NULL, "
            "expires_at REAL NOT NULL); "
            "CREATE TABLE IF NOT EXISTS graph_fact_compressions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
            "fact_id INTEGER, fact_before TEXT NOT NULL, fact_after TEXT, "
            "reason TEXT NOT NULL, created_at REAL NOT NULL); "
            "CREATE TABLE IF NOT EXISTS protected_facts ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
            "user_name TEXT NOT NULL, fact TEXT NOT NULL, "
            "created_at REAL NOT NULL, UNIQUE (chat_id, user_name, fact));"
        )
        await self.db.commit()
        for sql in (
            "ALTER TABLE graph_facts ADD COLUMN weight REAL NOT NULL DEFAULT 0.5",
            "ALTER TABLE graph_facts ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'",
            "ALTER TABLE graph_facts ADD COLUMN last_confirmed_at INTEGER",
            "ALTER TABLE graph_facts ADD COLUMN supersedes INTEGER",
            "ALTER TABLE edges ADD COLUMN created_at INTEGER",
        ):
            try:
                await self.db.execute(sql)
                await self.db.commit()
            except aiosqlite.OperationalError:
                pass                        # колонка уже есть (повторный запуск)
        # backfill: last_confirmed_at = created_at (66.3); edges.created_at —
        # из существующей колонки last_updated ('YYYY-MM-DD HH:MM:SS' UTC).
        await self.db.execute(
            "UPDATE graph_facts SET last_confirmed_at = created_at "
            "WHERE last_confirmed_at IS NULL")
        await self.db.execute(
            "UPDATE edges SET created_at = CAST(strftime('%s', last_updated) AS INTEGER) "
            "WHERE created_at IS NULL")
        await self.db.commit()
        await self.db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION_EPIC60}")
        await self.db.commit()

    async def _migrate_video_origins_v4(self) -> None:
        """Раунд 3 (3.6/B7, T-693): CHECK graph_facts.origin + 'voice_transcript'/
        'video_transcript' через пересоздание с сохранением ВСЕХ колонок
        (id, chat_id, fact, origin, expires_at, created_at, target_user,
        weight, status, last_confirmed_at, supersedes — статусы/веса Epic 60
        добавлялись отдельными ALTER, в rebuild включаем) + INSERT…SELECT +
        DROP old + индексы; PRAGMA user_version = 4. Повторный запуск — no-op
        (guard '"video_transcript" not in sql' + PRAGMA). FTS5 graph_facts_fts
        НЕ пересоздаётся (content-таблица пересоздана с теми же rowid —
        прецедент D201; content='graph_facts' резолвится динамически).
        Заметка (3.6): PostgreSQL-схемы graph_facts СЕЙЧАС НЕТ (pg_db.py —
        только bot_settings/bot_roles/bot_admins/uptime_events); эпик 86
        «GraphRAG→PG» — будущий, при его реализации origin-список
        синхронизировать."""
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "video_transcript" not in row["sql"]:
            logger.info(
                "[database] migration v4: graph_facts origins rebuild "
                "(voice/video_transcript)")
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_old; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT, "
                "weight REAL NOT NULL DEFAULT 0.5, "
                "status TEXT NOT NULL DEFAULT 'confirmed', "
                "last_confirmed_at INTEGER, supersedes INTEGER); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
                "created_at, target_user, weight, status, last_confirmed_at, "
                "supersedes) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, "
                "target_user, weight, status, last_confirmed_at, supersedes "
                "FROM graph_facts_old; "
                "DROP TABLE graph_facts_old; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin "
                "ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user "
                "ON graph_facts(chat_id, target_user);"
            )
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_VIDEO_ORIGINS}")
        await self.db.commit()

    async def _migrate_user_memory_v5(self) -> None:
        """Раунд 4 (T-713, spec 3.4.3): CHECK graph_facts.origin + 'user_memory'
        через пересоздание с сохранением ВСЕХ колонок (точная копия паттерна
        _migrate_video_origins_v4): guard по sqlite_master ('user_memory' ещё
        не в CHECK) → ALTER RENAME + CREATE (origin-список из
        _GRAPH_FACT_ORIGINS_SQL — единое место) + INSERT…SELECT + DROP old +
        индексы; PRAGMA user_version = 5. Повторный запуск — no-op. FTS5
        graph_facts_fts НЕ пересоздаётся (rowid сохранены — прецедент D201).
        Новых таблиц нет. PostgreSQL-схемы graph_facts по-прежнему НЕТ
        (pg_db.py — только bot_settings/роли/админы/uptime_events); при
        реализации эпика 86 origin-список синхронизировать."""
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "user_memory" not in row["sql"]:
            logger.info(
                "[database] migration v5: graph_facts origins rebuild "
                "(user_memory)")
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_old; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT, "
                "weight REAL NOT NULL DEFAULT 0.5, "
                "status TEXT NOT NULL DEFAULT 'confirmed', "
                "last_confirmed_at INTEGER, supersedes INTEGER); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
                "created_at, target_user, weight, status, last_confirmed_at, "
                "supersedes) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, "
                "target_user, weight, status, last_confirmed_at, supersedes "
                "FROM graph_facts_old; "
                "DROP TABLE graph_facts_old; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin "
                "ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user "
                "ON graph_facts(chat_id, target_user);"
            )
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_USER_MEMORY}")
        await self.db.commit()

    async def _migrate_chat_protected_facts_v6(self) -> None:
        """Раунд 5 (T-731, spec 3.2.1, FR-C1): protected_facts.user_name →
        nullable (чат-уровневые факты — «лор чата», user_name NULL, видны всем
        юзерам чата) через пересоздание с сохранением id (прецедент D201 /
        _migrate_user_memory_v5): guard по sqlite_master ('user_name TEXT NOT
        NULL' ещё в CREATE) → ALTER RENAME + CREATE (user_name TEXT без NOT
        NULL; UNIQUE (chat_id, user_name, fact) сохраняется) + частичный
        уникальный индекс idx_protected_facts_chat_level (чат-уровневые
        уникальны по (chat_id, fact): в SQLite NULL != NULL, обычный UNIQUE
        их не защищает от дублей) + INSERT…SELECT + DROP old; PRAGMA
        user_version = 6. Повторный запуск — no-op (guard false → только
        PRAGMA). Старые данные — только user_name NOT NULL → конфликтов при
        копировании нет; id сохраняются (FTS/ссылки не затронуты).
        CREATE в _migrate_epic60_v3 НЕ меняется (свежая БД проходит v3→v6;
        rebuild пустой таблицы — дешёвый)."""
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='protected_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "user_name TEXT NOT NULL" in row["sql"]:
            logger.info(
                "[database] migration v6: protected_facts rebuild "
                "(chat-level user_name NULL)")
            await self.db.executescript(
                "ALTER TABLE protected_facts RENAME TO protected_facts_old; "
                "CREATE TABLE protected_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "user_name TEXT, fact TEXT NOT NULL, created_at REAL NOT NULL, "
                "UNIQUE (chat_id, user_name, fact)); "
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_protected_facts_chat_level "
                "ON protected_facts(chat_id, fact) WHERE user_name IS NULL; "
                "INSERT INTO protected_facts (id, chat_id, user_name, fact, created_at) "
                "SELECT id, chat_id, user_name, fact, created_at "
                "FROM protected_facts_old; "
                "DROP TABLE protected_facts_old;"
            )
            await self.db.commit()
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_CHAT_PROTECTED_FACTS}")
        await self.db.commit()

    async def _migrate_history_import_v7(self) -> None:
        """Фаза 2 (T-758, spec 3.4/FR-6): user_version 6→7. Три независимые
        части, каждая идемпотентная (повторный запуск — no-op, только PRAGMA):

        (а) graph_facts rebuild по паттерну _migrate_user_memory_v5 (D201):
        + колонка message_timestamp INTEGER (nullable), CHECK origin +=
        'history_import' (список из _GRAPH_FACT_ORIGINS_SQL — единое место),
        все 11 существующих колонок сохраняются, INSERT…SELECT копирует
        message_timestamp = NULL → backfill = created_at (рендер COALESCE не
        меняет вывода для существующих фактов); индексы (chat_origin,
        target_user) воссоздаются; + частичный UNIQUE-индекс
        idx_graph_facts_history_import (chat_id, fact, message_timestamp) WHERE
        origin='history_import' AND message_timestamp IS NOT NULL —
        идемпотентность Graph-этапа/переноса дельты. FTS5 graph_facts_fts НЕ
        пересоздаётся (rowid сохранены — прецедент D201/v4/v5). GUARD по
        колонке message_timestamp (в sqlite_master CREATE-тексте): свежая БД
        после v5-rebuild уже содержит 'history_import' в CHECK (константа
        пополнена), но НЕ колонку — guard по origin не сработал бы.

        (б) smart_messages: import_key TEXT + history_processed INTEGER NOT
        NULL DEFAULT 0 — только ALTER-веткой (CREATE TABLE не трогаем;
        прецедент tg_message_id) + частичные индексы:
        idx_smart_messages_import_key (UNIQUE, WHERE import_key IS NOT NULL —
        идемпотентность FTS-импорта) и idx_smart_messages_history_pending
        (chat_id, history_processed, WHERE history_processed = 0 — выборка
        пачек Graph-воркера). Внешняя FTS5 smart_messages_fts не затрагивается
        (rebuild не происходит — rowid валидны).

        (в) PRAGMA user_version = 7.
        """
        cursor = await self.db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        )
        row = await cursor.fetchone()
        if row and row["sql"] and "message_timestamp" not in row["sql"]:
            logger.info(
                "[database] migration v7: graph_facts rebuild "
                "(message_timestamp + history_import origin)")
            await self.db.executescript(
                "ALTER TABLE graph_facts RENAME TO graph_facts_old; "
                "CREATE TABLE graph_facts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, "
                "fact TEXT NOT NULL, "
                "origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN "
                + _GRAPH_FACT_ORIGINS_SQL + "), "
                "expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT, "
                "weight REAL NOT NULL DEFAULT 0.5, "
                "status TEXT NOT NULL DEFAULT 'confirmed', "
                "last_confirmed_at INTEGER, supersedes INTEGER, "
                "message_timestamp INTEGER); "
                "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
                "created_at, target_user, weight, status, last_confirmed_at, "
                "supersedes, message_timestamp) "
                "SELECT id, chat_id, fact, origin, expires_at, created_at, "
                "target_user, weight, status, last_confirmed_at, supersedes, NULL "
                "FROM graph_facts_old; "
                "DROP TABLE graph_facts_old; "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin "
                "ON graph_facts(chat_id, origin); "
                "CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user "
                "ON graph_facts(chat_id, target_user);"
            )
            # backfill: существующие факты рендерятся как раньше (COALESCE)
            await self.db.execute(
                "UPDATE graph_facts SET message_timestamp = created_at "
                "WHERE message_timestamp IS NULL")
            await self.db.commit()
        # частичный UNIQUE-индекс идемпотентности (после backfill — guard)
        await self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_facts_history_import "
            "ON graph_facts(chat_id, fact, message_timestamp) "
            "WHERE origin='history_import' AND message_timestamp IS NOT NULL")
        await self.db.commit()
        # (б) smart_messages: ALTER-ветка (как tg_message_id; fresh CREATE не трогаем)
        for alter_sql in (
            "ALTER TABLE smart_messages ADD COLUMN import_key TEXT",
            "ALTER TABLE smart_messages ADD COLUMN history_processed "
            "INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                await self.db.execute(alter_sql)
                await self.db.commit()
            except aiosqlite.OperationalError:
                pass                        # колонка уже есть (повторный запуск)
        await self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_smart_messages_import_key "
            "ON smart_messages(import_key) WHERE import_key IS NOT NULL")
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_smart_messages_history_pending "
            "ON smart_messages(chat_id, history_processed) "
            "WHERE history_processed = 0")
        await self.db.commit()
        # (в)
        await self.db.execute(
            f"PRAGMA user_version = {_SCHEMA_VERSION_HISTORY_IMPORT}")
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()
    
    # ── Slava Presence ──────────────────────────────────
    
    async def set_presence(self, user_id: int, chat_id: int, present: bool) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO user_presence (user_id, chat_id, is_present) VALUES (?, ?, ?)",
            (user_id, chat_id, 1 if present else 0)
        )
        await self.db.commit()
    
    async def is_present(self, user_id: int, chat_id: int) -> bool:
        cursor = await self.db.execute(
            "SELECT is_present FROM user_presence WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        row = await cursor.fetchone()
        return bool(row and row["is_present"])
    
    async def get_present_chats(self, user_id: int) -> list[int]:
        cursor = await self.db.execute(
            "SELECT chat_id FROM user_presence WHERE user_id = ? AND is_present = 1",
            (user_id,)
        )
        rows = await cursor.fetchall()
        return [row["chat_id"] for row in rows]
    
    # ── Message Counters ────────────────────────────────
    
    async def increment_and_get_count(self, chat_id: int, user_id: int) -> int:
        """Atomically increment counter and return new value."""
        async with self._lock:
            await self.db.execute(
                "INSERT INTO message_counters (chat_id, user_id, count) "
                "VALUES (?, ?, 1) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1",
                (chat_id, user_id)
            )
            await self.db.commit()
            cursor = await self.db.execute(
                "SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id)
            )
            row = await cursor.fetchone()
            return row["count"] if row else 0
    
    async def get_count(self, chat_id: int, user_id: int) -> int:
        cursor = await self.db.execute(
            "SELECT count FROM message_counters WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        row = await cursor.fetchone()
        return row["count"] if row else 0
    
    # ── Dead Page Posts ─────────────────────────────────

    async def was_dead_page_recently(self, chat_id: int, cooldown_seconds: int) -> bool:
        """Check if a dead page was posted in this chat within the last N seconds."""
        cutoff = int(time.time()) - cooldown_seconds
        cursor = await self.db.execute(
            "SELECT 1 FROM dead_page_posts WHERE chat_id = ? AND slot = 'repost' AND timestamp > ?",
            (chat_id, cutoff)
        )
        row = await cursor.fetchone()
        return row is not None

    async def record_dead_page_post(self, chat_id: int, slot: str) -> None:
        """Record that a dead page post was made."""
        today = datetime.date.today().isoformat()
        now_ts = int(time.time())
        await self.db.execute(
            "INSERT INTO dead_page_posts (chat_id, slot, date, timestamp) VALUES (?, ?, ?, ?)",
            (chat_id, slot, today, now_ts)
        )
        await self.db.commit()

    # ── Леха activity (код-ключи alan_last_msg:* не переименовываются) ──

    async def get_alan_last_message_ts(self, chat_id: int) -> float | None:
        """Get the timestamp of Леха's last message in a chat."""
        key = f"alan_last_msg:{chat_id}"
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            try:
                return float(row["value"])
            except (ValueError, TypeError):
                return None
        return None

    async def set_alan_last_message_ts(self, chat_id: int, timestamp: float) -> None:
        """Record the timestamp of Леха's last message in a chat."""
        key = f"alan_last_msg:{chat_id}"
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (key, str(timestamp))
        )
        await self.db.commit()

    # ── Channel State ───────────────────────────────────

    async def get_last_known_message_id(self, channel_id: int = 0) -> int | None:
        """Get the last known message_id in the relay channel."""
        key = f"last_msg_id:{channel_id}" if channel_id else "last_known_message_id"
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            return int(row["value"])
        return None

    async def update_last_known_message_id(self, msg_id: int, channel_id: int = 0) -> None:
        """Update the last known message_id in the relay channel."""
        key = f"last_msg_id:{channel_id}" if channel_id else "last_known_message_id"
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (key, str(msg_id))
        )
        await self.db.commit()

    # ── Dead Page Anti-Repeat (Epic 22 / D54) ─────────────

    async def get_dead_page_last_sent(self, chat_id: int) -> int | None:
        """Primary relay-channel msg_id forwarded into this chat last time (anti-repeat).

        Uses channel_state key `dead_page_last_sent:{chat_id}`. Returns None when
        the key is missing or holds a broken (non-int) value.
        """
        key = f"dead_page_last_sent:{chat_id}"
        cursor = await self.db.execute(
            "SELECT value FROM channel_state WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row:
            try:
                return int(row["value"])
            except (ValueError, TypeError):
                return None
        return None

    async def set_dead_page_last_sent(self, chat_id: int, msg_id: int) -> None:
        """Record the primary relay-channel msg_id forwarded into this chat."""
        key = f"dead_page_last_sent:{chat_id}"
        await self.db.execute(
            "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
            (key, str(msg_id)),
        )
        await self.db.commit()

    # ── Dead Page Repost Map (Epic 52 / T-417, Section 61.6.2) ─────

    _DEAD_PAGE_REPOST_MAP_TTL_SECONDS = 86400   # 24ч
    _DEAD_PAGE_REPOST_MAP_CAP = 500             # cap-очистка

    async def record_dead_page_repost_map(
        self, chat_id: int, repost_msg_id: int, bot_msg_ids: list[int]
    ) -> None:
        """INSERT OR REPLACE маппинга {репост Славика → dead page бота}.

        Ленивая TTL-очистка (> 24ч) + cap-очистка (оставить последние 500 по id).
        """
        now = time.time()
        await self.db.execute(
            "DELETE FROM dead_page_repost_map WHERE created_at < ?",
            (now - self._DEAD_PAGE_REPOST_MAP_TTL_SECONDS,),
        )
        await self.db.execute(
            "INSERT OR REPLACE INTO dead_page_repost_map "
            "(chat_id, repost_msg_id, bot_msg_ids, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, repost_msg_id, json.dumps(bot_msg_ids), now),
        )
        # cap-очистка ПОСЛЕ вставки: оставить последние CAP по id (иначе
        # количество осциллирует 500/501 на границе)
        await self.db.execute(
            "DELETE FROM dead_page_repost_map WHERE id NOT IN "
            "(SELECT id FROM dead_page_repost_map ORDER BY id DESC LIMIT ?)",
            (self._DEAD_PAGE_REPOST_MAP_CAP,),
        )
        await self.db.commit()
        logger.info(
            "[dead_page_repost_map] recorded | chat=%s | repost_msg_id=%s | bot_ids=%s",
            chat_id, repost_msg_id, bot_msg_ids,
        )

    async def get_dead_page_repost_map(self, chat_id: int, repost_msg_id: int) -> list[int] | None:
        """bot_msg_ids по (chat_id, repost_msg_id); None = маппинга нет."""
        cursor = await self.db.execute(
            "SELECT bot_msg_ids FROM dead_page_repost_map "
            "WHERE chat_id = ? AND repost_msg_id = ?",
            (chat_id, repost_msg_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["bot_msg_ids"])
        except (ValueError, TypeError):
            logger.warning(
                "[dead_page_repost_map] broken JSON | chat=%s | repost_msg_id=%s",
                chat_id, repost_msg_id,
            )
            return None

    async def delete_dead_page_repost_map(self, chat_id: int, repost_msg_id: int) -> None:
        """Снять маппинг (срабатывание ровно один раз на пару (чат, репост))."""
        await self.db.execute(
            "DELETE FROM dead_page_repost_map WHERE chat_id = ? AND repost_msg_id = ?",
            (chat_id, repost_msg_id),
        )
        await self.db.commit()

    async def try_claim_dead_page_repost_map(
        self, chat_id: int, repost_msg_id: int
    ) -> bool:
        """Атомарно снять маппинг; True = claim выполнен, False = уже снят.

        M2 (review-fix): DELETE + rowcount — при двойном reply на удалённый
        репост в одном цикле оба хендлера успевают прочитать маппинг до
        delete, но фразу отправляет ровно первый claimer.
        """
        cursor = await self.db.execute(
            "DELETE FROM dead_page_repost_map WHERE chat_id = ? AND repost_msg_id = ?",
            (chat_id, repost_msg_id),
        )
        await self.db.commit()
        return cursor.rowcount == 1

    # ── Slavic Photo Counter (Epic 12) ──

    async def slavic_photo_count_tick(self, chat_id: int, interval: int) -> bool:
        """Increment Slava's photo counter. Returns True if photo should be sent.

        Counter auto-resets after reaching the configured interval.
        Uses channel_state key: slavic_photo:{chat_id}
        """
        key = f"slavic_photo:{chat_id}"
        logger.debug("slavic_photo_count_tick: key=%s interval=%d", key, interval)
        async with self._lock:
            cursor = await self.db.execute(
                "SELECT value FROM channel_state WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            current = int(row["value"]) if row else 0
            logger.debug("slavic_photo_count_tick: current=%d", current)
            new_count = current + 1
            logger.debug("slavic_photo_count_tick: new_count=%d", new_count)
            if new_count >= interval:
                logger.debug("slavic_photo_count_tick: interval reached, resetting counter")
                await self.db.execute(
                    "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
                    (key, "0"),
                )
                await self.db.commit()
                return True
            else:
                logger.debug("slavic_photo_count_tick: incrementing counter to %d", new_count)
                await self.db.execute(
                    "INSERT OR REPLACE INTO channel_state (key, value) VALUES (?, ?)",
                    (key, str(new_count)),
                )
                await self.db.commit()
                return False

    # ── Relay Album Map (Epic 14) ──────────────────────

    async def save_relay_album_map(self, message_id: int, media_group_id: str) -> None:
        """Save media_group_id for a relay channel message. Idempotent."""
        await self.db.execute(
            "INSERT OR REPLACE INTO relay_album_map (message_id, media_group_id) VALUES (?, ?)",
            (message_id, media_group_id),
        )
        await self.db.commit()

    async def get_relay_media_group_id(self, message_id: int) -> str | None:
        """Get media_group_id for a relay channel message. Returns None if not found."""
        cursor = await self.db.execute(
            "SELECT media_group_id FROM relay_album_map WHERE message_id = ?",
            (message_id,),
        )
        row = await cursor.fetchone()
        return row["media_group_id"] if row else None

    async def get_relay_album_message_ids(self, media_group_id: str) -> list[int]:
        """Get all message_ids belonging to the same media group, sorted ascending."""
        cursor = await self.db.execute(
            "SELECT message_id FROM relay_album_map WHERE media_group_id = ? ORDER BY message_id ASC",
            (media_group_id,),
        )
        rows = await cursor.fetchall()
        return [row["message_id"] for row in rows]

    # ── SmartModule: Summary (Epic 24) ──────────────────

    async def save_smart_message(
        self,
        user_id: int,
        chat_id: int,
        text: str | None,
        reply_to_id: int | None,
        timestamp: int,
        media_type: str,
        author_name: str,
        is_forward: bool = False,
        forward_source: str = "",
        message_id: int | None = None,
    ) -> int:
        """Insert a chat message into smart_messages + FTS index. Returns the new row id.
        Epic 50 (58.7, D201): message_id = TG message_id (для reply-цепочек
        <Conversation_Thread>); None → NULL (легаси-вызовы без изменений)."""
        cursor = await self.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source, tg_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name,
             int(is_forward), forward_source, message_id),
        )
        row_id = cursor.lastrowid
        if text:
            await self.db.execute(
                "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
                (row_id, text),
            )
        await self.db.commit()
        return row_id

    async def update_smart_message_text(self, chat_id: int, tg_message_id: int,
                                        text: str) -> int:
        """Epic 67 (Section 71.3, D267): инъекция транскрипта в smart_messages
        вместо плейсхолдера «[голосовое]». Матч по (chat_id, tg_message_id);
        возвращает число обновлённых строк (0 = observer не сохранил — no-op).
        FTS-индекс пересобирается под новый текст."""
        cursor = await self.db.execute(
            "SELECT id, text FROM smart_messages WHERE chat_id = ? AND tg_message_id = ?",
            (chat_id, tg_message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return 0
        row_id = row["id"]
        old_text = row["text"] or ""
        await self.db.execute(
            "UPDATE smart_messages SET text = ? WHERE id = ?", (text, row_id))
        # FTS: DELETE несуществующего rowid в FTS5 даёт «malformed» — трогаем
        # индекс только если строка там была (текст был непустой).
        if old_text:
            await self.db.execute(
                "DELETE FROM smart_messages_fts WHERE rowid = ?", (row_id,))
        if text:
            await self.db.execute(
                "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
                (row_id, text),
            )
        await self.db.commit()
        return 1

    async def get_smart_window(self, chat_id: int, since_ts: int, limit: int) -> list:
        """L1: messages within the generation window (timestamp >= since_ts), ASC order."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source, tg_message_id "
            "FROM smart_messages WHERE chat_id = ? AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (chat_id, since_ts, limit),
        )
        rows = await cursor.fetchall()
        rows.reverse()
        return rows

    async def get_smart_raw(self, chat_id: int, older_than_ts: int, limit: int,
                            exclude_imported: bool = False,
                            exclude_processed: bool = False) -> list:
        """L2/сжатие: messages older than the cutoff timestamp, ASC order.
        Фаза 2 (T-756, G1): exclude_imported=True → + AND import_key IS NULL
        (импортированные строки графом пополняются ТОЛЬКО Graph-воркером по
        history_processed — крон-LLM-экстракция по ним не гоняется);
        exclude_processed=True → + AND history_processed = 0 (extract-only:
        live-строки после успешной экстракции помечаются
        mark_smart_messages_processed — повторный крон их не пере-экстрактит)."""
        sql = (
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, "
            "author_name, is_forward, forward_source, tg_message_id "
            "FROM smart_messages WHERE chat_id = ? AND timestamp < ? "
        )
        if exclude_imported:
            sql += "AND import_key IS NULL "
        if exclude_processed:
            sql += "AND history_processed = 0 "
        sql += "ORDER BY timestamp ASC LIMIT ?"
        cursor = await self.db.execute(sql, (chat_id, older_than_ts, limit))
        return await cursor.fetchall()

    async def get_recent_messages(self, chat_id: int, limit: int) -> list:
        """Epic 65: ПОСЛЕДНИЕ limit сообщений чата, хронологически (ASC).
        Для chat_context фактчека/поиска (обогащение контекста вокруг цели)."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source, tg_message_id "
            "FROM smart_messages WHERE chat_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        rows.reverse()                     # DESC-выборка → хронологический порядок
        return rows


    async def get_smart_message_by_tg_id(self, chat_id: int, tg_message_id: int):
        """Epic 50 (58.7, D201): строка smart_messages по TG message_id
        (рекурсия reply-цепочек <Conversation_Thread>); None — нет записи."""
        cursor = await self.db.execute(
            "SELECT id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, "
            "is_forward, forward_source, tg_message_id "
            "FROM smart_messages WHERE chat_id = ? AND tg_message_id = ?",
            (chat_id, tg_message_id),
        )
        return await cursor.fetchone()

    async def delete_smart_messages_older_than(self, chat_id: int, cutoff_ts: int) -> int:
        """Delete messages (+ FTS rows) older than cutoff. Returns count of deleted rows."""
        await self.db.execute(
            "DELETE FROM smart_messages_fts WHERE rowid IN "
            "(SELECT id FROM smart_messages WHERE chat_id = ? AND timestamp < ? "
            "AND text IS NOT NULL AND text != '')",
            (chat_id, cutoff_ts),
        )
        cursor = await self.db.execute(
            "DELETE FROM smart_messages WHERE chat_id = ? AND timestamp < ?",
            (chat_id, cutoff_ts),
        )
        await self.db.commit()
        return cursor.rowcount

    async def delete_smart_messages_by_ids(self, chat_id: int, ids: list[int]) -> int:
        """Delete specific messages (+ FTS rows) of a chat. Returns count deleted."""
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        await self.db.execute(
            f"DELETE FROM smart_messages_fts WHERE rowid IN "
            f"(SELECT id FROM smart_messages WHERE chat_id = ? AND id IN ({placeholders}) "
            "AND text IS NOT NULL AND text != '')",
            [chat_id, *ids],
        )
        cursor = await self.db.execute(
            f"DELETE FROM smart_messages WHERE chat_id = ? AND id IN ({placeholders})",
            [chat_id, *ids],
        )
        await self.db.commit()
        return cursor.rowcount

    async def mark_smart_messages_processed(self, chat_id: int,
                                            ids: list[int]) -> int:
        """Фаза 2 (T-756/G1, fix): маркер обработанности live-строк
        (history_processed=1) ПОСЛЕ успешной extract-only экстракции окна —
        повторный крон (4×/день) не пере-экстрактит те же строки вечно
        (инфляция весов рёбер). Только live-строки (import_key IS NULL):
        выборка extract-ветки и выборка Graph-воркера (import_key IS NOT
        NULL AND history_processed = 0) не пересекаются. Returns count."""
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        cursor = await self.db.execute(
            f"UPDATE smart_messages SET history_processed = 1 "
            f"WHERE chat_id = ? AND import_key IS NULL "
            f"AND id IN ({placeholders})",
            [chat_id, *ids])
        await self.db.commit()
        return cursor.rowcount

    async def save_archive_fact(self, chat_id: int, fact: str, timestamp: int) -> int:
        """L3: save a compressed archive fact (+ FTS row). Returns the new fact id."""
        cursor = await self.db.execute(
            "INSERT INTO smart_archive_facts (chat_id, fact, timestamp) VALUES (?, ?, ?)",
            (chat_id, fact, timestamp),
        )
        fact_id = cursor.lastrowid
        await self.db.execute(
            "INSERT INTO smart_archive_facts_fts(rowid, fact) VALUES (?, ?)",
            (fact_id, fact),
        )
        await self.db.commit()
        return fact_id

    async def delete_archive_facts_older_than(self, chat_id: int, cutoff_ts: int) -> int:
        """Delete archive facts (+ FTS rows) older than cutoff. Returns count deleted."""
        await self.db.execute(
            "DELETE FROM smart_archive_facts_fts WHERE rowid IN "
            "(SELECT id FROM smart_archive_facts WHERE chat_id = ? AND timestamp < ?)",
            (chat_id, cutoff_ts),
        )
        cursor = await self.db.execute(
            "DELETE FROM smart_archive_facts WHERE chat_id = ? AND timestamp < ?",
            (chat_id, cutoff_ts),
        )
        await self.db.commit()
        return cursor.rowcount

    async def search_messages_fts(self, chat_id: int, match_query: str, limit: int) -> list:
        """L2-RAG / фоллбек: FTS5 search over raw messages, ordered by rank."""
        cursor = await self.db.execute(
            "SELECT m.id, m.user_id, m.chat_id, m.text, m.reply_to_id, m.timestamp, "
            "m.media_type, m.author_name, m.is_forward, m.forward_source "
            "FROM smart_messages_fts JOIN smart_messages m ON m.id = smart_messages_fts.rowid "
            "WHERE smart_messages_fts MATCH ? AND m.chat_id = ? "
            "ORDER BY smart_messages_fts.rank LIMIT ?",
            (match_query, chat_id, limit),
        )
        return await cursor.fetchall()

    async def search_messages_fts_count(self, chat_id: int, match_query: str,
                                        since_ts: int = 0) -> dict:
        """(count, first_seen, last_seen) по FTS-совпадениям smart_messages.
        since_ts>0 — окно по timestamp (в SQL, не пост-фильтр top-N).
        Bugfix-раунд 04.09.2026 (Часть 2, FR-19): точный счётчик для
        query_chat_memory (строки режутся top-40 по rank ДО фильтра окна —
        точное «N раз в окне» из выборки не извлекается)."""
        sql = ("SELECT COUNT(*) AS cnt, MIN(m.timestamp) AS first_ts, "
               "MAX(m.timestamp) AS last_ts FROM smart_messages m "
               "WHERE m.chat_id = ? AND m.id IN "
               "(SELECT rowid FROM smart_messages_fts WHERE smart_messages_fts MATCH ?)")
        params: list = [chat_id, match_query]
        if since_ts:
            sql += " AND m.timestamp >= ?"
            params.append(since_ts)
        cursor = await self.db.execute(sql, tuple(params))
        row = await cursor.fetchone()
        return {"count": int(row["cnt"] or 0) if row else 0,
                "first_seen": row["first_ts"] if row else None,
                "last_seen": row["last_ts"] if row else None}

    async def search_archive_fts(self, chat_id: int, match_query: str, limit: int) -> list[str]:
        """L3 фоллбек: FTS5 search over archive facts, ordered by rank."""
        cursor = await self.db.execute(
            "SELECT f.fact FROM smart_archive_facts_fts "
            "JOIN smart_archive_facts f ON f.id = smart_archive_facts_fts.rowid "
            "WHERE smart_archive_facts_fts MATCH ? AND f.chat_id = ? "
            "ORDER BY smart_archive_facts_fts.rank LIMIT ?",
            (match_query, chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [row["fact"] for row in rows]

    async def get_smart_chat_ids(self) -> list[int]:
        """Distinct chat ids that have at least one saved message."""
        cursor = await self.db.execute("SELECT DISTINCT chat_id FROM smart_messages")
        rows = await cursor.fetchall()
        return [row["chat_id"] for row in rows]

    # ── GraphRAG: nodes/edges (Epic 26, Section 35.2) ───────

    async def upsert_node(self, chat_id: int, entity_name: str, entity_type: str,
                          origin: str = "chat_history", expires_at=None) -> int:
        """INSERT OR IGNORE (ключ chat_id+entity_name): существующий узел сохраняет
        СВОЙ тип/origin (не перезаписывается); новые получают origin/expires_at."""
        await self.db.execute(
            "INSERT OR IGNORE INTO nodes (chat_id, entity_name, entity_type, origin, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, entity_name, entity_type, origin, expires_at),
        )
        cursor = await self.db.execute(
            "SELECT id FROM nodes WHERE chat_id = ? AND entity_name = ?",
            (chat_id, entity_name),
        )
        row = await cursor.fetchone()
        await self.db.commit()
        return row["id"]

    async def upsert_edge(
        self,
        source_id: int,
        target_id: int,
        relation_type: str,
        weight_increment: int = 1,
        origin: str = "chat_history",
        expires_at=None,
    ) -> None:
        """Merge a graph edge; duplicate (source,target,relation) bumps weight (D70).

        chat_id is taken from the source node (both nodes always belong to the
        same chat by construction). One statement → atomic. Epic 46 (55.3):
        origin/expires_at записываются. Epic 60 (66.3, T-481): подтверждение
        связи — +инкремент с cap 5 (T-459 тема 5: «+1 cap 5»), last_updated =
        CURRENT_TIMESTAMP (сброс затухания).
        """
        await self.db.execute(
            "INSERT INTO edges (chat_id, source_id, target_id, relation_type, weight, "
            "origin, expires_at) "
            "SELECT chat_id, ?, ?, ?, ?, ?, ? FROM nodes WHERE id = ? "
            "ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET "
            "weight = MIN(weight + excluded.weight, ?), "
            "last_updated = CURRENT_TIMESTAMP",
            (source_id, target_id, relation_type, weight_increment, origin,
             expires_at, source_id, _EDGE_WEIGHT_CAP),
        )
        await self.db.commit()

    async def match_nodes(
        self, chat_id: int, user_names: list[str], topic_keywords: list[str]
    ) -> list[int]:
        """Node ids matched by exact user names or topic substring LIKE (35.5).
        Epic 50 (58.8): сущности origin='bot_direct_reply' в /summary-справки
        НЕ попадают (R26-3-фильтр от direct-диалогов)."""
        conditions = []
        params: list = []
        if user_names:
            placeholders = ",".join("?" for _ in user_names)
            conditions.append(f"(entity_type = 'user' AND entity_name IN ({placeholders}))")
            params.extend(user_names)
        if topic_keywords:
            like_clauses = " OR ".join("entity_name LIKE ?" for _ in topic_keywords)
            conditions.append(f"(entity_type = 'topic' AND ({like_clauses}))")
            params.extend(f"%{kw}%" for kw in topic_keywords)
        if not conditions:
            return []
        sql = ("SELECT id FROM nodes WHERE chat_id = ? AND origin != 'bot_direct_reply' AND ("
               + " OR ".join(conditions) + ")")
        cursor = await self.db.execute(sql, [chat_id, *params])
        rows = await cursor.fetchall()
        return [row["id"] for row in rows]

    async def get_top_edges(self, chat_id: int, entity_ids: list[int], limit: int) -> list:
        """Top edges incident to any of entity_ids, weight DESC (35.5).
        Epic 50 (58.8): фильтр origin='bot_direct_reply' (рёбра и оба конца)."""
        if not entity_ids:
            return []
        placeholders = ",".join("?" for _ in entity_ids)
        cursor = await self.db.execute(
            "SELECT e.id, e.chat_id, e.source_id, e.target_id, e.relation_type, "
            "e.weight, e.last_updated, "
            "s.entity_name AS source_name, s.entity_type AS source_type, "
            "t.entity_name AS target_name, t.entity_type AS target_type "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            f"WHERE e.chat_id = ? AND (e.source_id IN ({placeholders}) "
            f"OR e.target_id IN ({placeholders})) "
            "AND e.origin != 'bot_direct_reply' "
            "AND s.origin != 'bot_direct_reply' AND t.origin != 'bot_direct_reply' "
            "ORDER BY e.weight DESC, e.last_updated DESC, e.id DESC "
            "LIMIT ?",
            [chat_id, *entity_ids, *entity_ids, limit],
        )
        return await cursor.fetchall()

    async def get_top_edges_all(self, chat_id: int, limit: int) -> list:
        """Chat-wide top edges, weight DESC (cold-graph fallback, 35.5).
        Epic 50 (58.8): фильтр origin='bot_direct_reply' (рёбра и оба конца)."""
        cursor = await self.db.execute(
            "SELECT e.id, e.chat_id, e.source_id, e.target_id, e.relation_type, "
            "e.weight, e.last_updated, "
            "s.entity_name AS source_name, s.entity_type AS source_type, "
            "t.entity_name AS target_name, t.entity_type AS target_type "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            "WHERE e.chat_id = ? "
            "AND e.origin != 'bot_direct_reply' "
            "AND s.origin != 'bot_direct_reply' AND t.origin != 'bot_direct_reply' "
            "ORDER BY e.weight DESC, e.last_updated DESC, e.id DESC "
            "LIMIT ?",
            (chat_id, limit),
        )
        return await cursor.fetchall()

    # ── GraphRAG v2 (Epic 46, Section 55.3): graph_facts ─────────

    async def insert_graph_fact(self, chat_id, fact, origin, expires_at,
                                target_user=None, status="confirmed",
                                supersedes=None, weight=None,
                                message_timestamp: int | None = None,
                                or_ignore: bool = False) -> int:
        """Факт-строка (+FTS-индекс). Возвращает id. Epic 50 (58.8, D205):
        target_user — имя обращающегося (origin='bot_direct_reply'); created_at
        ставится автоматически (int(time.time())). Epic 60 (64.1/64.2):
        status ('confirmed' default | 'unconfirmed' — зона 0.85–0.95) и
        supersedes (id инвалидированного предшественника). Epic 60 (66.1/66.3,
        T-479/T-481): weight 0..1 (None → 0.5; вне [0,1] — кламп + WARNING),
        last_confirmed_at = created_at (факт рождается подтверждённым).
        Фаза 2 (T-758, spec 3.4): message_timestamp — дата сообщения-источника
        (Graph-воркер истории; origin='history_import'); None для live-вызовов
        (поведение не меняется; рендер COALESCE использует created_at).
        Фаза 2 (T-763, Graph-воркер): or_ignore=True → INSERT OR IGNORE:
        дубль по частичному UNIQUE-индексу idx_graph_facts_history_import
        (chat_id, fact, message_timestamp, origin='history_import') молча
        пропускается → возврат 0 и БЕЗ FTS-строки (FTS5 external content не
        знает о дублях rowid — edge 5 spec; идемпотентность повторных
        прогонов/переноса дельты FR-10). Live-путь (or_ignore=False) —
        ровно прежний INSERT (дубль → IntegrityError, как и раньше)."""
        w = 0.5 if weight is None else float(weight)
        if not 0.0 <= w <= 1.0:
            logger.warning("graph fact weight %s outside [0,1] — clamped (66.1)", w)
            w = min(1.0, max(0.0, w))
        now = int(time.time())
        insert_sql = (
            "INSERT OR IGNORE INTO graph_facts "
            if or_ignore else
            "INSERT INTO graph_facts ")
        cursor = await self.db.execute(
            insert_sql +
            "(chat_id, fact, origin, expires_at, created_at, "
            "target_user, status, supersedes, weight, last_confirmed_at, "
            "message_timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (chat_id, fact, origin, expires_at, now, target_user,
             status, supersedes, w, now, message_timestamp))
        if cursor.rowcount == 0:
            # дубль (INSERT OR IGNORE) — FTS-строку НЕ пишем (edge 5),
            # коммитить нечего
            return 0
        fact_id = cursor.lastrowid
        await self.db.execute(
            "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)", (fact_id, fact))
        await self.db.commit()
        return fact_id

    async def search_graph_facts_fts(self, chat_id, match_query, limit, now_ts,
                                     include_direct_reply=False) -> list:
        """FTS-фолбек RAG с ленивым TTL-фильтром (D175). Epic 50 (58.8, D206):
        include_direct_reply=False (default) → origin='bot_direct_reply' НЕ
        подмешивается в чужие пайплайны; + created_at/target_user в SELECT.
        Epic 60 (64.2): статус-фильтр — unconfirmed-факты в RAG НЕ участвуют.
        Epic 60 (66.3, T-481): + weight/last_confirmed_at — время-взвешивание
        (пересортировка по w_eff) происходит в Python (SQL не меняем)."""
        sql = (
            "SELECT f.id, f.fact, f.origin, f.created_at, f.target_user, "
            "f.weight, f.last_confirmed_at, f.message_timestamp, "
            "COALESCE(f.message_timestamp, f.created_at) AS rag_ts "
            "FROM graph_facts_fts "
            "JOIN graph_facts f ON f.id = graph_facts_fts.rowid "
            "WHERE graph_facts_fts MATCH ? AND f.chat_id = ? "
            "AND (f.expires_at IS NULL OR f.expires_at > ?) "
            "AND f.status = 'confirmed' ")
        if not include_direct_reply:
            sql += "AND f.origin != 'bot_direct_reply' "
        sql += "ORDER BY graph_facts_fts.rank LIMIT ?"
        cursor = await self.db.execute(sql, (match_query, chat_id, now_ts, limit))
        return await cursor.fetchall()

    async def get_graph_fact_texts(self, fact_ids, status=None) -> list:
        """[(origin, fact, ts), ...] в порядке fact_ids (порядок KNN
        сохраняется). ts = message_timestamp or created_at (фаза 2, T-759:
        дата-рендер COALESCE — импортированные факты с датой сообщения).
        Epic 50 (58.7): + created_at/target_user (только SELECT).
        Epic 60 (64.2): status='confirmed' → unconfirmed исключаются из RAG."""
        if not fact_ids:
            return []
        placeholders = ",".join("?" for _ in fact_ids)
        sql = (f"SELECT id, fact, origin, created_at, target_user, "
               f"message_timestamp FROM graph_facts WHERE id IN ({placeholders})")
        params: list = list(fact_ids)
        if status:
            sql += " AND status = ?"
            params.append(status)
        cursor = await self.db.execute(sql, params)
        by_id = {
            row["id"]: (row["origin"], row["fact"],
                        row["message_timestamp"] or row["created_at"])
            for row in await cursor.fetchall()
        }
        return [by_id[fid] for fid in fact_ids if fid in by_id]

    async def purge_expired_graph_facts(self, chat_id=None) -> int:
        """Опциональный purge (D175, 55.1 #5): edges истёкших узлов → edges с
        истёкшим expires_at → истёкшие nodes → истёкшие graph_facts (+FTS).
        Epic 60 (66.11, T-489): chat_id=None → глобальный проход по всем чатам
        (пересмотр); с chat_id — piggyback 55.1 #5 (без изменений).
        Фаза 2 (T-756, гейт G3): memory.infinite_retention ON → return 0
        без SQL (TTL-факты не удаляются; единая точка — покрывает всех
        вызывающих: compress_and_purge :1930 и memory_maintenance.review).
        Раунд 8 (E3/T-805, spec §3.E3): гейт защиты graph_facts-строк —
        истёкший факт НЕ удаляется, если выполнено хотя бы одно:
          - вес >= limits.graph_purge_protect_weight (default 0.8) — защищает
            user_memory 1.0 и «вечные» origin, не трогая chat_history 0.5 /
            bot_direct_reply 0.7 (веса по _origin_weight);
          - last_confirmed_at свежее limits.graph_purge_protect_days
            (default 3 дня; подтверждение = недавний дедуп-hit);
          - текст факта совпадает с protected_facts (защищённый факт);
          - expires_at IS NULL (вечные — и не кандидаты по условию).
        FTS-строки чистятся тем же предикатом (иначе защищённый факт
        потерял бы поиск). nodes/edges — общий граф без per-fact-атрибуции,
        их expires_at-каскад не меняется."""
        if _infinite_retention_on():
            logger.info(
                "[database] purge_expired_graph_facts skipped — "
                "memory.infinite_retention ON (T-756)")
            return 0
        now = int(time.time())
        protect_weight = float(hot.get(
            "limits.graph_purge_protect_weight",
            settings.GRAPH_PURGE_PROTECT_WEIGHT) or 0.8)
        protect_days = int(hot.get(
            "limits.graph_purge_protect_days",
            settings.GRAPH_PURGE_PROTECT_DAYS) or 0) or 3
        protect_cutoff = now - protect_days * 86400
        chat_filter = "AND e.chat_id = ?" if chat_id is not None else ""
        node_chat = "AND chat_id = ?" if chat_id is not None else ""
        params = (now,) if chat_id is None else (now, chat_id)
        # E3: предикат «факт — кандидат на удаление» (истёкший, слабый,
        # давно не подтверждённый, не защищённый текстом).
        fact_candidate = (
            "expires_at IS NOT NULL AND expires_at <= ? AND "
            "NOT (weight >= ? OR "
            "(last_confirmed_at IS NOT NULL AND last_confirmed_at >= ?) OR "
            "EXISTS (SELECT 1 FROM protected_facts p "
            "WHERE p.chat_id = graph_facts.chat_id AND p.fact = graph_facts.fact))"
        )
        for side in ("source_id", "target_id"):
            await self.db.execute(
                f"DELETE FROM edges WHERE id IN ("
                f"SELECT e.id FROM edges e JOIN nodes n ON n.id = e.{side} "
                f"WHERE n.expires_at IS NOT NULL AND n.expires_at <= ? "
                f"{chat_filter})", params)
        await self.db.execute(
            "DELETE FROM edges WHERE expires_at IS NOT NULL AND expires_at <= ?"
            + node_chat,
            params)
        await self.db.execute(
            "DELETE FROM nodes WHERE expires_at IS NOT NULL AND expires_at <= ?"
            + node_chat,
            params)
        fact_params = (now, protect_weight, protect_cutoff) + \
            (() if chat_id is None else (chat_id,))
        await self.db.execute(
            "DELETE FROM graph_facts_fts WHERE rowid IN "
            f"(SELECT id FROM graph_facts WHERE {fact_candidate}{node_chat})",
            fact_params)
        cursor = await self.db.execute(
            f"DELETE FROM graph_facts WHERE {fact_candidate}{node_chat}",
            fact_params)
        await self.db.commit()
        return cursor.rowcount

    # ── bot_replies (Epic 60, Section 63.1, T-460) ─────────────
    # Персистентный аналог in-memory LRU _bot_replies (TTL 3600с лениво,
    # cap 200 — паттерн TTL+LRU, T-459 тема 8). last_used_at — время записи
    # (write-per-read запрещён: на чтении last_used_at НЕ обновляется — LRU
    # движется только записями, как в старом OrderedDict).

    _BOT_REPLIES_TTL_SECONDS = 3600.0   # 63.1
    _BOT_REPLIES_CAP = 200              # 63.1

    async def upsert_bot_reply(self, chat_id: int, tg_message_id: int,
                               text: str, now: float) -> None:
        """UPSERT текста ответа бота (63.1) + ленивый TTL-sweep + LRU-cap
        (NOT IN … ORDER BY last_used_at DESC LIMIT N — тема 8)."""
        await self.db.execute(
            "DELETE FROM bot_replies WHERE last_used_at < ?",
            (now - self._BOT_REPLIES_TTL_SECONDS,),
        )
        await self.db.execute(
            "INSERT INTO bot_replies (chat_id, tg_message_id, text, last_used_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id, tg_message_id) DO UPDATE SET "
            "text = excluded.text, last_used_at = excluded.last_used_at",
            (chat_id, tg_message_id, text, now),
        )
        await self.db.execute(
            "DELETE FROM bot_replies WHERE (chat_id, tg_message_id) NOT IN "
            "(SELECT chat_id, tg_message_id FROM bot_replies "
            "ORDER BY last_used_at DESC LIMIT ?)",
            (self._BOT_REPLIES_CAP,),
        )
        await self.db.commit()

    async def get_bot_reply(self, chat_id: int, tg_message_id: int,
                            now: float) -> str | None:
        """Текст ответа бота; None — нет записи. Протухший (> TTL) →
        ленивый DELETE + None (тема 8)."""
        cursor = await self.db.execute(
            "SELECT text, last_used_at FROM bot_replies "
            "WHERE chat_id = ? AND tg_message_id = ?",
            (chat_id, tg_message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        if now - row["last_used_at"] > self._BOT_REPLIES_TTL_SECONDS:
            await self.db.execute(
                "DELETE FROM bot_replies WHERE chat_id = ? AND tg_message_id = ?",
                (chat_id, tg_message_id),
            )
            await self.db.commit()
            return None
        return row["text"]

    # ── bot_reply_parents (Раунд 8, spec §3.G1/D3, T-800) ─────────
    # Parent-линк «бот-ответ → сообщение, на которое отвечал» — thread-walk
    # продолжает цепочку сквозь бот-сообщения. Тот же TTL/LRU-паттерн, что
    # bot_replies (63.1): ленивый TTL на чтении, cap на записи.

    async def set_bot_reply_parent(self, chat_id: int, tg_message_id: int,
                                   parent_tg_message_id: int | None,
                                   now: float) -> None:
        """Запись parent-линка (UPSERT + TTL-sweep + LRU-cap — паттерн
        upsert_bot_reply). parent=None (edit-путь, родитель неизвестен) →
        no-op: существующая строка линка НЕ перезаписывается (D3/Q9)."""
        if parent_tg_message_id is None:
            return
        await self.db.execute(
            "DELETE FROM bot_reply_parents WHERE last_used_at < ?",
            (now - self._BOT_REPLIES_TTL_SECONDS,),
        )
        await self.db.execute(
            "INSERT INTO bot_reply_parents "
            "(chat_id, tg_message_id, parent_tg_message_id, last_used_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id, tg_message_id) DO UPDATE SET "
            "parent_tg_message_id = excluded.parent_tg_message_id, "
            "last_used_at = excluded.last_used_at",
            (chat_id, tg_message_id, parent_tg_message_id, now),
        )
        await self.db.execute(
            "DELETE FROM bot_reply_parents WHERE (chat_id, tg_message_id) NOT IN "
            "(SELECT chat_id, tg_message_id FROM bot_reply_parents "
            "ORDER BY last_used_at DESC LIMIT ?)",
            (self._BOT_REPLIES_CAP,),
        )
        await self.db.commit()

    async def get_bot_reply_parent(self, chat_id: int, tg_message_id: int,
                                   now: float) -> int | None:
        """Parent-сообщение бот-ответа; None — нет линка/протух. Протухший
        (> TTL) → ленивый DELETE + None (паттерн get_bot_reply)."""
        cursor = await self.db.execute(
            "SELECT parent_tg_message_id, last_used_at FROM bot_reply_parents "
            "WHERE chat_id = ? AND tg_message_id = ?",
            (chat_id, tg_message_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        if now - row["last_used_at"] > self._BOT_REPLIES_TTL_SECONDS:
            await self.db.execute(
                "DELETE FROM bot_reply_parents "
                "WHERE chat_id = ? AND tg_message_id = ?",
                (chat_id, tg_message_id),
            )
            await self.db.commit()
            return None
        return row["parent_tg_message_id"]

    # ── Активные участники (Раунд 8, spec §3.C2, T-793) ──────────
    # UserResolutionMap строится не только по окну, но и по активным
    # участникам за limits.chat_map_participants_hours: SQL-агрегат по
    # smart_messages. Существующий индекс idx_smart_messages_chat_ts
    # (chat_id, timestamp) покрывает диапазон; GROUP BY/ORDER по cap ≤ 150 —
    # дешёвый temp b-tree (новый индекс НЕ создаём — RUNTIME WARNING).

    async def get_active_participants(self, chat_id: int, since_ts: int,
                                      cap: int) -> list:
        """Участники чата за период: user_id + MAX(author_name) (последний
        канон-самописей) + счётчик сообщений, ORDER BY cnt DESC, user_id ASC
        (стабильно), LIMIT cap."""
        cursor = await self.db.execute(
            "SELECT user_id, MAX(author_name) AS author_name, COUNT(*) AS cnt "
            "FROM smart_messages "
            "WHERE chat_id = ? AND timestamp >= ? AND user_id IS NOT NULL "
            "GROUP BY user_id ORDER BY cnt DESC, user_id ASC LIMIT ?",
            (chat_id, since_ts, cap),
        )
        return await cursor.fetchall()

    # ── Epic 60 Фаза C (65.4/65.5/65.8/65.10) ─────────────────
    # Стилевые якоря, пресеты тона (user_prefs), /clear, /forget,
    # защищённые факты (protected_facts).

    async def last_bot_replies(self, chat_id: int, limit: int, now: float) -> list[str]:
        """65.4: последние (по last_used_at) НЕ протухшие ответы бота чата,
        ASC (от старейшего к свежайшему) — для <style_anchors>."""
        cursor = await self.db.execute(
            "SELECT text FROM bot_replies "
            "WHERE chat_id = ? AND last_used_at > ? "
            "ORDER BY last_used_at DESC LIMIT ?",
            (chat_id, now - self._BOT_REPLIES_TTL_SECONDS, limit),
        )
        return [row["text"] for row in (await cursor.fetchall())][::-1]

    async def get_user_tone_preset(self, chat_id: int, user_id: int) -> str | None:
        """65.8: tone_preset из user_prefs (None — нет записи)."""
        cursor = await self.db.execute(
            "SELECT tone_preset FROM user_prefs WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        row = await cursor.fetchone()
        return row["tone_preset"] if row is not None else None

    async def set_user_tone_preset(self, chat_id: int, user_id: int,
                                   preset: str) -> None:
        """65.5/65.8: UPSERT tone_preset в user_prefs (/tone — единственная
        команда записи)."""
        await self.db.execute(
            "INSERT INTO user_prefs (chat_id, user_id, tone_preset) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
            "tone_preset = excluded.tone_preset",
            (chat_id, user_id, preset),
        )
        await self.db.commit()

    async def get_protected_facts(self, chat_id: int, user_name: str,
                                  include_chat_level: bool = True) -> list[str]:
        """65.10: защищённые факты юзера (подмешиваются в контекст; /forget
        их НЕ трогает). include_chat_level=True (default, раунд 5/T-732):
        + чат-уровневые факты (user_name IS NULL — «лор чата»), они идут
        ПЕРВЫМИ (не тонут при обрезке блока). False — старое поведение
        (только user_name = ?). Порядок: чат-уровневые → ASC по created_at, id."""
        if include_chat_level:
            cursor = await self.db.execute(
                "SELECT fact FROM protected_facts "
                "WHERE chat_id = ? AND (user_name = ? OR user_name IS NULL) "
                "ORDER BY (user_name IS NULL) DESC, created_at ASC, id ASC",
                (chat_id, user_name))
        else:
            cursor = await self.db.execute(
                "SELECT fact FROM protected_facts "
                "WHERE chat_id = ? AND user_name = ? "
                "ORDER BY created_at ASC, id ASC",
                (chat_id, user_name))
        return [row["fact"] for row in await cursor.fetchall()]

    async def clear_direct_dialogue(self, chat_id: int, target_user: str) -> int:
        """/clear (65.5): стереть цепочки чата (bot_replies) + graph_facts с
        origin='bot_direct_reply' AND target_user=имя юзера (+FTS-строки).
        chat_history-факты НЕ трогаем. Возвращает число удалённых фактов."""
        await self.db.execute("DELETE FROM bot_replies WHERE chat_id = ?", (chat_id,))
        cursor = await self.db.execute(
            "SELECT id FROM graph_facts "
            "WHERE chat_id = ? AND origin = 'bot_direct_reply' AND target_user = ?",
            (chat_id, target_user),
        )
        fact_ids = [row["id"] for row in await cursor.fetchall()]
        for fact_id in fact_ids:
            await self.db.execute(
                "DELETE FROM graph_facts_fts WHERE rowid = ?", (fact_id,))
            await self.db.execute(
                "DELETE FROM graph_facts WHERE id = ?", (fact_id,))
        await self.db.commit()
        return len(fact_ids)

    @staticmethod
    def _fts_forget_query(phrase: str) -> str:
        """FTS5-prefix-запрос для /forget (прецедент build_fts_query из
        summary_memory: `"слово"*` OR …; кавычки/`*` юзера вырезаны,
        слова <2 симв. отброшены — unicode61 их не токенизирует)."""
        cleaned = []
        for word in re.findall(r"[0-9a-zа-яё]+", phrase.lower()):
            word = word.replace('"', "").replace("*", "")
            if len(word) >= 2:
                cleaned.append(f'"{word}"*')
        return " OR ".join(cleaned)

    async def forget_direct_facts(self, chat_id: int, target_user: str,
                                  phrase: str, now_ts: int) -> int:
        """/forget (65.5/65.10): FTS-поиск по bot_direct_reply-фактам юзера →
        DELETE + запись в graph_fact_compressions (reason='forget').
        Защищённые факты (точное совпадение fact с protected_facts) НЕ
        удаляются. Fail-open: ошибка FTS → WARNING + 0. Возвращает число
        удалённых фактов."""
        match_query = self._fts_forget_query(phrase)
        if not match_query:
            return 0
        try:
            cursor = await self.db.execute(
                "SELECT f.id, f.fact FROM graph_facts_fts "
                "JOIN graph_facts f ON f.id = graph_facts_fts.rowid "
                "WHERE graph_facts_fts MATCH ? AND f.chat_id = ? "
                "AND f.origin = 'bot_direct_reply' AND f.target_user = ? "
                "AND (f.expires_at IS NULL OR f.expires_at > ?) "
                "AND NOT EXISTS (SELECT 1 FROM protected_facts p "
                "WHERE p.chat_id = f.chat_id AND p.user_name = f.target_user "
                "AND p.fact = f.fact)",
                (match_query, chat_id, target_user, now_ts),
            )
            rows = await cursor.fetchall()
        except Exception:
            logger.warning(
                "direct: /forget FTS search failed — fail-open | chat=%s",
                chat_id, exc_info=True)
            return 0
        for row in rows:
            await self.db.execute(
                "DELETE FROM graph_facts_fts WHERE rowid = ?", (row["id"],))
            await self.db.execute(
                "DELETE FROM graph_facts WHERE id = ?", (row["id"],))
            await self.log_fact_compression(
                chat_id, row["id"], row["fact"], None, "forget")
        await self.db.commit()
        return len(rows)

    # ── Раунд 4 (T-714, FR-D3, spec 3.4.5): «забудь» — user_memory ──

    @staticmethod
    def _memory_forget_words(phrase: str) -> list[str]:
        """Слова запроса «забудь»: [0-9a-zа-яё]+ из lower(phrase), длина >= 3,
        срез до 5 (AND-семантика; fail-open → [])."""
        return [
            w for w in re.findall(r"[0-9a-zа-яё]+", str(phrase or "").lower())
            if len(w) >= 3
        ][:5]

    async def forget_memory_facts(self, chat_id: int, words: list[str],
                                  target_user: str | None = None,
                                  now_ts: int = 0) -> int:
        """«забудь» (T-714/FR-D3): ТОЛЬКО origin='user_memory'. words — слова
        запроса (>=3 симв, до 5). FTS-prefix первого слова (fail-open → 0) →
        кандидаты; Python-фильтр: КАЖДОЕ слово содержится в lower(fact) (AND).
        target_user None → весь чат; иначе — свои факты юзера (scope по
        канон-имени). Удаление: graph_facts_fts → graph_facts → best-effort
        graph_facts_vec (vec-таблицы может не быть — FTS-режим); на каждый
        удалённый факт — журнал graph_fact_compressions (reason='user_forget').
        protected_facts в выборку НЕ попадают (отдельная таблица; запрос
        ограничен origin='user_memory'). Повторный вызов безвреден.
        Граница: chat_history/bot_direct_reply/прочее НЕ трогаются."""
        if now_ts <= 0:
            now_ts = int(time.time())
        words = [w for w in (words or []) if len(w) >= 3][:5]
        if not words:
            return 0
        match_query = f'"{words[0]}"*'
        sql = (
            "SELECT f.id, f.fact FROM graph_facts_fts "
            "JOIN graph_facts f ON f.id = graph_facts_fts.rowid "
            "WHERE graph_facts_fts MATCH ? AND f.chat_id = ? "
            "AND f.origin = 'user_memory' "
            "AND (f.expires_at IS NULL OR f.expires_at > ?) ")
        params: list = [match_query, chat_id, now_ts]
        if target_user is not None:
            sql += "AND f.target_user = ? "
            params.append(target_user)
        sql += "LIMIT 500"
        try:
            cursor = await self.db.execute(sql, params)
            rows = await cursor.fetchall()
        except Exception:
            logger.warning(
                "direct: «забудь» FTS search failed — fail-open | chat=%s",
                chat_id, exc_info=True)
            return 0
        removed = 0
        for row in rows:
            fact_lower = str(row["fact"] or "").lower()
            if not all(w in fact_lower for w in words):
                continue
            await self.db.execute(
                "DELETE FROM graph_facts_fts WHERE rowid = ?", (row["id"],))
            await self.db.execute(
                "DELETE FROM graph_facts WHERE id = ?", (row["id"],))
            try:
                await self.db.execute(
                    "DELETE FROM graph_facts_vec WHERE rowid = ?", (row["id"],)
                )
            except Exception:
                pass                        # vec-таблицы может не быть (FTS-режим)
            await self.log_fact_compression(
                chat_id, row["id"], row["fact"], None, "user_forget")
            removed += 1
        await self.db.commit()
        return removed

    # ── Epic 60 Фаза B (64.1/64.2/64.6, T-462/T-463/T-467) ─────

    @staticmethod
    def _like_escape(value: str) -> str:
        """Экранирование LIKE-паттерна (ESCAPE '!')."""
        return (str(value).replace("!", "!!").replace("%", "!%").replace("_", "!_"))

    async def find_graph_fact_exact(self, chat_id: int, key: str, now_ts: int):
        """64.1: точный дубль — строка graph_facts того же чата с фактом
        's p o' или 's p o (context)', не протухшая. Возвращает row
        (id/fact/weight/status) или None."""
        pattern = self._like_escape(key) + "%"
        cursor = await self.db.execute(
            "SELECT id, fact, weight, status, expires_at FROM graph_facts "
            "WHERE chat_id = ? AND fact LIKE ? ESCAPE '!' "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "ORDER BY created_at DESC LIMIT 5",
            (chat_id, pattern, now_ts),
        )
        for row in await cursor.fetchall():
            if row["fact"] == key or row["fact"].startswith(key + " ("):
                return row
        return None

    async def confirm_graph_fact(self, fact_id: int, now_ts: int,
                                 bonus: float) -> None:
        """64.1/64.2: noop-подтверждение — weight += bonus (cap 1.0, floor
        0.1), last_confirmed_at = now, status → 'confirmed'."""
        await self.db.execute(
            "UPDATE graph_facts SET "
            "weight = MIN(MAX(weight + ?, 0.1), 1.0), "
            "last_confirmed_at = ?, status = 'confirmed' WHERE id = ?",
            (bonus, now_ts, fact_id),
        )
        await self.db.commit()

    async def invalidate_graph_fact(self, fact_id: int, now_ts: int) -> None:
        """64.2: инвалидация (НЕ удаление) — expires_at = now; vec-строка
        удаляется (иначе KNN продолжил бы выдавать старый текст — TTL в
        vec-таблице живёт своей копией)."""
        await self.db.execute(
            "UPDATE graph_facts SET expires_at = ? WHERE id = ?",
            (now_ts, fact_id),
        )
        try:
            await self.db.execute(
                "DELETE FROM graph_facts_vec WHERE rowid = ?", (fact_id,)
            )
        except Exception:
            pass                        # vec-таблицы может не быть (FTS-режим)
        await self.db.commit()

    async def log_fact_compression(self, chat_id: int, fact_id, fact_before: str,
                                   fact_after, reason: str) -> None:
        """64.2: журнал «что во что» (supersede/сжатие/forget/conflict) —
        обратимость антиотравления. fact_id — id нового/пережившего факта."""
        await self.db.execute(
            "INSERT INTO graph_fact_compressions "
            "(chat_id, fact_id, fact_before, fact_after, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, fact_id, fact_before, fact_after, reason, time.time()),
        )
        await self.db.commit()

    async def get_graph_fact_rows(self, fact_ids: list) -> list:
        """Строки graph_facts по id (для дедупа 64.1): id/fact/status/weight/
        expires_at."""
        if not fact_ids:
            return []
        placeholders = ",".join("?" for _ in fact_ids)
        cursor = await self.db.execute(
            f"SELECT id, fact, status, weight, expires_at FROM graph_facts "
            f"WHERE id IN ({placeholders})", fact_ids,
        )
        return await cursor.fetchall()

    async def get_running_summary(self, chat_id: int, now: float) -> dict | None:
        """64.6: конспект чата (chat_running_summary) или None — нет строки.
        Раунд 8 (E4/T-806, Q11): expires_at при ЧТЕНИИ НЕ «убивает» конспект —
        lazy-DELETE по TTL убран (в тихом чате конспект живёт и остаётся в
        Global_Context; пересборка — по заполнению окна новыми сообщениями,
        триггер get_window_messages). expires_at продолжает писаться
        (диагностика/запасной механизм), колонки не меняются. Раунд 8
        (D5/T-802): SELECT несёт created_at (для логов; метке объёма нужен
        raw_count — уже был в выборке)."""
        cursor = await self.db.execute(
            "SELECT summary, window_start_ts, window_end_ts, raw_count, "
            "created_at, expires_at FROM chat_running_summary WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return row

    async def upsert_running_summary(self, chat_id: int, summary: str,
                                     window_start_ts: int, window_end_ts: int,
                                     raw_count: int, created_at: float,
                                     expires_at: float) -> None:
        """64.6: UPSERT конспекта (chat_id — PRIMARY KEY)."""
        await self.db.execute(
            "INSERT INTO chat_running_summary "
            "(chat_id, summary, window_start_ts, window_end_ts, raw_count, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "summary = excluded.summary, "
            "window_start_ts = excluded.window_start_ts, "
            "window_end_ts = excluded.window_end_ts, "
            "raw_count = excluded.raw_count, "
            "created_at = excluded.created_at, "
            "expires_at = excluded.expires_at",
            (chat_id, summary, window_start_ts, window_end_ts, raw_count,
             created_at, expires_at),
        )
        await self.db.commit()

    # ── Уровни конспекта (Раунд 8, spec §3.E2, T-804) ─────────
    # chat_summary_levels: level 2 = «широкий фон» — сжатие ПРЕДЫДУЩЕГО level 1
    # (running_summary) тем же COMPRESS_PROMPT. msg_count_highwater защищает
    # от перезаписи более узким окном. TTL уровня не вводится (E2.4).

    async def get_summary_level(self, chat_id: int, level: int) -> dict | None:
        """E2/T-804: строка уровня конспекта (None — уровня нет)."""
        cursor = await self.db.execute(
            "SELECT summary, updated_at, msg_count_highwater "
            "FROM chat_summary_levels WHERE chat_id = ? AND level = ?",
            (chat_id, level),
        )
        return await cursor.fetchone()

    async def upsert_summary_level(self, chat_id: int, level: int,
                                   summary: str, updated_at: float,
                                   msg_count_highwater: int) -> None:
        """E2/T-804: UPSERT уровня конспекта (PK chat_id+level)."""
        await self.db.execute(
            "INSERT INTO chat_summary_levels "
            "(chat_id, level, summary, updated_at, msg_count_highwater) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, level) DO UPDATE SET "
            "summary = excluded.summary, "
            "updated_at = excluded.updated_at, "
            "msg_count_highwater = excluded.msg_count_highwater",
            (chat_id, level, summary, updated_at, msg_count_highwater),
        )
        await self.db.commit()

    # ── Epic 60 Фаза D (66.1–66.12, T-479…T-490) ───────────────

    async def get_graph_fact_records(self, fact_ids, status=None) -> list:
        """66.1/66.3: полные строки graph_facts по id (id/fact/origin/
        created_at/target_user/weight/status/last_confirmed_at) — для
        weight×decay-ранжирования KNN-пути в Python. status-фильтр — как в
        get_graph_fact_texts (64.2). Фаза 2 (T-759): + message_timestamp
        (рендер COALESCE делает вызывающий — _knn_graph_facts)."""
        if not fact_ids:
            return []
        placeholders = ",".join("?" for _ in fact_ids)
        sql = (f"SELECT id, fact, origin, created_at, target_user, weight, "
               f"status, last_confirmed_at, message_timestamp FROM graph_facts "
               f"WHERE id IN ({placeholders})")
        params: list = list(fact_ids)
        if status:
            sql += " AND status = ?"
            params.append(status)
        cursor = await self.db.execute(sql, params)
        return await cursor.fetchall()

    async def touch_graph_facts(self, fact_ids, extend_days: int,
                                direct_ttl_days, archive_ttl_days: int,
                                now_ts: int) -> int:
        """66.5 (T-483): «используется — живёт» — RAG-hit продлевает
        expires_at на extend_days, cap: не дальше created_at + 2 × базовый TTL
        (вечное протухание невозможно). Только факты с expires_at NOT NULL
        (chat_history/вечные не трогаем). Базовая TTL по origin: direct —
        direct_ttl_days (None → пропуск), архивные — archive_ttl_days.
        Обновление по id списком (батч, без write-per-read)."""
        if not fact_ids:
            return 0
        placeholders = ",".join("?" for _ in fact_ids)
        extend = extend_days * 86400.0
        touched = 0
        for origins, ttl_days in ((
            ("'search_fact'", "'youtube_content'", "'web_content'"),
            archive_ttl_days), (("'bot_direct_reply'",), direct_ttl_days)):
            if ttl_days in (None, 0):
                continue
            origin_sql = ",".join(origins)
            cursor = await self.db.execute(
                f"UPDATE graph_facts SET expires_at = "
                f"MIN(expires_at + ?, created_at + ?) "
                f"WHERE id IN ({placeholders}) AND expires_at IS NOT NULL "
                f"AND origin IN ({origin_sql})",
                (extend, 2 * ttl_days * 86400.0, *fact_ids))
            touched += cursor.rowcount
        if touched:
            await self.db.commit()
        return touched

    async def delete_graph_fact(self, fact_id: int) -> None:
        """66.4/66.11: полное удаление факта — graph_facts_fts + vec-строка
        (rowid == fact_id) + строка graph_facts."""
        await self.db.execute(
            "DELETE FROM graph_facts_fts WHERE rowid = ?", (fact_id,))
        try:
            await self.db.execute(
                "DELETE FROM graph_facts_vec WHERE rowid = ?", (fact_id,))
        except Exception:
            pass                        # vec-таблицы может не быть (FTS-режим)
        await self.db.execute(
            "DELETE FROM graph_facts WHERE id = ?", (fact_id,))
        await self.db.commit()

    async def is_fact_protected(self, chat_id: int, fact_text: str) -> bool:
        """65.10/66.2/66.10: факт совпадает с защищённым (по тексту, чат-скоп) —
        дедуп/слияние/пересмотр его НЕ трогают."""
        cursor = await self.db.execute(
            "SELECT 1 FROM protected_facts WHERE chat_id = ? AND fact = ? LIMIT 1",
            (chat_id, fact_text))
        return await cursor.fetchone() is not None

    async def get_quota_victim(self, chat_id: int, target_user: str, quota: int,
                               now_ts: int):
        """66.4 (T-482): вытеснение — при live-фактах юзера >= quota вернуть
        самого лёгкого и старого: score = weight / (age_days + 1) MIN.
        Защищённые факты — вне кандидатов на вытеснение (65.10).
        Раунд 8 (E3/T-805): расширение защищённого множества — высоковесные
        (weight >= limits.graph_purge_protect_weight) и недавно подтверждённые
        (last_confirmed_at свежее limits.graph_purge_protect_days) тоже не
        выбираются жертвой (гейт purge/eviction spec §3.E3.2). None — квота
        не превышена / все кандидаты защищены."""
        protect_weight = float(hot.get(
            "limits.graph_purge_protect_weight",
            settings.GRAPH_PURGE_PROTECT_WEIGHT) or 0.8)
        protect_days = int(hot.get(
            "limits.graph_purge_protect_days",
            settings.GRAPH_PURGE_PROTECT_DAYS) or 0) or 3
        protect_cutoff = now_ts - protect_days * 86400
        cursor = await self.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts "
            "WHERE chat_id = ? AND target_user = ? "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (chat_id, target_user, now_ts))
        if (await cursor.fetchone())["c"] < quota:
            return None
        cursor = await self.db.execute(
            "SELECT id, fact FROM graph_facts "
            "WHERE chat_id = ? AND target_user = ? "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "AND NOT EXISTS (SELECT 1 FROM protected_facts p "
            "WHERE p.chat_id = graph_facts.chat_id "
            "AND p.user_name = graph_facts.target_user "
            "AND p.fact = graph_facts.fact) "
            "AND NOT (weight >= ? OR "
            "(last_confirmed_at IS NOT NULL AND last_confirmed_at >= ?)) "
            "ORDER BY (weight / (((? - created_at) / 86400.0) + 1.0)) ASC, "
            "id ASC LIMIT 1",
            (chat_id, target_user, now_ts, protect_weight, protect_cutoff,
             now_ts))
        return await cursor.fetchone()

    async def get_live_graph_facts(self, chat_id: int, now_ts: int) -> list:
        """66.2/66.11: живые (не протухшие) confirmed-факты чата для слияния/
        пересмотра."""
        cursor = await self.db.execute(
            "SELECT id, fact, origin, expires_at, created_at, weight, "
            "target_user, last_confirmed_at FROM graph_facts "
            "WHERE chat_id = ? AND status = 'confirmed' "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (chat_id, now_ts))
        return await cursor.fetchall()

    async def get_graph_chat_ids(self) -> list[int]:
        """66.11: чаты, в которых есть graph_facts (пересмотр по всем)."""
        cursor = await self.db.execute(
            "SELECT DISTINCT chat_id FROM graph_facts")
        return [row["chat_id"] for row in await cursor.fetchall()]

    async def find_exact_dup_groups(self, chat_id: int, now_ts: int) -> list:
        """66.11 (T-489): точные дубли (идентичный текст факта) живых
        confirmed-фактов чата — группы ≥2 (для склейки пересмотром)."""
        cursor = await self.db.execute(
            "SELECT id, fact, weight, created_at FROM graph_facts "
            "WHERE chat_id = ? AND status = 'confirmed' "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (chat_id, now_ts))
        groups: dict[str, list] = {}
        for row in await cursor.fetchall():
            key = str(row["fact"]).casefold().strip()
            groups.setdefault(key, []).append(row)
        return [rows for rows in groups.values() if len(rows) >= 2]

    async def purge_unconfirmed_graph_facts(self, now_ts: int,
                                            retention_days: int) -> int:
        """66.11 (T-489): выброс unconfirmed старше retention (64.2) — по всем
        чатам; vec/FTS-строки чистим вместе (иначе KNN выдавал бы текст).
        Фаза 2 (T-756, гейт G4): memory.infinite_retention ON → return 0
        без SQL."""
        if _infinite_retention_on():
            logger.info(
                "[database] purge_unconfirmed_graph_facts skipped — "
                "memory.infinite_retention ON (T-756)")
            return 0
        cursor = await self.db.execute(
            "SELECT id FROM graph_facts WHERE status = 'unconfirmed' "
            "AND created_at <= ?",
            (now_ts - retention_days * 86400,))
        ids = [row["id"] for row in await cursor.fetchall()]
        for fact_id in ids:
            await self.db.execute(
                "DELETE FROM graph_facts_fts WHERE rowid = ?", (fact_id,))
            try:
                await self.db.execute(
                    "DELETE FROM graph_facts_vec WHERE rowid = ?", (fact_id,))
            except Exception:
                pass
            await self.db.execute(
                "DELETE FROM graph_facts WHERE id = ?", (fact_id,))
        await self.db.commit()
        return len(ids)

    async def trim_compression_log(self, now: float, retention_days: int) -> int:
        """66.11 (T-489): усечение graph_fact_compressions старше retention —
        лог не растёт вечно. Фаза 2 (T-756, гейт G5): memory.infinite_retention
        ON → return 0 без SQL."""
        if _infinite_retention_on():
            logger.info(
                "[database] trim_compression_log skipped — "
                "memory.infinite_retention ON (T-756)")
            return 0
        cursor = await self.db.execute(
            "DELETE FROM graph_fact_compressions WHERE created_at < ?",
            (now - retention_days * 86400.0,))
        await self.db.commit()
        return cursor.rowcount

    async def get_persona_card(self, chat_id: int, name: str, limit: int,
                               now_ts: int) -> dict:
        """66.9 (T-487): карточка человека БЕЗ отдельной таблицы — агрегация:
        прямые факты (target_user = имя, weight DESC) + связи графа (edges по
        user-узлу с entity_name = имя, weight DESC). Без техдеталей (id/весов
        в ответе нет)."""
        cursor = await self.db.execute(
            "SELECT fact FROM graph_facts "
            "WHERE chat_id = ? AND target_user = ? AND status = 'confirmed' "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "ORDER BY weight DESC, created_at DESC",
            (chat_id, name, now_ts))
        facts = [row["fact"] for row in await cursor.fetchall()]
        cursor = await self.db.execute(
            "SELECT e.relation_type, "
            "s.entity_name AS source_name, t.entity_name AS target_name "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            "WHERE e.chat_id = ? "
            "AND ((s.entity_name = ? AND s.entity_type = 'user') "
            "OR (t.entity_name = ? AND t.entity_type = 'user')) "
            "AND e.origin != 'bot_direct_reply' "
            "AND s.origin != 'bot_direct_reply' AND t.origin != 'bot_direct_reply' "
            "ORDER BY e.weight DESC, e.id DESC LIMIT ?",
            (chat_id, name, name, limit))
        links = [dict(row) for row in await cursor.fetchall()]
        return {"facts": facts, "links": links}

    async def get_persona_names(self, chat_id: int, now_ts: int) -> list:
        """66.9: /persona list (только админ) — имена + счётчики прямых фактов
        (живых, confirmed)."""
        cursor = await self.db.execute(
            "SELECT target_user AS name, COUNT(*) AS c FROM graph_facts "
            "WHERE chat_id = ? AND target_user IS NOT NULL "
            "AND status = 'confirmed' "
            "AND (expires_at IS NULL OR expires_at > ?) "
            "GROUP BY target_user ORDER BY name ASC",
            (chat_id, now_ts))
        return [(row["name"], row["c"]) for row in await cursor.fetchall()]
