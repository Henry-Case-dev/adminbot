# Independent review H (S8-SELFDIAG)

**Verdict: Approved for REVIEW** (H3/H4 production checks remain postdeploy/READY_FOR_LIVE).

Candidate: `d238f808`; evidence HEAD: `120517a6`; branch `smart/h-selfdiag`; base lineage 18fa4d59 + merge of S3 (5e87ed48) + merge of G (cffc9fb2), merge commit ce9e9f01, cross-slice fixture 8c5549b7.

Transcription note: this artifact was requested by the Reviewer but its shell writes to master were rejected by the portable shell scanner ("invalid-structure"). The verdict and the observations below were delivered by the Reviewer in-session and transcribed by Orchestrator without changing their content. The Reviewer did not modify code, maps or statuses.

## Three proof pillars

- **Implementation:** inspected `services/checkup_prompts.py`, `services/diagnostic_collector.py`, `services/system_logs_fetcher.py`, `handlers/checkup.py`, plus existing Direct/ledger/identity/manifest consumers. No new error-code tables, whole-repo reader, counters, flags, DDL or production writes found.
- **Test validity:** read the assertions of the 25 CONTRACT tests in `tests/test_smart_exec_selfdiag.py`; they check real states, ledger, git files and journal argv; no vacuous assertions. Ran `25 passed`. A repeated broad targeted run was interrupted by tooling and is not claimed; saved binding runs: 168 + 124 + 181 + 129 passed = 627 passed.
- **Independent challenge:** checked unknown journal, permission fallback, foreign unit, root uid, missing manifest and continuation without `reply_to_bot`. Observed: unknown stays `degraded/not_checked`, fallback keeps the ledger, a foreign unit is not substituted, a missing manifest does not fabricate a SHA, continuation without reply-to-bot is not stored. Mutation evidence: continuation 1 red, unknown->zero 4 red, manifest SHA=0 1 red.

## Acceptance ledger

- `SXR-H1-01`: VERIFIED for REVIEW.
- `SXR-H1-02`: VERIFIED for REVIEW.
- `SXR-H2-01`: VERIFIED for REVIEW.
- `SXR-H3-01`: VERIFIED for REVIEW; production service-user/journal check remains `READY_FOR_LIVE`.
- `SXR-H4-01`: VERIFIED for REVIEW; deployed SHA/version/restart parity remains `READY_FOR_LIVE`.
- `SXR-H5-01`: VERIFIED for REVIEW.

## Scope and residual

- Cross-slice fixture 8c5549b7 was inspected: it disables `resolve_local_source` in a fixture only and does not weaken C2/C3 assertions.
- `git diff --check 18fa4d59..d238f808 -- services handlers tools tests` still reports pre-existing whitespace in older S3/G files: `BACKLOG_ONLY`, not an H defect. H's own changes are LF-clean per the builder's whitespace evidence.
- Real production journal access as the service user, actual `.deploy/release.json` bytes after the next deploy, live Direct continuation without marker words, Telegram `delivered=0` with ledger, and STT `not_checked` remain postdeploy observations. No deployment was performed; parent epic is not DONE.
