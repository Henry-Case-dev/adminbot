# -*- coding: utf-8 -*-
"""Synthetic SQLite fixture for the VMQ-MEM-06 G2 harness.

The fixture is evidence tooling, not product code. It creates a *fresh* DB
with the product schema (via ``DatabaseService.initialize``), inserts a small
deterministic corpus, checkpoints WAL and closes. The G2 harness then opens
that file STRICTLY READ-ONLY (``DatabaseService.initialize_readonly``).

No message/fact text is written outside this fixture file; the harness
records only ids/counts/years/hashes.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys

CHAT = -1002661910336
OTHER_CHAT = -1009999999999

# Sentinels: a smoke test asserts they never appear in harness outputs.
SECRET_FACT_TEXT = "SECRET_FACT_TEXT_G2"
SECRET_MSG_TEXT = "SECRET_MSG_TEXT_G2"

PEOPLE = (
    (485008070, "Иван Петров"),
    (138811255, "Мария Сидорова"),
    (1313107079, "Олег Смирнов"),
)


def ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(datetime.datetime(
        year, month, day, hour, minute, tzinfo=datetime.timezone.utc
    ).timestamp())


def _insert(db, sql: str, params=()):
    return db.execute(sql, params)


async def build_fixture(db_path: str, *, chat_id: int = CHAT,
                        other_chat: int = OTHER_CHAT) -> dict:
    if os.path.exists(db_path):
        raise FileExistsError(db_path)
    from services.database import DatabaseService

    db = DatabaseService(db_path)
    await db.initialize()
    conn = db.db
    ids: dict = {"facts": {}, "messages": {}, "nodes": {}, "span": []}

    async def msg(row_id, user_id, author, text, stamp, tg_id):
        await _insert(conn,
            "INSERT INTO smart_messages (id, user_id, chat_id, text, "
            "timestamp, media_type, author_name, tg_message_id) "
            "VALUES (?, ?, ?, ?, ?, 'text', ?, ?)",
            (row_id, user_id, chat_id, text, stamp, author, tg_id))
        await _insert(conn,
            "INSERT INTO smart_messages_fts (rowid, text) VALUES (?, ?)",
            (row_id, text))
        ids["messages"][row_id] = tg_id

    async def fact(row_id, text, stamp, *, origin="chat_history",
                   status="confirmed", target_user="Участник",
                   tg_id=None, subject_ref_id=None, speaker=None):
        await _insert(conn,
            "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
            "created_at, target_user, tg_message_id, forward_from, status, "
            "weight, last_confirmed_at, importance, subject_ref_id, "
            "speaker_author_id, attribution_method, assertion_kind, "
            "provenance_channel, message_timestamp) "
            "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, '', ?, 3, ?, 5, ?, ?, ?, ?, "
            "'live', ?)",
            (row_id, chat_id, text, origin, stamp, target_user, tg_id,
             status, stamp, subject_ref_id, speaker,
             ("self_report" if subject_ref_id else None),
             ("self_model" if subject_ref_id else "third_party"), stamp))
        await _insert(conn,
            "INSERT INTO graph_facts_fts (rowid, fact) VALUES (?, ?)",
            (row_id, text))
        ids["facts"][row_id] = stamp

    # ── 10 current (2026) facts: A1/A1P/T2/T3 classes ───────────────────
    for i in range(10):
        text = "шизы конфы: E1 было смешно 2026 выпуск %d" % i
        if i == 0:
            text += " " + SECRET_FACT_TEXT
        await fact(1000 + i, text, ts(2026, 1, 15, 9, i),
                   tg_id=7000 + i)
    # ── historical facts (A1/A1P/T2 historical period fill) ────────────
    await fact(1101, "шизы конфы в 2022: E1 было странно",
               ts(2022, 6, 10, 12, 0), tg_id=7101)
    await fact(1102, "шизы конфы в 2023: E1 было смешно",
               ts(2023, 3, 15, 10, 0), tg_id=7102)
    # ── D_2023: target + archived other-year pool row ───────────────────
    await fact(1203, "ссорились и ругались в 2024 из-за E1",
               ts(2024, 4, 1, 10, 0), status="archived_fact", tg_id=7203)
    await fact(1204, "ссорились и ругались в 2023 из-за E1",
               ts(2023, 5, 20, 10, 0), tg_id=7204)
    # ── people probes: 10 facts per person, 2026 ───────────────────────
    for offset, (uid, name) in enumerate(PEOPLE):
        for i in range(10):
            await fact(2000 + offset * 100 + i,
                       "%s любит дронов 2026 заметка %d" % (name, i),
                       ts(2026, 2, 1 + offset, 9, i), target_user=name,
                       tg_id=8000 + offset * 100 + i,
                       subject_ref_id=uid, speaker=uid)

    # ── dense lore messages: 3 windows × 3 rows, years 2022/2023/2026 ──
    # IDs are kept roughly chronological: 2022/2023 dense, then the 2023
    # episode span, then 2026 dense, people and recent fillers. This matters
    # for get_messages_around (id-based window).
    dense = (
        (2022, 6, 10, 12, "шизах конфы 2022 выпуск", 1001, 1),
        (2023, 3, 15, 10, "шизах конфы 2023 выпуск", 1004, 4),
        (2026, 1, 15, 9, "шизах конфы 2026 выпуск", 1007, 20),
    )
    for year, month, day, hour, text, tg0, base_id in dense:
        for i in range(3):
            body = text if i != 1 else (text + " " + SECRET_MSG_TEXT)
            await msg(base_id + i, 10 + i, "Участник%d" % (i + 1), body,
                      ts(year, month, day, hour, i * 5), tg0 + i)
    # ── 2023 episode span (Old_Episode_2023 / G4 sample) ───────────────
    for i in range(6):
        body = "ссорились и ругались E1 2023"
        if i == 2:
            body += " " + SECRET_MSG_TEXT
        await msg(10 + i, 20 + i, "Спорщик%d" % (i + 1), body,
                  ts(2023, 5, 20, 10, i), 2001 + i)
        ids["span"].append(10 + i)
    # ── recent fillers: push old episode rows out of the 40-row tail ───
    for i in range(60):
        await msg(60 + i, 30 + (i % 3), "Недавний%d" % (i % 3),
                  "recent filler note %d" % i,
                  ts(2026, 10, 1, 12, i), 3000 + i)
    # ── people display-name rows (A2 probe SQL) ────────────────────────
    for offset, (uid, name) in enumerate(PEOPLE):
        await msg(40 + offset, uid, name, "привет %s" % name,
                  ts(2026, 2, 1 + offset, 8, 0), 2400 + offset)
    # ── other chat (chat-scope probe) ──────────────────────────────────
    await _insert(conn,
        "INSERT INTO smart_messages (id, user_id, chat_id, text, timestamp, "
        "media_type, author_name, tg_message_id) "
        "VALUES (900, 999, ?, ?, ?, 'text', 'Other', 9001)",
        (other_chat, "шизы конфы otherchat " + SECRET_MSG_TEXT,
         ts(2026, 3, 1, 12, 0)))
    await _insert(conn,
        "INSERT INTO smart_messages_fts (rowid, text) VALUES (?, ?)",
        (900, "шизы конфы otherchat " + SECRET_MSG_TEXT))

    # ── graph nodes/edges + fact provenance ────────────────────────────
    nodes = ((1, "конфы", "topic"), (2, "шизах", "topic"),
             (3, "E1", "event"), (4, "Иван Петров", "user"))
    for node_id, name, kind in nodes:
        await _insert(conn,
            "INSERT INTO nodes (id, chat_id, entity_name, entity_type) "
            "VALUES (?, ?, ?, ?)", (node_id, chat_id, name, kind))
        ids["nodes"][node_id] = name
    await _insert(conn,
        "INSERT INTO edges (id, chat_id, source_id, target_id, relation_type, "
        "weight, fact_id) VALUES (1, ?, 1, 2, 'related_to', 3, 1000)",
        (chat_id,))
    await _insert(conn,
        "INSERT INTO edges (id, chat_id, source_id, target_id, relation_type, "
        "weight, fact_id) VALUES (2, ?, 1, 3, 'mentions', 2, NULL)",
        (chat_id,))

    # ── one legacy lore story for the 2023 episode channel ─────────────
    await _insert(conn,
        "INSERT INTO lore_stories (chat_id, topic_key, topic, story, last_ts, "
        "created_at, updated_at, origin, status, excluded_from_retrieval) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'lore_compiler', NULL, 0)",
        (chat_id, "ссорились и ругались в 2023",
         "ссорились и ругались в 2023", "ссорились ругались E1",
         ts(2023, 5, 20, 10, 5), ts(2023, 5, 20, 10, 6),
         ts(2023, 5, 20, 10, 6)))

    # ── one active proven community build (thematic probe) ─────────────
    summary = {
        "proven_community_ids": ["c1"],
        "proven_communities": [{
            "community_id": "c1", "status": "proven", "size": 1,
            "strong_share": 1.0, "density": 1.0, "basis": "probe"}]}
    await _insert(conn,
        "INSERT INTO mca_community_builds (build_id, chat_id, algorithm, "
        "algorithm_version, params_json, graph_revision, node_count, "
        "edge_count, prev_build_id, change_summary_json, status, started_at, "
        "finished_at) VALUES ('b1', ?, 'probe', '1', '{}', 'r1', 4, 2, "
        "NULL, ?, 'active', ?, ?)",
        (chat_id, json.dumps(summary), ts(2026, 1, 1), ts(2026, 1, 1)))
    await _insert(conn,
        "INSERT INTO mca_community_members (chat_id, build_id, community_id, "
        "node_id, member_weight, created_at) VALUES (?, 'b1', 'c1', 1, 1.0, ?)",
        (chat_id, ts(2026, 1, 1)))

    # ── source refs: same-chat vs other-chat (chat-scope probe) ─────────
    await _insert(conn,
        "INSERT INTO mca_source_refs (store, entity_type, entity_id, chat_id, "
        "revision, tg_message_id, resolution, created_at) "
        "VALUES ('smart_messages', 'message', '2003', ?, NULL, 2003, "
        "'resolved', ?)", (chat_id, ts(2023, 5, 20)))
    await _insert(conn,
        "INSERT INTO mca_source_refs (store, entity_type, entity_id, chat_id, "
        "revision, tg_message_id, resolution, created_at) "
        "VALUES ('smart_messages', 'message', '9001', ?, NULL, 9001, "
        "'resolved', ?)", (other_chat, ts(2026, 3, 1)))

    # ── one embedding generation row (fingerprint visibility) ──────────
    await _insert(conn,
        "INSERT INTO mca_embedding_index_generations (index_name, generation, "
        "fingerprint, provider, model, dims, preprocessing_version, namespace, "
        "config_revision, status, created_at, activated_at) "
        "VALUES ('graph_facts_vec', 1, 'fixture-fp', 'probe', 'probe', 3072, "
        "'v1', 'default', 'fixture', 'active', ?, ?)",
        (ts(2026, 1, 1), ts(2026, 1, 1)))

    await conn.commit()
    # Standalone snapshot (no WAL sidecar) for the read-only harness.
    await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    await conn.commit()
    await conn.rollback()
    await conn.execute("PRAGMA journal_mode=DELETE")
    await conn.commit()
    await db.close()
    return {
        "chat_id": chat_id,
        "other_chat_id": other_chat,
        "people": [{"uid": uid, "name": name} for uid, name in PEOPLE],
        "facts": {str(k): v for k, v in ids["facts"].items()},
        "messages": {str(k): v for k, v in ids["messages"].items()},
        "episode_span_rows": list(ids["span"]),
        "secret_markers": [SECRET_FACT_TEXT, SECRET_MSG_TEXT],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--chat-id", type=int, default=CHAT)
    args = parser.parse_args(argv)
    meta = asyncio.run(build_fixture(args.db, chat_id=args.chat_id))
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
