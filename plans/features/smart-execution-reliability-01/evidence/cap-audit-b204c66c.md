APPROVED for REVIEW
Candidate b204c66cf92b4b8e530bcdad756ad1d4d6b1a33c; code b6320e59; base d20a7f73.
Implementation: verified the three fixes in merged code. mca_retrieval_context constructors for message/fact/vector/reply/entity/community/episode now assign full source text; _truncate_preview call sites are absent from data paths. The remaining _PREVIEW_MAX_CHARS=400 is documented as an unused UI-snippet compatibility constant. tool_router passes reply_text in full; claim[:400] is display-only and claim_truncated is true iff the displayed claim field exceeds 400. handlers/youtube calls fetch_transcript(video_id, on_retry=None); Telegram chunking remains at delivery.
Test validity: independent tests/test_caps_tool_results.py tests/test_caps_context.py: 36 passed in 4.82s. Assertions cover >400 memory fragments, >300 reply claim into envelope, >20k transcript and real delivery chunking, full provider result/payload, physical vision limit and honest voice window_truncated. Reused lane evidence: tool 17, search 53, factcheck 84, memory 306, transcripts 386, vision 314 passed/38 skipped, affected 428, broad 3523 passed/4 failed/18 errors; cited broad failures/errors were reproduced on base as pre-existing (routes pin byte-freeze, mca20 escaping, YouTube multimodal fixtures). A command naming absent tests/test_caps_final.py was not counted.
Independent challenge: source grep found no _truncate_preview invocation in candidate constructors, no reply_text[:300], no _YT_TRANSCRIPT_CAP; direct source reads confirmed full values and delivery signatures. git diff --check d20a7f73 HEAD -- services handlers tools tests was empty under cr-at-eol.

| Семейство | Verdict | Evidence / residual |
| Search | REVIEW-ready | provider text no hard trim; compact/remainder remains. |
| Documents/pages | REVIEW-ready scoped | SourceReader/evidence continuation and provenance retained. |
| Memory | REVIEW-ready | tool-router caps removed; retrieval constructors preserve full fragments; dead UI preview constant does not reach tool. |
| OCR/Vision | REVIEW-ready | content uncapped; max_tokens is physical generation budget; output_truncated and bounded retry retained. |
| Transcripts/voice | REVIEW-ready | full transcript/voice row; explicit selection remains semantic; SQL page 120 is technical and window_truncated is honest. |
| Factcheck | REVIEW-ready | full input claim/evidence paths; display claim[:400] is explicitly marked and is not the checked claim. |
| Direct context/L1/Writer/fallback | REVIEW-ready | real capacity resolver/portioning, no legacy artificial cuts, OFF-budget preservation and readback tests retained. |
| Direct YouTube command | REVIEW-ready | 20k handler cap removed; full transcript reaches existing Telegram chunking. |

## Core ledger
- SXR-C2-01: VERIFIED for REVIEW on exact candidate; no remaining artificial ceiling in audited families. DIG_MAX_SYMBOLS factory is not applied unless explicit policy; vision max_tokens is physical; voice page 120 is technical with honest marker; dynamic evidence OFF is explicit operator rollback.
- SXR-C3-02: VERIFIED for REVIEW; artificial char/JSON/legacy-window/section-reserve/double-truncation/L1-Writer/fallback losses removed; real-window packing/readback and budgets-OFF behavior covered.
- SXR-C3-01: VERIFIED for REVIEW for transport/real-path evidence. Search, YouTube segment formatting, Vision analyze_image_bytes, voice and retrieval paths are exercised locally; memory uses repository/storage doubles and STT uses transport stub. Live external providers, Telegram delivery in production, live LLM payload and production effective configuration remain postdeploy-only and are not claimed as predeploy proof.

No blocking findings. Postdeploy-only: deployed-SHA effective config, real provider responses, live LLM payload and Telegram delivery canary. Browser/visual checks N/A for backend/static feature; external sources none. Next: PM binds these three rows to REVIEW evidence; DevOps performs the existing controlled deployment/live checks before final release acceptance.
