"""P0 memory-relevance lane B: compact A/B/C/D probe on a real SQLite fixture.

Read-only diagnostic. Seeds a local in-memory DatabaseService with a
production-shaped congratulation scenario and prints, for each variant, the
material that would reach the Writer payload:

  A  current direct-turn memory leg  -> build_memory_request + retrieve()
  B  direct original-message selection via existing FTS with author+period
  C  existing hybrid retrieval (vector/graph/episodes) — same retrieve() as A,
     reported separately (retrieval output before later filtering/packing)
  D  control: Writer with known-good originals (material only, no LLM here)

No production writes, no network, no embedding calls.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                "..", "..", "..", "..", "..")))

from services import mca_retrieval_context as rc          # noqa: E402
from services.database import DatabaseService             # noqa: E402

CHAT = -9001001
NIKITA = 777
OTHER = 888
ASKER = 999

T2022 = 1650000000          # 2022-04-15
T2023 = 1686820800          # 2023-06-15
T2024 = 1718424000          # 2024-06-15
T2025 = 1749960000          # 2025-06-15

NIKITA_CONGRATS = {
    T2023: "Поздравляю с днём рождения, братан! Желаю тебе горы бабок и "
           "чтобы башка не болела после пятницы.",
    T2024: "С днюхой, старик! Пусть всё будет ровно, а рыба клюёт сама.",
    T2025: "Поздравляю, дружище! Здоровья, денег и поменьше душных людей "
           "вокруг.",
}
OTHERS_CONGRATS = {
    T2024: "Никита, с днём рождения! Ты лучший, успехов во всём.",
    T2025: "Никита, поздравляю! Пусть всё получается.",
}
NOISE = {
    T2024: "Кто-нибудь видел мой ключ от гаража?",
    T2025: "Напиши мне потом, я забыл что хотел.",
}


async def _db() -> DatabaseService:
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _add_msg(db, chat, tg, user, text, ts) -> None:
    await db.save_smart_message(
        user_id=user, chat_id=chat, text=text, reply_to_id=None,
        timestamp=ts, media_type="text", author_name="", message_id=tg)


async def _add_fact(db, *, chat, fact, ts, target_user=None,
                    subject_ref_id=None, speaker=None) -> None:
    await db.db.execute(
        "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
        "target_user, tg_message_id, status, message_timestamp, weight, "
        "importance, subject_ref_id, speaker_author_id, "
        "attribution_method, assertion_kind, provenance_channel) "
        "VALUES (?, ?, 'chat_history', ?, ?, NULL, 'confirmed', ?, 1.0, 3, "
        "?, ?, ?, ?, ?)",
        (chat, fact, ts, target_user, ts, subject_ref_id, speaker,
         "self_report" if speaker is not None else None,
         "biographical" if speaker is not None else None,
         "chat_history" if speaker is not None else None))
    await db.db.commit()


async def seed(db):
    tg = 1000
    for ts, text in NIKITA_CONGRATS.items():
        await _add_msg(db, CHAT, tg, NIKITA, text, ts)
        tg += 1
    for ts, text in OTHERS_CONGRATS.items():
        await _add_msg(db, CHAT, tg, OTHER, text, ts)
        tg += 1
    for ts, text in NOISE.items():
        await _add_msg(db, CHAT, tg, ASKER, text, ts)
        tg += 1
    # derived facts about Никита (attribution surface used by the fact leg)
    await _add_fact(db, chat=CHAT, fact="Никита любит рыбалку",
                    ts=T2024, target_user=str(NIKITA))
    await _add_fact(db, chat=CHAT, fact="Никита написал поздравление брату",
                    ts=T2025, target_user=str(NIKITA), speaker=OTHER)
    await _add_fact(db, chat=CHAT, fact="у чата есть традиция поздравлять "
                                       "друг друга стихами", ts=T2025)


def _describe(cands):
    rows = []
    for cand in cands:
        rows.append({
            "type": cand.entity_type,
            "channel": cand.channel,
            "author_id": cand.author_id,
            "speaker_entity_id": cand.speaker_entity_id,
            "subject_entity_id": cand.subject_entity_id,
            "year": (__import__("time").gmtime(cand.sent_at).tm_year
                     if cand.sent_at else None),
            "preview": (cand.preview or "")[:70],
        })
    return rows


def _metrics(rows, *, author=NIKITA, years=None):
    total = len(rows)
    by_author = sum(1 for r in rows if r["author_id"] == author)
    msgs = [r for r in rows if r["type"] == "message"]
    msgs_by_author = sum(1 for r in msgs if r["author_id"] == author)
    period_ok = None
    if years is not None:
        period_ok = sum(1 for r in rows if r["year"] in years)
    return {
        "items": total,
        "messages": len(msgs),
        "messages_by_author": msgs_by_author,
        "facts": sum(1 for r in rows if r["type"] == "graph_fact"),
        "author_matches": by_author,
        "other_people_items": total - by_author,
        "in_period": period_ok,
    }


async def main():
    db = await _db()
    await seed(db)

    query_a = ("напиши поздравление Никите в его манере, "
               "как он сам поздравлял за прошедший год")
    # A: exactly what the live direct turn builds (addressee -> subject)
    req_a = rc.build_memory_request(
        chat_id=CHAT, topic=query_a, addressee_uid=NIKITA,
        addressee_name="Никита", top_k=12)
    res_a = await rc.retrieve(db, memory=None, request=req_a)
    rows_a = _describe(res_a.candidates)
    print("A request:", req_a.subject_entity_ids, req_a.participants,
          req_a.time_from, req_a.time_to, "| mode:", res_a.mode,
          "| reason:", res_a.reason_code)
    print("A metrics:", _metrics(rows_a))
    for row in rows_a:
        print("   ", row)

    # B: direct original-message selection, existing FTS, author + period
    from services.summary_memory import build_fts_query
    from services.mca_retrieval_context import year_time_bounds
    low, high = year_time_bounds(2025)
    match = build_fts_query(["поздравл"])
    rows_b = await db.search_messages_fts(
        CHAT, match, 50, since_ts=low, until_ts=high + 1,
        author_ids=[NIKITA], order="time")
    rows_b = [dict(row) for row in rows_b]
    print("\nB rows:", len(rows_b))
    for row in rows_b:
        print("    ", row["user_id"], row["timestamp"], str(row["text"])[:60])
    print("B metrics:", {
        "items": len(rows_b),
        "messages_by_author": sum(1 for r in rows_b
                                  if int(r["user_id"]) == NIKITA),
        "in_period": sum(1 for r in rows_b
                         if low <= int(r["timestamp"]) <= high),
    })

    # A2: same package path, but with the explicit author constraint
    import dataclasses
    req_a2 = dataclasses.replace(
        rc.build_memory_request(
            chat_id=CHAT,
            topic="поздравление в манере Никиты за 2025 год",
            addressee_uid=OTHER, addressee_name="Никита",
            author_uid=NIKITA, top_k=12),
        period_fill=True, memory_scope="historical")
    if req_a2 is not None:
        res_a2 = await rc.retrieve(db, memory=None, request=req_a2)
        rows_a2 = _describe(res_a2.candidates)
        print("\nA2 (author=Никита, year=2025) request:",
              req_a2.author_entity_ids, req_a2.subject_entity_ids,
              "| period_fill:", req_a2.period_fill)
        print("A2 metrics:", _metrics(rows_a2, years={2025}))
        for row in rows_a2:
            print("   ", row)

    # C: existing hybrid retrieval: same retrieve() without subject/addressee
    req_c = rc.RetrievalRequest(chat_id=CHAT, query=query_a, top_k=12)
    res_c = await rc.retrieve(db, memory=None, request=req_c)
    rows_c = _describe(res_c.candidates)
    print("\nC channels:", res_c.channels_used, "| mode:", res_c.mode)
    print("C metrics:", _metrics(rows_c))
    for row in rows_c:
        print("   ", row)

    # D: control material (known-good originals) — what the Writer should see
    rows_d = [{"author_id": NIKITA, "year": 2025,
               "text": NIKITA_CONGRATS[T2025]}]
    print("\nD control items:", len(rows_d),
          "| author:", rows_d[0]["author_id"], "| year:", rows_d[0]["year"])


asyncio.run(main())
