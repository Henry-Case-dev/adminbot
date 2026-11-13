"""Render the measurement section of the binding evidence from score JSONs."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return json.load(fh)


def fmt(value, digits=3):
    return "n/a" if value is None else ("%.*f" % (digits, value))


def table(score, label):
    lines = ["#### %s" % label, "",
             "| Страта / срез | Пар | recall_evidence base→cand | "
             "recall_exact base→cand | precision base→cand | "
             "cov_rows base→cand | cov_block base→cand | "
             "2026 share base→cand | Δrecall CI | Δprecision CI |",
             "|---|---:|---|---|---|---|---|---|---|---|"]
    for name in ("old/primary", "multi/primary", "recent/primary",
                 "old/both", "multi/both", "recent/both"):
        row = score["summary"].get(name)
        if not row:
            continue
        lines.append(
            "| %s | %d | %s → %s | %s → %s | %s → %s | %s → %s | %s → %s | "
            "%s → %s | %s | %s |" % (
                name, row["n_pairs"],
                fmt(row["recall_evidence"][0]), fmt(row["recall_evidence"][1]),
                fmt(row["recall_rows"][0]), fmt(row["recall_rows"][1]),
                fmt(row["precision"][0]), fmt(row["precision"][1]),
                fmt(row["coverage_rows"][0], 2),
                fmt(row["coverage_rows"][1], 2),
                fmt(row["coverage_block"][0], 2),
                fmt(row["coverage_block"][1], 2),
                fmt(row["year_share_2026"][0]), fmt(row["year_share_2026"][1]),
                row["bootstrap_recall_evidence_delta"]["ci95"],
                row["bootstrap_precision_delta"]["ci95"]))
    lines.append("")
    losses = [item for item in score["fresh_loss"]
              if item.get("lost") or item.get("lost_evidence")]
    lines.append("Потери обязательных фактов/свидетельств baseline у candidate: "
                 "**%d**." % len(losses))
    for item in losses:
        lines.append("* %s/%s: %s" % (item["key"], item["policy"],
                                      item.get("lost")
                                      or item.get("lost_evidence")))
    return "\n".join(lines)


def main():
    det = load(sys.argv[1])
    rerank = load(sys.argv[2]) if len(sys.argv) > 2 else None
    out = ["## Paired quality (same corpus copy, same fixed queries, "
           "frozen query embeddings)", ""]
    out.append("### Детерминированный retrieval-срез "
               "(identity-вердикт реарнка, LLM-судья не участвует)")
    out.append(table(det, "deterministic pair"))
    if rerank:
        out.append("")
        out.append("### Effective config (штатный LLM-реарнк включён)")
        out.append(table(rerank, "rerank-on pair"))
    text = "\n".join(out)
    with open(os.path.join(HERE, "next2final-tables.md"), "w",
              encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
