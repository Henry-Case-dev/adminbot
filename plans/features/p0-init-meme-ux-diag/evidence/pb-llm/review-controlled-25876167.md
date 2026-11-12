# Review: controlled P0IM-PB-LLM proof on 2.58.197. Verdict: Approved (technical part).

Candidate: test commit ee2ddeb5, docs 62708035, base 2587616759de31283585ffc105c91e7193c2e89e
(release 2.58.197, deployed). Branch fix/p0im-pbllm-proof.
Evidence reviewed: plans/features/p0-init-meme-ux-diag/evidence/pb-llm/controlled-25876167.md
(sha256 2b8c48e79f274bac6bfeff23a0ce2f84c6a1109ecddd9d866699dc3a07458612,
independent recomputation matches the value in the handoff).
No deploy, no code/settings/production change. Worktree clean; Reviewer probe run closed.

## Implementation (what was actually read and run)

git diff 25876167..ee2ddeb5 -- services web handlers is empty (0 lines); the whole test
commit is one new test in tests/test_evol014_meme_initiative.py (+187). The docs commit
adds only the evidence file. So the deployed 2.58.197 code is exactly the code exercised
here - no product change, nothing to re-approve in the backend.

Path inspected: meme.consider_chat -> _consider_once with a real LLMClient (only
client._post is patched at the HTTP boundary), real _default_summarize/_default_joke,
real llm_client._record_provider_call -> prompt_composer.record_provider_call,
real temp-SQLite attempt journal, real publication claim/delivery hooks. Image and
Telegram boundaries are the pre-existing pipeline hooks (_FormatProvider, sender).
The ring is NOT filled by hand: the test only reads composer.provider_calls, exactly as
Inspector and the attempt card read it. _prompt_identity was re-read: it returns only
block/source/revision/sha12 - no prompt text can reach the durable detail structurally.

## Test validity (assertions read, not names)

- Identity: provider "llm.example.invalid" and model "chat-model" are the real values of
  the client that made the call (LLMClient._provider_label derives the host from the base
  URL; verified directly), slot null with slot_reason "slot_not_used"; prompt block/source/
  revision and a 12-char sha12; summary and joke blocks differ.
- Cross-link, not a fixture echo: summary.prompt.sha12 equals sha256 of the ring record's
  actual system text; joke.prompt.sha12 equals sha256 of the J-directive built with the
  recorded joke limit, and the ring system actually starts with that directive. A stale or
  fabricated identity would break this.
- Durable absence: the dump of all journal rows contains neither the fake summary nor the
  fake joke, nor the factory joke-prompt fragment, nor the image-prompt fragment. This is
  non-vacuous: those exact strings were produced by the patched transport/provider in this
  run, so any write path would be caught. The summary system prompt is excluded
  structurally by _prompt_identity (no text fields), which I re-read rather than trusting
  a string search.
- Ring/Inspector: exactly two ring records for this chat, keyed {job}#meme_summary and
  {job}#meme_joke, module initiative, step correct, model/provider/status ok;
  speech_api._inspector_correlation_payload returns is_actual=True with the recorded
  messages_checksum text for both ids; pubapi._full_text_evidence marks both steps
  recorded. The same ring is what the attempt card links to - no second store.
- One attempt: pubapi._meme_attempts_grouped(rows) yields one attempt, outcome published,
  delivered true, message_id 777, generated true; exactly one publish row whose detail
  carries delivery sent and tg_message_id 777.
- No extra calls: sent_bodies == 2, provider.calls == 1, and after reading the ring,
  Inspector, full_text and read-model the ring still holds exactly two records.

## Independent sensitivity check

Appended a no-op record_provider_call at the end of services/prompt_composer.py (module
attribute shadowing, no call-site changes), ran only the new test: FAILED with
"assert 0 == 2 / len([])" at the ring assertion - i.e. the ring/correlation part is the
load-bearing evidence, not a tautology. Bytes restored (services/prompt_composer.py
SHA256 1BF4D30226998907A59645FB349A3CE3534685B59E75B51AD0306D8A9A48D90B) and the test
went green again; worktree clean.

## Counts (run on ee2ddeb5)

| Command | Result |
|---|---|
| pytest tests/test_evol014_meme_initiative.py | 62 passed |
| pytest tests/test_speech_inspector_exact.py + test_initiative_publications_api.py | 63 passed (23 + 40) |
| combined | 125 passed, matching the Builder claim |

## PB-LLM coverage (two duplicate rows items[23]/add[44]) - technical part VERIFIED

1. provider/model from the same client that made the call; slot null with the honest reason.
2. prompt source/revision/sha12, cross-checked against the actually sent system text.
3. Image API status/format/bytes/prompt_sha12 in the stage facts.
4. No full summary/joke/system/image-prompt text in the durable journal.
5. Full text is available only through the existing composer ring and the existing
   Inspector correlation mode, and the attempt card points at exactly those records.
6. One grouped attempt links the stage rows, the delivery and the terminal publish row.
7. No extra LLM/Image calls from identity or diagnostics.

## Honest limits (as stated by Builder, confirmed by me)

No network, no real provider, no Telegram, no production DB; image is a pipeline hook;
source="factory" reflects the test environment without chat/global overrides; the
production provider label and the natural production LLM event are NOT proven by this run.
Per the owner decision the natural production event is a separate non-blocking observation
(owner_live_check), not a release gate: it must be recorded as such, not as VERIFIED.

## Residual limitations

- The literal dump check covers the model responses and the joke/image prompt fragments;
  the summary system prompt is excluded structurally by _prompt_identity rather than by a
  string search in this test.
- The ring is the existing 24-record process-wide buffer; this proof is bound to the run.
- Delivery is a fake sender (tg_message_id 777 synthetic).

## Next action

PM/Orchestrator: mark the technical part of both P0IM-PB-LLM rows VERIFIED with this
artifact as evidence and record the natural production LLM event as a non-blocking
owner_live_check with the source decision. Release gate for 2.58.197 stays as is; no new
deploy is required by this review and none was performed.
