# -*- coding: utf-8 -*-
"""Relations probe for MEM-03 (metric 4: fabricated relations), read-only.

Measures the ONLY sanctioned relations path reachable from the reply/person
tool: `get_user_context` with purpose=relationships (which routes to the
existing single `retrieve`), plus the retrieval-contract `relations` field.
Records per edge: has an edge id, has a fact id, origin, weight, timestamp
year, direction, has_unsupported_sources. No text is stored.
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
CLONE = os.environ.get("VMQ_CLONE", "/root/vmq2/measure/repo-base")
DBPATH = os.environ.get("VMQ_DB", "/root/vmq2/measure/dbcopy.db")
OUT = os.environ.get("VMQ_OUT", "/root/vmq2/measure/out/rel-base.json")
ENT = os.environ.get("VMQ_ENT", "/root/vmq2/measure/entities.json")
CFG = os.environ.get("VMQ_CFG", "/root/vmq2/measure/cfg.json")
APP = "/var/www/admin_bot"
CHAT = -1002661910336

sys.path.insert(0, CLONE)
os.chdir(APP)
logging.basicConfig(level=logging.ERROR)

import services  # noqa: E402
from config.settings import settings  # noqa: E402
from services import hot_config as hot  # noqa: E402
from services import mca_retrieval_context as mca  # noqa: E402
from services.database import DatabaseService  # noqa: E402
from services.llm_client import LLMClient  # noqa: E402
from services.summary_memory import MemoryManager  # noqa: E402
from services.tool_router import ToolContext, ToolDeps, ToolRouter  # noqa: E402

WATCH = ("services/mca_retrieval_context.py", "services/tool_router.py",
         "services/semantic_contracts.py")


def year_of(ts):
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    return time.gmtime(ts).tm_year if ts > 0 else None


def edge_view(item: dict) -> dict:
    return {
        "has_edge_id": bool(item.get("edge_id")),
        "has_fact_id": bool(item.get("fact_id")),
        "origin": item.get("origin"),
        "direction": item.get("direction"),
        "weight": item.get("weight"),
        "ts_year": year_of(item.get("ts") or item.get("created_at")),
        "unsupported_sources": bool(item.get("has_unsupported_sources")),
        "has_conflict": bool(item.get("conflict")
                             or item.get("conflicting")),
    }


async def main() -> int:
    entities = json.load(open(ENT, encoding="utf-8"))
    cfg = json.load(open(CFG, encoding="utf-8"))
    person = entities["person"]

    class _Cache:
        def __init__(self, data):
            self._data = dict(data or {})
            self.pg = None

        def get(self, key, default=None):
            return self._data.get(key, default)

        def get_all(self):
            return dict(self._data)

    hot.set_config_cache(_Cache(cfg.get("effective") or {}))
    identity = {"variant": VARIANT, "clone": CLONE,
                "services_file": services.__file__,
                "git_head": os.environ.get("VMQ_HEAD"),
                "files": {}}
    for rel in WATCH:
        try:
            with open(os.path.join(CLONE, rel), "rb") as fh:
                identity["files"][rel] = hashlib.sha256(
                    fh.read()).hexdigest()[:16]
        except OSError:
            identity["files"][rel] = "absent"
    assert os.path.realpath(services.__file__).startswith(
        os.path.realpath(CLONE)), "IMPORT NOT FROM THE MEASURED CLONE"

    db = DatabaseService(DBPATH)
    await db.initialize()
    llm = LLMClient(
        hot.get("models.llm_base_url", settings.LLM_BASE_URL),
        hot.get("keys.llm_api_key", settings.LLM_API_KEY),
        hot.get("models.llm_model_name", settings.LLM_MODEL_NAME),
        hot.get("models.embedding_model_name", settings.EMBEDDING_MODEL_NAME),
        embed_base_url=hot.get("models.embedding_base_url",
                               settings.EMBEDDING_BASE_URL),
        embed_api_key=hot.get("keys.embedding_api_key",
                              settings.EMBEDDING_API_KEY))
    memory = MemoryManager(db, llm, aliases=None)
    try:
        await memory.initialize()
    except Exception:                  # noqa: BLE001
        pass
    try:
        from services.summary_aliases import build_alias_resolver
        aliases = await build_alias_resolver(CHAT)
    except Exception:                  # noqa: BLE001
        class _Stub:
            def resolve(self, user_id, nickname=None, username=None,
                        memory_name=None):
                return str(nickname or username or memory_name or user_id
                           or "")
        aliases = _Stub()
    router = ToolRouter(ToolDeps(search=None, memory=memory, aliases=aliases,
                                 db=db, llm=llm))
    out = {"variant": VARIANT, "identity": identity, "tool": {}, "retrieve": {},
           "errors": []}
    query = "как менялись наши отношения и взгляды за эти годы"

    try:
        raw = await asyncio.wait_for(
            router._get_user_context({"person": person["name"],
                                      "purpose": "relationships"},
                                     ToolContext(CHAT, query, user_id=None)),
            timeout=180)
        payload = json.loads(raw or "{}")
        rels = payload.get("relations") or payload.get("links") or []
        out["tool"] = {
            "status": payload.get("status"),
            "envelope_keys": sorted(payload.keys()),
            "chars": len(raw or ""),
            "relations": len(rels),
            "edges": [edge_view(item) for item in rels[:40]
                      if isinstance(item, dict)],
            "sources": len(payload.get("sources") or ()),
            "facts": len(payload.get("facts") or ()),
            "empty_reason": payload.get("empty_reason"),
        }
    except Exception as exc:           # noqa: BLE001
        out["errors"].append({"stage": "tool_relationships",
                              "error": type(exc).__name__,
                              "tb": traceback.format_exc()[-700:]})

    for name, kwargs in (
            ("subject_relations", dict(
                chat_id=CHAT, query=query, mode="auto", purpose="reply",
                top_k=10, reply_depth=0, channels=("subject",),
                subject_names=(person["name"],), include_relations=True)),
            ("relations_direct", dict(
                chat_id=CHAT, query=query, mode="auto", purpose="reply",
                top_k=10, reply_depth=0, channels=(),
                include_relations=True))):
        try:
            started = time.monotonic()
            result = await mca.retrieve(db, memory,
                                        mca.RetrievalRequest(**kwargs))
            rels = list(getattr(result, "relations", ()) or ())
            out["retrieve"][name] = {
                "seconds": round(time.monotonic() - started, 2),
                "status": result.status,
                "reason_code": result.reason_code,
                "channels_used": list(result.channels_used or ()),
                "candidates": len(result.candidates or ()),
                "has_relations_field": hasattr(result, "relations"),
                "relations": len(rels),
                "edges": [edge_view(item) for item in rels[:40]
                          if isinstance(item, dict)],
                "years": sorted({str(year_of(item.get("ts"))) for item in rels
                                 if isinstance(item, dict)
                                 and year_of(item.get("ts"))}),
            }
        except Exception as exc:       # noqa: BLE001
            out["errors"].append({"stage": name,
                                  "error": type(exc).__name__,
                                  "tb": traceback.format_exc()[-700:]})
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("REL_WROTE %s bytes=%s" % (OUT, os.path.getsize(OUT)))
    await db.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:                  # noqa: BLE001
        traceback.print_exc()
        sys.exit(3)
