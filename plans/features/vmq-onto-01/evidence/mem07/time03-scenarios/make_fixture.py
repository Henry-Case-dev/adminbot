# -*- coding: utf-8 -*-
"""Synthetic SQLite fixture for the VMQ-MEM-07 independent harness.

Evidence tooling only. It creates a fresh DB with the product schema via
DatabaseService.initialize(), inserts a deterministic synthetic corpus, then
closes. The harness opens it strictly read-only.

No real names, messages or facts are used. Sentinel markers let the smoke test
prove that no text leaks into harness outputs.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os

CHAT = -1002661910336
OTHER_CHAT = -1009999999999
SECRET_FACT_TEXT = "SECRET_FACT_TEXT_MEM07"
SECRET_MSG_TEXT = "SECRET_MSG_TEXT_MEM07"

PEOPLE = ((111, "Участник Один"), (222, "Участник Два"), (333, "Участник Три"))


def ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(datetime.datetime(
        year, month, day, hour, minute, tzinfo=datetime.timezone.utc).timestamp())


async def build_fixture(db_path: str, *, chat_id: int = CHAT,
                        other_chat: int = OTHER_CHAT) -> dict:
    if os.path.exists(db_path):
        raise FileExistsError(db_path)
    from services.database import DatabaseService

    db = DatabaseService(db_path)
    await db.initialize()
    conn = db.db
    meta = {"chat_id": chat_id, "other_chat_id": other_chat,
            "messages": 0, "facts": 0, "years": {},
            "secret_markers": [SECRET_FACT_TEXT, SECRET_MSG_TEXT]}

    async def msg(row_id, user_id, author, text, stamp, tg_id):
        await conn.execute(
            "INSERT INTO smart_messages (id, user_id, chat_id, text, timestamp, "
            "media_type, author_name, tg_message_id) VALUES (?, ?, ?, ?, ?, "
            "'text', ?, ?)", (row_id, user_id, chat_id, text, stamp, author, tg_id))
        await conn.execute(
            "INSERT INTO smart_messages_fts (rowid, text) VALUES (?, ?)",
            (row_id, text))
        meta["messages"] += 1
        year = str(datetime.datetime.fromtimestamp(
            stamp, tz=datetime.timezone.utc).year)
        meta["years"][year] = meta["years"].get(year, 0) + 1

    async def fact(row_id, text, stamp, *, origin="chat_history",
                   status="confirmed", target_user="Участник", tg_id=None,
                   subject_ref_id=None, speaker=None):
        await conn.execute(
            "INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, "
            "created_at, target_user, tg_message_id, forward_from, status, "
            "weight, last_confirmed_at, importance, subject_ref_id, "
            "speaker_author_id, attribution_method, assertion_kind, "
            "provenance_channel, message_timestamp) VALUES (?, ?, ?, ?, NULL, "
            "?, ?, ?, '', ?, 3, ?, 5, ?, ?, ?, ?, 'live', ?)",
            (row_id, chat_id, text, origin, stamp, target_user, tg_id, status,
             stamp, subject_ref_id, speaker,
             ("self_report" if subject_ref_id else None),
             ("self_model" if subject_ref_id else "third_party"), stamp))
        await conn.execute(
            "INSERT INTO graph_facts_fts (rowid, fact) VALUES (?, ?)",
            (row_id, text))
        meta["facts"] += 1

    next_msg = 1000
    next_fact = 5000

    async def topic_messages(topic, year, count, extra=""):
        nonlocal next_msg
        for i in range(count):
            text = "%s %d выпуск %d%s" % (topic, year, i, extra)
            if i == 0 and topic == "шизы конфы":
                text += " " + SECRET_MSG_TEXT
            await msg(next_msg, 10 + (i % 3), "Голос%d" % (i % 3), text,
                      ts(year, 3, 10, 9, i), next_msg + 50000)
            next_msg += 1

    async def topic_facts(topic, year, count, extra=""):
        nonlocal next_fact
        for i in range(count):
            text = "%s %d факт %d%s" % (topic, year, i, extra)
            if i == 0 and topic == "шизы конфы":
                text += " " + SECRET_FACT_TEXT
            await fact(next_fact, text, ts(year, 3, 10, 10, i),
                       tg_id=next_fact + 50000)
            next_fact += 1

    for year in (2022, 2023, 2024, 2025, 2026):
        await topic_messages("шизы конфы", year, 6)
        await topic_facts("шизы конфы", year, 5)
        await topic_messages("дружба отношения ссорились", year, 4)
        await topic_facts("дружба отношения ссорились", year, 4)
    await topic_messages("ремонт ванной история", 2022, 8)
    await topic_facts("ремонт ванной история", 2022, 6)
    await topic_messages("собака история", 2024, 8)
    await topic_facts("собака история", 2024, 6)
    await topic_messages("конфликт на конфе ссорились ругались", 2023, 8)
    await topic_facts("конфликт на конфе ссорились ругались", 2023, 6)
    await topic_messages("ругались ссорились", 2024, 8)
    await topic_facts("ругались ссорились", 2024, 6)
    for year in (2023, 2026):
        await topic_messages("работа зарплата", year, 8)
        await topic_facts("работа зарплата", year, 6)
    for year in (2025, 2026):
        await topic_messages("шаурма история", year, 5)
        await topic_facts("шаурма история", year, 5)
    for year in (2022, 2026):
        await topic_messages("органная музыка концерт", year, 5)
        await topic_facts("органная музыка концерт", year, 5)
    await topic_messages("витамины история", 2025, 6)
    await topic_facts("витамины история", 2025, 6)
    # current-state rows: old topic still has 2026 material
    await topic_messages("ремонт ванной история", 2026, 6)
    await topic_facts("ремонт ванной история", 2026, 5)
    await topic_messages("собака история", 2026, 6)
    await topic_facts("собака история", 2026, 5)
    # changed-position pair
    await fact(next_fact, "сервер вайпнут в 2024, сервер не работает",
               ts(2024, 7, 1, 12, 0), tg_id=next_fact + 50000)
    next_fact += 1
    await fact(next_fact, "сервер снова работает, сейчас сервер жив",
               ts(2026, 2, 1, 12, 0), tg_id=next_fact + 50000)
    next_fact += 1
    # participants: enough messages/facts for runtime selection
    for uid, name in PEOPLE:
        for year in (2022, 2023, 2024, 2025):
            for i in range(15):
                text = "%s заметка %d %d" % (name, year, i)
                await msg(next_msg, uid, name, text, ts(year, 5, 1, 8, i),
                          next_msg + 50000)
                next_msg += 1
            for i in range(5):
                await fact(next_fact, "%s факт %d %d" % (name, year, i),
                           ts(year, 5, 1, 9, i), target_user=name,
                           tg_id=next_fact + 50000, subject_ref_id=uid,
                           speaker=uid)
                next_fact += 1
    # recent filler pushes old episode rows out of the 40-row tail
    for i in range(60):
        await msg(next_msg, 30 + (i % 3), "Недавний%d" % (i % 3),
                  "recent filler note %d" % i, ts(2026, 10, 1, 12, i),
                  next_msg + 50000)
        next_msg += 1
    # other chat (scope sanity; never expected in target)
    await conn.execute(
        "INSERT INTO smart_messages (id, user_id, chat_id, text, timestamp, "
        "media_type, author_name, tg_message_id) VALUES (?, 999, ?, ?, ?, "
        "'text', 'Other', 99999)", (next_msg, other_chat,
                                   "шизы конфы otherchat " + SECRET_MSG_TEXT,
                                   ts(2026, 3, 1, 12, 0)))
    await conn.execute(
        "INSERT INTO smart_messages_fts (rowid, text) VALUES (?, ?)",
        (next_msg, "шизы конфы otherchat " + SECRET_MSG_TEXT))
    # minimal graph nodes/edges and lore story (episode channel can stay empty)
    for node_id, name, kind in ((1, "шизы", "topic"), (2, "конфы", "topic"),
                                (3, "сервер", "event")):
        await conn.execute(
            "INSERT INTO nodes (id, chat_id, entity_name, entity_type) "
            "VALUES (?, ?, ?, ?)", (node_id, chat_id, name, kind))
    await conn.execute(
        "INSERT INTO edges (id, chat_id, source_id, target_id, relation_type, "
        "weight, fact_id) VALUES (1, ?, 1, 2, 'related_to', 3, 5000)",
        (chat_id,))
    # explicit-year episode rows for the Old_Episode 2023/2024 probes
    for topic_key, topic, story, stamp in (
            ("episode_2023", "конфликт на конфе 2023",
             "конфликт на конфе 2023 ссорились ругались", ts(2023, 5, 20, 10, 5)),
            ("episode_2024", "собака 2024",
             "собака история 2024", ts(2024, 6, 10, 10, 5))):
        await conn.execute(
            "INSERT INTO lore_stories (chat_id, topic_key, topic, story, "
            "last_ts, created_at, updated_at, origin, status, "
            "excluded_from_retrieval) VALUES (?, ?, ?, ?, ?, ?, ?, "
            "'lore_compiler', NULL, 0)",
            (chat_id, topic_key, topic, story, stamp, stamp, stamp))
    await conn.commit()
    await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    await conn.commit()
    await conn.rollback()
    await conn.execute("PRAGMA journal_mode=DELETE")
    await conn.commit()
    await db.close()
    meta["next_msg"] = next_msg
    meta["next_fact"] = next_fact
    return meta


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