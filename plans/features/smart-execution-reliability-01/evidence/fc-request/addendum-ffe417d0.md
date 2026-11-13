# S13-FC-REQUEST — addendum: formatting-only correction (`ffe417d0`)

Independent review verdict `Needs Fixes` had one blocker and it was formatting,
not behavior: `git diff --check d20a7f73 bc2ac583` reported trailing whitespace
for added lines because `services/factcheck_orchestrator.py` (2267 lines) and a
single line in `services/media_readiness.py` carried CRLF endings, and the repo
commits those blobs with CR (no `.gitattributes`, `core.autocrlf=false`), so git
treated every added CR as trailing whitespace. Commit `ffe417d0` converts exactly
the S13-changed code/test files to LF; measured trailing spaces/tabs were zero,
so no line content was rewritten, and no logic, tests, test meaning or evidence
conclusions changed. Proof: `git diff --check d20a7f73 ffe417d0 -- services
handlers tests` is empty (exit 0), `git diff -w bc2ac583 ffe417d0 -- services
handlers tests` is empty (only EOL bytes differ), and on `ffe417d0`
`tests/test_factcheck_subject_contract.py` = 39 passed, context+planner subset
(`test_factcheck_context_cfg06.py` + `test_factcheck_planner_cfg06.py`) = 28
passed, and the 31-file affected factcheck/vision suite = 655 passed (1 known
network flake deselected, see binding §9). Because the orchestrator file is now
LF while its base blob is CRLF, the patch against `d20a7f73` shows a whole-file
line-ending diff; the canonical semantic view for review is `git diff -w
d20a7f73 ffe417d0 -- services handlers tests`. New code candidate for re-review:
**`ffe417d0`**.
