"""Compact durable summary of the NEXT-02 final paired measurement."""
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.environ.get("RAW_DIR", HERE)


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return json.load(fh)


def sha(name):
    path = os.path.join(HERE, name)
    with open(path, "rb") as fh:
        return {"file": name, "bytes": os.path.getsize(path),
                "sha256": hashlib.sha256(fh.read()).hexdigest()}


scores = {}
for tag, name in (("det", "next2final-score-det.json"),
                  ("rerank_r1", "next2final-score-r1.json"),
                  ("rerank_r2", "next2final-score-r2.json"),
                  ("noise_base_r1_vs_r2", "next2final-score-noise-base.json"),
                  ("noise_cand_r1_vs_r2", "next2final-score-noise-cand.json")):
    score = load(name)
    scores[tag] = {"summary": score["summary"],
                   "fresh_loss": score["fresh_loss"],
                   "n_pairs": len(score["per_query"])}

raw_meta = {}
for tag, name in (("base_det", "next2final-raw-base-det.json"),
                  ("cand_det", "next2final-raw-cand-det.json"),
                  ("base_r1", "next2final-raw-base-r1.json"),
                  ("cand_r1", "next2final-raw-cand-r1.json"),
                  ("base_r2", "next2final-raw-base-r2.json"),
                  ("cand_r2", "next2final-raw-cand-r2.json")):
    with open(os.path.join(RAW_DIR, name), encoding="utf-8") as fh:
        raw = json.load(fh)
    empty = sum(1 for item in raw["items"] for run in item["runs"].values()
                if not str(run.get("block") or "").strip())
    raw_meta[tag] = {
        "git_head": raw["meta"]["git_head"], "tag": raw["meta"]["tag"],
        "seam": raw["meta"]["seam"], "batch_s": raw["meta"]["batch_s"],
        "empty_blocks": empty,
        "frozen_embeddings": (raw.get("frozen_embeddings") or {}).get("sha256"),
        "frozen_hits": (raw.get("frozen_embeddings") or {}).get("hits"),
        "completed": len(raw["meta"].get("completed") or []),
        "missing": raw["meta"].get("missing"),
    }

sample = load("next2final-gold-v2.json")
payload = {
    "contract": "plans/features/vmq-onto-01/architecture-next2-quality.md",
    "base": "234776589c934024ed0e8dceba189fb9d70d3215",
    "candidate": "96c8bc7279c5a83afedeb9f38724006e83eaceab",
    "corpus": {
        "source": "probe-d86a98460c/prod-copy.db (read-only)",
        "sha256": "5310e91e282813f6342c950eb3ee182dc93e9ad6fdf54fdd91d3287e394082b2",
    },
    "sample": {
        "queries": len(sample["queries"]),
        "per_stratum": sample["meta"]["n"],
        "corpus_year_composition": sample["meta"]["corpus_year_composition"],
        "corpus_facts": sample["meta"]["corpus_confirmed_facts"],
        "rules": sample["meta"].get("evidence_rule"),
        "query_template": sample["meta"]["rules"]["query_template"],
    },
    "artifacts": [sha(name) for name in (
        "next2final-sample.json", "next2final-gold-v2.json",
        "next2final-embeddings.json", "next2final-harness.py",
        "next2final-sample.py", "next2final-evidence-sets.py",
        "next2final-freeze-emb.py", "next2final-run.py",
        "next2final-score.py", "next2final-trim.py",
        "next2final-trimmed-base-det.json",
        "next2final-trimmed-cand-det.json", "next2final-trimmed-base-r1.json",
        "next2final-trimmed-cand-r1.json", "next2final-trimmed-base-r2.json",
        "next2final-trimmed-cand-r2.json",
        "next2final-provider-fallback-repro.json")],
    "runs": raw_meta,
    "scores": scores,
}
path = os.path.join(HERE, "next2final-summary.json")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=1)
print("wrote", path, os.path.getsize(path))
