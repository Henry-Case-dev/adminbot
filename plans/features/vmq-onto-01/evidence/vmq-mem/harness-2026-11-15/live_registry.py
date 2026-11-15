# -*- coding: utf-8 -*-
"""Read-only snapshot of the LIVE embedding generation registry.

SELECT only, read-only connection (`mode=ro`, `PRAGMA query_only`). No write,
no restart, no network call, no index probe. Prints one JSON line.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

APP = "/var/www/admin_bot"
LIVE = APP + "/local_database.db"

sys.path.insert(0, APP)
os.chdir(APP)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(APP, ".env"), override=False)
except Exception:                                    # noqa: BLE001
    pass

from config.settings import settings           # noqa: E402
from services import embedding_control_plane as ecp  # noqa: E402

out: dict = {"readonly": True, "path": "live local_database.db"}
try:
    con = sqlite3.connect("file:%s?mode=ro" % LIVE, uri=True, timeout=8)
except Exception as exc:                             # noqa: BLE001
    out["error"] = "connect:%s" % type(exc).__name__
    print("LIVE_REGISTRY_JSON " + json.dumps(out, ensure_ascii=False))
    raise SystemExit(0)
try:
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=1")
    cursor = con.execute(
        "SELECT generation, status, dims, model, preprocessing_version, "
        "fingerprint, config_revision, namespace, index_name "
        "FROM mca_embedding_index_generations "
        "WHERE index_name=? AND namespace=? "
        "ORDER BY generation DESC LIMIT 8",
        ("graph_facts_vec", "default"))
    rows = [{key: row[key] for key in row.keys()} for row in cursor]
except Exception as exc:                             # noqa: BLE001
    rows = []
    out["error"] = "select:%s" % type(exc).__name__
finally:
    con.close()

dims = next((int(row["dims"]) for row in rows if row.get("dims")), None)
try:
    space_now = (ecp.model_space_identity(model=ecp._current_model(),
                                          dimension=dims) if dims else "")
    conn_now = ecp._current_conn()
except Exception:                                    # noqa: BLE001
    space_now, conn_now = "", ""
active = next((row for row in rows
               if str(row.get("status") or "") == "active"), None)
admission = ecp.parse_admission(
    (active or {}).get("config_revision")) if active else None
out.update({
    "rows": [{
        "generation": row.get("generation"),
        "status": row.get("status"),
        "dims": row.get("dims"),
        "model": row.get("model"),
        "preprocessing_version": str(
            row.get("preprocessing_version") or "")[:24] or None,
        "fingerprint12": str(row.get("fingerprint") or "")[:12] or None,
        "admission": ecp.parse_admission(row.get("config_revision")),
        "canary": ecp._admission_canary(
            ecp.parse_admission(row.get("config_revision"))),
        "space": ecp.generation_space_identity(row),
    } for row in rows],
    "active_present": active is not None,
    "space_now": space_now,
    "conn_now": conn_now,
    "active_admission_valid_for_current_msi_pci": bool(
        admission and ecp.admission_valid(
            admission, space_now=space_now, conn_now=conn_now)),
    "env_embedding_model": getattr(settings, "EMBEDDING_MODEL_NAME", None),
    "env_embedding_dim": getattr(settings, "EMBEDDING_DIM", None),
})
print("LIVE_REGISTRY_JSON " + json.dumps(out, ensure_ascii=False))
