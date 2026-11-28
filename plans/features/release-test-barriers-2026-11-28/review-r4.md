# Independent re-review r4 — release/test barriers corrective (F-BAR-08/09)

- Reviewer: independent (Reviewer role), 2026-11-28.
- Candidate: branch `fix/release-test-barriers-2026-11-28`, tip `f1fdd9132ab53924c6599713b475f93b4f90364f`,
  code `69096c451` (parent `0ecefb806`), base `release/2.58.272` `fa4ba62920a04ab5a4c994ad05c7dfb33d101f0e`.
- Scope: only the r4 corrective `0ecefb806..69096c451` and F-BAR-08/09; F-BAR-07 and the earlier
  mechanisms are checked for preservation only.
- Evidence inspected: `implementation.md` §12, `raw/mutation-r3-*.txt`, `review-r3.md`.
- Worktree left with only this untracked review file; product/tests/branch unchanged.

## 0. VERDICT

| Item | Verdict |
|---|---|
| F-BAR-08 (direct guard masked by same-name helper guard) | **CLOSED** — X1b/X1d/X1e RED via `direct_checks` |
| F-BAR-09 (`match_permission` argument) | **CLOSED** — P2 RED via `helper_checks` with `match_permission:*` |
| F-BAR-07 / earlier mechanisms | **preserved** — X1/X1c/P1 RED; 7 routes keep `can_access_chat` in `direct_checks` |
| F-BAR-10 (helper-helper union can still mask a helper guard removal) | **BACKLOG, low** — pre-existing set-multiplicity, not a depth-2 regression |
| F-BAR-11 (attribute-call/module-function name collision adds a false helper check) | **BACKLOG, low** — over-approximation, no weakening |
| Candidate `69096c451` / tip `f1fdd9132` | **APPROVED_FOR_RELEASE_PREPARATION** |

The candidate is suitable for the next release (2.58.274) **as a test-contract change**; product code is
untouched. No deployment is claimed.

## 1. Findings

### F-BAR-08 — CLOSED: direct guard removal is now visible

- `tests/routes_contract.py` schema 2 separates `direct_checks` (handler body/signature, no nested
  functions, no module-helper expansion) from `helper_checks` (nested functions + module helpers up to
  depth 2). `assert_routes_contract_intact()` compares both independently.
- My reproductions (each restored with `git checkout --`; tree clean):
  - **X1b** `GET /direct/turn-diagnostics`: delete only `web/api/routes.py:2877-2878` → **RED**
    `изменены прямые проверки прав /direct/turn-diagnostics ('GET',): ['can_access_chat','get_tma_user']
    -> ['get_tma_user']`.
  - **X1d** `GET /config`: delete only lines 690-691 → **RED** with the same `direct_checks` message.
  - **X1e** `POST /config`: delete only lines 1007-1008 → **RED** with the same `direct_checks` message.
- The self-check now asserts the exact pair for these routes
  (`test_manifest_separates_direct_guard_with_same_name_in_helper`) and a synthetic direct+helper case
  (`test_direct_guard_removal_is_visible_despite_same_helper_guard`).

### F-BAR-09 — CLOSED: `match_permission` argument is bound

- `match_permission` is in `_PERMISSION_ARG_CALLS`, so the const argument is recorded:
  `match_permission:edit_persona` / `match_permission:section.content`.
- My **P2** (`match_permission(perms, "edit_persona")` → `"access"`, line 5992) → **RED**:
  `изменены проверки прав в хелперах /persona ('DELETE',): ['match_permission:edit_persona',
  'match_permission:section.content'] -> ['match_permission:access', 'match_permission:section.content']`.
- Depth-2 removal is also caught: **P3** (`return match_permission(..., "edit_persona")` → `return False`)
  → **RED** with `match_permission:edit_persona` missing from `/persona` DELETE `helper_checks`.
- The self-check `test_match_permission_argument_is_recorded` covers the synthetic and manifest cases.

### F-BAR-10 — BACKLOG, severity: low. `helper_checks` is still a union: a guard removed from one helper can be masked by the same name in another helper

- Not a regression and not the F-BAR-08 defect: `direct_checks` is independent, so direct removal is
  always caught. This is the residual set-multiplicity inside `helper_checks`.
- Repro: `/config` POST has `can_edit_param` in both the nested `_recheck_config_chat_rights` and the
  module helper `_post_config_global`. Replace `if not access_srv.can_edit_param(fresh_ctx, matrix):`
  (line 1149) with `if False:` → contract **1 passed (GREEN)**. The direct initial `can_edit_param` in
  `post_config` remains, so the primary authorization is intact; the C3 recheck before the second write
  is not protected by the contract.
- This existed in r3 as well (the old `checks` union had the same overlap); r4 did not introduce it. The
  r4 declared guarantee is direct-vs-helper, which holds. If helper-level removal coverage is desired,
  the manifest needs per-source helper checks (or a helper-source label), not a single union.
- Backlog, not a release veto: the primary direct check remains and the product is untouched.

### F-BAR-11 — BACKLOG, severity: low. Attribute method call is matched to a module-level route handler, adding a false helper check

- `_persona_traits_meta` calls `bot_persona.get_persona_health()` (line 6080). `_called_helpers()` matches
  the call name `get_persona_health` to the module-level route handler `get_persona_health` (line 6472),
  whose signature has `Depends(requires_global_admin())`.
- Result: `/persona` GET `helper_checks` contains `requires_global_admin`, which is not a guard on that
  handler's path. It is an over-approximation (stricter), not a weakening; it can cause a spurious re-emit
  if `/persona/health` changes.
- Suggested low-priority improvement: expand module-level helpers only for bare `ast.Name` calls, not
  `ast.Attribute` calls (or exclude route-handler names from helper expansion). Backlog.

## 2. Independent mutation table (mine)

Environment: `C:\Code\Python\adminbot\.venv`, `PYTHONPATH` = worktree, `-p no:cacheprovider`.
Each mutation edits `web/api/routes.py`; final `git status` clean.

| Probe | Result |
|---|---|
| X1 `/direct/context-diagnostics`: remove `can_access_chat` | **RED** — `direct_checks` loses it |
| X1b `/direct/turn-diagnostics`: remove direct `can_access_chat` | **RED** — `direct_checks` loses it (F-BAR-08 closed) |
| X1c `GET /config/time`: remove `can_access_chat` | **RED** — `direct_checks` loses it |
| X1d `GET /config`: remove direct `can_access_chat` | **RED** — `direct_checks` loses it |
| X1e `POST /config`: remove direct `can_access_chat` | **RED** — `direct_checks` loses it |
| X3 `POST /admins`: remove `guard_admin_lockout` | **RED** — `direct_checks` loses it |
| X4 `POST /roles`: remove `validate_permissions` | **RED** — `direct_checks` loses it |
| X5 `GET /config`: replace `gate_authorization` | **RED** — `helper_checks` loses it |
| X6b `POST /roles`: remove `guard_last_wildcard` | **RED** — `direct_checks` loses it |
| P1 remove `can_access_chat` inside `_persona_can_view` | **RED** — `helper_checks` loses it; `_persona_access` does not mask |
| P2 `match_permission(..., "edit_persona")` → `"access"` | **RED** — `match_permission:access` in `helper_checks` |
| P3 remove `match_permission(..., "edit_persona")` at depth 2 | **RED** — `match_permission:edit_persona` lost |
| M1 `GET /admins`: `access` → `admin` | **RED** |
| M2 `GET /health`: add `Depends(get_tma_user)` | **RED** |
| M3 rename `/persona/rules/{rule_id}/sources` | **RED** |
| M4 `POST /vision/test`: drop `_ctx_global_admin` | **RED** |
| M5 shadow `GET /admins` without RBAC | **RED** — `неуникальные (path, methods)` |
| M6 `_prompt_hidden_admin` → `if False:` | **RED** |
| M7 remove `_random_selector_guard` | **RED** — `helper_checks` loses it |
| M8 drop `_recheck_config_chat_rights` | **RED** — `direct_checks` loses it |
| M9 drop `_recheck_meme_rights` | **RED** — `direct_checks` loses it |

## 3. Schema 2 / parity / emission

- Manifest: `schema: 2`, 78 rows, **0 legacy `checks`**, `direct_checks`/`helper_checks` sorted;
  `route_checks(row)` is the sorted union and is used by all readers (`test_fc_trust_s6_aggregate_api`
  adapted; no `["checks"]` reader left for this manifest).
- `collect_routes()` vs manifest: **78 == 78, equal=True**, duplicate/overlapping keys empty,
  public without initData = `['/health']`.
- `--emit` ×2: sha256 `05ed342b2284347b0fe4ee910d63e9d4e68cd3f4182809d6ab0d98042a19987f` stable;
  `--check` OK; a corrupted manifest copy → `CHECK FAILED`, exit 1.
- No false captures of the named categories: `add_admin`/`remove_admin`/`upsert_admin`,
  `prompt_access`, `global_access`, `can_read`/`can_edit`/`can_write`, `_persona_access` are absent from
  both sets. The `/vision/*` `can_access_chat` addition comes from the real `_scoped_chat_or_none`
  helper; `match_permission` args are specific. The only false capture found is F-BAR-11 (attribute call
  collision), an over-approximation.
- Depth 2 does not re-create direct masking: `direct_checks` is compared independently, P3 shows a
  unique depth-2 guard removal is RED, and P1 shows `_persona_access` (out of contract) does not hide
  removal in `_persona_can_view`.

## 4. Runs (reproduced)

| Run | Result |
|---|---|
| `tests/test_routes_contract_barriers.py` | **54 passed** |
| self-check + `test_routes_contract_intact` + `test_fc_trust_s6_aggregate_api` | **64 passed** |
| 32 changed `tests/test_*.py` (cf. `fa4ba6292`) | **1028 passed, 3 failed** — only `test_webapp_round108_ui` (`test_old_labels_gone`, `test_three_windows`, `test_no_accordion`) |
| `pytest --collect-only -q` | **23 738 collected, exit 0** |
| `python tools/gen_param_registry_round1025.py --check` | **EXIT 0**, `реестр 668 == REGISTRY` |
| `tests/test_status_section_ui_merge_round1019.py` | **1 failed, 6 passed** on candidate and on base `fa4ba6292` (pre-existing) |

## 5. No weakening / boundaries

- Corrective diff is 4 files: `tests/routes_contract.py`, `tests/fixtures/routes_contract.json`,
  `tests/test_routes_contract_barriers.py`, and the reader adaptation in
  `tests/test_fc_trust_s6_aggregate_api.py` (`route_checks()` instead of the removed `checks`). No product
  file (`web/**`, `services/**`, `config/settings.py`, `handlers/**`) changed; outside `tests/`/`plans/`
  the diff is empty.
- Strictness increased: uniqueness on AST and live router, manifest validation, `assert fn is not None`,
  independent `direct_checks`/`helper_checks` equality, public-route invariant; no assertion was removed
  or loosened. M1–M9 and all X probes remain RED.
- `test_fc_trust_s6_aggregate_api` still asserts `requires_global_admin` or `_ctx_global_admin` in the
  union; the adaptation is equivalent to the old `checks` membership.

## 6. Limitations

- Full 23 738-test suite was not run; changed files + targeted contract/behavior runs only.
- JS suite is not executed by pytest; F-BAR-05 remains a backlog observation.
- F-BAR-10 (helper-helper union) and F-BAR-11 (attribute-call false capture) are recorded as backlog/low.
  They do not undermine the r4 acceptance: direct-vs-helper is fixed, depth-2 unique checks are caught,
  and the product is unchanged.
- No production/deploy verification; no deployment claim.

## 7. Bottom line

F-BAR-08 and F-BAR-09 are closed with independent RED evidence (X1b/X1d/X1e via `direct_checks`, P2 via
`helper_checks` with `match_permission:*`). The schema 2 split is correct, the manifest is static and
byte-stable, and the earlier mechanisms (F-BAR-01/02/03/07) remain intact (X1/X1c/X3/X4/X5/X6b, P1,
M1–M9 all RED). The residual helper-helper union and the attribute-call false capture are low-severity
backlog observations, not blockers for a test-contract release; the product is untouched.

Candidate `69096c451` / tip `f1fdd9132` is **approved for release 2.58.274 as a test-contract change**.
