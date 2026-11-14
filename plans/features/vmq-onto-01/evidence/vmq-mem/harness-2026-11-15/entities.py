# -*- coding: utf-8 -*-
"""Deterministic entity selection for the VMQ-MEM/TIME measurement.

Chooses, from the frozen DB copy and the fixed chat:
  * P1 - the participant with the most 2023-2024 messages (TIME-02 subject);
  * E1 - a topic token that is frequent in 2023 and much rarer in 2026
         (TIME-03 / TIME-04 event anchor, same selection rule as the
         previous measurement so the two runs stay comparable).

Writes entities.json (contains the real name/token: server-side temp only).
Both variants read the same file, so the A/B pair is measured on identical
subjects.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys

CLONE = os.environ.get("VMQ_CLONE", "/root/vmq2/measure/repo-base")
DBPATH = os.environ.get("VMQ_DB", "/root/vmq2/measure/dbcopy.db")
OUT = os.environ.get("VMQ_ENT", "/root/vmq2/measure/entities.json")
APP = "/var/www/admin_bot"
CHAT = -1002661910336

sys.path.insert(0, CLONE)
os.chdir(APP)

Y2023 = (1672531200, 1704067199)
Y2024 = (1704067200, 1735689599)
Y2026 = (1767225600, 1798761599)
WORD = re.compile(r"[А-Яа-яЁёA-Za-z]{6,}")
# function words are not events: they would make the "event without a year"
# class meaningless (the previous run picked "всегда" and that is not a topic).
STOP = frozenset({
    "всегда", "вообще", "просто", "почему", "когда", "поэтому", "сейчас",
    "только", "можно", "нужно", "очень", "чтобы", "потому", "значит",
    "какой", "такая", "такие", "этого", "этому", "если", "даже", "хотя",
    "кроме", "через", "после", "перед", "между", "около", "теперь", "потом",
    "почти", "вполне", "конечно", "например", "который", "которая", "которые",
    "такого", "таком", "своих", "своими", "ничего", "никогда", "сколько",
    "другой", "другая", "другие", "хорошо", "плохо", "ладно", "кстати",
})


def _sql(sql: str, params=()) -> list:
    con = sqlite3.connect("file:%s?mode=ro" % DBPATH, uri=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def main() -> int:
    from services.database import DatabaseService
    from services.summary_memory import build_fts_query

    async def go() -> dict:
        db = DatabaseService(DBPATH)
        await db.initialize()
        try:
            rows = _sql(
                "SELECT user_id, author_name, COUNT(*) FROM smart_messages "
                "WHERE chat_id=? AND timestamp BETWEEN ? AND ? "
                "AND author_name<>'' AND text<>'' GROUP BY user_id "
                "ORDER BY 3 DESC LIMIT 6", (CHAT, Y2023[0], Y2024[1]))
            cand = []
            for uid, name, cnt in rows:
                r26 = _sql(
                    "SELECT COUNT(*) FROM smart_messages WHERE chat_id=? "
                    "AND user_id=? AND timestamp BETWEEN ? AND ?",
                    (CHAT, uid, Y2026[0], Y2026[1]))[0][0]
                cand.append({"uid": uid, "name": name,
                             "msgs_2023_2024": int(cnt),
                             "msgs_2026": int(r26 or 0)})
            person = max(cand, key=lambda c: c["msgs_2023_2024"])
            sample = _sql(
                "SELECT text FROM smart_messages WHERE chat_id=? AND timestamp "
                "BETWEEN ? AND ? AND length(text)>25 LIMIT 8000",
                (CHAT, Y2023[0], Y2023[1]))
            freq: dict[str, int] = {}
            for (text,) in sample:
                for word in set(w.lower() for w in WORD.findall(text or "")):
                    freq[word] = freq.get(word, 0) + 1
            tokens = [w for w, n in sorted(freq.items(), key=lambda kv: -kv[1])
                      if n >= 3 and w not in STOP][:6]

            async def _count(match, since, until):
                try:
                    got = await asyncio.wait_for(
                        db.search_messages_fts_count_by_author(
                            CHAT, match, since_ts=since, until_ts=until),
                        timeout=40)
                    return int(got.get("count") or 0)
                except Exception:      # noqa: BLE001
                    return -1

            scored = []
            for token in tokens:
                match = build_fts_query([token])
                if not match:
                    continue
                c23 = await _count(match, Y2023[0], Y2023[1])
                if c23 < 80:
                    continue
                c26 = await _count(match, Y2026[0], Y2026[1])
                scored.append({"token": token, "count_2023": c23,
                               "count_2026": c26,
                               "ratio_2026_to_2023": (round(c26 / c23, 3)
                                                      if c23 > 0 else None)})
            # an event anchor must be a TOPIC that is clearly denser in 2023
            # than in 2026; among those prefer the richest 2023 support.
            topic_like = [row for row in scored
                          if row["count_2026"] >= 0
                          and row["count_2026"] < row["count_2023"] / 4]
            chosen = (max(topic_like, key=lambda r: r["count_2023"])
                      if topic_like else None)
            if chosen is None and scored:
                chosen = min(scored, key=lambda r: (r["ratio_2026_to_2023"]
                                                    if r["ratio_2026_to_2023"]
                                                    is not None else 99))
            return {"chat_id": CHAT, "person": person,
                    "event": chosen, "person_candidates": len(cand),
                    "event_scored": scored}
        finally:
            await db.close()

    out = asyncio.run(go())
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("ENT_OK person_msgs=%s event2023=%s event2026=%s"
          % (out["person"]["msgs_2023_2024"],
             (out["event"] or {}).get("count_2023"),
             (out["event"] or {}).get("count_2026")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
