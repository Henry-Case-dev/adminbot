# Worktree final cleanup — 2026-10-28 (WORKTREE-FINAL lane, DevOps, local only)

Executed: 2026-10-28 23:53:14 +1200 (system local time). Scope: all non-main registered Git worktrees of adminbot + sibling `adminbot-wt-*` directories. No SSH, no production, no network. No `git worktree remove --force`, no `reset --hard`, no branch deletions, no commits to master, no history rewrite.

## Result

| Metric | Value |
|---|---|
| Registered non-main worktrees at start | 55 |
| Removed via `git worktree remove` (no force) | 54 |
| Retained | 0 |
| Directories verified gone | 54/55 |
| `git worktree list` after prune | 1 entry (main only) |
| Sibling dirs beside adminbot | 26 → 1 (`Temp`, 5,030 bytes — other lane's scope) |
| Bytes freed (C:\Code\Python) | 19,156,566,067 (~17.8 GiB): 25,199,230,782 after the earlier 28.10 pass (22:53 +12:00) → 6,042,664,715 after this pass |
| Preserve branches created | 40 (37 with preserve commits, 3 cheap refs) |
| Files quarantined | 15 (10 rule-5/6 data + 5 gitignored deploy tooling) |
| Verified duplicate copies deleted | 8 |
| Junk deleted (explicit paths) | 1 (`r3/run.log`) |

File-level verdict tally (all 55 dirty worktrees, per-file, git-content-based): {"DELETION": 241, "EQ_MASTER": 103, "READ_ERR": 4457, "TRULY_UNIQUE": 438}

## Method

1. Fresh `git worktree list --porcelain`; per-wt `status --porcelain=v1 -z` (correct non-ASCII path handling).

2. Per modified tracked file: blob sha of working copy vs `master:<path>` and vs `<head>:<path>`; EOL-insensitive comparison for text files; deletions (` D`) detected separately.

3. Reachability baseline: `git rev-list --objects --all` (31,058 objects incl. the two preserve refs created before the scan). A blob present in the set = content already committed in some branch → safe discard. Not present = truly unique → preserve.

4. Rule 2 (PNG/evidence JSON regenerations): applied only when `master:<path>` resolves (slot filled by master's own committed version) — verified via `rev-parse` for every discarded regen.

5. Preserve: one commit on `preserve/<name>` at the wt HEAD with only the preserved paths; local identity override; secret scan of the staged set before every commit.

6. Quarantine with `manifest.json` (path, sha256, bytes, reason) + hash verification after copy; duplicate copies deleted only after blob-sha equality with the committed reference.

7. Restore of discarded tracked changes (`checkout -- .`), status must be empty, then `git worktree remove`, then `git worktree prune`.


## Two unique detached commits (mission rule 7)

| Commit | Where | Content | Verdict | Preserved as |
|---|---|---|---|---|
| `a94f1b59` | adminbot-wt-nost1-rev | adds `plans/features/p0-nostalgia-rework/evidence/review-w1.md` (86 lines): independent review approval NOST-01..04/07; file absent from master tip | review evidence document, no code; functionality itself was reviewed/released in later rounds → integration not applicable | ref `preserve/nost1-rev-a94f1b59` → commit kept reachable before wt removal |
| `f57cb18c` | adminbot-wt-rel-final-rev | adds `plans/features/asap-speech-arch/evidence/p0-hotfix/review-release-final-p0.md` (71 lines): bounded integration review, Approved for release 2.58.139 (508 passed/0 failed); file absent from master tip | review evidence document, no code; release 2.58.139 itself shipped earlier → integration not applicable | ref `preserve/rel-final-rev-f57cb18c` → commit kept reachable before wt removal |

## Preserve branches (40)

37 branches carry one preserve commit each (unique uncommitted code/tests/review docs/plans artifacts, secret-scanned). 3 are cheap refs without commit:

| Branch | Files | Note |
|---|---|---|
| `preserve/alias-rev` | 1 |  |
| `preserve/asap5-final-rev` | 1 |  |
| `preserve/asap5-rev` | 1 |  |
| `preserve/asap5v-rev` | 1 |  |
| `preserve/delta-depth-rev` | 1 |  |
| `preserve/delta-review` | 1 |  |
| `preserve/fc-rev` | 1 |  |
| `preserve/fc-rev2` | 1 |  |
| `preserve/fcp-rev` | 1 |  |
| `preserve/nost1-rev-a94f1b59` | 1 | ref to unique commit a94f1b59 (see above) |
| `preserve/nost2-rev` | 1 |  |
| `preserve/osc-cfg02a-red` | 1 |  |
| `preserve/osc-payload-verify-recheck` | 20 |  |
| `preserve/osc-payload-verify-recheck2` | 7 |  |
| `preserve/osc-rel-25895-wt-base` | 1 |  |
| `preserve/osc-rev-embed-5877810d` | 4 |  |
| `preserve/osc-rev-embed-d3ba845b` | 1 |  |
| `preserve/osc-rev-rel-25887` | 31 | branch at wt HEAD 54a69f32, no commit: deploy tooling was gitignored → quarantined instead |
| `preserve/ows-dropdown-wg-fix` | 1 |  |
| `preserve/ows-rev-diag-minifix` | 2 |  |
| `preserve/ows-rev-dl-fix` | 3 |  |
| `preserve/ows-rev-entry-fix` | 4 |  |
| `preserve/ows-rev-postgen-diag` | 5 |  |
| `preserve/ows-rev-tools-minifix` | 4 |  |
| `preserve/ows-rev-tr-fix2` | 1 |  |
| `preserve/ows-speech-impl-wt` | 13 |  |
| `preserve/ows-speech-mobile-wt-clean` | 5 |  |
| `preserve/ows-wt-final5` | 31 |  |
| `preserve/pa5-rev` | 1 |  |
| `preserve/rel-final-rev-f57cb18c` | 1 | ref to unique commit f57cb18c (see above) |
| `preserve/res23` | 6 |  |
| `preserve/simpl2510` | 1 |  |
| `preserve/speech` | 21 |  |
| `preserve/speech-int` | 1 |  |
| `preserve/speech-p0` | 3 |  |
| `preserve/speech-rev` | 1 |  |
| `preserve/tgl-base` | 1 |  |
| `preserve/tgl-rev` | 1 |  |
| `preserve/tmp-alias-red` | 1 |  |
| `preserve/tmp-rev-embed-base` | 1 |  |

Highlights of preserved content: un-integrated review documents for asap5/asap5v/p0-delta/factcheck/nost-w2/tgl/pa5/speech rounds; owner source prompts (`source-owner-prompt-2026-10-25.md`, `source-owner-p0-corrective-2026-10-25.md`, `plans/owner_inputs/2026-10-26-no-meta-scope.md` — committed into a preserve branch only, main `plans/owner_inputs/` untouched); un-merged code diffs (`bot.py`+local bot api service+tests, initiative diagnostics, postgen vision, direct execution/capabilities, `web/app.js`+`index.html`+`app.css` speech-mobile entry, `image_normalize_cand.py`, cfg02a/alias/embed/admin-cache tests); speech evidence bundles (`withheld/`, `probes_final5/`, `requirements-map-speech-simplify.json`); release 2.58.87 deploy tooling + `fix.patch` (quarantine).

## Quarantine

Root: `C:\Users\main\.config\opencode\WorkspaceData\quarantine\` (27,180,745 bytes total). Manifests with sha256+bytes+reason:

- `quarantine\speech\manifest.json` — 9 probe DBs (`OPENCODE_WORKFLOW_SCRATCH/r2/db/r2_*.db`, ~29 MB total; rule 6: never committed, only copies); plus `r3/run.log` deleted as junk (rule 4).

- `quarantine\res23\manifest.json` — `res23_asap2_roundtrip.json` (454,626 bytes probe artifact).

- `quarantine\osc-rev-rel-25887\manifest.json` — 5 release-2.58.87 deploy/patch files (gitignored deploy tooling, no secrets inline — verified before decision) + `embedded-repo-clone\` (1-commit throwaway sandbox clone, preserved not deleted per clone rule).

## Incidents and resolutions

1. Secret scan flagged `TOKEN = "8802473181:TESTTOKENforLOCALbotAPIunit"` (test_vision_dl_fix.py) and `TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"` (test_p0_admin_cache_toggle_save.py). Verified obvious fake test constants; files committed to their preserve branches (`ows-rev-dl-fix` amended, `tgl-base` recreated). No real secret found in any committed set.

2. `image_normalize_cand.py` initially mapped to the wrong wt (`speech-mobile/wt-base`); corrected to OpenCodeScratch `release-25895/wt-base` (`preserve/osc-rel-25895-wt-base`); the empty first branch was deleted.

3. `rev-rel-25887` removal initially refused: phase A partial `git add` had staged `fix.patch`, and phase C restore materialized it on disk (content byte-equal to the quarantined copy — hash-verified — then deleted); embedded clone moved to quarantine. Removed cleanly afterwards.

4. Background size scan file (`sizes_before.json`) failed to persist; per-wt byte table replaced by the verified aggregate above (authoritative before-value from the earlier 28.10 pass measurement at 22:53 +12:00).

5. `f10parent`/`head_check`/`mca19_headcheck` (Temp\opencode) were not 'modified' — they were working trees with ~4,700 tracked files deleted from disk; all deletions restored from Git (content fully recoverable), then removed.

## Residue explicitly out of this lane's scope (not touched)

- Main worktree `C:\Code\Python\adminbot` is dirty (e.g. `plans/archive/INDEX.md`, `plans/features/asap-speech-arch/evidence/inspector/*.png` and more) — pre-existing/another lane's working state; main worktree files are untouchable for this lane.

- `C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH` non-worktree residue: 2,483,878,538 bytes / 16,790 files (probe scripts, logs, per-lane dirs) — unregistered junk inside the main checkout; owned by the other cleanup lane / owner decision.

- `OpenCodeScratch\adminbot-ccef72c25768` and `Temp\opencode` non-worktree junk — other lane's scope.

- Branches preserved untouched: all `task/*`, `release/*`, `review/*`, `speech-init-fix-r3` and every other pre-existing branch.


Evidence (this run, disposable, under WorkspaceData/runs/c742e4de9e92c489/...): inventory.json, classify4.json, unique_files.txt, disposition_state_*.json, phase_cd.json, phase_e.json, objects.txt. No commit of this report was made (per mission).
