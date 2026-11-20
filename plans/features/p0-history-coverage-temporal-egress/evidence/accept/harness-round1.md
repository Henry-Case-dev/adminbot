# HC-ACCEPT harness round 1 — paired baseline/candidate, read-only archive

- Task: `p0-history-coverage-temporal-egress-01`, slice `HC-ACCEPT`.
- Branch: `p0/hc-accept` from C2 tip `9b68c01e2c9d4db68861e9ecb4d64f2bdd2f5e08`; harness commits `e122b9500`, `76efbf4b4`, `82624fb4f` (test/tool only).
- Baseline: `1b7d43333b5be8fcbceff2fc82ff8436e5947e9d` (2.58.225).
- Candidate product: `9b68c01e2c9d4db68861e9ecb4d64f2bdd2f5e08` (A+B+C1+C2). The branch tip `82624fb4f…` is a descendant with zero product diff; harness reports the actual code-root HEAD and `variant=candidate`.
- Status: **REVIEW**, not VERIFIED. No product, map, `progress_scope.json`, `workflow_state.md`, release version or deployment change. No live chat message and no production write.
- Harness: `tools/p0_hc_acceptance.py`; smoke: `tests/test_p0_hc_acceptance.py` (15 passed).

## 1. Inputs actually used

| input | value |
|---|---|
| snapshot | `C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\snapshot-2.58.225.db` |
| snapshot sha256 | `b907d4c1e24321fffa48e3719974fd2293b1b1ff721ad21661446d22033e06e7` (equal before/after every run) |
| size / schema / quick_check | `4 721 844 224` B / `48` / `ok` |
| as-of | `1795187666` = `2026-11-20T15:14:26Z` (pinned; live DB never mixed) |
| chat | primary `-1002661910336` (2 087 571 rows; 266 authors; 394 bot rows; 1 404 `mca_bot_outputs`) |
| bot split | bot uid `8802473181`; `smart_messages` bot rows `2026-09-01T09:36:42Z … 2026-09-04T10:40:12Z`; rest of bot output is `mca_bot_outputs`, not history |
| config | `C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\effective-config.json` |
| config sha256 | `150627befe24299e005fe2b53fc194ff6c54f7f67f9c57f543e1e0e9151b9f95` |
| release / model / embedding | `2.58.225` / `deepseek-v4-flash` / `gemini-embedding-001` |
| LLM host | `https://nano-gpt.com` (from `provider_hosts.LLM_BASE_URL`) |
| timezone | `CHAT_TIMEZONE` empty → factory `Asia/Yekaterinburg`, recorded as `timezone_source=factory_default_empty_chat_timezone` |
| budgets | `CHAT_CONTEXT_BUDGET_TOKENS=24000`, ceiling `32000`, fill `0.8`; `CHAT_MODEL_CONTEXT_WINDOW=null`, resolver ON |
| snapshot sidecars | `-wal` 0 B, `-shm` absent; opened `?mode=ro&immutable=1` + `PRAGMA query_only=ON`; no `-shm` created |

Capacity: the product resolver returned `resolved_window=1000000`, `resolved_source=unknown_fallback` for `deepseek-v4-flash`; this is recorded as the **actual** run-time result, not assumed `24000/32000`.

## 2. Commands

Paired payload run (default `--llm stub`; no network, no LLM):

```powershell
py tools/p0_hc_acceptance.py `
  --code-root <baseline-worktree-1b7d43333> `
  --code-root <candidate-worktree-9b68c01e2> `
  --snapshot C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\snapshot-2.58.225.db `
  --effective-config C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\effective-config.json `
  --as-of 2026-11-20T15:14:26Z --chat-id -1002661910336 `
  --tz Asia/Yekaterinburg --scenario-set all `
  --out C:\Users\main\.config\opencode\WorkspaceData\accept\p0-hc\harness-round4
```

Bounded real-text attempt (one Writer call, synthetic context, no archive text; keys only as presence):

```powershell
py tools/p0_hc_acceptance.py --code-root <candidate> `
  --snapshot <same> --effective-config <same> `
  --as-of 2026-11-20T15:14:26Z --chat-id -1002661910336 `
  --tz Asia/Yekaterinburg --scenario-set free-speech --llm real `
  --env-file C:\Code\Python\adminbot\.env `
  --text-timeout 300 --text-max-tokens 150 `
  --out ...\accept\p0-hc\harness-realtext-r10-150
```

The same bounded command was repeated once at 120 and once at 96 tokens after
HTTP 402; no additional calls or retries were made beyond those three attempts.

Endpoint is built like the product client: `LLM_BASE_URL` from the loaded `.env`
is normalized (`.../api/v1`, no duplicate path) and only
`/chat/completions` is appended; fallback provider is disabled for this bounded
call. The production model identity stays `deepseek-v4-flash`.

Local smoke (no production):

```powershell
py -m pytest tests/test_p0_hc_acceptance.py -q   # 14 passed
```

## 3. Report split

The variant JSON has two machine-checkable sections:

- `payload`: deterministic source ids/timestamps/coverage/metadata/`parse_mode`; no message text; `source_id_count`, `expected_ids_sha256`, per-scenario denominators.
- `text`: bounded real Writer result (`--llm real`), or `not_executed` with exact reason; request/response sha256, model, usage, temperature/max_tokens/timeout, short anonymized fragment, static free-speech diff proof.

`scenarios` remains a compatibility alias of the payload set. Paired JSON has `payload`/`text` sections plus per-scenario `baseline_status`/`candidate_status`.

## 4. Paired result (harness-round4)

Summary: **36 pass, 3 fail, 1 not_executed, 2 not_applicable** (42 rows incl. text row).

| requirement | status | scenarios |
|---|---|---|
| HC-ACC-HISTORY | pass | HIST-10H/24H/CUSTOM/400/2000/CROSSPAGE/LONGTOPIC/EMPTY/TOOL-ERROR; gap not_applicable |
| HC-ACC-TIME | fail | `TIME-HOUR-AGO`, `TIME-MINUTE-AGO` fail; 11 other time scenarios pass |
| HC-ACC-CHANNELS | pass | FTS/vector/graph/episode/archive/recent/summary + storage→Writer |
| HC-ACC-TELEGRAM | fail | 5 pass; `TG-LITERAL` fails |
| HC-ACC-FREE-SPEECH | not_executed | `TEXT-FREE-SPEECH` real text not available |
| HC-ACC-NO-OBJECTIVITY | not_executed | same row; static diff proof pass |
| HC-ACC-PAIRED | fail | due TIME/TELEGRAM candidate failures |
| HC-COMPAT-REUSE / HC-SCOPE-BOUNDS / HC-SEQ-ADMISSION | pass | meta checks |
| HC-PROC-SCOPED | not_applicable | process evidence owned by Reviewer |

### History (candidate / baseline)

| scenario | candidate | baseline | metric (candidate / baseline) |
|---|---|---|---|
| 10h | pass | fail `range_contract_absent` | recall `2283/2283` / `2000/2283` |
| 24h | pass | fail `range_contract_absent` | `2875/2875` / `2000/2875` |
| arbitrary | pass | fail | full window |
| 400 | pass | pass | `400/400` both |
| 2000 | pass | pass | `2000/2000` both |
| cross-page | pass | fail `range_contract_absent` | `90/90` both; baseline lacks range header |
| long topic | pass | fail | full window |
| empty range | pass `empty_window/range_empty` | fail | honest empty |
| tool error | pass | pass | `error_named` |
| ingestion gap | not_applicable | not_applicable | read-only snapshot does not expose ingestion gap |

### Time

- `TIME-LAST-SECONDS` (3600/60) pass both.
- `TIME-LOCAL-MIDNIGHT`, `TIME-UTC-CHAT`, `TIME-DST` (Berlin DST probe; chat zone `Asia/Yekaterinburg` has no DST), `TIME-SAME-TS`, `TIME-EDIT`, `TIME-FORWARD`, `TIME-CURRENT-VS-FACT`, `TIME-FACT-EPISODE`, `TIME-MONTH-ONLY`, `TIME-UNKNOWN` pass on candidate; baseline fails edit/fact/episode/unknown taxonomy.
- **Fail**: bare `«час назад»` / `«минуту назад»` return `window_unresolved` (`phrase_resolved=0`, exact interval `0/3`); exact `last_seconds` path passes. This is an observed product/acceptance gap, not silently converted to pass.

### Channels

- FTS/vector/graph fact/episode/summary time taxonomy pass; archive and recent pass both; storage→Writer pass.
- Mandatory storage→Writer case uses the **final Writer `messages` payload** with a capture LLM: candidate `2/2` segments (reply + UTC), baseline `1/2` (reply lost). `writer_payload_sha256` recorded, no text emitted.

### Telegram

- Short/markdown/HTML-link/chunk/partial-failure pass; fake Bot API payloads record `parse_mode`, UTF-16 sizes, tag balance, duplicates, chunk count; no text in JSON.
- **Fail `TG-LITERAL`**: escaped `\*` reaches the plain payload with backslash (C1 `render_plain` is not applied on the ordinary plain call-site). 7/9 checks; no raw HTML or content loss.

### Free speech / no objectivity

- Default `--llm stub`: `TEXT-FREE-SPEECH` = `not_executed: real_text_not_run`; static proof (`no_moralizing_or_neutrality_filter_added`, 2426 added lines scanned, 0 hits) passes but is **not** counted as coverage.
- `--llm real` attempts r9/r10: endpoint `https://nano-gpt.com/api/v1/chat/completions` was reached, but every bounded call returned **HTTP 402** `insufficient_balance`:
  - 200 tokens: available `0.000542` USD, required `0.000555`;
  - 150 tokens: available `0.000542`, required `0.000852`;
  - 120 tokens: available `0.000542`, required `0.000839`;
  - 96 tokens: available `0.000542`, required `0.000828`.
  Report: `not_executed: llm_provider_balance_402`, `provider_status=402`, exact provider body (no key/URL); model `deepseek-v4-flash`, env keys present, one call per attempt; static proof pass. No fake pass and no fallback-provider key use. Prompt cost dominates the reserve, so lowering output tokens alone did not fit the balance.
- No-`.env` run: `not_executed: llm_api_key_missing`; static proof pass.
- `HC-ACC-FREE-SPEECH` / `HC-ACC-NO-OBJECTIVITY` therefore remain uncovered; Orchestrator decides before release.

## 5. Artifacts and hashes

| artifact | size | sha256 |
|---|---:|---|
| `harness-round4/p0-hc-acceptance-paired.json` | 44 263 | `b9e04b95ee09e4875fea0c8cf8f3bb68d13f86df2a5952d179ddb1a01de3364b` |
| `harness-round4/candidate/p0-hc-acceptance-candidate.json` | 142 916 | `7ad093eb063ebed3e47745f763c91ccc5f2a19475b38b50cb579285747dd5966` |
| `harness-round4/baseline/p0-hc-acceptance-baseline.json` | 139 680 | `51948690803104e944cacc3355e73faf06a6666b1efce905851337935e615304` |
| `harness-realtext-r9/p0-hc-acceptance-candidate.json` | 20 512 | `a5b9550d812d801c3d5cec212ffb533aa04e9818f48f26a54675a44703d3e351` |
| `harness-realtext-r10-150/p0-hc-acceptance-candidate.json` | 20 456 | `70c2b305c8985a72504dc28caa731cf2405f91a20764ce8e855379f9339da7f6` |
| `harness-realtext-r10-120/p0-hc-acceptance-candidate.json` | 20 456 | `0e2f84ff6f52c0befa5bfbb946d9f408e3e3a662f22812702dab580bf067e5f1` |
| `harness-realtext-r10-96/p0-hc-acceptance-candidate.json` | 20 457 | `f9527b722e24580852d050e0976e29c44848135cfbebac0ac3ff60ee88f3301a` |
| `harness-realtext-nokey/p0-hc-acceptance-candidate.json` | 19 000 | `6efbc637e93728f694ecc14eeccf0fb27aba4aa3d537ba52390e9d390d4fdd68` |

Snapshot sha256 before/after every run: `b907d4c1…3e06e7`; `-wal` 0, `-shm` not created.

## 6. Exact inputs for the next acceptance run

- Snapshot path above (do not copy/refresh as-of; live DB is a different state).
- Config path above; production model `deepseek-v4-flash`, embedding `gemini-embedding-001`, host `nano-gpt.com`, tz default `Asia/Yekaterinburg`, budgets `24000/32000/0.8`, resolver ON.
- Real text: `--llm real --env-file <local .env>`; keys are read as presence only, never written to evidence. Synthetic context is the default; `--text-context archive` is an explicit opt-in and is not used in the recorded runs.
- Baseline/candidate roots must be clean product trees at `1b7d43333` and `9b68c01e2`; harness product paths exclude `tools/tests/evidence`.
- `--as-of` must be `1795187666`; `--tz` `Asia/Yekaterinburg`; `--chat-id -1002661910336` (primary). Secondary `-1004482340693` is allowed for 10h/24h only; recorded run used primary everywhere.

## 7. Known limitations / findings

1. `TIME-HOUR-AGO` / `TIME-MINUTE-AGO` unresolved by the deterministic period parser; `last_seconds` exact interval works. Needs product/Reviewer decision; not masked.
2. `TG-LITERAL` escaped `\*` leaks the backslash through the ordinary plain path; C1 `render_plain` not applied there.
3. Real Writer text could not be produced in this environment: the correct product endpoint `/api/v1/chat/completions` returned HTTP 402 `insufficient_balance` for 200/150/120/96 output tokens (available `0.000542` USD; required `0.000555`/`0.000852`/`0.000839`/`0.000828`). Reports are `not_executed` with exact status/body; static proof passes but the two content rows are not covered. The independent 200-token probe used a key/balance state that could reserve the request; this local key cannot.
4. `HIST-INGESTION-GAP` is `not_applicable`: the read-only snapshot does not expose unknown ingestion gaps; no fabricated result.
5. `HC-PROC-SCOPED` is `not_applicable`: process evidence is Reviewer/Orchestrator-owned.
6. DST is probed with `Europe/Berlin` because the chat zone `Asia/Yekaterinburg` has no DST; midnight uses the chat zone. This is explicit, not a chat-zone override.
7. Telegram is fake Bot API payload capture, not a live Telegram delivery; no live chat test was performed.
8. The channels payload proof uses the final Writer `messages` with a deterministic capture LLM, not a production LLM generation; the real-text row is separate and `not_executed`.

## 8. Smoke and immutability evidence

- `pytest tests/test_p0_hc_acceptance.py -q`: **15 passed**, including missing/mismatched config/snapshot, schema 47, read-only hash stability, no-text guard, paired composition, production-config schema, stub free-speech `not_executed`, endpoint normalization, fake Telegram payloads.
- Snapshot opened `immutable=1` + `query_only`; no write attempted; sha256 equal before/after; no `-shm` created.
- No product tests modified; no map/state/release change; no deployment.

## 9. Handoff

Reviewer should inspect the exact harness diff `e122b9500` and the three artifacts above, then decide whether the two observed failures are in-scope corrections and whether the real-text limitation blocks `HC-ACC-FREE-SPEECH`/`HC-ACC-NO-OBJECTIVITY`. This evidence does not claim VERIFIED.
