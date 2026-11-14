# VMQ M1/NEXT2 independent deployed review

Verdict: Approved for M-01..M-03 and VMQ-NEXT-02/05 as VERIFIED on c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5 (2.58.203).

## Candidate and scope
- M1 candidate cfec9a1a5ef5f78599529e9ee9394d28355b34eb; NEXT2 candidate 96c8bc7279c5a83afedeb9f38724006e83eaceab; both ancestors of deployed SHA.
- Audited services/mca_episodes.py, services/mca_episode_jobs.py, services/mca_retrieval_context.py, callers and neighbor tests. SMART deltas are terminal fencing and preview-cap relocation only; M1/NEXT2 mechanisms are unchanged.

## Three pillars
- Implementation: traced run() checkpoint-after-success, paused-on-error, keyset watermark, finish fencing_token; traced period FTS filtering, post-LIMIT year/vector leg and UI snippet cap.
- Test validity: read assertions in test_vmq_m1_episode_contract.py and test_memory_period_vector_leg.py. They use real temp SQLite/SQLite-vector fixtures and assert state/results, negative boundaries, dedup, watermark, token filtering, year window, pool miss and None+reason timings.
- Independent challenge: cursor mutation to 0 made watermark test red (assert 0 == 2); reason_code mutation made probe red (row reason_code None); NEXT2 threshold >=4 to >=1 yielded 26 passed/4 failed, including short-token leakage, exact filter, period query and all-short skip.

## Checks
- Exact c97c06e4: M1 contract 34 passed; period-vector 30 passed; NEXT2 battery 447 passed.
- Reused after audit: story 161 passed, memory 295 passed, caps 20 passed; control 5 failed/3 passed is known pre-existing fb_retries(sent=...) mismatch.
- Independent probe: ALL PROBES PASSED; full fragment 933, UI 400; normal completion; stale takeover writes suppressed; paused watermark retained last successful cursor.

## Ledger
| M-01 | VERIFIED | 34 tests + implementation/probe |
| M-02 | VERIFIED | multi-year/gap/counterexample assertions |
| M-03 | VERIFIED | rebuild/idempotency/watermark + mutation red |
| NEXT-02 | VERIFIED | 30 tests + threshold mutation red |
| NEXT-05 | VERIFIED | measured timings and None+reason assertions |

## Limitations and housekeeping
- No production access; effective flags and live archive were not re-read. Full repository suite not rerun.
- Retained Builder probe: C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\vmq-onto-01-3689dd92710d\probe-bc9c1876f7\probe_deployed_interaction.py and probe-output.txt.
- Reviewer disposable mutation run: C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\vmq-onto-01-3689dd92710d\probe-74507b48ca; no production process created.
