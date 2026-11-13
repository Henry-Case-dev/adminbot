# G finalize — независимое ревью (2026-11-14)

**Reviewer:** independent Reviewer session `ses_e29df18e7ffepTNP4gJn6Bcm6L`.
**Candidate:** code `cffc9fb29bf7817bcf6658d0a758332f5b1021bb`, docs `00b0901c3f360a5ed8638874c08543ee1a0c5cfc`, base `8fc8b534`, branch `smart/g-finalize`.
**Recording note:** the Reviewer could not write the artifact (workflow shell scanner rejected the write). The Orchestrator transcribed the verdict; no approval was added.

## Verdict

**Needs Fixes.**

- Implementation: single `chat_with_tools`; finalization via existing `llm.generate` without tools; structured partial when LLM unavailable; route suppression by structural `tool|host`; `retryable=true`/`extract_failed` do not close the route; registry `direct.tool_finalize`, 113 blocks, factory hash consistent.
- Test validity: 17 G tests pass; prompt audit 82 passed / 3 known pre-existing drift.
- Independent challenge: exact candidate re-probe gives `router_calls=1`, second URL `denied/route_terminal`; the committed `green-cffc9fb2.jsonl` says two calls for `nonretryable_same_host` — evidence is stale/inconsistent.

## Acceptance ledger

- `SXR-G2-01`, `G3-01`, `G4-01` — VERIFIED (tests + inspection).
- `SXR-G1-01` — UNVERIFIED: map absent in candidate worktree.
- `SXR-G5-01` — UNVERIFIED: committed JSONL contradicts the live probe; regenerate.
- Strict review gate — UNVERIFIED: `FileNotFoundError` for `requirements-map.json` in the candidate (and docs SHA was passed instead of code SHA).
- Real providers/Telegram — postdeploy.

## Blockers

1. Regenerate G5 probe JSONL and binding on exact `cffc9fb2`.
2. Make the requirements map available to the exact candidate and run `--stage review --slice S7-FINALIZE --candidate cffc9fb2`.
3. Perform the two required mutations (revert the sarcastic stub when data exists; allow repeating a terminal route), observe red, restore to green.

`route tool|host` confirmed as a technical structural heuristic, not lexical user-text routing.
