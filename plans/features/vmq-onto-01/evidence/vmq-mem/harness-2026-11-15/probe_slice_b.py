# -*- coding: utf-8 -*-
"""VMQ-MEM / VMQ-MEM-TIME Slice B evidence probe (read-only).

Runs ON the production host against a CANDIDATE/BASELINE checkout clone and a
COPY of local_database.db. Never writes live data, never restarts a unit, never
sends a message, never commits.

Method: the committed Slice A probe (`probe_slice_a.py`) is reused verbatim for
the retrieval/Writer/Old_Episode measurement; this file adds ONLY the Slice B
invocation surface:

  * `A1` owner formulation with the bounded historical quota (row years,
    per-row keep reason, id -> SQL year cross-check);
  * `T2` event-without-a-year through a REAL `L1Plan(response_act=
    "historical_recall")` and the real `_apply_plan_memory_scope()` seam, plus
    the no-signal control;
  * `T3` current-state control (no signal = required; with signal = advisory);
  * P1 profile: real tool envelope (`subject_material`, subject refs, years),
    reply path (`subject_name/subject_uid`), and the exact SQL rows of the two
    new read-only readers;
  * relationships: raw `retrieve(purpose="relationships")` projection and the
    tool envelope `temporal_projection`, with every delivered edge/fact ref
    checked against the copy (`invented=0` by construction, verified by SQL);
  * `<Old_Episode>` for an explicit 2023 question (year window + block years).

Absent Slice B API on the baseline is reported as `absent`/`unsupported`, never
simulated. Text of facts/messages is never stored: only ids, years, refs,
counts and length.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import re
import sqlite3
import sys
import time
import traceback
from types import SimpleNamespace

VARIANT = os.environ.get("VMQ_VARIANT", "base")
CLONE = os.environ.get("VMQ_CLONE", "/root/vmqB/measure/repo-base")
DBPATH = os.environ.get("VMQ_DB", "/root/vmqB/measure/dbcopy.db")
OUT = os.environ.get("VMQ_OUT", "/root/vmqB/measure/out/base.json")
ENT = os.environ.get("VMQ_ENT", "/root/vmqB/measure/entities.json")
CFG = os.environ.get("VMQ_CFG", "/root/vmqB/measure/cfg.json")
SQLCACHE = os.environ.get("VMQ_SQLCACHE", "")
APP = "/var/www/admin_bot"
LIVE_DB = "/var/www/admin_bot/local_database.db"
CHAT = -1002661910336

sys.path.insert(0, CLONE)
os.chdir(APP)                      # load_dotenv() parity with the service

logging.basicConfig(level=logging.ERROR,
                    format="%(levelname)s %(name)s: %(message)s")

import services  # noqa: E402
from config.settings import settings  # noqa: E402
from services import hot_config as hot  # noqa: E402
from services import mca_retrieval_context as mca  # noqa: E402
from services import direct_context_composer as composer  # noqa: E402
from services.database import DatabaseService  # noqa: E402
from services.direct_chat_service import DirectChatService  # noqa: E402
from services.llm_client import LLMClient  # noqa: E402
from services.summary_memory import MemoryManager  # noqa: E402
from services.tool_router import ToolContext, ToolDeps, ToolRouter  # noqa: E402

Y2023 = (1672531200, 1704067199)
Y2024 = (1704067200, 1735689599)
Y2026 = (1767225600, 1798761599)
ISO = re.compile(r"\b(20\d{2})-\d{2}-\d{2}\b|\b\d{2}\.\d{2}\.(20\d{2})")

# ── formulation classes: frozen before the run, identical for A and B ────────
CREATIVE_OWNER = "напиши юмористический рассказ об основных шизах конфы"
PLAIN_TWIN = "что за шизы были на конфе?"
CONFLICT_2023 = "из-за чего мы ссорились и ругались в 2023 году"
RELATIONS = "как менялись наши отношения и взгляды за эти годы"

# deterministic relevance predicates (documented in the report, no LLM judge)
TOPIC_SHIZ = ("шиз",)
TOPIC_CONF = ("конф",)
CONFLICT_MARK = ("ссор", "ругал", "скандал", "конфликт", "послал", "обид",
                 "спор")
RELATION_MARK = ("отнош", "друж", "общени", "взгляд", "мнени")
WATCH = ("services/mca_retrieval_context.py",
         "services/direct_chat_service.py",
         "services/database.py",
         "services/summary_memory.py",
         "services/tool_router.py",
         "services/direct_context_composer.py",
         "services/mca_episodes.py")


def _accepts(fn, name) -> bool:
    """True only when the callable really declares that keyword."""
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _live_registry_snapshot() -> dict:
    """Read-only snapshot of the LIVE embedding-generation registry.

    Only `SELECT` on `mca_embedding_index_generations` with a read-only
    connection. Not a live compatibility canary and it does not make any
    vector leg participate.
    """
    out: dict = {"readonly": True, "path": "live local_database.db"}
    try:
        from services import embedding_control_plane as ecp
    except Exception as exc:                            # noqa: BLE001
        out["error"] = "import:%s" % type(exc).__name__
        return out
    try:
        con = sqlite3.connect("file:%s?mode=ro" % LIVE_DB, uri=True, timeout=8)
    except Exception as exc:                            # noqa: BLE001
        out["error"] = "connect:%s" % type(exc).__name__
        return out
    try:
        con.execute("PRAGMA query_only=1")
        rows = [dict(row) for row in con.execute(
            "SELECT generation, status, dims, model, preprocessing_version, "
            "fingerprint, config_revision, namespace, index_name "
            "FROM mca_embedding_index_generations "
            "WHERE index_name=? AND namespace=? "
            "ORDER BY generation DESC LIMIT 8", ("graph_facts_vec", "default"))]
    except Exception as exc:                            # noqa: BLE001
        out["error"] = "select:%s" % type(exc).__name__
        return out
    finally:
        con.close()
    try:
        dims = next((int(row.get("dims")) for row in rows
                     if row.get("dims")), None)
        space_now = (ecp.model_space_identity(
            model=ecp._current_model(), dimension=dims) if dims else "")
        conn_now = ecp._current_conn()
    except Exception:                                   # noqa: BLE001
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
        } for row in rows[:8]],
        "active_present": active is not None,
        "space_now": space_now,
        "conn_now": conn_now,
        "active_admission_valid_for_current_msi_pci": bool(
            admission and ecp.admission_valid(
                admission, space_now=space_now, conn_now=conn_now)),
    })
    return out


class Redactor:
    def __init__(self, entities: dict):
        person = (entities.get("person") or {})
        event = (entities.get("event") or {})
        self.map = []
        for real, alias in ((person.get("name"), "P1"),
                            ((event or {}).get("token"), "E1")):
            if real and len(str(real)) > 1:
                self.map.append((str(real), alias))

    def __call__(self, value):
        text = str(value)
        for real, alias in self.map:
            text = re.sub(re.escape(real), alias, text, flags=re.IGNORECASE)
        return text


def year_of(ts):
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return time.gmtime(ts).tm_year


def hist(values) -> dict:
    out: dict[str, int] = {}
    for value in values:
        key = str(value) if value else "no_date"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def block_years(text: str, redact) -> dict:
    out: dict[str, int] = {}
    for match in ISO.finditer(redact(text or "")):
        year = match.group(1) or match.group(2)
        if year:
            out[year] = out.get(year, 0) + 1
    return dict(sorted(out.items()))


def stems_hit(text: str, stems) -> bool:
    low = str(text or "").casefold()
    return any(stem in low for stem in stems)


def _period_intent_view(intent) -> dict | None:
    if intent is None:
        return None
    out = {}
    for key in ("kind", "years", "source"):
        value = getattr(intent, key, None)
        if value is None:
            continue
        if isinstance(value, tuple):
            value = list(value)
        out[key] = value
    return out or {"raw": str(intent)[:120]}


def _row_brief(row) -> dict:
    """Bounded per-row view: ids/years/reasons/refs only, never fact text."""
    def _int_id(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return {
        "id": _int_id((row or {}).get("id")),
        "year": year_of((row or {}).get("rag_ts")
                        or (row or {}).get("message_timestamp")
                        or (row or {}).get("created_at")),
        "origin": (row or {}).get("origin"),
        "period_source": (row or {}).get("period_source"),
        "period_fill": bool((row or {}).get("period_fill")),
        "proxy": (row or {}).get("subject_proxy"),
        "stems_shared": (row or {}).get("stems_shared"),
        "stems_reason": (row or {}).get("stems_shared_reason"),
        "unattributed": bool((row or {}).get("unattributed")),
        # Slice B subject role (absent on the baseline).
        "subject_role": (row or {}).get("subject_role"),
        "authored_by_subject": bool(
            (row or {}).get("authored_by_subject")),
    }


def _request_view(request) -> dict:
    keys = ("chat_id", "query", "mode", "purpose", "top_k", "channels",
            "scope", "include_overview", "memory_scope", "period_fill",
            "exclude_years", "include_archived", "preserve_channel_order",
            "intent", "subject_names", "subject_entity_ids", "time_from",
            "time_to", "lexical_time_window")
    out = {}
    for key in keys:
        value = getattr(request, key, "<none>")
        if key == "query":
            continue
        if isinstance(value, tuple):
            value = list(value)
        out[key] = value
    out["period_intent"] = _period_intent_view(
        getattr(request, "period_intent", None))
    return out


def _relation_view(item) -> dict:
    return {
        "edge_id": item.get("edge_id"),
        "fact_id": item.get("fact_id"),
        "origin": item.get("origin"),
        "unsupported": bool(item.get("has_unsupported_sources")),
        "ts": item.get("ts"),
        "year": item.get("year") if item.get("year") is not None
                else year_of(item.get("ts")),
        "direction": item.get("direction"),
        "weight": item.get("weight"),
        "legacy_ids": list(item.get("legacy_ids") or ()),
    }


def _result_view(result, redact, entities) -> dict:
    cands = list(getattr(result, "candidates", ()) or ())
    by_type: dict[str, int] = {}
    for cand in cands:
        by_type[cand.entity_type] = by_type.get(cand.entity_type, 0) + 1
    facts = list(getattr(result, "fact_rows", ()) or ())
    relations = list(getattr(result, "relations", ()) or ())
    relevance = getattr(result, "relevance", None)
    overview = getattr(result, "overview", None)
    rows = []
    for cand in cands[:24]:
        rows.append({
            "id": str(cand.id),
            "type": cand.entity_type,
            "channel": cand.channel,
            "year": year_of(cand.sent_at),
            "score": round(float(cand.score or 0), 2),
        })
    fact_years = [year_of((row or {}).get("rag_ts")
                          or (row or {}).get("message_timestamp"))
                  for row in facts]
    out = {
        "status": getattr(result, "status", None),
        "reason_code": getattr(result, "reason_code", None),
        "mode": getattr(result, "mode", None),
        "purpose": getattr(result, "purpose", None),
        "channels_used": list(getattr(result, "channels_used", ()) or ()),
        "candidates": len(cands),
        "by_type": by_type,
        "candidate_years": hist([year_of(c.sent_at) for c in cands]),
        "top": rows,
        "fact_rows": len(facts),
        "fact_years": hist(fact_years),
        "fact_rows_meta": [{
            "year": year_of((row or {}).get("rag_ts")
                            or (row or {}).get("message_timestamp")),
            "origin": (row or {}).get("origin"),
            "period_fill": bool((row or {}).get("period_fill")),
            "proxy": (row or {}).get("subject_proxy"),
            "attributed": not bool((row or {}).get("unattributed")),
            "subject_role": (row or {}).get("subject_role"),
            "chars": len(str((row or {}).get("fact") or "")),
        } for row in facts[:24]],
        "period_fill": getattr(result, "period_fill", None),
        "relevance": (None if relevance is None else {
            "use_memory": getattr(relevance, "use_memory", None),
            "reason_code": getattr(relevance, "reason_code", None),
            "matched_subject": getattr(relevance, "matched_subject", None),
            "dropped": len(getattr(relevance, "dropped", ()) or ()),
        }),
        "relations": len(relations),
        "relations_meta": [_relation_view(item) for item in relations[:20]],
        "fact_ids": [str((row or {}).get("id")) for row in facts[:40]
                     if (row or {}).get("id") is not None],
        "fact_rows_detail": [_row_brief(row) for row in facts[:40]],
    }
    if overview is not None:
        try:
            data = overview.as_dict()
        except Exception:              # noqa: BLE001
            data = {}
        coverage = data.get("coverage") or {}
        out["overview"] = {
            "state": data.get("state"),
            "subject_present": bool(data.get("subject_id")),
            "present_periods": [block.get("period") for block in
                                coverage.get("present_periods") or ()],
            "missing_periods": coverage.get("missing_periods"),
            "complete": coverage.get("complete"),
            "earliest": coverage.get("earliest_ts"),
            "latest": coverage.get("latest_ts"),
            "independent_periods": data.get("independent_periods"),
            "episode_refs": len(data.get("episode_refs") or ()),
            "support_source_refs": len(data.get("support_source_refs") or ()),
            "independent_support_count": data.get("independent_support_count"),
            "repeated_claims": data.get("repeated_claims"),
            "counterexamples": len(data.get("counterexamples") or ()),
            "limitations": data.get("limitations"),
            "period_support": len(data.get("period_support") or ()),
        }
    return out


class RetrieveSpy:
    def __init__(self, redact, entities):
        self.calls = []
        self._orig = None
        self._redact = redact
        self._entities = entities

    def __enter__(self):
        self._orig = mca.retrieve
        spy = self

        async def wrapper(db, memory, request):
            started = time.monotonic()
            out = await spy._orig(db, memory, request)
            spy.calls.append({
                "seconds": round(time.monotonic() - started, 2),
                "request": _request_view(request),
                "result": _result_view(out, spy._redact, spy._entities),
            })
            return out

        mca.retrieve = wrapper
        return self

    def __exit__(self, *exc):
        mca.retrieve = self._orig
        return False


async def _aliases_or_stub():
    try:
        from services.summary_aliases import build_alias_resolver
        got = await build_alias_resolver(CHAT)
        if got is not None and hasattr(got, "resolve"):
            return got, "real"
    except Exception:                  # noqa: BLE001
        pass

    class _Stub:
        def resolve(self, user_id, nickname=None, username=None,
                    memory_name=None):
            return str(nickname or username or memory_name or user_id or "")

    return _Stub(), "stub"


def _profile_view(raw: str, redact, entities) -> dict:
    payload = {}
    try:
        payload = json.loads(raw or "{}")
    except Exception:                  # noqa: BLE001
        payload = {}
    facts = payload.get("facts") or []
    sources = payload.get("sources") or []
    person_uid = str(((entities.get("person") or {}).get("uid")) or "")
    years = []
    detail = []
    for fact in facts:
        year = None
        if isinstance(fact, dict):
            for key in ("ts", "time", "date", "sent_at", "created_at"):
                year = year_of(fact.get(key))
                if year:
                    break
            if not year and fact.get("as_of_year"):
                try:
                    year = int(fact["as_of_year"])
                except (TypeError, ValueError):
                    year = None
            if not year:
                match = ISO.search(json.dumps(fact, ensure_ascii=False))
                if match:
                    year = int(match.group(1) or match.group(2))
            detail.append({
                "source_id": str(fact.get("source_id") or ""),
                "year": year,
                "subject_ref_id": fact.get("subject_ref_id"),
                "speaker_author_id": fact.get("speaker_author_id"),
                "target_is_p1": str(fact.get("target_user") or "")
                                in {person_uid, "P1"},
                "subject_role": fact.get("subject_role"),
                "attributed": not bool(fact.get("unattributed")),
                "chars": len(str(fact.get("text") or "")),
            })
        years.append(year)
    return {
        "chars": len(raw or ""),
        "status": payload.get("status"),
        "no_data": payload.get("no_data"),
        "empty_reason": payload.get("empty_reason"),
        "envelope_keys": sorted(payload.keys()),
        "facts": len(facts),
        "fact_years": hist(years),
        "distinct_years": len({y for y in years if y}),
        "facts_detail": detail[:24],
        "sources": len(sources),
        "sources_detail": [{
            "kind": str((src or {}).get("kind") or ""),
            "ref": str((src or {}).get("ref") or "")[:48],
            "year": (src or {}).get("year"),
            "subject_ref_id": (src or {}).get("subject_ref_id"),
            "speaker_author_id": (src or {}).get("speaker_author_id"),
            "subject_role": (src or {}).get("subject_role"),
        } for src in sources[:24]],
        "subject_material": payload.get("subject_material"),
        "temporal_projection": payload.get("temporal_projection"),
        "coverage_lines": [redact(line)[:120] for line
                           in (payload.get("coverage") or ())][:6],
        "limitations": [str(code) for code
                        in (payload.get("limitations") or ())][:8],
    }


def _dig_view(raw: str) -> dict:
    try:
        payload = json.loads(raw or "{}")
    except Exception:                  # noqa: BLE001
        payload = {}
    coverage = payload.get("coverage") or {}
    return {
        "status": payload.get("status"),
        "coverage": coverage if isinstance(coverage, dict) else {},
        "messages_total": coverage.get("messages_total")
                          if isinstance(coverage, dict) else None,
        "messages_shown": coverage.get("messages_shown")
                          if isinstance(coverage, dict) else None,
        "first_seen": coverage.get("first_seen")
                      if isinstance(coverage, dict) else None,
        "last_seen": coverage.get("last_seen")
                     if isinstance(coverage, dict) else None,
        "snippets": len(payload.get("snippets") or ()),
        "facts": len(payload.get("facts") or ()),
    }


async def measure_query(db, memory, svc, router, key, query, tail, redact,
                        entities, *, memory_scope=None, plan_act=None,
                        subject=None) -> dict:
    """One real `<RAG_Memory>` build (+ real `<Old_Episode>`)."""
    started = time.monotonic()
    out: dict = {"class": key, "query": redact(query),
                 "plan_act": plan_act,
                 "subject_bound_call": bool(subject)}
    stub = SimpleNamespace(text=query, chat_id=CHAT, message_id=0)
    captured: dict = {}
    orig_rows = svc._rag_unified_rows

    async def rows_spy(*args, **kwargs):
        got = await orig_rows(*args, **kwargs)
        captured["rows"] = got
        captured["period_stats"] = dict(
            getattr(svc, "_rag_period_stats", None) or {})
        captured["memory_scope"] = kwargs.get("memory_scope")
        captured["plan_act"] = kwargs.get("plan_act")
        return got

    svc._rag_unified_rows = rows_spy
    kwargs = {"memory_scope": memory_scope}
    if plan_act is not None:
        if _accepts(svc._build_rag_block, "plan_act"):
            kwargs["plan_act"] = plan_act
            out["plan_act_forwarded"] = True
        else:
            out["plan_act_forwarded"] = False
    if subject:
        kwargs["subject_name"] = subject[0]
        kwargs["subject_uid"] = subject[1]
    with RetrieveSpy(redact, entities) as spy:
        try:
            block, hint = await asyncio.wait_for(
                svc._build_rag_block(CHAT, stub, "", **kwargs), 300)
        except Exception as exc:       # noqa: BLE001
            out["rag_error"] = {"error": type(exc).__name__,
                                "text": str(exc)[:300],
                                "tb": traceback.format_exc()[-600:]}
            block, hint = "", ""
    svc._rag_unified_rows = orig_rows
    rows = captured.get("rows")
    out["rag"] = {
        "seconds": round(time.monotonic() - started, 2),
        "block_chars": len(block or ""),
        "block_lines": len([line for line in (block or "").splitlines()
                            if line.strip()]),
        "block_years": block_years(block or "", redact),
        "hint": bool(hint),
        "rows": (None if rows is None else len(rows)),
        "row_years": (None if rows is None else hist(
            [year_of((r or {}).get("rag_ts")
                     or (r or {}).get("message_timestamp"))
             for r in rows if isinstance(r, dict)])),
        "row_topic": (None if rows is None else {
            "shiz": sum(1 for r in rows if isinstance(r, dict)
                        and stems_hit(r.get("fact"), TOPIC_SHIZ)),
            "konfa": sum(1 for r in rows if isinstance(r, dict)
                         and stems_hit(r.get("fact"), TOPIC_CONF)),
            "conflict": sum(1 for r in rows if isinstance(r, dict)
                            and stems_hit(r.get("fact"), CONFLICT_MARK)),
            "relation": sum(1 for r in rows if isinstance(r, dict)
                            and stems_hit(r.get("fact"), RELATION_MARK)),
        }),
        "row_period_fill": (None if rows is None else sum(
            1 for r in rows if isinstance(r, dict) and r.get("period_fill"))),
        "row_unattributed": (None if rows is None else sum(
            1 for r in rows if isinstance(r, dict) and r.get("unattributed"))),
        "row_subject_roles": (None if rows is None else hist(
            [(r or {}).get("subject_role") for r in rows
             if isinstance(r, dict) and r.get("subject_role")])),
        "period_stats": captured.get("period_stats"),
        "memory_scope": captured.get("memory_scope"),
        "plan_act": captured.get("plan_act"),
        "block_topic": {
            "shiz": (block or "").casefold().count("шиз"),
            "konfa": (block or "").casefold().count("конф"),
        },
        "retrieve_calls": len(spy.calls),
        "retrieve": spy.calls,
        "row_ids": (None if rows is None else [
            int(r.get("id")) for r in rows
            if isinstance(r, dict) and str(r.get("id") or "").isdigit()][:40]),
        "rows_detail": (None if rows is None else [
            _row_brief(r) for r in rows[:40] if isinstance(r, dict)]),
        "period_rows": (None if rows is None else {
            "count": sum(1 for r in rows if isinstance(r, dict)
                         and r.get("period_fill")),
            "years": hist([
                year_of((r or {}).get("rag_ts")
                        or (r or {}).get("message_timestamp"))
                for r in rows if isinstance(r, dict)
                and r.get("period_fill")]),
            "reasons": hist([
                (r or {}).get("stems_shared_reason") for r in rows
                if isinstance(r, dict) and r.get("period_fill")]),
            "stems_shared": hist([
                (r or {}).get("stems_shared") for r in rows
                if isinstance(r, dict) and r.get("period_fill")]),
            "roles": hist([
                (r or {}).get("subject_role") for r in rows
                if isinstance(r, dict) and r.get("period_fill")
                and r.get("subject_role")]),
        }),
    }

    # ── real <Old_Episode> (same call the live turn makes) ────────────────
    ep_started = time.monotonic()
    with RetrieveSpy(redact, entities) as ep_spy:
        try:
            ep_block, ep_stats = await asyncio.wait_for(
                svc._build_old_episodes(CHAT, query, tail, {}, None, None),
                300)
        except Exception as exc:       # noqa: BLE001
            ep_block, ep_stats = "", {"error": type(exc).__name__}
            out["old_episode_error"] = {"error": type(exc).__name__,
                                        "text": str(exc)[:300]}
    spans = []
    for span in (ep_stats or {}).get("spans") or ():
        if isinstance(span, dict):
            spans.append({
                "first": span.get("first_ts"),
                "last": span.get("last_ts"),
                "first_year": year_of(span.get("first_ts")),
                "last_year": year_of(span.get("last_ts")),
                "sources": len(span.get("source_ids") or ()),
            })
    out["old_episode"] = {
        "seconds": round(time.monotonic() - ep_started, 2),
        "chars": len(ep_block or ""),
        "empty": not ep_block,
        "stats": {k: v for k, v in (ep_stats or {}).items() if k != "spans"},
        "period_intent": (ep_stats or {}).get("period_intent") if isinstance(
            ep_stats, dict) else None,
        "year_window": (ep_stats or {}).get("year_window") if isinstance(
            ep_stats, dict) else None,
        "stats_years": sorted(k for k in (ep_stats or {})
                              if isinstance(k, str) and k.isdigit()),
        "spans": spans,
        "block_years": block_years(ep_block or "", redact),
        "topic": {
            "shiz": (ep_block or "").casefold().count("шиз"),
            "konfa": (ep_block or "").casefold().count("конф"),
            "conflict": sum((ep_block or "").casefold().count(stem)
                            for stem in CONFLICT_MARK),
        },
        "retrieve_calls": len(ep_spy.calls),
        "retrieve": ep_spy.calls[:2],
    }
    out["caps"] = {"episode_max_count": composer.episode_max_count(),
                   "episode_max_messages": composer.episode_max_messages(),
                   "episode_gap_seconds": composer.episode_gap_seconds()}
    return out


async def measure_plan_flow(svc, key, query, response_act, redact,
                            entities) -> dict:
    """Real L1 tombstone: pre-plan block -> L1Plan -> `_apply_plan_memory_scope`.

    This is the exact production seam Slice B consumes: the plan is a real
    `L1Plan` dataclass with `response_act` set; no query words are added and
    `memory_scope` stays `auto` (the hard case)."""
    started = time.monotonic()
    out: dict = {"class": key, "query": redact(query),
                 "response_act": response_act}
    stub = SimpleNamespace(text=query, chat_id=CHAT, message_id=0)
    try:
        initial, _hint = await asyncio.wait_for(
            svc._build_rag_block(CHAT, stub, "", memory_scope="auto"), 300)
    except Exception as exc:           # noqa: BLE001
        out["error"] = {"stage": "pre_plan_block",
                        "error": type(exc).__name__,
                        "text": str(exc)[:300]}
        return out
    out["pre_plan_block_chars"] = len(initial or "")
    out["pre_plan_block_years"] = block_years(initial or "", redact)
    placeholder = not bool(initial)
    block = initial or "<RAG_Memory>\n(probe placeholder)\n</RAG_Memory>"
    plan_act_supported = _accepts(svc._build_rag_block, "plan_act")
    out["plan_act_supported"] = plan_act_supported
    try:
        from services.direct_l1 import L1Plan
        plan = L1Plan(response_act=response_act)
        out["plan_repr"] = {"type": type(plan).__name__,
                            "response_act": getattr(plan, "response_act", None),
                            "memory_scope": getattr(plan, "memory_scope",
                                                    "<absent>")}
    except Exception as exc:           # noqa: BLE001
        out["error"] = {"stage": "l1_plan", "error": type(exc).__name__,
                        "text": str(exc)[:300]}
        return out
    rag_ctx = {"chat_id": CHAT, "message": stub, "global_ctx": "",
               "history_sample": None, "projection": None,
               "subject_name": None, "subject_uid": None}
    captured: dict = {}
    orig_rows = svc._rag_unified_rows

    async def rows_spy(*args, **kwargs):
        got = await orig_rows(*args, **kwargs)
        captured["rows"] = list(got or ())
        captured["period_stats"] = dict(
            getattr(svc, "_rag_period_stats", None) or {})
        captured["plan_act"] = kwargs.get("plan_act")
        captured["memory_scope"] = kwargs.get("memory_scope")
        return got

    svc._rag_unified_rows = rows_spy
    with RetrieveSpy(redact, entities) as spy:
        try:
            blocks = await asyncio.wait_for(
                svc._apply_plan_memory_scope([block], rag_ctx, plan), 300)
        except Exception as exc:       # noqa: BLE001
            out["error"] = {"stage": "apply_plan_memory_scope",
                            "error": type(exc).__name__,
                            "text": str(exc)[:300],
                            "tb": traceback.format_exc()[-600:]}
            blocks = [block]
    svc._rag_unified_rows = orig_rows
    final = blocks[0] if blocks else ""
    rows = captured.get("rows") or []
    out.update({
        "placeholder_used": placeholder,
        "rebuilt": bool(final and final != block),
        "rebuild_rows": len(rows),
        "rebuild_row_years": hist([
            year_of((r or {}).get("rag_ts")
                    or (r or {}).get("message_timestamp")) for r in rows
            if isinstance(r, dict)]),
        "rebuild_period_rows": sum(
            1 for r in rows if isinstance(r, dict) and r.get("period_fill")),
        "rebuild_period_years": hist([
            year_of((r or {}).get("rag_ts")
                    or (r or {}).get("message_timestamp")) for r in rows
            if isinstance(r, dict) and r.get("period_fill")]),
        "rebuild_period_reasons": hist([
            (r or {}).get("stems_shared_reason") for r in rows
            if isinstance(r, dict) and r.get("period_fill")]),
        "period_stats": captured.get("period_stats"),
        "plan_act_forwarded": captured.get("plan_act"),
        "memory_scope_forwarded": captured.get("memory_scope"),
        "final_block_chars": len(final or ""),
        "final_block_years": block_years(final or "", redact),
        "final_block_chars_no_placeholder": len(final or "") if not placeholder
                                            else None,
        "retrieve_calls": len(spy.calls),
        "retrieve": spy.calls,
        "row_ids": [int(r.get("id")) for r in rows
                    if isinstance(r, dict)
                    and str(r.get("id") or "").isdigit()][:40],
        "rows_detail": [_row_brief(r) for r in rows[:40]
                        if isinstance(r, dict)],
        "seconds": round(time.monotonic() - started, 2),
    })
    return out


async def measure_relations(db, memory, mca_mod, router, person, redact,
                            entities) -> dict:
    """Raw projection + tool envelope of the relationships purpose."""
    name = str(person.get("name") or "")
    uid = int(person.get("uid") or 0)
    out: dict = {"subject_uid_present": bool(uid)}
    request = mca_mod.RetrievalRequest(
        chat_id=CHAT, query=RELATIONS, mode="auto",
        purpose="relationships", top_k=10, reply_depth=0,
        channels=(), include_relations=True,
        subject_names=(name,), subject_entity_ids=(uid,))
    with RetrieveSpy(redact, entities) as spy:
        try:
            result = await asyncio.wait_for(
                mca_mod.retrieve(db, memory, request), 180)
        except Exception as exc:       # noqa: BLE001
            out["error"] = {"stage": "retrieve_relations",
                            "error": type(exc).__name__,
                            "text": str(exc)[:300]}
            return out
    out["raw"] = spy.calls[0] if spy.calls else None
    try:
        envelope = await asyncio.wait_for(
            router._get_user_context(
                {"person": name, "purpose": "relationships"},
                ToolContext(CHAT, RELATIONS, user_id=None)), 180)
        out["envelope"] = _profile_view(envelope, redact, entities)
    except Exception as exc:           # noqa: BLE001
        out["envelope_error"] = {"error": type(exc).__name__,
                                 "text": str(exc)[:300]}
    out["relations_total"] = len(getattr(result, "relations", ()) or ())
    return out


async def _profile_sql(db, person, now_ts) -> dict:
    """Exact SQL rows of the two Slice B readers (refs/years only, no text)."""
    name = str(person.get("name") or "")
    uid = int(person.get("uid") or 0)
    out: dict = {"supported": {}, "rows": {}}
    reader = getattr(db, "get_subject_profile_facts", None)
    out["supported"]["get_subject_profile_facts"] = callable(reader)
    if callable(reader):
        try:
            got = await reader(CHAT, name, 10, now_ts, user_id=uid)
        except Exception as exc:       # noqa: BLE001
            out["rows"]["subject_profile_facts_error"] = type(exc).__name__
            got = []
        out["rows"]["subject_profile_facts"] = [{
            "id": row.get("id"),
            "yr": row.get("yr"),
            "year": year_of(row.get("message_timestamp")
                            or row.get("created_at")),
            "subject_role": row.get("subject_role"),
            "subject_ref_id": row.get("subject_ref_id"),
            "target_is_p1": str(row.get("target_user") or "") == name,
            "speaker_author_id": row.get("speaker_author_id"),
            "origin": row.get("origin"),
            "valid_now": row.get("valid_now"),
            "chars": len(str(row.get("fact") or "")),
            "tg_message_id_present": bool(row.get("tg_message_id")),
        } for row in got[:12]]
    reader2 = getattr(db, "get_author_message_periods", None)
    out["supported"]["get_author_message_periods"] = callable(reader2)
    if callable(reader2):
        try:
            got2 = await reader2(CHAT, uid, 10)
        except Exception as exc:       # noqa: BLE001
            out["rows"]["author_message_periods_error"] = type(exc).__name__
            got2 = []
        out["rows"]["author_message_periods"] = [{
            "id": row.get("id"),
            "year": row.get("as_of_year"),
            "speaker_author_id": row.get("speaker_author_id"),
            "subject_role": row.get("subject_role"),
            "authored_by_subject": bool(row.get("authored_by_subject")),
            "origin": row.get("origin"),
            "chars": len(str(row.get("text") or "")),
            "tg_message_id_present": bool(row.get("tg_message_id")),
        } for row in got2[:12]]
    return out


def _sql(conn_path, sql_text, params=()):
    try:
        con = sqlite3.connect("file:%s?mode=ro" % conn_path, uri=True)
        try:
            return con.execute(sql_text, params).fetchall()
        finally:
            con.close()
    except Exception as exc:          # noqa: BLE001
        return "err:%s" % type(exc).__name__


def _scalar(conn_path, sql_text, params=()):
    got = _sql(conn_path, sql_text, params)
    if isinstance(got, str):
        return got
    return got[0][0] if got else None


def _pairs(conn_path, sql_text, params=()):
    got = _sql(conn_path, sql_text, params)
    if isinstance(got, str):
        return got
    return [{"k": str(a), "n": int(b)} for a, b in got]


def _corpus_sql(conn_path) -> dict:
    """Copy-level counters (identical for both variants -> cached)."""
    out: dict = {}
    out["messages_by_year"] = _pairs(
        conn_path,
        "SELECT strftime('%Y', datetime(timestamp,'unixepoch')) AS y, "
        "COUNT(*) FROM smart_messages WHERE chat_id=? GROUP BY y ORDER BY y",
        (CHAT,))
    out["messages_total"] = _scalar(
        conn_path, "SELECT COUNT(*) FROM smart_messages WHERE chat_id=?",
        (CHAT,))
    out["messages_span"] = {
        "min": _scalar(conn_path, "SELECT MIN(timestamp) FROM smart_messages "
                                  "WHERE chat_id=?", (CHAT,)),
        "max": _scalar(conn_path, "SELECT MAX(timestamp) FROM smart_messages "
                                  "WHERE chat_id=?", (CHAT,)),
    }
    out["graph_facts_by_year"] = _pairs(
        conn_path,
        "SELECT strftime('%Y', datetime(COALESCE(message_timestamp, "
        "created_at),'unixepoch')) AS y, COUNT(*) FROM graph_facts "
        "WHERE chat_id=? GROUP BY y ORDER BY y", (CHAT,))
    out["episodes_by_year"] = _pairs(
        conn_path,
        "SELECT strftime('%Y', datetime(event_start_ts,'unixepoch')) AS y, "
        "COUNT(*) FROM mca_episodes WHERE chat_id=? GROUP BY y ORDER BY y",
        (CHAT,))
    out["episodes_total"] = _scalar(
        conn_path, "SELECT COUNT(*) FROM mca_episodes WHERE chat_id=?", (CHAT,))
    out["shiz_msgs_by_year"] = _pairs(
        conn_path,
        "SELECT strftime('%Y', datetime(timestamp,'unixepoch')) AS y, "
        "COUNT(*) FROM smart_messages WHERE chat_id=? AND lower(text) "
        "LIKE '%шиз%' GROUP BY y ORDER BY y", (CHAT,))
    out["conflict_msgs_by_year"] = _pairs(
        conn_path,
        "SELECT strftime('%Y', datetime(timestamp,'unixepoch')) AS y, "
        "COUNT(*) FROM smart_messages WHERE chat_id=? AND (lower(text) "
        "LIKE '%ссор%' OR lower(text) LIKE '%ругал%' OR lower(text) "
        "LIKE '%скандал%') GROUP BY y ORDER BY y", (CHAT,))
    out["edges"] = {
        "total": _scalar(conn_path, "SELECT COUNT(*) FROM edges"),
        "with_last_updated": _scalar(
            conn_path,
            "SELECT COUNT(*) FROM edges WHERE last_updated IS NOT NULL "
            "AND last_updated<>''"),
        "last_updated_by_year": _pairs(
            conn_path,
            "SELECT substr(last_updated,1,4) AS y, COUNT(*) FROM edges "
            "WHERE last_updated IS NOT NULL AND last_updated<>'' "
            "GROUP BY y ORDER BY y"),
        "chat_edges": _scalar(
            conn_path, "SELECT COUNT(*) FROM edges WHERE chat_id=?",
            (CHAT,)) if _scalar(
                conn_path,
                "SELECT COUNT(*) FROM pragma_table_info('edges') "
                "WHERE name='chat_id'") else "no_chat_column",
    }
    return out


def _id_tables(conn_path, ids) -> dict:
    got = {"graph_facts": 0, "smart_messages": 0, "absent": 0,
           "absent_ids": []}
    if not ids:
        return got
    try:
        con = sqlite3.connect("file:%s?mode=ro" % conn_path, uri=True)
    except Exception:                                   # noqa: BLE001
        got["absent"] = len(ids)
        got["absent_ids"] = ["<no_connection>"]
        return got
    try:
        for rid in ids:
            table = None
            for name in ("graph_facts", "smart_messages"):
                try:
                    hit = con.execute(
                        "SELECT 1 FROM %s WHERE id=? LIMIT 1" % name,
                        (int(rid),)).fetchone()
                except Exception:                   # noqa: BLE001
                    continue
                if hit:
                    table = name
                    break
            if table:
                got[table] += 1
            else:
                got["absent"] += 1
                if len(got["absent_ids"]) < 5:
                    got["absent_ids"].append(int(rid))
    finally:
        con.close()
    return got


def _id_year_check(conn_path, detail) -> dict:
    """Does the SQL row's own year equal the year the harness reported?"""
    out = {"checked": 0, "match": 0, "mismatch": 0, "missing": 0,
           "mismatch_items": []}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % conn_path, uri=True)
    except Exception:                                   # noqa: BLE001
        out["missing"] = len(detail or ())
        return out
    try:
        for item in detail or ():
            rid = item.get("id")
            if rid is None:
                continue
            sql_year = None
            found = False
            try:
                row = con.execute(
                    "SELECT strftime('%Y', datetime(COALESCE(NULLIF("
                    "message_timestamp,0), NULLIF(created_at,0)),"
                    "'unixepoch')) FROM graph_facts WHERE id=?",
                    (int(rid),)).fetchone()
                if row is not None:
                    found = True
                    sql_year = int(row[0]) if row[0] else None
            except Exception:                           # noqa: BLE001
                row = None
            if not found:
                try:
                    row = con.execute(
                        "SELECT strftime('%Y', datetime(timestamp,"
                        "'unixepoch')) FROM smart_messages WHERE id=?",
                        (int(rid),)).fetchone()
                    if row is not None:
                        found = True
                        sql_year = int(row[0]) if row[0] else None
                except Exception:                       # noqa: BLE001
                    row = None
            if not found:
                out["missing"] += 1
                continue
            out["checked"] += 1
            if sql_year == item.get("year"):
                out["match"] += 1
            else:
                out["mismatch"] += 1
                if len(out["mismatch_items"]) < 5:
                    out["mismatch_items"].append(
                        {"id": int(rid), "sql_year": sql_year,
                         "reported_year": item.get("year")})
    finally:
        con.close()
    return out


def _edge_check(conn_path, relations_meta) -> dict:
    """Each delivered edge/fact ref must exist; its year must match SQL."""
    out = {"edges_checked": 0, "edges_present": 0, "edges_absent": 0,
           "facts_checked": 0, "facts_present": 0, "facts_absent": 0,
           "year_checked": 0, "year_match": 0, "year_mismatch": 0,
           "absent_ids": []}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % conn_path, uri=True)
    except Exception:                                   # noqa: BLE001
        out["edges_absent"] = len(relations_meta or ())
        return out
    try:
        for item in relations_meta or ():
            edge_id = item.get("edge_id")
            fact_id = item.get("fact_id")
            if edge_id not in (None, ""):
                out["edges_checked"] += 1
                try:
                    row = con.execute(
                        "SELECT last_updated FROM edges WHERE id=?",
                        (int(edge_id),)).fetchone()
                except Exception:                       # noqa: BLE001
                    row = None
                if row:
                    out["edges_present"] += 1
                    if row[0]:
                        sql_year = None
                        try:
                            sql_year = int(str(row[0])[:4])
                        except (TypeError, ValueError):
                            sql_year = None
                        if sql_year:
                            out["year_checked"] += 1
                            if sql_year == item.get("year"):
                                out["year_match"] += 1
                            else:
                                out["year_mismatch"] += 1
                else:
                    out["edges_absent"] += 1
                    if len(out["absent_ids"]) < 5:
                        out["absent_ids"].append("e:%s" % edge_id)
            if fact_id not in (None, ""):
                out["facts_checked"] += 1
                try:
                    hit = con.execute(
                        "SELECT 1 FROM graph_facts WHERE id=?",
                        (int(fact_id),)).fetchone()
                except Exception:                       # noqa: BLE001
                    hit = None
                if hit:
                    out["facts_present"] += 1
                else:
                    out["facts_absent"] += 1
                    if len(out["absent_ids"]) < 5:
                        out["absent_ids"].append("f:%s" % fact_id)
    finally:
        con.close()
    return out


async def main() -> int:
    entities = json.load(open(ENT, encoding="utf-8"))
    cfg = json.load(open(CFG, encoding="utf-8"))
    redact = Redactor(entities)

    class _Cache:
        def __init__(self, data):
            self._data = dict(data or {})
            self.pg = None

        def get(self, key, default=None):
            return self._data.get(key, default)

        def get_all(self):
            return dict(self._data)

    hot.set_config_cache(_Cache(cfg.get("effective") or {}))

    identity = {
        "variant": VARIANT,
        "clone": CLONE,
        "services_file": services.__file__,
        "python": sys.version.split()[0],
        "db": DBPATH,
        "chat_id": CHAT,
        "git_head": os.environ.get("VMQ_HEAD"),
        "git_tree": os.environ.get("VMQ_TREE"),
        "files": {},
        "config": {
            "effective": cfg.get("effective"),
            "defaults": cfg.get("defaults"),
            "pg": cfg.get("pg"),
            "chat_overrides": cfg.get("chat"),
            "model_identity": cfg.get("model_identity"),
            "env_flags": cfg.get("env_flags"),
        },
    }
    for rel in WATCH:
        path = os.path.join(CLONE, rel)
        try:
            with open(path, "rb") as fh:
                identity["files"][rel] = hashlib.sha256(fh.read()).hexdigest()[:16]
        except OSError:
            identity["files"][rel] = "absent"
    assert os.path.realpath(services.__file__).startswith(
        os.path.realpath(CLONE)), "IMPORT NOT FROM THE MEASURED CLONE"
    print("IDENT " + json.dumps(identity, ensure_ascii=False), flush=True)

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
    vec = {"ok": None, "reason": None}
    try:
        vec["ok"] = bool(await memory.initialize())
    except Exception as exc:           # noqa: BLE001
        vec["ok"] = False
        vec["reason"] = type(exc).__name__
    vec["available"] = getattr(memory, "_vec_available", None)
    vec["off_reason"] = getattr(memory, "_vec_off_reason", None)
    vec["dim"] = getattr(memory, "_vec_dim", None)
    print("VEC " + json.dumps(vec), flush=True)

    aliases, alias_mode = await _aliases_or_stub()
    svc = DirectChatService(memory, db, llm, aliases)
    router = ToolRouter(ToolDeps(search=None, memory=memory, aliases=aliases,
                                 db=db, llm=llm))
    tail = await db.get_recent_messages(CHAT, 40)
    person = entities["person"]
    event = entities["event"] or {}
    person_q = "что ты знаешь про %s?" % person["name"]
    event_q = "что вообще было с %s, напомни?" % event.get("token")
    current_q = "что сейчас происходит с %s?" % event.get("token")
    uid = int(person.get("uid") or 0)

    out: dict = {
        "artifact_kind": "candidate_probe_not_live",
        "variant": VARIANT,
        "identity": identity,
        "vec": vec,
        "alias_mode": alias_mode,
        "caps_composer": {
            "episode_max_count": composer.episode_max_count(),
            "episode_max_messages": composer.episode_max_messages(),
            "episode_gap_seconds": composer.episode_gap_seconds(),
        },
        "constants": {
            "period_min_stems": getattr(
                DirectChatService, "_RAG_PERIOD_MIN_STEMS", None),
            "period_slot_div": getattr(
                DirectChatService, "_RAG_PERIOD_SLOT_DIV", None),
            "period_channels": list(getattr(
                DirectChatService, "_RAG_PERIOD_CHANNELS", ()) or ()),
            "period_pool": getattr(
                DirectChatService, "_RAG_PERIOD_POOL", None),
            "history_episode_slice_div": getattr(
                mca, "_HISTORY_EPISODE_SLICE_DIV", None),
            "history_markers": list(getattr(mca, "_HISTORY_MARKERS", ()) or ()),
            "period_intent_kinds": [
                getattr(mca, name) for name in
                ("PERIOD_INTENT_NONE", "PERIOD_INTENT_YEAR",
                 "PERIOD_INTENT_HISTORICAL", "PERIOD_INTENT_MULTI_YEAR")
                if hasattr(mca, name)],
            "period_keep_codes": [
                getattr(mca, name) for name in
                ("PERIOD_KEEP_IN_TARGET", "PERIOD_KEEP_SOFT_FALLBACK",
                 "PERIOD_KEEP_VECTOR", "PERIOD_KEEP_HISTORICAL_QUOTA",
                 "PERIOD_KEEP_MULTI_YEAR")
                if hasattr(mca, name)],
            "period_drop_codes": [
                getattr(mca, name) for name in
                ("PERIOD_DROP_OUT_OF_TARGET_YEAR", "PERIOD_DROP_UNKNOWN_YEAR",
                 "PERIOD_DROP_SUBJECT", "PERIOD_DROP_POOL_CAP")
                if hasattr(mca, name)],
            "slice_b": {
                "resolve_period_intent_plan_act": _accepts(
                    mca.resolve_period_intent, "plan_act"),
                "year_time_bounds": hasattr(mca, "year_time_bounds"),
                "lexical_time_window_field": hasattr(
                    mca.RetrievalRequest, "lexical_time_window"),
                "db_subject_profile_facts": hasattr(
                    DatabaseService, "get_subject_profile_facts"),
                "db_author_message_periods": hasattr(
                    DatabaseService, "get_author_message_periods"),
                "tool_subject_profile_reader": hasattr(
                    ToolRouter, "_memory_lookup_subject_profile_facts"),
                "tool_temporal_projection": hasattr(
                    ToolRouter, "_memory_lookup_subject_material"),
                "build_rag_block_plan_act": _accepts(
                    DirectChatService._build_rag_block, "plan_act"),
            },
        },
        "classes": {},
        "probes": {},
        "sql": {},
        "errors": [],
    }

    # structured intent, both variants, with and without the plan signal
    try:
        plain_intent = mca.resolve_period_intent(event_q, memory_scope="auto")
        out["probes"]["intent_t2_no_signal"] = _period_intent_view(plain_intent)
        if _accepts(mca.resolve_period_intent, "plan_act"):
            with_plan = mca.resolve_period_intent(
                event_q, memory_scope="auto", plan_act="historical_recall")
            out["probes"]["intent_t2_plan_act"] = _period_intent_view(with_plan)
        else:
            out["probes"]["intent_t2_plan_act"] = {"unsupported": True}
        out["probes"]["intent_t3"] = _period_intent_view(
            mca.resolve_period_intent(current_q, memory_scope="auto"))
        out["probes"]["intent_a1"] = _period_intent_view(
            mca.resolve_period_intent(CREATIVE_OWNER, memory_scope="auto"))
        out["probes"]["intent_d"] = _period_intent_view(
            mca.resolve_period_intent(CONFLICT_2023, memory_scope="auto"))
    except Exception as exc:           # noqa: BLE001
        out["errors"].append({"stage": "intent", "error": type(exc).__name__,
                              "text": str(exc)[:300]})

    out["probes"]["live_registry_readonly"] = _live_registry_snapshot()
    print("LIVE_REGISTRY ready=%s" % out["probes"][
        "live_registry_readonly"].get("active_present"), flush=True)

    # ── required classes ──────────────────────────────────────────────────
    classes = [
        ("A1_creative_owner", CREATIVE_OWNER, {}),
        ("A1P_plain_twin", PLAIN_TWIN, {}),
        ("D_conflict_2023", CONFLICT_2023, {}),
        ("T2_no_signal", event_q, {}),
        ("T3_current_no_signal", current_q, {}),
        ("P1_profile_reply", person_q, {"subject": (person["name"], uid)}),
        ("E_relations_years", RELATIONS, {}),
    ]
    for key, query, extra in classes:
        try:
            out["classes"][key] = await measure_query(
                db, memory, svc, router, key, query, tail, redact, entities,
                **extra)
        except Exception as exc:       # noqa: BLE001
            out["errors"].append({"stage": key, "error": type(exc).__name__,
                                  "text": str(exc)[:400],
                                  "tb": traceback.format_exc()[-900:]})
        print("CLASS_DONE %s" % key, flush=True)

    # ── T2 through the real plan seam (Slice B contract) ──────────────────
    for key, query, act in (
            ("T2_plan_historical_recall", event_q, "historical_recall"),
            ("T3_current_plan_historical_recall", current_q,
             "historical_recall")):
        try:
            out["classes"][key] = await measure_plan_flow(
                svc, key, query, act, redact, entities)
        except Exception as exc:       # noqa: BLE001
            out["errors"].append({"stage": key, "error": type(exc).__name__,
                                  "text": str(exc)[:400],
                                  "tb": traceback.format_exc()[-900:]})
        print("PLAN_DONE %s" % key, flush=True)

    # ── profile envelopes (biography/general/relationships) ───────────────
    for purpose in ("biography", "general", "relationships"):
        try:
            raw = await asyncio.wait_for(
                router._get_user_context({"person": person["name"],
                                          "purpose": purpose},
                                         ToolContext(CHAT, person_q,
                                                     user_id=None)),
                timeout=180)
            out["probes"]["profile_%s" % purpose] = _profile_view(
                raw, redact, entities)
        except Exception as exc:       # noqa: BLE001
            out["errors"].append({"stage": "profile_%s" % purpose,
                                  "error": type(exc).__name__,
                                  "text": str(exc)[:300]})
        print("PROFILE_DONE %s" % purpose, flush=True)

    # ── exact SQL rows of the new readers ─────────────────────────────────
    try:
        out["probes"]["profile_sql"] = await _profile_sql(
            db, person, int(time.time()))
    except Exception as exc:           # noqa: BLE001
        out["errors"].append({"stage": "profile_sql",
                              "error": type(exc).__name__,
                              "text": str(exc)[:300]})

    # ── relations projection (raw + envelope) ─────────────────────────────
    try:
        out["probes"]["relations"] = await measure_relations(
            db, memory, mca, router, person, redact, entities)
    except Exception as exc:           # noqa: BLE001
        out["errors"].append({"stage": "relations",
                              "error": type(exc).__name__,
                              "text": str(exc)[:300]})
    print("RELATIONS_DONE", flush=True)

    # ── copy-level counters (cached across variants) ──────────────────────
    if SQLCACHE and os.path.exists(SQLCACHE):
        try:
            out["sql"] = json.load(open(SQLCACHE, encoding="utf-8"))
            out["sql"]["_source"] = "cache"
        except Exception:              # noqa: BLE001
            out["sql"] = {}
    if not out["sql"]:
        out["sql"] = _corpus_sql(DBPATH)
        out["sql"]["_source"] = "computed"
        out["sql"]["person"] = {
            "msgs_2023_2024": int(person.get("msgs_2023_2024") or 0),
            "msgs_2026": int(person.get("msgs_2026") or 0),
            "msgs_by_year": _pairs(
                DBPATH,
                "SELECT strftime('%Y', datetime(timestamp,'unixepoch')) AS y, "
                "COUNT(*) FROM smart_messages WHERE chat_id=? AND user_id=? "
                "GROUP BY y ORDER BY y", (CHAT, person.get("uid"))),
        }
        out["sql"]["person_facts_by_year"] = _pairs(
            DBPATH,
            "SELECT strftime('%Y', datetime(COALESCE(message_timestamp, "
            "created_at),'unixepoch')) AS y, COUNT(*) FROM graph_facts "
            "WHERE chat_id=? AND (target_user=? OR target_user=? OR "
            "subject_ref_id=?) GROUP BY y ORDER BY y",
            (CHAT, person.get("name"), str(person.get("uid")),
             str(person.get("uid"))))
        out["sql"]["person_speaker_facts_by_year"] = _pairs(
            DBPATH,
            "SELECT strftime('%Y', datetime(COALESCE(message_timestamp, "
            "created_at),'unixepoch')) AS y, COUNT(*) FROM graph_facts "
            "WHERE chat_id=? AND speaker_author_id=? GROUP BY y ORDER BY y",
            (CHAT, int(person.get("uid") or 0)))
        out["sql"]["person_source_ref"] = _scalar(
            DBPATH,
            "SELECT source_ref_id FROM mca_source_refs WHERE store='telegram' "
            "AND entity_type='user' AND entity_id=? AND COALESCE(chat_id,-1)="
            "COALESCE(?,-1) LIMIT 1",
            (str(person.get("uid")), CHAT))
        out["sql"]["event_counts"] = event
        if SQLCACHE:
            try:
                with open(SQLCACHE, "w", encoding="utf-8") as fh:
                    json.dump(out["sql"], fh, ensure_ascii=False, indent=1)
            except OSError:            # noqa: BLE001
                pass

    # ── "no fabricated source": ids, years and edge refs against the copy ─
    id_check = {}
    year_check = {}
    for key, item in (out.get("classes") or {}).items():
        rag = item.get("rag") or item
        ids = list(rag.get("row_ids") or ())
        detail = list(rag.get("rows_detail") or ())
        id_check[key] = dict(_id_tables(DBPATH, ids), rows=len(ids))
        year_check[key] = _id_year_check(DBPATH, detail)
    out["sql"]["delivered_id_check"] = id_check
    out["sql"]["delivered_year_check"] = year_check
    rel = ((out.get("probes") or {}).get("relations") or {}).get("raw") or {}
    rel_meta = ((rel.get("result") or {}).get("relations_meta") or [])
    out["sql"]["relations_edge_check"] = _edge_check(DBPATH, rel_meta)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("WROTE " + OUT + " bytes=%s" % os.path.getsize(OUT), flush=True)
    await db.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:                  # noqa: BLE001
        traceback.print_exc()
        sys.exit(3)
