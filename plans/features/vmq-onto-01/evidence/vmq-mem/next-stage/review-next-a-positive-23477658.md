# NEXT-03/04 positive evidence — независимое ревью (2026-11-13)

**Reviewer:** independent Reviewer session `ses_e2e402b89ffeMtlTa841KOgwA0`.
**Candidate:** production `23477658` (2.58.198), evidence commits `02a148f4`, `0cc70c9e`.
**Recording note:** the Reviewer confirmed the verdict but could not write the artifact; shell writes were rejected and no write tool was available. The Orchestrator transcribed the verdict; no approval was added.

## Verdict

**Needs Fixes** for full NEXT-03/04 closure.

- **NEXT-03:** confirmed only on the controlled question, not on the original 17. Saved JSON/raw show real row id 2242 (2023, product `stems_shared=2`) from the FTS pool, surviving a valid `{"selected":[]}` as the only row (`period_kept=1`, `period_kept_despite_empty=1`). A new independent runtime rerun was not performed: the artifacts lack the required `positive_probe.py` and query JSON, so the runtime challenge remains `UNVERIFIED`.
- **NEXT-04:** remains **PENDING**; the archive C2 has no positive lexical row (10 lexical candidates all shared=1, FTS top-64 old rows all shared=1). The synthetic fixture confirms the mechanism but is not archive evidence; the gap is not closed.
- **`strict` under auto:** matches `next-stage-design.md` §4; no code change is justified. The §2 wording and the settled reading need alignment; this is a wording issue, not a proven product defect.

## Three pillars

- **Implementation:** real path `_build_rag_block → _rag_unified_rows → retrieve`; row 2242 accepted by the product filter, not injected; empty verdict leaves one row.
- **Test validity:** the saved JSON/raw support the claim; the independent runtime challenge is missing because the runnable entrypoint/query JSON are absent.
- **Independent challenge:** the Reviewer inspected the row id/year/stems and the empty-verdict result; the runtime rerun is pending.

## Next step

Restore a runnable entrypoint and query JSON for the controlled positive case, then perform a bounded independent rerun and record the review in the target worktree. Do not fake archive C2 evidence; NEXT-04 stays PENDING unless a real archive row appears or the clause is explicitly reformulated by the owner/Architect.
