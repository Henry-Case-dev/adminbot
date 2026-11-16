# SMART P0 checkup — S1–S6, S8: implementation evidence

- Epic: `smart-corrective-01` (production trace 2026-11-16, PERMsoc checkup + owner reply).
- Branch: `fix/p0-smart-checkup`; candidate `98338292`; lane parent `b9f5ec88`
  (S7 corrective: partial request/empty evidence/grant ordering/addressed grant),
  S7 base `612e6518`.
- Worktree: `WorkspaceData/worktrees/c742e4de9e92c489/smart-corrective-22cad8b9bca2-335c2570`.
- Scope: S1–S6 + S8 only. `services/direct_chat_service.py` (S7) and
  `services/llm_client.py` (transport) are not modified by this candidate.
  Models/providers/OpenCode/saved owner prompts are unchanged; no new flags.

## Observable contract implemented

1. **S1 LLMError classification** (`services/tool_loop.py`): existing classes
   `LLMTimeoutError`/`LLMTransportError`/`LLMServerError`/`LLMRateLimitError`
   plus `cause_class`/`status`; deterministic 4xx of the tools mode
   (400/404/422, excluding context overflow) is the only `tools_unavailable`
   case. Round-0 transient without evidence keeps the FR-15 plain fallback as a
   last resort but the result is `research_state.status=not_executed` with
   cause `llm_error`; with evidence (plan steps) it finalizes on data. Late
   or round-1 transient with a structurally available continuation and new
   journal entries appends the existing `_continuation_directive` and
   continues (signature/progress gate, no fixed quota). No transport retry
   duplication; no tool re-dispatch. Empty final with non-empty
   `tool_results` → `_finish_degraded("empty_final")`; without evidence the
   FR-14/65.1 `LLMBadResponseError` remains.
2. **S2/S3 honesty** (`services/checkup_service.py`): research note is driven
   by `research_status != complete` (deterministic `structured_partial` already
   carries its cause); `loop_ready=False` records
   `research_status=not_executed` / `research_cause=tools_unavailable`, and a
   requested-but-unusable runtime (`tool_runtime` dict) also marks the report.
   A legacy call without any tool runtime is not reported as complete, but does
   not get a false partial note.
3. **S5 two axes** (`handlers/checkup.py`, `web/api/routes.py`):
   `research_verdict` ∈ complete|partial|premature_stop|not_executed|unknown
   (`unknown` is never complete). Delivered reports emit `outcome=delivery` and
   `status=report_sent` only for complete; `report_sent_partial` /
   `report_sent_unresearched` are WARN. Self-diag delivery coverage counts all
   three statuses; `report_sent_partial`/`unresearched` are partial in stats.
4. **S6/S8 Markdown** (`handlers/checkup.py`, `services/telegram_send.py`,
   `services/checkup_prompts.py`): report goes through the existing
   `send_rich_message(..., content_format="markdown")` with
   `ReplyParameters(message_id=...)`; failure/absence/32000-char transport
   limit falls back to the existing plain chunking (`delivery_channel=plain_raw`,
   no truncation). No MarkdownV2, no converter for other consumers, ledger and
   `bot_replies` keep the original report. Addendum allows light Markdown,
   forbids tables/HTML; owner canon and prompt registry untouched.

## Checks (candidate `98338292`, project venv aiogram 3.31.0)

- Focused checkup/tool_loop/routes/S7/factcheck set (19 files):
  **571 passed, 0 failed** — includes `tests/test_smart_p0_checkup.py` (26
  tests: S1 classification/continuation, S2/S3 note/not_executed, S5 verdict
  and event levels/coverage, S6 rich/plain/limit/ledger, A/F handler runs) and
  the S7 reply suite (C/D: no SILENT, `read_source_code` with deployed SHA,
  `L2=None` → partial).
- Neighborhood (Direct/info/summary/self-diag/prompt/registry/cover):
  **476 passed, 1 failed** — `test_outgoing_guard_round1022::
  test_every_send_point_is_registered_or_allowlisted` fails identically on
  `b9f5ec88` and on `612e6518` (`handlers/meme_command.py` is not in
  `SEND_POINTS`/`SEND_ALLOWLIST`); pre-existing, not caused by this slice.
- Routes byte-freeze re-pinned consciously (`ROUTES_SHA256_F11` →
  `f87e0d8e…544a3a`, Δ routes = 0) per L-F11S-1, because S5 changes the
  existing self-diagnosis projection.
- Mutation checks at candidate tip (each fails its target test):
  1. `_is_transient_llm_error → False`: round-1 recovery and round-0
     plan-evidence finalization fail.
  2. research note reverted to `if not loop_result.degraded`: degraded
     LLM-finalize partial loses its note.
  3. `RESEARCH_VERDICT_PARTIAL → report_sent`: delivery-axis mapping fails.
- RED on the lane parent `b9f5ec88`: new suite import error
  (`RESEARCH_NOT_EXECUTED` absent) + 3 behavioral failures (empty final with
  evidence expects degradation; checkup partial note absent). Recorded before
  cleanup of the detached base-check worktree.
- Intermediate full-suite run (started before `b9f5ec88` was merged and before
  the candidate commit, 21,398 passed / 124 failed / 25 errors) is **not**
  candidate-bound and is not used as evidence; the UI/e2e failures it exposed
  were not triaged as part of this slice.

## Honest limitations

- Rich `sendRichMessage` delivery is verified at the handler/wrapper boundary
  (real `InputRichMessage`, real sanitize/reply parameters, real fallback),
  not against live Telegram/Bot API 10.1+; a live post-deploy check is required.
- Production self-diagnosis rows with the new statuses were not observed live;
  web-route behavior is proven on synthetic rows and existing contract tests.
- `research_verdict` classifies `premature_stop` from structural telemetry
  (cause `continuation_not_taken`/`no_progress` or available continuation), not
  from semantic reading of the report.
- Full-suite pre-existing failures unrelated to this slice were not repaired
  (BACKLOG_ONLY): `test_104_backend_additions`, `test_cfg03_param_audit`,
  `test_chat_settings_seed_round1019`, `test_evol018_prompt_audit`,
  `test_help_ui_round1020`, `test_prompt_field_audit` — reproduced on
  `b9f5ec88`; UI/YouTube e2e failures are environment-bound.
- No deploy, no production writes, no VERIFIED claim. Reviewer decision pending.

## Cleanup

- Detached base-check worktree `…-63c8b1a0` (612e6518) and `…-a81eee2f`
  (b9f5ec88) removed with `git worktree remove` (no force) after use; the
  temporary mutation backups under `%TEMP%\opencode` were deleted.
- Full-suite side effects in `plans/features/evol/audit/evidence/*` (screenshot
  regeneration) were reverted; working tree is clean.
