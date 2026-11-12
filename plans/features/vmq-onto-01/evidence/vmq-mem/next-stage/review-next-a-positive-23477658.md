# NEXT-03/04 positive evidence — независимое ревью (2026-11-13)

**Reviewer:** independent Reviewer session `ses_e2e402b89ffeMtlTa841KOgwA0`.
**Candidate:** production `23477658` (2.58.198), evidence commits `02a148f4`, `0cc70c9e`.
**Recording note:** this artifact is updated with the independent rerun below. No map or progress-scope status was changed.

## Verdict

**Needs Fixes** for full NEXT-03/04 closure.

- **NEXT-03:** confirmed on the controlled question only, not on the original 17. Independent runtime rerun on candidate `234776589c934024ed0e8dceba189fb9d70d3215` returned only `fact:2242` (2023; `stems_shared=2`) under both `historical` and `auto`; each had `period_kept=1`, `period_kept_despite_empty=1`, `expect=true`. The rerun used a valid empty verdict `{"selected":[]}`, read-only source DB SHA-256 `5310e91e282813f6342c950eb3ee182dc93e9ad6fdf54fdd91d3287e394082b2`, and a fresh derived copy. This proves the controlled case, not the 17-question set.
- **NEXT-04:** remains **PENDING**; the archive C2 has no positive lexical row (10 lexical candidates all shared=1, FTS top-64 old rows all shared=1). The synthetic fixture confirms the mechanism but is not archive evidence; the gap is not closed.
- **`strict` under auto:** matches `next-stage-design.md` §4; no code change is justified. The §2 wording and the settled reading need alignment; this is a wording issue, not a proven product defect.

## Three pillars

- **Implementation:** inspected `positive_probe.py` and its real path `_build_rag_block → _rag_unified_rows → _rag_retrieve → retrieve`; the harness does not inject rows or replace `_rag_unified_rows`. Runtime output records row 2242/year 2023/stems 2 and the single rendered block row for both policies.
- **Test validity:** the probe expectation checks IDs, year, shared stems, block row count and period counters; independently parsed output confirms both `expect.pass=true`, and the CLI reports `EXPECT pass=2 fail=0`, exit 0. The harness pins production-measured hot settings because SQLite lacks PostgreSQL chat settings; this is not a production effective-state check.
- **Independent challenge:** ran the controlled query with valid empty rerank verdict for both policies on a fresh derived copy. First run observed the expected rows but exited 1 because Windows refused deletion of the open derived DB; it is not counted as a pass. Repeated unchanged with `--keep-deriv`: exit 0, two expectations passed. The derived DB is retained in the managed run pending cleanup, not in the repository.

## Next step

NEXT-04 stays PENDING: the archive C2 still has no real positive lexical row; the synthetic fixture is not archive proof. Do not treat the controlled NEXT-03 case as coverage of the original 17 questions. Align `strict` wording in §2 with the settled reading and design §4; no implementation change is justified by this evidence.

## Independent rerun record

- Command: `py -3 -u positive_probe.py --code-root <candidate-23477658> --db <read-only-prod-copy.db> --env-file <project>/.env --work-dir <managed-run>/work-retry --out <managed-run>/out-retry.json --expect-sha 5310e91e282813f6342c950eb3ee182dc93e9ad6fdf54fdd91d3287e394082b2 --block-timeout 120 --batch-timeout 300 --mode empty --seam llm --keep-deriv`.
- Result: exit 0; `historical` and `auto` each returned one block row `[03.2023 | fact:2242]`, `stems_shared=2`, `period_kept=1`, `period_kept_despite_empty=1`; `EXPECT pass=2 fail=0`.
- Entrypoint SHA-256: `f2c9d72dc957527a1400c9d4690f3bf364fbc6b22accbb3ad3f9a04643a9e62c`; query SHA-256: `a975fec2d18ad7ff0c8881b98f9348243759e58c73d6bc357ba638ee6c93e3af`.
- Output SHA-256: `63f48e82610f9b742dd0c1f02a1f297f7dbcc6a4eb7538e9f0ebd47be39dbab8`. Candidate SHA: `234776589c934024ed0e8dceba189fb9d70d3215`.