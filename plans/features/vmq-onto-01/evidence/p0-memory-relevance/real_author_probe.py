"""Read-only probe: author_window на реальном архиве (F1 review r1).

Запуск: python real_author_probe.py <archive.db>
Только чтение (`initialize_readonly`), без production-записей.
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "..", "..", "..", "..", "..")))

from services import mca_retrieval_context as rc      # noqa: E402
from services.database import DatabaseService         # noqa: E402

CHAT = -1002661910336
AUTHOR = 138811255


async def main(path: str) -> None:
    db = DatabaseService(path)
    await db.initialize_readonly()
    try:
        cur = await db.db.execute(
            "SELECT COUNT(*) FROM smart_messages WHERE chat_id = ?",
            (CHAT,))
        total = int((await cur.fetchone())[0])
        print("chat rows:", total)
        # Существующее авторское чтение: сколько строк реально есть.
        rows = await db.get_author_message_periods(CHAT, AUTHOR, 60,
                                                   years=(2025,))
        print("author rows 2025 (existing read):", len(rows))
        request = dataclasses.replace(
            rc.build_memory_request(
                chat_id=CHAT, topic="манера поздравлений 2025 год",
                author_uid=AUTHOR, top_k=12),
            period_fill=True, memory_scope="historical")
        result = await rc.retrieve(db, memory=None, request=request)
        own = [cand for cand in result.candidates
               if cand.entity_type == "message" and cand.author_id == AUTHOR]
        years = sorted({rc._candidate_year(cand) for cand in own})
        channels = sorted({cand.channel for cand in own})
        print("retrieve candidates:", len(result.candidates))
        print("author-original candidates:", len(own), "years:", years,
              "channels:", channels)
        print("period usage:", (result.period_fill or {}).get("rows_in_target"))
    finally:
        await db.close()


asyncio.run(main(sys.argv[1]))
