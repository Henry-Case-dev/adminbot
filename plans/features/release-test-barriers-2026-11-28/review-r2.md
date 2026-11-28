# Independent re-review r2 — release/test barriers corrective (F-BAR-01/02/03)

- Reviewer: independent (Reviewer role), 2026-11-28.
- Candidate: branch `fix/release-test-barriers-2026-11-28`, tip `2e76c6570bdb1dbd48698899bc649c908ef9c31e`,
  code `222ad0046c2a35ad94437424662aacbe7c3adede`, parent `e535ae4d9`, base `release/2.58.272`
  `fa4ba62920a04ab5a4c994ad05c7dfb33d101f0e` (prod `a2195fe3f` / 2.58.272).
- Scoped re-review: only the corrective `e535ae4d9..222ad0046` (3 files) and the three r1 findings;
  the full candidate was not re-audited.
- Evidence inspected: `implementation.md` §10 (sha256 `62d7aff5…`), `raw/mutation-m*.txt`,
  `raw/corrective-r1-*.txt`, `plans/backlog.md`.
- Worktree left with only this untracked review file; product/tests/branch unchanged (`git status` clean
  before writing this file).

## 0. VERDICT

| Item | Verdict |
|---|---|
| F-BAR-01 (shadow route) | **CLOSED** |
| F-BAR-02 (inline guards outside `GUARD_CALLS`) | **CLOSED for the five enumerated names; same-class gap remains → F-BAR-07** |
| F-BAR-03 (re-emission CLI) | **CLOSED** |
| Candidate `222ad0046` / tip `2e76c6570` | **NEEDS_FIXES** — one IN_SCOPE finding (F-BAR-07), cheap correction |

The candidate is **not** approved for release preparation yet. No deployment is claimed.

## 1. Findings

### F-BAR-01 — CLOSED (shadow route)

- `tests/routes_contract.py` now has `duplicate_route_keys`, `overlapping_route_methods`,
  `assert_routes_unique`, applied twice: on AST decorators (`collect_routes`) and on the live
  `api_router.routes`; `assert_routes_contract_intact` also validates the manifest itself.
- My M5 (second `@api_router.get("/admins")` with only `Depends(get_tma_user)`, inserted **before** the
  original): **RED** — `AssertionError: неуникальные (path, methods) в AST-декораторы routes.py:
  [('/admins', ('GET',))] …`. Matches the claim. `tests/test_routes_contract_barriers.py::TestDuplicateRoutes`
  covers rows-level, AST-level and overlapping-method cases.

### F-BAR-02 — CLOSED for the five named guards; class gap remains (see F-BAR-07)

- The five r1 names are now recorded and visible: `_prompt_hidden_admin`, `_random_selector_guard`,
  `_recheck_config_chat_rights`, `_recheck_meme_rights`, `_meme_template_guard` (`TestGuardHeuristic`,
  manifest diff on 4 routes).
- My independent mutations: M6 (`if not _prompt_hidden_admin(...):` → `if False:`) **RED**
  (`/prompts/catalog`); M7 (remove `_random_selector_guard(cache, prepared)`) **RED** (`/config`);
  M8 (drop `recheck=_recheck_config_chat_rights`) **RED** (`/config`); M9 (drop
  `recheck=_recheck_meme_rights`) **RED** (`/initiative/meme-settings`). All match the claimed messages.
- The named finding is fixed. The broader class is not (F-BAR-07).

### F-BAR-03 — CLOSED (re-emission CLI)

- `python -m tests.routes_contract --emit` / `--check` exist, are deterministic and documented in the
  module docstring. My run: two `--emit` produce the same sha256
  `2f2e6774b40bf548b98f0653732cf4ca39b2e53ada1dc2d3aacfc74081ac31ba` as the committed fixture;
  `--check` exits 0; a deliberately corrupted manifest copy makes `--check` exit 1 (`CHECK FAILED`).
  `TestManifestEmission` also writes only to `tmp_path`; no runtime regeneration of the fixture.

### F-BAR-07 — IN_SCOPE, severity: medium. Derived guard heuristic still misses a direct chat-access check (`can_access_chat`)

- Source/contract: module docstring (`tests/routes_contract.py:3-5`) and `implementation.md` §1:
  «снятие RBAC/проверки прав … контракт обязан упасть»; r1 F-BAR-02 disposition: derive the guard set
  so the next inline access check does not fall out.
- Expected: removing an access check from a protected handler turns the routes contract RED (the old
  whole-file sha256 caught any such change).
- Actual: `is_guard_call_name("can_access_chat")` is **False**. `collect_routes()` records only
  `get_tma_user` for routes whose handler enforces chat isolation via
  `access_srv.can_access_chat(ctx, chat_id)`.
- Reproduction (mine, not reused from `raw/`): at tip `2e76c6570`, delete only
  `web/api/routes.py:1644-1645` (`if not access_srv.can_access_chat(...): raise HTTPException(403)`)
  from `GET /direct/context-diagnostics`; run
  `pytest tests/test_round1025_f8_registry.py::TestFrozenInvariants::test_routes_contract_intact -q`
  → **1 passed (GREEN)**. Restored with `git checkout -- web/api/routes.py`.
- Affected routes with manifest `checks == ['get_tma_user']` **and** a direct `can_access_chat` gate
  (from `collect_routes()` + AST): `GET /config/time`, `POST /config/time`,
  `GET /direct/context-diagnostics`, `GET /direct/turn-diagnostics`, `GET /config/keys/status`,
  `GET /config/overrides-map`, `GET /status`. `GET/POST /config` also call it but have other recorded
  checks.
- Same class, not classified (lower materiality because route-level RBAC remains):
  `gate_authorization`, `guard_admin_lockout`, `guard_last_wildcard`, `validate_permissions`,
  `match_permission` (alias of `requires_permission`, only used inside a helper). `add_admin` /
  `remove_admin` / `upsert_admin` are correctly **not** guards.
- Impact: the branch replaces a file-wide sha256 pin with this contract; for these routes the contract
  is now the release barrier. A future accidental removal of the chat-isolation check would pass the
  contract. Behavior tests cover some of these routes but not all (e.g. no route-level RBAC test for
  `/direct/context-diagnostics`), so the contract gap is material. This is the same class as F-BAR-02,
  not a new requirement.
- Expected fix (cheap): add `can_access_chat` (and analogous access helpers) to
  `EXPLICIT_GUARD_CALLS` or extend `_GUARD_NAME_RE` (e.g. `_access$` / `^can_` / `^gate_` / `^guard_`),
  re-emit the manifest, add a `TestGuardHeuristic`/manifest regression for `can_access_chat`, and re-run
  M1-M9 plus the X1 probe. No product change.
- Evidence honesty: `TestGuardHeuristic.test_access_check_names_are_visible` covers only the five r1
  names plus the explicit set, so a green self-test does not prove the class is closed.
  `implementation.md` §9/§10.2 should name this limitation or fix it.

### F-BAR-04/05/06 — BACKLOG, honestly recorded

- `plans/backlog.md:39-43` lists all three, explicitly «не исправлялись»; no hidden fix.
- F-BAR-05 confirmed: `tests/js/round1025_hotfix{7,8,9,10}_*.js` still contain
  `/APP_VERSION = "2\.58\.255"/`; no JS runner in the pytest gate.
- F-BAR-06 confirmed: `tests/test_status_section_ui_merge_round1019.py::TestStatusSectionMerge::
  test_mode_version_line_removed` fails **1 failed, 6 passed** on both the candidate and base
  `fa4ba6292`.
- F-BAR-04 wording was corrected in `implementation.md` §1 (baseline holds keys, types are protected by
  `gen --check`), not silently «fixed» in code.

## 2. Independent evidence (reproduced by me)

Environment: `C:\Code\Python\adminbot\.venv`, `PYTHONPATH` = worktree, `-p no:cacheprovider`.
All mutations edit `web/api/routes.py` and are restored with `git checkout --`; final `git status` clean.

| Probe | Result |
|---|---|
| M1 `GET /admins`: `requires_permission("access")` → `("admin")` | **RED** — `изменены проверки прав /admins ('GET',): ['get_tma_user','requires_permission:access'] -> [...,'requires_permission:admin']` |
| M2 `GET /health`: add `Depends(get_tma_user)` | **RED** — `изменена auth-модель /health ('GET',): init_data False -> True` |
| M3 `/persona/rules/{rule_id}/sources` → `/persona/rule-sources/{rule_id}` | **RED** — `маршруты контракта отсутствуют …` |
| M4 `POST /vision/test`: drop `_ctx_global_admin` block | **RED** — `изменены проверки прав /vision/test ('POST',): ['_ctx_global_admin','get_tma_user'] -> ['get_tma_user']` |
| M5 shadow `GET /admins` without RBAC before original | **RED** — `неуникальные (path, methods) в AST-декораторы routes.py: [('/admins', ('GET',))]` |
| M6 `_prompt_hidden_admin` → `if False:` | **RED** — `/prompts/catalog` checks lose `_prompt_hidden_admin` |
| M7 remove `_random_selector_guard` | **RED** — `/config` checks lose it |
| M8 drop `_recheck_config_chat_rights` | **RED** — `/config` checks lose it |
| M9 drop `_recheck_meme_rights` | **RED** — `/initiative/meme-settings` checks lose it |
| X1b remove only `can_access_chat` if-guard from `GET /direct/context-diagnostics` | **GREEN (false negative)** — see F-BAR-07 |
| X2 remove direct `_prompt_require_view` from `GET /prompts/{prompt_key}/versions` | **RED** — checks `['_prompt_require_edit','_prompt_require_view','get_tma_user'] -> ['_prompt_require_edit','get_tma_user']`; the `_prompt_can_activate` over-approximation does not mask it |

Other runs:

| Run | Result |
|---|---|
| `pytest tests/test_routes_contract_barriers.py -q` | **27 passed** |
| 32 changed `tests/test_*.py` files (cf. `fa4ba6292..222ad0046`) | **1001 passed, 3 failed** — only `test_webapp_round108_ui` (`test_old_labels_gone`, `test_three_windows`, `test_no_accordion`) |
| `pytest --collect-only -q` | **23 711 collected, exit 0**, no collection errors |
| `python tools/gen_param_registry_round1025.py --check` | **EXIT 0**, `реестр 668 == REGISTRY` |
| `collect_routes()` vs `routes_contract.json` | **78 == 78**, equal, no duplicate/overlapping keys, public without initData = `['/health']` |
| `--emit` ×2 + `--check` | same sha256 `2f2e6774…81ac31ba`, `CHECK OK`, negative copy exits 1 |
| `tests/test_status_section_ui_merge_round1019.py` on candidate | **1 failed, 6 passed** (same on base `fa4ba6292`) |

## 3. No weakening / integration checks

- Corrective diff is exactly 3 files: `tests/routes_contract.py`, `tests/fixtures/routes_contract.json`,
  `tests/test_routes_contract_barriers.py`. No product file (`web/**`, `services/**`,
  `config/settings.py`, `handlers/**`) changed (`git diff --name-only fa4ba6292 222ad0046` outside
  `tests/`/`plans/` is empty).
- Strictness increased, not decreased: uniqueness asserted on AST decorators and live router; the
  manifest is validated too; every live `APIRoute` must have an AST decorator (`assert fn is not None`),
  so the old silent `checks=[]` path is gone. The exact `exp["checks"] == act["checks"]` equality and
  the public-route invariant remain.
- Manifest is static at runtime: `MANIFEST_PATH` is read by `load_manifest`; the only writer is
  `emit_manifest`, reached from `--emit` and from the self-test with `tmp_path`. No test auto-emits the
  committed fixture.
- Heuristic excludes business operations: `add_admin` / `remove_admin` / `upsert_admin` are not guards
  (covered by `TestGuardHeuristic.test_business_helpers_are_not_guards` and my probe).
- Over-approximation (`_prompt_require_edit` added to `GET /prompts/{prompt_key}/versions` through
  `_prompt_can_activate`) is deliberate and does **not** mask removal of the direct `_prompt_require_view`
  on that route (X2 RED). It only makes the contract stricter.
- JS literals are not silently «fixed»; F-BAR-04/05/06 remain backlog.

## 4. Limitations / not verified

- Full 23 711-test suite was **not** run; only changed files, the targeted contract test, collect-only,
  registry check and the two pre-existing-red files. No project-wide green claim.
- JS suite is not executed by pytest (no runner/package.json); F-BAR-05 remains a backlog observation.
- Semantic change inside a guard helper itself is not covered by the routes contract (declared
  limitation); `checks` is a set, so order/multiplicity of the same guard call is not distinguished.
- No production/deploy verification; no claim of deployment. Merge compatibility of the three branches
  was checked with `git merge-tree --write-tree` (exit 0 for barriers×S7 `57ba095b5` and
  barriers×admission `eab570fe0`); this is only a merge check, not release proof.

## 5. Bottom line

F-BAR-01 and F-BAR-03 are closed; F-BAR-02 is closed for the five enumerated guards and my M6-M9 are
RED. One IN_SCOPE gap remains: the derived heuristic does not classify `can_access_chat`, so removing
the chat-access check from seven protected routes leaves the routes contract green (F-BAR-07). The fix
is local to the test contract (add the name/pattern, re-emit, add the regression, re-run the mutations)
and does not require product changes. After that, the candidate should be re-checked against F-BAR-07
and the impacted mutations only.
