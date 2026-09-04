"""Epic 60 (63.3, D245): smoke-тест скрипта миграции 2→3.

Создаёт v2-БД (пре-Epic-60 схема: graph_facts без weight/status/...,
edges без created_at, user_version=2) и запускает
scripts/migrate_epic60_v3.py::_main с путём в argv →
user_version==3, новые таблицы, v3-колонки, данные сохранены;
повторный запуск — no-op (идемпотентность). Прецедент
test_migrate_direct_chat_v2_script.py.
"""
import asyncio
import sqlite3

from scripts.migrate_epic60_v3 import _main

_V2_GRAPH_FACTS = """CREATE TABLE graph_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    fact       TEXT NOT NULL,
    origin     TEXT NOT NULL DEFAULT 'chat_history',
    expires_at INTEGER,
    created_at INTEGER NOT NULL,
    target_user TEXT
);"""

_V2_EDGES = """CREATE TABLE edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    source_id     INTEGER NOT NULL,
    target_id     INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    weight        INTEGER NOT NULL DEFAULT 1,
    last_updated  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    origin        TEXT NOT NULL DEFAULT 'chat_history',
    expires_at    INTEGER,
    UNIQUE (source_id, target_id, relation_type)
);"""


def _create_v2_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(_V2_GRAPH_FACTS + _V2_EDGES)
    conn.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
        "VALUES (-100, 'старый факт', 'chat_history', 1700000000)")
    conn.execute(
        "INSERT INTO edges (chat_id, source_id, target_id, relation_type, last_updated) "
        "VALUES (-100, 1, 2, 'связь', '2024-01-01 00:00:00')")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()


def test_migration_script_v2_to_v3(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    _create_v2_db(path)
    monkeypatch.setattr(
        "sys.argv", ["migrate_epic60_v3.py", str(path)])
    asyncio.run(_main())

    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"throttle_state", "bot_replies", "user_prefs",
                "embedding_cache", "chat_running_summary",
                "graph_fact_compressions", "protected_facts"} <= tables
        fact_cols = {r[1] for r in conn.execute("PRAGMA table_info(graph_facts)")}
        assert {"weight", "status", "last_confirmed_at", "supersedes"} <= fact_cols
        edge_cols = {r[1] for r in conn.execute("PRAGMA table_info(edges)")}
        assert "created_at" in edge_cols
        row = conn.execute(
            "SELECT fact, weight, status, last_confirmed_at FROM graph_facts"
        ).fetchone()
        assert row[0] == "старый факт"          # данные сохранены
        assert row[1] == 0.5
        assert row[2] == "confirmed"
        assert row[3] == 1700000000             # backfill = created_at
    finally:
        conn.close()


def test_migration_script_idempotent_second_run(tmp_path, monkeypatch):
    path = tmp_path / "old2.db"
    _create_v2_db(path)
    monkeypatch.setattr(
        "sys.argv", ["migrate_epic60_v3.py", str(path)])
    asyncio.run(_main())
    asyncio.run(_main())                        # повторный запуск — no-op

    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        row = conn.execute("SELECT COUNT(*) FROM graph_facts").fetchone()
        assert row[0] == 1                      # строки не задвоены
        row = conn.execute("SELECT COUNT(*) FROM edges").fetchone()
        assert row[0] == 1
    finally:
        conn.close()
