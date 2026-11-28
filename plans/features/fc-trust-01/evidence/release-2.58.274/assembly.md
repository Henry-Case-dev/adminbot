# Release 2.58.274 — assembly (FC-TRUST S4: throttling reliability — single-flight claim + cancel refund)

- **Date:** 2026-11-28
- **Branch:** `release/2.58.274` (from `release/2.58.273` tip `2cbbea193`, deployed code `74ef57ef4`)
- **Worktree:** `WorkspaceData/worktrees/c742e4de9e92c489/release-2-58-274-5aac2da8cc1c-63c506eb` (registered)
- **Product change (one):** FCT-1001 / FCT-1002 — atomic cooldown claim (`PersistentCooldownTracker.claim` reads and occupies the slot inside one `write_transaction`) and a refund of the user's throttle slot when the factcheck handler is cancelled, plus service-side throttling wiring.
- **Everything else:** tests + evidence only.

## 1. Candidate merged (`--no-ff`)

| # | branch | tip | code SHA | verdict | merge commit | scope |
|---|--------|-----|----------|---------|--------------|-------|
| 1 | `feat/fct-s4-reliability-2026-11-28` | `320517373` | `dc6703a8f` | r1 `APPROVED_FOR_RELEASE_PREPARATION` (`evidence/fct-s4-reliability-2026-11-28/review-r1.md`) | `4b6b5279d` | 21 files: `handlers/factcheck.py` (+63/−…), `services/persistent_throttling.py` (+55), `services/smartmodule_throttling.py` (+12), 4 test seams, `tests/test_fc_trust_s4_reliability.py` (+722), evidence |

Tip `320517373` = code `dc6703a8f` + two evidence/docs commits (implementation + review r1); `git diff dc6703a8f 320517373` touches only `plans/features/fc-trust-01/evidence/**`.

Merge conflict check before doing it: `git merge-tree --write-tree 74ef57ef4 320517373` — no conflicts. Actual merge: clean, no manual resolutions.

## 2. Candidate → assembled-tree identity (`raw/identity-predeploy.txt`)

```
branch=release/2.58.274
head=731a7e51cdb747fb3c0507ec80b885e4217766b0   (bump commit)
base_deploy_74ef57ef4=74ef57ef469220627207603ae133da308f37866f
candidate_tip_320517373=320517373cc8185835f0011e5724d50eda12caf8
candidate_code_dc6703a8f=dc6703a8f77b11505f3fe8518960fadc9df806de
merge_commit_4b6b5279d=4b6b5279da17f85bf2f5bbf8fa09619718ca10ea
dirty_tracked=0
factcheck_py_blob=953fec05b22b37e987907be80cd9ea71dc9fa1ef candidate_blob=953fec05b22b37e987907be80cd9ea71dc9fa1ef
persistent_throttling_blob=52c21a6cdfd35a2fb178cbaaecbe5592011a8c55 candidate_blob=(same)
smartmodule_throttling_blob=0dff538b8769e0a4759806cb23f299af9fbbf0c7 candidate_blob=(same)
routes_blob=92bb8a72… routes_blob_base=92bb8a72…   (unchanged)
appjs_blob=8d3c535e… appjs_blob_base=8d3c535e…     (unchanged)
index_blob=90499d81… index_blob_base=90499d81…     (unchanged)
```

Every file the candidate touched is byte-identical (`git hash-object` == `git rev-parse dc6703a8f:<path>`). `web/api/routes.py`, `web/app.js`, `web/index.html` are unchanged from the deployed 2.58.273 blobs (sha256 `5c20750a…`, `20e87aa8…`, `b8570e5d…`), so the route set and Mini App bundle are untouched by this release.

## 3. Version bump

`raw/bump-verify.txt` — canonical version-only set (same 29 files as `5e38d9b72`, 2.58.272→2.58.273):

```
files_in_canonical_set=29 files_changed=29 occurrences_replaced=34
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0 non_version_added_lines=0
remaining_old_occurrences=0 new_occurrences=34
size_changed_files=(none)
APP_VERSION_lines=['APP_VERSION = "2.58.274"   # (27.11.2026): 2.58.254 - MAC-S4-172 …']
```

Commit `731a7e51c chore(release): bump 2.58.273 -> 2.58.274 (version-only, 29 files / 34 occurrences)`.

## 4. Check results

| check | command | result |
|-------|---------|--------|
| version contract | `pytest -k version -q` (`raw/version-contract.txt`) | 205 passed, 3 failed |
| base parity | same on `2cbbea193` (`raw/version-contract-base-2.58.273.txt`) | **identical 3 node-ids**, 205 passed, 3 failed → pre-existing |
| parameter registry | `tools/gen_param_registry_round1025.py --check` (`raw/registry-check.txt`) | exit 0, "реестр 668 == REGISTRY … R17-чисто" |
| collection | `pytest --collect-only -q` (`raw/collect-only.txt`) | exit 0, 23765 collected |
| routes contract module | `python -m tests.routes_contract --check` | module absent in repo (same as 2.58.273) → sha-pinned route suites + blob identity used |
| targeted throttling/handler | `test_fc_trust_s4_reliability, test_persistent_throttling, test_smartmodule_throttling, test_factcheck_handlers` (`raw/tests-targeted-throttle.txt`) | **104 passed** |
| targeted factcheck/routes family | `test_mca23_planned_vs_actual, test_round1025_f8_registry, test_fc_trust_s6_aggregate_api, test_fc_trust_{verdict,target,render,retrieval}, test_factcheck_media_2026_10_25, test_rc_target_media_evidence, test_mca20_integration_round1045, test_evol_fc_admission` (`raw/tests-targeted-factcheck.txt`) | **355 passed** |
| import smoke | `import handlers.factcheck, services.persistent_throttling, services.smartmodule_throttling` | ok |
| DDL | `git diff 74ef57ef4 HEAD -- services/database.py database migrations` | empty → schema untouched |

The 3 version-contract failures are the known stale-README / status-UI pins
(`test_hotfix_round1025_cachebust`, `test_status_section_ui_merge_round1019::test_mode_version_line_removed`,
`test_webapp_round108_ui::test_app_version_matches_readme`); reproduced with identical node-ids and counts on the
base commit `2cbbea193`, so they are not attributed to this release.

## 5. Manifest

`raw/manifest-predeploy.txt` — head `731a7e51c`, tree `16d79f701767a932bf942c1b49a21650915559bd`, version `2.58.274`,
`dirty_tracked: false`, candidate `320517373`, code `dc6703a8f`, schema unchanged.
