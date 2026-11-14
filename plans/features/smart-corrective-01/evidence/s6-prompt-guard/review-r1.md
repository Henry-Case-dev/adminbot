# S6 prompt guard independent review R1

## Candidate

- Epic/slice: `SMART-CORRECTIVE-01 / S6 extension (EVOL-016 prompt guard)`
- Branch: `sc/corrective-s6-guard`
- Base: `release/smart-corrective-01` @ `409f4e8a` (deployed 2.58.201)
- Code candidate: `a8b6197f` (`a8b6197fc49142097a3ea14e76d10a0bcec5a1eb`)
- Evidence: `ea1f5a8b`; retained HEAD/evidence binding: `703b2877`
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-3aa92750`
- Review is read-only except this artifact. Application code, map and backlog were not changed.

## Implementation / contract audit

Inspected the exact diff in `services/prompt_release_policy.py`, `docs/prompt-versioning-contract.md`, the four new guard tests and the three updated tests. The guard is placed after the explicit pinned/baseline branch in `_apply_scope_release`, so `baseline_assign` retains priority.

The guard calls `read_live_manual_revision(block_id, scope, chat_id)` using the stored journal state, not caller-provided revision data. Both `MemoryPromptJournal` and `PgPromptJournal` implementations filter `origin='manual'` and `retired=false`; the PG query returns identity/hash metadata without reading the body. The call is made under the existing release transaction/lock path.

For chat scope and activate/legacy-cutover plans with a live manual revision, the implementation:

- inserts the factory revision into history;
- does not call `_write_active_value`, `remove_chat_override` or `notify_chat`;
- preserves the manual active revision, override and bytes;
- records `deploy_activate / skipped_same / factory_superseded_manual`;
- advances `factory_revision_applied`, allowing the next same-label restart to be a true no-op.

The explicit baseline branch remains before this guard and still emits `factory_superseded_pinned`. A chat override without a live manual revision follows the old `factory_activate` behavior and is removed with its bytes retained in history. A post-2.58.201 state with a manual revision but no override produces no chat release result and does not invent a factory override.

No DDL, feature flag, settings change, factory text change or factory-label change was found. The contract documentation §3.2 was updated with the manual-revision case. The separate data-only reactivation of `rev:d31300ef35a0` is not part of this candidate and remains a DevOps action after the 2.58.202 deploy.

## Test validity

Read the four new tests in `tests/test_smart_corrective_prompt_delivery.py`:

- `test_manual_chat_edition_survives_factory_cutover` asserts byte-exact manual body/hash/origin, retained factory revision, exact event/detail, unchanged override, no notification, global activation and true restart no-op.
- `test_guard_is_isolated_to_the_chat_with_manual_edition` asserts the protected chat is skipped while another chat with an override but no saved revision follows `factory_activate` and retains the removed bytes in history.
- `test_explicit_baseline_assign_still_wins_over_manual_guard` asserts pinned action/detail, preserved override and applied factory revision.
- `test_preserved_manual_edition_without_override_is_not_replaced` asserts the post-2.58.201 state is absent from chat release results, has no invented override and keeps the manual revision live.

The three updated tests were read as well. They retain real store/activation assertions for global/two-chat isolation, unpinned-without-saved-edition behavior and chat baseline isolation. No vacuous assertions, empty bodies or weakened unconditional checks were found.

## Executed suites

- Focused guard/S6 suite: `320 passed, 2 skipped`.
- Checkup/prompt compatibility suite: `331 passed`.
- Regression/adjacent suite: `264 passed, 1 failed`; the failure is pre-existing `test_prompt_field_audit.py::test_every_editable_prompt_has_reachable_surface`.
- Baseline/activation suite: `274 passed, 2 skipped, 1 failed`; the same pre-existing prompt-field-audit failure.
- The implementation evidence also reports `py_compile` exit 0 and clean `git diff --check`.
- The live PostgreSQL test was skipped because no DSN was available; this is not claimed as runtime PG verification.

## Independent falsification

A disposable Git archive was made under the allocated probe run and the guard was disabled by removing only the `read_live_manual_revision` lookup block. The targeted regression set produced:

```text
3 failed, 2 passed
```

The three failures were exactly:

- `test_manual_chat_edition_survives_factory_cutover`;
- `test_guard_is_isolated_to_the_chat_with_manual_edition`;
- `test_scope_global_and_two_chats`.

The two tests that stayed green were the independent baseline-priority and post-2.58.201-without-override cases, as expected from their separate semantics. This confirms the RED signal is specific to the guard behavior rather than a blanket suite failure.

The owner's reported production state (`rev:d31300ef35a0` manual, override absent after 2.58.201) was checked against the candidate investigation/evidence and the dedicated `test_preserved_manual_edition_without_override_is_not_replaced`: the chat is not included in release results and no override is invented. This is fixture/evidence verification only; no production database access was performed. Actual production effective state and a postdeploy checkup with `prompt_source=chat` remain unverified.

## Acceptance ledger

- S6 guard requirements mapped to owner corrective §8.1, AC-15 and AC-19: **REVIEW** for this exact candidate.
- Baseline precedence, manual bytes/override preservation, factory history insertion, diagnostic event, chat isolation and no-invention post-2.58.201 behavior: **REVIEW**.
- Production effective-state/postdeploy checkup with `prompt_source=chat`: **UNVERIFIED**; required after deployment.
- `VERIFIED`: none.
- `FAILED`: none.

## Findings

### IN_SCOPE blockers

None found.

### Nonblocking / separate owner

- The data-only reactivation of `rev:d31300ef35a0` is a separate DevOps action after deployment of 2.58.202; it is not a code-review blocker for this guard.
- The pre-existing prompt-field-audit failure is unrelated to this candidate and remains outside the current slice.

## Three-pillar summary

- **Implementation:** exact guard path, journal readers, pinned precedence, activation/history behavior and no-write/no-notify path inspected against §8.1/AC-15/AC-19 and docs §3.2.
- **Test validity:** all four new and three updated test bodies/assertions read; they verify real store state, bytes, history, activation diagnostics, isolation and restart behavior.
- **Independent challenge:** disabling only the guard in a disposable archive caused exactly the three guard tests to fail; baseline and no-override tests remained green.

## Verdict

**Approved** for predeploy review of exact candidate `a8b6197f`. This approval does not mark requirements `VERIFIED`, does not claim production access or production effective state, and does not include the separate DevOps data-only reactivation. A postdeploy checkup in the affected chat must verify `prompt_source=chat` and the effective saved edition before final release acceptance.

## Housekeeping

Probe run: `C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a\probe-368098b139`.

The candidate worktree is retained untouched. Disposable probe content is retained only as required by housekeeping because it contains protected/unknown managed content.
