# Harness review â€” SXR / SFC live-canary evidence

**Verdict: Needs Fixes**

- SXR and FC offline self-tests are not admissible: SXR fails and crashes with `CapacityResult.as_window_meta`; FC times out with exit 143.
- Both harnesses are untracked and absent from release commit `13884da`; no candidate-binded evidence.
- Vacuous arsertions were found: unconditional true continuation assertion and `count >= 0` journal check.

## Proof pillars

1. **Implementation**: read both harnesses along control loop, evidence, safety budgets, flag handling, jurnal identity, and FC scenarios. Scripted doubles prove only controlled plumbing.
2. **Test validity*: SXR fails and FC times out; no passing admissibility proof exists.
3. **Independent challenge*: provider-disabled self-test challenge fails for both harnesses.

## Acceptance ledger

All deelegated SXR (Rùe}=I}1%Y¤¹M±¥Ù”µ…¹…ÉäÉ½ÝÌè€¨©U9YI%%¨¨¸9¼±¥Ù”ÉÕ¸¥Ì…ÕÑ¡½É¥é•¸±…œµ½™˜½½¸ØÈÍ•¹…É¥½Ì°¡•­ÕÁ}É•…°°©½ÕÉ¹…°¥‘•¹Ñ¥Ñä°É…Ü1¤¹Õµ‰•ÉÌ°…¹Í…™•Ñä±…¥µÌÉ•µ…¥¸U9YI%%™½ÈÉ•±•…Í”•Ù¥‘•¹”¸((ŒŒ	±½­¥¹œ™¥¹‘¥¹Ì((´€¨© ´Ä	1=-H¨¨è¡…É¹•ÍÌ…¹‘¥‘…Ñ”µ¥Íµ…Ñ ¸	Õ¥±‘•ÈµÕÍÐ½µµ¥ÐÑ¡”•á…Ð¡…É¹•ÍÍ•Ì°‰¥¹M!½‘¥•ÍÐ°Ñ¡•¸É•Ù¥•Ü……¥¸¸((´€¨© û"$Äô4´U"¢£¢5…"öffÆ–æR6VÆb×FW7Bf–Ç2×VÇF—ÆRÆö÷ö66—G’76W'F–öç2æB7&6†W2BÆ–æR3#“bv—F‚Ö—76–ær”66—G•&W7VÇBæ5÷v–æF÷uöÖWFâ'V–ÆFW"×W7B&W—"æB&÷fRW†—Bv—F†÷WBG&6V&6²à £ëH
Š’È“ÐÒÑTŠŠŽˆÈÙ[‹]\Ý[YYÝ]]NÙXÈ[™Ø\È\›Z[˜]YÚ]^]MËˆZ[\ˆ]\Ý™[[Ý™HHÙ™›[™H[™È[™™\[ˆÈ^]Ú]Ù[—Ý\ÝÜ\ÜÙYYK‚‚‹H
Š’“ÐÒÑTŠŠŽˆ˜XÝ[Ý\È\ÜÙ\[ÛœÈ[™ØÜš\Y™\ÜÛ™\œÈØ[ˆÛÛ\HÚ]HÜ›Û™È™Z]š[Ü‹ˆZ[\ˆ]\ÝYYX[š[™Ù[™YØ]]™H\ÜÙ\È[™X™[[Xš[™ÈÛ›K‚‚ˆÈÈÚXÚÜÈ[™™^XÝ[Û‚”\™›Ü›YYˆÛÝ\˜ÙKX\ÛÛ\[KÕÔˆÙ[‹]\ÝÈÙ[‹]\Ý][\™[X\ÙK]™YHš[™[™ÈÚXÚËˆ™]\ÙY\›Ý˜[]šY[˜ÙNˆ›Û™Kˆ›È›ÙXÝ[Û‹Ü›ÝšY\ˆØ[Ø\ÈXYKˆZ[\ˆ™\Z\œÈ[™ÛÛ[Z]ÈH^XÝ\›™\ÜÙ\Ë[ˆÜ˜Ú\Ý˜]Üˆ›Ý]\ÈH™]ÈØ[™Y]HÈ[ˆ[™\[™[™]šY]Ë‚‚”›Ø™H[ØØ][ÛŽˆÎ—\Ù\œ×XZ[—˜ÛÛ™šY×Ü[˜ÛÙWÛÜšÜÜXÙQ]W[œ×ÍÍ™MNL™LŒX—>smart-execution-reliability-01-45d7d5f19c3b\\ùÁÉ½‰”µ™‘…”Ñ”ÈÕÅ€. 
## Re-review r2 (corrected harnesses) 
 
Verdict: both corrected harnesses are admissible for production evidence collection; parent acceptance rows remain UNVERIFIED. 
 
H-1 fixed. Both files are committed in ea595ef8 and 46dec0b3. SHA256 matched the requested SMART and FC values. SMART reported tracked=true and blob_matches_head=true; FC JSON reported binding_status=verified, dirty=false, git_head=13884daa. Wrong expected SHA exited 2 before checks. Foreign SMART checkout exited 1 with explicit BLOCKED and no traceback. 
 
H-2 fixed. SMART self-test against the release worktree exited 0 in 5020 ms, failures=0, no traceback; all loop, caps, capacity, variants, continuation, evidence-class and redaction checks passed. 
 
H-3 fixed. FC self-test exited 0 in 3345 ms with self_test_passed=true and reported duration 0.257 s. A hung-step probe returned HUNG_STEP_TIMED_OUT True, duration 1.007 s, bounds step 0.2 s and total 1.0 s, process exit 0. 
 
H-4 fixed. SMART continuation requires real remainder/cursor, next range and second read; journal requires aggregate rows and a real last attempt. FC checks stop reason, durable run scope, and delivered plus remainder equals total; S14 runs positive and negative controls. No old unconditional True or count greater-than-or-equal zero decision predicate remains. 
 
Runtime checks: SMART self-test exit 0; FC self-test exit 0; SMART dry-run exit 0 with 14 checks and no network or DB; FC dry-run exit 0; SMART selected offline checks had observed=0, production_observed=0, not_observed=3, error=0; FC selected checks had observed=2, not_observed=1, production_observed=0, error=0. 
 
FC flag probe with flags.factcheck_pipeline_v2=false returned PIPELINE_V2_ENABLED False, exit 0. run_scenario returns not_observed with pipeline_v2_disabled_effective. 
 
Per-check admissibility: self-tests and offline guards are admissible only as preflight; offline plumbing is not production evidence; SMART checkup/I1/I2 and FC v2-on production scenarios remain unverified and ready for controlled collection. 
 
No H-1 through H-4 blocker remains. No production canary or paid provider call was run, and no requirement was marked VERIFIED.
 
## Audit r3 (post-production harness fixes) 
 
Candidate d7df228d. SMART sha 21c7ac74dbe139d9784168b93cb0a1a6c7fb7f18c1e17f7aa497d6d12fffd820; FC sha 984dbdf444e13974767e10954e2aa4f69f4f2c921f0c20c0f39892435c05ef2d. Deployed application worktree 13884daa release/2.58.200. No production or paid provider calls. 
 
Three pillars: inspected FC PgDatabase readonly SELECT path, effective pipeline-state contract, SMART BudgetState.as_meta and source-reader contracts; read changed assertions and negative controls; independently ran both self-tests, both dry-runs, foreign checkout, SHA mismatch and disposable mutations for budget shape, K3 attribution, PG failure and timeout behavior. 
 
Fix status: FC PG read fixed, S16/S17 passed; synthetic PG outage produced available=false, exact pg error, known=false enabled=null source=unavailable. SMART budget contract fixed; unknown enabled-only shape returned None with expected budgets_enabled and observed keys. SMART K3 fixed; unattributed and out-of-window writes returned ok=false. External-read contract fixed in source and assertions: README unverified, source file verified, network/content/identity/refusal/SafeFetcher checks required. 
 
Runtime: SMART self-test exit 0 failures=0; FC self-test exit 0 self_test_passed=true duration 0.282; SMART dry-run exit 0 14 checks no network/DB; FC dry-run exit 0 identity_code unknown; SMART foreign checkout exit 1 explicit BLOCKED; SMART bad expected SHA exit 2 before checks. 
 
Remaining blocker: FC has no explicit --expect-harness-sha256 CLI option. Supplying it exits 2 as unrecognized argument, not as a deliberate preflight hash mismatch. Location fc_live_canary.py _parse_args around 2740-2760 and _main around 3500. This is a focused binding blocker for FC production rerun; add explicit expected-hash preflight or document and independently verify an equivalent binding mechanism. 
 
SMART verdict: admissible for the production re-run. 
FC verdict: not admissible for the production re-run until explicit hash-mismatch preflight is added or formally replaced and independently verified. 
 
Parent acceptance remains UNVERIFIED.
 
## Final binding recheck (FC, commit 6f6d414d) 
 
FC SHA256 391deff843a4254470e01767ae20823dc85c08853c4bad8cb62dccc88aba972c matched Get-FileHash. Prior Audit r3 section was inspected and preserved; its FC blocker text was unchanged before this append. 
 
Preflight ordering at fc_live_canary.py lines 3820-3847: parse args, self hash and expected hash preflight run before Runtime, load_modules, read_pg_snapshot, provider setup or checks. 
 
Correct SHA normal run: exit 0, checks 6, observed 2, not_observed 4, errors 0, production_observed 0; JSON harness_sha256 and expected_harness_sha256 matched. 
Zero SHA: exit 2, PREFLIGHT FAILED no checks were run, JSON checks 0 and reason harness_sha256_mismatch, with no pg or provider_calls fields. 
notasha: exit 2, malformed expected SHA message, JSON checks 0 and reason expected_sha256_malformed, with no pg or provider_calls fields. 
self-test: exit 0, self_test_passed true, duration 0.48; S18 covers match mismatch malformed absent and child-process preflight. 
correct SHA plus offline dry-run: exit 0, dry_run true, identity_code unknown, offline true. 
 
Final FC verdict: admissible for the production re-run with pinned SHA 391deff843a4254470e01767ae20823dc85c08853c4bad8cb62dccc88aba972c. No requirements were marked VERIFIED.
 
## Audit r4 (F4 external scenarios) 
 
Candidate 67701e0b; SMART harness SHA256 39600b90ebc0e7b6873846e1e2db1f512c0d5c8478ed5edf2f94c0acdad41119 matched Get-FileHash. Release application worktree 13884daa, branch release/2.58.200. No natural-request check, paid calls, Bot sends or production writes were run. 
 
Implementation pillar: inspected external_scenarios lines 2193-2520. It uses production ToolRouter.dispatch read_source_code for read, locate and blob-link operations; asserts actual status, path, exact commit, source_kind=file, verified, snippets, network_calls, related sibling, factual missing-repo code and no retries. Capability facts inspect canonical tool schemas/command registry. external_natural_request lines 2523-2672 is gated by allow_provider_calls, consumes one provider budget unit, parses a real L1 decision and requires selected read_source_code execution plus verified path and network. 
 
Test-validity pillar: self-test exit 0, failures=0, and all 24 external controls passed: chain positive/negative, exact commit/path negatives, link identity negative, factual missing/rate-limit/unknown-code/retry negatives, extra-tool/partial-operation/command negatives, wiring observed/broken not_observed and natural-request guard without flag. 
 
Independent falsification: disposable mutation with related sibling path equal to primary produced distinct_verified_sibling=False; missing status=ok mutation produced factual=False and not_read=False; unknown refusal code produced factual=False. Predicates flipped as required. 
 
Runtime outputs: self-test exit 0, failures=0, harness SHA matched, tracked=True and blob_matches_head=True. Dry-run exit 0 listed 16 checks and no network/DB. Offline external_scenarios exit 0 with status not_observed, production_observed=0 and failed_assertions=0. Real external_scenarios on release worktree with provider calls disabled and max-provider-calls 0 exited 0: status observed, production_observed=1, not_observed=0, error=0, failed_assertions=0, duration 7.25s. 
 
Safety: focused run used one production read_source_code tool path, no Bot/send/config persistence, no natural provider call, no paid calls. The observed external result is production-class real network evidence; it is not promoted to requirement VERIFIED here. 
 
Per-check admissibility: external_scenarios is admissible for the focused production run; self-test and offline are plumbing/unavailable only; external_natural_request is admissible only for a later authorized production run with allow-provider-calls and remains unverified in this audit. 
 
Remaining blocker: none for external_scenarios harness admissibility. external_natural_request remains intentionally unverified because it requires a real provider call; this is a postdeploy/live evidence condition, not a harness defect. 
 
SMART verdict: admissible for the focused production run (external_scenarios plus later external_natural_request under its explicit provider gate). No requirements were marked VERIFIED.

## Audit r5 (FC harness v1.4.0 cap/proxies)

Candidate `16fbae81fffec1baa8a4eca3763812d4ce205a2f` (master); `fc_live_canary.py` v1.4.0. Exact harness SHA256: `afcd6ee00ffe332cf64503e7ec05e9845483f73e7745627fe910763a7776e3f1`, independently matched with `Get-FileHash`. Release application worktree: `13884daa32e5cf2a1c05c5c43188ca299f8179f8`. No production access, provider/paid calls, Bot sends, or PG writes were used.

### Implementation

Inspected the cap path around `fc_live_canary.py:1649-1770`, scenario consumers around `2670-2816`, and proxy predicates around `2819-2964`. `run_scenario` reserves the documented measured `CHECK_CALL_COSTS` plus answer-stage margin before starting; insufficient remaining budget returns `provider_budget_insufficient` without starting the pipeline. A cap reached during execution is represented separately as `provider_cap_reached`, with denied-call count/kinds and `evidence_class=unavailable`; the message explicitly says it is **not a product verdict**. Provider failure remains a distinct state. Raw event fields (`finish_reason`, `reason_code`, `decision`, `fallback_used`, `error_code`) are retained. `material_kept` requires both subject overlap >= 0.6 and actual material-anchor usage; `_answer_stage_reached` requires verdict and verbalize stages and rejects `temporal_fallback_mode`; country matching uses stems; honest direct negative answers are accepted while the generic fallback template is rejected.

### Test validity

Read S19-S21 bodies and assertions. S19 asserts red/green cap controls, `provider_budget_insufficient` versus `provider_cap_reached`, unavailable evidence class, and cap-not-provider-failure semantics. S20 asserts nominative/genitive/instrumental country forms, unrelated-country rejection, honest-negative acceptance, fallback-template rejection, and independent anchor defect/fix/weak-presence cases. S21 asserts the defective bundle fails `material_kept`, `answer_stage_completed`, and `direct_answer_on_question`, while the corrected bundle passes all assertions. The release-worktree self-test exited `0` with `self_test_passed=true`; dry-run exited `0`; offline exited `0` with 6 checks, 2 observed, 4 not observed, 0 errors, and 0 production observations. These self-tests are plumbing evidence, not production acceptance.

### Independent challenge

A disposable byte-level mutation changed only the S20 defect control from requiring `anchor_used is False` to `anchor_used is True`. The mutated self-test exited `1`, with `S20_answer_measurement_predicates.ok=false` while the fixed-anchor control remained true; this demonstrates the anchor predicate is non-vacuous. The exact preflight mismatch was also exercised with a 64-zero expected SHA: exit `2`, `checks=[]`, reason `harness_sha256_mismatch`, and no `pg` or `provider_calls` fields. The first probe invocation from the allocated run directory failed only because a relative script path was resolved against the run directory; it was immediately corrected from the repository root and is not a candidate behavior result.

### Admissibility and ledger disposition

| Mandatory item | Status | Evidence / limitation |
|---|---|---|
| Cap is measurement state, not product verdict | REVIEW-VERIFIED / admissible | Implementation audit + S19 + independent preflight; no live provider run in r5 |
| `provider_budget_insufficient` vs `provider_cap_reached` vs provider failure | REVIEW-VERIFIED / admissible | `run_scenario`, S19 and distinct machine fields inspected |
| SFC-12-09 material overlap plus actual anchor | REVIEW-VERIFIED / admissible | `_material_anchor_usage`, S20/S21, mutation flip |
| Answer stage excludes `temporal_fallback_mode` | REVIEW-VERIFIED / admissible | `_answer_stage_reached`, S20/S21 assertions |
| Country stems / honest negative / fallback rejection | REVIEW-VERIFIED / admissible | S20 assertions and source audit |
| Preflight SHA binding | REVIEW-VERIFIED / admissible | Exact candidate SHA, exit-2 mismatch with zero checks and no PG/provider fields |
| `original_production_scenario` live acceptance | UNVERIFIED | No production/provider calls by instruction; requires clean isolated run with cap 20 |
| `production_smoke` live acceptance | UNVERIFIED | No production/provider calls by instruction; requires clean isolated run with cap 12 |

`REVIEW-VERIFIED / admissible` above means the harness mechanism is accepted for the requested controlled production rerun; it does not mark any product requirement `VERIFIED`. The two production checks remain `UNVERIFIED` until their real isolated runs produce candidate-bound evidence.

**Verdict: admissible for the clean isolated runs** `--checks original_production_scenario --max-provider-calls 20` and `--checks production_smoke --max-provider-calls 12`. No harness blocker found. No requirements were marked `VERIFIED`.