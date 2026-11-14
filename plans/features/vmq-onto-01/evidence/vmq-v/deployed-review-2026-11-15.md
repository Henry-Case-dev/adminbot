# VMQ-V / VMQ-A-01 independent deployed-candidate review

## Verdict
**Approved** for candidate-bound behavioral review. PM must bind rows as REVIEW; this artifact does not mark requirements VERIFIED.

## Exact deployed candidate
- SHA: c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
- Version: 2.58.203
- Branch and upstream: release/smart-corrective-01 / origin/release/smart-corrective-01
- `git merge-base --is-ancestor c97c06e4 origin/release/smart-corrective-01`: exit 0
- `git rev-parse origin/release/smart-corrective-01`: c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
- Manifest/release evidence: `plans/features/smart-corrective-01/release-evidence/2.58.203/deploy.md`; runtime identity and manifest agree on SHA/version/branch, dirty=false.
- Exact tree contains: `handlers/voice_transcription.py`, `services/voice_transcripts.py`, `tests/test_vmq_v_voice_writer.py`. `services/voice_transcription.py` is not present in this exact tree listing.

## Three proof pillars
- **Implementation:** exact c97 blobs inspected for `services/database.py::set_smart_message_transcript`, `services/voice_transcripts.py::resolve_voice_bundle/render_voice_block`, `services/direct_chat_service.py` voice-evidence path, handler and payload integration. The path persists transcript text/status/revision by one Telegram source row, builds adjacent source bundles with author/ref/order, and renders ready/pending/failed states into the Writer block.
- **Test validity:** read assertions in `tests/test_vmq_v_voice_writer.py`; reconstructed exact-c97 copy ran 48 passed. Assertions cover DB text/status/revision, source refs/order, cross-chat exclusion, pending/failed/restart/stale behavior, payload source/author/text, long text and retry/revision refresh. No vacuous `assert True` or empty body found. External STT is isolated at its provider boundary where mocked; this proves local integration semantics, not real provider delivery.
- **Independent challenge:** wrong expected transcript mutation failed; revision mutation (`revision = 1`) failed `test_transcript_is_version_of_single_source_ref` (`assert 1 == 2`); removing payload transcript text failed `test_ready_transcript_text_reaches_payload_block` and `test_long_transcript_is_delivered_without_silent_cut`. Mutations were confined to disposable c97 copy and restored.

## Per-row behavioral verdicts (candidate-bound REVIEW; PM binding required)
- `VMQ-A-01`: **Approved at candidate-bound review level**. Exact tree and deployed identity are bound; no real Telegram voice event or production DB delivery evidence was used, so this is not VERIFIED.
- `V-01`: **Approved at candidate-bound review level**. Same source-ref persistence and monotonic revision assertions pass; no real production voice event evidence, so not VERIFIED.
- `V-02`: **Approved at candidate-bound review level**. Adjacent two/three voice grouping, authors, order, reply/quote and cross-chat exclusion are asserted; no real production media bundle evidence, so not VERIFIED.
- `V-03`: **Approved at candidate-bound review level**. Ready transcript text/source-ref reaches Writer payload, including long text; no actual production Writer/provider delivery evidence, so not VERIFIED.
- `V-04`: **Approved at candidate-bound review level**. Pending/failed/restart/stale/retry states are asserted and honest; no real production state-transition event evidence, so not VERIFIED.

## Limitations and handoff
- No production access and no real production voice messages were used, by scope.
- Production deploy evidence reports `outbound_delivered_to_telegram=0`; therefore real Telegram voice-event and actual Writer/provider delivery claims remain absent.
- PM should bind the five rows as candidate-bound `REVIEW` based on this artifact; do not convert them to `VERIFIED` without the required real event evidence.
- Housekeeping unchanged: retained disposable c97 evidence at `C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\vmq-onto-01-3689dd92710d\temp-afd409e420`.

