"""B09 (v6.3) — перенос supergroup ≠ потеря истории и памяти.

Контракты (закрытие wa3-остатка «Summary/Memory вне доказанного
сквозного переноса»):
- `services.chat_migration.migrate_chat_memory` переносит SQLite-память
  old→new идемпотентно: smart_messages (история/dig), smart_archive_facts
  (Summary), graph_facts (Memory) + FTS, vec0-индексы, конспекты, эпизоды,
  protected/journal;
- только UPDATE (0 DELETE) + safe backup ДО записи (chat_migration_backup);
- старые факты находятся по new chat_id и ПОСЛЕ РЕСТАРТА (переоткрытие БД);
- хендлер `on_chat_migrated` вызывает перенос (проводка link≠proof);
- конфликт (целевой id занят) не abort-ит перенос, остаток честно репортит.

TEST-LIFECYCLE: INTEGRATION owner=REQ-B09-BODY
R17: только синтетические векторы/факты, никаких реальных переписок.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.database import DatabaseService
from services.summary_memory import MemoryManager

OLD = -100500
NEW = -100999
DIM = 8


def _unit(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i % DIM] = 1.0
    return v


class VecLLM:
    def __init__(self, vec_map=None):
        self.vec_map = vec_map or {}
        self.embed_calls = 0

    async def embed(self, texts):
        self.embed_calls += 1
        return [self.vec_map.get(t, _unit(0)) for t in texts]

    async def generate(self, messages):  # pragma: no cover
        raise AssertionError("generate не нужен в B09-тестах")


@pytest.fixture
def db_file(tmp_path):
    return str(tmp_path / "b09_migration.db")


async def _open(db_file):
    d = DatabaseService(db_file)
    await d.initialize()
    return d


async def _init_memory(db, monkeypatch):
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        pytest.skip("sqlite-vec not installed")

    async def _probe_fixed(self):
        return False                       # float-only (детерминизм)

    monkeypatch.setattr(MemoryManager, "_probe_vec_int8", _probe_fixed)
    memory = MemoryManager(db, VecLLM())

    async def _noop_backfill() -> int:
        return 0

    memory.backfill_archive_vectors = _noop_backfill
    memory.backfill_graph_fact_vectors = _noop_backfill
    ok = await memory.initialize()
    if not ok:
        pytest.skip("sqlite-vec extension could not be loaded")
    return memory


async def _seed_old_chat_memory(db, memory):
    """Полный memory-корпус старого чата: сообщения, Summary, Memory
    (graph_facts+vec), конспект, эпизод, protected."""
    now = 1_700_000_000
    # L1: переписка (dig_into_lore / исторический FTS)
    msg_id = await db.save_smart_message(
        777, OLD, "решение по биллингу приняли", None, now, "text",
        "Игорь")
    # L3 Summary
    afid = await db.save_archive_fact(OLD, "итог: биллинг переезжает на SBP",
                                      now)
    memory.llm.vec_map["итог: биллинг переезжает на SBP"] = _unit(1)
    await memory._save_archive_embedding(OLD, afid,
                                         "итог: биллинг переезжает на SBP")
    # Memory (GraphRAG)
    fid = await db.insert_graph_fact(OLD, "Игорь отвечает за биллинг",
                                     "chat_history", None)
    memory.llm.vec_map["Игорь отвечает за биллинг"] = _unit(2)
    await memory._insert_graph_vec_row(fid, OLD, "Игорь отвечает за биллинг",
                                       "chat_history", None, _unit(2))
    # бегущий конспект
    await db.upsert_running_summary(OLD, "конспект: чат про биллинг",
                                    now - 600, now, 5, float(now),
                                    float(now + 3600))
    # эпизод
    await db.db.execute(
        "INSERT OR IGNORE INTO mca_episodes (episode_id, chat_id, title, "
        "summary, discovered_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("ep-b09-1", OLD, "Биллинг", "обсудили биллинг", now, now))
    # protected
    await db.db.execute(
        "INSERT OR IGNORE INTO protected_facts (chat_id, user_name, fact, "
        "created_at) VALUES (?, ?, ?, ?)",
        (OLD, "Игорь", "Игорь отвечает за биллинг", float(now)))
    await db.db.commit()
    return {"msg_id": msg_id, "archive_fid": afid, "fact_id": fid, "now": now}


async def _register_migration(db):
    from services.message_identity import register_chat_id_migration
    await register_chat_id_migration(db, old_chat_id=OLD, new_chat_id=NEW,
                                     evidence="telegram:migrate_to_chat_id")


class TestSupergroupMemoryMigration:
    @pytest.mark.asyncio
    async def test_end_to_end_transfer_and_restart(
            self, db_file, monkeypatch):
        db = await _open(db_file)
        memory = await _init_memory(db, monkeypatch)
        seeded = await _seed_old_chat_memory(db, memory)
        fid = seeded["fact_id"]
        afid = seeded["archive_fid"]
        await _register_migration(db)

        from services.chat_migration import (migrate_chat_memory,
                                             verify_chat_memory_integrity)
        result = await migrate_chat_memory(db, OLD, NEW)

        # перенос состоялся по всем носителям
        moved = result["moved"]
        for table in ("smart_messages", "smart_archive_facts", "graph_facts",
                      "chat_running_summary", "mca_episodes",
                      "protected_facts"):
            assert moved.get(table, 0) >= 1, f"{table} не перенесён"
        assert result["errors"] == []
        assert result["backup_rows"] >= 5

        # vec-индексы переезжают aux chat_id
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts_vec WHERE chat_id = ?",
            (OLD,))
        assert (await cursor.fetchone())["n"] == 0
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts_vec WHERE chat_id = ?",
            (NEW,))
        assert (await cursor.fetchone())["n"] == 1

        # ── чтение по НОВОМУ chat_id: все пути ──
        # Memory: FTS
        rows = await db.search_graph_facts_fts(NEW, '"биллинг"*', 10,
                                               seeded["now"] + 10)
        assert any(r["id"] == fid for r in rows)
        # Memory: KNN (vec)
        fact_rows = await memory._knn_graph_facts(
            NEW, _unit(2), 5, with_meta=True)
        assert any(r["id"] == fid for r in fact_rows)
        # Summary: FTS
        arch_fts = await db.search_archive_fts(NEW, '"биллинг"*', 10)
        assert arch_fts
        # Summary: KNN (vec)
        arch_vec = await memory._search_archive_knn(NEW, _unit(1), 5)
        assert arch_vec
        # история: smart_messages FTS
        msg_rows = await db.search_messages_fts(NEW, '"биллинг"*', 10)
        assert msg_rows
        # конспект и эпизод
        summary = await db.get_running_summary(NEW, float(seeded["now"]))
        assert summary is not None
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM mca_episodes WHERE chat_id = ?",
            (NEW,))
        assert (await cursor.fetchone())["n"] == 1

        # целостность: под old пусто, backup записан
        report = await verify_chat_memory_integrity(db, OLD, NEW)
        assert report["ok"] is True, report["residual_old_rows"]

        # идемпотентность: повторный перенос — 0 строк
        second = await migrate_chat_memory(db, OLD, NEW)
        assert second["moved"] == {}

        # ── рестарт: переоткрытие той же файловой БД ──
        await db.close()
        db2 = await _open(db_file)
        memory2 = await _init_memory(db2, monkeypatch)
        rows = await db2.search_graph_facts_fts(NEW, '"биллинг"*', 10,
                                                seeded["now"] + 10)
        assert any(r["id"] == fid for r in rows), \
            "старые факты не найдены после рестарта"
        arch_vec2 = await memory2._search_archive_knn(NEW, _unit(1), 5)
        assert arch_vec2, "Summary-вектор недоступен после рестарта"
        await db2.close()

    @pytest.mark.asyncio
    async def test_conflict_does_not_abort_and_is_reported(
            self, db_file, monkeypatch):
        db = await _open(db_file)
        await _init_memory(db, monkeypatch)
        now = 1_700_000_000
        await db.insert_graph_fact(OLD, "старый факт чата", "chat_history",
                                   None)
        await db.upsert_running_summary(OLD, "старый конспект",
                                        now - 600, now, 5, float(now),
                                        float(now + 3600))
        # целевой id занят конспектом (конфликт PK chat_id)
        await db.upsert_running_summary(NEW, "новый конспект",
                                        now - 300, now, 9, float(now),
                                        float(now + 3600))
        await _register_migration(db)

        from services.chat_migration import migrate_chat_memory
        result = await migrate_chat_memory(db, OLD, NEW)
        # факт переехал, конспект остался под old (guard), без abort/потери
        assert result["moved"].get("graph_facts") == 1
        cursor = await db.db.execute(
            "SELECT summary FROM chat_running_summary WHERE chat_id = ?",
            (NEW,))
        assert (await cursor.fetchone())["summary"] == "новый конспект"
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM chat_running_summary "
            "WHERE chat_id = ?", (OLD,))
        assert (await cursor.fetchone())["n"] == 1
        from services.chat_migration import verify_chat_memory_integrity
        report = await verify_chat_memory_integrity(db, OLD, NEW)
        assert report["ok"] is False           # остаток честно репортится
        assert "chat_running_summary" in report["residual_old_rows"]
        await db.close()

    @pytest.mark.asyncio
    async def test_chunked_backup_covers_all_rows_rev_w1_f1(
            self, db_file, monkeypatch):
        """REGRESSION (REV-W1 F1): backup читается ЧАНКАМИ до исчерпания —
        объём больше одного чанка НЕ приводит к переносу без полного backup
        (прод-чат >1M сообщений: старое поведение LIMIT cap переносило
        не-забэкапленные строки). TEST-LIFECYCLE: REGRESSION owner=REQ-B09."""
        import services.chat_migration as cm
        monkeypatch.setattr(cm, "_BACKUP_CHUNK", 2)   # крошечный чанк
        db = await _open(db_file)
        await _init_memory(db, monkeypatch)
        now = 1_700_000_000
        total_msgs = 25
        for i in range(total_msgs):
            await db.save_smart_message(
                777, OLD, f"реплика {i} про биллинг", None, now + i,
                "text", "Игорь")
        await _register_migration(db)

        result = await cm.migrate_chat_memory(db, OLD, NEW)
        assert isinstance(result, dict)        # N1: всегда dict
        assert result["errors"] == [], result["errors"]
        assert result["backup_rows"] >= total_msgs
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ?",
            (OLD,))
        assert (await cursor.fetchone())["n"] == 0     # перенесено всё
        # каждая исходная строка присутствует в backup-журнале
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM chat_migration_backup "
            "WHERE table_name = 'smart_messages'")
        assert (await cursor.fetchone())["n"] >= total_msgs
        report = await cm.verify_chat_memory_integrity(db, OLD, NEW)
        assert report["ok"] is True
        await db.close()

    @pytest.mark.asyncio
    async def test_backup_hard_cap_aborts_move_rev_w1_f1(
            self, db_file, monkeypatch):
        """REGRESSION (REV-W1 F1): аварийный потолок backup — явный abort
        переноса (ошибка + строки НЕ переезжают), а не молчаливое
        продолжение; функция возвращает dict (N1)."""
        import services.chat_migration as cm
        monkeypatch.setattr(cm, "_BACKUP_CHUNK", 2)
        monkeypatch.setattr(cm, "_BACKUP_HARD_CAP", 10)
        db = await _open(db_file)
        await _init_memory(db, monkeypatch)
        now = 1_700_000_000
        for i in range(25):
            await db.save_smart_message(
                777, OLD, f"реплика {i} про биллинг", None, now + i,
                "text", "Игорь")
        await _register_migration(db)

        result = await cm.migrate_chat_memory(db, OLD, NEW)
        assert isinstance(result, dict)
        assert any(e.endswith("backup_hard_cap") for e in result["errors"])
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ?",
            (OLD,))
        # mass-move НЕ начинался: строки остались под old
        assert (await cursor.fetchone())["n"] == 25
        await db.close()

    @pytest.mark.asyncio
    async def test_no_delete_contract(self, db_file, monkeypatch):
        """Перенос только UPDATE: суммарное число строк носителей не меняется."""
        db = await _open(db_file)
        await _init_memory(db, monkeypatch)
        now = 1_700_000_000
        await db.save_smart_message(1, OLD, "сообщение один", None, now,
                                    "text", "A")
        await db.insert_graph_fact(OLD, "факт один", "chat_history", None)

        async def _counts():
            out = {}
            for table in ("smart_messages", "graph_facts"):
                cursor = await db.db.execute(
                    f"SELECT COUNT(*) AS n FROM {table}")
                out[table] = (await cursor.fetchone())["n"]
            return out

        before = await _counts()
        from services.chat_migration import migrate_chat_memory
        await migrate_chat_memory(db, OLD, NEW)
        after = await _counts()
        assert before == after, "перенос не должен менять число строк"
        await db.close()


class TestLifecycleWiring:
    @pytest.mark.asyncio
    async def test_on_chat_migrated_calls_memory_migration(self, db_file):
        """link ≠ proof: хендлер обязан запустить сквозной перенос памяти
        (проводка B09), а не только профиль PG-store."""
        import handlers.chat_lifecycle as lifecycle

        db = await _open(db_file)
        store = MagicMock()
        store.add_link = AsyncMock()
        store.migrate_profile = AsyncMock(
            return_value={"moved": True, "merged": False})
        store.get_profile = AsyncMock(return_value=object())
        msg = MagicMock()
        msg.chat = MagicMock()
        msg.chat.id = OLD
        msg.migrate_to_chat_id = NEW
        msg.message_id = 555
        with patch.object(lifecycle, "_store", store), \
                patch.object(lifecycle, "_db", db), \
                patch.object(lifecycle, "ensure_gates_defaults",
                             AsyncMock()):
            with patch("services.chat_migration.migrate_chat_memory",
                       AsyncMock(return_value={"moved": {}, "errors": [],
                                               "backup_rows": 0})
                       ) as mig_mock:
                await lifecycle.on_chat_migrated(msg)
        mig_mock.assert_awaited_once()
        args = mig_mock.await_args
        assert args.args[1] == OLD and args.args[2] == NEW
        await db.close()
