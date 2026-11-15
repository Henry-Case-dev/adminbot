# -*- coding: utf-8 -*-
"""Build the redacted postdeploy e2e evidence for 2.58.204 (server-side).

Inputs: raw Writer probe JSON, raw tool probe JSON, live cfg snapshot.
Output: one JSON with ids/periods/counts/codes only — no participant names,
no forum token, no prompt/override text, no chat ids (hashed), no message
texts. Includes the acceptance checks of the approved M-04/O-04 wait.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

APP = "/var/www/admin_bot"
DEPLOYED_SHA = os.environ.get("DEPLOYED_SHA", "")
DEPLOYED_VERSION = os.environ.get("DEPLOYED_VERSION", "")
DEPLOYED_BRANCH = os.environ.get("DEPLOYED_BRANCH", "")
COPY_DB = os.environ.get("VMQ_DB", "")


def sha12(value) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def bundle_view(wrapper: dict | None) -> dict | None:
    """The probe stores {gate, bundle}; the real bundle is nested."""
    if not wrapper:
        return None
    bundle = wrapper.get("bundle") if isinstance(wrapper.get("bundle"),
                                                dict) else None
    out = {"gate": wrapper.get("gate"), "present": bundle is not None}
    if wrapper.get("error"):
        out["error"] = wrapper.get("error")
        return out
    if bundle is None:
        out["note"] = wrapper.get("note")
        return out
    counter = bundle.get("counterexamples") or []
    out.update({
        "type": bundle.get("type"),
        "coverage_lines": [str(v)[:160] for v in
                           (bundle.get("coverage_lines") or [])][:12],
        "independent_periods": [str(v) for v in
                                (bundle.get("independent_periods") or [])][:12],
        "counterexamples": [{"chars": len(str(v))} for v in counter][:8],
        "counterexamples_count": len(counter),
        "limitations": [str(v) for v in (bundle.get("limitations") or [])][:12],
        "episode_refs_count": bundle.get("episode_refs_count"),
        "semantic_hints_count": bundle.get("semantic_hints_count"),
        "context_version": bundle.get("context_version"),
        "schema_version": bundle.get("schema_version"),
        "has_overview_slots": bundle.get("has_overview_slots"),
    })
    return out


def request_view(request: dict | None) -> dict | None:
    if not request:
        return None
    keep = ("mode", "purpose", "top_k", "channels", "scope",
            "include_overview", "memory_scope", "period_fill",
            "exclude_years", "include_archived", "preserve_channel_order",
            "intent", "subject_entity_ids", "time_from", "time_to",
            "lexical_time_window", "period_intent")
    out = {key: request.get(key) for key in keep if key in request}
    out["subject_bound"] = bool(request.get("subject_names")
                                or request.get("subject_entity_ids"))
    return out


def result_view(result: dict | None) -> dict | None:
    if not result:
        return None
    keep = ("status", "reason_code", "mode", "purpose", "channels_used",
            "candidates", "candidate_years", "fact_rows", "fact_years",
            "period_fill", "overview", "fact_ids", "fact_rows_detail")
    out = {key: result.get(key) for key in keep if key in result}
    top = result.get("top")
    if isinstance(top, list):
        out["top"] = [{k: row.get(k) for k in
                       ("id", "type", "channel", "year", "score")}
                      for row in top[:24] if isinstance(row, dict)]
    return out


def retrieve_calls(calls) -> list:
    out = []
    for call in calls or []:
        out.append({
            "seconds": call.get("seconds"),
            "request": request_view(call.get("request")),
            "result": result_view(call.get("result")),
        })
    return out


def class_view(entry: dict) -> dict:
    rag = entry.get("rag") or {}
    rag_out = {key: rag.get(key) for key in
               ("seconds", "block_chars", "block_lines", "block_years",
                "hint", "rows", "row_years", "row_topic", "row_period_fill",
                "period_stats", "memory_scope", "include_overview_forwarded",
                "overview_result_present",
                "overview_result_is_first_retrieve", "overview_on_result",
                "retrieve_calls", "retrieve_include_overview",
                "episode_reads", "row_ids", "rows_detail", "period_rows")}
    rag_out["retrieve"] = retrieve_calls(rag.get("retrieve"))
    return {
        "class": entry.get("class"),
        "query": entry.get("query"),
        "subject_bound_call": entry.get("subject_bound_call"),
        "response_act": entry.get("response_act"),
        "rebuild_rows": entry.get("rebuild_rows"),
        "rebuild_row_years": entry.get("rebuild_row_years"),
        "rebuild_period_rows": entry.get("rebuild_period_rows"),
        "plan_act_forwarded": entry.get("plan_act_forwarded"),
        "memory_scope_forwarded": entry.get("memory_scope_forwarded"),
        "overview_result_present": entry.get("overview_result_present"),
        "overview_on_result": entry.get("overview_on_result"),
        "retrieve_calls": entry.get("retrieve_calls"),
        "retrieve_include_overview": entry.get("retrieve_include_overview"),
        "episode_reads": entry.get("episode_reads"),
        "final_block_years": entry.get("final_block_years"),
        "pre_plan": entry.get("pre_plan"),
        "rag": rag_out,
        "bundle": bundle_view(entry.get("bundle")),
        "errors": {k: v for k, v in entry.items() if k.endswith("_error")},
    }


def note(checks, name: str, ok: bool, detail) -> None:
    checks.append({"check": name, "ok": bool(ok), "detail": detail})


CHAT = -1002661910336


def correction_effect() -> dict:
    """Read-only proof that a corrected source changes the version trace.

    Finds a real message with ``current_revision > 1`` that belongs to an
    episode, recomputes the deployed code's episode fingerprint with the real
    revisions and with all revisions = 1, and shows whether the correction is
    visible to the next EpisodeView/overview (no write, no message).
    """
    if not COPY_DB:
        return {"status": "no_path"}
    try:
        sys.path.insert(0, APP)
        from services import mca_episodes
    except Exception as exc:                    # noqa: BLE001
        return {"status": "import_failed", "error": type(exc).__name__}
    out = {"status": "checked"}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % COPY_DB, uri=True,
                              timeout=30)
        try:
            revised = con.execute(
                "SELECT id, tg_message_id, current_revision, timestamp "
                "FROM smart_messages WHERE chat_id=? AND current_revision>1 "
                "ORDER BY timestamp DESC LIMIT 60", (CHAT,)).fetchall()
            out["revised_messages_total"] = con.execute(
                "SELECT COUNT(*) FROM smart_messages WHERE chat_id=? AND "
                "current_revision>1", (CHAT,)).fetchone()[0]
            episodes = []
            for msg_id, tg_id, revision, ts in revised:
                row = con.execute(
                    "SELECT episode_id, message_keys_json FROM mca_episodes "
                    "WHERE chat_id=? AND (message_keys_json LIKE ? OR "
                    "message_keys_json LIKE ?) LIMIT 1",
                    (CHAT, f"%:tg:{tg_id}", f"%:db:{msg_id}")).fetchone()
                if not row:
                    continue
                episode_id, raw = row
                try:
                    keys = [str(k) for k in json.loads(raw or "[]")]
                except Exception:                # noqa: BLE001
                    continue
                wanted_tg, wanted_db = [], []
                for key in keys:
                    kind, _sep, value = key.rpartition(":")
                    try:
                        token = int(value)
                    except (TypeError, ValueError):
                        continue
                    if kind.endswith("tg"):
                        wanted_tg.append(token)
                    elif kind.endswith("db"):
                        wanted_db.append(token)
                revisions = {}
                for column, values in (("tg_message_id", wanted_tg),
                                       ("id", wanted_db)):
                    values = list(dict.fromkeys(values))
                    if not values:
                        continue
                    rows = con.execute(
                        "SELECT %s, current_revision FROM smart_messages "
                        "WHERE chat_id=? AND %s IN (%s)"
                        % (column, column, ",".join("?" for _ in values)),
                        (CHAT, *values)).fetchall()
                    for token, rev in rows:
                        revisions[int(token)] = int(rev or 1)
                real = mca_episodes.episode_source_fingerprint(
                    keys, revisions=revisions)
                baseline = mca_episodes.episode_source_fingerprint(
                    keys, revisions={k: 1 for k in keys})
                episodes.append({
                    "episode_ref": str(episode_id)[:32],
                    "keys": len(keys),
                    "keys_resolved": len(revisions),
                    "keys_revision_gt1": sum(
                        1 for value in revisions.values() if value > 1),
                    "source_fingerprint_real_revisions": real,
                    "source_fingerprint_all_revision_1": baseline,
                    "correction_changes_fingerprint": real != baseline,
                })
                if len(episodes) >= 5:
                    break
        finally:
            con.close()
        out["sampled_episodes"] = episodes
        out["revised_messages_in_sample"] = len(revised)
        out["observable"] = any(row["correction_changes_fingerprint"]
                                for row in episodes)
    except Exception as exc:                    # noqa: BLE001
        out["status"] = "error"
        out["error"] = type(exc).__name__
        import traceback
        out["tb"] = traceback.format_exc()[-900:]
    return out


def db_copy_meta() -> dict:
    if not COPY_DB:
        return {"status": "no_path"}
    out = {"path_ref": "backup copy (server-side)",
           "bytes": os.path.getsize(COPY_DB) if os.path.exists(COPY_DB) else None}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % COPY_DB, uri=True, timeout=30)
        try:
            out.update({
                "user_version": con.execute("PRAGMA user_version").fetchone()[0],
                "journal_mode": con.execute("PRAGMA journal_mode").fetchone()[0],
                "integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
                "messages": con.execute(
                    "SELECT COUNT(*) FROM smart_messages").fetchone()[0],
                "episodes": con.execute(
                    "SELECT COUNT(*) FROM mca_episodes").fetchone()[0],
                "revisions_gt1": con.execute(
                    "SELECT COUNT(*) FROM smart_messages "
                    "WHERE current_revision>1").fetchone()[0],
            })
        finally:
            con.close()
    except Exception as exc:                    # noqa: BLE001
        out["error"] = type(exc).__name__
    out["sha256"] = os.environ.get("E2E_COPY_SHA256", "")
    return out


def overview_flags(entry: dict) -> list:
    return list((entry.get("rag") or {}).get("retrieve_include_overview") or [])


def route_view(entry: dict) -> dict:
    calls = (entry.get("rag") or {}).get("retrieve") or []
    return {
        "total_calls": len(calls),
        "purposes": [((c.get("request") or {}).get("purpose"))
                     for c in calls],
        "channels": [((c.get("request") or {}).get("channels"))
                     for c in calls],
        "include_overview": overview_flags(entry),
        "episode_reads": (entry.get("rag") or {}).get("episode_reads"),
    }


def main() -> int:
    if len(sys.argv) < 5:
        raise SystemExit("usage: build_postdeploy_evidence.py writer tool cfg out")
    writer = load(sys.argv[1])
    tool = load(sys.argv[2])
    cfg = load(sys.argv[3])
    dest = Path(sys.argv[4])

    ident = writer.get("identity") or {}
    classes = {key: class_view(value) for key, value in
               (writer.get("classes") or {}).items()}
    plans = {key: class_view(value) for key, value in
             (writer.get("plan_flows") or {}).items()}
    tool_calls = tool.get("calls") or {}
    version_check = tool.get("version_check") or {}

    checks: list[dict] = []
    note(checks, "writer_imports_deployed_tree",
         ident.get("clone") == APP
         and str(ident.get("services_file", "")).startswith(APP),
         {"clone": ident.get("clone"),
          "services_file": ident.get("services_file")})
    note(checks, "writer_git_head_is_deployed_sha",
         bool(DEPLOYED_SHA) and ident.get("git_head") == DEPLOYED_SHA,
         {"probe": ident.get("git_head"), "deployed": DEPLOYED_SHA})
    note(checks, "tool_imports_deployed_tree",
         (tool.get("identity") or {}).get("clone") == APP,
         (tool.get("identity") or {}).get("clone"))

    a1 = classes.get("A1_creative_owner") or {}
    a1r = a1.get("rag") or {}
    a1ov = a1r.get("overview_on_result") or {}
    a1b = a1.get("bundle") or {}
    note(checks, "exact_owner_one_overview_retrieve",
         overview_flags(a1) == [True, False]
         and a1r.get("overview_result_is_first_retrieve") is True,
         {"route": route_view(a1)})
    note(checks, "exact_owner_overview_same_result",
         bool(a1r.get("overview_result_present"))
         and bool(a1r.get("overview_result_is_first_retrieve")),
         {"present": a1r.get("overview_result_present"),
          "same": a1r.get("overview_result_is_first_retrieve")})
    note(checks, "exact_owner_coverage_actual",
         bool((a1ov.get("coverage") or {}).get("present_periods"))
         and bool(a1ov.get("independent_periods")),
         {"periods": (a1ov.get("coverage") or {}).get("present_periods"),
          "independent": a1ov.get("independent_periods")})
    note(checks, "exact_owner_bundle_slots",
         bool(a1b.get("has_overview_slots"))
         and bool(a1b.get("coverage_lines"))
         and bool(a1b.get("limitations")),
         {"gate": a1b.get("gate"),
          "coverage_lines": a1b.get("coverage_lines"),
          "independent": a1b.get("independent_periods"),
          "limitations": a1b.get("limitations"),
          "counterexamples": a1b.get("counterexamples_count"),
          "context_version": a1b.get("context_version")})
    note(checks, "exact_owner_counterexamples_or_limitations",
         bool(a1ov.get("counterexamples_count")) or bool(a1ov.get("limitations")),
         {"counterexamples": a1ov.get("counterexamples_count"),
          "limitations": a1ov.get("limitations")})
    note(checks, "exact_owner_route_documented",
         route_view(a1).get("total_calls") == 2
         and route_view(a1).get("purposes") == ["reply", "reply"]
         and route_view(a1).get("include_overview") == [True, False],
         route_view(a1))

    d = classes.get("D_conflict_2023") or {}
    dr = d.get("rag") or {}
    d_periods = (dr.get("period_rows") or {}).get("years") or {}
    d_reasons = (dr.get("period_rows") or {}).get("reasons") or {}
    note(checks, "temporal_2023_period_fill_target_year",
         "2023" in {str(k) for k in d_periods.keys()}
         and "in_target_year" in d_reasons,
         {"period_rows": dr.get("period_rows"),
          "period_stats": dr.get("period_stats")})
    note(checks, "temporal_one_overview_retrieve",
         overview_flags(d) == [True, False]
         and dr.get("overview_result_is_first_retrieve") is True,
         route_view(d))
    note(checks, "temporal_bundle_slots",
         bool((d.get("bundle") or {}).get("has_overview_slots")),
         d.get("bundle"))

    t3 = classes.get("T3_current_no_signal") or {}
    t3r = t3.get("rag") or {}
    t3_intent = (t3r.get("period_stats") or {}).get("period_intent") or {}
    note(checks, "current_state_no_historical_overview",
         t3r.get("overview_on_result") is None
         and not t3r.get("overview_result_present")
         and True not in overview_flags(t3),
         {"overview": t3r.get("overview_on_result"),
          "present": t3r.get("overview_result_present"),
          "include_overview": overview_flags(t3)})
    note(checks, "current_state_no_period_fill",
         int(t3r.get("row_period_fill") or 0) == 0
         and t3_intent.get("kind") == "none",
         {"row_period_fill": t3r.get("row_period_fill"),
          "period_intent": t3_intent,
          "period_rows": t3r.get("period_rows")})
    note(checks, "current_state_route_documented",
         route_view(t3).get("total_calls") == 2
         and overview_flags(t3) == [False, False],
         {"route": route_view(t3),
          "row_years_observation": t3r.get("row_years")})
    note(checks, "current_state_no_extra_episode_reads",
         not any(int(v or 0) for v in (t3r.get("episode_reads") or {}).values()),
         t3r.get("episode_reads"))

    bio = tool_calls.get("biography") or {}
    gen = tool_calls.get("general") or {}
    idn = tool_calls.get("identity") or {}
    bio_ov = bio.get("overview") or {}
    bio_env = bio.get("envelope") or {}
    gen_env = gen.get("envelope") or {}
    note(checks, "tool_person_overview_one_retrieve",
         bio.get("retrieve_calls") == 1
         and bio.get("retrieve_include_overview") == [True],
         {"calls": bio.get("retrieve_calls"),
          "include_overview": bio.get("retrieve_include_overview")})
    note(checks, "tool_person_overview_envelope",
         bool(bio_env.get("coverage_lines"))
         and bool(bio_env.get("limitations_codes")),
         {"coverage_lines": bio_env.get("coverage_lines"),
          "independent": bio_env.get("independent_periods_values"),
          "limitations": (bio_env.get("limitations_codes") or [])[:12],
          "counterexamples": bio_env.get("counterexamples_chars")})
    note(checks, "tool_person_overview_overview_slots",
         bool((bio_ov.get("coverage") or {}).get("present_periods"))
         and bool(bio_ov.get("independent_periods")),
         {"periods": (bio_ov.get("coverage") or {}).get("present_periods"),
          "independent": bio_ov.get("independent_periods"),
          "limitations": bio_ov.get("limitations")})
    note(checks, "tool_general_overview_one_retrieve",
         gen.get("retrieve_calls") == 1
         and gen.get("retrieve_include_overview") == [True]
         and bool(gen_env.get("coverage_lines")),
         {"calls": gen.get("retrieve_calls"),
          "include_overview": gen.get("retrieve_include_overview"),
          "coverage": gen_env.get("coverage_lines")})
    note(checks, "tool_identity_negative_no_overview",
         idn.get("retrieve_calls") == 1
         and idn.get("retrieve_include_overview") == [False]
         and idn.get("overview") is None
         and "coverage" not in (idn.get("envelope") or {}).get("keys", []),
         {"calls": idn.get("retrieve_calls"),
          "include_overview": idn.get("retrieve_include_overview"),
          "overview": idn.get("overview"),
          "keys": (idn.get("envelope") or {}).get("keys")})
    for name, entry in (("biography", bio), ("general", gen), ("identity", idn)):
        llm_calls = entry.get("llm_calls") or {}
        note(checks, f"tool_no_chat_model_call:{name}",
             int(llm_calls.get("generate") or 0) == 0
             and int(llm_calls.get("embed") or 0) <= 1
             and int(llm_calls.get("embed_once") or 0) <= 1,
             llm_calls)
    note(checks, "tool_no_second_route",
         all((entry.get("retrieve_calls") or 0) == 1
             for entry in (bio, gen, idn)),
         {name: entry.get("retrieve_calls") for name, entry in
          (("biography", bio), ("general", gen), ("identity", idn))})

    vc = version_check.get("biography") or {}
    note(checks, "version_trace_present",
         vc.get("status") == "checked" and bool(vc.get("episodes")),
         {"status": vc.get("status"),
          "episodes": len(vc.get("episodes") or [])})
    note(checks, "version_fingerprints_match_source_revisions",
         vc.get("all_fingerprints_match") is True,
         {"episodes_checked": len(vc.get("episodes") or []),
          "mismatches": [row for row in (vc.get("episodes") or [])
                         if row.get("present") and not row.get(
                             "fingerprint_match")]})
    note(checks, "version_trace_not_contradictory",
         all((row.get("view_source_integrity") in ("ok", "unknown"))
             for row in (vc.get("episodes") or []) if row.get("present")),
         {"integrity": sorted({row.get("view_source_integrity")
                               for row in (vc.get("episodes") or [])
                               if row.get("present")}),
          "stale": sum(1 for row in (vc.get("episodes") or [])
                       if row.get("view_stale")),
          "corrected_source_episodes": vc.get(
              "episodes_with_corrected_source"),
          "copy_revision_stats": vc.get("copy_revision_stats")})

    corr = correction_effect()
    note(checks, "correction_effect_trace_checked",
         corr.get("status") == "checked",
         {"status": corr.get("status"),
          "revised_messages_total": corr.get("revised_messages_total"),
          "revised_messages_in_sample": corr.get("revised_messages_in_sample")})
    note(checks, "correction_effect_changes_source_fingerprint",
         corr.get("observable") is True or not (corr.get("sampled_episodes")
                                                or []),
         {"observable": corr.get("observable"),
          "sampled": [{k: row.get(k) for k in
                       ("episode_ref", "keys", "keys_revision_gt1",
                        "correction_changes_fingerprint")}
                      for row in (corr.get("sampled_episodes") or [])]})

    coverage_checks = (writer.get("sql") or {}).get(
        "overview_coverage_check") or {}
    bad = []
    checked_cases = []
    for name, row in coverage_checks.items():
        if not isinstance(row, dict) or row.get("status") == "no_overview":
            continue
        checked_cases.append(name)
        if row.get("claimed_periods_not_in_sql") or row.get(
                "sql_periods_not_claimed") or row.get("episode_refs_absent"):
            bad.append({"case": name,
                        "claimed_not_sql": row.get("claimed_periods_not_in_sql"),
                        "sql_not_claimed": row.get("sql_periods_not_claimed"),
                        "refs_absent": row.get("episode_refs_absent")})
    note(checks, "overview_coverage_matches_independent_sql", not bad,
         {"mismatches": bad, "cases_checked": checked_cases})
    note(checks, "overview_chat_scoped_no_cross_chat_refs",
         all(not (row or {}).get("episode_refs_absent")
             for row in coverage_checks.values()
             if isinstance(row, dict)),
         {"cases": checked_cases})

    payload = {
        "artifact_kind": "postdeploy_readonly_e2e",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deployed": {"sha": DEPLOYED_SHA, "version": DEPLOYED_VERSION,
                     "branch": DEPLOYED_BRANCH},
        "method": {
            "where": "production host, deployed checkout at %s, read-only copy "
                     "of the pre-deploy verified backup" % APP,
            "live_process": False,
            "no_user_messages": True,
            "note": "the Writer/tool paths run in-process on the deployed tree; "
                    "no Telegram message, no provider chat completion, no write "
                    "to live data. The Writer block keeps its documented "
                    "base+period retrieve pair; the overview/bundle uses one "
                    "RetrievalResult.",
        },
        "writer_identity": {
            "variant": ident.get("variant"),
            "clone": ident.get("clone"),
            "services_file": ident.get("services_file"),
            "python": ident.get("python"),
            "git_head": ident.get("git_head"),
            "git_tree": ident.get("git_tree"),
            "files_sha256_16": ident.get("files"),
            "gates": ident.get("gates"),
            "vec": writer.get("vec"),
        },
        "config": {
            "effective": (cfg.get("effective") or {}),
            "defaults": (cfg.get("defaults") or {}),
            "pg": cfg.get("pg"),
            "chat_override_keys": sorted((cfg.get("chat") or {}).keys()),
            "chat_override_count": len(cfg.get("chat") or {}),
            "env_flags": cfg.get("env_flags"),
            "model_identity": cfg.get("model_identity"),
        },
        "db_copy": db_copy_meta(),
        "correction_effect": corr,
        "constants": writer.get("constants"),
        "classes": classes,
        "plan_flows": plans,
        "sql": writer.get("sql"),
        "writer_errors": writer.get("errors"),
        "tool": {
            "identity": {
                "clone": (tool.get("identity") or {}).get("clone"),
                "git_head": (tool.get("identity") or {}).get("git_head"),
                "git_tree": (tool.get("identity") or {}).get("git_tree"),
                "files_sha256_16": (tool.get("identity") or {}).get("files"),
                "gates": (tool.get("identity") or {}).get("gates"),
            },
            "alias_mode": tool.get("alias_mode"),
            "vec": tool.get("vec"),
            "calls": tool_calls,
            "version_check": version_check,
            "errors": tool.get("errors"),
        },
        "checks": checks,
        "failed": [c["check"] for c in checks if not c["ok"]],
        "ok": all(c["ok"] for c in checks),
    }
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                               default=str), encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "failed": payload["failed"],
                      "n_checks": len(checks),
                      "bytes": dest.stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
