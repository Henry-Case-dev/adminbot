# L1 semantics + harness fix — implementation evidence

- LANE_ID: **L1-SEMANTICS-FIX**
- Worktree: `C:\Code\Python\adminbot-wt-speech-p0`, branch `task/speech-p0-hotfix`.
- Candidate commit: **`47fba46561e2e7abb279c2b06915955943715202`** (`47fba465`).
- Start HEAD was `b49f309f`; sibling evidence lanes committed `7443b6cc` /
  `dd10de9d` / `5c2d134b` in the same worktree while this lane ran. This
  commit stages ONLY its own paths; `services/database.py` is a concurrent
  sibling-lane edit (lore provenance) and is NOT part of this candidate.
- Source: `source-owner-p0-corrective-2026-10-25.md` §1.1/§1.2; audit
  `evidence/p0-hotfix/l1-harness-audit.md` §3/§5/§7/§8. No prod, no
  Telegram, no LLM calls.

## 1. Canon (services/chat_prompts.py)

| Byte set | SHA256[:16] | chars | role |
|---|---|---|---|
| `PREV_DIRECT_L1_PLANNER_P0CS` | `8ef75b632d12c944` | 8574 | previous ACTIVE bytes (old rule 7), rollback target |
| `DIRECT_L1_PLANNER_SYSTEM_PROMPT` | `f6f5d3b1fc1db38d` | 9145 | new active canon |
| `PREV_DIRECT_L1_PLANNER_R3B` | `6c2ddc17c998c01a` | 8261 | frozen, unchanged |

- Old rule 7 (object-based: "просьба оценить человека… extent=normal/compact,
  structure=answer") is retained ONLY inside `_DIRECT_L1_PLANNER_RULES_P0CS`.
- New rules (audit §5 wording):
  - 7 — criterion is "what the person asks to do with the material":
    already-said/history/correspondence/own words/repeated traits →
    `response_act=research`, internal analysis may be deep; only opinion/
    evaluation/short conclusion → `structure=answer`, no chronicle/bio/report.
  - 8 — depth does not set length: usual request `compact|normal`, explicit
    detailed request `detailed`, full report `detailed|longform` with
    `structure=report`; if material is beyond the visible window, request the
    existing history/memory capability from the list, otherwise rely on the
    visible and do not pass a guess as confirmed.
  - 9 — exactly one JSON line.
- Rules 1-6 are byte-identical to `_DIRECT_L1_PLANNER_RULES_R3B` (joined via
  `.replace`; asserted in tests). No literal request phrase ("проанализируй мои
  сообщения", "злобный", "в чате") appears in the canon.

## 2. Mode (services/direct_l1.py)

`plan_response_mode`: `response_act=research` on `L1Plan` → `serious`
(previously `casual`). Not mapped to `deep_research` on purpose: the PG-custom
`verbilizer_mode_deep_research` may still carry the old "output the report in
full" block; exact analysis/Writer texts are delivered by the plan block and
are counted once.

## 3. Ladder (services/prompt_migrations.py)

- Forward: `(PREV_DIRECT_L1_PLANNER_P0CS, ACTIVE)` added; historical steps kept.
- Rollback: `ACTIVE → P0CS → R3B → R3 → CLAR` (4 calls for full return).
- PG canon is updated by the standard `migrate_prompt_canons` on restart; the
  owner's non-canonical custom is not touched (exact byte match only).
- Registry: label `l1-planner-material-routing`; factory fingerprint bumped
  `a8ae82425a33 → 9de29133885a` (comment block documents the change).

## 4. Harness (`probes_full/harness_probe_full.py`)

- sha256 `a370c9867e8c19085e66bf688ec9b077e833c5a57154642f98d798c7eda1defe`,
  31249 bytes. Runs from `--root` (no staging copy), records git HEAD/branch/
  dirty and sha256 of 8 imported service modules.
- One real L1 plan feeds mode + `ResponsePlan` + extent block + plan block +
  `_compose_speech_system`; `scrub_for_plan` applied like the service.
- `--force-plan research [--force-extent compact|normal|auto|detailed]
  [--force-structure answer|report]` is a separate scenario, `forced=true`.
- Counters use `psb.ANALYSIS_DIRECTIVE_TEXT` / `psb.ANALYSIS_WRITER_TEXT` in
  system/user/total; ASCII-name counters removed. Invariant violation →
  `invalid="counter_invariant"`.
- RAG is the real chain: `_rag_rows_with_ranks` → `provenance.
  is_self_referential_origin` filter → `dedup_rag_vs_global` →
  `_mark_rag_fact` → `order_rag_facts_asc` → `build_rag_context(origin_labels=
  True)` → `<RAG_Memory>` + cap; render error → `invalid="rag_render"`, no
  fallback lines. Invented `<Chat_Summary>` injection removed (summary is
  recorded as not injected; in the direct path it lives in global head/tail).
- User part follows service order: plan block → lessons (composer OFF) → RAG →
  `<Global_Context>` → `<Target_User>` → `<Current_Question>`; `user_parts` is
  passed to the composer when ON. L1 parse/compose failure → `invalid`, never
  a deterministic fallback plan.
- `--self-check` (offline, exit 0): counts 1×1, ASCII marker 0, synthetic
  payload 1×1, research predicate True, answer predicate False, research mode
  `serious`, modules under root.

```
py -3 probes_full/harness_probe_full.py --self-check
=> {"self_check": "PASS", ... "payload_1x1": true} exit 0
```

## 5. Tests

- New `tests/test_speech_p0_corrective_l1_route.py` (7 tests, CONTRACT/
  REGRESSION, lifecycle marker inside): canon branches, no literal phrases,
  analysis texts don't impose length, P0CS snapshot/rollback/R3b intact,
  research compact payload 1×1, answer compact 0×0, research auto single
  source, research mode serious (report stays deep_research).
- Updated pins: `test_speech_p0_core_serious.py`, `test_direct_l1_corrective_
  r1.py`, `test_direct_l1_l1d_contract.py`, `test_asap2_clar_contract.py`,
  `test_asap_speech_r3b_canon.py`, `test_prompt_migrations.py`,
  `test_p0_prompts_core.py`, `test_expression_isolation_followup.py`.
- `py_compile` clean. Focused run:
  `pytest tests -k "direct_l1 or speech_p0 or asap_speech or prompt_migrations
  or prompt_registry or p0_prompts or asap2_clar or asap_w1_semantics" -q`
  → **261 passed, 0 failed**.

## 6. Live/server status (honest limits)

- No LLM was called and no PG/SQLite payload was built in this lane: the next
  real proof is the server run of this harness on the new tree
  (`--case A/B`, then `--force-plan research`), with RAG/Memory/Core/
  Expression present. That step belongs to DevOps/live probe, not here.
- Harness sha256 must match on the server before trusting a run.

## 7. Requirements-map gap (PM action)

`plans/features/asap-speech-arch/requirements-map-p0-corrective.json`
(worktree `adminbot-wt-book`, commit `b11f2d9b`) contains `L1-ROUTING-REPAIR`
only. Source §1.2 (verified harness / honest counters / real RAG payload) has
NO `HARNESS` slice row. The work is implemented here per the delegated brief,
but PM must add the missing HARNESS requirement(s) and bind evidence; the map
must not stay narrower than the user source.
