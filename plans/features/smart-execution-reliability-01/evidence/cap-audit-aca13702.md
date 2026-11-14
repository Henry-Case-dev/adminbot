Needs Fixes
Candidate aca1370250a7579cd3cc969679852cf2b1d2608b.
Seven-step chain audited: tool -> structured result -> ToolResult/evidence -> tool-loop -> composer -> LLM payload -> final answer.
Search: search_aggregator hard text[:max_symbols], settings default 4000; C2-01 FAILED.
Documents/pages: SourceReader and evidence_bundle continuation/provenance proven only in scoped S3.
Memory: tool_router max symbols 3500, hard max items 20, result 4000, slice 240 and truncation; C2-01 FAILED.
OCR/Vision: structured delivery only; provider step 1 and cap classification UNVERIFIED.
Transcripts: voice_transcripts _MAX_ITEMS=3 and YouTube max_symbols remain; C2-01 FAILED.
Factcheck: FACTCHECK_CONTEXT_TOTAL_CAP default 40 plus max_symbols/support/evidence caps; C2-01 FAILED.
Message length: CHAT_CURRENT_QUESTION_MAX_CHARS=800 and correction caps remain; C2-01 FAILED.
Tool-result and total model volume: direct-chat digest/persona/protected reserve and L1/Writer/fallback paths remain; C3-02 FAILED.
C3-01 UNVERIFIED outside SourceReader: other families only steps 2-6 with supplied structured inputs, no provider step 1. C2-02 VERIFIED only scoped.
Three pillars: implementation paths read; tests assert real values/provenance/byte identity but use fake provider; independent challenge found concrete caps. No external sources. Builder must remove/prove artificial caps and add durable boundary tests; Reviewer rechecks exact combined candidate.
