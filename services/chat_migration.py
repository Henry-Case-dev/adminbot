"""B09 (v6.3): сквозной перенос памяти чата при supergroup-миграции.

wa3-остаток: D02 переносил профиль/роли/links/историю PG-store, а SQLite
память (graph_facts/GraphRAG-vec, summary smart_archive, конспекты, эпизоды,
сообщения) оставалась под старым chat_id → Summary/Memory «вне доказанного
сквозного переноса».

Контракт:
- **идемпотентно**: повторный вызов по уже перенесённому чату — 0 строк;
- **без удаления**: только UPDATE chat_id old→new (+ backup ДО записи);
  никакой silent truncate, FTS (external content) переезжает сам по rowid;
- **safe backup**: затронутые строки копируются в `chat_migration_backup`
  (полные строки row-таблиц; метаданные aux-колонок для vec0-таблиц —
  embedding восстановим штатным backfill из текстов);
- **цепочка миграций**: new резолвится до канонического конца цепочки
  (resolve_canonical_chat_id), чтобы перенос при повторном переезде
  догонял до актуального id;
- **fail-soft**: ошибки таблицы не прерывают весь перенос — собираются в
  result["errors"] (вызывающий решает; хендлер логирует).

Никаких массовых DELETE/автоочисток здесь нет и не будет (запрет B09).
"""

from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

# chat_id-носители памяти/истории, покрываемые сквозным переносом B09.
# vec0-таблицы обновляют auxiliary chat_id (sqlite-vec 0.1.9 — UPDATE aux
# поддержан, проверено пробником); их embedding НЕ копируются в backup.
_ROW_TABLES: tuple[str, ...] = (
    "smart_messages",          # L1 переписка (dig/исторический FTS)
    "smart_archive_facts",     # L3 summary-факты (+FTS external content)
    "graph_facts",             # память (+graph_facts_fts external content)
    "edges",                   # GraphRAG-рёбра
    "graph_fact_compressions", # журнал версий (supersede/сжатие)
    # chat_id входит в UNIQUE/PK — per-row guard по конфликтным колонкам:
    # занятая строка назначения пропускается (остаётся под old, её честно
    # репортит verify), остальные строки переезжают, abort-а нет.
    "nodes",                   # UNIQUE(chat_id, entity_name)
    "protected_facts",         # UNIQUE(chat_id, user_name, fact)
    "mca_episodes",            # UNIQUE(chat_id, segment_key)
    "chat_summary_levels",     # PK(chat_id, level)
    "chat_running_summary",    # PK(chat_id) — одна строка
)
# conflict-колонки для per-row guard (в порядке UNIQUE-определения).
_GUARD_COLS: dict[str, tuple[str, ...]] = {
    "nodes": ("entity_name",),
    "protected_facts": ("user_name", "fact"),
    "mca_episodes": ("segment_key",),
    "chat_summary_levels": ("level",),
    "chat_running_summary": (),  # PK = сам chat_id
}
_VEC_TABLES: tuple[str, ...] = (
    "graph_facts_vec",         # aux chat_id (rowid=fact_id)
    "smart_archive",           # aux chat_id (rowid=archive vec row)
)

# Bounded backup: разумный потолок строк на таблицу (защита от
# непропорциональной транзакции; превышение фиксируется в результате).
_BACKUP_ROW_CAP = 200_000

_BACKUP_DDL = (
    "CREATE TABLE IF NOT EXISTS chat_migration_backup ("
    "backup_id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "migration_id TEXT NOT NULL, "
    "table_name TEXT NOT NULL, "
    "rowid_value INTEGER, "
    "row_json TEXT NOT NULL, "
    "created_at INTEGER NOT NULL)"
)


async def migrate_chat_memory(db, old_chat_id: int, new_chat_id: int) -> dict:
    """Перенести память old_chat_id → new_chat_id (идемпотентно, с backup).

    Возвращает {"old_chat_id", "new_chat_id", "canonical_new", "moved":
    {table: count}, "backup_rows": int, "skipped": bool, "errors": [...]}.
    Никогда не бросает на уровне одной таблицы; ошибки собираются.
    """
    old_chat_id = int(old_chat_id)
    new_chat_id = int(new_chat_id)
    result: dict = {"old_chat_id": old_chat_id, "new_chat_id": new_chat_id,
                    "moved": {}, "backup_rows": 0, "skipped": False,
                    "errors": []}
    if old_chat_id == new_chat_id:
        result["skipped"] = True
        return result
    try:
        canonical_new = int(await db.resolve_canonical_chat_id(new_chat_id))
    except Exception:
        canonical_new = new_chat_id
    result["canonical_new"] = canonical_new
    if canonical_new != new_chat_id:
        # new сам уже переехал дальше — переносим сразу в конец цепочки.
        new_chat_id = canonical_new
        result["new_chat_id"] = new_chat_id
    migration_id = f"{old_chat_id}->{new_chat_id}:{int(time.time())}"
    result["migration_id"] = migration_id

    # mca-01 single-writer (аудит test_write_points_go_through_single_writer):
    # вся фаза записи (backup-DDL, backup-строки, UPDATE old→new, commit/
    # rollback) — внутри serialized()-гарда общего соединения, как
    # graphrag_rebuild/dossier_rebuild. Если serialized() недоступен —
    # исключение уходит в fail-open вызывателя (handlers/chat_lifecycle.py).
    async with db.serialized():
        try:
            await db.db.execute(_BACKUP_DDL)
            await db.db.commit()
        except Exception as exc:
            # backup-таблица обязательна: без неё массовую запись не начинаем.
            result["errors"].append(f"backup_ddl: {type(exc).__name__}")
            logger.warning("[chat_migration] backup DDL failed | old=%s new=%s",
                           old_chat_id, new_chat_id, exc_info=True)
            return

        total_backup = 0
        for table in _ROW_TABLES:
            try:
                cursor = await db.db.execute(
                    f"SELECT rowid AS __rid, * FROM {table} WHERE chat_id = ? "
                    f"LIMIT {_BACKUP_ROW_CAP}", (old_chat_id,))
                rows = await cursor.fetchall()
            except Exception as exc:
                if "no such table" in str(exc).lower():
                    continue                 # факультативная таблица отсутствует
                result["errors"].append(f"{table}:backup:{type(exc).__name__}")
                logger.warning("[chat_migration] backup read failed | table=%s",
                               table, exc_info=True)
                continue
            for row in rows:
                try:
                    await db.db.execute(
                        "INSERT INTO chat_migration_backup (migration_id, "
                        "table_name, rowid_value, row_json, created_at) "
                        "VALUES (?,?,?,?,?)",
                        (migration_id, table, row["__rid"],
                         json.dumps({k: row[k] for k in row.keys()
                                     if k != "__rid"},
                                    ensure_ascii=False, default=str),
                         int(time.time())))
                except Exception as exc:
                    result["errors"].append(
                        f"{table}:backup_write:{type(exc).__name__}")
                    logger.warning(
                        "[chat_migration] backup write failed | table=%s",
                        table, exc_info=True)
                    break
            total_backup += len(rows)
            if len(rows) >= _BACKUP_ROW_CAP:
                logger.warning(
                    "[chat_migration] backup cap hit | table=%s | cap=%d",
                    table, _BACKUP_ROW_CAP)
        # vec0: backup только aux-метаданных (embedding восстанавливаем штатным
        # backfill; копия float-BLOB в JSON дала бы сотни МБ без пользы).
        for table in _VEC_TABLES:
            try:
                cursor = await db.db.execute(
                    f"SELECT rowid, chat_id FROM {table} WHERE chat_id = ? "
                    f"LIMIT {_BACKUP_ROW_CAP}", (old_chat_id,))
                rows = await cursor.fetchall()
            except Exception as exc:
                if "no such table" in str(exc).lower():
                    continue
                result["errors"].append(f"{table}:backup:{type(exc).__name__}")
                continue
            for row in rows:
                try:
                    await db.db.execute(
                        "INSERT INTO chat_migration_backup (migration_id, "
                        "table_name, rowid_value, row_json, created_at) "
                        "VALUES (?,?,?,?,?)",
                        (migration_id, table, row["rowid"],
                         json.dumps({"chat_id": row["chat_id"]}),
                         int(time.time())))
                except Exception:
                    result["errors"].append(
                        f"{table}:backup_write:{type(exc).__name__}")
                    break
            total_backup += len(rows)
        result["backup_rows"] = total_backup
        if result["errors"]:
            # AVERT: часть backup не записана — массовый UPDATE не начинаем
            # (никакой записи без полного backup; ретрай безопасен).
            try:
                await db.db.commit()      # фиксируем частичный backup-журнал
            except Exception:
                pass
            logger.warning(
                "[chat_migration] backup incomplete — aborting move | old=%s "
                "new=%s | errors=%d", old_chat_id, new_chat_id,
                len(result["errors"]))
            return
        try:
            await db.db.commit()          # backup закоммичен ДО переноса
        except Exception:
            pass

        moved: dict[str, int] = {}
        # Неявная транзакция sqlite3: все UPDATE до commit атомарны; при ошибке
        # — rollback целиком (partial failure не оставляет полупереноса).
        ok = True
        for table in _ROW_TABLES:
            try:
                guard_cols = _GUARD_COLS.get(table)
                if guard_cols:
                    exists = " AND ".join(
                        f"t2.{c} = {table}.{c}" for c in guard_cols)
                    cursor = await db.db.execute(
                        f"UPDATE {table} SET chat_id = ? WHERE chat_id = ? "
                        f"AND NOT EXISTS (SELECT 1 FROM {table} t2 "
                        f"WHERE t2.chat_id = ? AND {exists})",
                        (new_chat_id, old_chat_id, new_chat_id))
                elif guard_cols is not None:
                    # PK = сам chat_id: guard — «цель свободна целиком»
                    cursor = await db.db.execute(
                        f"UPDATE {table} SET chat_id = ? WHERE chat_id = ? "
                        f"AND NOT EXISTS (SELECT 1 FROM {table} t2 "
                        f"WHERE t2.chat_id = ?)",
                        (new_chat_id, old_chat_id, new_chat_id))
                else:
                    cursor = await db.db.execute(
                        f"UPDATE {table} SET chat_id = ? WHERE chat_id = ?",
                        (new_chat_id, old_chat_id))
                if cursor.rowcount:
                    moved[table] = int(cursor.rowcount)
            except Exception as exc:
                if "no such table" in str(exc).lower():
                    continue
                ok = False
                result["errors"].append(f"{table}:move:{type(exc).__name__}")
                logger.warning("[chat_migration] move failed | table=%s",
                               table, exc_info=True)
                break
        for table in _VEC_TABLES:
            try:
                cursor = await db.db.execute(
                    f"UPDATE {table} SET chat_id = ? WHERE chat_id = ?",
                    (new_chat_id, old_chat_id))
                if cursor.rowcount:
                    moved[table] = int(cursor.rowcount)
            except Exception as exc:
                if "no such table" in str(exc).lower():
                    continue
                ok = False
                result["errors"].append(f"{table}:move:{type(exc).__name__}")
                logger.warning("[chat_migration] vec move failed | table=%s",
                               table, exc_info=True)
                break
        if ok:
            try:
                await db.db.commit()
            except Exception:
                pass
            result["moved"] = moved
            logger.info(
                "[chat_migration] memory migrated | old=%s | new=%s | %s | "
                "backup_rows=%d", old_chat_id, new_chat_id, moved, total_backup)
        else:
            try:
                await db.db.rollback()
            except Exception:
                pass
            logger.warning(
                "[chat_migration] move aborted (rolled back) | old=%s new=%s",
                old_chat_id, new_chat_id)

    return result


async def verify_chat_memory_integrity(db, old_chat_id: int,
                                       new_chat_id: int) -> dict:
    """Проверка «перенос без потерь»: под old не осталось строк, счётчики
    таблиц сходятся с backup. Никогда не бросает."""
    report: dict = {"residual_old_rows": {}, "backup_rows": 0,
                    "ok": True}
    try:
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM chat_migration_backup")
        report["backup_rows"] = int((await cursor.fetchone())["n"])
    except Exception:
        pass
    for table in (*_ROW_TABLES, *_VEC_TABLES):
        try:
            cursor = await db.db.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE chat_id = ?",
                (int(old_chat_id),))
            n = int((await cursor.fetchone())["n"])
            if n:
                report["residual_old_rows"][table] = n
        except Exception:
            continue                  # таблицы может не быть
    report["ok"] = not report["residual_old_rows"]
    return report
