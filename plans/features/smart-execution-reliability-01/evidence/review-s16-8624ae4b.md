# Review S16-FC-FINALIZE

VERDICT: Needs Fixes

Candidate: 8624ae4b; base: d8f50a68.

Implementation: inspected check_claim_envelope through Analyst, validator, Verbalizer, fallback and Renderer, plus legacy finalization. Existing stages remain; no third LLM stage, editor, new template or prompt change.

Test validity: tests/test_factcheck_finalization.py assertions inspected. Candidate focused suite: 12 passed. Base comparison: 8 failed / 4 passed; focused contour 240 passed vs 228 base; broad contour 782 passed, 1 failure, same base/isolation behavior. OCR test checks tag names but not container contents.

Independent challenge: probe_s16.py with PYTHONPATH=. injected raw chat_context containing OCR. User-facing output retained text with картинки after tags were removed.

Ledger: SFC-9-01 VERIFIED; SFC-9-02 VERIFIED; SFC-9-03 VERIFIED; SFC-9-04 VERIFIED; SFC-10-06 FAILED.

BLOCKER SFC-10-06: strip_service_tokens removes service tags but not their inner content, leaking raw OCR into speech. Builder must remove entire supported raw/service containers, add mixed and service-only assertions, then rerun focused suite and probe.

Residual: S17 scenarios 12.1-12.8 and observability remain postdeploy. Backlog-only: pre-existing order/network failure and G/S7 CRLF. UI gate not applicable; no web sources.

Next: Builder fix, then independent re-review SFC-10-06.
