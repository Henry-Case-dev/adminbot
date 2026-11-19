#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TIME-03 natural memory - real-archive S1-S7 acceptance harness.

Evidence tooling only. It does NOT import or edit product code until the
requested `--code-root` has been validated and inserted on sys.path, and it
never writes to the snapshot: the DB is opened with SQLite `mode=ro` and its
sha256 is compared before/after.

Vendored primitives (`mem07_lib.py`, `measure_effective_config.py`,
`make_fixture.py`) are copied from the independent MEM-07 harness commit
1bdd8d360. They provide:
  * read-only snapshot metadata and sha256;
  * failing LLM/embedding stubs and a socket egress block;
  * archive-derived deterministic references (participants/topics/anchors);
  * the existing product memory path (`_rag_unified_rows`, `_build_rag_block`,
    `_build_old_episodes`, `_build_evidence_bundle`, `payload_builder`).

Scenario references are built from the snapshot itself, not from handwritten
fact ids. Output contains only ids/years/hashes/counts/codes: no message text,
fact text or display names. No year-share is used as a success metric.

Run baseline and candidate separately (same snapshot, same effective config):
  py time03_scenarios.py --variant baseline  --db ... --chat-id ... \
     --code-root <baseline-worktree> --effective-config effective.json --out ...
  py time03_scenarios.py --variant candidate --db ... --chat-id ... \
     --code-root <candidate-worktree> --effective-config effective.json --out ...
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import measure_effective_config as _effective  # noqa: E402
import mem07_lib as _base  # noqa: E402

BASELINE_SHA = "0fce97a14338521a24d94f560e896ebcb19f9492"
CANDIDATE_SHA = "357b3f4eb03412527f526078faa4babeac25cea5"
SCHEMA = "vmq-time03-scenarios/2"
EXPECTED_SCHEMA = 48
CURRENT_YEAR = 2026
MAX_REPORTED_ITEMS = 200
CONFLICT_TERMS = ("ссор", "ругал", "конфликт", "спор")
S7_YEAR = 2019
S7_TOKEN = "zztime03missingcue"

#: Product trees that must be clean in the supplied code root.
PRODUCT_PATHS = ("services", "config", "handlers", "web", "tools")


def sha256_text(value) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def git_out(cwd: str, *args) -> str:
    proc = subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        raise RuntimeError("git_failed:%s" % " ".join(args))
    return proc.stdout.strip()


def product_tree_clean(code_root: Path) -> tuple[bool, str]:
    try:
        out = git_out(str(code_root), "status", "--porcelain", "--",
                      *PRODUCT_PATHS)
    except Exception:
        return False, "product_status_error"
    return (not bool(out.strip()),
            "" if not out.strip() else "product_tree_dirty")


def ensure_code_root(code_root: Path, variant: str, expected_sha: str) -> str:
    if not (code_root / "services" / "direct_chat_service.py").is_file():
        raise RuntimeError("code_root_missing_services")
    head = git_out(str(code_root), "rev-parse", "HEAD")
    expected = BASELINE_SHA if variant == "baseline" else CANDIDATE_SHA
    if expected_sha:
        expected = expected_sha
    if head != expected:
        raise RuntimeError("code_root_sha_mismatch")
    clean, reason = product_tree_clean(code_root)
    if not clean:
        raise RuntimeError(reason)
    return head


def load_effective(path: str, *, fixture: bool,
                   code_root: str | None = None) -> dict:
    if fixture and not path:
        raw = asyncio.run(_effective.measure(
            settings_only=True, code_root=code_root))
        raw["file_sha256"] = sha256_text(json.dumps(
            raw, ensure_ascii=False, sort_keys=True))
        return _base.validate_effective_provenance(
            raw, "fixture_settings_only", raw["file_sha256"], fixture=True)
    if not path:
        raise _base.ConfigProvenanceError("effective_config_required")
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    file_sha = _base.sha256_file(path)
    source = "effective_config_file"
    result = _base.validate_effective_provenance(
        raw, source, file_sha, fixture=fixture)
    if not fixture:
        if result.get("settings_only"):
            raise _base.ConfigProvenanceError("settings_only_not_production")
        if not result.get("hot_config_measured"):
            raise _base.ConfigProvenanceError("hot_config_not_measured")
    return result


def effective_values(measured: dict) -> tuple[bool, int]:
    values = measured.get("effective") or {}
    return (bool(values.get("flags.graph_rag_enabled")),
            int(values.get("limits.graph_rag_facts_limit") or 0))


def compact_anchor(anchor: dict) -> dict:
    return {
        "kind": anchor.get("kind"),
        "id": anchor.get("id"),
        "year": anchor.get("year"),
        "ref": anchor.get("ref"),
        "refs": list(anchor.get("refs") or ()),
    }


def compact_ref(ref: dict) -> dict:
    return {
        "key": ref.get("key"),
        "mode": ref.get("mode"),
        "expected_years": list(ref.get("expected_years") or ()),
        "counts": dict(ref.get("counts") or {}),
        "reference_sha256": ref.get("reference_sha256"),
        "not_executed": ref.get("not_executed"),
        "subject": ref.get("subject"),
        "terms": list(ref.get("terms") or ()),
        "required_match": str(ref.get("required_match") or "all"),
        "validation": dict(ref.get("validation") or {}),
        "anchors": [compact_anchor(a) for a in (ref.get("anchors") or ())],
        "old_anchors": [compact_anchor(a)
                        for a in (ref.get("old_anchors") or ())],
    }


def _pick(anchors: list, limit: int = 1) -> list:
    return list(anchors or ())[:max(1, int(limit))]


async def _make_ref(builder, key: str, years: list, terms=(), *, person=None,
                    and_terms=(), per_year: int = 1, mode: str = "custom",
                    kind: str = "any", required_match: str = "all") -> dict:
    years = sorted({int(y) for y in years})
    support = await builder.support_years(terms, "or", person, and_terms)
    anchors = []
    by_year = {}
    for year in years:
        facts = await builder._fact_anchors(terms, year, and_terms, person)
        messages = await builder._message_anchors(terms, year, and_terms,
                                                  person)
        facts = builder._select(facts, "fact")
        messages = builder._select(messages, "message")
        if kind == "message":
            picked = _pick(messages, per_year)
        elif kind == "fact":
            picked = _pick(facts, per_year)
        else:
            picked = _pick(facts, per_year) or _pick(messages, per_year)
        anchors.extend(picked)
        by_year[str(year)] = {
            "facts": len(facts), "messages": len(messages),
            "picked": len(picked)}
    out = {
        "key": key, "mode": mode, "expected_years": years,
        "terms": [str(term) for term in (terms or ())],
        "required_match": str(required_match or "all"),
        "anchors": anchors,
        "counts": {"facts": sum(1 for a in anchors if a["kind"] == "fact"),
                   "messages": sum(1 for a in anchors if a["kind"] == "message"),
                   "by_year": by_year},
        "support": support, "reference_sha256": sha256_text(json.dumps(
            {"anchors": [{"kind": a["kind"], "id": a["id"],
                          "year": a["year"], "ref": a["ref"]}
                         for a in anchors],
             "expected_years": years,
             "terms": [str(term) for term in (terms or ())],
             "required_match": str(required_match or "all")},
            ensure_ascii=False, sort_keys=True)),
        "not_executed": None, "as_of": builder.as_of, "subject": None,
    }
    if person:
        out["subject"] = {"pseudo": "participant",
                          "uid_sha256": sha256_text(person[1]),
                          "name_sha256": sha256_text(person[0])}
    if not years:
        out["not_executed"] = "reference_support_low"
    elif not anchors:
        out["not_executed"] = "reference_empty"
    return out


async def _select_s6(builder) -> dict:
    """Two similar conflict periods; cue unique to the older one."""
    support = await builder.support_years(CONFLICT_TERMS, "or")
    years = sorted(int(y) for y in support
                   if support[y].get("messages", 0) >= 2)
    if len(years) < 2:
        return {"not_executed": "similar_episode_pair_unavailable"}
    correct_year, decoy_year = years[0], years[-1]
    correct_msgs = await builder._message_anchors(
        CONFLICT_TERMS, correct_year)
    decoy_msgs = await builder._message_anchors(CONFLICT_TERMS, decoy_year)
    if len(correct_msgs) < 2 or len(decoy_msgs) < 2:
        return {"not_executed": "similar_episode_pair_unavailable"}
    phrase = None
    for anchor in builder._select(correct_msgs, "message"):
        rows = await builder._rows(
            "SELECT text FROM smart_messages WHERE id=? AND chat_id=?",
            (int(anchor["id"]), builder.chat_id))
        text = str((rows[0] if rows else {}).get("text") or "")
        tokens = re.findall(r"[0-9A-Za-zА-Яа-яЁё]{4,}", text)
        for left, right in zip(tokens, tokens[1:]):
            try:
                cur = await builder._rows(
                    "SELECT COUNT(*) AS n FROM smart_messages_fts "
                    "JOIN smart_messages m ON m.id=smart_messages_fts.rowid "
                    "WHERE smart_messages_fts MATCH ? AND m.chat_id=? "
                    "AND m.timestamp>=? AND m.timestamp<?",
                    ('"%s %s"' % (left, right), builder.chat_id,
                     *_base.utc_bounds(correct_year)))
                n_correct = int((cur[0] if cur else {}).get("n") or 0)
                cur = await builder._rows(
                    "SELECT COUNT(*) AS n FROM smart_messages_fts "
                    "JOIN smart_messages m ON m.id=smart_messages_fts.rowid "
                    "WHERE smart_messages_fts MATCH ? AND m.chat_id=? "
                    "AND m.timestamp>=? AND m.timestamp<?",
                    ('"%s %s"' % (left, right), builder.chat_id,
                     *_base.utc_bounds(decoy_year)))
                n_decoy = int((cur[0] if cur else {}).get("n") or 0)
            except Exception:
                continue
            if n_correct and not n_decoy:
                phrase = "%s %s" % (left, right)
                break
        if phrase:
            break
    if not phrase:
        return {"not_executed": "distinctive_cue_unavailable"}
    correct = await _make_ref(builder, "s6_correct", [correct_year],
                              CONFLICT_TERMS, per_year=2, mode="episode",
                              kind="message")
    decoy = await _make_ref(builder, "s6_decoy", [decoy_year],
                            CONFLICT_TERMS, per_year=2, mode="episode",
                            kind="message")
    if correct.get("not_executed") or decoy.get("not_executed"):
        return {"not_executed": "similar_episode_pair_unavailable"}
    correct["decoy_anchors"] = decoy.get("anchors") or []
    correct["decoy_refs"] = [a["ref"] for a in correct["decoy_anchors"]]
    correct["query"] = 'та самая история с "%s"' % phrase
    correct["correct_year"] = correct_year
    correct["decoy_year"] = decoy_year
    return correct


async def _scenario_refs(builder, participants, e1, ce, current_year):
    scenarios = []
    person = participants.get("P1")
    if person:
        support = await builder.support_years((), person=person)
        years = [int(y) for y in sorted(support)
                 if int(y) < current_year
                 and (support[y].get("facts", 0) >= 1
                      or support[y].get("messages", 0) >= 1)]
        years = years[:3]
        ref = await _make_ref(builder, "s1_person", years, person=person,
                              mode="participant")
        if len(years) < 2:
            scenarios.append({"id": "S1", "not_executed":
                              "participant_support_insufficient"})
        else:
            scenarios.append({
                "id": "S1", "scope": "auto", "plan_act": "research",
                "ref": ref, "query": "что ты знаешь про %s за всё время?"
                                     % person[0],
                "predicate": ("__subject__", "P1"),
                "person": person})
    else:
        scenarios.append({"id": "S1", "not_executed":
                          "participant_support_insufficient"})

    if e1 and e1.get("years"):
        old_year = min(int(y) for y in e1["years"])
        ref = await _make_ref(builder, "s2_old_story", [old_year],
                              e1["topic"][1], mode="year")
        scenarios.append({
            "id": "S2", "scope": "auto", "plan_act": "research",
            "ref": ref,
            "query": "помнишь, что говорили про %s, темы: %s?" % (
                e1["topic"][0], " ".join(e1["topic"][1])),
            "predicate": tuple(e1["topic"][1])})
        years = [min(int(y) for y in e1["years"]),
                 max(int(y) for y in e1["years"])]
        ref3 = await _make_ref(builder, "s3_change", sorted(set(years)),
                               e1["topic"][1], mode="year")
        if len(set(years)) < 2 or ref3.get("not_executed"):
            scenarios.append({"id": "S3", "not_executed":
                              "multi_year_support_insufficient"})
        else:
            scenarios.append({
                "id": "S3", "scope": "auto", "plan_act": "research",
                "ref": ref3,
                "query": "как менялось отношение к %s, темы: %s?" % (
                    e1["topic"][0], " ".join(e1["topic"][1])),
                "predicate": tuple(e1["topic"][1])})
    else:
        scenarios.append({"id": "S2", "not_executed":
                          "topic_support_insufficient"})
        scenarios.append({"id": "S3", "not_executed":
                          "topic_support_insufficient"})

    if ce and ce.get("years"):
        years = sorted({int(y) for y in ce["years"]})
        current = [y for y in years if y == current_year]
        ref4 = await _make_ref(builder, "s4_current", current,
                               ("вайп", "сервер"), mode="current",
                               per_year=3, required_match="any")
        old_years = [y for y in years if y < current_year]
        old_ref = await _make_ref(builder, "s4_stale", old_years,
                                  ("вайп", "сервер"), mode="year")
        ref4["old_anchors"] = old_ref.get("anchors") or []
        ref4["old_refs"] = [a["ref"] for a in ref4["old_anchors"]]
        if (ref4.get("not_executed") or old_ref.get("not_executed")
                or not ref4.get("anchors") or not old_years):
            scenarios.append({"id": "S4", "not_executed":
                              "stale_history_support_insufficient"})
        else:
            scenarios.append({
                "id": "S4", "scope": "auto", "plan_act": "",
                "ref": ref4,
                "query": "что сейчас с %s, темы: вайп сервер?" % (
                    ce.get("topic") or "сервером"),
                "predicate": ("вайп", "сервер")})
    else:
        scenarios.append({"id": "S4", "not_executed":
                          "current_state_support_insufficient"})

    s5_topic = (e1.get("topic") if e1 else ("обстановка", ("вайп", "сервер")))
    s5_terms = tuple(str(term) for term in (s5_topic[1] or ())
                     if str(term).strip()) or ("вайп", "сервер")
    s5_support = await builder.support_years(s5_terms, "or")
    s5_years = [int(y) for y in (e1.get("years") if e1 else ())
                if int(y) < current_year
                and (s5_support.get(str(y), {}).get("facts", 0) >= 2
                     or s5_support.get(str(y), {}).get("messages", 0) >= 2)]
    year = 2024 if 2024 in s5_years else (
        max(s5_years) if s5_years else 2024)
    ref5 = await _make_ref(builder, "s5_year", [year], s5_terms,
                           per_year=2, mode="year")
    if ref5.get("not_executed") or len(ref5.get("anchors") or ()) < 2:
        scenarios.append({"id": "S5", "not_executed":
                          "year_sequence_unavailable"})
    else:
        scenarios.append({
            "id": "S5", "scope": "auto", "plan_act": "",
            "ref": ref5,
            "query": "что происходило в чате в %d году про %s, темы: %s?" % (
                year, s5_topic[0], " ".join(s5_terms)),
            "predicate": ("__year__", year)})

    s6 = await _select_s6(builder)
    if s6.get("not_executed"):
        scenarios.append({"id": "S6", "not_executed": s6["not_executed"]})
    else:
        scenarios.append({
            "id": "S6", "scope": "auto", "plan_act": "",
            "ref": s6, "query": s6["query"],
            "predicate": CONFLICT_TERMS,
            "decoy_refs": s6.get("decoy_refs") or [],
            "correct_year": s6.get("correct_year")})

    ref7 = {"key": "s7_missing", "mode": "missing",
            "expected_years": [S7_YEAR], "anchors": [],
            "counts": {"facts": 0, "messages": 0, "by_year": {}},
            "reference_sha256": sha256_text("s7:%s" % S7_TOKEN),
            "not_executed": None, "as_of": builder.as_of, "subject": None}
    scenarios.append({
        "id": "S7", "scope": "auto", "plan_act": "",
        "ref": ref7,
        "query": "что было с %s в %d году?" % (S7_TOKEN, S7_YEAR),
        "predicate": ()})
    return scenarios


def _item_refs(row: dict) -> list:
    refs = []
    fact_id = _base.as_int(row.get("id"))
    if fact_id is not None:
        refs.append("fact:%d" % fact_id)
    item = str(row.get("item_id") or "")
    if item.startswith(("fact:", "tg:", "msg:")) and item not in refs:
        refs.append(item)
    tg = _base.as_int(row.get("tg_message_id"))
    if tg:
        refs.append("tg:%d" % tg)
    return refs


async def probe_scenario(svc, db, chat_id: int, spec: dict, query: str,
                         tail) -> dict:
    from html import escape as html_escape
    from services.payload_builder import build_messages
    entry = {"id": spec["id"], "scope": spec["scope"],
             "plan_act": spec.get("plan_act") or "",
             "query_sha256": sha256_text(query), "errors": []}
    try:
        rows_result = await asyncio.wait_for(svc._rag_unified_rows(
            chat_id, query, SimpleNamespace(text=query, chat_id=chat_id,
                                            message_id=0),
            memory_scope=spec["scope"], plan_act=spec.get("plan_act") or ""),
            300)
    except Exception as exc:
        entry["errors"].append("rows:%s" % type(exc).__name__)
        rows_result = None
    rows = list(rows_result or ())
    period = dict(getattr(svc, "_rag_period_stats", None) or {})
    trace = {}
    rag_block = ""
    try:
        rag_block, _hint = await asyncio.wait_for(svc._build_rag_block(
            chat_id, SimpleNamespace(text=query, chat_id=chat_id,
                                     message_id=0), "",
            memory_scope=spec["scope"], out_memory=trace,
            plan_act=spec.get("plan_act") or ""), 300)
    except Exception as exc:
        entry["errors"].append("rag:%s" % type(exc).__name__)
    ep_block = ""
    ep_stats = {}
    try:
        ep_block, ep_stats = await asyncio.wait_for(
            svc._build_old_episodes(chat_id, query, tail, {}, None, None),
            300)
    except Exception as exc:
        entry["errors"].append("episodes:%s" % type(exc).__name__)
    question = "<Current_Question>%s</Current_Question>" % html_escape(query)
    user_blocks = [b for b in (rag_block, ep_block, question) if b]
    payload = build_messages("[time03-harness-system-placeholder]",
                             user_blocks, time_line="")
    payload_text = payload[1]["content"] if len(payload) > 1 else ""
    payload_refs = []
    for ref in _base.REF_RE.findall(payload_text):
        if ref not in payload_refs:
            payload_refs.append(ref)
    bundle_status = "not_requested"
    bundle_refs = []
    try:
        bundle = await asyncio.wait_for(svc._build_evidence_bundle(
            chat_id, SimpleNamespace(text=query, chat_id=chat_id,
                                     message_id=None), query, "", None,
            user_blocks, excluded=None, chosen_intent=None,
            retrieval_result=None), 120)
        if bundle is None:
            bundle_status = "gate_off"
        else:
            bundle_status = "ok"
            for item in getattr(bundle, "evidence", ()) or ():
                ref = str(getattr(item, "entity_id", "") or "")
                if _base.REF_RE.fullmatch(ref) and ref not in bundle_refs:
                    bundle_refs.append(ref)
    except Exception as exc:
        bundle_status = "error:%s" % type(exc).__name__
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        items.append({
            "kind": "fact", "id": _base.as_int(row.get("id")),
            "refs": _item_refs(row), "year": _item_year(row),
            "text": str(row.get("fact") or ""),
            "origin": str(row.get("origin") or ""),
            "status": str(row.get("status") or ""),
            "period_fill": bool(row.get("period_fill")),
            "user_id": _base.as_int(row.get("user_id")),
            "speaker_author_id": _base.as_int(row.get("speaker_author_id")),
            "subject_ref_id": row.get("subject_ref_id"),
            "target_user": str(row.get("target_user") or ""),
        })
    ep_spans = []
    for span in (ep_stats or {}).get("spans") or ():
        refs = [str(x) for x in (span.get("source_ids") or ())]
        year_set = set()
        users = set()
        for ref in refs:
            row = await _base.resolve_message_ref(db, chat_id, ref)
            if row is None:
                continue
            year = _base.year_of(row.get("timestamp"))
            if year:
                year_set.add(year)
            uid = _base.as_int(row.get("user_id"))
            if uid is not None:
                users.add(uid)
        ep_spans.append({
            "source_count": len(set(refs)),
            "resolved": len([r for r in refs if r]),
            "first_ts": int(span.get("first_ts") or 0),
            "last_ts": int(span.get("last_ts") or 0),
            "years": sorted(year_set),
            "participants": len(users),
            "participants_sha256": sorted(sha256_text(uid) for uid in users),
            "source_refs": refs,
        })
    rag_lines = []
    for line in str(rag_block or "").splitlines():
        refs = _base.REF_RE.findall(line)
        if refs:
            rag_lines.append({"refs": refs,
                              "archive": "архив" in line,
                              "date": bool(re.search(r"20\d\d", line))})
    entry.update({
        "rows": len(rows),
        "retrieval_path": ("unified" if rows_result is not None
                           else "legacy_or_error"),
        "period_present": bool(period.get("policy")),
        "row_years": _base.hist([_item_year(r) for r in rows
                                 if isinstance(r, dict)]),
        "years": _base.hist([i["year"] for i in items]),
        "period": {
            "policy": str(period.get("policy") or ""),
            "replace_allowed": int(period.get("replace_allowed") or 0),
            "period_skipped": str(period.get("period_skipped") or ""),
            "intent": period.get("period_intent") or {},
            "intent_source": str(period.get("intent_source") or ""),
            "pool": int(period.get("selection_rows") or 0),
            "kept": int(period.get("selection_kept") or 0),
            "dropped_subject": int(period.get("rejected_subject") or 0),
            "dropped_budget": int(period.get("dropped_budget") or 0),
            "vector_leg": str(period.get("vector_leg") or ""),
            "vector_rows": int(period.get("vector_rows") or 0),
            "breadth_allowed": int(period.get("breadth_allowed") or 0),
            "breadth_reason": str(period.get("breadth_reason") or ""),
            "breadth_used": int(period.get("breadth_used") or 0),
        },
        "writer": {
            "rag_rendered": bool(rag_block),
            "rag_chars": len(rag_block or ""),
            "rag_years": dict(trace.get("years") or {}),
            "rag_source_ids": len(trace.get("source_ids") or ()),
            "episode_rendered": bool(ep_block),
            "episode_chars": len(ep_block or ""),
            "episode_messages": int((ep_stats or {}).get("messages") or 0),
            "payload_chars": len(payload_text),
            "payload_sha256": sha256_text(payload_text),
            "payload_refs": len(payload_refs),
        },
        "payload_refs": payload_refs,
        "bundle_status": bundle_status,
        "bundle_ref_count": len(bundle_refs),
        "bundle_refs": bundle_refs,
        "episode": {
            "spans": ep_spans,
            "messages": int((ep_stats or {}).get("messages") or 0),
            "year_window": (ep_stats or {}).get("year_window"),
            "period_intent": (ep_stats or {}).get("period_intent"),
        },
        "rag_lines": rag_lines,
        "_items": items,
        "_payload": payload_text,
    })
    return entry


def _item_year(row) -> int | None:
    for key in ("message_timestamp", "rag_ts", "created_at"):
        try:
            value = int(row.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            return _base.year_of(value)
    return None


def _anchor_refs(anchors) -> set:
    refs = set()
    for anchor in anchors or ():
        refs.update(anchor.get("refs") or ())
        if anchor.get("ref"):
            refs.add(anchor["ref"])
    return refs


def _metric(num, den) -> dict:
    return {"num": int(num), "den": int(den),
            "value": (float(num) / den) if den else None,
            "applicable": bool(den)}


async def _resolve_claim(db, chat_id: int, ref: str) -> dict:
    """Resolve a canonical ref, including a graph fact's tg_message_id.

    A rendered fact line can carry `tg:<message_id>` even when the imported
    row exists only in `graph_facts` (no smart_messages row). The harness must
    not count such an archive ref as fabricated; the product SourceRef is
    still an id, and the id is checked against the snapshot.
    """
    info = await _base.resolve_ref(db, chat_id, ref)
    if info.get("resolved"):
        return info
    head, rid = _base.parse_ref(ref)
    if head not in ("tg", "msg") or rid is None:
        return info
    try:
        cur = await db.db.execute(
            "SELECT id, status, tg_message_id FROM graph_facts "
            "WHERE chat_id=? AND (tg_message_id=? OR id=?) LIMIT 1",
            (int(chat_id), int(rid), int(rid)))
        row = await cur.fetchone()
    except Exception:
        row = None
    if row is None:
        return info
    info = dict(info)
    info["resolved"] = True
    info["fabricated"] = False
    if str(row["status"] or "") != "confirmed":
        info["weak"] = True
        info["reason"] = "fact_status_" + str(row["status"] or "")
    return info


async def _fetch_rows(db, sql: str, params=()):
    cur = await db.db.execute(sql, params)
    return [dict(row) for row in await cur.fetchall()]


async def validate_reference(db, chat_id: int, ref: dict, spec: dict,
                             as_of: int) -> dict:
    """Read-only reachability/eligibility audit for required anchors.

    No text or names are emitted: only ref/kind/year/reason codes and counts.
    A reference with any invalid anchor is not executed by the scenario loop.
    """
    anchors = list(ref.get("anchors") or ())
    old_anchors = list(ref.get("old_anchors") or ())
    all_anchors = anchors + old_anchors
    expected = set(int(y) for y in (ref.get("expected_years") or ()))
    terms = [str(t).lower() for t in (ref.get("terms") or ())
             if str(t).strip()]
    query = str(spec.get("query") or "").lower()
    kinds = {}
    for anchor in all_anchors:
        kinds[str(anchor.get("kind") or "")] = kinds.get(
            str(anchor.get("kind") or ""), 0) + 1
    fact_refs = [a for a in all_anchors if a.get("kind") == "fact"]
    query_terms_present = (
        all(term in query for term in terms) if terms and fact_refs else True)
    checked = []
    invalid = []
    match = _base.fs_terms(terms, "or") if terms else ""
    for anchor in all_anchors:
        reasons = []
        kind = str(anchor.get("kind") or "")
        rid = _base.as_int(anchor.get("id"))
        year = _base.as_int(anchor.get("year"))
        is_old = anchor in old_anchors
        if rid is None:
            reasons.append("missing_id")
        if expected and not is_old and year not in expected:
            reasons.append("year_not_expected")
        if rid is not None and kind == "message":
            rows = await _fetch_rows(
                db,
                "SELECT id, timestamp, user_id, tg_message_id, text "
                "FROM smart_messages WHERE id=? AND chat_id=?",
                (rid, int(chat_id)))
            if not rows:
                reasons.append("message_missing")
            else:
                row = rows[0]
                if _base.year_of(row.get("timestamp")) != year:
                    reasons.append("message_year")
                person = spec.get("person")
                if person:
                    name, uid = person
                    if (int(row.get("user_id") or 0) != int(uid)
                            and str(name).casefold()
                            not in str(row.get("text") or "").casefold()):
                        reasons.append("message_person")
                if match:
                    found = await _fetch_rows(
                        db,
                        "SELECT 1 FROM smart_messages_fts WHERE rowid=? "
                        "AND smart_messages_fts MATCH ?",
                        (rid, match))
                    if not found:
                        reasons.append("message_topic")
        elif rid is not None and kind == "fact":
            rows = await _fetch_rows(
                db,
                "SELECT id, message_timestamp, created_at, status, kind, "
                "origin, expires_at, target_user, speaker_author_id "
                "FROM graph_facts WHERE id=? AND chat_id=?",
                (rid, int(chat_id)))
            if not rows:
                reasons.append("fact_missing")
            else:
                row = rows[0]
                ts = int(row.get("message_timestamp")
                         or row.get("created_at") or 0)
                if _base.year_of(ts) != year:
                    reasons.append("fact_year")
                if str(row.get("status") or "") != "confirmed":
                    reasons.append("fact_status")
                if str(row.get("kind") or "") != "fact":
                    reasons.append("fact_kind")
                if str(row.get("origin") or "") in (
                        "bot_direct_reply", "bot_self_reply"):
                    reasons.append("fact_origin")
                expires_at = row.get("expires_at")
                if expires_at not in (None, ""):
                    try:
                        if int(expires_at) <= int(as_of):
                            reasons.append("fact_expired")
                    except (TypeError, ValueError):
                        reasons.append("fact_expiry")
                person = spec.get("person")
                if person:
                    name, uid = person
                    if (int(row.get("speaker_author_id") or 0) != int(uid)
                            and str(name).casefold() not in str(
                                row.get("target_user") or "").casefold()):
                        reasons.append("fact_person")
                if match:
                    found = await _fetch_rows(
                        db,
                        "SELECT 1 FROM graph_facts_fts WHERE rowid=? "
                        "AND graph_facts_fts MATCH ?",
                        (rid, match))
                    if not found:
                        reasons.append("fact_topic")
                if terms and not query_terms_present:
                    reasons.append("query_terms")
        else:
            reasons.append("unknown_kind")
        checked.append({"ref": anchor.get("ref"), "kind": kind,
                        "year": year, "old": is_old,
                        "valid": not reasons, "reasons": reasons})
        if reasons:
            invalid.append({"ref": anchor.get("ref"), "reason": reasons[0]})
    return {
        "valid": not invalid,
        "checked": len(checked),
        "invalid": invalid,
        "anchor_kinds": dict(sorted(kinds.items())),
        "old_checked": len(old_anchors),
        "expected_years": sorted(expected),
        "terms": terms,
        "query_terms_present": query_terms_present,
        "as_of": int(as_of),
        "anchors": checked,
    }


async def _scenario_metrics(entry, ref, spec, participants, current_year, db,
                            chat_id, elapsed_ms, retrieve_calls) -> dict:
    items = list(entry.get("_items") or ())
    anchors = list(ref.get("anchors") or ())
    expected = [int(y) for y in (ref.get("expected_years") or [])]
    expected_set = set(expected)

    fact_refs = set()
    for item in items:
        fact_refs.update(item.get("refs") or ())
    message_refs = set(entry.get("payload_refs") or ())
    for span in (entry.get("episode") or {}).get("spans") or ():
        message_refs.update(span.get("source_refs") or ())

    hits = []
    misses = []
    for anchor in anchors:
        refs = set(anchor.get("refs") or ())
        kind = str(anchor.get("kind") or "")
        universe = message_refs if kind == "message" else fact_refs
        if refs & universe:
            hits.append(anchor)
        else:
            misses.append(anchor)
    match_policy = str(ref.get("required_match") or "all")
    if match_policy == "any":
        required = _metric(1 if hits else 0, 1)
    else:
        required = _metric(len(hits), len(anchors))
    kinds = {str(a.get("kind") or ""): sum(
        1 for item in anchors if str(item.get("kind") or "") ==
        str(a.get("kind") or "")) for a in anchors}
    required.update({
        "anchor_kind": ("message" if anchors and all(
            a.get("kind") == "message" for a in anchors) else
            "fact" if anchors and all(a.get("kind") == "fact" for a in anchors)
            else "mixed" if anchors else "none"),
        "anchor_kinds": dict(sorted(kinds.items())),
        "anchor_count": len(anchors),
        "hit_refs": sorted(str(a.get("ref")) for a in hits),
        "missing_refs": sorted(str(a.get("ref")) for a in misses),
        "match_policy": match_policy,
        "universe": ("payload_plus_episode" if any(
            a.get("kind") == "message" for a in anchors) else "fact_rows"),
    })

    evidence_years = set()
    for item in items:
        year = item.get("year")
        if year:
            evidence_years.add(int(year))
    for span in (entry.get("episode") or {}).get("spans") or ():
        for year in span.get("years") or ():
            evidence_years.add(int(year))
    for year in ((entry.get("writer") or {}).get("rag_years") or {}).keys():
        try:
            evidence_years.add(int(year))
        except (TypeError, ValueError):
            continue
    delivered_years = sorted(expected_set & evidence_years)
    temporal = _metric(len(delivered_years), len(expected))
    temporal.update({
        "evidence_years": sorted(evidence_years),
        "delivered_years": delivered_years,
        "basis": "resolved_fact_rows+period_rows+episode_spans",
    })

    claims = list(entry.get("payload_refs") or ())
    unresolved = 0
    weak = 0
    cache = {}
    for claim in claims:
        if claim not in cache:
            cache[claim] = await _resolve_claim(db, chat_id, claim)
        info = cache[claim]
        if not info.get("resolved"):
            unresolved += 1
        elif info.get("weak"):
            weak += 1
    source_proof = _metric(len(claims) - unresolved, len(claims))
    source_proof.update({"unresolved": unresolved, "weak": weak})

    judged = len([i for i in items if str(i.get("text") or "").strip()])
    relevant = 0
    if spec.get("predicate"):
        for item in items:
            if not str(item.get("text") or "").strip():
                continue
            if _base._predicate_match(spec, item, ref, participants):
                relevant += 1
    if not spec.get("predicate"):
        relevance = {"num": 0, "den": judged, "value": None,
                     "applicable": False}
    else:
        relevance = _metric(relevant, judged)

    episode = _episode_metric(entry, ref, spec)
    attribution = {"num": 0, "den": 0, "value": None, "applicable": False}
    person = spec.get("person")
    if person:
        uid = int(person[1])
        attributed = [i for i in items
                      if i.get("speaker_author_id") is not None
                      or i.get("user_id") is not None]
        matched = [i for i in attributed
                   if _base.as_int(i.get("speaker_author_id")) == uid
                   or _base.as_int(i.get("user_id")) == uid
                   or str(i.get("subject_ref_id") or "") == str(uid)]
        attribution = _metric(len(matched), len(attributed))
        if episode.get("applicable"):
            first = ((entry.get("episode") or {}).get("spans") or [{}])[0]
            subject = bool(first.get("subject_participant"))
            attribution = _metric(1 if subject else 0, 1)
            attribution["basis"] = "episode_first_span_subject"
            attribution["fact_attribution"] = {
                "num": len(matched), "den": len(attributed)}
    if episode.get("applicable") and spec.get("id") in ("S2", "S6"):
        participants_n = min(2, int(episode.get("first_span_participants", 0)))
        attribution = {"num": participants_n, "den": 2,
                       "value": participants_n / 2.0,
                       "applicable": True, "basis": "episode_participants"}
    years = sorted(evidence_years)
    return {
        "required_fact_recall": required,
        "relevance": relevance,
        "episode_completeness": episode,
        "temporal_correctness": temporal,
        "participant_attribution": attribution,
        "source_proof": source_proof,
        "latency_cost": {
            "elapsed_ms": int(elapsed_ms),
            "retrieve_calls": int(retrieve_calls),
            "payload_chars": int((entry.get("writer") or {}).get(
                "payload_chars") or 0),
            "rag_chars": int((entry.get("writer") or {}).get(
                "rag_chars") or 0),
            "episode_chars": int((entry.get("writer") or {}).get(
                "episode_chars") or 0),
            "embed_calls": int(getattr(spec.get("_stub"), "embed_calls", 0)),
            "generate_calls": int(getattr(spec.get("_stub"),
                                          "generate_calls", 0)),
        },
        "years": years,
    }


def _episode_metric(entry, ref, spec) -> dict:
    ep = entry.get("episode") or {}
    spans = ep.get("spans") or []
    expected = set(int(y) for y in (ref.get("expected_years") or ()))
    subject_hash = (ref.get("subject") or {}).get("uid_sha256")
    covered = set()
    complete = []
    complete_years = set()
    for span in spans:
        years = set(int(y) for y in (span.get("years") or ()))
        covered.update(years)
        span["subject_participant"] = bool(
            subject_hash and subject_hash in
            (span.get("participants_sha256") or ()))
        if (int(span.get("source_count") or 0) >= 2
                and int(span.get("participants") or 0) >= 2
                and int(span.get("first_ts") or 0) < int(
                    span.get("last_ts") or 0)):
            complete.append(span)
            complete_years.update(years)
    if not expected or not spans:
        return {"num": 0, "den": 0, "value": None, "applicable": False,
                "spans": len(spans), "messages": ep.get("messages", 0),
                "expected_years": sorted(expected),
                "covered_years": sorted(covered),
                "complete_years": sorted(complete_years)}
    first = spans[0]
    first_correct = bool(set(first.get("years") or ()) & expected)
    all_expected = bool(expected) and expected <= complete_years
    value = 1 if (all_expected and first_correct) else 0
    return {
        "num": value, "den": 1, "value": float(value), "applicable": True,
        "spans": len(spans), "messages": int(ep.get("messages") or 0),
        "expected_years": sorted(expected),
        "covered_years": sorted(covered),
        "complete_years": sorted(complete_years),
        "coverage": (len(expected & complete_years) / len(expected)
                     if expected else 0.0),
        "all_expected_covered": all_expected,
        "complete_spans": len(complete),
        "first_span_correct": first_correct,
        "first_span_participants": int(first.get("participants") or 0),
        "first_span_sources": int(first.get("source_count") or 0),
        "first_span_years": list(first.get("years") or ()),
        "correct_spans": len([span for span in spans
                              if set(span.get("years") or ()) & expected]),
        "subject_spans": sum(1 for span in spans
                             if span.get("subject_participant")),
        "first_span_subject": bool(first.get("subject_participant")),
    }


def _strip_scenario(entry: dict) -> dict:
    out = dict(entry)
    for key in ("_items", "_payload", "rag_lines", "query_template",
                "query", "text", "fact"):
        out.pop(key, None)
    for key in ("period", "writer"):
        if isinstance(out.get(key), dict):
            out[key] = {k: v for k, v in out[key].items()
                        if k not in ("query", "text", "fact")}
    return out


def _verdict(scenario: dict, metrics: dict) -> str:
    sid = scenario.get("id")
    if scenario.get("not_executed") or \
            (scenario.get("ref") or {}).get("not_executed"):
        return "not_executed"
    if sid == "S7":
        return ("informational" if metrics["source_proof"].get("unresolved") == 0
                else "fail")
    req = metrics["required_fact_recall"].get("value")
    src = metrics["source_proof"].get("unresolved")
    temporal = metrics["temporal_correctness"].get("value")
    mandatory = (req == 1.0 and src == 0 and temporal == 1.0)
    episode = metrics["episode_completeness"]
    if episode.get("applicable"):
        mandatory = mandatory and bool(episode.get("value") == 1.0)
        if sid == "S6":
            mandatory = mandatory and bool(episode.get("first_span_correct"))
    if sid == "S4":
        mandatory = mandatory and (scenario.get("current_recall") == 1.0
                                   or req == 1.0)
        mandatory = mandatory and (metrics.get("stale_history") or {}).get(
            "unlabeled", 0) == 0
    return "pass" if mandatory else "fail"


def _privacy_scan(payload, private_names) -> dict:
    names = [str(n).strip() for n in private_names if str(n).strip()]
    hits = []
    bad_keys = []

    def walk(obj, path=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ("text", "fact", "query", "query_template",
                           "name", "author_name", "display_name",
                           "topic") and isinstance(value, str):
                    bad_keys.append(path + "/" + key)
                walk(value, path + "/" + str(key))
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                walk(value, path + "/%d" % idx)
        elif isinstance(obj, str):
            for name in names:
                if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)",
                             obj, re.IGNORECASE):
                    hits.append(path)
                    break

    walk(payload)
    return {"hits": len(hits), "fields": sorted(set(hits + bad_keys))[:20],
            "structured_fields": len(bad_keys)}


def _write_outputs(out_dir: str, payload: dict, variant: str) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / ("time03-scenarios-%s.json" % variant)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
    json_path.write_text(text, encoding="utf-8")
    digest = sha256_text(text)
    (out / ("time03-scenarios-%s.sha256" % variant)).write_text(
        digest + "  " + json_path.name + "\n", encoding="utf-8")
    lines = ["# TIME-03 real-archive S1-S7 scenarios (%s)" % variant, "",
             "- schema: `%s`" % payload.get("schema"),
             "- variant: `%s`" % payload.get("variant"),
             "- code_root_head: `%s`" % payload.get("code_root_head"),
             "- snapshot_sha256: `%s`" % (payload.get("snapshot") or {}).get(
                 "sha256"),
             "- chat_id: `%s`" % payload.get("chat_id"),
             "- status: `%s`" % payload.get("status"),
             "- output_sha256: `%s`" % digest, "",
             "| scenario | status | required recall | relevance | episode | temporal | source proof |",
             "|---|---|---|---|---|---|---|"]
    for row in payload.get("scenarios") or ():
        m = row.get("metrics") or {}

        def _v(key):
            part = m.get(key) or {}
            value = part.get("value")
            return "n/a" if value is None else "%.3f (%s/%s)" % (
                value, part.get("num"), part.get("den"))
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            row.get("id"), row.get("status"), _v("required_fact_recall"),
            _v("relevance"), _v("episode_completeness"),
            _v("temporal_correctness"), _v("source_proof")))
    lines.extend(["", "No message/fact text or display names are stored; "
                      "ids, years, hashes and counts only.",
                  "This is acceptance evidence, not a VERIFIED claim."])
    md_path = out / ("time03-scenarios-%s.md" % variant)
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"paths": [str(json_path), str(md_path),
                      str(out / ("time03-scenarios-%s.sha256" % variant))],
            "sha256": digest}


def _payload(args, meta, code_root, head, mode, effective, reason=""):
    return {
        "schema": SCHEMA, "mode": mode, "variant": args.variant,
        "generated_at": int(time.time()),
        "code_root": str(code_root), "code_root_head": head,
        "product_sha": str(head or (CANDIDATE_SHA
                                    if args.variant == "candidate"
                                    else BASELINE_SHA)),
        "chat_id": args.chat_id,
        "snapshot": meta,
        "snapshot_sha256_after": meta.get("sha256"),
        "effective_config": {
            "file_sha256": effective.get("file_sha256"),
            "measurement_source": effective.get("measurement_source"),
            "pg_status": effective.get("pg_status"),
            "hot_config_measured": effective.get("hot_config_measured"),
            "sources": effective.get("sources"),
            "effective": effective.get("effective"),
        },
        "scenarios": [], "assertions": [],
        "status": "not_executed", "technical_reason": reason,
        "limitations": [
            "Read-only snapshot; not the live process.",
            "LLM/embedding clients are failing stubs; no Writer prose.",
            "Vector leg may be compat_not_proven; lexical path is measured.",
            "One chat, one run per variant; no statistical generalization.",
            "S1-S7 references are archive-derived by deterministic rules.",
            "No year-share metric; no one-episode success rule.",
        ],
    }


async def run_on_snapshot(args, code_root: Path, head: str, meta: dict,
                          effective: dict, network=None) -> dict:
    from services import hot_config as hot
    from services import mca_gates
    from services.database import DatabaseService
    from services.direct_chat_service import DirectChatService
    from services.summary_memory import MemoryManager
    from services import mca_retrieval_context as mrc

    enabled, limit = effective_values(effective)
    payload = _payload(args, meta, code_root, head,
                       "fixture" if args.fixture else "snapshot", effective)
    if not enabled or limit <= 0:
        payload["technical_reason"] = "graph_rag_disabled"
        return payload
    hot.set_config_cache(_base.CacheStub({
        "flags.graph_rag_enabled": enabled,
        "limits.graph_rag_facts_limit": limit,
    }))
    db = DatabaseService(args.db)
    await db.initialize_readonly()
    private_names = await _base.collect_private_names(db, args.chat_id)
    stub = _base.StubLLM()
    diagnostics = _base.DiagnosticsHandler()
    root_logger = logging.getLogger()
    prev_level = root_logger.level
    root_logger.addHandler(diagnostics)
    root_logger.setLevel(min(prev_level, logging.WARNING) if prev_level
                         else logging.WARNING)
    try:
        memory = MemoryManager(db, stub, aliases=None)

        async def _noop():
            return 0
        memory.backfill_archive_vectors = _noop
        memory.backfill_graph_fact_vectors = _noop
        vec = {"vec_ok": False, "vec_dim": None,
               "sqlite_vec_off_reason": None, "sqlite_vec_loaded": False,
               "vec_error": None}
        try:
            vec["vec_ok"] = bool(await asyncio.wait_for(
                memory.initialize(), 120))
        except Exception as exc:
            vec["vec_error"] = type(exc).__name__
        vec["vec_dim"] = getattr(memory, "_vec_dim", None)
        vec["sqlite_vec_off_reason"] = getattr(memory, "_vec_off_reason", None)
        vec["sqlite_vec_loaded"] = bool(
            vec["vec_ok"] or vec["sqlite_vec_off_reason"] == "embed")
        svc = DirectChatService(memory, db, stub, _base.StubAliases())
        tail = await db.get_recent_messages(args.chat_id, 40)
        archive = meta.get("archive") or {}
        current_year = int(archive.get("current_year") or CURRENT_YEAR)
        as_of = int(archive.get("max_ts") or int(time.time()))
        seed = sha256_text("%s:%s:%s:%s" % (
            args.variant, args.chat_id, meta.get("sha256"),
            SCHEMA))
        participants = await _base.select_participants(
            db, args.chat_id, seed)
        builder = _base.ReferenceBuilder(
            db, args.chat_id, seed, current_year, as_of,
            participants, {}, {})
        e1 = await _base.select_e1(builder, seed)
        builder.e1 = e1
        ce = await _base.select_counterexample(builder)
        builder.counterexample = ce
        scenarios = await _scenario_refs(builder, participants, e1, ce,
                                         current_year)
        reference_checks = []
        for spec in scenarios:
            if spec.get("not_executed"):
                continue
            ref = spec.get("ref") or {}
            validation = await validate_reference(
                db, args.chat_id, ref, spec, as_of)
            ref["validation"] = validation
            reference_checks.append({
                "id": spec.get("id"), "valid": bool(validation.get("valid")),
                "checked": int(validation.get("checked") or 0),
                "invalid": list(validation.get("invalid") or ()),
            })
            if not validation.get("valid"):
                spec["_reference_invalid"] = validation
        gates = {}
        for key, fn in (("retrieval_context",
                         mca_gates.retrieval_context_enabled),
                        ("evidence_bundle", mca_gates.evidence_bundle_enabled),
                        ("typed_reranker", mca_gates.typed_reranker_enabled),
                        ("episodes", mca_gates.episodes_enabled),
                        ("canonical_attribution",
                         mca_gates.canonical_attribution_enabled),
                        ("event_contract", mca_gates.event_contract_enabled)):
            try:
                gates[key] = bool(fn())
            except Exception:
                gates[key] = None
        payload["configuration"] = {
            "graph_rag_enabled": enabled,
            "graph_rag_facts_limit": limit,
            "gates": gates,
            "vector": vec,
        }
        out_scenarios = []
        for spec in scenarios:
            if spec.get("not_executed"):
                out_scenarios.append({
                    "id": spec["id"], "status": "not_executed",
                    "reason": spec["not_executed"], "metrics": {}})
                continue
            ref = spec.get("ref") or {}
            if spec.get("_reference_invalid") or not (
                    ref.get("validation") or {}).get("valid", True):
                out_scenarios.append({
                    "id": spec["id"], "status": "not_executed",
                    "reason": "reference_invalid",
                    "reference": compact_ref(ref), "metrics": {}})
                continue
            if ref.get("not_executed"):
                out_scenarios.append({
                    "id": spec["id"], "status": "not_executed",
                    "reason": ref["not_executed"],
                    "reference": compact_ref(ref), "metrics": {}})
                continue
            count = {"n": 0}
            original = mrc.retrieve

            async def counted(*a, **k):
                count["n"] += 1
                return await original(*a, **k)
            mrc.retrieve = counted
            started = time.perf_counter()
            try:
                entry = await probe_scenario(
                    svc, db, args.chat_id, spec, spec["query"], tail)
            finally:
                mrc.retrieve = original
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            spec = dict(spec)
            spec["_stub"] = stub
            metrics = await _scenario_metrics(
                entry, ref, spec, participants, current_year, db,
                args.chat_id, elapsed_ms, count["n"])
            if spec.get("id") == "S4":
                old_refs = set(ref.get("old_refs") or ())
                old_items = [i for i in (entry.get("_items") or ())
                             if old_refs & set(i.get("refs") or ())]
                archive_marked = 0
                unlabeled = 0
                for item in old_items:
                    refs = set(item.get("refs") or ())
                    lines = [ln for ln in (entry.get("rag_lines") or ())
                             if refs & set(ln.get("refs") or ())]
                    if any(ln.get("archive") for ln in lines):
                        archive_marked += 1
                    elif not any(ln.get("date") for ln in lines):
                        unlabeled += 1
                metrics["stale_history"] = {
                    "old_anchors": len(ref.get("old_anchors") or ()),
                    "old_delivered": len(old_items),
                    "archive_marked": archive_marked,
                    "unlabeled": unlabeled,
                    "pass": unlabeled == 0,
                }
            row = {
                "id": spec.get("id"),
                "status": None,
                "scope": spec.get("scope"),
                "plan_act": spec.get("plan_act") or "",
                "reference": compact_ref(ref),
                "metrics": metrics,
                "entry": _strip_scenario(entry),
            }
            row["status"] = _verdict({**spec, "ref": ref}, metrics)
            out_scenarios.append(row)
        payload["scenarios"] = out_scenarios
        payload["scenario_count"] = len(out_scenarios)
        payload["executed"] = sum(1 for s in out_scenarios
                                  if s["status"] in ("pass", "fail",
                                                     "informational"))
        payload["failed"] = [s["id"] for s in out_scenarios
                             if s["status"] == "fail"]
        payload["not_executed"] = [s["id"] for s in out_scenarios
                                   if s["status"] == "not_executed"]
        payload["diagnostics"] = diagnostics.snapshot()
        payload["stub_embed_calls"] = stub.embed_calls
        payload["stub_generate_calls"] = stub.generate_calls
        payload["private_names_count"] = len(private_names)
        after = _base.sha256_file(args.db)
        payload["snapshot_sha256_after"] = after
        assertions = []
        assertions.append({
            "id": "SNAPSHOT-READONLY",
            "expected": "sha256 unchanged; quick_check=ok; user_version=48",
            "actual": {"quick_check": meta.get("quick_check"),
                       "user_version": meta.get("user_version"),
                       "before": meta.get("sha256"), "after": after},
            "status": ("pass" if after == meta.get("sha256")
                       and meta.get("quick_check") == "ok"
                       and int(meta.get("user_version") or 0)
                       == EXPECTED_SCHEMA else "fail"),
        })
        assertions.append({
            "id": "CONFIG-FAIL-CLOSED",
            "expected": "measured graph_rag_enabled=true and limit>0",
            "actual": {"enabled": enabled, "limit": limit,
                       "source": effective.get("measurement_source")},
            "status": "pass",
        })
        assertions.append({
            "id": "NETWORK-OFF",
            "expected": "socket egress blocked; LLM/embed stubs only",
            "actual": {"blocked_attempts": int(getattr(network, "blocked", 0)),
                       "embed_calls": stub.embed_calls,
                       "generate_calls": stub.generate_calls},
            "status": "pass",
        })
        assertions.append({
            "id": "SCENARIOS-EXECUTED",
            "expected": "S1-S7 have an executed or explicit not_executed row",
            "actual": {"rows": len(out_scenarios),
                       "executed": payload["executed"]},
            "status": ("pass" if len(out_scenarios) == 7 else "fail"),
        })
        invalid_references = [
            check for check in reference_checks if not check.get("valid")]
        assertions.append({
            "id": "REFERENCE-VALID",
            "expected": "every non-S7 anchor resolves in chat/year, is eligible, and query/topic matches",
            "actual": {"checked": len(reference_checks),
                       "invalid": [c.get("id") for c in invalid_references],
                       "details": invalid_references},
            "status": "pass" if not invalid_references else "fail",
        })
        assertions.append({
            "id": "NO-FABRICATED-REFS",
            "expected": "every payload/bundle ref resolves; zero fabricated",
            "actual": {
                "unresolved": sum(int((s.get("metrics") or {}).get(
                    "source_proof", {}).get("unresolved") or 0)
                    for s in out_scenarios),
                "fabricated": sum(int((s.get("metrics") or {}).get(
                    "source_proof", {}).get("unresolved") or 0)
                    for s in out_scenarios),
            },
            "status": ("pass" if all(int((s.get("metrics") or {}).get(
                "source_proof", {}).get("unresolved") or 0) == 0
                for s in out_scenarios) else "fail"),
        })
        privacy = _privacy_scan(payload, private_names)
        assertions.append({
            "id": "NO-TEXT-NAMES",
            "expected": "no message/fact text or display names in output",
            "actual": privacy,
            "status": "pass" if privacy["hits"] == 0
            and privacy["structured_fields"] == 0 else "fail",
        })
        payload["assertions"] = assertions
        statuses = [a["status"] for a in assertions]
        if "fail" in statuses or payload["failed"]:
            payload["status"] = "fail"
        elif payload["not_executed"]:
            payload["status"] = "not_executed"
        else:
            payload["status"] = "ok"
        return payload
    finally:
        try:
            root_logger.removeHandler(diagnostics)
            root_logger.setLevel(prev_level)
        except Exception:
            pass
        try:
            await db.close()
        except Exception:
            pass


def _network_blocked(payload) -> int:
    # The NetworkBlock counter is not serializable into payload; the caller
    # records it separately when available. 0 means "not observed".
    return int(payload.get("_network_blocked") or 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="TIME-03 real-archive S1-S7 acceptance harness")
    parser.add_argument("--db", help="saved SQLite snapshot (read-only)")
    parser.add_argument("--chat-id", type=int, required=True)
    parser.add_argument("--code-root", required=True,
                        help="baseline or candidate worktree")
    parser.add_argument("--out", required=True)
    parser.add_argument("--variant", choices=("baseline", "candidate"),
                        required=True)
    parser.add_argument("--effective-config", default="",
                        help="measured effective GraphRAG JSON")
    parser.add_argument("--expected-sha", default="",
                        help="override expected code-root HEAD")
    parser.add_argument("--fixture", action="store_true",
                        help="synthetic smoke only; never production evidence")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    code_root = Path(args.code_root).resolve()
    if args.dry_run:
        print(json.dumps({
            "schema": SCHEMA, "variant": args.variant,
            "expected_code_root_sha": (BASELINE_SHA if args.variant ==
                                       "baseline" else CANDIDATE_SHA),
            "code_root": str(code_root), "chat_id": args.chat_id,
            "db": args.db, "out": args.out, "fixture": bool(args.fixture),
        }, ensure_ascii=False, indent=1))
        return 0
    try:
        head = ensure_code_root(code_root, args.variant, args.expected_sha)
    except Exception as exc:
        payload = _payload(args, {"exists": False, "sha256": None},
                           code_root, "", "fixture" if args.fixture else
                           "snapshot", {}, reason=str(exc))
        payload["assertions"] = [{"id": "CODE-ROOT", "expected":
                                  "validated clean product tree",
                                  "actual": {"reason": str(exc)},
                                  "status": "fail"}]
        payload["status"] = "fail"
        info = _write_outputs(args.out, payload, args.variant)
        print(json.dumps({"status": "fail", "reason": str(exc),
                          "out": info["paths"]}, ensure_ascii=False))
        return 4
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    try:
        effective = load_effective(args.effective_config,
                                   fixture=args.fixture,
                                   code_root=str(code_root))
    except Exception as exc:
        payload = _payload(args, {"exists": False, "sha256": None},
                           code_root, head, "fixture" if args.fixture else
                           "snapshot", {}, reason=str(exc))
        payload["assertions"] = [{"id": "CONFIG-PROVENANCE",
                                  "expected": "measured effective config",
                                  "actual": {"reason": str(exc)},
                                  "status": "not_executed"}]
        payload["status"] = "not_executed"
        info = _write_outputs(args.out, payload, args.variant)
        print(json.dumps({"status": "not_executed", "reason": str(exc),
                          "out": info["paths"]}, ensure_ascii=False))
        return 2
    if args.fixture:
        sys.path.insert(0, str(HERE))
        from make_fixture import build_fixture
        fixture_dir = tempfile.mkdtemp(prefix="time03-fixture-")
        args.db = os.path.join(fixture_dir, "fixture.db")
        asyncio.run(build_fixture(args.db, chat_id=args.chat_id))
    if not args.db or not os.path.exists(args.db):
        payload = _payload(args, {"exists": False, "sha256": None},
                           code_root, head, "fixture" if args.fixture else
                           "snapshot", effective, reason="snapshot_missing")
        payload["assertions"] = [{"id": "SNAPSHOT",
                                  "expected": "existing SQLite snapshot",
                                  "actual": {"exists": False},
                                  "status": "not_executed"}]
        payload["status"] = "not_executed"
        info = _write_outputs(args.out, payload, args.variant)
        print(json.dumps({"status": "not_executed",
                          "reason": "snapshot_missing",
                          "out": info["paths"]}, ensure_ascii=False))
        return 2
    meta = _base.snapshot_meta(args.db, args.chat_id)
    try:
        with _base.NetworkBlock() as network:
            payload = asyncio.run(run_on_snapshot(
                args, code_root, head, meta, effective, network))
            payload["_network_blocked"] = network.blocked
    except BaseException as exc:
        payload = _payload(args, meta, code_root, head,
                           "fixture" if args.fixture else "snapshot",
                           effective, reason=type(exc).__name__)
        payload["technical_detail"] = traceback.format_exc(limit=2)
        payload["assertions"] = [{"id": "RUN",
                                  "expected": "technical run completed",
                                  "actual": {"error": type(exc).__name__},
                                  "status": "fail"}]
        payload["status"] = "fail"
        info = _write_outputs(args.out, payload, args.variant)
        print(json.dumps({"status": "fail",
                          "reason": type(exc).__name__,
                          "out": info["paths"]}, ensure_ascii=False))
        return 4
    info = _write_outputs(args.out, payload, args.variant)
    print(json.dumps({
        "status": payload.get("status"),
        "variant": args.variant,
        "code_root_head": head,
        "snapshot_sha256": meta.get("sha256"),
        "scenario_count": payload.get("scenario_count"),
        "failed": payload.get("failed"),
        "not_executed": payload.get("not_executed"),
        "output_sha256": info["sha256"],
        "out": info["paths"],
    }, ensure_ascii=False))
    return {"ok": 0, "fail": 1, "not_executed": 2}.get(
        payload.get("status"), 4)


if __name__ == "__main__":
    raise SystemExit(main())
