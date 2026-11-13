# Release train 2.58.199 - combined candidate (4 approved slices)

- Base: `234776589c934024ed0e8dceba189fb9d70d3215` (2.58.198, no bump).
- Branch: `release/2.58.199-train`.
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\2-58-199-train-8ec228d101d0-704ae241`.
- **Code/test merge tip: `7c5669e55a9ad62914dd721450b4302d967f4c93`.**
- **Docs merge tip (before this evidence commit): `d62514d9651575cf6ffcbd4d5c026c5c5cdf5d91`.**
- **Combined-review fix (restored M1 initial binding): `a15f8345e3570cc01ab0fd6d2f0f3f833e68e810`; see §9.**
- Status: **REVIEW** (Builder handoff to independent Reviewer; not deployed, not approved).

## 1. Merged slice SHAs

Order: four code/test tips first, then the four docs tips.

| # | Slice | Code/test tip | Merge commit | Docs tip | Merge commit |
|---|---|---|---|---|---|
| 1 | self-diag/corrective | `76fcb82962592a8e099239cd11e6c34ff13cf407` | `94dce30e1220a9b77da88150ac4240132644e374` | `e5a92ebae08dd312ec739a94c12c76e7ddcbef3d` | `21d2fc35256c0ef935c1f06dbae98fe3841c7edb` |
| 2 | self-diag/identity | `ea9e9f2a1dc8b04bb82607acf9939bdefa3c16be` | `367e12f62a76117b530b1e4cf350977100ceaf47` | `6639baa35c276e97544a9f93e3e7da1808209b59` | `7fb8462ddb99e7a25069adff9779bc5ec7258e55` |
| 3 | vmq/m1 | `cfec9a1a5ef5f78599529e9ee9394d28355b34eb` | `0187debfea57acb1e58b30bae2342c77b39409dc` | `d2c95ca296edb061f5698de500f87bd34d5430f4` | `116cf02a3b034003c311c38726cb45bcd96f8020` |
| 4 | vmq/next2-final | `96c8bc7279c5a83afedeb9f38724006e83eaceab` | `7c5669e55a9ad62914dd721450b4302d967f4c93` | `a34929250798f149dbb0fe0c7806cd1792d4721d` | `d62514d9651575cf6ffcbd4d5c026c5c5cdf5d91` |

Every docs tip is a descendant of its code tip (`git merge-base --is-ancestor <code> <docs>` true
for all four); every tip is an ancestor of the train HEAD.

## 2. Conflicts and semantics

- Merge conflicts: **none**. All eight merges completed with the `ort` strategy without
  manual resolution; no conflict hunks existed, therefore no semantic conflict decision was
  taken. No ProbeSpec/block collision occurred (the four slices touch disjoint files).
- No approved behavior was changed, dropped, reordered or re-worded by the merge.
- Content proof: every one of the 75 union paths at train HEAD was compared to the blob
  at each approved tip (`git rev-parse HEAD:<path>` vs `git rev-parse <tip>:<path>`).
  **75 / 75 paths byte-identical to an approved tip; 0 mismatches; 0 files different from
  every approved branch.** No partial merge, no whitespace reflow, no re-encoded file.
  (The 74-path result of the first pass plus the restored M1 binding; see §9.)

## 3. Merged union file set vs `23477658` (75 files; plus this report, §9)

Product / tooling (21):
```
M .gitignore
M README.md
M bot.py
M handlers/checkup.py
M services/bot_output_ledger.py
M services/chat_prompts.py
M services/checkup_prompts.py
M services/checkup_service.py
M services/database.py
M services/deploy_identity.py
M services/direct_capabilities.py
M services/direct_chat_service.py
M services/direct_l1.py
M services/log_ring.py
M services/mca_episode_jobs.py
M services/mca_episodes.py
M services/mca_retrieval_context.py
M services/runtime_probes.py
M services/source_reader.py
M services/tool_router.py
A tools/release_manifest.py
```
Tests (9):
```
M tests/test_checkup_contract.py
M tests/test_deploy_identity.py
M tests/test_diagnostic_probes.py
M tests/test_memory_period_vector_leg.py
A tests/test_release_manifest.py
M tests/test_self_diag_golden.py
A tests/test_selfdiag_corrective_research.py
M tests/test_soul1_composer_parity_off.py
A tests/test_vmq_m1_episode_contract.py
```
(6 modified, 3 added; no test file outside the approved slices.)

Plans/evidence (45): `plans/features/self-diag-01/corrective-2026-11-13/*` (10 files),
`plans/features/self-diag-01/requirements-map.json`, `plans/features/vmq-onto-01/*` (32 files:
3 architecture-next2 docs, 3 `evidence/vmq-m/*` including restored `binding-m1-80726249.md`,
26 `evidence/vmq-mem/next-stage/*`),
`plans/owner_inputs/2026-11-13-selfdiag-corrective-journal-code-identity.md`,
`plans/owner_inputs/2026-11-13-vmq-next02-natural-retrieval-metric.md`.

**Unexpected files outside the union: only this report** (declared in §9). Every other added
file is either an approved test, `tools/release_manifest.py` (approved identity slice deploy
artifact) or approved plans/evidence. No `plans/current_task.md`, `plans/workflow_state.md` or
`plans/progress_scope.json` edit.

## 4. Scope guards (verified)

- **Version:** `config/settings.py` untouched; `APP_VERSION = "2.58.198"`. No bump (DevOps owns it).
- **DDL/migrations:** none. No `.sql`, no migration directory change; the only database-related
  edit is the closed `BOT_OUTPUT_KINDS` extension (`checkup_report`) in `services/database.py`,
  explicitly no DDL. Schema version/user_version not touched.
- **Settings/flags:** `config/settings.py` not changed; no new flag, endpoint or parameter.
  Prompt edits exist only inside the approved corrective slice (`services/chat_prompts.py`
  adds `DIRECT_L1_DIAGNOSTIC_RESEARCH_ADDENDUM`; `services/checkup_prompts.py` adds
  `CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM`); both are additive functional addenda, no canon/personality
  bytes rewritten.
- **No new LLM/agent/store:** no new provider, model, agent, scheduler or storage added.
  `tools/release_manifest.py` is a deploy-time manifest producer, not runtime LLM/agent code.
- **Web app not touched:** no `web/**`, JS, HTML, CSS or Mini App file changed. JS checks were
  therefore not required.
- **Compile:** `python -m py_compile` over all changed `.py` paths - exit 0.

## 5. Tests (project venv, cwd = train worktree)

Interpreter: `C:\Code\Python\adminbot\.venv\Scripts\python.exe` (Python 3.12.0, pytest 9.1.1).

| Slice | Set | Result | Exit |
|---|---|---|---|
| corrective | `tests/test_selfdiag_corrective_research.py` | **28 passed** | 0 |
| corrective | focused: new + checkup service/handlers/contract + tool_router/schemas + source_reader + direct_l1 corrective/l1d + asap7 direct_l1 | **330 passed** | 0 |
| corrective | L1/engine cluster (12 files: direct_chat, ur_turn_engine, p1, rlr, decision, asap8 direct x2, soul1 profile, prompt migrations, p0 checkup core, p0 prompts core, asap fc voice) | **442 passed** | 0 |
| corrective | `test_soul1_composer_parity_off.py::test_p4_l1_planner_system_matches_recorded_dump` | **1 passed** | 0 |
| identity | `tests/test_deploy_identity.py tests/test_release_manifest.py` | **58 passed** | 0 |
| identity | 16 impacted files (identity D4 A/B/C, probes, settings adapter, golden, prompt_readback, checkup contract/handlers/logs/prompts/service, p0 checkup, UR bot output, mca22, release manifest) | **555 passed** | 0 |
| vmq/m1 | `tests/test_vmq_m1_episode_contract.py` | **34 passed** | 0 |
| vmq/m1 | 6-file episode/story set (mca05, evol021, asap8 f7, asap8 v63 b08, mca12, m1) | **161 passed** | 0 |
| vmq/m1 | 4-file memory set (memory_contracts, graphrag_memory, mca17 sleep workers, memory_health) | **295 passed** | 0 |
| vmq/next2 | `tests/test_memory_period_vector_leg.py` | **30 passed** | 0 |
| vmq/next2 | focused 447 set (period_vector_leg + mem_time_policy + unified_retrieval/mca07 + memory_core + asap8 v63 b03 + graphrag + memory_lookup) | **447 passed** | 0 |
| extra impact | `tests/test_vmq_mem_retrieval_fixes.py tests/test_memory_communities_retrieval.py` | **23 passed** | 0 |

Exact commands match the ones recorded in the approved slice bindings
(`binding-core-76fcb829...`, `binding-identity-ea9e9f2a...`, `engineering.md` M1,
`binding-next2-final-96c8bc72.md`); the 555 set is the 15 named impacted files plus
`test_release_manifest.py` (16 files), which reproduces the recorded 555 exactly.

## 6. Web-wide baseline

`pytest tests/test_web*.py` (68 files) was run on the train **and** on a detached base
worktree at `23477658` with the same interpreter:

- train: **11 failed, 1541 passed** (167.4 s)
- base: **11 failed, 1541 passed** (170.6 s)
- failure identities are identical (same 11 node ids), therefore **no new web failure**:
  `test_webapp_asap_cover_ui_v21::TestHistoryAndCoverTimer::test_history_shows_activation_date`,
  `test_webapp_asap_ui02_delta::test_no_magic_z_index_outside_decorative_in_card`,
  `test_webapp_avatars_ui::TestAvatarFrontAudit::test_close_and_fullscreen_buttons`,
  `test_webapp_dm_ui::TestDmSummaryGateMarkers::test_s3_scheduler_skips_dm_positive_ids_behavioral`,
  `test_webapp_round1020_ui::TestNavigationSnapshot::test_tabs_ids_and_order_unchanged`,
  `test_webapp_round1020_ui::TestNavigationSnapshot::test_navbar_legacy_and_v2`,
  `test_webapp_round1020_ui::TestHumanReadableLabels::test_examples_from_tz`,
  `test_webapp_round1024_nodeflow::TestNodeFlowNaming::test_no_english_jargon`,
  `test_webapp_round108_ui::TestCacheBustAndEsc108::test_app_version_matches_readme`,
  `test_webapp_ui_rework_round1020::TestNavigationSnapshot::test_tabs_ids_and_order_unchanged`,
  `test_webapp_ui_rework_round1020::TestNavigationSnapshot::test_navbar_and_modules_unchanged`.

Web tests rewrite tracked PNG/JSON evidence under `plans/features/evol/audit/evidence/`; those
48 incidental modifications were reverted (`git restore`) and the train worktree is clean.

## 7. Effective configuration

- No new acceptance-critical flag was introduced by the train; `MCA_BOT_OUTPUT_LEDGER_ENABLED`
  keeps its factory ON default used by the identity tests (OFF branch covered by
  `test_telegram_delivery_ledger_disabled_is_not_configured`).
- Diagnostic research/tool addenda activate only when the runtime actually exposes diagnostic
  tools; the ordinary direct path keeps the previous prompt bytes.
- VMQ episode/retrieval changes stay behind the existing `mca_*` gates/contracts; no new gate.
- `ADMINBOT_DEPLOYED_SHA` absent in tests; it never upgrades identity above manifest evidence.

## 8. Honest limits

- This is a locally merged and locally tested candidate, not a deployment and not an approval.
  Reviewer must inspect the combined diff; DevOps performs the version bump (2.58.199) and deploy.
- No production runtime proof in this handoff: release manifest `.deploy/release.json`,
  `deployed_sha`, real journald access and Telegram behavior are post-deploy checks.
- Web baseline has 11 pre-existing failures (identical on base and train); they are not caused by
  this train and remain outside it.
- Some aiosqlite "leaked connection" warnings appear on stderr in older test files; pytest exit
  codes were 0 for every set above (confirmed with `$LASTEXITCODE` on the 555 set).
- Byte-preservation proves the merge did not modify approved content; it does not replace
  independent behavioral review of the combined candidate.
- Docs tip written below this file's own commit: the branch tip after committing this evidence is
  reported in the handoff message; the code/test merge tip is `7c5669e5`. The only non-union
  artifact is this report itself (§9).

## 9. Combined-review fix — restored M1 initial binding (2026-11-13)

The combined-review defect: `plans/features/vmq-onto-01/evidence/vmq-m/binding-m1-80726249.md`
existed at code tip `cfec9a1a` and at the initial M1 docs commit `955e282a`, but the M1 fix docs
commit `d2c95ca2` renamed it to `binding-m1-cfec9a1a.md` and the train therefore lost the
original artifact. The file was restored with exact bytes:

- `git checkout 955e282a -- plans/features/vmq-onto-01/evidence/vmq-m/binding-m1-80726249.md`
- restore commit `a15f8345e3570cc01ab0fd6d2f0f3f833e68e810`;
- blob `fb03162a8fcc8f1d6cb1c4a00054515960378217`, 9170 bytes,
  sha256 `4b3c83edf185f8c03bd61f6eae817ee8588cae9d756b0c57d4a43391910266f4`;
- identical to `955e282a:<path>`, to `7c5669e5:<path>` (the file was present at the code merge
  tip) and to the master restored copy (`56ffb880`).

Union re-verification (`HEAD` after restore), every path of each tip's `base..tip` diff compared
blob-to-blob with the train:

| Tip | Paths in diff | Matched in train | Mismatched |
|---|---|---|---|
| `76fcb829` | 17 | 17 | 0 |
| `e5a92eba` | 25 | 25 | 0 |
| `ea9e9f2a` | 11 | 11 | 0 |
| `6639baa3` | 12 | 12 | 0 |
| `cfec9a1a` | 5 | 4 | 1 |
| `d2c95ca2` | 5 | 5 | 0 |
| `96c8bc72` | 2 | 2 | 0 |
| `a3492925` | 32 | 32 | 0 |
| `955e282a` | 5 | 2 | 3 |

The four per-tip mismatches are expected supersessions, not lost content:

- `cfec9a1a` → `plans/features/vmq-onto-01/evidence/vmq-m/engineering.md` was updated by the
  approved docs tip `d2c95ca2`; train matches `d2c95ca2`.
- `955e282a` → `engineering.md` (matches `d2c95ca2`), `services/mca_episode_jobs.py` and
  `tests/test_vmq_m1_episode_contract.py` (both match `cfec9a1a`).
- the restored `binding-m1-80726249.md` is matched.

Union totals: **75 unique paths, 75 matched, 0 mismatch** (the full path list is §3 plus the
restored M1 binding). Train diff vs base has 76 paths = 75 union + 1 evidence report.

**Evidence extra declaration:** `train-2.58.199-7c5669e5...md` (this file) is the **only**
non-union path in the train. It is intentionally kept in the corrective evidence directory and
declared explicitly; relocating it would not make the union exact because no approved tip
contains it. It contains no product code, tests, settings or generated runtime data.

No product/test path changed by this fix: `git diff 7c5669e5..HEAD` after the restore contains
only `plans/` files (restored binding + this report).

Decisive bounded re-run after the docs fix (same interpreter, cwd = train worktree):

| Set | Result | Exit |
|---|---|---|
| `tests/test_selfdiag_corrective_research.py` | **28 passed** | 0 |
| corrective focused set (10 files) | **330 passed** | 0 |
| `tests/test_deploy_identity.py tests/test_release_manifest.py` | **58 passed** | 0 |
| `tests/test_vmq_m1_episode_contract.py` | **34 passed** | 0 |
| `tests/test_memory_period_vector_leg.py` | **30 passed** | 0 |

The counts equal the pre-fix numbers, so the docs-only restoration did not affect behavior.
