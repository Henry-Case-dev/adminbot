#!/usr/bin/env python3
"""P0 LIVE-FINAL-GUARDS analysis (offline, read-only).

Reads raw harness JSONs from <run_root>/raw, applies the SAME production
direct-L2 guards as services/direct_chat_service.py (meta lead + unverified
quotes) with the SAME source blocks that the Writer received, and writes
analysis.json + manifest.json. No network, no DB writes.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys

EXPECTED_CORE_CHARS = 3294
EXPECTED_CORE_SHA12 = "ead77b2ab509"

RUNS = [
    ("new_A", "raw_new_A.json"),
    ("new_B", "raw_new_B.json"),
    ("new_C", "raw_new_C.json"),
    ("new_D", "raw_new_D.json"),
    ("new_E", "raw_new_E.json"),
    ("new_F", "raw_new_F.json"),
    ("forced_A", "raw_forced_A.json"),
    ("forced_B", "raw_forced_B.json"),
]

DATE_RE = re.compile(
    r"\b(?:19|20)\d{2}\b|\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b|"
    r"(?i:\b(?:январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|"
    r"июл[ья]|август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья])\b)",
)
NUM_RE = re.compile(r"(?m)^\s*(?:\d{1,2}[.)]|[-•*])\s+\S")
STRICT_META_PREFIX_RE = re.compile(
    r"^(?:ну|ладно|ок|окей|окэй|так|итак|сейчас|давай|глянул|посмотрел|"
    r"разложу|разберу|разберём|начну|начнём)\b",
    re.IGNORECASE,
)


def strip_lead_markup(text: str) -> str:
    return re.sub(r"^[\s*_\"'«»]+", "", text or "")


def strict_meta(sentence: str) -> bool:
    return bool(STRICT_META_PREFIX_RE.match(strip_lead_markup(sentence)))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def extract_block(tag: str, text: str) -> str:
    m = re.search(r"<%s>.*?</%s>" % (tag, tag), text or "", re.S)
    return m.group(0) if m else ""


def first_sentence(text: str) -> str:
    head = (text or "").split("\n", 1)[0]
    m = re.search(r"[.!?…]+(?=\s|$)", head)
    return (head[:m.end()] if m else head).strip()


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "/tmp/p0-final5/new"
    run_root = sys.argv[2] if len(sys.argv) > 2 else "/tmp/p0-final5"
    raw_dir = os.path.join(run_root, "raw")
    os.chdir(root)
    sys.path.insert(0, root)

    from services import direct_chat_service as dcs
    from services import prompt_style_blocks as psb
    from services import summary_l2_writer as sl2

    def quote_scan(text: str, pool, pool_source):
        total = kept = non = byte_kept = 0
        examples = []
        for m in sl2._QUOTE_RE.finditer(text or ""):
            q = m.group(0)
            before = (text or "")[:m.start()]
            if before.rfind("<") > before.rfind(">"):
                continue
            inner = sl2._strip_quotes(q)
            if (not inner.strip() or "<" in q or ">" in q
                    or not any(ch.isalpha() for ch in inner)):
                continue
            total += 1
            if sl2._quote_matches_pool(q, pool):
                kept += 1
                if any(inner in s for s in pool_source):
                    byte_kept += 1
            else:
                non += 1
                if len(examples) < 4:
                    examples.append(inner[:80])
        return {"total": total, "kept": kept, "unquoted": non,
                "byte_exact_kept": byte_kept, "non_exact_examples": examples}

    runs_out = []
    all_meta_raw = all_meta_final = 0
    all_quotes_raw = all_quotes_final = all_nonfinal = 0
    cores_ok = 0
    malformed = 0
    for label, fname in RUNS:
        path = os.path.join(raw_dir, fname)
        if not os.path.isfile(path):
            runs_out.append({"label": label, "file": fname,
                             "missing": True})
            malformed += 1
            continue
        d = json.load(open(path, encoding="utf-8"))
        user_text = (d.get("payload", {}).get("messages", [{}, {}])[1]
                     .get("content", "") if d.get("payload") else "")
        system = (d.get("payload", {}).get("messages", [{}])[0]
                  .get("content", "") if d.get("payload") else "")
        question = d.get("question") or ""
        blocks = [extract_block(t, user_text)
                  for t in ("RAG_Memory", "Global_Context",
                            "Target_User", "Current_Question")]
        blocks = [b for b in blocks if b]
        pool_source = [question] + blocks
        pool = [sl2._normalize_quote(x) for x in pool_source if x.strip()]

        core_info = {"found": 0, "offsets": [], "chars": 0, "sha12": ""}
        for i in range(0, max(0, len(system) - EXPECTED_CORE_CHARS + 1)):
            sl = system[i:i + EXPECTED_CORE_CHARS]
            if hashlib.sha256(sl.encode("utf-8")).hexdigest()[:12] \
                    == EXPECTED_CORE_SHA12:
                core_info["found"] += 1
                core_info["offsets"].append(i)
                core_info["chars"] = len(sl)
                core_info["sha12"] = EXPECTED_CORE_SHA12
                if core_info["found"] >= 2:
                    break
        if core_info["found"]:
            cores_ok += 1

        payload_counts = {
            "analysis_directive": (system + user_text).count(
                getattr(psb, "ANALYSIS_DIRECTIVE_TEXT", "") or ""),
            "analysis_writer": (system + user_text).count(
                getattr(psb, "ANALYSIS_WRITER_TEXT", "") or ""),
            "no_meta": (system + user_text).count(
                getattr(psb, "NO_META_STRUCTURE_TEXT", "") or ""),
            "quote_fidelity": (system + user_text).count(
                getattr(psb, "QUOTE_FIDELITY_TEXT", "") or ""),
        }

        rag_block = extract_block("RAG_Memory", user_text)
        rag_markers = {
            "unconfirmed": rag_block.count("(не подтверждено)"),
            "assumption": rag_block.count("(предположение)"),
            "chat": rag_block.count("[чат]"),
            "bot": rag_block.count("[Бот]"),
        }

        texts = list(d.get("l2_texts") or [])
        per_text = []
        for text in texts:
            raw_meta = first_sentence(text)
            raw_meta_flag = bool(
                dcs._L2_META_FILLER_RE.match(raw_meta)
                or dcs._L2_META_ANNOUNCE_RE.match(raw_meta)
                or strict_meta(raw_meta))
            guarded, meta_stats = dcs.strip_l2_meta_lead(text)
            guarded, quote_stats = dcs.strip_unverified_l2_quotes(
                guarded, query=question, blocks=blocks, evidence="")
            final_meta = first_sentence(guarded)
            final_meta_flag = bool(
                dcs._L2_META_FILLER_RE.match(final_meta)
                or dcs._L2_META_ANNOUNCE_RE.match(final_meta)
                or strict_meta(final_meta))
            raw_q = quote_scan(text, pool, pool_source)
            fin_q = quote_scan(guarded, pool, pool_source)
            all_meta_raw += int(raw_meta_flag)
            all_meta_final += int(final_meta_flag)
            all_quotes_raw += raw_q["total"]
            all_quotes_final += fin_q["total"]
            all_nonfinal += fin_q["unquoted"]
            per_text.append({
                "raw_chars": len(text or ""),
                "final_chars": len(guarded or ""),
                "raw_first_sentence": raw_meta[:160],
                "final_first_sentence": final_meta[:160],
                "raw_meta": raw_meta_flag,
                "final_meta": final_meta_flag,
                "meta_stats": meta_stats,
                "quote_stats": quote_stats,
                "quotes_raw": raw_q,
                "quotes_final": fin_q,
                "numbered_lines": len(NUM_RE.findall(guarded or "")),
                "dates": sorted(set(DATE_RE.findall(guarded or "")))[:10],
                "selfecho": (guarded or "").count("я уже говорил"),
                "final_text": guarded,
            })

        plan = d.get("l1_plan") or {}
        runs_out.append({
            "label": label,
            "file": fname,
            "question": question,
            "forced": bool(d.get("forced")),
            "plan_source": d.get("plan_source"),
            "l1_plan": plan,
            "extent": plan.get("extent"),
            "structure": plan.get("structure"),
            "mode": d.get("mode"),
            "analysis_predicate": d.get("analysis_predicate"),
            "l1_attempts": d.get("l1_attempts"),
            "l1_elapsed_s": d.get("l1_elapsed_s"),
            "l1_canon": d.get("l1_canon"),
            "invalid": d.get("invalid"),
            "fatal": d.get("fatal"),
            "stage_errors": d.get("stage_errors"),
            "core": core_info,
            "payload_counts": payload_counts,
            "rag": d.get("rag"),
            "rag_markers": rag_markers,
            "freq": d.get("expression_check"),
            "expression_doc": d.get("expression_doc"),
            "alias": d.get("alias_probe"),
            "composer_on": d.get("composer_on"),
            "extent_scrub_removed": d.get("extent_scrub_removed"),
            "l2": per_text,
            "l2_raw_lengths": [len(t or "") for t in texts],
            "l2_final_lengths": [x["final_chars"] for x in per_text],
            "l2_count": len(texts),
            "llm_model": (d.get("llm") or {}).get("model"),
            "pins_git": (d.get("pins") or {}).get("git"),
            "pins_harness": ((d.get("pins") or {}).get("harness") or {}).get("sha256"),
        })

    by = {r["label"]: r for r in runs_out}
    natural_ab = [by.get("new_A"), by.get("new_B")]
    ab_research = sum(
        1 for r in natural_ab
        if r and r.get("plan_source") == "llm"
        and (r.get("l1_plan") or {}).get("response_act") == "research")
    forced_ab = [by.get("forced_A"), by.get("forced_B")]
    forced_research = sum(
        1 for r in forced_ab
        if r and r.get("plan_source") == "forced"
        and (r.get("l1_plan") or {}).get("response_act") == "research")
    e = by.get("new_E") or {}
    e_plan = e.get("l1_plan") or {}

    summary = {
        "l1_natural_ab_research": {"count": ab_research, "of": 2,
                                   "runs": [
                                       {"label": r.get("label"),
                                        "act": (r.get("l1_plan") or {}).get("response_act"),
                                        "source": r.get("plan_source"),
                                        "extent": (r.get("l1_plan") or {}).get("extent")}
                                       for r in natural_ab if r]},
        "l1_forced_ab_research": {"count": forced_research, "of": 2},
        "e_not_silent": bool(e_plan.get("action") not in (None, "silent")
                             and e_plan.get("response_act") == "research"),
        "e_route": {"action": e_plan.get("action"),
                    "response_act": e_plan.get("response_act"),
                    "extent": e_plan.get("extent"),
                    "structure": e_plan.get("structure"),
                    "confidence": e_plan.get("confidence")},
        "meta_first_sentence": {"raw": all_meta_raw, "final": all_meta_final,
                                "of": sum(r.get("l2_count", 0) for r in runs_out),
                                "final_examples": [
                                    {"label": r["label"], "repeat": i + 1,
                                     "first": t["final_first_sentence"]}
                                    for r in runs_out for i, t in enumerate(r.get("l2") or [])
                                    if t.get("final_meta")]},
        "quotes": {"raw_total": all_quotes_raw,
                   "final_total": all_quotes_final,
                   "final_non_exact": all_nonfinal},
        "core": {"runs_with_expected_core": cores_ok,
                 "of": len(runs_out), "chars": EXPECTED_CORE_CHARS,
                 "sha12": EXPECTED_CORE_SHA12},
        "malformed": malformed,
        "invalid_runs": [r["label"] for r in runs_out
                         if r.get("invalid") or r.get("fatal")],
        "l1_attempts": {r["label"]: r.get("l1_attempts") for r in runs_out},
        "b_lengths": (by.get("new_B") or {}).get("l2_final_lengths"),
        "e_lengths": (by.get("new_E") or {}).get("l2_final_lengths"),
        "c_d_f": {k: {"act": ((by.get(k) or {}).get("l1_plan") or {}).get("response_act"),
                       "extent": (by.get(k) or {}).get("extent"),
                       "lengths": (by.get(k) or {}).get("l2_final_lengths")}
                  for k in ("new_C", "new_D", "new_F")},
    }

    out = {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": root,
        "run_root": run_root,
        "expected_core": {"chars": EXPECTED_CORE_CHARS,
                          "sha12": EXPECTED_CORE_SHA12},
        "runs": runs_out,
        "summary": summary,
    }
    analysis_path = os.path.join(run_root, "analysis.json")
    json.dump(out, open(analysis_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    files = []
    for base, _dirs, names in os.walk(run_root):
        for name in names:
            p = os.path.join(base, name)
            rel = os.path.relpath(p, run_root).replace("\\", "/")
            if rel == "manifest.json":
                continue
            files.append({"file": rel, "bytes": os.path.getsize(p),
                          "sha256": sha256_file(p)})
    manifest = {
        "generated_utc": out["generated_utc"],
        "root": root,
        "files": sorted(files, key=lambda x: x["file"]),
        "analysis_script": {
            "path": os.path.basename(os.path.abspath(__file__)),
            "sha256": sha256_file(os.path.abspath(__file__)),
        },
        "harness": {
            "probes_full/harness_probe_full.py": sha256_file(
                os.path.join(root, "probes_full", "harness_probe_full.py")),
            "probes_full/harness_extra.py": (
                sha256_file(os.path.join(root, "probes_full",
                                         "harness_extra.py"))
                if os.path.isfile(os.path.join(root, "probes_full",
                                               "harness_extra.py")) else ""),
        },
        "pins_git": ((by.get("new_A") or {}).get("pins_git")),
        "pins_harness": ((by.get("new_A") or {}).get("pins_harness")),
    }
    json.dump(manifest, open(os.path.join(run_root, "manifest.json"), "w",
                             encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"summary": summary,
                      "harness": manifest["harness"]},
                     ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
