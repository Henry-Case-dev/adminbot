"""D1 probe: full period-fill -> profile chain on a real (in-memory) DB.

Не тест, а компактное воспроизведение продуктовой последовательности из
five-class evidence: base(8)+accepted period rows(2) -> профильный шаг.
RUN: python d1_probe_chain.py  (cwd = checkout под проверкой)
"""
import asyncio
import calendar
import json
import sys

from services import direct_chat_service as dcs
from services.database import DatabaseService

CHAT = -100
UID = 7


def ts(year, month=6, day=1):
    return calendar.timegm((year, month, day, 12, 0, 0, 0, 0, 0))


async def _fact(db, text, year, origin, target="Вася", speaker=UID):
    return await db.insert_graph_fact(
        CHAT, text, origin, None, target_user=target, status="confirmed",
        weight=0.6, importance=5, message_timestamp=ts(year),
        speaker_author_id=speaker, subject_ref_id=15000,
        attribution_method="self_report",
        tg_message_id=9000 + abs(hash(text)) % 5000)


async def main(profile_origin):
    db = DatabaseService(":memory:")
    await db.initialize()
    for i in range(12):
        await _fact(db, f"бот в 2026 сказал про Васю #{i}", 2026, profile_origin)
    service = dcs.DirectChatService(memory=object(), db=db, llm=None,
                                    aliases=None)
    base = [{"id": 9100 + i, "fact": f"текущий {i}", "origin": "chat_history",
             "status": "confirmed", "rag_ts": ts(2026),
             "message_timestamp": ts(2026)} for i in range(8)]
    accepted = [{"id": 30709, "fact": "Вася уточняет", "origin": "history_import",
                 "status": "confirmed", "rag_ts": ts(2026),
                 "message_timestamp": ts(2026)},
                {"id": 5567, "fact": "Вася Поляна", "origin": "history_import",
                 "status": "confirmed", "rag_ts": ts(2025),
                 "message_timestamp": ts(2025)}]
    rows = dcs.DirectChatService._rag_append_period_rows(base, accepted, 10,
                                                        slots=2)
    before = [row["id"] for row in rows]
    out = await service._rag_append_profile_rows(
        db, rows, CHAT, "расскажи, что за человек Вася, по его сообщениям",
        "Вася", UID, 10, allow_replace=True)
    after = [row["id"] for row in out]
    print(json.dumps({
        "profile_origin": profile_origin,
        "after_period_append": before,
        "after_profile_step": after,
        "lost": sorted(set(before) - set(after)),
        "added": sorted(set(after) - set(before)),
        "base_rows_kept": [row["id"] for row in base if row["id"] in after]
                          == [row["id"] for row in base],
        "len": len(out),
    }, ensure_ascii=False))
    await db.close()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    for origin in ("bot_direct_reply", "chat_history"):
        loop.run_until_complete(main(origin))
    loop.close()
