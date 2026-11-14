# -*- coding: utf-8 -*-
"""Build the three evidence JSONs from the raw probe outputs.

Sanitises personal data (no participant names, no forum-token, no prompt or
alias overrides), computes the four metrics with the predicates frozen before
the run, and writes:
  formulation-class-matrix.json
  run-retrieval-trace.json
  metrics-comparison.json
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "artifacts"
DATE = "2026-11-15"
CHAT = -1002661910336
BASE_SHA = "c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5"
CAND_SHA = "f7a9c596638ea733de5673c5fd31675c746e20a7"
DB_SHA = "9fe79cdd9995081a90c1acaef28a7dfa5688da82c73699c10f2683b7fb3be501"
DB_BYTES = 3245551616
DB_SHA_RUN4 = "ce1044cf13da79ac154fc8a3901ca6b4e5e7ade70beb519a20bb8e7ddebb8060"

MEASURED_KEYS = (
    "flags.graph_rag_enabled",
    "flags.chat_rag_rerank_enabled",
    "flags.memory_communities_enabled",
    "flags.memory_identity_enabled",
    "flags.memory_attribution_enabled",
    "limits.graph_rag_facts_limit",
    "limits.graph_rag_context_max_chars",
    "limits.chat_rag_dedup_overlap_ratio",
    "limits.chat_episode_max_count",
    "limits.chat_episode_max_messages",
    "limits.chat_episode_gap_seconds",
    "limits.dig_max_snippets",
    "limits.dig_max_symbols",
)

# ── frozen per-class expectations (declared before looking at the outputs) ──
CLASS_SPEC = {
    "A1_creative_owner": {
        "role": "creative/exact owner query about the chat's core memes",
        "support": "shiz_msgs_by_year",
        "required_years": ["2022", "2023", "2024", "2025", "2026"],
        "temporal_mode": "span",
        "relevance": "shiz",
    },
    "A1P_plain_twin": {
        "role": "ordinary factual twin of the same topic (parity control)",
        "support": "shiz_msgs_by_year",
        "required_years": ["2022", "2023", "2024", "2025", "2026"],
        "temporal_mode": "span",
        "relevance": "shiz",
    },
    "A2_creative_generic": {
        "role": "creative story about the chat, 'over all years'",
        "support": "messages_by_year",
        "required_years": ["2022", "2023", "2024", "2025", "2026"],
        "temporal_mode": "span",
        "relevance": None,
    },
    "B_retell": {
        "role": "ordinary retelling, 'over all years'",
        "support": "messages_by_year",
        "required_years": ["2022", "2023", "2024", "2025", "2026"],
        "temporal_mode": "span",
        "relevance": None,
    },
    "C_person_profile": {
        "role": "participant profile without a year",
        "support": "person",
        "required_years": ["2022", "2023", "2024", "2025", "2026"],
        "temporal_mode": "span",
        "relevance": "person",
    },
    "D_conflict_2023": {
        "role": "reconstruction of a concrete conflict, explicit year 2023",
        "support": "conflict_msgs_by_year",
        "required_years": ["2023"],
        "temporal_mode": "exact",
        "relevance": "conflict",
    },
    "E_relations_years": {
        "role": "change of relations/views across years",
        "support": "messages_by_year",
        "required_years": ["2022", "2023", "2024", "2025", "2026"],
        "temporal_mode": "span",
        "relevance": "relation",
    },
    "T2_event_no_year": {
        "role": "event question without a year (old-period material required)",
        "support": "event",
        "required_years": ["2023"],
        "temporal_mode": "old",
        "relevance": "old_window",
    },
    "T3_current_state": {
        "role": "current-state question (control: must stay current)",
        "support": "messages_by_year",
        "required_years": ["2026"],
        "temporal_mode": "current",
        "relevance": "current",
    },
}


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def support_years(data: dict, spec: dict) -> list[str]:
    key = spec["support"]
    if key == "person":
        rows = data["sql"]["person"]["msgs_by_year"]
    elif key == "event":
        return ["2023"]
    else:
        rows = data["sql"][key]
    if not isinstance(rows, list):
        return []
    return [row["k"] for row in rows if int(row["n"]) > 0]


def variant_identity(raw: dict, db_sha: str | None = None) -> dict:
    ident = raw.get("identity") or {}
    cfg = ident.get("config") or {}
    effective = {k: cfg.get("effective", {}).get(k) for k in MEASURED_KEYS}
    defaults = {k: cfg.get("defaults", {}).get(k) for k in MEASURED_KEYS}
    return {
        "variant": ident.get("variant"),
        "git_head": ident.get("git_head"),
        "git_tree": ident.get("git_tree"),
        "files_sha256_16": ident.get("files"),
        "python": ident.get("python"),
        "deployed_app_dir": "/var/www/admin_bot",
        "measured_tree": ident.get("clone"),
        "db_sha256": db_sha,
        "config": {
            "effective": effective,
            "settings_defaults": defaults,
            "pg_snapshot": cfg.get("pg"),
            "model_identity": cfg.get("model_identity"),
            "env_flags": cfg.get("env_flags"),
        },
    }


def years_of(histogram: dict) -> list[str]:
    if not isinstance(histogram, dict):
        return []
    return [str(y) for y in histogram.keys() if str(y).isdigit()]


def coverage(reached: list[str], required: list[str]) -> dict:
    reached_set = {str(y) for y in reached}
    required_set = {str(y) for y in required}
    if not required_set:
        return {"ratio": None, "hit": [], "miss": [], "required": []}
    hit = sorted(reached_set & required_set)
    miss = sorted(required_set - reached_set)
    return {"ratio": round(len(hit) / len(required_set), 3),
            "hit": hit, "miss": miss, "required": sorted(required_set)}


def class_metrics(entry: dict, spec: dict, support: list[str]) -> dict:
    rag = entry.get("rag") or {}
    ep = entry.get("old_episode") or {}
    row_years = rag.get("row_years") or {}
    ep_years = ep.get("block_years") or {}
    rows = int(rag.get("rows") or 0)
    reached = sorted({*years_of(row_years), *years_of(ep_years)})
    cov = coverage(reached, spec["required_years"])
    topic = rag.get("row_topic") or {}
    meta = []
    for call in rag.get("retrieve") or []:
        res = call.get("result") or {}
        meta.extend(res.get("fact_rows_meta") or [])
    person_rows = sum(1 for row in meta if row.get("target_is_p1"))
    predicate = spec["relevance"]
    if predicate == "shiz":
        relevant = int(topic.get("shiz") or 0)
        judged = rows
    elif predicate == "conflict":
        relevant = int(topic.get("conflict") or 0)
        judged = rows
    elif predicate == "relation":
        relevant = int(topic.get("relation") or 0)
        judged = rows
    elif predicate == "person":
        relevant = person_rows
        judged = rows
    elif predicate == "old_window":
        relevant = sum(int(n) for year, n in row_years.items()
                       if str(year).isdigit() and int(year) < 2026)
        judged = rows
    elif predicate == "current":
        relevant = sum(int(n) for year, n in row_years.items()
                       if str(year).isdigit() and int(year) >= 2026)
        judged = rows
    else:
        relevant = None
        judged = None
    supported = [y for y in spec["required_years"] if y in support]
    return {
        "rows_delivered_rag": rows,
        "rag_years": row_years,
        "rag_distinct_years": len(years_of(row_years)),
        "old_episode_messages": (ep.get("stats") or {}).get("messages", 0),
        "old_episode_blocks": (ep.get("stats") or {}).get("count", 0),
        "old_episode_years": ep_years,
        "retrieve_calls": rag.get("retrieve_calls"),
        "period_fill": rag.get("period_stats"),
        "coverage": {**cov, "support_years": support,
                     "coverage_ratio_vs_support": (
                         None if not supported else
                         round(len([y for y in cov["hit"] if y in supported])
                               / len(supported), 3))},
        "multi_year": len(reached) >= 2,
        "relevance": ({"predicate": predicate, "relevant_rows": relevant,
                       "judged_rows": judged,
                       "precision": (None if not judged else
                                     round(relevant / judged, 3))}
                      if relevant is not None else
                      {"predicate": None, "note": "not separable: every chat "
                                                  "message is in scope"}),
        "history_query": entry.get("history_query"),
        "overview_delivered": any(
            (call.get("result") or {}).get("overview")
            for call in (rag.get("retrieve") or [])),
    }


def main() -> int:
    OUT.mkdir(exist_ok=True)
    base = load("base.json")
    cand = load("cand.json")
    rel_base = load("rel-base.json")
    rel_cand = load("rel-cand.json")
    lore_base = load("lore-base.json")
    lore_cand = load("lore-cand.json")

    support = {key: support_years(base, spec)
               for key, spec in CLASS_SPEC.items()}

    matrix = {
        "artifact_kind": "candidate_probe_not_live",
        "measurement_date": DATE,
        "method": {
            "where": "production host, throwaway clones of the exact commits, "
                     "fresh SQLite .backup copy of local_database.db",
            "live_process": False,
            "note": "the copy is not the live process; no LLM answer was "
                    "generated for the classes (VMQ-MEM-05)",
        },
        "deployed": {"head": BASE_SHA, "label": "2.58.203"},
        "baseline": variant_identity(base),
        "candidate": variant_identity(cand),
        "corpus": {
            "chat_scope": "single chat (id withheld)",
            "db_sha256": DB_SHA,
            "db_bytes": DB_BYTES,
            "db_sha256_lore_relations_copy": DB_SHA_RUN4,
            "messages_span_ts": base["sql"].get("messages_span"),
            "messages_by_year": base["sql"]["messages_by_year"],
            "messages_total": base["sql"]["messages_total"],
            "graph_facts_by_year": base["sql"]["graph_facts_by_year"],
            "episodes_by_year": base["sql"]["episodes_by_year"],
            "episodes_total": base["sql"]["episodes_total"],
            "shiz_msgs_by_year": base["sql"]["shiz_msgs_by_year"],
            "conflict_msgs_by_year": base["sql"]["conflict_msgs_by_year"],
            "person_msgs_by_year": base["sql"]["person"]["msgs_by_year"],
            "person_facts_by_year": base["sql"]["person_facts_by_year"],
            "event_counts": {k: v for k, v in
                             (base["sql"].get("event_counts") or {}).items()
                             if k != "token"},
        },
        "classes": [],
    }
    for key, spec in CLASS_SPEC.items():
        entry = {"class": key, "spec": spec, "support_years": support[key],
                 "variants": {}}
        for name, data in (("base", base), ("cand", cand)):
            payload = data["classes"].get(key) or {}
            entry["variants"][name] = {
                "query": payload.get("query"),
                **class_metrics(payload, spec, support[key]),
            }
        matrix["classes"].append(entry)

    # ── TIME windows: profile / dig / lore ────────────────────────────────
    def profile_view(data: dict, purpose: str) -> dict:
        value = (data.get("probes") or {}).get("profile_%s" % purpose) or {}
        return {k: value.get(k) for k in
                ("facts", "fact_years", "distinct_years", "status",
                 "empty_reason", "overview_slots", "coverage_lines",
                 "independent_periods", "counterexamples", "limitations",
                 "sources")}

    def dig_view(data: dict, name: str) -> dict:
        value = (data.get("probes") or {}).get("dig_%s" % name) or {}
        return {k: value.get(k) for k in
                ("sampling", "messages_total", "messages_shown", "truncated",
                 "first_seen", "last_seen", "snippets", "facts", "seconds")}

    matrix["time_windows"] = {
        "profile_biography": {name: profile_view(data, "biography")
                              for name, data in (("base", base),
                                                 ("cand", cand))},
        "profile_general": {name: profile_view(data, "general")
                            for name, data in (("base", base),
                                               ("cand", cand))},
        "dig": {name: dig_view(data, name) for name in
                ("event_no_year", "event_year_2023", "current_no_year",
                 "conflict_year_2023") for data in (base,)},
        "dig_by_variant": {
            "base": {name: dig_view(base, name) for name in
                     ("event_no_year", "event_year_2023", "current_no_year",
                      "conflict_year_2023")},
            "cand": {name: dig_view(cand, name) for name in
                     ("event_no_year", "event_year_2023", "current_no_year",
                      "conflict_year_2023")},
        },
        "lore_material": {
            "base": {k: lore_base.get(k) for k in
                     ("graph", "dialogs", "corpus_topic_by_year")},
            "cand": {k: lore_cand.get(k) for k in
                     ("graph", "dialogs", "corpus_topic_by_year")},
        },
        "relations": {
            "base": {k: rel_base.get(k) for k in ("tool", "retrieve")},
            "cand": {k: rel_cand.get(k) for k in ("tool", "retrieve")},
        },
    }
    (OUT / "formulation-class-matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── raw trace (sanitised) ─────────────────────────────────────────────
    def trace(data: dict) -> dict:
        classes = {}
        for key, payload in (data.get("classes") or {}).items():
            classes[key] = {
                "query": payload.get("query"),
                "history_query": payload.get("history_query"),
                "caps": payload.get("caps"),
                "rag": payload.get("rag"),
                "old_episode": payload.get("old_episode"),
                "errors": {k: v for k, v in payload.items()
                           if k.endswith("_error")},
            }
        probes = {}
        for name, value in (data.get("probes") or {}).items():
            if name.startswith("relations_channel"):
                continue
            probes[name] = value
        return {"identity": variant_identity(data), "classes": classes,
                "probes": probes,
                "constants": data.get("constants"),
                "caps_composer": data.get("caps_composer"),
                "vec": data.get("vec"), "alias_mode": data.get("alias_mode"),
                "errors": data.get("errors")}

    trace_doc = {
        "artifact_kind": "candidate_probe_not_live",
        "measurement_date": DATE,
        "note": "per-run trace of the single mca retrieve() call and of the "
                "blocks that reach the Writer: no answer text, ids/periods/"
                "sources only",
        "baseline": trace(base),
        "candidate": trace(cand),
        "relations_probe": {"base": rel_base, "cand": rel_cand},
        "lore_probe": {"base": lore_base, "cand": lore_cand},
    }
    (OUT / "run-retrieval-trace.json").write_text(
        json.dumps(trace_doc, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── metrics comparison ────────────────────────────────────────────────
    def metrics_of(entry: dict) -> dict:
        return {name: {
            "coverage_ratio_vs_support": row["coverage"]["coverage_ratio_vs_support"],
            "coverage_hit_years": row["coverage"]["hit"],
            "coverage_miss_years": row["coverage"]["miss"],
            "multi_year": row["multi_year"],
            "rows_rag": row["rows_delivered_rag"],
            "rag_years": row["rag_years"],
            "old_episode_messages": row["old_episode_messages"],
            "old_episode_years": row["old_episode_years"],
            "relevance_precision": row["relevance"].get("precision"),
            "overview_delivered": row["overview_delivered"],
        } for name, row in entry["variants"].items()}

    metrics_doc = {
        "artifact_kind": "candidate_probe_not_live",
        "measurement_date": DATE,
        "metric_definitions": {
            "coverage": "years actually delivered to the Writer block / years "
                        "that the corpus supports for the class question",
            "chronological_accuracy": "share of delivered rows inside the "
                                      "question's temporal target (only for "
                                      "queries with an explicit target)",
            "relevance": "deterministic predicate over delivered rows "
                         "(topic stem / conflict stem / relation stem / "
                         "subject attribution); no LLM judge",
            "fabricated_relations": "relations delivered without edge/fact "
                                    "source (has_unsupported_sources or "
                                    "missing ids)",
        },
        "by_class": {entry["class"]: metrics_of(entry)
                     for entry in matrix["classes"]},
        "temporal_accuracy": {},
        "relations_metric": {},
        "parity": {},
        "requirement_mapping": [],
        "limits": [],
    }

    def acc(entry: dict, name: str, target: set[str], label: str) -> None:
        rows = entry["variants"][name]
        hist = rows["rag_years"] or {}
        total = sum(int(n) for n in hist.values()) or 0
        inside = sum(int(n) for year, n in hist.items()
                     if str(year) in target)
        ep = rows["old_episode_years"] or {}
        ep_total = sum(int(n) for n in ep.values()) or 0
        ep_inside = sum(int(n) for year, n in ep.items() if str(year) in target)
        metrics_doc["temporal_accuracy"].setdefault(entry["class"], {})[name] = {
            "target": label,
            "rag_share_inside_target": (round(inside / total, 3)
                                        if total else None),
            "rag_rows_inside": inside,
            "rag_rows_total": total,
            "episode_share_inside_target": (round(ep_inside / ep_total, 3)
                                            if ep_total else None),
            "episode_messages_total": ep_total,
        }

    by_class = {entry["class"]: entry for entry in matrix["classes"]}
    acc(by_class["D_conflict_2023"], "base", {"2023"}, "2023")
    acc(by_class["D_conflict_2023"], "cand", {"2023"}, "2023")
    acc(by_class["T2_event_no_year"], "base", {"2022", "2023", "2024", "2025"},
        "pre-2026")
    acc(by_class["T2_event_no_year"], "cand", {"2022", "2023", "2024", "2025"},
        "pre-2026")
    acc(by_class["T3_current_state"], "base", {"2026"}, "2026")
    acc(by_class["T3_current_state"], "cand", {"2026"}, "2026")

    for name, data in (("base", rel_base), ("cand", rel_cand)):
        tool = data.get("tool") or {}
        edges = tool.get("edges") or []
        metrics_doc["relations_metric"][name] = {
            "tool_status": tool.get("status"),
            "tool_empty_reason": tool.get("empty_reason"),
            "relations_delivered": tool.get("relations"),
            "edges_with_sources": sum(1 for edge in edges
                                      if edge.get("has_edge_id")
                                      or edge.get("has_fact_id")),
            "edges_unsupported": sum(1 for edge in edges
                                     if edge.get("unsupported_sources")),
            "fabricated_relations": sum(
                1 for edge in edges
                if not (edge.get("has_edge_id") or edge.get("has_fact_id"))),
            "retrieve_subject_relations": (
                (data.get("retrieve") or {}).get("subject_relations") or {}
            ).get("relations"),
        }

    creative = metrics_doc["by_class"]["A1_creative_owner"]
    plain_twin = metrics_doc["by_class"]["A1P_plain_twin"]
    retell = metrics_doc["by_class"]["B_retell"]
    person = metrics_doc["by_class"]["C_person_profile"]
    metrics_doc["parity"] = {
        "question": "parity: an ordinary factual question is not worse than "
                    "the creative story (VMQ-MEM-04)",
        "creative_material_owner_query": {
            "variant": "base=cand",
            **creative["base"],
        },
        "creative_answer_path_material": matrix["time_windows"]["lore_material"],
        "plain_twin": plain_twin["base"],
        "plain_retell": retell["base"],
        "person_reply_block": person["base"],
        "person_profile_biography":
            matrix["time_windows"]["profile_biography"]["base"],
        "verdict": "NOT ACHIEVED — see measurement-2026-11-15.md §5",
    }

    map_ref = {
        "matrix": "plans/features/vmq-onto-01/evidence/vmq-mem/"
                  "formulation-class-matrix.json",
        "trace": "plans/features/vmq-onto-01/evidence/vmq-mem/"
                 "run-retrieval-trace.json",
        "metrics": "plans/features/vmq-onto-01/evidence/vmq-mem/"
                   "metrics-comparison.json",
        "report": "plans/features/vmq-onto-01/evidence/vmq-mem/"
                  "measurement-2026-11-15.md",
    }

    def row(req_id, verdict, evidence, refs, gap=""):
        return {"req_id": req_id, "verdict": verdict, "observed": evidence,
                "artifact_refs": refs, "gap": gap}

    metrics_doc["requirement_mapping"] = [
        row("VMQ-MEM-01", "evidence_provided",
            "9 formulations measured on one frozen corpus copy: exact owner "
            "query, its ordinary twin, generic creative, retelling, person, "
            "explicit-2023 conflict, relations across years, event without "
            "year, current state",
            [map_ref["matrix"] + "#classes"], ""),
        row("VMQ-MEM-02", "evidence_provided",
            "per-run trace of every retrieve() call (request fields, status, "
            "channels, candidate pool by type/year, fact rows, period fill, "
            "relevance decision) plus the Writer blocks; candidate adds "
            "bounded overview slots on the history-marker path and in the "
            "person tool",
            [map_ref["trace"]], "no EvidenceBundle object was serialised; "
            "overview slots + block material are recorded instead"),
        row("VMQ-MEM-03", "evidence_provided",
            "four metrics computed: coverage 0.0-1.0 per class, "
            "chronological accuracy only where a target exists (D=0.0, "
            "T2=0.0, T3=1.0), deterministic relevance precision, fabricated "
            "relations 0/0 delivered",
            [map_ref["metrics"] + "#by_class"], "relevance is a keyword/"
            "attribution predicate, not a human/LLM judge"),
        row("VMQ-MEM-04", "not_satisfied",
            "parity fails: creative answer path (Lore material) delivers "
            "148 rows from 2022-2023 + 6 graph edges for the owner topic, "
            "while the ordinary twin/retelling/person reply blocks deliver "
            "0 pre-2026 rows; the person RAG block has 0 rows attributed to "
            "the person",
            [map_ref["metrics"] + "#parity", map_ref["report"] + "#5"], ""),
        row("VMQ-MEM-05", "satisfied_by_method",
            "no answer text was generated for the classes; nothing is "
            "counted from a creative answer — only retrieve()/block trace",
            [map_ref["report"] + "#2"], ""),
        row("VMQ-MEM-06", "not_measured_here",
            "the deployment-wide e2e path document is unchanged "
            "(architect-e2e-path.md on 32e018b9); this run re-confirms the "
            "same seam (single retrieve, Old_Episode consumer) on c97c06e4",
            [map_ref["trace"]], "a re-authored Architect document was not "
            "part of this Builder task"),
        row("VMQ-MEM-07", "not_measured_here",
            "Reviewer's independent comparison on the real archive is not "
            "Builder-owned; this run supplies candidate-bound inputs for it",
            [map_ref["matrix"], map_ref["metrics"]], ""),
        row("VMQ-MEM-08", "partially_measured",
            "single retrieve() implementation in both trees "
            "(mca_retrieval_context.py), no DDL in the candidate diff, "
            "_HISTORY_MARKERS unchanged; candidate adds an overview "
            "projection over existing M1 reads, no new store",
            [map_ref["trace"]], "ONTO-01 modules exist only in the candidate "
            "(semantic_contracts.py absent on the deployed baseline), so a "
            "cross-variant ONTO control is not possible on c97c06e4"),
        row("VMQ-TIME-01", "not_satisfied",
            "history/person questions stay 2026-bound: 8-10 of 10 RAG rows "
            "are 2026; the explicit-2023 conflict question delivers 0 rows "
            "from 2023 (RAG 9 rows {2025:1, 2026:8}; episodes 82 messages "
            "{2025:19, 2026:63})",
            [map_ref["matrix"] + "#classes", map_ref["metrics"]], ""),
        row("VMQ-TIME-02", "partial",
            "person profile via purpose=biography delivers 11 facts across 5 "
            "years (2022-2026); purpose=general still 8 facts, all 2026; the "
            "person reply RAG block is all 2026 with 0 rows attributed to "
            "the person; graph_facts about the person exist only for 2026 "
            "(35), while 44 577 messages exist for 2023-2024",
            [map_ref["matrix"] + "#time_windows"], ""),
        row("VMQ-TIME-03", "not_satisfied",
            "event question without a year: 10/10 RAG rows 2026, 0 episode "
            "messages, 0 pre-2026 rows; the year window works only inside "
            "the dig tool when a year is passed explicitly "
            "(window_scan_by_time, 97 724 messages in 2023)",
            [map_ref["matrix"] + "#time_windows"], "no frequent topic token "
            "in this archive is 4x denser in 2023 than 2026, so the class is "
            "'old material required', not 'one uniquely old event'"),
        row("VMQ-TIME-04", "evidence_provided",
            "per block years recorded and the loss stage named: vector "
            "period leg compat_not_proven (0 knn rows), subject filter "
            "rejected 13-16 of 16 lexical period rows, episode cap 2 / "
            "typed ranking, dig payload budget hides snippets (0 shown)",
            [map_ref["trace"]], ""),
        row("VMQ-TIME-05", "partially_confirmed",
            "root-cause branches are re-checked on the deployed tree: period "
            "slot = limit//5 with min 2 shared stems under auto; freshness "
            "bonus in typed_rank_score; graph_facts year distribution; "
            "profile purpose; episode slice div=2",
            [map_ref["trace"]], "the written root-cause document stays the "
            "authority for the code-level proof; this run measures the "
            "effect, not a new diagnosis"),
        row("VMQ-TIME-06", "not_satisfied",
            "the existing mechanism is reused (one retrieve, no new store, "
            "no embeddings change) but the temporal-extent defect is not "
            "fixed by the measured candidate: identical blocks in baseline "
            "and candidate",
            [map_ref["metrics"], map_ref["trace"]], ""),
        row("VMQ-TIME-07", "evidence_provided",
            "before/after matrix on the real anonymised archive: baseline "
            "c97c06e4 and candidate f7a9c596 are identical on every "
            "measured class (no degradation and no improvement); 2023-2024 "
            "threshold not reached",
            [map_ref["matrix"], map_ref["report"] + "#4"], ""),
        row("VMQ-TIME-08", "not_measured_here",
            "Reviewer's independent archive confirmation is not "
            "Builder-owned",
            [map_ref["metrics"]], ""),
    ]

    metrics_doc["limits"] = [
        "the SQLite copy is not the live process: L1 plan, dedup against the "
        "global context (passed empty), budgets and the Writer prompt are not "
        "exercised; blocks are measured at the producer boundary",
        "the embedding provider returned EMBED_API_FAILED once per variant "
        "and the vector period leg reported compat_not_proven, so the KNN "
        "period path was inactive and only lexical period rows were "
        "available; production may differ",
        "flags.chat_rag_rerank_enabled is effectively true in production, so "
        "the LLM reranker decided which fact rows survived; a rerun may "
        "produce a different row set. The A/B pair used identical config and "
        "identical candidate ids at pool level",
        "dig snippets are squeezed out by the payload budget (snippets=0), so "
        "the year window is proven by coverage counters only",
        "no answer text was generated (VMQ-MEM-05), so answer quality and "
        "'invented claims in text' are out of scope of this measurement",
        "the relations path delivered nothing in both variants (tool "
        "empty_reason=empty, 0 edges, retrieve subject channel 0 relations), "
        "so the fabricated-relations metric is vacuously 0 and unfalsifiable "
        "here",
        "the creative answer path measured is the LoreCompiler material "
        "builder (lore_graph_slice + lore_dense_dialogs) without generation; "
        "whether the model actually calls compile_lore_story in production is "
        "not proven by this trace",
        "one chat, one query per class, one run per variant: no statistical "
        "generalisation",
        "candidate f7a9c596 is not deployed; every candidate figure is "
        "candidate_probe_not_live",
    ]

    catalog_sha = sha256(HERE / "probe.py")
    metrics_doc["harness"] = {
        "probe.py_sha256": catalog_sha,
        "entities.py_sha256": sha256(HERE / "entities.py"),
        "cfg_probe.py_sha256": sha256(HERE / "cfg_probe.py"),
        "relations_probe.py_sha256": sha256(HERE / "relations_probe.py"),
        "lore_probe.py_sha256": sha256(HERE / "lore_probe.py"),
        "raw_base_sha256": sha256(HERE / "base.json"),
        "raw_cand_sha256": sha256(HERE / "cand.json"),
    }
    (OUT / "metrics-comparison.json").write_text(
        json.dumps(metrics_doc, ensure_ascii=False, indent=1),
        encoding="utf-8")

    print("WROTE", [p.name for p in OUT.iterdir()])
    for key in ("A1_creative_owner", "A1P_plain_twin", "B_retell",
                "D_conflict_2023", "T2_event_no_year", "T3_current_state"):
        print(key, json.dumps(metrics_doc["by_class"][key]["base"],
                              ensure_ascii=False))
    print("temporal", json.dumps(metrics_doc["temporal_accuracy"],
                                 ensure_ascii=False))
    print("relations", json.dumps(metrics_doc["relations_metric"],
                                 ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
