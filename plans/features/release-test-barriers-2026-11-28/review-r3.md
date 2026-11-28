# Independent re-review r3 — release/test barriers corrective (F-BAR-07)

- Reviewer: independent (Reviewer role), 2026-11-28.
- Candidate: branch `fix/release-test-barriers-2026-11-28`, tip `0ecefb8065b92e9cf662a616dde9aba98447c428`,
  code `114c6b4b4` (parent `2e76c6570`), base `release/2.58.272` `fa4ba62920a04ab5a4c994ad05c7dfb33d101f0e`.
- Scope: only F-BAR-07 and the r3 corrective `2e76c6570..114c6b4b4` (3 files); F-BAR-01/02/03 were closed in r2
  and are not re-audited except for regression checks.
- Evidence inspected: `implementation.md` §11, `raw/mutation-r2-*.txt`, `review-r2.md`.
- Worktree left with only this untracked review file; product/tests/branch unchanged.

## 0. VERDICT

| Item | Verdict |
|---|---|
| F-BAR-07 (missing `can_access_chat` in contract) | **CLOSED for the missing-name defect** — the seven routes now record it; X1 and X1c RED |
| F-BAR-08 (direct guard masked by same-name guard in a helper) | **OPEN — IN_SCOPE, severity medium (blocking)** |
| F-BAR-09 (`match_permission` argument not captured) | **OPEN — IN_SCOPE, severity low** |
| Candidate `114c6b4b4` / tip `0ecefb806` | **NEEDS_FIXES** |

The candidate is **not** approved for release preparation yet. No deployment is claimed.

## 1. Findings

### F-BAR-07 — named defect CLOSED; residual masking in F-BAR-08

- `can_access_chat`, `gate_authorization`, `guard_admin_lockout`, `guard_last_wildcard`,
  `validate_permissions`, `match_permission` are now classified; `_GUARD_NAME_RE` also has `^can_` / `^guard_`
  for calls, while `_is_guard_callback_name` keeps the narrow callback set (so `can_write`/`can_read` locals
  do not leak into `checks`).
- My X1 (`GET /direct/context-diagnostics`: remove only the `if not can_access_chat(...): raise`) → **RED**:
  `изменены проверки прав /direct/context-diagnostics ('GET',): ['can_access_chat','get_tma_user'] -> ['get_tma_user']`.
- My X1c (`GET /config/time`: same removal) → **RED** with the same shape.
- The seven chat-isolation routes now have `can_access_chat` in the manifest
  (`/config/time` GET+POST, `/direct/context-diagnostics`, `/direct/turn-diagnostics`,
  `/config/keys/status`, `/config/overrides-map`, `/status`).
- However, the contract still cannot distinguish a guard *directly* in the handler from the same guard
  name found only in a called helper. See F-BAR-08.

### F-BAR-08 — IN_SCOPE, severity: medium. Direct-guard removal is masked when the same guard name exists in a called helper

- Source/contract: `tests/routes_contract.py` docstring and `implementation.md` §1: «снятие RBAC/проверки
  прав … контракт обязан упасть»; r3 task explicitly asks to verify that the one-level helper expansion
  does not mask a real removal.
- Expected: removing the unconditional chat-isolation check from a protected handler turns
  `test_routes_contract_intact` RED, as X1 does on `/direct/context-diagnostics`.
- Actual: `collect_routes()` builds `checks` as a **set-union** of direct checks and one-level helper
  checks. If the same guard name exists in both places, removing the direct one leaves the name from the
  helper, so the contract stays **GREEN**.
- Reproductions (mine, `git checkout --` after each; tree clean):
  - **X1b** `GET /direct/turn-diagnostics`: delete only `web/api/routes.py:2877-2878`
    (`if not access_srv.can_access_chat(...): raise 403`) → contract **1 passed (GREEN)**. The name
    survives from `_turn_attach_text` (line 2833), which is called **only when `include_text=1`**
    (line 2965-2966). The default `include_text=0` path would return cross-chat turn diagnostics to any
    authenticated user. The behavioral test
    `tests/test_vmq_time09_turn_coverage.py::test_api_403_for_foreign_chat_and_200_for_admin` does catch
    this specific mutation (it gets 200 instead of 403), but the contract does not.
  - **X1d** `GET /config`: delete only `web/api/routes.py:690-691` → contract **1 passed (GREEN)**.
    The name survives from `_module_states_for_config` (line 636); the handler fetches foreign
    `chat_root` (line 692) before that helper's per-module check. Behavioral tests for foreign-DM/non-admin
    403 on GET /config still **pass** (4 passed) because the helper re-checks per module; they do not
    detect the removed early gate, and the contract does not either.
  - **X1e** `POST /config`: delete only `web/api/routes.py:1007-1008` → contract **1 passed (GREEN)**.
    The name survives from `_write_chat_overrides_with_retry` (line 1119), which is called only on one
    branch (line 1188). The early unconditional gate is not represented separately.
- Generalization: the same-name pattern exists on other routes (`/admins/remove`, `/config` GET/POST,
  `/config/time` POST, `/experience/pipeline`, `/persona` GET/sources/self-model for helper-only checks, etc.).
  The set-union cannot express “this guard must be present *in the handler itself*”.
- Impact: the release barrier (routes contract) can miss removal of an unconditional access check whenever
  a same-name check happens to exist in a called helper. That is the same class as F-BAR-07. Behavior tests
  catch X1b (200 instead of 403) but **not** X1d (4 passed); the contract is the systematic barrier and the
  same-name pattern can hide a future removal on a route without equivalent behavior coverage.
- Expected fix (cheap, schema change accepted): record direct and helper-derived checks separately
  (e.g. manifest schema 2 with `direct_checks` and `helper_checks`, or per-check origin) and assert both.
  Add a regression test with a synthetic handler + helper sharing a guard: remove the direct call while the
  helper still has it → must RED. Re-run X1b/X1d/X1e.

### F-BAR-09 — IN_SCOPE, severity: low. `match_permission` (alias of `requires_permission`) argument is not captured

- `tests/routes_contract.py` special-cases only the exact names `requires_permission` /
  `requires_recovery` for const args; `match_permission` is `requires_permission as match_permission`
  (`web/api/routes.py:67`) and is added to `EXPLICIT_GUARD_CALLS` as a bare name.
- My **P2**: change `_persona_has_edit_action` from `match_permission(perms, "edit_persona")` to
  `match_permission(perms, "access")` (line 5992) → contract **1 passed (GREEN)**. The manifest still says
  only `match_permission`, so a permission escalation in the persona edit gate is invisible. The route-level
  `requires_permission` argument change is still caught (M1 RED), so this is the inline alias path only.
- Impact: `/persona` PUT/DELETE and `/persona/rules/{rule_id}/pause|resume` rely on
  `_persona_can_edit` → `_persona_has_edit_action`; changing the required action is not detected.
- Expected fix: treat `match_permission` like `requires_permission` in the const-arg branch of
  `_source_checks`, re-emit the manifest, add a regression (arg change → RED).

## 2. Independent mutation table (mine)

Environment: `C:\Code\Python\adminbot\.venv`, `PYTHONPATH` = worktree, `-p no:cacheprovider`.
Each mutation edits `web/api/routes.py`; final `git status` clean.

| Probe | Result |
|---|---|
| X1 `/direct/context-diagnostics`: remove `can_access_chat` if+raise | **RED** — `['can_access_chat','get_tma_user'] -> ['get_tma_user']` |
| X1b `/direct/turn-diagnostics`: remove `can_access_chat` if+raise | **GREEN (masked)** — helper `_turn_attach_text` keeps the name; behavior test catches 200 |
| X1c `/config/time` GET: remove `can_access_chat` if+raise | **RED** — checks lose `can_access_chat` |
| X1d `GET /config`: remove direct `can_access_chat` if+raise | **GREEN (masked)** — `_module_states_for_config` keeps the name |
| X1e `POST /config`: remove direct `can_access_chat` if+raise | **GREEN (masked)** — `_write_chat_overrides_with_retry` keeps the name |
| X3 `POST /admins`: remove `guard_admin_lockout` | **RED** — `/admins` loses it |
| X4 `POST /roles`: remove `validate_permissions` | **RED** — `/roles` loses it |
| X5 `GET /config`: replace `gate_authorization` call | **RED** — `/config` loses it |
| X6b `POST /roles`: remove `guard_last_wildcard` | **RED** — `/roles` loses it |
| P1 remove `can_access_chat` inside `_persona_can_view` | **RED** — `/persona` loses it; `_persona_access` itself does not mask |
| P2 `match_permission(..., "edit_persona")` → `"access"` | **GREEN (false negative)** — F-BAR-09 |
| M1 `GET /admins`: `access` → `admin` | **RED** |
| M2 `GET /health`: add `Depends(get_tma_user)` | **RED** |
| M3 rename `/persona/rules/{rule_id}/sources` | **RED** |
| M4 `POST /vision/test`: drop `_ctx_global_admin` | **RED** |
| M5 shadow `GET /admins` without RBAC | **RED** — `неуникальные (path, methods)` |
| M6 `_prompt_hidden_admin` → `if False:` | **RED** |
| M7 remove `_random_selector_guard` | **RED** |
| M8 drop `_recheck_config_chat_rights` | **RED** |
| M9 drop `_recheck_meme_rights` | **RED** |

## 3. No false capture / business helpers / `_persona_access`

- `add_admin`, `remove_admin`, `upsert_admin` are **not** guards and do not appear in `checks`
  (`TestGuardHeuristic` + my manifest scan).
- No `can_write` / `can_read` / `can_edit` / `prompt_access` / `global_access` / `_persona_access` in any
  `checks`; the callback rule (`_is_guard_callback_name`) excludes the wide `^can_`/`^guard_` patterns.
- Added manifest checks correspond to actual guard calls or one-level expansion of a called module helper:
  25 routes changed, 0 checks removed. The “not in handler source” names (`gate_authorization`,
  `can_edit_param` on GET /config; `can_access_chat` on `/experience/pipeline`, `/persona*`) are all reached
  through named module helpers (`_module_states_for_config`, `_scoped_chat_or_none`,
  `_persona_can_view`/`_persona_can_edit`), not arbitrary names.
- `_persona_access` is correctly out of the contract (it only resolves `ctx`); the enforcement helpers
  `_persona_can_view` / `_persona_can_edit` are captured, and P1 proves removing `can_access_chat` inside
  `_persona_can_view` is RED. It does not mask a real removal.

## 4. Manifest / parity / emission

| Check | Result |
|---|---|
| `collect_routes()` vs manifest | **78 == 78**, equal, no duplicate/overlapping keys, public without initData = `['/health']` |
| `--emit` ×2 | same sha256 `1e126646e8fb915ca310273b18a4994223fa053dd50caadab621a5aeda3c5b9f` (matches §11.3) |
| `--check` | `CHECK OK`, exit 0 |
| Corrupted manifest copy | `CHECK FAILED`, exit 1 |
| Manifest writes | only `emit_manifest` (CLI / self-test `tmp_path`); no runtime regeneration |

## 5. Runs (reproduced)

| Run | Result |
|---|---|
| `tests/test_routes_contract_barriers.py` + `test_routes_contract_intact` | **51 passed** |
| 32 changed `tests/test_*.py` (cf. `fa4ba6292`) | **1024 passed, 3 failed** — only `test_webapp_round108_ui` (`test_old_labels_gone`, `test_three_windows`, `test_no_accordion`) |
| `pytest --collect-only -q` | **23 734 collected, exit 0** |
| `python tools/gen_param_registry_round1025.py --check` | **EXIT 0**, `реестр 668 == REGISTRY` |
| `tests/test_status_section_ui_merge_round1019.py` | **1 failed, 6 passed** on candidate and on base `fa4ba6292` (pre-existing) |

## 6. No weakening / boundaries

- Corrective diff is exactly 3 files: `tests/routes_contract.py`, `tests/fixtures/routes_contract.json`,
  `tests/test_routes_contract_barriers.py`. No product file (`web/**`, `services/**`, `config/settings.py`,
  `handlers/**`) changed; `git diff --name-only fa4ba6292 114c6b4b4` outside `tests/`/`plans/` is empty.
- Strictness increased, not decreased: uniqueness on AST decorators and live router, manifest validation,
  `assert fn is not None`, exact checks equality, public-route invariant. No assertion was removed or
  loosened. M1-M9 remain RED.
- Backlog F-BAR-04/05/06 unchanged (not part of this corrective; r2 verified they are honestly recorded).

## 7. Limitations

- Full 23 734-test suite was not run; changed files + targeted contract/behavior runs only.
- JS suite is not executed by pytest; F-BAR-05 remains a backlog observation.
- `checks` is still a set; the masking in F-BAR-08 is the concrete manifestation. Order/multiplicity of
  identical calls is not distinguished.
- No production/deploy verification; no deployment claim.

## 8. Bottom line

The missing-name defect of F-BAR-07 is fixed: the seven routes record `can_access_chat`, and X1/X1c are RED;
`_persona_access` does not mask (P1 RED); `add_*`/`remove_*`/`upsert_admin` are correctly excluded. But the
set-union of direct and one-level helper checks still masks removal of an **unconditional** direct guard when
a same-name guard exists in a called helper: X1b (`/direct/turn-diagnostics`), X1d (`GET /config`), X1e
(`POST /config`) are GREEN. That is F-BAR-08 (IN_SCOPE, medium). F-BAR-09 (`match_permission` argument not
captured; P2 GREEN) is a smaller in-scope gap. Both are local to `tests/routes_contract.py` + manifest
re-emission; no product change is needed. Re-review the direct-vs-helper representation, X1b/X1d/X1e, and
the `match_permission` argument after the correction.
