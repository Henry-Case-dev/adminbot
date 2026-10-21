# Owner decision — `resolve_failed` stays out of `_POLICY_BLOCK_CODES`

Date: 2026-10-16. Recorded by Orchestrator on the owner's explicit instruction.

## Context

A security review of `services/web_content_extractor.py` (see `review-ssrf-fix.md`) found that
the guard-order defect is fixed (a dangerous destination can no longer reach cloud fallbacks
when the optional local-extraction package is missing), but flagged a remaining narrow gap:

- `resolve_failed` (the local DNS resolver could not resolve the hostname) is **not** a
  policy-block code, so such a URL can still be forwarded to the cloud fallbacks
  (Tavily/Exa) without destination validation.
- Consequence: an internal / split-horizon hostname can leak to third-party services.
- Counter-consideration: adding the code makes a transient local DNS failure a hard error
  instead of letting the cloud fallback rescue the article.

The reviewer noted the precedent in `video_downloader.py:386` (there the actual download stays
under the local egress guard, so it is not the same situation), and explicitly warned against
claiming "dangerous destinations never reach the cloud" without this caveat.

## Decision

**Leave the behaviour as is (resilience).** The owner chose to keep the cloud fallback
available on `resolve_failed` rather than fail closed.

## Consequences to respect by every agent

1. Do NOT add `resolve_failed` to `_POLICY_BLOCK_CODES` without a new explicit owner decision.
2. Do NOT write or repeat the claim that dangerous destinations can never reach cloud
   fallbacks; the accurate statement is: dangerous destinations are blocked whenever the
   destination can be validated locally, and an unresolvable hostname is a documented
   exception kept deliberately for resilience.
3. `client_error` and `safe_fetch_timeout` must not be added either — they are
   post-validation transients where the fallback is appropriate.
