# Harness review ‚Äî SXR / SFC live-canary evidence

**Verdict: Needs Fixes**

- SXR and FC offline self-tests are not admissible: SXR fails and crashes with `CapacityResult.as_window_meta`; FC times out with exit 143.
- Both harnesses are untracked and absent from release commit `13884da`; no candidate-binded evidence.
- Vacuous arsertions were found: unconditional true continuation assertion and `count >= 0` journal check.

## Proof pillars

1. **Implementation**: read both harnesses along control loop, evidence, safety budgets, flag handling, jurnal identity, and FC scenarios. Scripted doubles prove only controlled plumbing.
2. **Test validity*: SXR fails and FC times out; no passing admissibility proof exists.
3. **Independent challenge*: provider-disabled self-test challenge fails for both harnesses.

## Acceptance ledger

All deelegated SXR (R˘e}=I}1%Y§ÅπêÅMÅ±•ŸîµçÖπÖ…‰Å…Ω›ÃËÄ®©U9YI%%®®∏Å9ºÅ±•ŸîÅ…’∏Å•ÃÅÖ’—°Ω…•Èïê∏Å±ÖúµΩôòΩΩ∏Åÿ»ÅÕçïπÖ…•ΩÃ∞Åç°ïç≠’¡}…ïÖ∞∞Å©Ω’…πÖ∞Å•ëïπ—•—‰∞Å…Ö‹Å1§Åπ’µâï…Ã∞ÅÖπêÅÕÖôï—‰Åç±Ö•µÃÅ…ïµÖ•∏ÅU9YI%%ÅôΩ»Å…ï±ïÖÕîÅïŸ•ëïπçî∏((ååÅ	±Ωç≠•πúÅô•πë•πùÃ((¥Ä®© ¥ƒÅ	1=-H®®ËÅ°Ö…πïÕÃÅçÖπë•ëÖ—îÅµ•ÕµÖ—ç†∏Å	’•±ëï»Åµ’Õ–ÅçΩµµ•–Å—°îÅï·Öç–Å°Ö…πïÕÕïÃ∞Åâ•πêÅM!Ωë•ùïÕ–∞Å—°ï∏Å…ïŸ•ï‹ÅÖùÖ•∏∏((¥Ä®© ˚"$ƒÙ4¥U"¢£¢5Ö"ˆff∆ñÊR6V∆b◊FW7Bfñ«2◊V«Fó∆R∆ˆ˜ˆ66óGí76W'FñˆÁ2ÊB7&6ÜW2B∆ñÊR3#ìbvóFÇ÷ó76ñÊrî66óGï&W7V«BÊ5˜vñÊF˜uˆ÷WF‚'Vñ∆FW"◊W7B&Wó"ÊB&˜fRWÜóBvóFÜ˜WBG&6V&6≤‡†£ÎH
äí»ì–“—Tääéàê»Ÿ[ã]\›[YY›]]NŸX»[ôÿ\»\õZ[ò]Y⁄]^]MÀàùZ[\à]\›ô[[›ôHHŸôõ[ôH[ô»[ôô\ù[à»^]⁄]Ÿ[ó›\›‹\‹ŸYùYKÇÇãH
äíì–“—TääéàòX›[›\»\‹Ÿ\ù[€ú»[ôÿ‹ö\Yô\‹€ô\ú»ÿ[à€€\H⁄]H‹õ€ô»ôZ]ö[‹ãàùZ[\à]\›YYX[ö[ôŸù[ôYÿ]]ôH\‹Ÿ\ù»[ôXô[[Xö[ô»€õKÇÇà»»⁄X⁄‹»[ôô^X›[€Çî\ôõ‹õYYà€›\òŸKX\€€\[K’‘àŸ[ã]\›ê»Ÿ[ã]\›][\ô[X\ŸK]ôYHö[ô[ô»⁄X⁄Ààô]\ŸY\õ›ò[]öY[òŸNàõ€ôKàõ»õŸX›[€ã‹õ›öY\àÿ[ÿ\»XYKàùZ[\àô\Z\ú»[ô€€[Z]»H^X›\õô\‹Ÿ\À[à‹ò⁄\›ò]‹àõ›]\»Hô]»ÿ[ôY]H»[à[ô\[ô[ùô]öY]ÀÇÇîõÿôH[ÿÿ][€éàŒó\Ÿ\ú◊XZ[óò€€ôöY◊‹[ò€ŸW€‹ö‹‹XŸQ]Wù[ú◊ÕÕôMNLôLåXó>smart-execution-reliability-01-45d7d5f19c3b\\˘¡…ΩâîµôëÖî—î»’ê≈Ä. 
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
