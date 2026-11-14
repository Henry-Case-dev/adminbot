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
