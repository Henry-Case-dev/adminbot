#!/usr/bin/env python3
"""Read-only dump of the prod context sources for the P0 full probe.

Runs ON the server inside the prod venv. Opens PG in a READ ONLY session and
SQLite in mode=ro. Never writes to prod databases, never calls Telegram.
Writes one JSON to --out.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys

PG_ENV_KEYS = ("DATABASE_URL", "POSTGRES_DSN", "PG_DSN", "DB_DSN")
CHAT_ID = -1002661910336
T_A = 1792873281          # message A
T_B = 1792873478          # message B

SKIP_TABLES = {
    "llm_usage_events", "mca_events", "graph_facts_vec", "graph_facts_fts",
    "graph_facts_old", "graph_facts_v8_legacy", "graph_facts_v9_legacy",
    "messages_json", "embedding_cache", "smart_archive_facts",
    "smart_archive_facts_fts", "import_checkpoints", "import_checkpoints_old",
    "nodes", "nodes_old", "edges", "protected_facts", "protected_facts_old",
    "mca_embedding_index_generations", "cover_style_assets",
    "cover_style_connections", "cover_style_references",
    "cover_style_issue_assignments", "cover_style_provenance",
    "uptime_events", "worker_budget", "param_permissions", "chat_keys",
    "chat_usage", "schema_migrations",
}


def env_from(path, key):
    try:
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def coerce(value, cap=60000):
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return "<bytes:%d>" % len(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value)
    if len(text) > cap:
        return text[:cap] + "...<trunc:%d>" % len(text)
    return text


def row_json(row):
    return {k: coerce(v) for k, v in dict(row).items()}


async def dump_pg(root, out):
    import asyncpg

    dsn = None
    for key in PG_ENV_KEYS:
        dsn = env_from(os.path.join(root, ".env"), key)
        if dsn:
            break
    if not dsn:
        return {"error": "no DSN in prod .env"}
    conn = await asyncpg.connect(dsn, timeout=20)
    try:
        await conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        ro = await conn.fetchval("SHOW transaction_read_only")
        cols = await conn.fetch(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema='public' ORDER BY table_name, ordinal_position")
        tables = {}
        for r in cols:
            tables.setdefault(r["table_name"], []).append(r["column_name"])
        picked = []
        for name, columns in tables.items():
            if name in SKIP_TABLES:
                continue
            interesting = ({"full_text", "compact_text", "prompt_key", "value"}
                           & set(columns))
            if interesting or name in {
                    "personas", "persona_traits", "persona_state", "mca_lessons",
                    "mca_self_identity", "chat_running_summary", "summary_runs",
                    "chat_summary_levels", "chat_params", "lore_stories",
                    "bot_settings", "config", "mca_behavior_rules",
                    "mca_experience_feedback", "chat_profiles", "chat_links",
                    "bot_roles", "mca_stories", "mca_episodes", "user_prefs"}:
                picked.append(name)
        data = {"read_only": ro, "tables": {}, "columns": {}}
        for name in sorted(picked):
            cols_main = tables[name]
            where = ""
            if "chat_id" in cols_main:
                where = (" WHERE chat_id = %d" % CHAT_ID)
            try:
                rows = await conn.fetch(
                    "SELECT * FROM %s%s LIMIT 60" % (name, where))
                data["tables"][name] = [row_json(r) for r in rows]
                data["columns"][name] = cols_main
            except Exception as exc:                     # noqa: BLE001
                data["tables"][name] = {"error": "%s: %s"
                                        % (type(exc).__name__, str(exc)[:200])}
        # targeted graph facts (self-echo evidence)
        try:
            rows = await conn.fetch(
                "SELECT * FROM graph_facts WHERE chat_id = $1 "
                "AND (fact ILIKE '%злобн%' OR fact ILIKE '%Ринтаро%' "
                "     OR subject ILIKE '%злобн%') ORDER BY id DESC LIMIT 25",
                CHAT_ID)
            data["graph_facts_targeted"] = [row_json(r) for r in rows]
        except Exception as exc:                         # noqa: BLE001
            data["graph_facts_targeted"] = {"error": str(exc)[:200]}
        try:
            rows = await conn.fetch(
                "SELECT id, chat_id, source_type, status, created_at, "
                "       length(coalesce(summary,'')) AS summary_len "
                "FROM summary_runs WHERE chat_id = $1 "
                "ORDER BY created_at DESC LIMIT 6", CHAT_ID)
            data["summary_runs_recent"] = [row_json(r) for r in rows]
        except Exception as exc:                         # noqa: BLE001
            data["summary_runs_recent"] = {"error": str(exc)[:200]}
        json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False)
        return {"ok": True, "tables": len(data["tables"]),
                "read_only": ro, "path": out}
    finally:
        await conn.close()


def dump_sqlite(root, out_sqlite):
    db_path = os.path.join(root, "local_database.db")
    uri = "file:%s?mode=ro" % db_path.replace("\\", "/")
    conn = sqlite3.connect(uri, uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cols = [r["name"] for r in
                cur.execute("PRAGMA table_info(smart_messages)")]
        q = ("SELECT * FROM smart_messages WHERE chat_id = ? "
             "AND timestamp BETWEEN ? AND ? ORDER BY timestamp")
        rows = [dict(r) for r in cur.execute(
            q, (CHAT_ID, T_A - 5400, T_B + 600)).fetchall()]
        for r in rows:
            for k, v in list(r.items()):
                if isinstance(v, (bytes, bytearray)):
                    r[k] = "<bytes:%d>" % len(v)
        payload = {"columns": cols, "rows": rows}
        json.dump(payload, open(out_sqlite, "w", encoding="utf-8"),
                  ensure_ascii=False)
        return {"rows": len(rows), "columns": len(cols)}
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/var/www/admin_bot")
    ap.add_argument("--out", default="/tmp/p0_pg_dump.json")
    ap.add_argument("--out-sqlite", default="/tmp/p0_sqlite_dump.json")
    args = ap.parse_args()
    result = {}
    try:
        result["pg"] = asyncio.run(dump_pg(args.root, args.out))
    except Exception as exc:                             # noqa: BLE001
        result["pg"] = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:300])}
    try:
        result["sqlite"] = dump_sqlite(args.root, args.out_sqlite)
    except Exception as exc:                             # noqa: BLE001
        result["sqlite"] = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:300])}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
