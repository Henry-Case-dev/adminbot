# -*- coding: utf-8 -*-
"""TIME-06 inventory: vector leg tables/counters and the admission verdict."""
from __future__ import annotations

import asyncio
import json
import os
import sys

CLONE = os.environ.get("VMQ_CLONE") or os.getcwd()
DBPATH = os.environ.get("VMQ_DB") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dbcopy.db")
OUT = os.environ.get("PROBE_OUT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "vector-inventory.json")
sys.path.insert(0, CLONE)
os.chdir(CLONE)

from services import hot_config as hot                      # noqa: E402
from services.database import DatabaseService               # noqa: E402
from services import embedding_control_plane as ecp         # noqa: E402


class _Cache:
    def get(self, key, default=None):
        return default

    def get_all(self):
        return {}


async def main():
    hot.set_config_cache(_Cache())
    db = DatabaseService(DBPATH)
    await db.initialize()
    out = {"db": DBPATH, "rows": {}}
    async with db.db.execute(
            "SELECT generation, status, dims, model, config_revision, "
            "namespace, index_name FROM mca_embedding_index_generations "
            "ORDER BY generation DESC") as cur:
        out["generations"] = [dict(row) for row in await cur.fetchall()]
    async with db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts_vec_rowids") as cur:
        out["rows"]["graph_facts_vec_rowids"] = (await cur.fetchone())["n"]
    async with db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts f WHERE EXISTS ("
            "SELECT 1 FROM graph_facts_vec_rowids r WHERE r.rowid=f.id)"
    ) as cur:
        out["rows"]["facts_with_vector"] = (await cur.fetchone())["n"]
    async with db.db.execute("SELECT COUNT(*) AS n FROM graph_facts") as cur:
        out["rows"]["facts_total"] = (await cur.fetchone())["n"]
    async with db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts "
            "WHERE status='confirmed'") as cur:
        out["rows"]["facts_confirmed"] = (await cur.fetchone())["n"]
    async with db.db.execute(
            "SELECT COUNT(*) AS n FROM embedding_cache") as cur:
        out["rows"]["embedding_cache"] = (await cur.fetchone())["n"]
    active = next((row for row in out["generations"]
                   if str(row.get("status")) == "active"
                   and row.get("index_name") == "graph_facts_vec"), None)
    out["active_generation"] = active
    try:
        out["admission"] = ecp.parse_admission(
            (active or {}).get("config_revision"))
    except Exception as exc:                            # noqa: BLE001
        out["admission"] = {"error": type(exc).__name__}
    try:
        out["model_now"] = {
            "space": ecp.model_space_identity(
                model=ecp._current_model(),
                dimension=(active or {}).get("dims")),
            "conn": ecp._current_conn(),
        }
    except Exception as exc:                            # noqa: BLE001
        out["model_now"] = {"error": type(exc).__name__}
    try:
        out["compat"] = await ecp.resolve_index_compat(
            db, "graph_facts_vec",
            current_fp=None,
            current_dims=(active or {}).get("dims"))
    except Exception as exc:                            # noqa: BLE001
        out["compat"] = {"error": type(exc).__name__,
                         "text": str(exc)[:200]}
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:3000], flush=True)
    await db.close()
    os._exit(0)


try:
    asyncio.run(main())
except BaseException:                                     # noqa: BLE001
    import traceback
    traceback.print_exc()
    os._exit(2)
