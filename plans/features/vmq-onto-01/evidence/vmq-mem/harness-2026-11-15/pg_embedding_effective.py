# -*- coding: utf-8 -*-
"""Read-only PG effective embedding-route check (parity for the vector leg).

SELECT only. Prints key names for credentials (never values) and the non-secret
routing values (base_url host/model/quota group) plus the resulting connection
identity (PCI) computed with (a) env defaults and (b) PG bot_settings values.
No write, no restart, no provider call.
"""
from __future__ import annotations

import asyncio
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
from services import hot_config as hot        # noqa: E402


class _Cache:
    def __init__(self, data):
        self._data = dict(data or {})
        self.pg = None

    def get(self, key, default=None):
        return self._data.get(key, default)

    def get_all(self):
        return dict(self._data)


async def _select(keys_like) -> dict:
    dsn = os.getenv("POSTGRES_DSN") or getattr(settings, "POSTGRES_DSN", "")
    if not dsn:
        return {}
    import asyncpg
    con = await asyncpg.connect(dsn=dsn, timeout=12)
    try:
        rows = await con.fetch(
            "SELECT key, value FROM bot_settings WHERE key LIKE $1 "
            "OR key LIKE $2", keys_like[0], keys_like[1])
    finally:
        await con.close()
    return {row["key"]: row["value"] for row in rows}


def _admission() -> dict | None:
    try:
        con = sqlite3.connect("file:%s?mode=ro" % LIVE, uri=True, timeout=8)
    except Exception:                                # noqa: BLE001
        return None
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=1")
        row = con.execute(
            "SELECT config_revision, status, model, dims FROM "
            "mca_embedding_index_generations WHERE index_name=? AND "
            "namespace=? AND status='active' ORDER BY generation DESC LIMIT 1",
            ("graph_facts_vec", "default")).fetchone()
        return {key: row[key] for key in row.keys()} if row else None
    except Exception:                                # noqa: BLE001
        return None
    finally:
        con.close()


def main() -> int:
    out: dict = {"readonly": True}
    try:
        got = asyncio.run(_select(("models.embedding%", "keys.embedding%")))
    except Exception as exc:                         # noqa: BLE001
        got = {}
        out["pg_error"] = "%s:%s" % (type(exc).__name__, str(exc)[:120])
    out["pg_keys"] = sorted(got)
    safe = {}
    for key, value in got.items():
        if key.startswith("keys."):
            safe[key] = "<present len=%d>" % len(str(value or ""))
        else:
            safe[key] = str(value or "")
    out["pg_values"] = safe

    hot.set_config_cache(_Cache({}))                 # env-only profile
    out["conn_env"] = ecp._current_conn()
    hot.set_config_cache(_Cache(got))                # PG-effective profile
    out["conn_pg"] = ecp._current_conn()
    try:
        profiles = ecp.resolve_embedding_profiles()["primary"]
        from urllib.parse import urlsplit
        out["pg_primary"] = {
            "host": urlsplit(profiles.base_url or "").hostname,
            "path": (urlsplit(profiles.base_url or "").path or ""),
            "model": profiles.model,
            "quota_group": profiles.quota_group,
        }
    except Exception as exc:                         # noqa: BLE001
        out["pg_primary_error"] = type(exc).__name__

    active = _admission() or {}
    admission = ecp.parse_admission(active.get("config_revision"))
    out["active_row"] = {"status": active.get("status"),
                         "model": active.get("model"),
                         "dims": active.get("dims")}
    out["admission"] = admission
    try:
        dims = int(active.get("dims") or 0) or None
        space_now = (ecp.model_space_identity(model=ecp._current_model(),
                                              dimension=dims) if dims else "")
        out["space_now_pg"] = space_now
        out["admission_valid_conn_env"] = bool(
            admission and ecp.admission_valid(
                admission, space_now=space_now, conn_now=out["conn_env"]))
        out["admission_valid_conn_pg"] = bool(
            admission and ecp.admission_valid(
                admission, space_now=space_now, conn_now=out["conn_pg"]))
    except Exception as exc:                         # noqa: BLE001
        out["valid_error"] = type(exc).__name__
    print("PG_EMBEDDING_JSON " + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
