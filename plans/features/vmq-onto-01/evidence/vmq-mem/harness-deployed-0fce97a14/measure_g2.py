# -*- coding: utf-8 -*-
"""VMQ-MEM-06 G2 — read-only evidence harness (candidate 0fce97a14).

Contract: ``plans/features/vmq-onto-01/evidence/acceptance-closeout-2026-11-19/architect-mem06-decision.md`` §5.
This is evidence tooling, not product code. It reuses:
  * ``harness-slice-d-2026-11-15/measure.py`` method-level probes (A1/A1P/D/T2/T3,
    Old_Episode, people),
  * the real product seams (``DirectChatService._rag_unified_rows``,
    ``_build_rag_block``, ``_build_old_episodes``, ``_build_evidence_bundle``,
    ``mca_retrieval_context.retrieve``, ``DatabaseService.lore_*``,
    ``LoreCompilerService`` renderers),
and adds only the G2 probes required by §5.3-§5.4.

No LLM/embedding calls: the LLM stub raises. The snapshot DB is opened with
``DatabaseService.initialize_readonly`` (SQLite URI ``mode=ro``); the harness
never writes to it (hash before/after is recorded).

Outputs (under ``--out``):
  * ``g2-mem06.json``       compact ids/counts/years/timestamps/hashes only
  * ``g2-mem06-summary.md`` command/candidate/snapshot/chat/topics/tables/
                            per-assertion pass|fail|not_executed/limitations
  * ``g2-mem06-hashes.txt`` snapshot/harness sha256

Exit codes: 0 = all assertions pass; 1 = any fail; 2 = any not_executed
(and no fail); 3 = read-only violation; 4 = technical failure.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

CANDIDATE = "0fce97a14338521a24d94f560e896ebcb19f9492"
CHAT = -1002661910336
A1_QUERY = "напиши юмористический рассказ об основных шизах конфы"
A1P_QUERY = "что за шизы были на конфе?"
D_QUERY = "из-за чего мы ссорились и ругались в 2023 году"
T2_QUERY = "что вообще было с E1, напомни?"
T3_QUERY = "что сейчас происходит с E1?"
LORE_TOPICS = ("шизы конфы", A1_QUERY)
ASSERTION_IDS = (
    "MEM06-A1-AUTO", "MEM06-A1-HIST", "MEM06-A1P-AUTO", "MEM06-A1P-HIST",
    "MEM06-D2023", "MEM06-T2-AUTO", "MEM06-T2-PLANHIST", "MEM06-T3-CURRENT",
    "MEM06-OLD23", "MEM06-OLDP", "MEM06-P1", "MEM06-P2", "MEM06-P3",
    "MEM06-THEMATIC", "MEM06-LORE-GRAPH", "MEM06-LORE-DENSE",
    "MEM06-G1-HINTS", "MEM06-G4-REFS", "MEM06-CHAT-SCOPE",
)
QUERIES = (
    ("A1_auto", A1_QUERY, {"memory_scope": "auto"}),
    ("A1_historical", A1_QUERY, {"memory_scope": "historical"}),
    ("A1P_auto", A1P_QUERY, {"memory_scope": "auto"}),
    ("A1P_historical", A1P_QUERY, {"memory_scope": "historical"}),
    ("D_2023", D_QUERY, {"memory_scope": "auto"}),
    ("T2_auto", T2_QUERY, {"memory_scope": "auto"}),
    ("T2_plan_hist", T2_QUERY,
     {"memory_scope": "auto", "plan_act": "historical_recall"}),
    ("T3_current", T3_QUERY, {"memory_scope": "auto"}),
)
PEOPLE = (
    ("P1", 485008070),
    ("P2_top_author", 138811255),
    ("P3_history_2023_2024", 1313107079),
)
REF_ID_RE = re.compile(r"(?:tg|msg|fact):\d+")
#: G4 resolver sample categories; "other" = recognised but unsupported prefix
#: (e.g. `bot_output_tg:`), "unparseable" = no/lousy `<prefix>:<int>` shape.
SAMPLE_PREFIXES = ("row", "tg", "msg", "other", "unparseable")
GRAPH_TABLES = (
    "smart_messages", "smart_messages_fts", "graph_facts", "graph_facts_fts",
    "nodes", "edges", "lore_stories", "mca_source_refs",
    "mca_community_builds", "mca_community_members",
    "mca_embedding_index_generations",
)


# ── small helpers ──────────────────────────────────────────────────────────

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def year_of(ts):
    try:
        value = int(ts)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return time.gmtime(value).tm_year


def hist(values):
    out: dict = {}
    for value in values:
        key = str(value) if value is not None else "no_date"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def brief(row):
    """No fact/message text: only ids/codes/year/chat."""
    return {
        "id": as_int((row or {}).get("id")),
        "year": year_of((row or {}).get("rag_ts")
                        or (row or {}).get("message_timestamp")
                        or (row or {}).get("created_at")),
        "origin": (row or {}).get("origin"),
        "chat_id": as_int((row or {}).get("chat_id")),
        "period_fill": bool((row or {}).get("period_fill")),
        "subject_proxy": (row or {}).get("subject_proxy"),
        "status": (row or {}).get("status"),
    }


def year_sum(hist_map: dict, years) -> int:
    return sum(int(hist_map.get(str(y), 0)) for y in years)


def _open_ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def db_meta(path: str) -> dict:
    meta = {
        "path": path,
        "exists": os.path.exists(path),
        "bytes": None,
        "sidecars": [],
        "quick_check": "not_executed",
        "user_version": None,
        "tables": {},
        "tables_error": None,
    }
    if not os.path.exists(path):
        return meta
    meta["bytes"] = os.path.getsize(path)
    for suffix in ("-wal", "-shm"):
        if os.path.exists(path + suffix):
            meta["sidecars"].append(suffix)
    try:
        con = _open_ro(path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("PRAGMA quick_check").fetchone()
            meta["quick_check"] = str(row[0]) if row is not None else "empty"
            row = con.execute("PRAGMA user_version").fetchone()
            meta["user_version"] = int(row[0]) if row is not None else None
            present = {str(r[0]) for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type IN "
                "('table','view')").fetchall()}
            for name in GRAPH_TABLES:
                meta["tables"][name] = None
                if name not in present:
                    continue
                try:
                    n = con.execute(
                        "SELECT COUNT(*) FROM %s" % name).fetchone()[0]
                    meta["tables"][name] = int(n)
                except Exception:
                    meta["tables"][name] = "error"
        finally:
            con.close()
    except Exception as exc:                                # noqa: BLE001
        meta["tables_error"] = type(exc).__name__
    return meta


def git_out(cwd: str, *args) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True,
            timeout=60, encoding="utf-8", errors="replace")
        return int(proc.returncode), (proc.stdout or "").strip()
    except Exception as exc:                                # noqa: BLE001
        return 1, "git_error:%s" % type(exc).__name__


def environment_info() -> dict:
    """Interpreter / sqlite-vec identity required by decision §5.1.

    No network: the harness only reports which local interpreter and
    extension it found; the failing LLM/embedding stub is what keeps the
    run offline.
    """
    info = {
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_vec_version": None,
        "sqlite_vec_import": False,
        "sqlite_vec_loaded": None,
        "sqlite_vec_off_reason": None,
        "vec_ok": None,
        "vec_dim": None,
        "network": "not_used_by_harness",
    }
    try:
        import sqlite_vec  # noqa: F401
        info["sqlite_vec_import"] = True
    except Exception as exc:                                # noqa: BLE001
        info["sqlite_vec_import_error"] = type(exc).__name__
    try:
        from importlib.metadata import version as _pkg_version
        info["sqlite_vec_version"] = _pkg_version("sqlite-vec")
    except Exception:                                       # noqa: BLE001
        info["sqlite_vec_version"] = None
    return info


# ── product stubs ──────────────────────────────────────────────────────────

class _Cache:
    def get(self, key, default=None):
        return default

    def get_all(self):
        return {}


class StubLLM:
    async def embed(self, texts):
        raise RuntimeError("EMBED_API_FAILED provider_unavailable")

    async def generate(self, messages, **kwargs):
        raise RuntimeError("LLM unavailable")


class StubAliases:
    def resolve(self, user_id, nickname=None, username=None, memory_name=None):
        return str(nickname or username or memory_name or user_id or "")

    def canon_name(self, name):
        return str(name or "").strip()


class PoolSpy:
    """Capture the period selector input/output (counts only)."""

    def __init__(self, mrc):
        self.mrc = mrc
        self.pool = []
        self.stats = {}
        self.accepted = []
        self._orig = None

    def __enter__(self):
        self._orig = self.mrc.select_period_rows
        spy = self

        def wrapper(rows, **kwargs):
            pool = list(rows or ())
            accepted, stats = spy._orig(rows, **kwargs)
            spy.pool = [brief(row) for row in pool]
            spy.accepted = [brief(row) for row in accepted]
            spy.stats = dict(stats or {})
            return accepted, stats

        self.mrc.select_period_rows = wrapper
        return self

    def __exit__(self, *exc):
        self.mrc.select_period_rows = self._orig
        return False


def period_record(stats: dict, spy: PoolSpy, scope: str) -> dict:
    stats = dict(stats or {})
    return {
        "policy": stats.get("policy") or scope,
        "replace_allowed": int(stats.get("replace_allowed") or 0),
        "period_skipped": str(stats.get("period_skipped") or ""),
        "period_intent": stats.get("period_intent") or {},
        "intent_source": str(stats.get("intent_source") or ""),
        "pool": int(stats.get("selection_rows")
                    if stats.get("selection_rows") is not None
                    else len(spy.pool)),
        "kept": int(stats.get("selection_kept")
                    if stats.get("selection_kept") is not None
                    else len(spy.accepted)),
        "historical_quota": int(stats.get("historical_quota") or 0),
        "multi_year_quota": int(stats.get("multi_year_quota") or 0),
        "dropped_subject": int(stats.get("rejected_subject") or 0),
        "dropped_budget": int(stats.get("dropped_budget") or 0),
        "dropped_status": int(stats.get("dropped_status") or 0),
        "dropped_out_of_target_year": int(
            stats.get("dropped_out_of_target_year") or 0),
        "dropped_unknown_year": int(
            stats.get("dropped_unknown_year") or 0),
        "dropped_pool_cap": int(stats.get("dropped_pool_cap") or 0),
        "vector_leg": str(stats.get("vector_leg") or ""),
        "vector_rows": int(stats.get("vector_rows") or 0),
        "vector_unavailable": int(stats.get("vector_unavailable") or 0),
        "vector_unavailable_reason": str(
            stats.get("vector_unavailable_reason") or ""),
    }


# ── probes ─────────────────────────────────────────────────────────────────

async def class_probe(svc, mrc, db, chat_id, stub, tail, key, query,
                      extra, with_writer=True) -> dict:
    entry = {"query_class": key, "query_sha256": sha256_text(query)}
    scope = str(extra.get("memory_scope") or "auto")
    call_kwargs = dict(extra)
    call_kwargs.pop("memory_scope", None)
    stub.text = query
    with PoolSpy(mrc) as spy:
        try:
            rows = await asyncio.wait_for(svc._rag_unified_rows(
                chat_id, query, stub, memory_scope=scope, **call_kwargs), 300)
            entry["error"] = None
        except Exception as exc:                            # noqa: BLE001
            rows = []
            entry["error"] = type(exc).__name__
    rows = list(rows or ())
    stats = dict(getattr(svc, "_rag_period_stats", None) or {})
    entry.update({
        "rows": len(rows),
        "row_years": hist([year_of(r.get("rag_ts")
                                   or r.get("message_timestamp"))
                           for r in rows if isinstance(r, dict)]),
        "row_chat_ids": hist([as_int(r.get("chat_id")) for r in rows
                              if isinstance(r, dict)]),
        "rows_brief": [brief(r) for r in rows if isinstance(r, dict)],
        "period": period_record(stats, spy, scope),
        "selection_stats": {k: int(v) for k, v in (spy.stats or {}).items()
                            if isinstance(v, int)},
        "pool_years": hist([r.get("year") for r in spy.pool]),
        "accepted_years": hist([r.get("year") for r in spy.accepted]),
    })

    # Writer blocks (actual product seam). Its own retrieval pass is not mixed
    # with the class-period stats above; only the returned block/trace is used.
    writer = {}
    if with_writer:
        try:
            trace: dict = {}
            block, _hint = await asyncio.wait_for(svc._build_rag_block(
                chat_id, stub, "", memory_scope=scope, out_memory=trace,
                **call_kwargs), 300)
            writer.update({
                "rag_rendered": bool(block),
                "rag_chars": len(block or ""),
                "rag_years": dict(trace.get("years") or {}),
                "rag_source_ids": len(trace.get("source_ids") or ()),
            })
        except Exception as exc:                            # noqa: BLE001
            writer.update({"rag_rendered": False, "rag_chars": 0,
                           "rag_years": {}, "rag_source_ids": 0,
                           "rag_error": type(exc).__name__})
        try:
            ep_block, ep_stats = await asyncio.wait_for(
                svc._build_old_episodes(chat_id, query, tail, {}, None,
                                        None), 300)
            writer.update({
                "episode_rendered": bool(ep_block),
                "episode_chars": len(ep_block or ""),
                "episode_years": dict((ep_stats or {}).get("years") or {}),
                "episode_messages": int((ep_stats or {}).get("messages") or 0),
                "episode_hits": int((ep_stats or {}).get("hits") or 0),
                "episode_spans": len((ep_stats or {}).get("spans") or ()),
                "episode_skip": "" if ep_block else "empty",
            })
        except Exception as exc:                            # noqa: BLE001
            writer.update({"episode_rendered": False, "episode_chars": 0,
                           "episode_years": {}, "episode_messages": 0,
                           "episode_hits": 0, "episode_spans": 0,
                           "episode_skip": "error:%s" % type(exc).__name__})
    entry["writer"] = writer
    return entry


async def old_episode_probe(svc, mrc, db, chat_id, stub, tail, key,
                            query) -> dict:
    entry = {"query_class": key, "query_sha256": sha256_text(query)}
    try:
        block, stats = await asyncio.wait_for(
            svc._build_old_episodes(chat_id, query, tail, {}, None, None), 300)
    except Exception as exc:                                # noqa: BLE001
        return {**entry, "error": type(exc).__name__}
    stats = dict(stats or {})
    spans = []
    all_sources: list = []
    for span in stats.get("spans") or ():
        if not isinstance(span, dict):
            continue
        src = [str(x) for x in (span.get("source_ids") or ())]
        all_sources.extend(src)
        spans.append({
            "source_count": len(src),
            "first_ts": int(span.get("first_ts") or 0),
            "last_ts": int(span.get("last_ts") or 0),
        })
    # One extra read-only retrieval: composition by entity_type/channel.
    # The consumer rejects non-message entities and messages already in the
    # fresh tail; record both so an empty plain episode is explained instead
    # of turning a normal skip into a failed assertion (§2 R2 / §5.2).
    composition = {"episode": 0, "graph_fact": 0, "message": 0, "other": 0}
    channels: dict = {}
    message_cands: list = []
    comp_error = None
    status = None
    reason = None
    try:
        req = mrc.RetrievalRequest(
            chat_id=chat_id, query=query, mode="history", top_k=8,
            reply_depth=0)
        result = await mrc.retrieve(db, svc.memory, req)
        for cand in result.candidates:
            kind = ("episode" if cand.entity_type == "episode"
                    else "graph_fact" if cand.entity_type == "graph_fact"
                    else "message" if cand.entity_type == "message"
                    else "other")
            composition[kind] += 1
            channels[cand.channel] = channels.get(cand.channel, 0) + 1
            if cand.entity_type == "message":
                message_cands.append(cand)
        status = result.status
        reason = result.reason_code
    except Exception as exc:                                # noqa: BLE001
        status, reason, comp_error = "error", None, type(exc).__name__
    tail_tg: set = set()
    tail_ids: set = set()
    for row in tail or ():
        item = dict(row) if row is not None else {}
        tg = as_int(item.get("tg_message_id"))
        if tg is not None:
            tail_tg.add(tg)
        rid = as_int(item.get("id"))
        if rid is not None:
            tail_ids.add(rid)
    message_tail = 0
    message_unparseable = 0
    for cand in message_cands:
        head, _, value = str(getattr(cand, "id", "") or "").partition(":")
        number = as_int(value)
        if head not in ("tg", "msg") or number is None:
            message_unparseable += 1
        elif (head == "tg" and number in tail_tg) or (
                head == "msg" and (number in tail_tg or number in tail_ids)):
            message_tail += 1
    try:
        from services import direct_context_composer as _composer
        episode_max_count = int(_composer.episode_max_count())
    except Exception:                                       # noqa: BLE001
        episode_max_count = None
    entry.update({
        "empty": not bool(block),
        "block_chars": len(block or ""),
        "period_intent": stats.get("period_intent"),
        "year_window": stats.get("year_window"),
        "hits": int(stats.get("hits") or 0),
        "messages": int(stats.get("messages") or 0),
        "spans": spans,
        "source_ids": all_sources,
        "years": dict(stats.get("years") or {}),
        "skipped_available": False,
        "candidate_composition": composition,
        "candidate_message_count": len(message_cands),
        "candidate_message_tail": message_tail,
        "candidate_message_unparseable": message_unparseable,
        "episode_max_count": episode_max_count,
        "composition_channels": channels,
        "composition_status": status,
        "composition_reason": reason,
        "composition_error": comp_error,
    })
    return entry


async def person_probe(svc, mrc, db, chat_id, stub, alias, uid) -> dict:
    entry = {"alias": alias, "uid": uid}
    row = await db.db.execute(
        "SELECT author_name FROM smart_messages WHERE user_id=? AND "
        "chat_id=? AND COALESCE(author_name,'')<>'' "
        "GROUP BY author_name ORDER BY COUNT(*) DESC LIMIT 1",
        (uid, chat_id))
    name_row = await row.fetchone()
    name = str(name_row["author_name"] if name_row else "")
    entry["name_present"] = bool(name)
    entry["name_sha256"] = sha256_text(name) if name else None
    query = "что ты знаешь про %s?" % name
    entry["query_sha256"] = sha256_text(query)
    stub.text = query
    try:
        rows = await asyncio.wait_for(svc._rag_unified_rows(
            chat_id, query, stub, memory_scope="auto",
            subject_name=name, subject_uid=uid), 300)
        entry["error"] = None
    except Exception as exc:                                # noqa: BLE001
        rows = []
        entry["error"] = type(exc).__name__
    rows = list(rows or ())
    entry.update({
        "rows": len(rows),
        "row_years": hist([year_of(r.get("rag_ts")
                                   or r.get("message_timestamp"))
                           for r in rows if isinstance(r, dict)]),
        "row_chat_ids": hist([as_int(r.get("chat_id")) for r in rows
                              if isinstance(r, dict)]),
        "rows_brief": [brief(r) for r in rows if isinstance(r, dict)],
        "period": period_record(
            dict(getattr(svc, "_rag_period_stats", None) or {}),
            SimpleNamespace(pool=[], accepted=[]), "auto"),
    })
    try:
        profile = await db.get_subject_profile_facts(
            chat_id, name, 10, int(time.time()), user_id=uid)
        entry["profile_facts"] = len(profile or ())
        entry["profile_years"] = hist(
            [r.get("yr") for r in (profile or ()) if isinstance(r, dict)])
    except Exception as exc:                                # noqa: BLE001
        entry["profile_facts"] = 0
        entry["profile_years"] = {}
        entry["profile_error"] = type(exc).__name__
    return entry


async def thematic_probe(mrc, db, memory, chat_id, gates) -> dict:
    out = {"query_sha256": sha256_text(A1_QUERY)}
    try:
        req = mrc.RetrievalRequest(
            chat_id=chat_id, query=A1_QUERY, mode="thematic", top_k=8)
        res = await asyncio.wait_for(mrc.retrieve(db, memory, req), 300)
        counts: dict = {}
        for cand in res.candidates:
            counts[cand.entity_type] = counts.get(cand.entity_type, 0) + 1
        out.update({
            "mode": res.mode,
            "status": res.status,
            "reason_code": res.reason_code,
            "channels_used": list(res.channels_used),
            "candidates": len(res.candidates),
            "counts": counts,
            "community": counts.get("community", 0),
            "community_gate": bool(gates.get("memory_communities")),
            "community_builds": gates.get("community_builds"),
            "community_active": gates.get("community_active"),
        })
    except Exception as exc:                                # noqa: BLE001
        out.update({"error": type(exc).__name__})
    return out


async def g1_probe(svc, mrc, db, chat_id, stub) -> dict:
    out = {"query_sha256": sha256_text(A1_QUERY)}
    try:
        base_req = mrc.RetrievalRequest(
            chat_id=chat_id, query=A1_QUERY, mode="specific", top_k=10,
            channels=("vector",), preserve_channel_order=True,
            include_self=True, include_direct_reply=True)
        try:
            # The in-memory served-fact penalty is stateful across calls and
            # is not a hint effect; reset it so the probe isolates overview.
            svc.memory._rag_usage.clear()
        except Exception:
            pass
        res_no = await asyncio.wait_for(
            mrc.retrieve(db, svc.memory, base_req), 300)
        try:
            svc.memory._rag_usage.clear()
        except Exception:
            pass
        res_yes = await asyncio.wait_for(
            mrc.retrieve(db, svc.memory, dataclasses.replace(
                base_req, include_overview=True)), 300)
        cand_no = [(c.id, c.entity_type, c.channel)
                   for c in res_no.candidates]
        cand_yes = [(c.id, c.entity_type, c.channel)
                    for c in res_yes.candidates]
        same_order = cand_no == cand_yes
        same_set = set(cand_no) == set(cand_yes)
        overview = res_yes.overview
        stub.text = A1_QUERY
        result = None
        rows = await asyncio.wait_for(svc._rag_unified_rows(
            chat_id, A1_QUERY, stub, memory_scope="auto",
            include_overview=True), 300)
        result = getattr(svc, "_rag_overview_result", None)
        rag_block, _hint = await asyncio.wait_for(svc._build_rag_block(
            chat_id, stub, "", memory_scope="auto"), 300)
        user_blocks = [rag_block] if rag_block else []
        bundle = await asyncio.wait_for(svc._build_evidence_bundle(
            chat_id, stub, A1_QUERY, "Probe", 485008070, user_blocks,
            retrieval_result=result), 300)
        applied = None
        if bundle is not None:
            applied = mrc.apply_overview_to_bundle(bundle, overview)
        hints = list(getattr(overview, "semantic_hints", ()) or ())
        bundle_hints = list(getattr(applied, "semantic_hints", ()) or ())
        payload = []
        try:
            from services.payload_builder import build_messages
            payload = build_messages("", user_blocks)
        except Exception as exc:                            # noqa: BLE001
            out["payload_error"] = type(exc).__name__
        payload_text = "\n".join(str(m.get("content") or "")
                                 for m in payload)
        needles: list[tuple[str, str]] = []
        for idx, hint in enumerate(hints):
            for field in ("text", "label"):
                value = str((hint or {}).get(field) or "")
                if value:
                    needles.append(("hint[%d].%s" % (idx, field), value))
        for idx, value in enumerate(bundle_hints):
            if value:
                needles.append(("bundle.semantic_hints[%d]" % idx,
                                str(value)))
        leaks = [name for name, value in needles if value in payload_text]
        out.update({
            "overview_present": overview is not None,
            "overview_state": (str(getattr(overview, "state", ""))
                               if overview is not None else None),
            "hints": len(hints),
            "hint_kinds": hist([h.get("kind") for h in hints
                                if isinstance(h, dict)]),
            "bundle_present": applied is not None,
            "bundle_hints": len(bundle_hints),
            "needles_checked": len(needles),
            "leaks": leaks,
            "payload_chars": len(payload_text),
            "candidates_no_overview": len(cand_no),
            "candidates_with_overview": len(cand_yes),
            "candidates_identical": same_order,
            "candidates_same_set": same_set,
            "candidates_same_order": same_order,
            "candidate_ids_no": [list(x) for x in cand_no],
            "candidate_ids_yes": [list(x) for x in cand_yes],
            "rows_with_overview": len(rows or ()),
            "error": None,
        })
    except Exception as exc:                                # noqa: BLE001
        out["error"] = type(exc).__name__
    return out


def sample_ref_prefix(ref: str) -> tuple[str, int | None]:
    """Classify a G4 span source id; never guess across prefixes."""
    text = str(ref or "").strip()
    head, sep, tail = text.partition(":")
    if not sep or not head or not tail:
        return "unparseable", None
    if head not in ("row", "tg", "msg"):
        return "other", None
    value = as_int(tail)
    if value is None or value <= 0:
        return "unparseable", None
    return head, value


async def resolve_sample_ref(db, chat_id: int,
                             ref: str) -> tuple[str, bool, bool]:
    """(prefix, resolved, same_chat) for one sampled episode source id.

    `row:<smart_messages.id>` is the shape emitted by
    `direct_context_composer.row_to_fragment` for imported rows without a
    Telegram id; `msg:` keeps its documented dual id/tg meaning. Unknown
    prefixes stay unresolved (§5.4: no guessing).
    """
    prefix, value = sample_ref_prefix(ref)
    if prefix == "row":
        sql = ("SELECT chat_id FROM smart_messages WHERE chat_id=? AND "
               "id=? LIMIT 1")
        params = (chat_id, value)
    elif prefix == "tg":
        sql = ("SELECT chat_id FROM smart_messages WHERE chat_id=? AND "
               "tg_message_id=? LIMIT 1")
        params = (chat_id, value)
    elif prefix == "msg":
        sql = ("SELECT chat_id FROM smart_messages WHERE chat_id=? AND "
               "(id=? OR tg_message_id=?) LIMIT 1")
        params = (chat_id, value, value)
    else:
        return prefix, False, False
    cur = await db.db.execute(sql, params)
    row = await cur.fetchone()
    if row is None:
        return prefix, False, False
    return prefix, True, int(row["chat_id"]) == int(chat_id)


async def resolve_episode_sample(db, chat_id: int, refs, *,
                                 limit: int = 5) -> dict:
    """Resolve first `limit` span source ids and record per-prefix counts."""
    sample = [str(ref) for ref in list(refs or ())[:int(limit)] if str(ref)]
    by_prefix = {key: 0 for key in SAMPLE_PREFIXES}
    resolved_by_prefix = {key: 0 for key in SAMPLE_PREFIXES}
    resolved = 0
    same_chat = 0
    for ref in sample:
        prefix, ok, same = await resolve_sample_ref(db, chat_id, ref)
        by_prefix[prefix] += 1
        if ok:
            resolved += 1
            resolved_by_prefix[prefix] += 1
            if same:
                same_chat += 1
    return {
        "sampled": len(sample),
        "resolved": resolved,
        "same_chat": same_chat,
        "unresolved": len(sample) - resolved,
        "by_prefix": by_prefix,
        "resolved_by_prefix": resolved_by_prefix,
        "sample_refs": sample,
    }


async def g4_probe(svc, mrc, db, chat_id, stub, tail) -> dict:
    out = {"query_sha256": sha256_text(D_QUERY)}
    try:
        from services.canonical_context import (
            SpeechProjection, speech_projection_enabled)
        out["speech_projection"] = bool(speech_projection_enabled())

        async def build(projection):
            stub.text = D_QUERY
            rag, _hint = await asyncio.wait_for(svc._build_rag_block(
                chat_id, stub, "", memory_scope="auto",
                projection=projection), 300)
            ep, stats = await asyncio.wait_for(svc._build_old_episodes(
                chat_id, D_QUERY, tail, {}, None, projection), 300)
            blocks = [b for b in (rag, ep,
                                  "<Current_Question>\n%s\n"
                                  "</Current_Question>" % D_QUERY) if b]
            bundle = await asyncio.wait_for(svc._build_evidence_bundle(
                chat_id, stub, D_QUERY, "Probe", 485008070, blocks,
                retrieval_result=getattr(svc, "_rag_overview_result", None)),
                300)
            return rag, ep, stats, bundle

        rag_raw, ep_raw, stats_raw, bundle_raw = await build(None)
        proj = SpeechProjection(run_id="g2-mem06")
        rag_proj, ep_proj, stats_proj, bundle_proj = await build(proj)

        def bundle_view(bundle, rag, ep):
            if bundle is None:
                return {"bundle": False}
            evidence_ids = [str(item.entity_id)
                            for item in (bundle.evidence or ())]
            rag_refs = list(dict.fromkeys(REF_ID_RE.findall(rag or "")))
            ep_refs = list(dict.fromkeys(REF_ID_RE.findall(ep or "")))
            ep_only = [ref for ref in ep_refs if ref not in rag_refs]
            evidence_set = set(evidence_ids)
            rag_set = set(rag_refs)
            ep_in_bundle = [ref for ref in ep_refs
                            if ref in evidence_set and ref not in rag_set]
            return {
                "bundle": True,
                "rag_refs": len(rag_refs),
                "old_episode_refs": len(ep_refs),
                "episode_only_refs": len(ep_only),
                "episode_refs_in_evidence": len(ep_in_bundle),
                "evidence": len(bundle.evidence or ()),
                "branch": len(bundle.branch or ()),
                "selected_refs_reconstructed": (
                    (1 if bundle.current_message_ref else 0)
                    + len(bundle.branch or ())
                    + len(bundle.evidence or ())),
                "fact_refs": sum(1 for ref in evidence_ids
                                 if ref.startswith("fact:")),
                "overview_episode_refs": len(bundle.episode_refs or ()),
                "context_version_len": len(bundle.context_version or ""),
            }

        out["raw"] = bundle_view(bundle_raw, rag_raw, ep_raw)
        out["projection_view"] = bundle_view(bundle_proj, rag_proj, ep_proj)

        seen: list = []
        for span in (stats_raw or {}).get("spans") or ():
            if not isinstance(span, dict):
                continue
            for ref in span.get("source_ids") or ():
                text = str(ref)
                if text and text not in seen:
                    seen.append(text)
        episode_sample = await resolve_episode_sample(
            db, chat_id, seen, limit=5)
        out.update({
            "episode_source_ids": len(seen),
            "episode_sample": episode_sample,
            "episode_stats": {
                "hits": int((stats_raw or {}).get("hits") or 0),
                "messages": int((stats_raw or {}).get("messages") or 0),
                "spans": len((stats_raw or {}).get("spans") or ()),
                "years": dict((stats_raw or {}).get("years") or {}),
            },
            "projection_episode_stats": {
                "spans": len((stats_proj or {}).get("spans") or ()),
                "years": dict((stats_proj or {}).get("years") or {}),
            },
            "error": None,
        })
    except Exception as exc:                                # noqa: BLE001
        out["error"] = type(exc).__name__
    return out


async def lore_probe(db, chat_id, topic) -> dict:
    from services import lore_compiler_service as lcs
    from services.canonical_context import SpeechProjection
    from services.summary_memory import build_fts_query
    out = {"topic": topic, "topic_sha256": sha256_text(topic)}
    try:
        tokens = lcs.topic_tokens(topic)
        match = build_fts_query(tokens) if tokens else ""
        graph = await db.lore_graph_slice(
            chat_id, topic, depth=2, max_facts=lcs._LORE_GRAPH_MAX_FACTS)
        speech = SpeechProjection(run_id="lore:%s" % chat_id)
        graph_lines = lcs.LoreCompilerService._trim(
            lcs.LoreCompilerService(None, None)._graph_facts(graph, speech),
            lcs._LORE_GRAPH_MAX_SYMBOLS)
        dense = await db.lore_dense_dialogs(
            chat_id, match, max_dialogs=lcs._LORE_DIALOGS_MAX,
            window_minutes=lcs._LORE_DIALOG_WINDOW_MINUTES, since_ts=0)
        pairs = lcs.LoreCompilerService._trim_pairs(
            lcs.LoreCompilerService(None, None)._dialog_pairs(
                dense.get("dialogs") or [], speech),
            lcs._LORE_DIALOG_MAX_SYMBOLS)
        dialog_lines = [line for line, _ in pairs]
        included_last_ts = max((ts for _, ts in pairs), default=0)
        fact_years = hist([year_of(f.get("rag_ts"))
                           for f in (graph.get("facts") or ())
                           if isinstance(f, dict)])
        windows = []
        rows_total = 0
        row_years = {}
        for window in dense.get("dialogs") or ():
            stamps = []
            wyears = {}
            for row in window or ():
                row = dict(row or {})
                ts = int(row.get("timestamp") or 0)
                if ts:
                    stamps.append(ts)
                y = year_of(ts)
                if y is not None:
                    wyears[y] = wyears.get(y, 0) + 1
            rows_total += len(window or ())
            for y, n in wyears.items():
                row_years[y] = row_years.get(y, 0) + n
            windows.append({
                "start": min(stamps) if stamps else 0,
                "end": max(stamps) if stamps else 0,
                "rows": len(window or ()),
                "years": {str(k): v for k, v in sorted(wyears.items())},
            })
        out.update({
            "topic_tokens": tokens,
            "topic_token_count": len(tokens),
            "match_present": bool(match),
            "graph": {
                "nodes": len(graph.get("nodes") or ()),
                "edges": len(graph.get("edges") or ()),
                "facts": len(graph.get("facts") or ()),
                "fact_years": fact_years,
            },
            "dense": {
                "total": int(dense.get("total") or 0),
                "earliest": int(dense.get("earliest") or 0),
                "latest": int(dense.get("latest") or 0),
                "dialogs": len(dense.get("dialogs") or ()),
                "rows": rows_total,
                "row_years": {str(k): v for k, v in sorted(row_years.items())},
                "windows": windows,
            },
            "rendered": {
                "graph_lines": len(graph_lines),
                "dialog_lines": len(dialog_lines),
                "chars": len("\n".join(graph_lines))
                + len("\n".join(dialog_lines)),
            },
            "included_last_ts": int(included_last_ts or 0),
            "error": None,
        })
    except Exception as exc:                                # noqa: BLE001
        out["error"] = type(exc).__name__
    return out


async def chat_scope_probe(mrc, db, memory, chat_id, other_chat) -> dict:
    out = {"chat_id": chat_id}
    try:
        probe_query = "шизы конфы otherchat"
        req = mrc.RetrievalRequest(
            chat_id=chat_id, query=probe_query, mode="specific", top_k=10,
            channels=("lexical", "exact"), reply_depth=0)
        res = await asyncio.wait_for(mrc.retrieve(db, memory, req), 300)
        out["other_chat_query_candidates"] = len(res.candidates)
        out["other_chat_query_foreign"] = sum(
            1 for c in res.candidates
            if c.chat_id is not None and int(c.chat_id) != int(chat_id))
        out["other_chat_query_chat_ids"] = hist(
            [int(c.chat_id) if c.chat_id is not None else None
             for c in res.candidates])
        other_id = None
        other_tg = None
        if other_chat is not None:
            cur = await db.db.execute(
                "SELECT id, tg_message_id FROM smart_messages "
                "WHERE chat_id=? LIMIT 1", (int(other_chat),))
            row = await cur.fetchone()
            if row is not None:
                other_id = int(row["id"])
                if row["tg_message_id"] is not None:
                    other_tg = int(row["tg_message_id"])
        out["other_chat_id"] = other_id
        out["other_chat_message_hits"] = sum(
            1 for c in res.candidates
            if str(c.id) in ({("tg:%d" % other_tg) if other_tg else "",
                              ("msg:%d" % other_id) if other_id else ""})
            or (other_id is not None
                and str(getattr(c, "entity_id", "")) == str(other_id)))
        target_has_other = None
        if other_id is not None:
            cur = await db.db.execute(
                "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id=? "
                "AND id=?", (int(chat_id), other_id))
            row = await cur.fetchone()
            target_has_other = int(row["n"] if row is not None else 0)
        out["other_chat_message_in_target"] = target_has_other
        same_ref = None
        other_ref = None
        cur = await db.db.execute(
            "SELECT entity_type, entity_id FROM mca_source_refs WHERE "
            "chat_id=? LIMIT 1", (int(chat_id),))
        row = await cur.fetchone()
        if row is not None:
            same_ref = (str(row["entity_type"]), str(row["entity_id"]))
        if other_chat is not None:
            cur = await db.db.execute(
                "SELECT entity_type, entity_id FROM mca_source_refs WHERE "
                "chat_id=? LIMIT 1", (int(other_chat),))
            row = await cur.fetchone()
            if row is not None:
                other_ref = (str(row["entity_type"]), str(row["entity_id"]))
        out["same_chat_source_ref"] = None
        out["other_chat_source_ref"] = None
        if same_ref:
            resolved = await db.resolve_source_ref_ids(
                int(chat_id), [same_ref])
            out["same_chat_source_ref"] = bool(resolved)
        if other_ref:
            resolved = await db.resolve_source_ref_ids(
                int(chat_id), [other_ref])
            out["other_chat_source_ref"] = bool(resolved)
        out["source_refs_available"] = bool(same_ref or other_ref)
    except Exception as exc:                                # noqa: BLE001
        out["error"] = type(exc).__name__
    return out


# ── assertions ─────────────────────────────────────────────────────────────

def _class_ok(classes, key):
    entry = (classes or {}).get(key) or {}
    return entry, not entry.get("error")


def assertion(aid: str, expected: str, actual: dict, status: str) -> dict:
    return {"id": aid, "expected": expected, "actual": actual,
            "status": status}


def evaluate(classes, old_episodes, people, thematic, lore, g1, g4,
             scope) -> list:
    out: list = []

    def add(aid, expected, actual, ok, reason=None):
        if ok is True:
            status = "pass"
        elif ok is False:
            status = "fail"
        else:
            status = "not_executed"
        if reason:
            actual = dict(actual or {})
            actual["reason"] = reason
        out.append(assertion(aid, expected, actual or {}, status))

    e, ok = _class_ok(classes, "A1_auto")
    if not ok:
        add("MEM06-A1-AUTO", "rows=10 all 2026, replace_allowed=0, "
            "period_skipped auto*, Old_Episode_plain empty", e, None,
            "class_error")
    else:
        plain = old_episodes.get("Old_Episode_plain") or {}
        okv = (e.get("rows") == 10
               and e.get("row_years") == {"2026": 10}
               and e.get("period", {}).get("replace_allowed") == 0
               and e.get("period", {}).get("period_skipped") in (
                   "auto_full_slice", "auto_thin_slice", "auto_no_replace")
               and not plain.get("error")
               and bool(plain.get("empty")))
        add("MEM06-A1-AUTO", "rows=10 all 2026, replace_allowed=0, "
            "period_skipped auto*, Old_Episode_plain empty",
            {"rows": e.get("rows"), "row_years": e.get("row_years"),
             "replace_allowed": e.get("period", {}).get("replace_allowed"),
             "period_skipped": e.get("period", {}).get("period_skipped"),
             "old_episode_plain_empty": plain.get("empty")}, okv)

    for aid, key in (("MEM06-A1-HIST", "A1_historical"),
                     ("MEM06-A1P-HIST", "A1P_historical")):
        e, ok = _class_ok(classes, key)
        if not ok:
            add(aid, "2026 majority + >=1 pre-2026, pool>0 kept>0, drop "
                "counters recorded", e, None, "class_error")
            continue
        years = e.get("row_years") or {}
        pre = sum(v for y, v in years.items()
                  if y.isdigit() and int(y) < 2026)
        cur = int(years.get("2026") or 0)
        period = e.get("period") or {}
        okv = (e.get("rows", 0) > 0 and cur > pre and pre >= 1
               and int(period.get("pool") or 0) > 0
               and int(period.get("kept") or 0) > 0
               and "dropped_budget" in period
               and "dropped_subject" in period)
        add(aid, "2026 majority + >=1 pre-2026, pool>0 kept>0, drop "
            "counters recorded",
            {"rows": e.get("rows"), "row_years": years, "pre_2026": pre,
             "pool": period.get("pool"), "kept": period.get("kept"),
             "dropped_budget": period.get("dropped_budget"),
             "dropped_subject": period.get("dropped_subject")}, okv)

    e, ok = _class_ok(classes, "A1P_auto")
    if not ok:
        add("MEM06-A1P-AUTO", "rows=10 all 2026, replace_allowed=0, "
            "period_skipped auto*", e, None, "class_error")
    else:
        okv = (e.get("rows") == 10
               and e.get("row_years") == {"2026": 10}
               and e.get("period", {}).get("replace_allowed") == 0
               and e.get("period", {}).get("period_skipped") in (
                   "auto_full_slice", "auto_thin_slice", "auto_no_replace"))
        add("MEM06-A1P-AUTO", "rows=10 all 2026, replace_allowed=0, "
            "period_skipped auto*",
            {"rows": e.get("rows"), "row_years": e.get("row_years"),
             "replace_allowed": e.get("period", {}).get("replace_allowed"),
             "period_skipped": e.get("period", {}).get("period_skipped")},
            okv)

    e, ok = _class_ok(classes, "D_2023")
    if not ok:
        add("MEM06-D2023", ">=1 2023 row, replace_allowed=1, foreign-year "
            "period rows only with drop reason", e, None, "class_error")
    else:
        years = e.get("row_years") or {}
        period = e.get("period") or {}
        foreign = {y: v for y, v in years.items()
                   if y.isdigit() and int(y) not in (2023, 2026)}
        okv = (int(years.get("2023") or 0) >= 1
               and int(period.get("replace_allowed") or 0) == 1
               and (not foreign
                    or int(period.get("dropped_out_of_target_year") or 0) > 0))
        add("MEM06-D2023", ">=1 2023 row, replace_allowed=1, foreign-year "
            "period rows only with drop reason",
            {"row_years": years, "replace_allowed": period.get(
                "replace_allowed"), "foreign_years": sorted(foreign),
             "dropped_out_of_target_year": period.get(
                 "dropped_out_of_target_year")}, okv)

    e, ok = _class_ok(classes, "T2_auto")
    if not ok:
        add("MEM06-T2-AUTO", "rows=10 all 2026, replace_allowed=0, "
            "period_skipped auto*", e, None, "class_error")
    else:
        okv = (e.get("rows") == 10
               and e.get("row_years") == {"2026": 10}
               and e.get("period", {}).get("replace_allowed") == 0
               and e.get("period", {}).get("period_skipped") in (
                   "auto_full_slice", "auto_thin_slice", "auto_no_replace"))
        add("MEM06-T2-AUTO", "rows=10 all 2026, replace_allowed=0, "
            "period_skipped auto*",
            {"rows": e.get("rows"), "row_years": e.get("row_years"),
             "replace_allowed": e.get("period", {}).get("replace_allowed"),
             "period_skipped": e.get("period", {}).get("period_skipped")},
            okv)

    e, ok = _class_ok(classes, "T2_plan_hist")
    if not ok:
        add("MEM06-T2-PLANHIST", "historical shape + plan_act signal", e,
            None, "class_error")
    else:
        years = e.get("row_years") or {}
        pre = sum(v for y, v in years.items()
                  if y.isdigit() and int(y) < 2026)
        cur = int(years.get("2026") or 0)
        period = e.get("period") or {}
        intent = period.get("period_intent") or {}
        okv = (e.get("rows", 0) > 0 and cur > pre and pre >= 1
               and int(period.get("pool") or 0) > 0
               and int(period.get("kept") or 0) > 0
               and str(intent.get("source") or "") in (
                   "plan_act", "memory_scope"))
        add("MEM06-T2-PLANHIST", "historical shape + plan_act signal",
            {"row_years": years, "pool": period.get("pool"),
             "kept": period.get("kept"), "period_intent": intent}, okv)

    e, ok = _class_ok(classes, "T3_current")
    if not ok:
        add("MEM06-T3-CURRENT", "rows=10 all 2026, no period fill", e,
            None, "class_error")
    else:
        okv = (e.get("rows") == 10
               and e.get("row_years") == {"2026": 10}
               and e.get("period", {}).get("replace_allowed") == 0
               and e.get("period", {}).get("period_skipped") in (
                   "auto_full_slice", "auto_thin_slice", "auto_no_replace"))
        add("MEM06-T3-CURRENT", "rows=10 all 2026, no period fill",
            {"rows": e.get("rows"), "row_years": e.get("row_years"),
             "replace_allowed": e.get("period", {}).get("replace_allowed"),
             "period_skipped": e.get("period", {}).get("period_skipped")},
            okv)

    old23 = old_episodes.get("Old_Episode_2023") or {}
    if old23.get("error"):
        add("MEM06-OLD23", "non-empty, only 2023, spans with source_ids",
            old23, None, "probe_error")
    else:
        years = old23.get("years") or {}
        years = {str(k): v for k, v in years.items()}
        spans = old23.get("spans") or []
        okv = (not old23.get("empty")
               and years and set(years) == {"2023"}
               and bool(spans) and all(int(s.get("source_count") or 0) > 0
                                       for s in spans))
        add("MEM06-OLD23", "non-empty, only 2023, spans with source_ids",
            {"empty": old23.get("empty"), "years": years,
             "spans": len(spans),
             "source_ids": len(old23.get("source_ids") or ())}, okv)

    oldp = old_episodes.get("Old_Episode_plain") or {}
    if oldp.get("error"):
        add("MEM06-OLDP", "empty (A2 baseline); candidate composition "
            "explains why", oldp, None, "probe_error")
    else:
        comp = oldp.get("candidate_composition") or {}
        total = sum(int(v or 0) for v in comp.values())
        msg = int(comp.get("message") or 0)
        msg_tail = int(oldp.get("candidate_message_tail") or 0)
        msg_bad = int(oldp.get("candidate_message_unparseable") or 0)
        if total == 0:
            explanation = "no_candidates"
        elif msg == 0:
            explanation = "non_message_candidates"
        elif msg_tail + msg_bad >= msg:
            explanation = "tail_or_ref_filter"
        else:
            explanation = "no_span"
        # Expected shape is empty (A2 baseline); a non-empty plain episode is
        # the regression signal. The composition explains which consumer
        # filter emptied it, but does not itself turn a correct empty result
        # into a failure.
        okv = bool(oldp.get("empty"))
        add("MEM06-OLDP", "empty (A2 baseline); candidate composition "
            "explains why",
            {"empty": oldp.get("empty"), "hits": oldp.get("hits"),
             "messages": oldp.get("messages"),
             "composition": comp, "message_tail": msg_tail,
             "message_unparseable": msg_bad,
             "episode_max_count": oldp.get("episode_max_count"),
             "explanation": explanation}, okv)

    for aid, alias_key in (("MEM06-P1", "P1"),
                           ("MEM06-P2", "P2_top_author"),
                           ("MEM06-P3", "P3_history_2023_2024")):
        p = (people or {}).get(alias_key) or {}
        if p.get("error"):
            add(aid, "name present, rows=10 all 2026", p, None,
                "probe_error")
            continue
        okv = (bool(p.get("name_present")) and p.get("rows") == 10
               and p.get("row_years") == {"2026": 10})
        add(aid, "name present, rows=10 all 2026",
            {"name_present": p.get("name_present"), "rows": p.get("rows"),
             "row_years": p.get("row_years")}, okv)

    th = thematic or {}
    if th.get("error"):
        add("MEM06-THEMATIC", "mode=thematic, ok, candidates>0; community "
            "contract exercised", th, None, "probe_error")
    else:
        community_expected = bool(th.get("community_gate")
                                  and th.get("community_active"))
        okv = (th.get("mode") == "thematic" and th.get("status") == "ok"
               and int(th.get("candidates") or 0) > 0)
        add("MEM06-THEMATIC", "mode=thematic, ok, candidates>0; community "
            "contract exercised",
            {"mode": th.get("mode"), "status": th.get("status"),
             "channels_used": th.get("channels_used"),
             "candidates": th.get("candidates"),
             "community": th.get("community"),
             "community_channel_used": ("community" in (
                 th.get("channels_used") or ())),
             "community_expected": community_expected}, okv)

    lore = lore or {}
    graph_ok = True
    graph_actual = {}
    dense_ok = True
    dense_actual = {}
    for topic in LORE_TOPICS:
        item = (lore.get(topic) or {})
        if item.get("error"):
            graph_ok = dense_ok = None
            graph_actual[topic] = {"error": item.get("error")}
            dense_actual[topic] = {"error": item.get("error")}
            continue
        graph = item.get("graph") or {}
        rendered = item.get("rendered") or {}
        if not (int(graph.get("nodes") or 0) > 0
                and int(graph.get("edges") or 0) > 0
                and int(rendered.get("graph_lines") or 0) > 0):
            graph_ok = False
        graph_actual[topic] = {
            "nodes": graph.get("nodes"), "edges": graph.get("edges"),
            "facts": graph.get("facts"),
            "graph_lines": rendered.get("graph_lines")}
        dense = item.get("dense") or {}
        pre_years = [y for y in (dense.get("row_years") or {})
                     if y.isdigit() and int(y) < 2024]
        ok_d = (int(dense.get("dialogs") or 0) == 3
                and int(dense.get("rows") or 0) > 0
                and len(dense.get("windows") or ()) == 3
                and len(pre_years) >= 2)
        if not ok_d:
            dense_ok = False
        dense_actual[topic] = {
            "dialogs": dense.get("dialogs"), "rows": dense.get("rows"),
            "windows": len(dense.get("windows") or ()),
            "row_years": dense.get("row_years"),
            "pre_2024_years": sorted(pre_years)}
    add("MEM06-LORE-GRAPH", "both topics: nodes>0, edges>0, "
        "rendered graph_lines>0", graph_actual, graph_ok)
    add("MEM06-LORE-DENSE", "both topics: dialogs=3, rows>0, windows=3, "
        ">=2 pre-2024 years", dense_actual, dense_ok)

    g1 = g1 or {}
    if g1.get("error"):
        add("MEM06-G1-HINTS", "overview hints>0, bundle gets slots, no hint "
            "text in payload, candidates identical", g1, None, "probe_error")
    else:
        okv = (g1.get("overview_present") is True
               and int(g1.get("hints") or 0) > 0
               and int(g1.get("bundle_hints") or 0) > 0
               and not g1.get("leaks")
               and g1.get("candidates_identical") is True)
        add("MEM06-G1-HINTS", "overview hints>0, bundle gets slots, no hint "
            "text in payload, candidates identical",
            {"overview_state": g1.get("overview_state"),
             "hints": g1.get("hints"),
             "bundle_hints": g1.get("bundle_hints"),
             "needles_checked": g1.get("needles_checked"),
             "leaks": g1.get("leaks"),
             "candidates_identical": g1.get("candidates_identical"),
             "payload_chars": g1.get("payload_chars")}, okv)

    g4 = g4 or {}
    if g4.get("error"):
        add("MEM06-G4-REFS", "episode refs are not bundle refs; episode "
            "source ids resolve same-chat sampled=resolved=same_chat",
            g4, None, "probe_error")
    else:
        raw = g4.get("raw") or {}
        sample = g4.get("episode_sample") or {}
        expected_sampled = min(5, int(g4.get("episode_source_ids") or 0))
        okv = (raw.get("bundle") is True
               and int(raw.get("old_episode_refs") or 0) > 0
               and int(raw.get("episode_refs_in_evidence") or 0) == 0
               and int(g4.get("episode_source_ids") or 0) > 0
               and expected_sampled > 0
               and int(sample.get("sampled") or 0) == expected_sampled
               and sample.get("resolved") == expected_sampled
               and sample.get("same_chat") == expected_sampled
               and int(sample.get("unresolved") or 0) == 0)
        add("MEM06-G4-REFS", "episode refs are not bundle refs; episode "
            "source ids resolve same-chat sampled=resolved=same_chat=min(5, "
            "episode_source_ids)",
            {"raw": raw, "episode_source_ids": g4.get(
                "episode_source_ids"), "episode_sample": sample,
             "expected_sampled": expected_sampled,
             "fact_refs": raw.get("fact_refs"),
             "speech_projection": g4.get("speech_projection")}, okv)

    sc = scope or {}
    row_chats: dict = {}
    rows_without_chat_id = 0
    for entry in (classes or {}).values():
        for key, value in (entry.get("row_chat_ids") or {}).items():
            if key in ("None", "no_date"):
                rows_without_chat_id += int(value)
                continue
            row_chats[key] = row_chats.get(key, 0) + int(value)
    for entry in (people or {}).values():
        for key, value in (entry.get("row_chat_ids") or {}).items():
            if key in ("None", "no_date"):
                rows_without_chat_id += int(value)
                continue
            row_chats[key] = row_chats.get(key, 0) + int(value)
    if sc.get("error"):
        add("MEM06-CHAT-SCOPE", "all retrieval rows/refs scoped to chat; "
            "other-chat probe foreign=0", sc, None, "probe_error")
    elif sc.get("other_chat_query_candidates") is None:
        add("MEM06-CHAT-SCOPE", "all retrieval rows/refs scoped to chat; "
            "other-chat probe foreign=0", sc, None, "probe_not_executed")
    else:
        okv = ((not row_chats
                or set(row_chats) == {str(scope.get("chat_id"))})
               and (bool(row_chats)
                    or int(sc.get("other_chat_query_candidates") or 0) > 0
                    or bool(sc.get("source_refs_available")))
               and int(sc.get("other_chat_query_foreign") or 0) == 0
               and int(sc.get("other_chat_message_hits") or 0) == 0
               and int(sc.get("other_chat_message_in_target") or 0) == 0
               and sc.get("other_chat_source_ref") in (False, None)
               and (not sc.get("source_refs_available")
                    or sc.get("same_chat_source_ref") is True))
        add("MEM06-CHAT-SCOPE", "all retrieval rows/refs scoped to chat; "
            "other-chat probe foreign=0",
            {"row_chat_ids": row_chats,
             "rows_without_chat_id": rows_without_chat_id,
             "other_chat_query_candidates": sc.get(
                 "other_chat_query_candidates"),
             "other_chat_query_foreign": sc.get(
                 "other_chat_query_foreign"),
             "other_chat_message_hits": sc.get(
                 "other_chat_message_hits"),
             "other_chat_message_in_target": sc.get(
                 "other_chat_message_in_target"),
             "same_chat_source_ref": sc.get("same_chat_source_ref"),
             "other_chat_source_ref": sc.get("other_chat_source_ref"),
             "source_refs_available": sc.get("source_refs_available")}, okv)

    # Preserve the exact contract order, no missing/extra ids.
    by_id = {item["id"]: item for item in out}
    return [by_id[aid] for aid in ASSERTION_IDS]


# ── output ─────────────────────────────────────────────────────────────────

def harness_files(out_dir_or_root: str, code_root: str) -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    names = ("measure_g2.py", "make_fixture.py", "test_g2_harness_smoke.py",
             "README.md")
    files = {}
    for name in names:
        path = os.path.join(here, name)
        if os.path.exists(path):
            files[name] = sha256_file(path)
    files["_combined"] = hashlib.sha256(
        "".join("%s:%s" % (k, files[k]) for k in sorted(files))
        .encode("utf-8")).hexdigest()
    return files


def _fmt_actual(value) -> str:
    text = json.dumps(value or {}, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 420 else text[:417] + "..."


def write_outputs(out_dir: str, payload: dict, assertions: list,
                  command: str, limitations: list) -> None:
    os.makedirs(out_dir, exist_ok=True)
    payload = dict(payload)
    payload["assertions"] = assertions
    payload["limitations"] = list(limitations)
    with open(os.path.join(out_dir, "g2-mem06.json"), "w",
              encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")

    lines = [
        "# VMQ-MEM-06 — G2 read-only evidence",
        "",
        "- Generated (local): %s" % time.strftime(
            "%Y-%m-%d %H:%M:%S %z", time.localtime()),
        "- Mode: **%s**" % payload.get("mode"),
        "- Command: `%s`" % command,
        "- Candidate SHA: `%s`" % payload.get("candidate_sha"),
        "- Code root HEAD: `%s`" % payload.get("code_root_head"),
        "- Product diff vs candidate: `%s`" % (
            "clean" if payload.get("product_diff_clean") else "DRIFT"),
        "- Snapshot SHA-256: `%s`" % payload.get("snapshot_sha256"),
        "- Snapshot quick_check: `%s`; user_version: `%s`" % (
            (payload.get("snapshot") or {}).get("quick_check"),
            (payload.get("snapshot") or {}).get("user_version")),
        "- Chat: `%s`" % payload.get("chat_id"),
        "- Environment: Python `%s`; sqlite-vec `%s`; "
        "sqlite_vec_loaded=`%s`; off_reason=`%s`; vec_ok=`%s`" % (
            (payload.get("environment") or {}).get("python_version"),
            (payload.get("environment") or {}).get("sqlite_vec_version"),
            (payload.get("environment") or {}).get("sqlite_vec_loaded"),
            (payload.get("environment") or {}).get("sqlite_vec_off_reason"),
            (payload.get("environment") or {}).get("vec_ok")),
        "- Effective gates: `%s`" % json.dumps(
            payload.get("configuration") or {}, ensure_ascii=False,
            sort_keys=True),
        "- Topics: %s" % ", ".join(
            "`%s`" % topic for topic in payload.get("topics") or ()),
        "- Tables: `%s`" % json.dumps(
            (payload.get("snapshot") or {}).get("tables") or {},
            ensure_ascii=False, sort_keys=True),
        "",
        "## Assertions",
        "",
        "| ID | Status | Expected | Actual (counts/hashes only) |",
        "|---|---|---|---|",
    ]
    for item in assertions:
        lines.append("| `%s` | **%s** | %s | `%s` |" % (
            item["id"], item["status"],
            str(item.get("expected") or "").replace("|", "\\|"),
            _fmt_actual(item.get("actual")).replace("|", "\\|")))
    lines += ["", "## Limitations", ""]
    if limitations:
        lines += ["- %s" % item for item in limitations]
    else:
        lines.append("- none recorded")
    lines += [
        "",
        "## Notes",
        "",
        "- Text of messages/facts is not written; only ids/counts/years/"
        "timestamps/hashes.",
        "- The harness opens the snapshot with SQLite `mode=ro`; the hash "
        "before/after is recorded in `g2-mem06-hashes.txt`.",
        "- If not all assertions are `pass`, MEM-06 stays PENDING.",
        "",
    ]
    with open(os.path.join(out_dir, "g2-mem06-summary.md"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    hashes = [
        "# VMQ-MEM-06 G2 hashes",
        "snapshot_sha256=%s" % (payload.get("snapshot_sha256") or
                                "unavailable"),
        "snapshot_sha256_after=%s" % (
            payload.get("snapshot_sha256_after") or "unavailable"),
        "snapshot_path=%s" % ((payload.get("snapshot") or {}).get("path")),
        "snapshot_bytes=%s" % ((payload.get("snapshot") or {}).get("bytes")),
        "candidate_sha=%s" % payload.get("candidate_sha"),
        "code_root_head=%s" % payload.get("code_root_head"),
        "harness_combined_sha256=%s" % (
            (payload.get("harness") or {}).get("_combined")),
    ]
    for name, digest in sorted((payload.get("harness") or {}).items()):
        if name == "_combined":
            continue
        hashes.append("harness_%s=%s" % (name, digest))
    with open(os.path.join(out_dir, "g2-mem06-hashes.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(hashes) + "\n")


def base_payload(args, snapshot_meta, code_root, candidate, harness) -> dict:
    return {
        "schema": "vmq-mem06-g2/1",
        "mode": "fixture" if args.fixture else "snapshot",
        "generated_at": int(time.time()),
        "candidate_sha": candidate,
        "code_root": code_root,
        "code_root_head": None,
        "product_diff_clean": None,
        "chat_id": args.chat_id,
        "snapshot": snapshot_meta,
        "snapshot_sha256": (sha256_file(args.db)
                            if args.db and os.path.exists(args.db) else None),
        "snapshot_sha256_after": None,
        "harness": harness,
        "environment": environment_info(),
        "topics": list(LORE_TOPICS),
        "configuration": {},
        "tables": snapshot_meta.get("tables") or {},
        "classes": {},
        "old_episode": {},
        "people": {},
        "thematic": {},
        "lore": {},
        "g1": {},
        "g4": {},
        "chat_scope": {},
        "assertions": [],
        "limitations": [],
    }


def publish_not_executed(args, reason: str, code_root: str = "",
                         candidate: str = CANDIDATE) -> int:
    harness = harness_files(args.out, code_root)
    meta = db_meta(args.db) if args.db else {
        "path": args.db, "exists": False, "tables": {}}
    payload = base_payload(args, meta, code_root, candidate, harness)
    payload["technical_reason"] = reason
    limitations = ["Run not executed: %s" % reason]
    if args.fixture:
        limitations.append("Fixture mode: never production evidence.")
    assertions = [assertion(aid, "see architect-mem06-decision.md §5",
                            {"reason": reason}, "not_executed")
                  for aid in ASSERTION_IDS]
    write_outputs(args.out, payload, assertions,
                  " ".join(sys.argv), limitations)
    return 2 if reason.startswith("snapshot_") else 4


# ── main run ───────────────────────────────────────────────────────────────

async def run(args, snapshot_meta=None) -> tuple[dict, list, list, int]:
    from services import hot_config as hot
    from services import mca_retrieval_context as mrc
    from services import mca_gates
    from services.database import DatabaseService
    from services.direct_chat_service import DirectChatService
    from services.lore_compiler_service import LoreCompilerService
    from services.summary_memory import MemoryManager

    hot.set_config_cache(_Cache())
    db = DatabaseService(args.db)
    await db.initialize_readonly()
    try:
        memory = MemoryManager(db, StubLLM(), aliases=None)

        async def _noop():
            return 0

        # §5.1: sqlite-vec loaded, failing LLM/embed stub, no backfill writes.
        # `initialize()` loads the extension and returns before DDL because
        # the stub embed probe fails; the read-only snapshot is never written.
        memory.backfill_archive_vectors = _noop
        memory.backfill_graph_fact_vectors = _noop
        vec_error = None
        try:
            vec_ok = bool(await asyncio.wait_for(memory.initialize(), 120))
        except Exception as exc:                            # noqa: BLE001
            vec_ok = False
            vec_error = type(exc).__name__
        vec_off_reason = getattr(memory, "_vec_off_reason", None)
        vec = {
            "vec_ok": vec_ok,
            "vec_dim": getattr(memory, "_vec_dim", None),
            "sqlite_vec_off_reason": vec_off_reason,
            # "embed" = extension loaded, stub embed probe failed (expected);
            # "extension" = sqlite-vec could not be loaded (environment gap).
            "sqlite_vec_loaded": bool(vec_ok or vec_off_reason == "embed"),
            "vec_error": vec_error,
        }
        svc = DirectChatService(memory, db, StubLLM(), StubAliases())
        stub = SimpleNamespace(text="", chat_id=args.chat_id, message_id=0)
        tail = await db.get_recent_messages(args.chat_id, 40)

        classes = {}
        for key, query, extra in QUERIES:
            classes[key] = await class_probe(
                svc, mrc, db, args.chat_id, stub, tail, key, query, extra,
                with_writer=True)

        old_episodes = {}
        for key, query in (("Old_Episode_2023", D_QUERY),
                           ("Old_Episode_plain", A1P_QUERY)):
            old_episodes[key] = await old_episode_probe(
                svc, mrc, db, args.chat_id, stub, tail, key, query)

        people = {}
        for alias, uid in PEOPLE:
            people[alias] = await person_probe(
                svc, mrc, db, args.chat_id, stub, alias, uid)

        cur = await db.db.execute(
            "SELECT COUNT(*) AS n FROM mca_community_builds WHERE chat_id=? "
            "AND status='active'", (args.chat_id,))
        row = await cur.fetchone()
        active_builds = int(row["n"] if row is not None else 0)
        gates = {
            "retrieval_context": bool(mca_gates.retrieval_context_enabled()),
            "evidence_bundle": bool(mca_gates.evidence_bundle_enabled()),
            "typed_reranker": bool(mca_gates.typed_reranker_enabled()),
            "memory_communities": bool(
                await mca_gates.memory_communities_enabled(args.chat_id)),
            "episodes": bool(mca_gates.episodes_enabled()),
            "canonical_attribution": bool(
                mca_gates.canonical_attribution_enabled()),
            "event_contract": bool(mca_gates.event_contract_enabled()),
            "telemetry_store": bool(mca_gates.telemetry_store_enabled()),
            "provenance": bool(mca_gates.provenance_enabled()),
            "community_builds": ((snapshot_meta or {}).get("tables", {})
                                 .get("mca_community_builds")),
            "community_active": active_builds,
            "sqlite_vec_loaded": vec["sqlite_vec_loaded"],
            "sqlite_vec_off_reason": vec["sqlite_vec_off_reason"],
            "vec_ok": vec["vec_ok"],
            "vec_dim": vec["vec_dim"],
        }
        from services.canonical_context import speech_projection_enabled
        gates["speech_projection"] = bool(speech_projection_enabled())

        thematic = await thematic_probe(mrc, db, memory, args.chat_id, gates)
        g1 = await g1_probe(svc, mrc, db, args.chat_id, stub)
        g4 = await g4_probe(svc, mrc, db, args.chat_id, stub, tail)
        lore = {}
        for topic in LORE_TOPICS:
            lore[topic] = await lore_probe(db, args.chat_id, topic)
        if getattr(args, "other_chat", None) is None:
            cur = await db.db.execute(
                "SELECT chat_id FROM smart_messages WHERE chat_id != ? "
                "ORDER BY chat_id LIMIT 1", (args.chat_id,))
            row = await cur.fetchone()
            if row is not None:
                args.other_chat = int(row["chat_id"])
        scope = await chat_scope_probe(
            mrc, db, memory, args.chat_id, getattr(args, "other_chat", None))

        assertions = evaluate(classes, old_episodes, people, thematic, lore,
                               g1, g4, scope)
        payload = {
            "classes": classes,
            "old_episode": {k: {kk: vv for kk, vv in v.items()
                                if kk != "source_ids"}
                            for k, v in old_episodes.items()},
            "people": people,
            "thematic": thematic,
            "lore": lore,
            "g1": g1,
            "g4": g4,
            "chat_scope": scope,
            "configuration": gates,
            "vec": vec,
        }
        return payload, assertions, [], 0
    finally:
        try:
            await db.close()
        except Exception:
            pass


async def async_main(args, code_root: str, candidate: str,
                     head: str) -> int:
    harness = harness_files(args.out, code_root)
    meta = db_meta(args.db)
    payload = base_payload(args, meta, code_root, candidate, harness)
    payload["code_root_head"] = head
    rc, diff = git_out(code_root, "diff", "--stat", candidate, "--",
                       "services", "handlers", "web/api", "web/static",
                       "config")
    rc_status, status = git_out(code_root, "status", "--porcelain", "--",
                                "services", "handlers", "web/api",
                                "web/static", "config")
    clean = (rc == 0 and not diff and rc_status == 0 and not status)
    payload["product_diff_clean"] = clean
    if not clean and not args.fixture:
        reason = "product_diff_vs_candidate"
        payload["technical_reason"] = reason
        assertions = [assertion(
            aid, "see architect-mem06-decision.md §5",
            {"reason": reason, "product_diff_clean": False},
            "not_executed") for aid in ASSERTION_IDS]
        limitations = [
            "Run not executed: product code differs from candidate %s"
            % candidate,
            "git diff --stat output: %s" % (diff[:400] or "n/a"),
            "git status output: %s" % (status[:400] or "clean"),
        ]
        if args.fixture:
            limitations.append("Fixture mode: never production evidence.")
        write_outputs(args.out, payload, assertions,
                      " ".join(sys.argv), limitations)
        return 2

    if meta.get("quick_check") != "ok":
        payload["technical_reason"] = "snapshot_quick_check_%s" % (
            meta.get("quick_check"))
        assertions = [assertion(
            aid, "see architect-mem06-decision.md §5",
            {"reason": payload["technical_reason"]}, "not_executed")
            for aid in ASSERTION_IDS]
        write_outputs(args.out, payload, assertions, " ".join(sys.argv),
                      ["Run not executed: snapshot quick_check=%s"
                       % meta.get("quick_check")])
        return 2

    try:
        probe, assertions, _, _ = await run(args, meta)
    except Exception as exc:                                # noqa: BLE001
        payload["technical_reason"] = "probe_failed:%s" % type(exc).__name__
        assertions = [assertion(
            aid, "see architect-mem06-decision.md §5",
            {"reason": payload["technical_reason"]}, "not_executed")
            for aid in ASSERTION_IDS]
        write_outputs(args.out, payload, assertions, " ".join(sys.argv),
                      ["Run not executed: %s"
                       % payload["technical_reason"]])
        return 4
    vec = dict(probe.pop("vec", {}) or {})
    payload.update(probe)
    environment = dict(payload.get("environment") or {})
    environment.update(vec)
    payload["environment"] = environment
    payload["snapshot_sha256_after"] = (
        sha256_file(args.db) if os.path.exists(args.db) else None)
    limitations = []
    if args.fixture:
        limitations.append(
            "Fixture mode: synthetic SQLite; NOT production evidence. "
            "MEM-06 cannot be closed from this run.")
    if not str(environment.get("python_version") or "").startswith("3.12"):
        limitations.append(
            "Python %s != contract 3.12 (§5.1)."
            % (environment.get("python_version") or "unknown"))
    if environment.get("sqlite_vec_loaded") is not True:
        limitations.append(
            "sqlite-vec not loaded (off_reason=%s); §5.1 environment not met."
            % (environment.get("sqlite_vec_off_reason") or "unknown"))
    else:
        limitations.append(
            "sqlite-vec loaded; probe embed failed as designed "
            "(off_reason=%s, vec_ok=%s)."
            % (environment.get("sqlite_vec_off_reason"),
               environment.get("vec_ok")))
    if payload["snapshot_sha256"] != payload["snapshot_sha256_after"]:
        limitations.append(
            "Read-only violation: snapshot sha256 changed during the run.")
        for item in assertions:
            item["status"] = "not_executed"
            item["actual"] = dict(item.get("actual") or {})
            item["actual"]["reason"] = "read_only_violation"
        write_outputs(args.out, payload, assertions, " ".join(sys.argv),
                      limitations)
        return 3
    vector_legs = sorted({
        str((c.get("period") or {}).get("vector_leg") or "")
        for c in (payload.get("classes") or {}).values()})
    limitations += [
        "Embedding/LLM clients are failing stubs by contract; no HTTP client "
        "is constructed; vector leg reported as %s (not a semantic-retrieval "
        "claim). OS-level egress was not separately blocked."
        % ("," .join(x for x in vector_legs if x) or "not_recorded"),
        "Snapshot DB is opened read-only; product write paths (TTL touch, "
        "embedding_cache/quota, mcа_events telemetry) fail with "
        "OperationalError and are logged; the before/after sha256 proves the "
        "file is unchanged and selection is unaffected.",
        "`_build_old_episodes` keeps its local `skipped` dict; only "
        "candidate_composition is recorded (L6 precision note §2).",
        "`selected_refs` is reconstructed as current+branch+evidence "
        "(EvidenceBundle does not expose the list).",
        "Typed semantic hints have no text/label fields; the payload check "
        "uses the rendered bundle semantic-hint slots as needles.",
        "No chat timezone is read for Lore date rendering; default UTC.",
    ]
    write_outputs(args.out, payload, assertions, " ".join(sys.argv),
                  limitations)
    statuses = [item["status"] for item in assertions]
    if all(s == "pass" for s in statuses):
        return 0
    if any(s == "fail" for s in statuses):
        return 1
    return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="VMQ-MEM-06 G2 read-only evidence harness")
    parser.add_argument("--db", default=None,
                        help="consistent SQLite snapshot (opened mode=ro)")
    parser.add_argument("--chat-id", type=int, default=CHAT)
    parser.add_argument("--out", required=True,
                        help="output directory for g2-mem06.*")
    parser.add_argument("--code-root", default=os.environ.get("VMQ_CLONE")
                        or os.getcwd())
    parser.add_argument("--other-chat", type=int, default=None,
                        help="optional other chat id for the scope probe")
    parser.add_argument("--expected-candidate", default=CANDIDATE)
    parser.add_argument("--fixture", action="store_true",
                        help="build a synthetic fixture DB and run on it")
    parser.add_argument("--dry-run", action="store_true",
                        help="print resolved configuration, no probes")
    args = parser.parse_args(argv)
    code_root = os.path.abspath(args.code_root)
    if not os.path.isdir(os.path.join(code_root, "services")):
        print("CODE_ROOT_INVALID", code_root)
        return 4
    args.out = os.path.abspath(args.out)
    os.makedirs(args.out, exist_ok=True)
    if args.dry_run:
        meta = db_meta(args.db) if args.db else {"exists": False}
        rc, head = git_out(code_root, "rev-parse", "HEAD")
        print(json.dumps({
            "mode": "fixture" if args.fixture else "snapshot",
            "code_root": code_root,
            "code_root_head": head if rc == 0 else None,
            "candidate": args.expected_candidate,
            "chat_id": args.chat_id,
            "db": args.db,
            "db_exists": bool(meta.get("exists")),
            "db_bytes": meta.get("bytes"),
            "quick_check": meta.get("quick_check"),
            "user_version": meta.get("user_version"),
            "out": args.out,
            "assertions": list(ASSERTION_IDS),
        }, ensure_ascii=False, indent=2))
        return 0

    temp_dir = None
    if args.fixture and not args.db:
        temp_dir = tempfile.mkdtemp(prefix="vmq-g2-fixture-")
        args.db = os.path.join(temp_dir, "fixture.db")
        sys.path.insert(0, code_root)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        os.chdir(code_root)
        from make_fixture import build_fixture
        asyncio.run(build_fixture(args.db, chat_id=args.chat_id))
        if args.other_chat is None:
            args.other_chat = -1009999999999
    if args.db:
        args.db = os.path.abspath(args.db)
    if not args.db or not os.path.exists(args.db):
        return publish_not_executed(
            args, "snapshot_missing", code_root, args.expected_candidate)

    sys.path.insert(0, code_root)
    os.chdir(code_root)
    rc, head = git_out(code_root, "rev-parse", "HEAD")
    head = head if rc == 0 else ""
    rc2, resolved = git_out(code_root, "rev-parse", "--verify",
                            args.expected_candidate + "^{commit}")
    candidate = resolved if rc2 == 0 else args.expected_candidate
    try:
        return asyncio.run(async_main(args, code_root, candidate, head))
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
