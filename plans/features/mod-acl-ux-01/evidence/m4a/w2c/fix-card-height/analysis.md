# W2c card-height fix — root cause and verification

**Status:** REVIEW; no deploy, no version bump, no VERIFIED.
**Base:** `67ef30cd120163132a2f2e894a0fe474bba9623d` (product candidate; 2.58.220 pins, no bump)
**Branch:** `fix/mod-acl-w2c-card-height`
**Deployed failure evidence:** commit `b4cc33971`, `plans/features/mod-acl-ux-01/evidence/m4a/w2c/release-2.58.221/deploy-2.58.221.md`, `deploy-2.58.221-m4a.json`, `deploy-2.58.221-w2c.json`.

## 1. Real root cause

The postdeploy failure is **title wrapping**, not an assertion defect:

- Deployed M4A 1440: `mod_transcribe`, `mod_video_summary`, `mod_media_download`, `mod_images`, `mod_vision` = **179.56 px**; every other card = 162.06. Extra height = **17.5 px** = 14 px title × 1.25 line-height, i.e. exactly one extra title line.
- The catalog grid stretches row siblings: one long title in the media row makes all cards in that row 179.56.
- `.module-card .module-title` had no clamp (`font-size:14px; line-height:1.25` only). Production Linux/font metrics wrap the long media titles at the 4-column width (286 px at 1440; similar at 1680); the synthetic global-scope harness on Windows kept them one line, which is why local 132/146/162 did not expose it.
- Reproduction with realistic long values in the existing W2c harness (chat scope, real long chat labels, long titles/descriptions):
  - old code: **179.56**, `titleH=35` (2 lines) for the four cards at 1680/1440, and at 320 for the long-title row;
  - RED log: `test-output/red.log`, `red.json`; screenshots `red-shots` in the run artifact.

The fix does **not** weaken the height assertion: the same 132–164 assertion is retained and the long-content title is the thing clamped.

## 2. Minimal fix

- `web/static/app.css`: `.module-card .module-title` becomes a one-line block with `white-space:nowrap; overflow:hidden; text-overflow:ellipsis;`.
- `web/index.html`: catalog title gets `:title="m.title"` so the full title remains available on hover/accessibility; DOM text stays complete.
- No change to description clamp, control row, tri-state, badges, parent chip, split, footer or glass tokens.
- No backend/API/DDL/flags/prompts/storage change; no `APP_VERSION` bump.

After the fix (long-content harness, chat scope, realistic long titles/descriptions):

| Viewport | mod_transcribe | mod_video_summary | mod_media_download | mod_images | titleH |
|---|---:|---:|---:|---:|---:|
| 1680 | 162.06 | 162.06 | 162.06 | 162.06 | 18 |
| 1440 | 162.06 | 162.06 | 162.06 | 162.06 | 18 |
| 320 | 162.06 | 162.06 | 162.06 | 162.06 | 18 |

Green evidence: `test-output/green.json` / `green.log`; screenshots `card-height-1680.png`, `card-height-1440.png`, `card-height-320.png`.

## 3. Tests

- Targeted long-content Playwright (`tools/ui_mod_acl_w2c_card_height_e2e.py`): **3 viewports (1680/1440/320), 0 failures**; four cards 162.06, `titleH=18`, descriptions 32 (2 lines), chat labels 13.
- W2c Playwright 6 viewports: **0 failures**, all 21 cards 162 at every viewport; parent chips, split, deep links, owner links, touch and overflow unchanged (`test-output/w2c-6viewports.json`).
- M4A catalog e2e: **`M4A-CATALOG-E2E OK | failures=0`** (13 conflict/badge/mobile/height checks).
- Node W2c 7 files: **0 fail** — M3 235, M4 catalog 207, params 64, review 75, W2a 141, W2b 356, W2c 84. The D2 label test remains green because chat labels keep their full wrapped text; only the title is clamped.
- Affected Python: **218 passed / 6 failed**, the same 6 baseline failures as before; no new failures. Log: `test-output/affected-python.txt`.
- Mutation: removing the title clamp re-introduces **179.56 / titleH=35** and the targeted test fails (24 assertions: 4 cards × height+title × 3 viewports). Log: `test-output/mutation-title-clamp-removed.txt`.

## 4. Residual / next

- This branch is product-only from `67ef30cd`; the release branch still contains the 2.58.221 bump/evidence. A subsequent assembly/binding must merge this fix and decide 2.58.222 (or a re-cut of 2.58.221 with a new content SHA); no version is bumped here.
- Deployed 2.58.221 was rolled back to 2.58.220; this fix is not deployed.
- W2c rows remain REVIEW; no VERIFIED claim.
