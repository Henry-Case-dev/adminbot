# Review closure-train. Verdict: Approved.

Candidate: code 3b1c4ba9a994fa29dd7d2d98ae6068276f8a3ddf, docs 87b5f0e48eae4a704f756e73d25ba5b1d8373348,
base c134f93d (2.58.195, released). Branch fix/p0im-closure-train.
Production code was not modified; no deploy. All Reviewer servers/browsers were
stopped, the disposable probe run was closed, the temporary baseline worktree was
removed, and the candidate worktree is clean (git status --porcelain is empty).
web/api/speech.py SHA256 after the mutation check:
004AC5DA28BDC9ECA063FE4A565351744B211A577A687CC2DA905E1785F4D811.

Implementation (paths actually inspected): _inspector_correlation_payload plus the
early return in _inspector_payload and get_inspector(correlation_id)
(web/api/speech.py); provider_calls(chat_id=...) filtering before the limit and
PROVIDER_CALL_MAX=24 (services/prompt_composer.py); _llm_identity /
_prompt_identity / _image_format and the image "api" facts written in
_consider_once (services/meme_initiative.py); merge_terminal_facts and
release_manual_priority(job_id=...) (handlers/meme_command.py); the image_module
gate, image_provider and heartbeat projection (services/initiative_diagnostics.py);
_full_text_evidence (web/api/initiative_publications.py); iniOpenInspector,
setSpeechInspectorMode, loadSpeechSection, initiativeRecentEvents,
iniHeartbeatViewOf, iniImageProviderViewOf (web/app.js); and the template guards
!speechInspector.requested_correlation_id, data-ini-event-mode,
data-meme-diag-heartbeat, data-meme-diag-image-provider,
data-ini-step-full-text[-missing] (web/index.html).

Test validity (assertions read, not only green): the correlation tests assert the
absence of the whole current-build key set (preview, sent, core, layers, style,
hierarchy, skip_reasons, conflicts_detail, sent_note, trace_coverage), absence of
a marker string taken from the real _preview_manifest, an honest not_recorded note
without the word "предпросмотр", masking of sk-live-..., absence of foreign-chat
text, the "процесс"/no-"на чат" retention wording, and real eviction after 25
foreign calls. PB-LLM tests assert identity/sha12/Image API facts in the durable
detail and the absence of model output and prompt texts in the journal dump.
AC-MATRIX-FAIL asserts one attempt, terminal failed, empty_content, no publish
stage and no sender call. S6 asserts the gate present with layer=global in ON and
OFF, two chats, and heartbeat taken from _initiative_observer_last_tick.

Independent challenge (executed, not restated from Builder): probe on this
candidate with an input the Builder did not use - the same correlation id recorded
only in a foreign chat. Authorized admin of -100500: the miss returns
not_recorded, empty exact, no forbidden keys, no current-build marker, no foreign
text; the own id returns only its ring record, secret masked, no foreign text; a
non-admin gets 403; ordinary mode still returns preview/hierarchy/skip_reasons; 25
foreign calls evict the own record (ring_limit 24, ring_hits 0). Mutation: adding
back "preview" to the correlation payload turned 4 tests red
(test_inspector_correlation_filter_returns_the_exact_meme_call,
test_inspector_correlation_miss_is_not_a_preview,
test_inspector_correlation_foreign_chat_returns_no_text,
test_ring_is_process_wide_not_per_chat); the original bytes were restored (SHA
above) and the same 6 tests went green again.

## Checks executed on this candidate

| Check | Result |
|---|---|
| pytest tests/test_speech_inspector_exact.py | 23 passed |
| pytest six remaining files (evol014, publications, diagnostics, s6, s5 marker, binding-delivery) | 181 passed |
| same 7 files combined (Builder claim 204) | 204 = 23 + 181 |
| 5 bound AC-MATRIX-FAIL checks + test_probability_one_is_reported_as_no_draw | 6 passed |
| node tests/js/initiative_ui_rework_test.js / p0im_ov_honesty_test.js | INITIATIVE-UI-OK / P0IM-OV-HONESTY-OK |
| python tests/ui_inspector_exact_e2e.py (real index.html/app.js, 7 viewports) | checks=142, failures=0 |
| python tests/ui_meme_ui_fields_e2e.py | failures=0 |
| python tests/ui_initiative_rework_e2e.py | failures=2, identical to baseline c134f93d run in a separate worktree (same two "Исходный из кода / журнал недоступен" at 1536 and 390) |
| pytest tests/test_soul1_w6_speech_ui.py (ordinary Inspector contour) | 23 passed |
| Browser Use: real Chrome on the candidate web/ served over HTTP (existing rework-e2e API stubs) | app mounted, 5 tabs, overview with mechanism cards and event rows rendered |

## Ledger on 3b1c4ba9

VERIFIED:
- P0IM-PB-ACCESS. Correlation mode returns only the ring record or honest
  not_recorded; no preview/hierarchy/skip_reasons/conflicts/sent; no current-build
  text; on a miss the badge/note say the full text is not stored/found, not
  "preview"; preview switching is forbidden for a requested correlation; RBAC and
  masking unchanged; retention is stated as 24 process-wide records.
- P0IM-PB-LLM. Identity (provider/model, slot null + slot_not_used, or the honest
  custom_step_hook reason), prompt source/revision/sha12, Image API status/format/
  bytes, prompt_sha12 - only in the stage detail; no messages/summary/joke/prompt
  text in the durable journal; ring miss and historical rows are honest.
- P0IM-PB-MANUAL. priority_marker (ok/until) is shown from the considered row; the
  release fact is merged into the SAME terminal row (no second row/attempt), a
  repeated release writes nothing and returns false, marker TTL/addressing logic
  and the finally-call on every terminal outcome are unchanged; historical rows
  say release_not_recorded.
- P0IM-OV-LIST. manual/auto is taken only from attempt_mode of the terminal row;
  the joke stage key "mode" (length budget) is never used; a historical row says
  "способ не записан"; the change is in app.js/index.html only.
- P0IM-S6-EFFECTIVE. image_module is always present with layer=global and the
  enabled value from the existing image_dependency; image_provider and
  heartbeat_ok/heartbeat are projections of existing computations; both chats are
  exercised; no new panel - rows in the existing technical panel.
- P0IM-AC-MATRIX-FAIL. Two new real tests (provider failure after LLM A/B; ok=True
  with content=None) plus five pre-existing bound checks pass.
- P0IM-AC-NODUP. Diff vs c134f93d is 7 product files + tests/evidence: no new
  tables/columns/migrations, no new flags/settings/prompts/models/endpoints, no
  new scheduler, task, second pipeline or logical hardcode; hold registry, spool
  and schema are untouched.
- P0IM-AC-MATRIX-CONFIG. No new acceptance flags; behaviour is unconditional; both
  image_module ON and OFF are asserted; test_probability_one_is_reported_as_no_draw
  and the silent/no-draw honesty rows in the diagnostics/publications suites pass;
  no fabrication of manual/auto or of image availability.
- P0IM-AC-MATRIX-RBAC. Probe: 403 for a non-admin with correlation_id; secrets in
  the ring are masked in exact and in the detail payload; another chat gets neither
  rows nor text; the competing-holders aggregator test still passes.

2.58.195 rows that still apply unchanged (no code path of theirs was touched; their
files pass: 61 evol014 / 40 publications / 44 diagnostics): ID-FINISH, ID-CONC,
PB-VOCAB, PB-COUNT, PB-STEP, BAN-CONFLATE.

## Findings

- Blocking: none. Both PB-ACCESS blockers of review-931945b7 are closed by
  observed evidence, not by Builder prose.
- BACKLOG_ONLY (not blocking): the retention/note strings say "последние 24
  записей процесса" instead of "24 записи" - cosmetic wording in two user-visible
  strings (web/api/speech.py INSPECTOR_RETENTION and the correlation last_run_note).
- BACKLOG_ONLY (not blocking, pre-existing): ui_initiative_rework_e2e has 2 failures
  at 1536 and 390 about the meme settings source after override removal; reproduced
  identically on c134f93d, so it is not caused by this candidate.
- BACKLOG_ONLY (carried from Builder, agreed): the overview receives analytics
  attempts in a bounded 20-row window, so a very long attempt series can honestly
  show "способ не записан" instead of manual/auto.

## Residual limitations (honest)

1. The provider-call ring is ONE process-wide structure: 24 records shared by all
   chats, no per-chat ring. Another chat's call can evict this chat's record before
   its "own" 24. UI/API now say exactly this; no new store was created.
2. Full prompt text is never in the durable journal. Historical rows and evicted
   records are shown as full_text_not_recorded / not_recorded.
3. Visual coverage: the closure-train surfaces were verified at API + view-model
   level (real app.js functions and asserted template anchors) and the whole
   Inspector/Initiative UI was exercised by the three Playwright e2e runs on this
   candidate. In Browser Use the candidate's real Initiative page rendered, but the
   existing e2e fixtures do not carry full_text/heartbeat/image_provider/attempt_mode
   data, so the correlation-mode and new meta rows were not re-rendered in a
   browser; this is a fixture gap, not a proven defect.
4. Live checks remain for DevOps on the deployed candidate: OV-SAMPLE (real sample
   of both chats), PB-FILTERS (publication filters on live data), AC-SETTINGS
   (effective settings/factory state in production) and AC-DONE. Nothing here was
   claimed as live-verified.

## Next action

Orchestrator: this candidate is approved for the closure train; hand
3b1c4ba9/87b5f0e4 to DevOps for a normal release (per PET_PROJECT the owner's
standing consent applies) and run the four live rows above against the deployed
artifact. This review artifact is written in the candidate worktree as an
untracked docs file - PM/Orchestrator should commit it with the closure docs.
Housekeeping: probe run
WorkspaceData/runs/.../probe-38df484ade closed, temporary c134f93d worktree for
the baseline e2e comparison removed, all review servers and browser tabs closed;
the candidate worktree stays for DevOps.
