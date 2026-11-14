# SMART-CORRECTIVE-01 s1/s2 review r1

Verdict: NEEDS FIXES.

Candidate: f07da3314685a8637394761db32a9044a5d48093; HEAD: 0b7735a1; base: 13884daa32e5cf2a1c05c5c43188ca299817f9x8.

Implementation audit: read services/source_reader.py main path run -> _run -> _content_search -> _content_search_payload, fallback and consumers. The contract fields are present; local-to-remote is bounded.

Test validity: read 25 new tests plus the existing provenance test. 157 focused tests passed. Assertions are meaningful for core outcomes, cursors, SHA, call counts and permission no-bypass.

Third pillar: counterexample with 4 files before target succeeded, finding fourth file and files_scanned=7. Multi-line traceback probe returned ok but matched generic token x.py as caller, not a contiguous tracebback fragment.

Acceptance ledger: SMC-SEARCH-CAP-05 FAILED/UNVERIFIED. Other SCR/SPC classes were synthetically passed. Production effective config not tested. UI not applicable.

Blocker: _content_search tokenizes traceback queries and matches per line. As a result, a fragment spread across tracebback lines can return ok from a generic token, misclassified as caller. User impact: diagnostics can return irrelevant source.

Minimum correction: add contiguous multi-line tracebback matching, return partial when not proven, and add a regression fixture. Owner: Builder. Recheck: focused pytest and the same adversarial case.

Nonblocking: tool_router cursor forwarding and reuse payload are S3/S4 scope. Two pre-existing coordinator failures remain backlog only.

Checks: focused pytest 157 passed, source and consumer audit, independent fourth-file and multi-line probes. Disposable run: C:\Users\main\.git\opencode\WorkspaceData\runs\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-90a1abda\probe-021d177d54.

Follow-up for Orchestrator: route to Builder, fix traceback matching, run the focused test and the same independent challenge.
## Re-review r2 (SC-SEARCH-CAP-05 fix)

**Verdict: Approved** for implemented S1/S2 scope. Fix 91516d55, branch HEAD 057b65c9. Focused suites: 162 passed in 6.31s; consumer suites: 310 passed, 1 warning in 11.81s. Generic x.py-only adversarial query returned status=partial, outcome=partial, verified=false, empty path/match_count, reason=traceback_fragment_not_confirmed, with no caller/ok claim. Positive contiguous block returned ok with path services/payments_worker.py, line_range=[2,4], matched_line_count=3, traceback.fragment_verified=true. Reordered, changed-line and single-code-line cases did not confirm. CRLF/trailing whitespace confirmed; content change did not. Mutation replacing contiguous matcher with unconditional success was killed: negative test observed mutated status=ok, verified=true, non-empty path and match_count=1. S3 tool_router cursor/chat_id/budget_enforced forwarding remains explicitly out of S1/S2 scope; no regression observed. Implementation and tests inspected; no remaining S1/S2 blocker. Production/live requirements are not claimed VERIFIED. UI checks not applicable. Disposable run probe-884bc1c0e4 was allocated for this review and must be closed with run-close.
