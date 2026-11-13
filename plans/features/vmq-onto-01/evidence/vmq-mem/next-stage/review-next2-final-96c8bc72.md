# Independent review: NEXT-02 final / NEXT-05

Date: 2026-11-13. Code candidate: `96c8bc7279c5a83afedeb9f38724006e83eaceab`.
Docs candidate: `a34929250798f149dbbfe0c7806cd1792d4721d`.
Base: `234776589c934024ed0e8dceba189fb9d70d3215`.

## Final per-row verdict

- NEXT-02 section A quality: `REVIEW`.
- NEXT-05 timings: `REVIEW`.
- Section B pool/priority/counters/pin: `N/A_WITH_REASON`, explicitly dropped.
- vmq-onto-01 epic: remains open with 54 gaps; this review does not mark it DONE.

## Source binding confirmation

The four required candidate-bound source files are present and their bytes match
both the stated SHA256 and the docs-line Git blobs at `fb7e6be7a0c0322fce7aae341453ba75215c8c64`:

- `plans/owner_inputs/2026-11-13-vmq-next02-natural-retrieval-metric.md`: SHA256 `d730045387fe77cddb12d8f185a91206b9f1577d8826c0cb2111ef4b06a0a2f1`.
- `plans/features/vmq-onto-01/architecture-next2-quality.md`: SHA256 `cfef9d0572189c5ff17d9e57a99b1f3f0f45390faed845ff262bdada9f691cb6`.
- `plans/features/vmq-onto-01/architecture-next2-corrected.md`: SHA256 `82998a726fc9826b2f13a712022a8630e33278c85ef3344b08ebbf019593b4c8`.
- `plans/features/vmq-onto-01/architecture-next2-mechanism.md`: SHA256 `e0a63c1162683db7ba01bd592df32da34f19687e21b7900fcc407b61a8ba3c7a`.

`binding-next2-final-96c8bc72.md` §9 lists the same paths and hashes. `HEAD`
is `a34929250798f149dbbfe0c7806cd1792d4721d`; it is docs-only over the
unchanged code candidate. `git diff 96c8bc7279c5a83afedeb9f38724006e83eaceab
-- services tests web handlers config` is empty. No code, test, settings,
production, DDL, or map/progress_scope changes were made by this review.

The current quality contract explicitly supersedes the older 58.1% contract
for NEXT-02, while preserving the historical corrected/mechanism documents for
traceability. Therefore the old threshold text is not an unresolved source gap.

## Three-pillar summary

**Implementation.** Inspected `retrieve` in `services/mca_retrieval_context.py`:
period facts use `_period_fts_keywords` with the same morphology as section 2;
the filtered match is scoped to `period_fill`; messages retain the full match;
an empty match skips only period FTS; vector and main retrieval continue; the
year predicate remains before LIMIT. `_period_add_ms` runs only after actual
SQL/KNN calls and missing calls produce `None` plus a reason. The exact diff
from base contains only `mca_retrieval_context.py` and
`test_memory_period_vector_leg.py`; direct-chat pool/priority behavior remains
base behavior.

**Test validity.** Reused the prior candidate-bound focused evidence: `447
passed` in the delegated set and `275 passed` in the unified/GraphRAG/lookup
subsets. Assertions cover short-token pollution, meaningful-token retention,
empty-match isolation, FTS failure isolation, non-period preservation, timing
reasons, and year-before-LIMIT. The paired harness uses one corpus, 60 fixed
queries in 20/20/20 strata, and frozen embeddings with `hits=235`. Gold-v2 was
formed after the first output, so it is used for paired non-degradation rather
than absolute-quality claims.

**Independent challenge.** Prior runtime-only mutation of
`_period_fts_keywords` to return all tokens was caught red by the independent
section-2 assertion, then restored. Boundary cases passed: short-token-only
input made no period SQL call, vector stayed alive, the old row survived year
exclusion, and `period_fill=False` retained baseline SQL. No separate archive
query corpus is present, so the broad claim for all unselected archive queries
remains unproven beyond the paired sample.

## Behavioral evidence and residual

Retained evidence: 0 mandatory-fact losses, 115/120 identical rows,
120/120 identical year composition, period lexical pool 1374 to 897, KNN 498
unchanged, and rerank differences within baseline noise. The 2026 share is
strictly diagnostic; no cap, quota, forced displacement, threshold weakening,
or new retrieval/metric mechanism is present. The fallback-provider embedding
run was excluded by the frozen-vector guard. Fallback-provider behavior, NULL
timestamps, missing participant cross-year linkage, and five asap32 failures
remain pre-existing residual/backlog items.

## Review gate

The repository has no `plans/features/vmq-onto-01/requirements-map.json` or
slice graph. The standard `requirements_gate.py` requires such a map for
`--stage review`; consequently no honest scoped gate invocation could be run
for this feature, and no fabricated gate result is reported. Source binding,
exact candidate lineage, implementation audit, test-validity audit, and
independent challenge were performed directly against the candidate.

## Decision

`Approved` for NEXT-02 quality and NEXT-05 at the pre-deployment `REVIEW`
stage for code `96c8bc7279c5a83afedeb9f38724006e83eaceab` plus docs
`a34929250798f149dbbfe0c7806cd1792d4721d`. This is not deployment or final
production acceptance and does not mark the vmq epic DONE. The owner's
finish-if-no-real-mandatory-defects decision applies only to this corrective
stage.
