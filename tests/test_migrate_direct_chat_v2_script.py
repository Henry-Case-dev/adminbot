"""Epic 50 (58.7, D201; REVISE S1): smoke-тест скрипта миграции 1→2.

Создаёт старую БД (схема Epic 46: graph_facts без 'bot_direct_reply',
smart_messages без tg_message_id, user_version=1) и запускает
scripts/migrate_direct_chat_v2.py::_main с путём в argv →
CHECK + target_user, tg_message_id, данные сохранены. Epic 60 (63.3):
initialize теперь применяет и v3 — финальный user_version == 3.
"""
import asyncio
import sqlite3

from scripts.migrate_direct_chat_v2 import _main

_OLD_GRAPH_FACTS = """CREATE TABLE graph_facts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id    INTEGER NOT NULL,
    fact       TEXT NOT NULL,
    origin     TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN
               ('chat_history','search_fact','youtube_content','web_content')),
    expires_at INTEGER,
    created_at INTEGER NOT NULL
);"""

_OLD_SMART_MESSAGES = """CREATE TABLE smart_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    chat_id         INTEGER NOT NULL,
    text            TEXT,
    reply_to_id     INTEGER,
    timestamp       INTEGER NOT NULL,
    media_type      TEXT NOT NULL DEFAULT 'text',
    author_name     TEXT NOT NULL DEFAULT ''
);"""


def _create_v1_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript(_OLD_GRAPH_FACTS + _OLD_SMART_MESSAGES)
    conn.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
        "VALUES (-100, 'старый факт', 'chat_history', 100)"
    )
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def test_migration_script_v1_to_v2(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    _create_v1_db(path)
    monkeypatch.setattr(
        "sys.argv", ["migrate_direct_chat_v2.py", str(path)])
    asyncio.run(_main())

    conn = sqlite3.connect(str(path))
    try:
        # Epic 60 (63.3 + раунды 4/5): initialize каскадно применяет v3+v5+v6 → финал 7.
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_facts'"
        ).fetchone()[0]
        assert "bot_direct_reply" in sql
        fact_cols = {r[1] for r in conn.execute("PRAGMA table_info(graph_facts)")}
        assert "target_user" in fact_cols
        msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(smart_messages)")}
        assert "tg_message_id" in msg_cols
        row = conn.execute("SELECT fact FROM graph_facts").fetchone()
        assert row[0] == "старый факт"          # данные сохранены (id не тронуты)
    finally:
        conn.close()


def test_migration_script_idempotent_second_run(tmp_path, monkeypatch):
    path = tmp_path / "old2.db"
    _create_v1_db(path)
    monkeypatch.setattr(
        "sys.argv", ["migrate_direct_chat_v2.py", str(path)])
    asyncio.run(_main())
    asyncio.run(_main())                        # повторный запуск — no-op

    conn = sqlite3.connect(str(path))
    try:
        # Epic 60 (63.3 + раунды 4/5): initialize каскадно применяет v3+v5+v6 → финал 7.
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
        row = conn.execute("SELECT COUNT(*) FROM graph_facts").fetchone()
        assert row[0] == 1                      # строки не задвоены
    finally:
        conn.close()
