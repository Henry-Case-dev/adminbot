# Release 2.58.273 — assembly (FC-TRUST: S7 acceptance harness + S8 admission fix + U1 year-conflict fix)

- **Date:** 2026-11-28
- **Branch:** `release/2.58.273` (assembled from `release/2.58.272` tip `fa4ba6292`)
- **Worktree:** `WorkspaceData/worktrees/c742e4de9e92c489/release-2-58-273-f9db0e705d8d-2d64d359` (registered)
- **Product change (one):** U1 / FCT-U1-R1-F1 — a 4-digit amount is not a year (false year-conflict in factcheck no longer fires on money amounts).
- **Everything else:** test contracts + evidence only.

## 1. Candidates merged (`--no-ff`, in this order)

| # | branch | tip | verdict | merge commit | scope |
|---|--------|-----|---------|--------------|-------|
| 1 | `feat/fct-s7-acceptance-harness-2026-11-28` | `57ba095b5` | r2 APPROVED_FOR_RELEASE_PREPARATION | `430d3e52e` | 18 files, tests + evidence (`tests/test_fc_trust_acceptance.py` 12 deterministic scenarios + live skips) |
| 2 | `fix/fct-insufficient-evidence-title-2026-11-28` | `eab570fe0` | r1 APPROVED_FOR_RELEASE_PREPARATION | `893605b0a` | 8 files, test only (`tests/test_evol_fc_admission.py` +30) |
| 3 | `feat/fct-u1-assertion-binding-2026-11-28` | `10652fea4` (code `0fc7201ea`) | r2 APPROVED_FOR_RELEASE_PREPARATION (`evidence/fct-u1-2026-11-28/review-r2-f1.md`) | `48502c07f` | 47 files: `services/search_aggregator.py`, `services/temporal_factcheck.py`, `services/prompt_registry.py`, tests, evidence |

**Deviation from the dispatch note, recorded honestly:** the dispatch listed the U1 tip as
`49d8a5111`. The branch tip is `10652fea4` = `49d8a5111` + one docs/evidence commit
(`docs(fc-trust): U1 review r2 F1 …`), which adds only
`plans/features/fc-trust-01/evidence/fct-u1-2026-11-28/review-r2-f1.md` (+149 lines) and no
product/test code. `git diff 49d8a5111..10652fea4` touches exactly that one file, so the
merged code is byte-identical to the reviewed candidate `0fc7201ea`.

## 2. Candidate → assembled-tree identity

`raw/candidates-identity.txt` (script compares every file each candidate touched against `HEAD`):

```
candidate s7 tip=57ba095b5 ancestor_of_head=True files_vs_base=18 identical=18 version_only=0 mismatched=0
candidate admission tip=eab570fe0 ancestor_of_head=True files_vs_base=8 identical=8 version_only=0 mismatched=0
candidate u1 tip=10652fea4 ancestor_of_head=True files_vs_base=47 identical=47 version_only=0 mismatched=0
ALL_CANDIDATES_MATCHED=True
web/api/routes.py sha256=5c20750a0a273651600a2baf1fe0a74a842585742af1e1a846cf1f8ecff79bdf == 2.58.272
web/app.js sha256=20e87aa86fd888114ba706282021a4fcb10331e2672c0aec12d8b61f04b28e74 == 2.58.272
web/index.html sha256=b8570e5deb8136756dba402719d9530d6e3ff4ed17a45f18ed0d99b001323907 == 2.58.272
```

`web/api/routes.py`, `web/app.js`, `web/index.html` are identical to the currently deployed
2.58.272 blobs, so the route set and the Mini App bundle are unchanged by this release.

## 3. Version bump

`raw/bump-verify.txt` — the project's canonical version-only bump (same file set as
`cb47e6cbd`, 2.58.271→2.58.272):

```
files_in_canonical_set=29 files_changed=29 occurrences_replaced=34
removed_lines=34 added_lines=34
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0 non_version_added_lines=0
remaining_old_occurrences=0 new_occurrences=34
APP_VERSION_lines=['APP_VERSION = "2.58.273"   # …']
```

Byte sizes are unchanged for every file (pure `2.58.272`→`2.58.273` substitution), CRLF/LF
preserved. Commit `5e38d9b72 chore(release): bump 2.58.272 -> 2.58.273 (version-only, 29 files / 34 occurrences)`.

**Note for the record:** the dispatch asked for a two-file bump (`config/settings.py` +
`plans/docs/param-registry-round1025.meta.md`). That alone leaves 25 version-pin tests red and
would make the mandated `pytest -k version` contract fail. The repository's established and
reviewed convention (commits `cb47e6cbd`, `8578ebe17`, `3eafef83c`, `07c345e88`, …) is the
29-file / 34-occurrence version-only substitution; this release follows it and adds nothing
else to the bump.

## 4. Check results (see `raw/`)

| check | command | result |
|-------|---------|--------|
| version contract | `pytest -k version -q` | 205 passed, 3 failed — identical 3 fail on base `fa4ba6292` (stale README `v<version>` header + `statusData.bot.version` UI assertion) |
| parameter registry | `tools/gen_param_registry_round1025.py --check` | exit 0, `реестр 668 == REGISTRY … R17-чисто` |
| collection | `pytest --collect-only -q` | exit 0, 23754 collected |
| routes contract | `python -m tests.routes_contract --check` | module does not exist in this repo (see §5) |
| routes pin suites | `test_mca23_planned_vs_actual.py`, `test_round1025_f8_registry.py`, `test_fc_trust_s6_aggregate_api.py` | 62 passed |
| targeted | `test_fc_trust_acceptance`, `test_fc_trust_assertion_kind`, `test_fc_trust_relation_binding`, `test_evol_fc_admission`, `test_evol_fc_evidence_style` | 109 passed, 7 skipped |
| factcheck family (48 suites) | see `raw/tests-factcheck-family-release.txt` | 11 failed, 1071 passed, 7 skipped, 4 errors |
| factcheck family on base 2.58.272 (45 suites) | `raw/tests-factcheck-family-base-2.58.272.txt` | 11 failed, 1008 passed, 4 errors |
| pre-existing parity | diff of failure node-ids | `identical_sets=True`, 15 == 15 |
| surrounding suites | `test_asap8_v6_p1_d10_temporal`, `test_asap_fc_voice01_verbalizer`, `test_evol_evidence_routing`, `test_fc_backend_corrective`, `test_cfg07_guard_07d5/tail`, `test_evol_reply_context_consumers`, `test_asap8_v6_p1_d11_registry`, `test_caps_tool_results` | 364 passed |

Pre-existing failures are test-order/shared-state artifacts reproduced byte-for-byte at base
(same node ids, same counts) and are not attributed to this release.

## 5. `tests.routes_contract` note

`python -m tests.routes_contract --check` fails with `No module named tests.routes_contract`;
there is no `tests/routes_contract.py` in this repository (`raw/routes-contract-missing.txt`).
The equivalent in-repo mechanism — sha-pinned `web/api/routes.py` route-set contracts — was
used instead: the three pin suites above pass, and the routes file sha256
`5c20750a0a27…` equals the deployed 2.58.272 blob, so no route contract changed.

## 6. Manifest

`raw/manifest-predeploy.txt`.
