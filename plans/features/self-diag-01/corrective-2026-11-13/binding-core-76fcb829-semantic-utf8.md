# SELF-DIAG-01 corrective — semantic evidence UTF-8 reissue (candidate `76fcb829`)

- Code+tests candidate: `76fcb82962592a8e099239cd11e6c34ff13cf407` (unchanged; no code change in this reissue).
- Base: `234776589c934024ed0e8dceba189fb9d70d3215`.
- Branch/worktree: `self-diag/corrective`.
- Prior binding: `binding-core-76fcb82962592a8e099239cd11e6c34ff13cf407.md`.
- Not deployed; not approved.

## 1. UTF-8 semantic artifacts (replace the unreadable one)

The previous `semantic-live-76fcb829.json` was written through a PowerShell
UTF-16/console path and contained mojibake. It is replaced by explicit
`encoding="utf-8"`, `ensure_ascii=False`, LF-only files, validated by reading
the bytes back, rejecting BOM and `\r`, and decoding strict UTF-8.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `plans/features/self-diag-01/corrective-2026-11-13/semantic-live-76fcb829.json` | 69616 | `a3b64d1cd3709d1c0862157b325f656ac807469072fd1a08725b733a4c2604bd` |
| `plans/features/self-diag-01/corrective-2026-11-13/semantic-live-76fcb829.md` | 6278 | `bd1631ad3ec34b5b3a3f7af4939d76cfda344a7f4f646793deabe6172986e499` |

Provider used: `nano-gpt.com` / `https://nano-gpt.com/api/v1`,
model `deepseek/deepseek-v4.1-flash`; project `.env` config, no secrets recorded.
Two series, temperature 0, `max_output_tokens=512`, 9 cases each.
This is the project's local provider, not production-equivalent.

The JSON `self_check` block contains: series count 2, cases per series 9,
positives 4, negatives 5, `utf8_valid=true`, `per_case_user_sha256` for all nine
verbatim inputs, and `flipped_cases`. Each case has a stable `case_id`, exact
`user_text`, `user_text_sha256`, `reply_context`, `user_context_sha256`,
`structured_decision` (`needed/target/sources`), `tool` (`called/name/status/
verified/path/line_range/commit/error`), `final_answer_excerpt`,
`model_response_sha256`, `timestamp_utc`, and provider/model at the top level.

`final_answer_excerpt` is the provider's actual JSON response excerpt (not
published Telegram prose); the C Writer answer is separately proven in
`ag-traces-76fcb829.json`.

## 2. Two-series result and the one flip

Both series: 4/4 positives → `needed=true`, `target=self`, real
`read_source_code` `status=ok, verified=true, path=services/checkup_service.py,
line_range=[150,175]`.

Both series: 5/5 negatives → `needed=false`, no tool call.

Honest flip: **`neg_external`** differed only in `target`:
series 1 `null` (field absent/uncaptured), series 2 `unknown`. In both series
`needed=false` and `tool.called=false`; no research outcome flipped. This is
recorded in `self_check.flipped_cases` and the Markdown `Flips:` line, not
averaged away. No other case flipped.

The exact provider error is recorded per case in `provider_error`; both series
completed with zero provider errors.

First pre-fix model pass (before candidate `76fcb829`) had two negative misses
and an unstable reply-positive; the semantic prompt guards in `76fcb829` fixed
that. This reissue re-runs the same unseen set; it is not a new phrase table.

## 3. Stage-correct review-gate documents (exact bytes)

Copied from the master docs line into the candidate branch at the same paths,
without editing contents:

| Path | Bytes | SHA-256 |
|---|---:|---|
| `plans/features/self-diag-01/requirements-map.json` | 2310736 | `be33e963fecc1320089abba5e7a49938637c03f136ea2f4a51595b0d42059d65` |
| `plans/features/self-diag-01/corrective-2026-11-13/architecture-corrective.md` | 31373 | `ad56af83680031a43fdcacbc5594546fce537fa845dc11ab5dfbf7114f589756` |
| `plans/owner_inputs/2026-11-13-selfdiag-corrective-journal-code-identity.md` | 34871 | `c796c4c92e407c33fef47a9eafb7afe9596e78f825023e7c69ecd9a62b822b9d` |

These are byte-identical to the master files (SHA-256 above), so the
requirements gate can evaluate the candidate without a missing-map/source error.

## 4. Test status (unchanged candidate)

- New corrective tests: **28 passed**, EXIT=0.
- Focused set: **330 passed**, EXIT=0.
- L1/engine cluster: **442 passed**, EXIT=0.
- P4 contract: **1 passed**, EXIT=0.
- Four old failures were individually reproduced on base `23477658` (each
  `1 failed`, EXIT=1), so they are pre-existing; P4 is now green after the
  contract update.

Interpreter: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`.

## 5. Limits

- Live-model run is a local project provider, not production route/model/context.
- The run proves semantic decision + real local read; it does not prove a
  production Telegram answer.
- Journal remains DevOps production evidence; local collector uses a journal
  subprocess fixture.
- Deploy identity/counters and production deploy are outside this candidate.

**Status: REVIEW.** Docs SHA reported after commit.
