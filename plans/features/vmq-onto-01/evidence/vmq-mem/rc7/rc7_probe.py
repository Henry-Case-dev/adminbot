"""VMQ-MEM RC7 read-only snapshot probe: story → episode links → anchors."""
import asyncio
import hashlib
import json
import os
import sys

import aiosqlite

WT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "..", ".."))
SNAP = r"C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\snapshot-2.58.225.db"
OUT = os.path.join(os.path.dirname(__file__), "rc7-snapshot.json")
CHAT = -1002661910336
SAMPLE = 16
os.chdir(WT)
sys.path.insert(0, WT)

from services.database import DatabaseService  # noqa: E402
from services.mca_episodes import story_message_anchors  # noqa: E402


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _count(ds, sql, params=()):
    cursor = await ds.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row["n"])


async def main():
    before = _sha256(SNAP)
    ds = DatabaseService(SNAP)
    uri = "file:" + SNAP.replace("\\", "/") + "?mode=ro&immutable=1"
    ds.db = await aiosqlite.connect(uri, uri=True)
    ds.db.row_factory = aiosqlite.Row
    await ds.db.execute("PRAGMA query_only=ON")
    try:
        cursor = await ds.db.execute(
            "SELECT story_id FROM mca_stories WHERE chat_id = ? "
            "ORDER BY updated_at DESC, story_id DESC LIMIT ?",
            (CHAT, SAMPLE))
        story_ids = [str(row["story_id"]) for row in await cursor.fetchall()]
        anchors = await story_message_anchors(
            ds, CHAT, story_ids, per_story=2, limit=8)
        refs = [ref for values in anchors.values() for ref in values]
        absent = await story_message_anchors(
            ds, CHAT, ["no-such-story-rc7"], per_story=2, limit=8)
        counts = {
            "stories": await _count(
                ds, "SELECT COUNT(*) AS n FROM mca_stories WHERE chat_id = ?",
                (CHAT,)),
            "episode_links": await _count(
                ds,
                "SELECT COUNT(*) AS n FROM mca_story_episode_links l "
                "JOIN mca_episodes e ON e.episode_id = l.episode_id "
                "WHERE e.chat_id = ?", (CHAT,)),
            "episodes_with_keys": await _count(
                ds,
                "SELECT COUNT(*) AS n FROM mca_episodes WHERE chat_id = ? "
                "AND message_keys_json NOT IN ('', '[]')", (CHAT,)),
            "legacy_links_total": await _count(
                ds, "SELECT COUNT(*) AS n FROM mca_story_legacy_links"),
        }
    finally:
        await ds.db.close()
    after = _sha256(SNAP)
    result = {
        "artifact_kind": "vmq_mem_rc7_snapshot_probe",
        "snapshot": SNAP,
        "mode": "mode=ro&immutable=1; PRAGMA query_only=ON",
        "chat_id": CHAT,
        "sample_stories": len(story_ids),
        "stories_with_anchors": len(anchors),
        "anchors_total": len(refs),
        "anchor_tg": sum(1 for ref in refs if ref.startswith("tg:")),
        "anchor_msg": sum(1 for ref in refs if ref.startswith("msg:")),
        "per_story_max": max((len(v) for v in anchors.values()), default=0),
        "absent_story_anchors": bool(absent),
        "counts": counts,
        "snapshot_sha256_before": before,
        "snapshot_sha256_after": after,
        "read_only": before == after,
        "pass": {
            "anchors_ge_1": len(refs) >= 1,
            "anchors_are_canonical": all(
                ref.startswith("tg:") or ref.startswith("msg:")
                for ref in refs),
            "per_story_bounded": (max(
                (len(v) for v in anchors.values()), default=0) <= 2),
            "absent_story_honest": not absent,
            "legacy_not_mapped": counts["legacy_links_total"] == 0,
            "snapshot_unchanged": before == after,
        },
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=True, indent=1)
    print(json.dumps(result, ensure_ascii=True, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
