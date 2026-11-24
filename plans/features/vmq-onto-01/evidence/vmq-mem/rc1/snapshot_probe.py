"""VMQ-MEM-RC1 read-only snapshot probe (before/after facade).

Opens snapshot-2.58.225.db with mode=ro&immutable=1 + PRAGMA query_only=ON.
Writes only IDs/counters/kinds, no story texts. Run from the RC1 worktree:
  python plans/features/vmq-onto-01/evidence/vmq-mem/rc1/snapshot_probe.py
"""
import asyncio
import json
import os
import sys

import aiosqlite

WT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", ".."))
SNAP = r"C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\snapshot-2.58.225.db"
OUT = os.path.join(os.path.dirname(__file__), "snapshot-before-after.json")
CHAT = -1002661910336
LIMIT = 200
os.chdir(WT)
sys.path.insert(0, WT)

from services.database import DatabaseService  # noqa: E402
from services.mca_episodes import (  # noqa: E402
    EpisodeRepository,
    effective_story,
    list_stories_for_retrieval,
)


async def _before_facade(db, chat_id=CHAT, limit=LIMIT):
    """Pre-RC1 algorithm, verbatim, for the before measurement."""
    repo = EpisodeRepository(db)
    out = []
    stories = await repo.list_stories(int(chat_id), limit=max(1, int(limit)))
    for row in stories:
        if int(row.get("excluded_from_retrieval") or 0):
            continue
        if str(row.get("verification") or "") == "rejected":
            continue
        story = effective_story(row)
        out.append({
            "id": story["story_id"], "chat_id": int(chat_id),
            "topic_key": "", "topic": str(story.get("title") or ""),
            "story": str(story.get("summary") or ""),
            "last_ts": int(story.get("event_end_ts")
                           or story.get("updated_at") or 0),
            "created_at": int(story.get("discovered_at") or 0),
            "updated_at": int(story.get("updated_at") or 0),
            "kind": "story",
        })
    redirected = {
        str(r.get("old_id")) for r in await repo._fetch_all(
            "SELECT old_id FROM mca_story_redirects WHERE old_kind = 'story'")
    }
    out = [row for row in out if str(row["id"]) not in redirected]
    cursor = await db.db.execute(
        "SELECT l.* FROM lore_stories l LEFT JOIN mca_story_legacy_links "
        "g ON g.lore_story_id = l.id WHERE l.chat_id = ? AND "
        "COALESCE(g.mapping_status, 'unmapped') != 'mapped' AND "
        "COALESCE(l.excluded_from_retrieval, 0) = 0 "
        "AND COALESCE(l.status, '') != 'rejected' "
        "ORDER BY l.updated_at DESC LIMIT ?",
        (int(chat_id), max(1, int(limit))))
    for row in await cursor.fetchall():
        legacy = dict(row)
        legacy["kind"] = "legacy_story"
        out.append(legacy)
    out.sort(key=lambda r: int(r.get("updated_at") or 0), reverse=True)
    return out[:max(1, int(limit))]


def _summary(rows):
    legacy = sorted(int(r["id"]) for r in rows
                    if r.get("kind") == "legacy_story")
    ids = {str(r["id"]) for r in rows}
    return {
        "total": len(rows),
        "new_stories": sum(1 for r in rows if r.get("kind") == "story"),
        "legacy_ids": legacy,
        "legacy_5_8_present": all(str(i) in ids for i in range(5, 9)),
        "rejected_3_4_present": any(str(i) in ids for i in (3, 4)),
    }


async def main():
    ds = DatabaseService(SNAP)
    uri = "file:" + SNAP.replace("\\", "/") + "?mode=ro&immutable=1"
    ds.db = await aiosqlite.connect(uri, uri=True)
    ds.db.row_factory = aiosqlite.Row
    await ds.db.execute("PRAGMA query_only=ON")
    try:
        before = _summary(await _before_facade(ds))
        after = _summary(await list_stories_for_retrieval(ds, CHAT, LIMIT))
    finally:
        await ds.db.close()
    result = {
        "artifact_kind": "vmq_mem_rc1_snapshot_probe",
        "snapshot": SNAP,
        "snapshot_sha256_expected": "b907d4c1e24321fffa48e3719974fd2293b1b1ff721ad21661446d22033e06e7",
        "chat_id": CHAT,
        "limit": LIMIT,
        "mode": "mode=ro&immutable=1; PRAGMA query_only=ON",
        "before": before,
        "after": after,
        "pass": {
            "before_dropped_5_8": not before["legacy_5_8_present"],
            "after_all_5_16": after["legacy_ids"] == list(range(5, 17)),
            "rejected_absent": not after["rejected_3_4_present"],
            "total_200": before["total"] == LIMIT and after["total"] == LIMIT,
        },
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=True, indent=1)
    print(json.dumps(result, ensure_ascii=True, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
