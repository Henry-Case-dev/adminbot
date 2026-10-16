# AUDIT-2 — UI / Initiative / Legacy v6.3 recon

Lane: AUDIT-2 (epic SOUL-1) · Date 2026-10-16 · read-only.
Repo `C:\Code\Python\adminbot`, branch `master`, local HEAD `a854ad953d360e0dcda1174b3a171cdecebc0417`.
Source of scope: `plans/features/soul-1/source-current-task.md` (SHA256 `8C42DDFA…`);
task IDs SOUL-11 / SOUL-12 / SOUL-13 / SOUL-18.
Machine-readable findings: `plans/features/soul-1/evidence/ui-initiative-legacy.json` (27 findings).

Evidence classes used:
- **code** — exact `file:line`;
- **local runtime** — FastAPI `TestClient` over `web.app` (TMA dep override + fake PG), anon HTTP GET, bounded pytest, local SQLite;
- **doc** — v6.3 feature artifacts (*claimed*, cross-checked against code where possible);
- **EXTERNAL_UNVERIFIED** — platform/provider facts not provable from repo.

---

## A. SOUL-11 — UI routes and Direct prompt editing

### A.1 Verified code facts

| Ref | Fact |
|---|---|
| `services/direct_chat_service.py:3641`, `:7552` | `prompts.direct_l1_planner_system_prompt` is read at runtime (L1 planner). |
| `web/app.js:13439` | Same key is rendered by the UI `stageCard`. |
| `services/param_catalog.py` | grep `direct_l1_planner` → **0 matches** ⇒ key absent from REGISTRY ⇒ `/api/config` returns `null` ⇒ **no editing path** (code default only). |
| `web/app.js:705` | `mod_direct` tabs = `['overview','settings','synthesizer','verbalizer','models','limits','testing']` — **no** `prompts` tab. |
| `web/app.js:750` | back-map `mod_direct → prompts_direct_chat` (library "Открыть" lands on `synthesizer`). |
| `web/index.html:2286-2293` | With `PROMPTS_UI_V2_ENABLED`, the `prompts_verbilizer` group card is **skipped**; modes editable only via module-card mode tabs / fallback dropdown (`:2299-2332` is the non-skipped branch). |
| `web/index.html:2193-2199` | Empty states: "вкладка пустая" (`:2193`) and "Ничего не найдено по запросу …" (`:2196`) — shown even when the search box is empty. |
| `web/app.js:14649-14795` | `promptSections` / `promptVisibleItems` do **not** apply `isAdminIdHidden` (`web/app.js:18530`); `workspacePromptStale` returns false when the item list is empty ⇒ empty list, **no reason**. |
| `web/app.js:2775-2787` | Mobile `<768px`: `mobileTopnavItems` = exactly `['status','oversight','modules']`; `mobileMoreItems` = navItems minus those ⇒ **«ИИ» (prompt library) only in «Ещё»**. |

Editable Direct keys (all `per_chat=true`, `secret=false`): `prompts.direct_chat_system_prompt`
(stage null/basic), `prompts.direct_chat_synthesizer_system_prompt` (advanced/synthesizer),
`prompts.direct_chat_verbalizer_system_prompt` (advanced/verbalizer),
`prompts.verbilizer_mode_casual|serious|deep_research` + `prompts.verbilizer_default_mode`.

### A.2 Local runtime evidence

| Probe | Result |
|---|---|
| anon `GET /api/config` | **401** (RBAC gate) |
| `GET /api/config` (TMA override + fake `ConfigCache(pg=_FakePg())`) | 200; **23** `prompts.*` keys; **9** groups incl. `prompts_verbilizer` |
| anon `GET /web/` | 200 |
| anon `GET /static/glass-teststand.html` | 200 (see D.2) |

### A.3 UNVERIFIED / decisions
- Whether `direct_l1_planner_system_prompt` **should** become editable — owner contract, not provable from code.
- Discoverability of the two-door prompt model (module tab vs library) and mobile one-extra-tap — UX acceptance, owner.

---

## B. SOUL-12 — Telegram fullscreen (three operations kept separate)

### B.1 Operation A — launch / shell
`web/static/telegram-init.js:12` `wa.ready()`, `:13` `wa.expand()`; safe-area events wired here.

### B.2 Operation B — WebApp fullscreen API
`web/static/fullscreen-policy.js`:
- `:65` `slotFromGeometry('tdesktop',…) → 'hidden'`;
- `:88-92` `reason='tdesktop_disabled_until_e2e'`, `slot='hidden'`;
- `:77-108` reason/capability resolution; `:258-267` class writer (`fs-slot-float` / `fs-hidden` / `data-fs-reason`);
- SDK surface used: `requestFullscreen` (+legacy `requestFullScreen`), `exitFullscreen`, `isFullscreen`, `onEvent/offEvent` for `fullscreenChanged`, `fullscreenFailed`, `viewportChanged`, `safeAreaChanged`, `contentSafeAreaChanged`, `viewportStableHeight`, `safeAreaInset`, `contentSafeAreaInset`.

### B.3 Operation C — responsive CSS
Geometry-driven slot + separate class writer (above) ⇒ slot/class rendering is locally verifiable without a real client; distinct from A and B.

### B.4 External contract — EXTERNAL_UNVERIFIED
| Source | Fact |
|---|---|
| `core.telegram.org/bots/webapps` (Bot API 8.0, 2024-11-17; current 10.1, 2026-06-11) | Added `requestFullscreen`/`exitFullscreen`/`isFullscreen` + safe-area insets and the above events. |
| `core.telegram.org/api/bots/webapps` | `fullscreen_failed.error ∈ {UNSUPPORTED, ALREADY_FULLSCREEN}`. |
| `docs.telegram-mini-apps.com/platform/viewport` | Desktop mini apps open maximized in a medium window; `web_app_expand` has no effect there. |
| @BotFather docs | Main Mini App `mode=compact|fullscreen` is **BotFather-only**; bot cannot change it. |
| `github.com/telegramdesktop/tdesktop` #30963 / #31041 / #31114 (lib_ui PR #342/#343) | Telegram Desktop fullscreen client bug: panel resized but origin retained, taskbar visible, input offset. Fix not confirmed against the installed client version ⇒ `EXTERNAL_UNVERIFIED`. |

### B.5 Live gate
`plans/features/asap8-v6-3-live-correction/w4-live-probes.md:28` — **V06 = BLOCKED_REAL_HUMAN_GATE** (8 map items `U07.*`); mock matrix + Playwright (`w2-evidence-fullscreen/`) **do not substitute** real clients.

---

## C. SOUL-18 — Initiative diagnostics / observability

### C.1 Pipeline / scheduling
| Ref | Fact |
|---|---|
| `services/memory_maintenance.py:335-342, `:430-469`` | durable `task_jobs` kind `initiative.observe`, coalesce `initiative.observe:global`, owner `asap8b01`. |
| `services/memory_maintenance.py` (`_INITIATIVE_OBSERVER_TICK_SECONDS=300`) | tick every **300 s ⇒ 288 ticks/day**. The "25/day" figure (`w4-live-probes.md:16`) is **completed-job count in one 24 h window**, not the schedule. |
| `services/initiative_observer.py:913-1028` | `handle_initiative` → decision SAY/REACT/SILENT → Direct L2 Writer → SendRecheck → send. |
| `:1032-1043` | diagnose phase (`DIAG_MIN_OBSERVED=20` at `:79`, `:1035`). |

### C.2 Counters & gates
- Counters (`:245-254`): `passes, observed, eligible, scan_skipped, evals, opportunities, silent_decisions, intents_created, sent, react_decisions, writer_unavailable, eval_unavailable, errors, eval_skips{reason}`.
- Skip codes (`:81-93`): `chat_disabled, direct_address_seen, min_gap, day_cap, topic_cap, eval_budget, eval_not_due, not_enough_messages, context_duplicate, no_opportunity, semantic_parse_error, semantic_eval_unavailable`.
- Suppressors: master `flags.initiative_observer_enabled`; K1 `mca_gates.intents_enabled()` (fail-closed); per-chat `initiative.enabled` (groups, chat_id<0); profiles rare/normal/active (`:104-127`: `min_gap` 2700–21600 s, `max_replies_per_day` 2–12, `eval_min_interval` 1200–21600 s, `eval_min_messages` 6–12, `eval_llm_budget` 4–24/day); `_window_addressed_to_bot` → `direct_address_seen`; context hash TTL 12 h; `worker_budget.consume` fail-open; LLM `None` → `eval_unavailable`.
- Funnel route: `GET /memory/intel-funnels` (`web/api/memory_overview.py:216-289`, global-admin only).

### C.3 What is NOT available locally
Local SQLite backups (`pre_migration_20261007_010900.db`, `local_database_2026-09-04_history.db`) contain only `smart_messages` (60 k / 1.93 M rows), **no `mca_events` / `task_jobs`**; `local_database.db` is an empty 12 KB dev file ⇒ no local initiative telemetry.

### C.4 Request (prod-only, do NOT fetch)
Per chat, 24–48 h: scans / observed / eligible; opportunities by kind; decisions; SILENCE-reason distribution; send attempts; deliveries with `message_id`; dupes/refusals; latency; last timestamps; which suppressors actually fired.

---

## D. SOUL-13 — Legacy v6.3 tails

### D.1 Deployed SHA vs local HEAD
| Fact | Value / ref |
|---|---|
| Production deployed SHA | `c2775a54258512a3e20c97341d3e8a6738b1a33b` (2.58.79) — `live-canary.md:9,21-24`, `release-reconciliation.md:3` (server-verified) |
| Local HEAD | `a854ad95…`; `git merge-base --is-ancestor c2775a54 HEAD` → **0** |
| Delta | `git log c2775a54..HEAD` = **6 commits**, all `docs(v6.3)` / `chore(workflow)` (`225c3c2b`, `736a8834`, `8c960df6`, `4ca40730`, `00eb362b`, `a854ad95`) — **no app-code change** |
| Version | `APP_VERSION = "2.58.79"` (`config/settings.py:3286`) |

Commit `225c3c2b` = `225c3c2bbc8c5065d5a4afc2c4e0b189b403b77c` resolves locally; binds map to `c2775a54`.

### D.2 glass-teststand exposure (production static)
| Probe | Result |
|---|---|
| anon `GET /static/glass-teststand.html` | **200** |
| anon `GET /web/static/glass-teststand.html` | **200** |
| anon `GET /glass-teststand.html` | 404 |
| anon `GET /web/` | 200 |

Mounts without auth: `web/app.py:338` (`/web → web`), `:344-347` (`/static → web/static`).
Assets: `web/static/glass-teststand.{html,css,js}`, `web/static/glass-probe.js`.
Tests that must be updated if assets leave prod static: `tests/js/glass_probe_test.js:110-111`,
`tests/test_unified_image_request_round1026.py:742-744`, `tests/test_tool_coordinator_round1026.py:763-770`.
Minimal fix = remove teststand assets from production static **or** add server-side auth; keep
`web/static/vendor/lg-lens-map.png` (used by production liquid glass); do not touch polygon background / runtime glass.

### D.3 v6.3 artifacts exist (tracked)
`git ls-files plans/features/asap8-v6-3-live-correction` lists `release-reconciliation.md`,
`final-audit-current-task.md`, `live-canary.md`, `w4-live-probes.md`, `baseline-pytest-b10.md`,
`SNAPSHOT_MANIFEST.md`, `requirements-map.json`, `waves.md`, reports/evidence. Contradicts any
"not found" claim. (Some PNG evidence shows as working-tree-modified only.)

### D.4 Release gate / 14 live gates
- `check --stage plan` → exit 0 (`inventory=148 manual=74 scoped=0 errors=0`).
- `check --stage release` → **exit 1** (202 errors): `candidate_commit`/`deployed_commit` empty, all 148 statuses `PENDING` (`live-canary.md:75-85`, `final-audit-current-task.md:155-165`). Map **not** edited to force green.
- **14** items `BLOCKED_REAL_HUMAN_GATE` in `requirements-map.json` (lines 1533, 1583, 1839, 2020, 2092, 2406, 3138, 3210, 3304, 3486, 3536, 3564, 4384, 4662); `w4-live-probes.md:19-29` marks V01/V02/V04/V06 blocked, V03/V05/V07 `READY_FOR_LIVE`.

### D.5 Embedding quota (documented vs assumed)
| Ref | Fact |
|---|---|
| `services/embedding_control_plane.py:295-341` | Credential slots: `primary` (hot `keys.embedding_api_key` → env `EMBEDDING_API_KEY`), `fallback_1/2`, `extra_N`; **each alias = its own quota group** (auto-group = alias, or `EMBEDDING_QUOTA_GROUP_LABELS` `alias:group`). |
| `:656-678`, `:959`, `:2035-2086` | `embedding_quota_state` (v23) + cooldown skip + rotation in `_pick_credential`. |
| `services/llm_client.py:434-436` | Empty primary ⇒ fall back to `keys.llm_api_key` (backward compat). |
| `.env` (local probe) | `EMBEDDING_API_KEY` **absent**, `EMBEDDING_BASE_URL` absent ⇒ default `https://apinet.cloud/v1` (`config/settings.py:374-375`); primary resolves from hot-config. `LLM_API_KEY` + `EMBEDDING_FALLBACK_API_KEY` present (no secrets printed). |
| `w4-live-probes.md:41-54` (prod journal) | 00:05:08 `primary` 429 → 00:05:19 `fallback_1` 429 → 00:05:28 `fallback_2` 429 (three independent provider responses, distinct keys/groups) — **all to one host `apinet.cloud`** ⇒ shared proxy cap, **not** "three keys = three independent quotas". |

Rotation itself is **proven from code**; the shared-cap cause is **documented from prod journal**;
the real reset horizon is **provider-side and NOT provable from the repo** ⇒ owner/provider confirmation.
No secrets written to this report or the JSON.

### D.6 6 pre-existing pytest failures (reproduced locally)
Local bounded run of the 6 node IDs → `6 failed, 2 warnings in 3.13s`. Same set as `W2-REPIN.md:36-51`
(sweep `13493 passed / 6 failed / 1 skipped`):
1. `tests/test_mca02_safe_fetch_round1027.py::TestOffParityAndTrusted::test_web_extractor_blocks_destination_without_fallback`
2. `tests/test_mca16_experience_block_d_round1039.py::test_no_per_message_llm_reflection_module_is_llm_free`
3. `tests/test_outgoing_guard_round1022.py::TestTelegramSendWrappers::test_send_rich_message_sanitizes_and_uses_html_mode`
4. `tests/test_outgoing_guard_round1022.py::TestTelegramSendWrappers::test_send_rich_message_markdown_cover_uses_markdown_link`
5. `tests/test_summary_asap2_failsoft_round1027.py::test_t3959_10_l1_dead_level2_l2_called_and_cover_fallback`
6. `tests/test_summary_publish_integration_round1026.py::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article`

Classification (fix vs re-pin) is owner/Builder work — a green release with an unexplained
regression is forbidden. `baseline-pytest-b10.md` covers a separate Direct-concurrency regression
(now approved-closed in v6.3), not these 6.

### D.7 Vector circuit degradation = not a v6.3 regression
`w4-live-probes.md:31-39`: `embedding_quota_state` = `primary/fallback_1/fallback_2 exhausted`,
`next_allowed_at=1792109100` (2026-10-16 00:05 UTC), note `parked kind=spend est=utc_day_end`;
`EMBEDDING_GENERATION_PAUSED | index=graph_facts_vec | reason=paused_rate_limit`. v6.3 diff on
`embedding_control_plane.py` / `graphrag_rebuild.py` = 0. Correction: `no such module: vec0` was a
B11-script artifact; on prod `sqlite-vec` is available.

---

## Blocking questions (consolidated)

1. **(A)** `prompts.direct_l1_planner_system_prompt`: editable registry key vs read-only code default?
2. **(A)** mod_direct reachability of all three Direct prompts; mobile one-extra-tap; honest empty-state reasons (seed vs RBAC-hidden vs filtered).
3. **(B)** tdesktop `hidden` accepted until platform e2e, or deliver fullscreen with visual proof? Confirm installed Telegram Desktop version behavior (EXTERNAL_UNVERIFIED).
4. **(B)** Real-client fullscreen matrix (Windows/Android/tdesktop) — owner run or explicit waiver (no mock-DONE).
5. **(C)** Prod 24–48 h initiative telemetry per chat (see C.4) — request, do not fetch.
6. **(D)** Minimal safe fix for glass-teststand exposure (remove from prod static + update 3 tests, or add auth).
7. **(D)** Bind `requirements-map.json` candidate/deployed = `c2775a54`, fill live statuses + evidence, re-run release gate; then close/waive the 14 `BLOCKED_REAL_HUMAN_GATE`.
8. **(D)** Classify the 6 pre-existing pytest failures (fix vs re-pin) with RCA.
9. **(D)** Provider confirmation of the shared embedding proxy reset horizon; accept a non-destructive "primary missing / degraded pool" WARN.

## Non-blocking notes
- Local doc-only commits ahead of prod (D.1) are expected; no code drift.
- "25 initiative jobs/day" is a completed-job count, not the 300 s schedule (C.1).
- `deploy_commands.txt` (creds) is untracked and outside git (`final-audit-current-task.md:84-86`).
