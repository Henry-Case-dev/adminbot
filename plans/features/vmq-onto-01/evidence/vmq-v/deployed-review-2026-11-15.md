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



## Q1/Q2 release-gate decisions (2026-11-15)

### Q1 - VMQ-A-01: Needs Evidence, not VERIFIED-eligible

The artifact audit-head.md contains the required 12 sections, including sections 6, 7, and 9. It is not VERIFIED-eligible because its header still pins c816e83c / 2.58.168, while this review binds the deployed base to c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5 / 2.58.203. It does not explicitly reconcile current HEAD, active MEMORY tasks, and production configuration against c97.

Minimum correction: Architect/PM update the base/current-head pin to c97c06e4 / 2.58.203 and add an explicit c97 delta for done, in-progress, newly added MEMORY work, and production configuration. Then recheck the document. No application-code correction is indicated.

### Q2 - graph correction preferred; no fabricated live evidence

The M2-to-V edge is no longer technically necessary for the approved train. Exact ancestry confirms c97c06e4 is the deployed base of 16931216ab0015b4a3001c9947768305517e46eb. The c97-to-16931216 diff is empty for services/direct_context_composer.py and the V handler/transcript/test paths; only the shared services/database.py path changes. The deployed c97 tree contains the V implementation and test paths. This supports correcting the graph edge rather than holding M2 on unrelated future V production observation.

This is a graph correction, not a status shortcut. V-01..V-04 remain candidate-bound REVIEW until a real production voice event and Writer/provider delivery are observed. They are not VERIFIED, and this artifact does not convert them to READY_FOR_LIVE without a separately approved wait object. After correction, V rows remain independent acceptance work and must not block M2 solely through the removed edge.

### Three review pillars

- Implementation: inspected exact c97 identity and the train diff across the composer, V handler/transcript/tests, and database seam; the V/composer paths are unchanged.
- Test validity: inspected the existing V artifact assertions for revision/source-ref, grouping, payload, pending/failed/restart/stale states, and 48 exact-c97 passes. They prove local integration semantics, not production delivery.
- Independent challenge: checked the stale Q1 pin against c97 and challenged the dependency with the exact c97-to-16931216 path diff. Live delivery remains unproven; deploy evidence reports outbound_delivered_to_telegram=0.

### Release consequence

Train 16931216ab0015b4a3001c9947768305517e46eb is safe to assemble/deploy with respect to Q2 once PM/Architect records the graph correction and reruns the train gate. Q1 remains the genuine pre-deploy documentation blocker for VMQ-A-01 binding, not a runtime blocker. No production access was used. The requirements map was not edited.

## Final Q1/Q2 recheck (2026-11-15)

### Q1 - VERIFIED-eligible at document-review level

The focused recheck accepts audit-head.md section 13 as sufficient for VMQ-A-01. It binds the deployed base c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5 / 2.58.203, release branch and runtime identity; records health/version, restart/schema/DDL/rollback facts; maps current MEMORY/VMQ states; records effective production configuration; and separates done, in-progress, and added work. The historical c816e83c / 2.58.168 pin is explicitly preserved as the dated section 1-12 audit, not used as the current base. Event/fixture, no-duplicate, and DAG material is retained.

Verdict: VMQ-A-01 is VERIFIED-eligible as a document artifact. PM must bind the existing map row to VERIFIED; Reviewer did not edit the map.

### Q2 - dependency correction confirmed

The current slice graph has VMQ-M2.depends_on = [VMQ-M1, VMQ-ONTO-B]; VMQ-V is absent from the M2 dependency closure. Independent recheck of c97..16931216 found no changed files in services/voice_transcripts.py, handlers/voice_transcription.py, or services/direct_context_composer.py. Removing composer from M2.write_scope matches the approved M2 code scope and the train diff; composer remains historical VMQ-V ownership. V-01..V-04 remain independent REVIEW rows with live_required=true and are not falsely closed or converted to VERIFIED.

### Slice C corpus binding

The actual corpus JSON file hash is 4e644e52c057381aaea78d264310cd41f847b028c2c0066caa8f46170a9cafdd, matching the PM binding. The JSON records the copied DB hash e16284958208dd8def242bac3211a5003fb031a97a3f88e504394d36678f0505. The Markdown provenance text swaps these references and cites an older JSON digest; this is a documented provenance-text defect, but binding is to the actual files and their contents. The observed behavior supports structural-signal interpretation: historical, explicit-year, and relationship flows activate overview while the no-signal current-state negative does not; the report explicitly rejects a dictionary trigger. Vector KNN and live delivery remain unverified.

### Final train gate disposition

Approved for train deploy binding, with PM ledger synchronization required. Q1 document evidence and Q2 dependency correction are clear. Train 16931216ab0015b4a3001c9947768305517e46eb may proceed to controlled deploy binding after PM records VMQ-A-01 as VERIFIED and reruns the scoped gate. Reported M2 deploy-gate errors for VMQ-A-01/O-01/O-02/O-03 are remaining ledger/dependency acceptance rows, not a VMQ-V or M2-to-V blocker. V live acceptance remains open: V-01..V-04 are REVIEW, not VERIFIED. Slice C evidence is candidate-bound and structurally valid, but its own map rows and live/vector limitations retain their existing statuses.

### Three review pillars

- Implementation: inspected section 13, slice-graph M2 dependency/write-scope, exact c97..16931216 path diff, and the V/M2 ownership seam.
- Test validity: inspected Q1 document contents and Slice C report/JSON assertions for identity, effective config, one-retrieve/one-bundle, period coverage, negative current-state behavior, and structural signal; limitations remain explicit.
- Independent challenge: independently recomputed the train path diff and SHA-256 of the actual Slice C JSON/Markdown files, and checked swapped provenance claims against file contents; no V/composer train change or false corpus binding was found.
