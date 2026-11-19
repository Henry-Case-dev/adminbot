# TIME-03 real-archive S1–S7 acceptance harness

Evidence tooling for TIME-03 natural memory. It does **not** change product
code, maps, statuses, DDL, flags or L1, and it does not claim VERIFIED.

The harness runs the seven owner scenarios against the **saved real snapshot**,
once with baseline product code `0fce97a14` (2.58.219) and once with candidate
`65edc92dc` (2.58.220 preparation), using the same snapshot, chat, effective
GraphRAG config and failing LLM/embedding stubs.

## Files

| file | purpose |
|---|---|
| `time03_scenarios.py` | S1–S7 harness (read-only, privacy-safe output) |
| `mem07_lib.py` | vendored read-only/stub/reference primitives from MEM-07 harness commit `1bdd8d36` |
| `measure_effective_config.py` | read-only GraphRAG config measurement (PostgreSQL `bot_settings` + settings fallback) |
| `make_fixture.py` | synthetic fixture for local smoke only |
| `test_time03_scenarios_smoke.py` | local smoke tests (no production/SSH) |

## Prerequisites (DevOps)

* A read-only snapshot of the real DB, e.g. the saved
  `c1d45bdab4f91ae78744ceb721509a02709a2ac1b2eba9737347b0e4a8e0183d`
  or a fresh `mode=ro` copy. The harness never deletes it.
* Two clean worktrees: baseline `0fce97a14`, candidate `65edc92dc`.
* Production venv and `.env` used by the service (for
  `measure_effective_config.py` and `POSTGRES_DSN`).
* No network needed by the product path: stubs raise and socket egress is
  blocked inside the harness.

## Exact run

```bash
# 0) Production environment (adjust to the actual prod venv/.env paths)
PROD_PY="${PROD_PY:-/var/www/admin_bot/.venv/bin/python}"
set -a; . /var/www/admin_bot/.env; set +a

SNAP="${SNAP:-/tmp/time03-snapshot.db}"          # saved real snapshot
CHAT_ID="${CHAT_ID:--1002661910336}"
BASE="${BASE:-/tmp/adminbot-0fce97a14}"          # worktree at baseline
CAND="${CAND:-/tmp/adminbot-65edc92dc}"          # worktree at candidate
HARNESS="$(pwd)/plans/features/vmq-onto-01/evidence/mem07/time03-scenarios"

# 1) Measure effective GraphRAG config read-only (PostgreSQL bot_settings).
"$PROD_PY" "$HARNESS/measure_effective_config.py" \
  --out /tmp/time03-effective.json

# 2) Baseline on the snapshot.
"$PROD_PY" "$HARNESS/time03_scenarios.py" \
  --variant baseline \
  --db "$SNAP" --chat-id "$CHAT_ID" \
  --code-root "$BASE" \
  --effective-config /tmp/time03-effective.json \
  --out /tmp/time03-baseline

# 3) Candidate on the SAME snapshot/config/chat.
"$PROD_PY" "$HARNESS/time03_scenarios.py" \
  --variant candidate \
  --db "$SNAP" --chat-id "$CHAT_ID" \
  --code-root "$CAND" \
  --effective-config /tmp/time03-effective.json \
  --out /tmp/time03-candidate
```

Exit codes: `0` all assertions pass and no scenario fail; `1` executed but at
least one scenario fail; `2` not executed (missing config/support/snapshot);
`4` technical/code-root failure. Both runs write `time03-scenarios-<variant>.json`,
`.md` and `.sha256`; the compact JSON is the machine-checkable artifact.

The harness fails closed when:

* the code root is not the expected commit or has a dirty product tree;
* the effective config is hand-written/malformed, `settings_only`, or not
  measured from the hot config (`hot_config_measured=false`);
* `graph_rag_enabled=false` or `graph_rag_facts_limit<=0`;
* the snapshot is missing/not read-only or `quick_check != ok`;
* the snapshot sha256 changes during the run.

## Scenarios and metrics

S1 yearless long-standing person; S2 old story by partial cue; S3 multi-year
relationship/circumstance change; S4 current state with stale history; S5
explicit period with several events; S6 similar episodes (correct one); S7
missing evidence.

References are derived deterministically from the snapshot (participant
support, multi-year topic support, changed-position pair, conflict periods,
explicit year, synthetic missing token). No handwritten fact ids are used.

Each scenario records explicitly denominated:

* `required_fact_recall` — archive-derived required anchors hit / anchors;
* `relevance` — delivered rows matching the scenario predicate / judged rows;
* `episode_completeness` — correct first span, ≥2 sources, ≥2 participants,
  ordered timestamps;
* `temporal_correctness` — expected years hit / expected years;
* `participant_attribution` — subject/participant matches / attributed rows;
* `source_proof` — resolved payload refs / all refs, unresolved and weak;
* `latency_cost` — elapsed ms, `retrieve_calls`, payload/rag/episode chars,
  stub embed/generate calls.

No year-share is a success metric. A single episode does not pass a scenario
by itself. S7 is `informational` where Writer honesty cannot be measured
without a generated answer; it still requires zero unresolved refs.

## Local smoke (no production)

```bash
py -m pytest plans/features/vmq-onto-01/evidence/mem07/time03-scenarios/test_time03_scenarios_smoke.py -q
```

The smoke fixture proves: read-only hash stable, quick_check/user_version,
config gate, socket/LLM stubs, S1–S7 rows, explicit denominators, no
message/fact text or display names, no year-share metric. It is **not**
acceptance evidence for TIME-03.

## Limitations

* Read-only snapshot, not the live process; no generated Writer prose.
* Vector leg is `compat_not_proven` when the embedding stub fails; lexical
  path is measured, not semantic retrieval.
* One chat, one run per variant; no statistical generalization.
* S1–S7 support depends on the saved archive; absent support is reported as
  `not_executed` with a reason, not fabricated.
* Baseline/candidate comparison is reviewer work; this harness only records
  the same metrics for both.
