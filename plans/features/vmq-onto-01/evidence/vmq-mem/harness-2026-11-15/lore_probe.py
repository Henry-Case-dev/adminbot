# -*- coding: utf-8 -*-
"""Lore-story material probe (read-only): does the creative path get a wider
period than the reply path?

Measures ONLY the two existing material builders of `LoreCompilerService`
(Шаг А `db.lore_graph_slice`, Шаг Б `db.lore_dense_dialogs`) — no LLM
generation, so the answer text cannot be mistaken for retrieval proof
(VMQ-MEM-05). Also counts the corpus support of the same topic per year with
the existing FTS counter.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
import traceback

VARIANT = os.environ.get("VMQ_VARIANT", "base")
CLONE = os.environ.get("VMQ_CLONE", "/root/vmq2/measure4/repo-base")
DBPATH = os.environ.get("VMQ_DB", "/root/vmq2/measure4/dbcopy.db")
OUT = os.environ.get("VMQ_OUT", "/root/vmq2/measure4/out/lore-base.json")
CFG = os.environ.get("VMQ_CFG", "/root/vmq2/measure4/cfg.json")
APP = "/var/www/admin_bot"
CHAT = -1002661910336
OWNER = "напиши юмористический рассказ об основных шизах конфы"

sys.path.insert(0, CLONE)
os.chdir(APP)
logging.basicConfig(level=logging.ERROR)

import services  # noqa: E402
from config.settings import settings  # noqa: E402
from services import hot_config as hot  # noqa: E402
from services.database import DatabaseService  # noqa: E402
from services.lore_compiler_service import topic_tokens  # noqa: E402
from services.summary_memory import build_fts_query  # noqa: E402

Y2023 = (1672531200, 1704067199)
Y2026 = (1767225600, 1798761599)


def year_of(ts):
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    return time.gmtime(ts).tm_year if ts > 0 else None


def hist(values):
    out = {}
    for value in values:
        key = str(value) if value else "no_date"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


async def main() -> int:
    cfg = json.load(open(CFG, encoding="utf-8"))

    class _Cache:
        def __init__(self, data):
            self._data = dict(data or {})
            self.pg = None

        def get(self, key, default=None):
            return self._data.get(key, default)

    hot.set_config_cache(_Cache(cfg.get("effective") or {}))
    db = DatabaseService(DBPATH)
    await db.initialize()
    tokens = topic_tokens(OWNER)
    match = build_fts_query(tokens) if tokens else ""
    out = {
        "variant": VARIANT,
        "identity": {
            "variant": VARIANT,
            "git_head": os.environ.get("VMQ_HEAD"),
            "services_file": services.__file__,
            "db_sha256": os.environ.get("VMQ_DB_SHA"),
        },
        "topic_token_count": len(tokens),
        "match_nonempty": bool(match),
        "errors": [],
    }
    started = time.monotonic()
    try:
        graph = await db.lore_graph_slice(CHAT, OWNER)
        facts = graph.get("facts") or []
        years = []
        for row in facts:
            if isinstance(row, dict):
                years.append(year_of(row.get("rag_ts")
                                     or row.get("message_timestamp")
                                     or row.get("created_at")))
        out["graph"] = {
            "nodes": len(graph.get("nodes") or ()),
            "edges": len(graph.get("edges") or ()),
            "facts": len(facts),
            "fact_years": hist(years),
            "symbols": sum(len(str(row.get("fact") or "")) for row in facts
                           if isinstance(row, dict)),
        }
    except Exception as exc:           # noqa: BLE001
        out["errors"].append({"stage": "lore_graph_slice",
                              "error": type(exc).__name__,
                              "tb": traceback.format_exc()[-600:]})
    try:
        dialogs = await db.lore_dense_dialogs(CHAT, match)
        rows = [row for dialog in dialogs.get("dialogs") or ()
                for row in dialog]
        out["dialogs"] = {
            "total": dialogs.get("total"),
            "earliest_year": year_of(dialogs.get("earliest")),
            "latest_year": year_of(dialogs.get("latest")),
            "dialogs": len(dialogs.get("dialogs") or ()),
            "rows": len(rows),
            "row_years": hist([year_of(row.get("timestamp")
                                       if isinstance(row, dict) else None)
                               for row in rows]),
            "symbols": sum(len(str(row.get("text") or ""))
                           for row in rows if isinstance(row, dict)),
        }
    except Exception as exc:           # noqa: BLE001
        out["errors"].append({"stage": "lore_dense_dialogs",
                              "error": type(exc).__name__,
                              "tb": traceback.format_exc()[-600:]})
    out["seconds"] = round(time.monotonic() - started, 2)
    try:
        counts = {}
        for label, (since, until) in (("2022", (1640995200, 1672531199)),
                                      ("2023", Y2023),
                                      ("2024", (1704067200, 1735689599)),
                                      ("2025", (1735689600, 1767225599)),
                                      ("2026", Y2026)):
            got = await db.search_messages_fts_count_by_author(
                CHAT, match, since_ts=since, until_ts=until)
            counts[label] = int(got.get("count") or 0)
        out["corpus_topic_by_year"] = counts
    except Exception as exc:           # noqa: BLE001
        out["errors"].append({"stage": "corpus_counts",
                              "error": type(exc).__name__})
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("LORE_WROTE %s bytes=%s" % (OUT, os.path.getsize(OUT)))
    await db.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:                  # noqa: BLE001
        traceback.print_exc()
        sys.exit(3)
