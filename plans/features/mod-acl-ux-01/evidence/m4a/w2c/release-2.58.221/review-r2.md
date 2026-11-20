# W2c review r2 — assembly input

**Status:** RE-REVIEW INPUT ONLY; no independent APPROVED verdict is recorded here.
**Candidate reviewed by assembly:** `67ef30cd120163132a2f2e894a0fe474bba9623d` (branch `release/mod-acl-w2c-2.58.221`, base `d03027b1`).
**Fix commit:** `2978a605f` (F1/F2/F3), evidence `40ffec595`, final candidate `67ef30cd1`.
**Release assembly:** merge `c16c3566d`; content/bump `1c75a1d8a2b1f573c44deabab4d38bfcbc20ddbe`.

## Findings and resolution

| ID | Reviewer finding | Resolution | Evidence |
|---|---|---|---|
| F1 | `round1025_f7_permsoc_local_test.js` and `routing_test.js` fail with `TypeError: self.submoduleOwnedGroups is not a function` at `web/app.js:30347`; base 0 / candidate 2. | All three call sites (`_memoryGroups`, `memorySubgroupChips`, `_permsocOwnerGroups`) use `typeof … === 'function'` guards. Production filtering unchanged. | Both tests green; mutation removing the guard kills both with the same TypeError. |
| F2 | Catalog parent chip is 15/16 px at 390; touch rule only covers `main.workspace-surface`. | Catalog anchor gets `min-height:44px` + transparent `padding-block:14px; margin-block:-14px` under `max-width:1199px`/coarse; visible pill stays 16 px, cards stay 132–164. | Chips 44/44/44/44 at 768/390/320; card heights 132/146/162; mutation removing override kills 3 viewports with 16 px. |
| F3 | Split stays two-column at 1024–1199; contract requires one column at 768–1199. | Collapse breakpoint moved to `max-width:1199px`; split remains 8/4 at ≥1200. | 1024/1152/1199 stacked; 1200 629/307; 1680 949/467; mutation reverting to 1023 kills 3 breakpoints. |

## Verification snapshot

- Node 7 W2c files: 0 fail (W2c 83 checks); F1 targeted tests green.
- W2c Playwright: 6 viewports, 0 failures; split breakpoints above; no overflow.
- M4A catalog e2e: 0 failures.
- Affected Python: 218 passed / 6 failed, same 6 on base.
- Broad JS: candidate 124/4, base 123/4, same four stale failures; no regressions.
- Mutations F1/F2/F3: all killed.

## Requested re-review

Independent Reviewer should confirm the three findings are closed, the touch target is real (bounding rect 44, no card-height regression), the 1199/1200 breakpoint is correct, and no unrelated behavior changed. This document is not an approval and does not mark VERIFIED.
