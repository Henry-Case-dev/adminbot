# -*- coding: utf-8 -*-
"""VMQ-MEM/TIME Slice C corpus probe (read-only, runs ON the production host).

Derived from the committed Slice B probe (`harness-2026-11-15/probe_slice_b.py`).
Only the Slice C invocation surface is added:

  * the exact owner query through the real `_build_rag_block` seam, capturing
    per-`retrieve` `include_overview` / `period_intent` and the bounded
    overview fields of the SAME `RetrievalResult`;
  * the SAME `RetrievalResult` identity check (`_rag_overview_result is base`)
    and the real `_build_evidence_bundle(...)` -> `apply_overview_to_bundle`
    projection: coverage / independent_periods / counterexamples / limitations
    actually delivered to the Writer bundle;
  * episode-view reads (`list_episode_views`, `subject_longitudinal_view`)
    counted around the RAG block only, so a current-state question can be
    shown as "no overview -> no episode reads";
  * an independent SQL projection of the documented episode window
    (ORDER BY updated_at DESC LIMIT 200) verifying that overview coverage
    never claims periods the copy does not contain.

Never writes live data, never restarts a unit, never sends a message. Fact
texts are never stored: ids, years, refs, counts, lengths only.
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
CLONE = os.environ.get("VMQ_CLONE", "/root/vmqC/measure/repo-base")
DBPATH = os.environ.get("VMQ_DB", "/root/vmqC/measure/dbcopy.db")
OUT = os.environ.get("VMQ_OUT", "/root/vmqC/measure/out/base.json")
ENT = os.environ.get("VMQ_ENT", "/root/vmqC/measure/entities.json")
CFG = os.environ.get("VMQ_CFG", "/root/vmqC/measure/cfg_frozen.json")
APP = "/var/www/admin_bot"
CHAT = -1002661910336

sys.path.insert(0, CLONE)
os.chdir(APP)                      # load_dotenv() parity with the service

logging.basicConfig(level=logging.ERROR,
                    format="%(levelname)s %(name)s: %(message)s")

import services  # noqa: E402
from config.settings import settings  # noqa: E402
from services import hot_config as hot  # noqa: E402
from services import mca_gates  # noqa: E402
from services import mca_retrieval_context as mca  # noqa: E402
from services import mca_episodes  # noqa: E402
from services.database import DatabaseService  # noqa: E402
from services.direct_chat_service import DirectChatService  # noqa: E402
from services.llm_client import LLMClient  # noqa: E402
from services.summary_memory import MemoryManager  # noqa: E402

Y2023 = (1672531200, 1704067199)
Y2024 = (1704067200, 1735689599)
Y2026 = (1767225600, 1798761599)
ISO = re.compile(r"\b(20\d{2})-\d{2}-\d{2}\b|\b\d{2}\.\d{2}\.(20\d{2})")

# ── query set: identical to the Slice B probe ────────────────────────────────
CREATIVE_OWNER = "напиши юмористический рассказ об основных шизах конфы"
PLAIN_TWIN = "что за шизы были на конфе?"
CONFLICT_2023 = "из-за чего мы ссорились и ругались в 2023 году"
RELATIONS = "как менялись наши отношения и взгляды за эти годы"

TOPIC_SHIZ = ("шиз",)
TOPIC_CONF = ("конф",)
CONFLICT_MARK = ("ссор", "ругал", "скандал", "конфликт", "послал", "обид",
                 "спор")
RELATION_MARK = ("отнош", "друж", "общени", "взгляд", "мнени")
WATCH = ("services/mca_retrieval_context.py",
         "services/direct_chat_service.py",
         "services/database.py",
         "services/mca_episodes.py",
         "services/mca_gates.py")


def _accepts(fn, name) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


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
    if hasattr(intent, "wants_overview"):
        out["wants_overview"] = bool(intent.wants_overview)
    return out or {"raw": str(intent)[:120]}


def _row_brief(row) -> dict:
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
        "subject_role": (row or {}).get("subject_role"),
        "authored_by_subject": bool(
            (row or {}).get("authored_by_subject")),
    }


def _request_view(request) -> dict:
    keys = ("chat_id", "mode", "purpose", "top_k", "channels", "scope",
            "include_overview", "memory_scope", "period_fill",
            "exclude_years", "include_archived", "preserve_channel_order",
            "intent", "subject_names", "subject_entity_ids", "time_from",
            "time_to", "lexical_time_window")
    out = {}
    for key in keys:
        value = getattr(request, key, "<none>")
        if isinstance(value, tuple):
            value = list(value)
        out[key] = value
    out["period_intent"] = _period_intent_view(
        getattr(request, "period_intent", None))
    return out


def _overview_view(overview) -> dict | None:
    """Bounded view of the overview attached to the SAME RetrievalResult."""
    if overview is None:
        return None
    try:
        data = overview.as_dict()
    except Exception:                    # noqa: BLE001
        return {"error": "as_dict_failed"}
    coverage = data.get("coverage") or {}
    present = []
    for block in coverage.get("present_periods") or ():
        if not isinstance(block, dict):
            continue
        present.append({"period": block.get("period"),
                        "episodes": block.get("episodes"),
                        "episode_refs": len(block.get("episode_refs") or ())})
    support = []
    for row in data.get("period_support") or ():
        if isinstance(row, dict):
            support.append({"period": row.get("period"),
                            "independent": row.get("independent"),
                            "repeated": row.get("repeated")})
    counterexamples = []
    for pair in data.get("counterexamples") or ():
        if isinstance(pair, dict):
            counterexamples.append({
                "left_refs": len(pair.get("left_refs") or ()),
                "right_refs": len(pair.get("right_refs") or ()),
                "left_chars": len(str(pair.get("left_text") or "")),
                "right_chars": len(str(pair.get("right_text") or "")),
            })
    versions = data.get("episode_versions") or []
    hints = data.get("semantic_hints") or []
    return {
        "state": data.get("state"),
        "subject_present": bool(data.get("subject_id")),
        "derived_version": data.get("derived_version"),
        "coverage": {
            "period_grain": coverage.get("period_grain"),
            "present_periods": present,
            "missing_periods": coverage.get("missing_periods"),
            "unknown_time_episode_refs": len(
                coverage.get("unknown_time_episode_refs") or ()),
            "earliest_year": year_of(coverage.get("earliest_ts")),
            "latest_year": year_of(coverage.get("latest_ts")),
            "complete": coverage.get("complete"),
            "complete_reason": coverage.get("complete_reason"),
            "timezone": coverage.get("timezone"),
        },
        "independent_periods": list(data.get("independent_periods") or ()),
        "period_support": support,
        "episode_refs": [str(value) for value in
                         (data.get("episode_refs") or ())[:20]],
        "episode_refs_count": len(data.get("episode_refs") or ()),
        "support_source_refs_count": len(
            data.get("support_source_refs") or ()),
        "independent_support_count": data.get("independent_support_count"),
        "repeated_claims": data.get("repeated_claims"),
        "counterexamples": counterexamples,
        "counterexamples_count": len(counterexamples),
        "limitations": list(data.get("limitations") or ()),
        "episode_versions_count": len(versions),
        "episode_versions_stale": sum(
            1 for row in versions if isinstance(row, dict) and row.get("stale")),
        "episode_versions_content_status": hist(
            [(row or {}).get("content_status") for row in versions
             if isinstance(row, dict)]),
        "semantic_hints_count": len(hints),
        "semantic_hints_kinds": hist(
            [(row or {}).get("kind") for row in hints if isinstance(row, dict)]),
    }


def _result_view(result) -> dict:
    cands = list(getattr(result, "candidates", ()) or ())
    facts = list(getattr(result, "fact_rows", ()) or ())
    rows = []
    for cand in cands[:24]:
        rows.append({
            "id": str(cand.id),
            "type": cand.entity_type,
            "channel": cand.channel,
            "year": year_of(cand.sent_at),
            "score": round(float(cand.score or 0), 2),
        })
    return {
        "status": getattr(result, "status", None),
        "reason_code": getattr(result, "reason_code", None),
        "mode": getattr(result, "mode", None),
        "purpose": getattr(result, "purpose", None),
        "channels_used": list(getattr(result, "channels_used", ()) or ()),
        "candidates": len(cands),
        "candidate_years": hist([year_of(c.sent_at) for c in cands]),
        "top": rows,
        "fact_rows": len(facts),
        "fact_years": hist([
            year_of((row or {}).get("rag_ts")
                    or (row or {}).get("message_timestamp")) for row in facts]),
        "period_fill": getattr(result, "period_fill", None),
        "overview": _overview_view(getattr(result, "overview", None)),
        "result_object_id": id(result),
        "fact_ids": [str((row or {}).get("id")) for row in facts[:40]
                     if (row or {}).get("id") is not None],
        "fact_rows_detail": [_row_brief(row) for row in facts[:40]],
    }


class RetrieveSpy:
    def __init__(self):
        self.calls = []
        self._orig = None

    def __enter__(self):
        self._orig = mca.retrieve
        spy = self

        async def wrapper(db, memory, request):
            started = time.monotonic()
            out = await spy._orig(db, memory, request)
            spy.calls.append({
                "seconds": round(time.monotonic() - started, 2),
                "request": _request_view(request),
                "result": _result_view(out),
            })
            return out

        mca.retrieve = wrapper
        return self

    def __exit__(self, *exc):
        mca.retrieve = self._orig
        return False


class EpisodeSpy:
    """Counts episode-view reads around ONE RAG block build only."""

    NAMES = ("list_episode_views", "subject_longitudinal_view")

    def __init__(self):
        self.calls = {}
        self._orig = {}

    def __enter__(self):
        for name in self.NAMES:
            self.calls[name] = 0
            self._orig[name] = getattr(mca_episodes, name, None)
            if self._orig[name] is None:
                continue
            setattr(mca_episodes, name, self._wrap(name, self._orig[name]))
        return self

    def _wrap(self, name, orig):
        spy = self

        async def wrapper(*args, **kwargs):
            spy.calls[name] = spy.calls.get(name, 0) + 1
            return await orig(*args, **kwargs)

        return wrapper

    def __exit__(self, *exc):
        for name, orig in self._orig.items():
            if orig is not None:
                setattr(mca_episodes, name, orig)
        return False


def _bundle_view(bundle) -> dict | None:
    if bundle is None:
        return None
    return {
        "type": type(bundle).__name__,
        "coverage_lines": list(getattr(bundle, "coverage", ()) or ()),
        "independent_periods": list(
            getattr(bundle, "independent_periods", ()) or ()),
        "counterexamples": list(getattr(bundle, "counterexamples", ()) or ()),
        "limitations": list(getattr(bundle, "limitations", ()) or ()),
        "episode_refs_count": len(getattr(bundle, "episode_refs", ()) or ()),
        "semantic_hints_count": len(
            getattr(bundle, "semantic_hints", ()) or ()),
        "context_version": getattr(bundle, "context_version", None),
        "schema_version": getattr(bundle, "schema_version", None),
        "has_overview_slots": bool(
            getattr(bundle, "coverage", ())
            or getattr(bundle, "independent_periods", ())
            or getattr(bundle, "counterexamples", ())
            or getattr(bundle, "limitations", ())),
    }


async def _aliases_or_stub():
    try:
        from services.summary_aliases import build_alias_resolver
        got = await build_alias_resolver(CHAT)
        if got is not None and hasattr(got, "resolve"):
            return got, "real"
    except Exception:                    # noqa: BLE001
        pass

    class _Stub:
        def resolve(self, user_id, nickname=None, username=None,
                    memory_name=None):
            return str(nickname or username or memory_name or user_id or "")

    return _Stub(), "stub"


async def _capture_bundle(svc, block, query, message_id, target_name) -> dict:
    """The real bundle build the live turn performs, same retrieval_result."""
    out: dict = {"gate": bool(mca_gates.evidence_bundle_enabled())}
    if not out["gate"]:
        out["bundle"] = None
        out["note"] = "evidence bundle gate OFF"
        return out
    stub = SimpleNamespace(text=query, chat_id=CHAT, message_id=message_id)
    try:
        bundle = await asyncio.wait_for(
            svc._build_evidence_bundle(
                CHAT, stub, query, target_name, None, [block or ""],
                excluded=[], chosen_intent=None, trace_id="probe-slice-c",
                retrieval_result=getattr(svc, "_rag_overview_result", None)),
            180)
    except Exception as exc:             # noqa: BLE001
        out["error"] = {"error": type(exc).__name__,
                        "text": str(exc)[:200]}
        return out
    out["bundle"] = _bundle_view(bundle)
    return out


async def measure_query(svc, key, query, tail, redact, entities, *,
                        subject=None) -> dict:
    """One real `<RAG_Memory>` build through `_build_rag_block` + bundle."""
    started = time.monotonic()
    out: dict = {"class": key, "query": redact(query),
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
        captured["include_overview"] = kwargs.get("include_overview")
        return got

    svc._rag_unified_rows = rows_spy
    kwargs = {"memory_scope": None}
    if subject:
        kwargs["subject_name"] = subject[0]
        kwargs["subject_uid"] = subject[1]
    with EpisodeSpy() as ep_spy, RetrieveSpy() as spy:
        try:
            block, hint = await asyncio.wait_for(
                svc._build_rag_block(CHAT, stub, "", **kwargs), 300)
        except Exception as exc:         # noqa: BLE001
            out["rag_error"] = {"error": type(exc).__name__,
                                "text": str(exc)[:300],
                                "tb": traceback.format_exc()[-600:]}
            block, hint = "", ""
    svc._rag_unified_rows = orig_rows
    rows = captured.get("rows")
    overview_result = getattr(svc, "_rag_overview_result", None)
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
        "period_stats": captured.get("period_stats"),
        "memory_scope": captured.get("memory_scope"),
        "include_overview_forwarded": captured.get("include_overview"),
        "overview_result_present": overview_result is not None,
        "overview_result_is_first_retrieve": bool(
            overview_result is not None and spy.calls
            and id(overview_result) == spy.calls[0]["result"][
                "result_object_id"]),
        "overview_on_result": _overview_view(getattr(overview_result,
                                                     "overview", None)),
        "retrieve_calls": len(spy.calls),
        "retrieve_include_overview": [
            call["request"]["include_overview"] for call in spy.calls],
        "retrieve": spy.calls,
        "episode_reads": dict(ep_spy.calls),
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
        }),
    }
    out["bundle"] = await _capture_bundle(svc, block, query, 0, "")
    return out


async def measure_plan_flow(svc, key, query, response_act, redact) -> dict:
    """Pre-plan block -> real L1Plan -> `_apply_plan_memory_scope` + bundle."""
    started = time.monotonic()
    out: dict = {"class": key, "query": redact(query),
                 "response_act": response_act}
    stub = SimpleNamespace(text=query, chat_id=CHAT, message_id=0)
    with EpisodeSpy() as pre_ep, RetrieveSpy() as pre_spy:
        try:
            initial, _hint = await asyncio.wait_for(
                svc._build_rag_block(CHAT, stub, "", memory_scope="auto"), 300)
        except Exception as exc:         # noqa: BLE001
            out["error"] = {"stage": "pre_plan_block",
                            "error": type(exc).__name__,
                            "text": str(exc)[:300]}
            return out
    out["pre_plan"] = {
        "block_chars": len(initial or ""),
        "retrieve_calls": len(pre_spy.calls),
        "retrieve_include_overview": [
            call["request"]["include_overview"] for call in pre_spy.calls],
        "overview_present": getattr(svc, "_rag_overview_result", None)
        is not None,
        "episode_reads": dict(pre_ep.calls),
    }
    placeholder = not bool(initial)
    block = initial or "<RAG_Memory>\n(probe placeholder)\n</RAG_Memory>"
    try:
        from services.direct_l1 import L1Plan
        plan = L1Plan(response_act=response_act)
        out["plan_repr"] = {"type": type(plan).__name__,
                            "response_act": getattr(plan, "response_act", None),
                            "memory_scope": getattr(plan, "memory_scope",
                                                    "<absent>")}
    except Exception as exc:             # noqa: BLE001
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
        captured["include_overview"] = kwargs.get("include_overview")
        return got

    svc._rag_unified_rows = rows_spy
    with EpisodeSpy() as ep_spy, RetrieveSpy() as spy:
        try:
            blocks = await asyncio.wait_for(
                svc._apply_plan_memory_scope([block], rag_ctx, plan), 300)
        except Exception as exc:         # noqa: BLE001
            out["error"] = {"stage": "apply_plan_memory_scope",
                            "error": type(exc).__name__,
                            "text": str(exc)[:300],
                            "tb": traceback.format_exc()[-600:]}
            blocks = [block]
    svc._rag_unified_rows = orig_rows
    final = blocks[0] if blocks else ""
    rows = captured.get("rows") or []
    overview_result = getattr(svc, "_rag_overview_result", None)
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
        "period_stats": captured.get("period_stats"),
        "plan_act_forwarded": captured.get("plan_act"),
        "memory_scope_forwarded": captured.get("memory_scope"),
        "include_overview_forwarded": captured.get("include_overview"),
        "overview_result_present": overview_result is not None,
        "overview_result_is_first_retrieve": bool(
            overview_result is not None and spy.calls
            and id(overview_result) == spy.calls[0]["result"][
                "result_object_id"]),
        "overview_on_result": _overview_view(getattr(overview_result,
                                                     "overview", None)),
        "final_block_chars": len(final or ""),
        "final_block_years": block_years(final or "", redact),
        "retrieve_calls": len(spy.calls),
        "retrieve_include_overview": [
            call["request"]["include_overview"] for call in spy.calls],
        "retrieve": spy.calls,
        "episode_reads": dict(ep_spy.calls),
        "row_ids": [int(r.get("id")) for r in rows
                    if isinstance(r, dict)
                    and str(r.get("id") or "").isdigit()][:40],
        "rows_detail": [_row_brief(r) for r in rows[:40]
                        if isinstance(r, dict)],
        "seconds": round(time.monotonic() - started, 2),
    })
    out["bundle"] = await _capture_bundle(svc, final, query, 0, "")
    return out


def _sql(conn_path, sql_text, params=()):
    try:
        con = sqlite3.connect("file:%s?mode=ro" % conn_path, uri=True)
        try:
            return con.execute(sql_text, params).fetchall()
        finally:
            con.close()
    except Exception as exc:             # noqa: BLE001
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
    out: dict = {}
    out["messages_by_year"] = _pairs(
        conn_path,
        "SELECT strftime('%Y', datetime(timestamp,'unixepoch')) AS y, "
        "COUNT(*) FROM smart_messages WHERE chat_id=? GROUP BY y ORDER BY y",
        (CHAT,))
    out["messages_total"] = _scalar(
        conn_path, "SELECT COUNT(*) FROM smart_messages WHERE chat_id=?", (CHAT,))
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
    return out


def _year_in_tz(ts, iana: str):
    try:
        value = int(ts)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    import datetime
    import zoneinfo
    moment = datetime.datetime.fromtimestamp(value, datetime.timezone.utc)
    try:
        return int(moment.astimezone(zoneinfo.ZoneInfo(iana or "UTC")).year)
    except Exception:                    # noqa: BLE001
        return int(moment.year)


def _overview_coverage_check(conn_path, overview: dict | None,
                             iana: str) -> dict:
    """Independent SQL projection of the same documented episode window.

    Window rule of `list_episode_views` (bounded cap 200):
    `WHERE chat_id=? ORDER BY updated_at DESC, episode_id LIMIT 200`;
    period = year of `COALESCE(event_end_ts, event_start_ts)` in chat tz.
    """
    out: dict = {"status": "no_overview"}
    if not overview:
        return out
    rows = _sql(conn_path,
                "SELECT episode_id, event_start_ts, event_end_ts "
                "FROM mca_episodes WHERE chat_id=? "
                "ORDER BY updated_at DESC, episode_id LIMIT 200", (CHAT,))
    if isinstance(rows, str):
        out["status"] = rows
        return out
    sql_years: dict[str, int] = {}
    unknown = 0
    ids = set()
    for episode_id, start_ts, end_ts in rows:
        ids.add(str(episode_id))
        year = _year_in_tz(end_ts if end_ts else start_ts, iana)
        if year is None:
            unknown += 1
            continue
        key = str(year)
        sql_years[key] = sql_years.get(key, 0) + 1
    coverage = overview.get("coverage") or {}
    claimed = {str(block.get("period")): int(block.get("episodes") or 0)
               for block in coverage.get("present_periods") or ()}
    refs = [str(value) for value in (overview.get("episode_refs") or ())]
    refs_all = _sql(
        conn_path,
        "SELECT episode_id FROM mca_episodes WHERE chat_id=? AND episode_id "
        "IN (%s)" % ",".join("?" for _ in refs), (CHAT, *refs)) if refs else []
    refs_present = ([] if isinstance(refs_all, str)
                    else {str(row[0]) for row in refs_all})
    out.update({
        "status": "checked",
        "window_rows": len(rows),
        "sql_periods": dict(sorted(sql_years.items())),
        "sql_unknown_time": unknown,
        "claimed_periods": dict(sorted(claimed.items())),
        "claimed_unknown_time": coverage.get(
            "unknown_time_episode_refs"),
        "periods_match": dict(sorted(sql_years.items())) == dict(
            sorted(claimed.items())),
        "unknown_match": unknown == int(
            coverage.get("unknown_time_episode_refs") or 0),
        "claimed_periods_not_in_sql": sorted(
            set(claimed) - set(sql_years)),
        "sql_periods_not_claimed": sorted(set(sql_years) - set(claimed)),
        "episode_refs_checked": len(refs),
        "episode_refs_absent": sorted(set(refs) - refs_present),
        "independent_subset_ok": set(
            str(value) for value in (overview.get("independent_periods") or ())
        ) <= set(claimed),
        "complete_claimed": coverage.get("complete"),
    })
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
        "gates": {
            "evidence_bundle": bool(mca_gates.evidence_bundle_enabled()),
            "episodes": bool(mca_gates.episodes_enabled()),
            "is_history_query": hasattr(mca, "is_history_query"),
            "resolve_period_intent": hasattr(mca, "resolve_period_intent"),
            "wants_overview": hasattr(
                getattr(mca, "PeriodIntent", object), "wants_overview"),
        },
        "config": {
            "effective": cfg.get("effective"),
            "defaults": cfg.get("defaults"),
            "pg": cfg.get("pg"),
            "chat_overrides": cfg.get("chat"),
            "env_flags": cfg.get("env_flags"),
            "model_identity": cfg.get("model_identity"),
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
    except Exception as exc:             # noqa: BLE001
        vec["ok"] = False
        vec["reason"] = type(exc).__name__
    vec["available"] = getattr(memory, "_vec_available", None)
    vec["off_reason"] = getattr(memory, "_vec_off_reason", None)
    print("VEC " + json.dumps(vec), flush=True)

    aliases, alias_mode = await _aliases_or_stub()
    svc = DirectChatService(memory, db, llm, aliases)
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
        "constants": {
            "period_min_stems": getattr(
                DirectChatService, "_RAG_PERIOD_MIN_STEMS", None),
            "period_slot_div": getattr(
                DirectChatService, "_RAG_PERIOD_SLOT_DIV", None),
            "period_channels": list(getattr(
                DirectChatService, "_RAG_PERIOD_CHANNELS", ()) or ()),
            "period_pool": getattr(
                DirectChatService, "_RAG_PERIOD_POOL", None),
            "overview_version": getattr(mca, "OVERVIEW_VERSION", None),
            "overview_max_episodes": getattr(
                mca, "OVERVIEW_MAX_EPISODES", None),
            "history_markers": list(getattr(mca, "_HISTORY_MARKERS", ()) or ()),
            "period_history_markers": list(
                getattr(mca, "_PERIOD_HISTORY_MARKERS", ()) or ()),
        },
        "queries": {
            "A1_creative_owner": CREATIVE_OWNER,
            "A1P_plain_twin": PLAIN_TWIN,
            "D_conflict_2023": CONFLICT_2023,
            "T2_event_no_year": event_q,
            "T3_current": current_q,
            "P1_profile_reply": person_q,
            "E_relations_years": RELATIONS,
        },
        "triggers": {},
        "classes": {},
        "plan_flows": {},
        "sql": {},
        "errors": [],
    }

    # ── trigger matrix: baseline heuristic vs structured PeriodIntent ──────
    for key, query in out["queries"].items():
        item = {"query": redact(query)}
        try:
            if hasattr(mca, "is_history_query"):
                item["baseline_is_history_query"] = bool(
                    mca.is_history_query(query))
            intent = mca.resolve_period_intent(query, memory_scope="auto")
            item["intent_auto"] = _period_intent_view(intent)
            intent_plan = None
            if _accepts(mca.resolve_period_intent, "plan_act"):
                intent_plan = mca.resolve_period_intent(
                    query, memory_scope="auto", plan_act="historical_recall")
            item["intent_plan_historical_recall"] = _period_intent_view(
                intent_plan)
            item["intent_historical_scope"] = _period_intent_view(
                mca.resolve_period_intent(query, memory_scope="historical"))
        except Exception as exc:         # noqa: BLE001
            item["error"] = "%s:%s" % (type(exc).__name__, str(exc)[:160])
        out["triggers"][key] = item

    # ── required classes (same query set as the Slice B probe) ─────────────
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
                svc, key, query, tail, redact, entities, **extra)
        except Exception as exc:         # noqa: BLE001
            out["errors"].append({"stage": key, "error": type(exc).__name__,
                                  "text": str(exc)[:400],
                                  "tb": traceback.format_exc()[-900:]})
        print("CLASS_DONE %s" % key, flush=True)

    for key, query, act in (
            ("T2_plan_historical_recall", event_q, "historical_recall"),
            ("T3_current_plan_historical_recall", current_q,
             "historical_recall")):
        try:
            out["plan_flows"][key] = await measure_plan_flow(
                svc, key, query, act, redact)
        except Exception as exc:         # noqa: BLE001
            out["errors"].append({"stage": key, "error": type(exc).__name__,
                                  "text": str(exc)[:400],
                                  "tb": traceback.format_exc()[-900:]})
        print("PLAN_DONE %s" % key, flush=True)

    # ── copy-level counters + overview coverage vs independent SQL ─────────
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
    try:
        iana, tz_source = await mca_episodes._view_timezone(CHAT)
    except Exception:                    # noqa: BLE001
        iana, tz_source = "UTC", "error"
    out["sql"]["chat_timezone"] = {"iana": iana, "source": tz_source}
    out["sql"]["overview_coverage_check"] = {}
    for key, item in list(out["classes"].items()) + list(
            out["plan_flows"].items()):
        out["sql"]["overview_coverage_check"][key] = _overview_coverage_check(
            DBPATH, item.get("overview_on_result"), iana)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("WROTE " + OUT + " bytes=%s" % os.path.getsize(OUT), flush=True)
    await db.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:                    # noqa: BLE001
        traceback.print_exc()
        sys.exit(3)
