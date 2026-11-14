Needs Fixes
Candidate aca1370250a7579cd3cc969679852cf2b1d2608b; base d20a7f73; docs-only Reviewer audit.
Implementation: inspected direct_context_composer, evidence_bundle, response_extent, SourceReader/tool-loop, tool_router, search_aggregator, voice_transcripts, factcheck, direct_chat_service and settings.
Test validity: smart execution assertions verify counts, continuation, provenance, byte-identical role-tool payload and final-answer marker; fake provider does not prove provider step 1 or production config.
Independent challenge: found _MEMORY_MAX_SYMBOLS=3500, hard memory item/result/slice caps, search max_symbols truncation, transcript _MAX_ITEMS=3, factcheck context cap 40, direct-chat digest/persona/reserve caps and settings defaults.
Broad failure-only comparison: base 124, candidate 118, only-on-candidate 0, only-on-base 6. This does not prove system-wide acceptance.
Ledger: SXR-C2-01 FAILED; SXR-C3-01 UNVERIFIED outside SourceReader; SXR-C3-02 FAILED; scoped SXR-C2-02 VERIFIED only for S3. Postdeploy effective state UNVERIFIED.
Next: Builder removes artificial caps or proves physical/provider limits, fixes L1/Writer/fallback/reserve paths, adds boundary tests; Reviewer rechecks combined candidate. PM updates rows only after proof. Full pytest rerun and live provider run were not completed after interruption; browser N/A; web sources none.
