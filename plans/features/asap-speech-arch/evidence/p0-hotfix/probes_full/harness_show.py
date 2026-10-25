import json
import sys

for path in sys.argv[1:]:
    d = json.load(open(path, encoding="utf-8"))
    print("=" * 12, path, d.get("label"), d.get("case"))
    print("fatal", d.get("fatal"))
    print("errors", json.dumps(d.get("stage_errors"), ensure_ascii=False))
    for k in ("sources", "l2_summary", "base_prompt", "gates", "identity_block_chars",
              "rag_block_chars", "lessons_block_chars", "l1_input", "l1_plan",
              "plan_block", "system", "user", "l1_elapsed_s", "l1_parse_failed",
              "plan_source"):
        if k in d:
            print(k, "=>", json.dumps(d[k], ensure_ascii=False)[:700])
    layers = d.get("layers") or []
    print("layers", [(l["layer"], l["chars"], l["rendered"], l["skip_reason"]) for l in layers])
    for r in (d.get("l2_runs") or []):
        print("l2", json.dumps(r, ensure_ascii=False)[:300])
