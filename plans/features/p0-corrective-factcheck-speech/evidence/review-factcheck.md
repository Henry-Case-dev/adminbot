# REV-P0-FACTCHECK - independent factcheck review

- Lane: `REV-P0-FACTCHECK` (read-only review; only this file written)
- Candidate: `b93f1557` (`fix(p0b): factcheck per-part queries, verifiable evidence, retrieval outcome classes, image OCR`)
- Base: `f26b5209`; scoped files have no uncommitted changes (`git status --porcelain -- <factcheck files>` empty)
- Source: `source-2026-10-24.md` §3.2-§3.7, §9 (FC-01..FC-09)
- Verdict: **Needs Fixes** (not approved; not deployable as-is)
- Date: 2026-10-24 (local +12)

## 1. Candidate binding and checks performed

- `git show --stat b93f1557`: 8 files, all factcheck/renderer/tests/evidence; no Expression files.
- `git show 09f56517 --stat`: Expression files only; no overlap with b93f1557; no foreign edit reverted.
- Focused suite: `py -3 -m pytest -q -k "factcheck or search_aggregator or temporal"` -> **517 passed**, 31.31s.
- New file: `tests/test_factcheck_p0_fc.py` -> **16 passed**, 3.46s.
- No real Tavily/Exa/DDG/LLM/Vision calls were made in this lane. All observations below are offline/reproducible on the candidate.
- Map rows `FC-01..FC-09` are still `PENDING`; `candidate_commit` is empty. This is expected before PM/Reviewer finalisation, but the map cannot be used as proof yet.

## 2. Acceptance ledger (FC-01..FC-09)

| ID | Status | What is actually proven / gap |
|---|---|---|
| FC-01 | **FAIL (partial)** | Composite in the test gets 2-3 queries, but a first sentence containing both a number and a year consumes all 3 queries; later sentences get no query at all. See F4. |
| FC-02 | PASS (offline) | Morphology keys pass the paraphrase case and reject the one-name off-topic case (`TestFC02Morphology`). |
| FC-03 | PASS (offline) | Broken primary fetch keeps secondary URL refs (`TestFC03SecondarySources`). |
| FC-04 | **FAIL** | The test calls `search_relevant` without `timeout_budget`; the product path always passes it. With a budget, Exa and DDG raise `TypeError` before any HTTP call and Tavily failure ends in `AllSearchEnginesFailedException`. See F1. |
| FC-05 | PASS (logic) / weak test | `classify_retrieval` maps budget to `deadline_exceeded`; the headline is rendered. But the test builds the outcome and verdict by hand and does not assert the real retrieval-to-class path. |
| FC-06 | **FAIL** | The planner no longer puts URL-less refs into `EvidenceMap`, but `check_claim_envelope` falls back to `evidence_rows_from_results(search_text)` when refs are empty and re-creates URL-less evidence rows. The production symptom (`url=null`) is not eliminated on the main envelope path. See F2. |
| FC-07 | PASS (renderer) / aggregate unchanged | Parts without refs are now visible; `_aggregate_factual_verdict` is pre-existing. The new test constructs `CheckedVerdict` by hand, not through the service. |
| FC-08 | PASS (main path) / honesty edge | OCR from existing `mca_vision` reaches claim/planning/analyst; caption is kept. A ready analysis with no OCR text is reported as "not analyzed" (F6). |
| FC-09 | **FAIL** | Only the legacy `factcheck` cache key was bumped (`fcv4`). The main envelope cache key still uses `TEMPORAL_PIPELINE_VERSION = "tf2"` (unchanged), so a pre-fix cached verdict for the same text-only claim is served for up to 6h/720h. The test only checks `_v2_cache_input`. See F3. |

## 3. Blocking findings

### F1 (BLOCKER) - provider cascade is broken in the real factcheck path

- Requirement: §3.6 and §9 FC-04 (one provider down -> next returns result; technical failure is not absence of facts).
- Location: `services/search_aggregator.py:256-257` passes `timeout_budget=` to every engine, but `_search_exa` (:342) and `_search_ddg` (:379) accept only `query`.
- Repro (candidate, offline):
  - `agg.search_relevant(..., timeout_budget=3.0)` with Tavily failing and a one-argument Exa fake:
    `AllSearchEnginesFailedException`; log: `provider=exa ... unexpected keyword argument 'timeout_budget'`; `provider=ddg ... unexpected keyword argument 'timeout_budget'`.
  - `run_retrieval` with the same setup: `attempted=3 used=0 refs=0 provider_failures=3` -> class `search_failed`.
  - The same call **without** `timeout_budget` reaches Exa normally.
- User impact: after a Tavily outage/empty result (or with no Tavily key), Exa still has not been contacted, and the user is told "search services unavailable". The FC-04 fallback is absent exactly where it is needed.
- Minimal correction: pass `timeout_budget` only to engines that accept it (or add the parameter and per-engine timeout to Exa/DDG); add a regression test through `search_relevant(..., timeout_budget=...)` with real one-argument engine signatures.
- Recheck: same repro must return the Exa result, `used>=1`, `refs>=1`, class `ok`.

### F2 (BLOCKER) - URL-less rows are re-admitted as evidence by the envelope fallback

- Requirement: §3.3/§3.6/§3.7: a row without a URL is not proof; "results found but processing failed" must not become a content verdict.
- Location: `services/factcheck_service.py:795-806` (`retrieval_refs` empty -> `evidence_rows_from_results(results)`), and `factcheck_service.py:830` (`classify_retrieval` only when `not evidence`).
- Repro (candidate, offline): a retrieval outcome with `refs=0`, non-empty `search_text` containing the production-style off-topic block:
  - `classify_retrieval(outcome)` -> `processing_failed`;
  - the service's `else` branch is `evidence_rows_from_results(search_text)`; reproduced directly: 1 row `ev-1`, `url=None`;
  - therefore `evidence` is non-empty and `retrieval_state` becomes `ok`, not `processing_failed`.
- User impact: the durable evidence can again contain `url=null` rows (the production `tfr-6e0ab2dbcc784b57` symptom), the analyst may treat them as evidence, and the new technical class/headline is bypassed.
- Minimal correction: when the run came from the web retrieval (`retrieval is not None`) and `retrieval_refs` is empty, do not rebuild evidence from raw `search_text`; filter blocks without a URL (or set `evidence=()` so `processing_failed` applies). Cover this through `check_claim_envelope`, not only through `verdict_from_payload`.
- Recheck: the same block must yield 0 evidence rows and `processing_failed` (or an explicit "no citable links" technical result), never `ev-N url=None` evidence.

### F3 (BLOCKER) - FC-09 not satisfied for the main temporal cache

- Requirement: §9 FC-09: a cached old verdict must not hide the corrected check.
- Location: `services/temporal_factcheck.py:62` (`TEMPORAL_PIPELINE_VERSION = "tf2"`, unchanged by the candidate); `build_temporal_cache_key`/`cache_components` use it; the legacy bump is only `services/factcheck_orchestrator.py:694-706`.
- User impact: for a text-only message already checked before the fix, `factcheck_temporal` returns the old verdict from cache (volatile 6h, stable up to 720h) and never executes the new per-part/class logic. The new OCR text changes the key only for image posts.
- Minimal correction: bump `TEMPORAL_PIPELINE_VERSION` (e.g. `tf3`) or include `fcv4`/planner version in `cache_components`; add a test that an old `factcheck_temporal` entry is not served after the change.
- Recheck: same envelope built on the candidate gets a different key from the pre-fix value; cached old text is not returned.

## 4. Related findings (not the first blocker, but should be fixed in the same pass)

### F4 (RELATED) - per-part query budget is consumed by refinements of the first part

- Location: `services/factcheck_planner.py:322-343` (for each unit: entity query, then numeric, then years; the loop stops at 3).
- Repro: claim `"V build 283365 on macOS 13.1.0 (2024) added AI agents. Telegram connected Claude. Durov killed Claude Code."` produces 3 queries all about part 1 (`entity_check`, `numeric_verification`, `temporal_context`); parts 2 and 3 get no query. The test claim places the number in sentence 2, so it does not see this.
- Impact: the claim "query for each part" is overstated; a realistic version headline can starve the other claims, recreating the original one-claim retrieval failure.
- Minimal correction: first pass one entity query per unit (up to 3), second pass numeric/year refinements with the remaining budget; add the above counterexample.
- Recheck: 3 units -> at least one query per unit when the budget is 3.

### F5 (RELATED) - server parts can contradict a positive top verdict

- Location: `services/factcheck_service.py:306` (`_server_parts` always `insufficient_evidence`) and its use in `check_claim_envelope` when the model returned no parts.
- Repro: `verdict_from_payload({"factual_verdict":"supported", ...})` + `_server_parts` on a 3-sentence claim -> rendered `**Supported**` followed by three `data is insufficient` lines.
- Impact: the user sees a confident headline and a per-part breakdown that denies every part; this is the "unsupported fact" pattern §3.7 prohibits.
- Minimal correction: do not synthesize parts that contradict a positive top, or aggregate the synthesized parts into the top and show them as an explicitly unverified decomposition; add a test.
- Recheck: positive top + synthesized parts never renders "supported" with all parts "insufficient".

### F6 (RELATED) - `image_not_analyzed` is not honest for a ready analysis with no OCR text

- Location: `services/factcheck_service.py:232-234` (any empty `untrusted_ocr_texts` -> `image_not_analyzed=True`).
- Repro: `render_media_context_async` returns `{"knowledge_time": ..., "untrusted_ocr_texts": []}` for an analyzed image with no text; `load_claim_media` reports "recognition is not ready" even though it is ready and found no text.
- Impact: the user is told the check is incomplete when it is complete; this is a false statement about the check.
- Minimal correction: distinguish "analysis ready" (`knowledge_time`/absence of `PENDING_LINE`) from "analysis not ready"; for ready-no-text set `image_analyzed=True, ocr_chars=0` and no "not ready" notice; add the test case.
- Recheck: ready/no-text -> no `image_not_analyzed`; pending -> `image_not_analyzed=True`.

## 5. Evidence/test weaknesses (must be corrected with the code, not accepted as green)

- `tests/test_factcheck_p0_fc.py:267-282` (FC-04) does not pass `timeout_budget`, so it tests a path the product does not use. This is why 517 green tests coexist with F1.
- FC-05 (`:288-319`) constructs `RetrievalOutcome` and `CheckedVerdict` by hand; it does not prove the real retrieval -> classify -> headline chain.
- FC-06 (`:322-352`) constructs the payload by hand and calls `verdict_from_payload`; it does not exercise `check_claim_envelope`'s evidence fallback (F2).
- FC-07 (`:365-387`) constructs `CheckedVerdict` by hand; it proves the renderer, not the service's mixed parts.
- FC-09 (`:458-497`) checks only the legacy key; the temporal key (F3) is untested.
- `evidence/factcheck.md:85` (FC-04 PASS), `:87` (FC-06 PASS), `:90` (FC-09 PASS) and the "such a set does not enter EvidenceMap" statement are not supported by the candidate on the real service path.
- `evidence/factcheck.md:75` "517 passed" is reproduced; `factcheck.md:56` "16 tests" is reproduced.

## 6. Can it go to the trip / deploy?

**No.** Three independent blocking defects remain (F1, F2, F3); two of them break explicit §9 scenarios (FC-04, FC-06) and one breaks FC-09 on the main cache path. A controlled deployment would ship a factcheck that (a) cannot use Exa/DDG when Tavily fails, (b) can still treat URL-less rows as evidence, and (c) can serve the old verdict from the temporal cache.

## 7. What must be checked after the fixes

- Real Tavily failure -> Exa result (FC-04), with `provider_failures` and `used/refs` numbers.
- Real composite post with a version/year in the first sentence -> per-part queries and per-part verdicts (FC-01).
- Real envelope run with a URL-less search result -> 0 citable evidence and `processing_failed` headline (FC-06).
- Old `factcheck_temporal` entry -> new check runs (FC-09).
- Real Vision on an image post (OCR text in claim; ready-no-text notice) (FC-08).
- Real LLM analyst/verbalizer on a partially confirmed post -> mixed headline + visible parts (FC-07).
- FC-05 budget exhaustion on the real path -> `deadline_exceeded` headline, not "no facts".

The `live_required: true` map rows (FC-01..FC-05, FC-08) remain pending; after the code fixes they need a post-deploy canary on the real bot and a real provider/LLM/Vision run. FC-06/07/09 can be closed by the corrected offline integration tests, but F2/F3 must be exercised through the service/cache path.

## 8. Final verdict

`Needs Fixes` for `b93f1557`. The diff scope and the main OCR/per-part direction are sound; the candidate is not acceptable while F1-F3 are open and FC-04/FC-06/FC-09 remain FAILED.
