"""VMQ-MEM RC6a read-only snapshot probe: card metadata + alias links."""
import asyncio
import collections
import datetime
import json
import os
import sys

import aiosqlite

WT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", ".."))
SNAP = r"C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\snapshot-2.58.225.db"
OUT = os.path.join(os.path.dirname(__file__), "rc6a-snapshot.json")
CHAT = -1002661910336
UID_LEKHA = 138811255
NOW = 1795187666
os.chdir(WT)
sys.path.insert(0, WT)

from services.database import DatabaseService  # noqa: E402


def _year(ts):
    try:
        return datetime.datetime.fromtimestamp(
            int(ts), datetime.timezone.utc).year
    except Exception:
        return None


def _summary(card):
    facts = list(card.get("facts") or ())
    meta = list(card.get("facts_meta") or ())
    years = collections.Counter(
        _year(item.get("message_timestamp") or item.get("created_at"))
        for item in meta if isinstance(item, dict))
    return {
        "facts": len(facts),
        "facts_meta": len(meta),
        "meta_order_matches": [item.get("fact") for item in meta] == facts,
        "years": {str(k): v for k, v in sorted(years.items()) if k},
        "known_years": sum(1 for k in years if k),
        "source_refs": sum(1 for item in meta
                           if item.get("source_ref_id") is not None),
        "tg_sources": sum(1 for item in meta
                          if item.get("tg_message_id") is not None),
        "links": len(card.get("links") or ()),
        "link_names": sorted({
            str(link.get("source_name") or "")
            for link in card.get("links") or ()} |
            {str(link.get("target_name") or "")
             for link in card.get("links") or ()}),
    }


async def main():
    ds = DatabaseService(SNAP)
    uri = "file:" + SNAP.replace("\\", "/") + "?mode=ro&immutable=1"
    ds.db = await aiosqlite.connect(uri, uri=True)
    ds.db.row_factory = aiosqlite.Row
    await ds.db.execute("PRAGMA query_only=ON")
    try:
        exact = _summary(await ds.get_persona_card(
            CHAT, "Леха", 20, NOW, user_id=UID_LEKHA))
        alias = _summary(await ds.get_persona_card(
            CHAT, "Леха", 20, NOW, user_id=UID_LEKHA,
            alias_names=("леха вдовин",)))
    finally:
        await ds.db.close()
    result = {
        "artifact_kind": "vmq_mem_rc6a_snapshot_probe",
        "snapshot": SNAP,
        "snapshot_sha256_expected": "b907d4c1e24321fffa48e3719974fd2293b1b1ff721ad21661446d22033e06e7",
        "mode": "mode=ro&immutable=1; PRAGMA query_only=ON",
        "chat_id": CHAT,
        "exact_name": exact,
        "alias_names": alias,
        "pass": {
            "facts_meta_order": (exact["facts"] == exact["facts_meta"]
                                 and alias["facts"] == alias["facts_meta"]),
            "years_present": exact["known_years"] > 0,
            "sources_present": (exact["source_refs"] + exact["tg_sources"]) > 0,
            "alias_links_ge_1": alias["links"] >= 1,
            "exact_name_snapshot_has_node": exact["links"] >= 1,
        },
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=True, indent=1)
    print(json.dumps(result, ensure_ascii=True, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
