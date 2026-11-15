# -*- coding: utf-8 -*-
"""VMQ Slice D — before/after measurement on a copy of the prod archive.

Runs the REAL product seam (`DirectChatService._rag_unified_rows`,
`_build_old_episodes`, `DatabaseService` readers). Prints/writes only ids,
years, reason codes and counters — never fact or message text.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace

CLONE = os.environ.get("VMQ_CLONE") or r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\vmq-slice-d-963e66a7a511-6602ef7e"
DBPATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dbcopy.db")
OUT = os.environ.get("PROBE_OUT") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "measure.json")
CHAT = -1002661910336

sys.path.insert(0, CLONE)
os.chdir(CLONE)

from services import hot_config as hot                    # noqa: E402
from services import mca_retrieval_context as mrc         # noqa: E402
from services.database import DatabaseService             # noqa: E402
from services.direct_chat_service import DirectChatService  # noqa: E402
from services.summary_memory import MemoryManager         # noqa: E402


class _Cache:
    def get(self, key, default=None):
        return default

    def get_all(self):
        return {}


class StubLLM:
    async def embed(self, texts):
        raise RuntimeError("EMBED_API_FAILED provider_unavailable")

    async def generate(self, messages):
        raise RuntimeError("LLM unavailable")


class StubAliases:
    def resolve(self, user_id, nickname=None, username=None, memory_name=None):
        return str(nickname or username or memory_name or user_id or "")


def year_of(ts):
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return time.gmtime(ts).tm_year


def hist(values):
    out = {}
    for value in values:
        key = str(value) if value is not None else "no_date"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def brief(row, query_stems=None):
    text = (row or {}).get("fact") or ""
    shared = None
    if query_stems is not None:
        shared = mrc.period_subject_shared(query_stems, text)
    return {
        "id": as_int((row or {}).get("id")),
        "year": year_of((row or {}).get("rag_ts")
                        or (row or {}).get("message_timestamp")
                        or (row or {}).get("created_at")),
        "origin": (row or {}).get("origin"),
        "proxy": (row or {}).get("subject_proxy"),
        "stems_shared": (row or {}).get("stems_shared"),
        "stems_recomputed": shared,
        "stems_reason": (row or {}).get("stems_shared_reason"),
        "period_fill": bool((row or {}).get("period_fill")),
        "unattributed": bool((row or {}).get("unattributed")),
        "subject_role": (row or {}).get("subject_role"),
    }


class PoolSpy:
    def __init__(self):
        self.pool = []
        self.stats = {}
        self.accepted = []
        self._orig = None

    def __enter__(self):
        self._orig = mrc.select_period_rows
        spy = self

        def wrapper(rows, **kwargs):
            pool = list(rows or ())
            query = str(kwargs.get("query") or "")
            stems = mrc.period_subject_stems(query)
            accepted, stats = spy._orig(rows, **kwargs)
            spy.pool = [brief(row, stems) for row in pool]
            spy.stats = dict(stats or {})
            spy.accepted = [brief(row, stems) for row in accepted]
            return accepted, stats

        mrc.select_period_rows = wrapper
        return self

    def __exit__(self, *exc):
        mrc.select_period_rows = self._orig
        return False


QUERIES = (
    ("A1_auto", "напиши юмористический рассказ об основных шизах конфы",
     {"memory_scope": "auto"}),
    ("A1_historical", "напиши юмористический рассказ об основных шизах конфы",
     {"memory_scope": "historical"}),
    ("A1P_auto", "что за шизы были на конфе?",
     {"memory_scope": "auto"}),
    ("A1P_historical", "что за шизы были на конфе?",
     {"memory_scope": "historical"}),
    ("D_2023", "из-за чего мы ссорились и ругались в 2023 году",
     {"memory_scope": "auto"}),
    ("T2_auto", "что вообще было с E1, напомни?",
     {"memory_scope": "auto"}),
    ("T2_plan_hist", "что вообще было с E1, напомни?",
     {"memory_scope": "auto", "plan_act": "historical_recall"}),
    ("T3_current", "что сейчас происходит с E1?",
     {"memory_scope": "auto"}),
)


async def main():
    hot.set_config_cache(_Cache())
    db = DatabaseService(DBPATH)
    await db.initialize()
    memory = MemoryManager(db, StubLLM(), aliases=None)

    async def _noop():
        return 0

    memory.backfill_archive_vectors = _noop
    memory.backfill_graph_fact_vectors = _noop
    try:
        vec_ok = bool(await asyncio.wait_for(memory.initialize(), 120))
    except Exception:                                     # noqa: BLE001
        vec_ok = False
    svc = DirectChatService(memory, db, StubLLM(), StubAliases())
    stub = SimpleNamespace(text="", chat_id=CHAT, message_id=0)
    tail = await db.get_recent_messages(CHAT, 40)

    out = {
        "identity": {
            "clone": CLONE,
            "db": DBPATH,
            "db_bytes": os.path.getsize(DBPATH),
            "chat": CHAT,
            "vec_ok": vec_ok,
            "generated_at": int(time.time()),
        },
        "classes": {},
        "old_episode": {},
        "people": {},
        "vector_inventory": {},
    }

    for key, query, extra in QUERIES:
        stub.text = query
        entry = {"query_class": key}
        call_kwargs = dict(extra)
        scope = str(call_kwargs.pop("memory_scope", "auto"))
        with PoolSpy() as spy:
            try:
                rows = await asyncio.wait_for(svc._rag_unified_rows(
                    CHAT, query, stub, memory_scope=scope,
                    **call_kwargs), 300)
            except Exception as exc:                      # noqa: BLE001
                rows = None
                entry["error"] = "%s: %s" % (type(exc).__name__,
                                             str(exc)[:200])
        rows = list(rows or ())
        entry.update({
            "rows": len(rows),
            "row_years": hist([year_of((r or {}).get("rag_ts")
                                       or (r or {}).get("message_timestamp"))
                               for r in rows if isinstance(r, dict)]),
            "rows_brief": [brief(r) for r in rows if isinstance(r, dict)],
            "period_stats": dict(getattr(svc, "_rag_period_stats", None) or {}),
            "pool_rows": len(spy.pool),
            "pool_years": hist([r.get("year") for r in spy.pool]),
            "pool_shared": hist([r.get("stems_recomputed")
                                 for r in spy.pool]),
            "pool_multi_stem": sum(1 for r in spy.pool
                                   if (r.get("stems_recomputed") or 0) >= 2),
            "pool_ge1_stem": sum(1 for r in spy.pool
                                 if (r.get("stems_recomputed") or 0) >= 1),
            "pool_old_years": sorted({r.get("year") for r in spy.pool
                                      if r.get("year") is not None}),
            "pool_brief": spy.pool[:40],
            "accepted_brief": spy.accepted,
            "selection_stats": spy.stats,
        })
        out["classes"][key] = entry

    # D5: продуктовая трасса того же хода (`out_memory` из `_build_rag_block`).
    for key, query, subject in (
            ("A1P_auto", "что за шизы были на конфе?", None),
            ("A1P_historical", "что за шизы были на конфе?", None),
            ("T3_alina", "что сейчас с Алиной?",
             ("Alina", 485008070)),
            ("T3_mulyanka", "как сейчас дела с мулянкой?", None)):
        stub.text = query
        trace: dict = {}
        scope = "historical" if key.endswith("_historical") else "auto"
        kwargs = {"memory_scope": scope, "out_memory": trace}
        if subject:
            kwargs["subject_name"] = subject[0]
            kwargs["subject_uid"] = subject[1]
        try:
            block, _hint = await asyncio.wait_for(svc._build_rag_block(
                CHAT, stub, "", **kwargs), 300)
            out["classes"].setdefault(key, {})
            out["classes"][key]["product_trace"] = {
                "period": trace.get("period"),
                "years": trace.get("years"),
                "source_ids": len(trace.get("source_ids") or ()),
                "block_chars": len(block or ""),
            }
        except Exception as exc:                          # noqa: BLE001
            out["classes"].setdefault(key, {})
            out["classes"][key]["product_trace"] = {
                "error": type(exc).__name__, "text": str(exc)[:200]}


    for key, query in (("Old_Episode_2023",
                        "из-за чего мы ссорились и ругались в 2023 году"),
                       ("Old_Episode_plain", "что за шизы были на конфе?")):
        with PoolSpy() as spy:
            try:
                block, stats = await asyncio.wait_for(
                    svc._build_old_episodes(CHAT, query, tail, {}, None,
                                            None), 300)
                ok = True
            except Exception as exc:                      # noqa: BLE001
                block, stats, ok = "", {}, False
                out["old_episode"][key] = {"error": type(exc).__name__}
        if not ok:
            continue
        out["old_episode"][key] = {
            "block_chars": len(block or ""),
            "empty": not bool(block),
            "period_intent": (stats or {}).get("period_intent"),
            "year_window": (stats or {}).get("year_window"),
            "stats": {k: v for k, v in (stats or {}).items() if k != "spans"},
            "spans": [{"first_year": year_of(s.get("first_ts")),
                       "last_year": year_of(s.get("last_ts")),
                       "sources": len(s.get("source_ids") or ())}
                      for s in ((stats or {}).get("spans") or ())
                      if isinstance(s, dict)],
            "selection_stats": spy.stats,
            "pool_years": hist([r.get("year") for r in spy.pool]),
        }

    now = int(time.time())
    from services.tool_router import ToolContext, ToolDeps, ToolRouter

    class _Aliases:
        def __init__(self, mapping):
            self._aliases = {str(k): str(v) for k, v in mapping.items()}

        def resolve(self, user_id, nickname=None, username=None,
                    memory_name=None):
            return self._aliases.get(str(user_id),
                                     nickname or str(user_id))

        def canon_name(self, name):
            return str(name or "").strip()

    router = ToolRouter(ToolDeps(search=None, memory=memory,
                                 aliases=_Aliases({}), db=db))
    for uid, alias in ((485008070, "P1"), (138811255, "P2_top_author"),
                       (1313107079, "P3_history_2023_2024")):
        row = await db.db.execute(
            "SELECT author_name FROM smart_messages WHERE user_id=? AND "
            "chat_id=? AND COALESCE(author_name,'')<>'' "
            "GROUP BY author_name ORDER BY COUNT(*) DESC LIMIT 1",
            (uid, CHAT))
        name_row = await row.fetchone()
        name = str(name_row["author_name"] if name_row else "")
        person = {"uid": uid, "name_present": bool(name)}
        try:
            profile = await db.get_subject_profile_facts(CHAT, name, 10, now,
                                                         user_id=uid)
        except Exception as exc:                          # noqa: BLE001
            profile = []
            person["profile_error"] = type(exc).__name__
        person["subject_profile_facts"] = [{
            "id": r.get("id"), "yr": r.get("yr"),
            "status": r.get("status"), "origin": r.get("origin"),
            "subject_role": r.get("subject_role"),
            "subject_ref_id": r.get("subject_ref_id"),
            "speaker_author_id": r.get("speaker_author_id"),
        } for r in (profile or ())]
        try:
            multi = await db.get_user_context_facts(
                CHAT, name, 10, now, user_id=uid, scope="historical")
        except Exception as exc:                          # noqa: BLE001
            multi = []
            person["multi_error"] = type(exc).__name__
        person["profile_multiperiod"] = [{
            "id": r.get("id"), "yr": r.get("yr"),
            "status": r.get("status"), "valid_now": r.get("valid_now"),
        } for r in (multi or ())]
        try:
            messages = await db.get_author_message_periods(CHAT, uid, 10)
        except Exception as exc:                          # noqa: BLE001
            messages = []
            person["messages_error"] = type(exc).__name__
        person["author_message_periods"] = {
            "count": len(messages or ()),
            "years": hist([r.get("as_of_year") for r in (messages or ())]),
            "roles": hist([r.get("subject_role") for r in (messages or ())]),
        }
        stub.text = "что ты знаешь про %s?" % name
        with PoolSpy() as spy:
            try:
                rows = await asyncio.wait_for(svc._rag_unified_rows(
                    CHAT, stub.text, stub, memory_scope="auto",
                    subject_name=name, subject_uid=uid), 300)
            except Exception as exc:                      # noqa: BLE001
                rows = None
                person["reply_error"] = type(exc).__name__
        rows = list(rows or ())
        person["reply_rows"] = len(rows)
        person["reply_years"] = hist(
            [year_of((r or {}).get("rag_ts")
                     or (r or {}).get("message_timestamp"))
             for r in rows if isinstance(r, dict)])
        person["reply_period"] = [brief(r) for r in rows
                                  if isinstance(r, dict)
                                  and r.get("period_fill")]
        person["reply_stats"] = dict(
            getattr(svc, "_rag_period_stats", None) or {})
        # D1: тот же вопрос под historical — контроль не вакуумный.
        with PoolSpy() as spy:
            try:
                hist_rows = await asyncio.wait_for(svc._rag_unified_rows(
                    CHAT, stub.text, stub, memory_scope="historical",
                    subject_name=name, subject_uid=uid), 300)
            except Exception as exc:                      # noqa: BLE001
                hist_rows = None
                person["reply_historical_error"] = type(exc).__name__
        hist_rows = list(hist_rows or ())
        person["reply_historical_years"] = hist(
            [year_of((r or {}).get("rag_ts")
                     or (r or {}).get("message_timestamp"))
             for r in hist_rows if isinstance(r, dict)])
        person["reply_historical_period"] = [
            brief(r) for r in hist_rows
            if isinstance(r, dict) and r.get("period_fill")]
        person["reply_historical_stats"] = dict(
            getattr(svc, "_rag_period_stats", None) or {})
        # D3/D4: продуктовый tool-envelope `biography` (top-author single-year
        # regression) — тот же `_get_user_context`, без второго поиска.
        router.deps.aliases._aliases[str(uid)] = name
        try:
            raw = await asyncio.wait_for(router._get_user_context(
                {"person": name, "purpose": "biography",
                 "user_id": uid},
                ToolContext(CHAT, "что ты знаешь про %s?" % name)), 300)
            payload = json.loads(raw or "{}")
            facts = payload.get("facts") or []
            person["tool_biography"] = {
                "status": payload.get("status"),
                "no_data": payload.get("no_data"),
                "empty_reason": payload.get("empty_reason"),
                "facts": len(facts),
                "years": hist([fact.get("as_of_year") for fact in facts]),
                "roles": hist([fact.get("subject_role") for fact in facts
                               if fact.get("subject_role")]),
                "unattributed": sum(1 for fact in facts
                                    if fact.get("unattributed")),
                "subject_material": payload.get("subject_material"),
            }
        except Exception as exc:                          # noqa: BLE001
            person["tool_biography"] = {"error": type(exc).__name__}
        out["people"][alias] = person

    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % DBPATH.replace("\\", "/"),
                          uri=True)
    con.row_factory = sqlite3.Row

    def q(sql, args=()):
        return [dict(r) for r in con.execute(sql, args).fetchall()]

    out["vector_inventory"] = {
        "generations": q(
            "SELECT generation, status, dims, model, config_revision, "
            "namespace, index_name FROM mca_embedding_index_generations "
            "ORDER BY generation DESC LIMIT 8"),
        "graph_facts_vec_rowids": q(
            "SELECT COUNT(*) AS n FROM graph_facts_vec_rowids"),
        "graph_facts_vec_info": q("SELECT * FROM graph_facts_vec_info"),
        "graph_facts_vec_auxiliary": q(
            "SELECT COUNT(*) AS n FROM graph_facts_vec_auxiliary"),
        "facts_with_vector": q(
            "SELECT COUNT(*) AS n FROM graph_facts f WHERE EXISTS ("
            "SELECT 1 FROM graph_facts_vec_rowids r WHERE r.rowid=f.id)"),
        "facts_total": q("SELECT COUNT(*) AS n FROM graph_facts"),
        "facts_confirmed": q(
            "SELECT COUNT(*) AS n FROM graph_facts WHERE status='confirmed'"),
        "embedding_cache_rows": q(
            "SELECT COUNT(*) AS n FROM embedding_cache"),
        "vec_tables": q(
            "SELECT name FROM sqlite_master WHERE type='table' AND "
            "(name LIKE '%vec%' OR name LIKE '%embedding%') ORDER BY name"),
    }
    con.close()

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("OUT", OUT, flush=True)
    await db.close()
    os._exit(0)


try:
    asyncio.run(main())
except BaseException as exc:                              # noqa: BLE001
    import traceback
    traceback.print_exc()
    print("PROBE_FAILED", type(exc).__name__, flush=True)
    os._exit(2)
