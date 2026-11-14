# -*- coding: utf-8 -*-
"""VMQ-MEM / VMQ-MEM-TIME evidence probe (read-only).

Runs ON the production host, but against a CANDIDATE/BASELINE checkout clone and
a COPY of local_database.db. It never writes to live data, never restarts a
unit, never sends a message and never commits anything.

Per formulation class it records the REAL product path, not answer text:
  * every `mca_retrieval_context.retrieve()` call made by the RAG block
    (request fields, status/reason, channels, candidate pool, fact rows,
    period-fill counters, relevance decision, relations, M2 overview);
  * the `<RAG_Memory>` block the Writer would receive (size, years, topic
    support, period stats, row meta) — text is redacted and never stored;
  * the `<Old_Episode>` block from the real
    `DirectChatService._build_old_episodes` (chars, blocks, messages, spans);
  * participant profile / person overview tool envelopes (year histogram);
  * `dig_into_lore` coverage for plain and year-windowed calls.

Output is anonymised: the participant name becomes P1, the event token E1.
"""
from __future__ import annotations

import asyncio
import hashlib
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
CLONE = os.environ.get("VMQ_CLONE", "/root/vmq2/measure/repo-base")
DBPATH = os.environ.get("VMQ_DB", "/root/vmq2/measure/dbcopy.db")
OUT = os.environ.get("VMQ_OUT", "/root/vmq2/measure/out/base.json")
ENT = os.environ.get("VMQ_ENT", "/root/vmq2/measure/entities.json")
CFG = os.environ.get("VMQ_CFG", "/root/vmq2/measure/cfg.json")
APP = "/var/www/admin_bot"
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
from services.summary_memory import MemoryManager, build_fts_query  # noqa: E402
from services.tool_router import ToolContext, ToolDeps, ToolRouter  # noqa: E402

Y2023 = (1672531200, 1704067199)
Y2024 = (1704067200, 1735689599)
Y2026 = (1767225600, 1798761599)
ISO = re.compile(r"\b(20\d{2})-\d{2}-\d{2}\b|\b\d{2}\.\d{2}\.(20\d{2})\b")

# ── formulation classes: frozen before the run, identical for A and B ────────
CREATIVE_OWNER = "напиши юмористический рассказ об основных шизах конфы"
CREATIVE_GENERIC = ("расскажи смешную историю про наши шутки и приколы "
                    "за все годы")
PLAIN_TWIN = "что за шизы были на конфе?"
RETELL = "перескажи, о чём мы говорили в этом чате за все годы"
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


def _request_view(request) -> dict:
    keys = ("chat_id", "query", "mode", "purpose", "top_k", "channels",
            "scope", "include_overview", "memory_scope", "period_fill",
            "exclude_years", "include_archived", "preserve_channel_order",
            "intent", "subject_names", "subject_entity_ids")
    out = {}
    for key in keys:
        value = getattr(request, key, "<none>")
        if key == "query":
            continue
        if isinstance(value, tuple):
            value = list(value)
        out[key] = value
    return out


def _result_view(result, redact, entities) -> dict:
    cands = list(getattr(result, "candidates", ()) or ())
    by_type: dict[str, int] = {}
    for cand in cands:
        by_type[cand.entity_type] = by_type.get(cand.entity_type, 0) + 1
    facts = list(getattr(result, "fact_rows", ()) or ())
    relations = list(getattr(result, "relations", ()) or ())
    relevance = getattr(result, "relevance", None)
    overview = getattr(result, "overview", None)
    person_uid = str(((entities.get("person") or {}).get("uid")) or "")
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
    rel_rows = []
    for item in relations[:20]:
        rel_rows.append({
            "edge": bool(item.get("edge_id")),
            "fact": bool(item.get("fact_id")),
            "origin": item.get("origin"),
            "unsupported": bool(item.get("has_unsupported_sources")),
            "ts": year_of(item.get("ts")),
            "direction": item.get("direction"),
            "weight": item.get("weight"),
        })
    out = {
        "status": getattr(result, "status", None),
        "reason_code": getattr(result, "reason_code", None),
        "mode": getattr(result, "mode", None),
        "purpose": getattr(result, "purpose", None),
        "channels_used": list(getattr(result, "channels_used", ()) or ()),
        "candidates": len(cands),
        "by_type": by_type,
        "candidate_years": hist([year_of(c.sent_at) for c in cands]),
        "episode_years": hist([year_of(c.sent_at) for c in cands
                               if c.entity_type == "episode"]),
        "top": rows,
        "fact_rows": len(facts),
        "fact_years": hist(fact_years),
        "fact_rows_meta": [{
            "year": year_of((row or {}).get("rag_ts")
                            or (row or {}).get("message_timestamp")),
            "origin": (row or {}).get("origin"),
            "period_fill": bool((row or {}).get("period_fill")),
            "proxy": (row or {}).get("subject_proxy"),
            "target_is_p1": str((row or {}).get("target_user") or "") in
                            {person_uid, "P1"},
            "attributed": not bool((row or {}).get("unattributed")),
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
        "relations_meta": rel_rows,
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
            "semantic_hints": [hint.get("kind") for hint in
                               (data.get("semantic_hints") or ())],
            "period_support": len(data.get("period_support") or ()),
        }
        try:
            slots = mca.overview_bundle_slots(overview)
            out["overview_slots"] = {
                "coverage": [redact(line)[:140] for line
                             in (slots.get("coverage") or ())],
                "independent_periods": list(
                    slots.get("independent_periods") or ()),
                "counterexamples": len(slots.get("counterexamples") or ()),
                "limitations": list(slots.get("limitations") or ()),
            }
        except Exception:              # noqa: BLE001
            out["overview_slots_error"] = True
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
    person_uid = str(((entities.get("person") or {}).get("uid")) or "")
    years = []
    for fact in facts:
        year = None
        if isinstance(fact, dict):
            for key in ("ts", "time", "date", "sent_at", "created_at"):
                year = year_of(fact.get(key))
                if year:
                    break
            if not year:
                match = ISO.search(json.dumps(fact, ensure_ascii=False))
                if match:
                    year = int(match.group(1) or match.group(2))
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
        "overview_slots": bool(payload.get("coverage")),
        "coverage_lines": [redact(line)[:140] for line
                           in (payload.get("coverage") or ())][:8],
        "counterexamples": len(payload.get("counterexamples") or ()),
        "limitations": [str(code) for code
                        in (payload.get("limitations") or ())][:8],
        "sources": len(payload.get("sources") or ()),
        "fact_target_is_p1": sum(
            1 for fact in facts if isinstance(fact, dict)
            and str(fact.get("target_user") or "") in {person_uid, "P1"}),
    }


def _dig_view(raw: str) -> dict:
    try:
        payload = json.loads(raw or "{}")
    except Exception:                  # noqa: BLE001
        payload = {}
    coverage = payload.get("coverage") or {}
    return {
        "status": payload.get("status"),
        "coverage": coverage,
        "sampling": coverage.get("sampling") if isinstance(coverage, dict)
                    else None,
        "messages_total": coverage.get("messages_total")
                          if isinstance(coverage, dict) else None,
        "messages_shown": coverage.get("messages_shown")
                          if isinstance(coverage, dict) else None,
        "truncated": coverage.get("truncated") if isinstance(coverage, dict)
                     else None,
        "first_seen": coverage.get("first_seen") if isinstance(coverage, dict)
                      else None,
        "last_seen": coverage.get("last_seen") if isinstance(coverage, dict)
                     else None,
        "snippets": len(payload.get("snippets") or ()),
        "facts": len(payload.get("facts") or ()),
        "total_mentions": payload.get("total_mentions"),
    }


async def measure_query(db, memory, svc, router, key, query, tail, redact,
                        entities) -> dict:
    started = time.monotonic()
    out: dict = {"class": key, "query": redact(query),
                 "history_query": bool(mca.is_history_query(query))}
    stub = SimpleNamespace(text=query, chat_id=CHAT, message_id=0)
    captured: dict = {}
    orig_rows = svc._rag_unified_rows

    async def rows_spy(*args, **kwargs):
        got = await orig_rows(*args, **kwargs)
        captured["rows"] = got
        captured["period_stats"] = dict(
            getattr(svc, "_rag_period_stats", None) or {})
        captured["memory_scope"] = kwargs.get("memory_scope")
        return got

    svc._rag_unified_rows = rows_spy
    with RetrieveSpy(redact, entities) as spy:
        try:
            block, hint = await asyncio.wait_for(
                svc._build_rag_block(CHAT, stub, "", memory_scope=None), 240)
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
        "period_stats": captured.get("period_stats"),
        "memory_scope": captured.get("memory_scope"),
        "block_topic": {
            "shiz": (block or "").casefold().count("шиз"),
            "konfa": (block or "").casefold().count("конф"),
        },
        "retrieve_calls": len(spy.calls),
        "retrieve": spy.calls,
    }

    # ── real <Old_Episode> (same call the live turn makes) ────────────────
    ep_started = time.monotonic()
    ep_calls = []
    with RetrieveSpy(redact, entities) as ep_spy:
        try:
            ep_block, ep_stats = await asyncio.wait_for(
                svc._build_old_episodes(CHAT, query, tail, {}, None, None),
                240)
        except Exception as exc:       # noqa: BLE001
            ep_block, ep_stats = "", {"error": type(exc).__name__}
            out["old_episode_error"] = {"error": type(exc).__name__,
                                        "text": str(exc)[:300]}
    ep_calls = ep_spy.calls
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
        "spans": spans,
        "block_years": block_years(ep_block or "", redact),
        "topic": {
            "shiz": (ep_block or "").casefold().count("шиз"),
            "konfa": (ep_block or "").casefold().count("конф"),
            "conflict": sum((ep_block or "").casefold().count(stem)
                            for stem in CONFLICT_MARK),
        },
        "retrieve_calls": len(ep_calls),
        "retrieve": ep_calls[:2],
    }
    out["caps"] = {"episode_max_count": composer.episode_max_count(),
                   "episode_max_messages": composer.episode_max_messages(),
                   "episode_gap_seconds": composer.episode_gap_seconds()}
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

    queries = {
        "A1_creative_owner": CREATIVE_OWNER,
        "A1P_plain_twin": PLAIN_TWIN,
        "A2_creative_generic": CREATIVE_GENERIC,
        "B_retell": RETELL,
        "C_person_profile": person_q,
        "D_conflict_2023": CONFLICT_2023,
        "E_relations_years": RELATIONS,
        "T2_event_no_year": event_q,
        "T3_current_state": current_q,
    }
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
        "overview_api": hasattr(mca, "build_retrieval_overview"),
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
        },
        "classes": {},
        "probes": {},
        "sql": {},
        "errors": [],
    }

    for key, query in queries.items():
        try:
            out["classes"][key] = await measure_query(
                db, memory, svc, router, key, query, tail, redact, entities)
        except Exception as exc:       # noqa: BLE001
            out["errors"].append({"stage": key, "error": type(exc).__name__,
                                  "text": str(exc)[:300],
                                  "tb": traceback.format_exc()[-900:]})
        print("CLASS_DONE %s" % key, flush=True)

    # ── profile envelopes (TIME-02: several periods, not freshest 10) ─────
    for purpose in ("biography", "general"):
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

    # ── dig: plain and year-windowed (TIME-03/04) ─────────────────────────
    for name, args in (
            ("event_no_year", {"query": event_q, "mode": "messages"}),
            ("event_year_2023", {"query": event_q, "mode": "messages",
                                 "year": 2023}),
            ("current_no_year", {"query": current_q, "mode": "messages"}),
            ("conflict_year_2023", {"query": CONFLICT_2023,
                                    "mode": "messages", "year": 2023})):
        try:
            started = time.monotonic()
            raw = await asyncio.wait_for(
                router._dig_into_lore(args,
                                      ToolContext(CHAT, args["query"],
                                                  user_id=None)),
                timeout=180)
            view = _dig_view(raw)
            view["seconds"] = round(time.monotonic() - started, 2)
            out["probes"]["dig_%s" % name] = view
        except Exception as exc:       # noqa: BLE001
            out["errors"].append({"stage": "dig_%s" % name,
                                  "error": type(exc).__name__,
                                  "text": str(exc)[:300]})
        print("DIG_DONE %s" % name, flush=True)

    # ── relations channel (MEM-03: fabricated relations) ──────────────────
    try:
        with RetrieveSpy(redact, entities) as spy:
            await mca.retrieve(db, memory, mca.RetrievalRequest(
                chat_id=CHAT, query=RELATIONS, mode="auto",
                purpose="relationships", top_k=10, reply_depth=0,
                channels=(), include_relations=True))
        out["probes"]["relations_channel"] = spy.calls
    except Exception as exc:           # noqa: BLE001
        out["errors"].append({"stage": "relations_channel",
                              "error": type(exc).__name__,
                              "text": str(exc)[:300]})
    print("RELATIONS_DONE", flush=True)

    # ── corpus support (counters only, no text) ───────────────────────────
    def sql(sql_text, params=()):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % DBPATH, uri=True)
            try:
                return con.execute(sql_text, params).fetchall()
            finally:
                con.close()
        except Exception as exc:       # noqa: BLE001
            return "err:%s" % type(exc).__name__

    def scalar(sql_text, params=()):
        got = sql(sql_text, params)
        if isinstance(got, str):
            return got
        return got[0][0] if got else None

    def pairs(sql_text, params=()):
        got = sql(sql_text, params)
        if isinstance(got, str):
            return got
        return [{"k": str(a), "n": int(b)} for a, b in got]

    out["sql"]["messages_by_year"] = pairs(
        "SELECT strftime('%Y', datetime(timestamp,'unixepoch')) AS y, "
        "COUNT(*) FROM smart_messages WHERE chat_id=? GROUP BY y ORDER BY y",
        (CHAT,))
    out["sql"]["messages_total"] = scalar(
        "SELECT COUNT(*) FROM smart_messages WHERE chat_id=?", (CHAT,))
    out["sql"]["messages_span"] = {
        "min": scalar("SELECT MIN(timestamp) FROM smart_messages "
                      "WHERE chat_id=?", (CHAT,)),
        "max": scalar("SELECT MAX(timestamp) FROM smart_messages "
                      "WHERE chat_id=?", (CHAT,)),
    }
    out["sql"]["graph_facts_by_year"] = pairs(
        "SELECT strftime('%Y', datetime(COALESCE(message_timestamp, "
        "created_at),'unixepoch')) AS y, COUNT(*) FROM graph_facts "
        "WHERE chat_id=? GROUP BY y ORDER BY y", (CHAT,))
    out["sql"]["episodes_by_year"] = pairs(
        "SELECT strftime('%Y', datetime(event_start_ts,'unixepoch')) AS y, "
        "COUNT(*) FROM mca_episodes WHERE chat_id=? GROUP BY y ORDER BY y",
        (CHAT,))
    out["sql"]["episodes_total"] = scalar(
        "SELECT COUNT(*) FROM mca_episodes WHERE chat_id=?", (CHAT,))
    out["sql"]["person"] = {
        "msgs_2023_2024": int(person.get("msgs_2023_2024") or 0),
        "msgs_2026": int(person.get("msgs_2026") or 0),
        "msgs_by_year": pairs(
            "SELECT strftime('%Y', datetime(timestamp,'unixepoch')) AS y, "
            "COUNT(*) FROM smart_messages WHERE chat_id=? AND user_id=? "
            "GROUP BY y ORDER BY y", (CHAT, person.get("uid"))),
    }
    uid = str(person.get("uid") or "")
    out["sql"]["person_facts_by_year"] = pairs(
        "SELECT strftime('%Y', datetime(COALESCE(message_timestamp, "
        "created_at),'unixepoch')) AS y, COUNT(*) FROM graph_facts "
        "WHERE chat_id=? AND (target_user=? OR target_user=? OR "
        "subject_ref_id=?) GROUP BY y ORDER BY y",
        (CHAT, person.get("name"), uid, uid))
    out["sql"]["shiz_msgs_by_year"] = pairs(
        "SELECT strftime('%Y', datetime(timestamp,'unixepoch')) AS y, "
        "COUNT(*) FROM smart_messages WHERE chat_id=? AND lower(text) "
        "LIKE '%шиз%' GROUP BY y ORDER BY y", (CHAT,))
    out["sql"]["conflict_msgs_by_year"] = pairs(
        "SELECT strftime('%Y', datetime(timestamp,'unixepoch')) AS y, "
        "COUNT(*) FROM smart_messages WHERE chat_id=? AND (lower(text) "
        "LIKE '%ссор%' OR lower(text) LIKE '%ругал%' OR lower(text) "
        "LIKE '%скандал%') GROUP BY y ORDER BY y", (CHAT,))
    out["sql"]["event_counts"] = event

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
