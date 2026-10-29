# Context & UI Audit — EVOL (read-only, 30.10.2026)

Scope: message-context pipeline, memory quality paths, EVOL-014 prerequisites, backend surfaces EVOL-019..021, DB schema, web UI inventory. Repo HEAD 3193b657 (master). Facts only, no changes made.

---

## 1. EVOL-015 — Telegram quote (reply/quote pipeline)

**Client library:** aiogram `>=3.31.0,<4.0.0` (requirements.txt:1). Installed in venv: **aiogram 3.31.0**. Verified in venv: `Message.model_fields` contains `quote`; `aiogram.types.TextQuote` exists (Bot API 7.0 TextQuote: text/position/entities/is_manual). **The SDK delivers the quote field** — no MTProto/Telethon in the project.

**Ingress (single catch-all observer):**
- Router registration: `bot.py:899` (`dp.include_router(summary_observer_router)`), router defined `handlers/summary.py:35` (position 0a), catch-all handler `@summary_observer_router.message()` `handlers/summary.py:318`.
- **Quote extraction: `handlers/summary.py:366-381`** — reads ONLY `quote.text` (`getattr(message, "quote", None)` → `getattr(quote, "text", None)`) and `quote_author_id` from `reply_to_message.from_user.id`.
  - **DROP POINT #1 (ingest): `quote.position`, `quote.entities`, `quote.is_manual` are never extracted.** No other place in the codebase reads `message.quote`.
- Storage: `message_identity.save_live_message` (`services/message_identity.py:154`, signature `quote_text=None` at :160, normalization :181, payload :235) → column `smart_messages.quote_text` (additive column `("quote_text","TEXT")` `services/database.py:304`).
- `edited_message` handler `handlers/summary.py:485-514` records only text/caption revisions (no quote relevance).

**Reply-context assembly (prompt) — where the stored quote does NOT reach:**
- Thread chain: `ChainItem` (`services/thread_chain.py:30-42`) fields = uid/name/text/is_bot/ts/item_id/forward_source — **no quote field**. `format_chain_line` `thread_chain.py:200-216` → `format_context_item` (`services/canonical_context.py:252+`) renders ts/author/item_id/forward_source/text/target-marker only — **no quote parameter at all**. `<Conversation_Thread>`/`<Conversation_Branch>` render: `direct_chat_service.py:9811-9849` (`_render_thread`), chain collection `:9764-9785`.
- Global-Context verbatim window: SQL SELECTs **exclude quote columns**: `get_smart_window` `database.py:7541-7552` and `get_recent_messages` `database.py:7577-7631` (both select only id/user_id/chat_id/text/reply_to_id/timestamp/media_type/author_name/is_forward/forward_source/tg_message_id; `get_smart_raw` :7554-7575 same). Row renderer `_context_row_line` `direct_chat_service.py:9742-9759` — no quote. **DROP POINT #2 (read/SELECT).**
- MCA-22 quote resolver (attribution only): `_resolve_quote_live` `direct_chat_service.py:7600-7634` passes `tg_quote_text=row["quote_text"]` (:7627); gate `MCA_CANONICAL_ATTRIBUTION_ENABLED` default **ON** (`services/mca_gates.py:996-1003`).
- What the resolver's result contributes to the prompt: only an attribution **flag/directive** — `<Speech_Understanding>` block renders the fixed line «Цитата принадлежит её автору: не приписывай чужие слова себе…» (`services/claim_envelope.py:844-879`, flag source `u.quote` :850; presence derived in `direct_chat_service.py:6198-6212`). **The quoted text itself never enters any prompt block** (neither Current_Question, nor Thread/Branch, nor Global_Context). This is the effective loss the owner observed.
- Fact-extraction input also drops it: `_build_batch_text` = `[author]: text` lines only (`services/summary_memory.py:942-958`).
- Dead-in-prod renderer: `format_canonical_envelope` (`services/canonical_messages.py:232-269`) DOES render `> {quote_text} (автор цитаты: …)` but is referenced **only from tests** (`tests/test_mca22_core_round1027.py:257`, `tests/test_mca22_truthset_round1027.py:84,114`).
- Diagnostic API already surfaces quote fields: `web/api/memory_agi.py:1100-1101` (`quote_present`, `quote_speaker_entity_id` in attribution trace).

**Conclusion:** quote survives SDK → ingest(text only) → DB, but is dropped on every context-build read path (SELECT columns, ChainItem, format_context_item) and by design never serialized into a prompt; only a generic attribution directive reaches the model.

---

## 2. EVOL-006/007 — memory facts pipeline and the «Новые факты» widget

**Extraction schedule (EVOL-007 freshness bottleneck):** `SummarySchedulerService` (`services/summary_scheduler.py:125-152`) — APScheduler **CronTrigger hour=0,6,12,18** (4 runs/day) in `limits.summary_timezone`; per-chat skip on disabled (B06.1, :193+). Running-summary additionally triggered on window fill (`services/summary_memory.py:2730-2766` `get_window_messages`, `_schedule_running_summary` :2768+). Graph extract uses background channel with deadline/attempts (`_GRAPH_EXTRACT_TIMEOUT_SECONDS=120`, attempts 2, `summary_memory.py:5540-5541`).

**Extraction chain:** batch of raw rows → `_build_batch_text` `[author]: text` (`summary_memory.py:942-958`) → LLM system prompt `EXTRACT_PROMPT` (`services/summary_prompts.py:988-998`) → `parse_triplets` → `_write_graph_triplets` (user-quota check `summary_memory.py:3508-3511`, `target_user` attribution :3534, provenance attach :3579-3584). Chunked retry phase A/B when `GRAPH_EXTRACT_MAX_BATCH_FAILURES` not hit (`:5538+`).

**EVOL-006 structural gap (prompt-level):** `EXTRACT_PROMPT` has **no stability/temporality dimension**: `subject` = "имя_участника или тема", `subject_type` only `user|topic`; no classes for one-off request / quote / hypothetical character / news repost / intent. Same for the memorize-path prompt `FACT_EXTRACT_PROMPT` (`summary_memory.py:143-157`, canon R46-2 + «ФОКУС НА СОДЕРЖАНИИ» paragraph) — it filters media-format facts only. `PREV_FACT_EXTRACT_PROMPT` (:143-150) is the byte-snapshot of the previous canon. Retry prompt `_FACT_RETRY_SYSTEM_PROMPT` :173-178 (JSON-shape only). Fact origins enum `_FACT_ORIGINS` :159-163 (`chat_history, search_fact, youtube_content, web_content, bot_direct_reply, voice_transcript, video_transcript, user_memory`).

**Widget «Новые факты» (what it actually queries):**
- UI: status page card `web/index.html:10473-10500`; computed `factsFeed` `web/app.js:5574-5587` (maps `created_at`/`ts` **if present** — they never are), loader `loadDossierFeed` `app.js:10800-10825`.
- API: `GET /api/oversight/dossier_feed` (`web/api/oversight.py:380-424`, limit 1..40 default 12; fail-open empty feed).
- Data: `db.dossier_feed` (`services/database.py:11248-11277`) — `graph_facts WHERE status='confirmed' AND target_user IS NOT NULL AND fact<>'' AND (expires_at IS NULL OR > now)`, fresh pool `limit*20` by `id DESC`, then `ORDER BY RANDOM() LIMIT n`. **SELECT returns only chat_id/name/fact — no created_at** ⇒ the widget cannot show dates (matches owner observation). Semantics: "random sample of recently written confirmed dossier facts", not "facts from the latest extraction run".
- Dedup/idempotency: `person_fact_exists` (`database.py:11295+`), `meme_exists` :11284+; statuses `confirmed`/`unconfirmed`/`chat_meme` (no CHECK, comment :11280-11282).

**Sleep / Deep Sleep / Personality scheduling:**
- DreamWorker (`services/dream_worker.py`): two APScheduler jobs on `IntervalTrigger(minutes=tick_minutes)` (:648-662), enabled resolved per-tick; global master `memory.dream_enabled` (:564-567); per-chat `enabled` (:892-894); belief decay under `flags.belief_decay_enabled` (:817-820).
- Deep Sleep constants: lookback 12h, min anchor age 90d, min historical 2, **cooldown `_DEEP_SLEEP_MIN_INTERVAL_HOURS = 20`** (:280-289), job `deep_sleep_tick`; runtime key `memory.deep_sleep_min_interval_hours` with one-off migration 20→6 gated by `DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED` default **False** (`services/config_migrations.py:65-69,165-203`).
- Personality: no separate scheduler class; persona state lives in PG (`services/pg_db.py`: `persona_state` :216, `personas` :232, `persona_traits` :261); evolution writes sourced `deep_sleep` (`services/bot_persona.py:415,631,659`).

---

## 3. EVOL-014 prerequisites

### (a) Quantum random contour
- Single service: `services/mca_random_source.py` (mca-10a, ADR-1028-14; header contract :1-42). Components: `RandomSourceService`, `ExplorationPolicy`, `CoreDreamRandomSource` (mca-06 adapter), `AnuClient`, `RandomStore` (v27 tables). "Second mechanisms forbidden".
- Modes `quantum | pseudorandom` (:65-67); selected setting `memory.random_source` (:119) vs effective resolved per draw; provider `ANU Quantum Numbers` (:70).
- Config keys: `keys.random_quantum_api_key` (:123), `keys.random_quantum_endpoint` / `_plan` / `_batch_length` / `_data_type` / `_request_timeout_seconds` (:124-128), refill `keys.random_quantum_refill_low_watermark` / `_buffer_max_values` (:129-130). Key never logged (fingerprint sha256[:12] only, :28-29).
- Gates: `MCA_RANDOM_SOURCE_ENABLED`, `MCA_RANDOM_QUANTUM_ENABLED`, `MCA_RANDOM_REFILL_ENABLED`, `MCA_RANDOM_EXPLORATION_ENABLED` — default ON (:35-41); resolvers `mca_gates.random_quantum_enabled` (`mca_gates.py:1339`), `random_quantum_hex_block_size` (:1688).
- Failure modes: `fallback_to_pseudorandom` is a **user setting, not kill-switch** (:20); circuit-breaker env `MCA_RANDOM_CIRCUIT_FAILS`/`_COOLDOWN_SECONDS`/`_MIN_REQUEST_INTERVAL_SECONDS` (:38-39); rejection sampling without modulo bias, n=1 doesn't consume a draw (:21-22); exploration purposes closed set (10a) + exactly 5 sanctioned extensions in 10b (:77-86) — **a new "meme trigger" purpose requires a sanctioned 10b-style extension**; ineligible measurements never randomized (:104-107). Telemetry codes `random_fallback`, `quantum_activated` (`services/mca_events.py:260,281`). DB: `source TEXT NOT NULL DEFAULT 'quantum'` (`database.py:1069`).
- Initiative already consumes this contour (skip reason `random_fallback`, `initiative_observer.py:236`).

### (b) Image generation
- `services/image_generation.py` (131KB). Config keys: `models.image_base_url` (:80), `models.image_model` (:81), `models.image_get_mode` (:82), `keys.image_api_key` (:83), `flags.image_generation_module_enabled` (:84); settings fallbacks `IMAGE_BASE_URL/IMAGE_MODEL/IMAGE_GET_MODE/IMAGE_API_KEY/IMAGE_GENERATION_ENABLED/IMAGE_GENERATION_MODULE_ENABLED` (:211-218); per-chat override via `resolve_module_enabled` (:211-228).
- Availability: `probe()` (:1428-1476) — same universal request path as generation, never sends to Telegram, does not spend per-chat budget; returns `ProbeResult(ok/status_code/reason/body_excerpt/latency_ms/model/mode)`, key redacted (:1436, `_redact_secret`). Errors: `ImageGenerationError(reason, provider_body sanitized)` (:138-148).
- **Daily quota infrastructure already exists** (directly reusable for EVOL-014): env-only `IMAGE_DAILY_LIMIT_ENABLED` default ON (:242-249); `image_reserve_mode()` (:252-272) — atomic reserve/journal/commit-release vs honest legacy reasons (`kill_switch_off`, `budgets_off`); per-chat **calendar day in chat timezone** (`worker_budget.image_day` :613, `image_timezone` :623, `image_next_reset` :628), limit key `limits.image_daily_limit` (`services/worker_budget.py:66`, per-chat resolve :427/:966); honest reset note `image_quota_reset_note` (:275-290); shared budget note (:293+).
- Prompt assembly: `services/image_prompt_compiler.py` — `PromptComponent` (:44), `CoverBrief` (:56), `CompiledPrompt` with `prompt_limit_exceeded` (:91), `compile_prompt` priority P0/P1 (:189+), semantic-compression kill-switch `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED` (:32-37), legacy path `_compile_prompt_legacy` (:287+).
- Model capabilities: `services/image_capabilities.py` — `PromptLimit` (:193), `ImageModelCapabilities` (:215, edit_supported/references), manual limits map (:100-164), dynamic-limit gate (:177), provider-error parsing (`extract_provider_error` :340, `looks_like_prompt_too_long` :321), env overrides `COVER_STYLE_CAPABILITY_OVERRIDES` (:420-425), `conservative_unknown` (:257).

### (c) Initiative
- `services/initiative_observer.py` — `InitiativeObserverRunner` (:881+): durable task `initiative.observe` (state/checkpoint in `task_jobs` payload :901-929), phases **scan → evaluate → diagnose** (:884-887); cursor inheritance across restarts (:931-960).
- Output kinds: `INITIATIVE_OUTPUT_KINDS = ("initiative_reply",)` (:136) — a meme capability would extend this tuple with its own kind.
- Gates/keys (:277-286): master `flags.initiative_observer_enabled` (+ K1 `intents_enabled`, `observer_enabled` :326-338); per-chat `initiative.enabled` (`chat_observer_enabled` :361-368); profile `initiative.frequency_profile`, `min_gap_seconds`, `max_replies_per_day`, `day_window_seconds`, `max_replies_per_topic`, `eval_min_messages`, `eval_min_interval_seconds`, `eval_llm_budget_per_day`. Profiles rare/normal/active with `eval_min_interval_seconds` 6h/2700s/1200s (:166-180).
- Publish/recheck/send — single existing entry `handle_initiative` (`services/direct_chat_service.py:10620`, mca-09; documented `initiative_observer.py:8`); durable intent delay 900s (:289).
- Skip-reason taxonomy `REASON_LABELS` (:225-265) already includes `random_fallback`, `recheck_demoted`, `recheck_passed`, `direct_pending`, `delivery_not_text`, `no_opportunities_24h`, etc.; `reason_label()` R17-safe (:268-273).
- API surface exists: `web/api/initiative_vitality.py`.

---

## 4. EVOL-019/020/021 backend surfaces

### (a) Vision «Проверить»
- Endpoint: `POST /api/vision/test` (`web/api/routes.py:2274-2328`). RBAC: global admin OR `can_view_key_value(keys.vision_api_key)`; server rate-limit 10s/user (:2229-2245). Always HTTP 200 with verdict fields (`ok`, `capability`, `image_input`, `visible_reason`, provider/model/api_type, refreshed `state`).
- What it actually does: `mca_vision.probe_connection()` (`services/mca_vision.py:867-951`): stage 0 offline config validation; **stage 1 sends a real generated valid image 512×512+** (`probe_images()` :903) via chat-completions; modality refusal → `no_vision`; "invalid image" → retry with second image (:940-951); other 4xx → text-stage cross-check; timeout/transport/5xx → transient; verdict cached per (endpoint, model, config_revision) (:881-882).
- Success classification `_classify_success` (:843-864): **ok = 2xx + non-empty `choices` and no error-object**; `empty_completion` (no choices) is honest `unavailable`. **It does NOT verify the completion content describes the probe image** — recognition quality/real content is unproven. So current «Проверить» proves: config + reachability + image acceptance + shape-valid completion; it does not prove meaningful recognition (EVOL-019 gap confirmed).
- State endpoint: `GET /api/vision/state` (:2331-2360) — `runtime_snapshot` without network calls. UI card: provider block `b.id === 'vision'` (`web/index.html:2143-2164`, facts from /api/vision/state; test button via generic `testBlock` mechanism, comment :2166).

### (b) Experience pipeline (EVOL-020)
- `services/mca_experience_jobs.py` (MCA-16, ADR-1028-15): durable job `kind="experience.review"`, coalesce `experience.review:global` (:1-6). Triggers: cadence `memory.experience_review_cadence` (hourly/daily/**weekly default daily**) from existing `MemoryMaintenanceService` + immediate enqueue on substantive correction (:8-11).
- Steps per run (:13-16): capture-cursor → propose → validate → activate/suspend → outcome-link → utility-update → recheck → prune; idempotent (UNIQUE keys v28).
- **No LLM at all**: proposals are deterministic `CANONICAL_RECOMMENDATIONS` (:19-21); randomness read-only observation of `mca_random_draws` (:22-26); capture only from `mca_experience_feedback` + notable tool terminals in `mca_events` (:27-29); `unknown` outcome never updates success/failure (:30-32); master switch `EXPERIENCE_LEARNING_ENABLED` (:547).
- Storage v28: `mca_experience_episodes`, `mca_experience_feedback`, `mca_lessons` (`services/database.py:3754-3775`, DDL :1133-1192). Runtime hook in direct chat: `mca_gates.experience_lessons_enabled()` (`direct_chat_service.py:7549`).

### (c) Memory stories/episodes (EVOL-021)
- Builder: `services/mca_episodes.py` — pipeline `mca05-episodes-1` (:53); deterministic segmentation (hard gap 30 min, soft 10 min, reply-horizon 6h, :57-60); continuation candidates cap 8, story claims cap 120, episode component cap 200 (:63-65).
- Honest-content states (B08, derived without DDL): `ready` (non-empty summary OR ≥1 claim) vs `insufficient_sources` (:70-76); read-side fallback strings: **`NO_SOURCES_MESSAGE = "Не удалось восстановить сюжет: нет источников"` (:77)**, pending message :78-79. Legacy auto-stub titles «Эпизод <ts>» / «История <ts>» detected by regex and replaced with honest display (:84-86, `is_auto_stub_title` :295).
- Deterministic card: `deterministic_card` (:255-282) — title = key message text [:120], summary = «Хронология по исходным сообщениям (N шт.)…», claims from stable keys. LLM rebuild path exists separately (extractor `episodes_extract-1`, prompts in `services/mca_episode_prompts.py`).
- Backfill: `services/mca_episode_jobs.py` — durable `episodes.backfill:<chat_id>` (:40-55), kill-switch `episodes_backfill_enabled` (:77), budget pause reason `story_backfill_paused_budget` (:42), bounded empty-episode content backfill per run (:44-48), yields to direct path (:16, :48-51). **"Backfill: не запускался" in UI = no such task_jobs row was ever created/enqueued.**
- Widget API: `web/api/stories.py` — `GET /stories/summary` (:220), `GET /stories/feed` (:250), `GET /stories` (:281), `GET /stories/{id}` (:338), `POST /stories/{id}/action` (:392).
- Why the owner sees many fallbacks: episodes whose build produced no summary/claims (or only auto-stub titles) are stored as technical rows; the feed surfaces them with `insufficient_sources` rendering — matches screenshot «Краткое содержание: неизвестно», «исход неизвестен».

---

## 5. DB schema versions and additive-migration mechanism

- **SQLite:** versioned by `PRAGMA user_version` cascade — constants `database.py:145-203+`, latest `_SCHEMA_VERSION_HUMOR_SAMPLES = 37` (v36 alias also defined). Registry book since v13: table `schema_migrations (version INTEGER PK, name, applied_at, checksum)` (`database.py:190-197`); contract (mca-14, ADR-1027-1): **additive only — `CREATE TABLE IF NOT EXISTS`, old tables/ids untouched** (:183-189). Column additions via `ALTER TABLE ... ADD COLUMN` steps (e.g. edges.fact_id 9→10 :161-165; graph_facts tg_message_id/forward_from 11→12 :175-181). Some auxiliary stores are created additively **without** bumping user_version (exact-match cache :2224, smart_cache :2248-2318). Example additive column: `smart_messages.quote_text` (`database.py:304`).
- **PostgreSQL:** `services/pg_db.py` — idempotent DDL at startup, `DDL_STATEMENTS` tuple of `CREATE TABLE IF NOT EXISTS` (:33+, header :3); explicit handling needed for new columns on existing tables (comment :124). **No versioned PG migration mechanism found** (no schema-version table like SQLite's). `services/config_migrations.py` contains config/default-value migrations (dream thresholds :106, global budgets :135, deep_sleep :165, context limits :207, factcheck :248, image provider defaults :313) — data, not schema.
- `migrate_history/` holds only historical JSON logs (10.08.2025.json, 10.2024.json, 2026.json) — not code.

---

## 6. Web UI inventory

**Stack:** FastAPI app (`web/app.py:152` `create_app`) serving one Telegram Mini App SPA. Frontend: **Vue 3 Options API, global build, zero-build** (`web/app.js:2`; vendored `vue.global.prod.min.js` `index.html:12248`; DOMPurify 3.4.15 :12252). **Tailwind is pre-built** (comment `index.html:18-21`: build = `npx tailwindcss@3 -i web/static/tailwind.input.css -o web/static/vendor/tailwind.css --minify`; ADR-1016-2 §3; Play CDN forbidden). No bundler; `app.js` ≈1.33 MB, `index.html` ≈929 KB (all pages + `x-template` components in single files).

**Serving:** `/web/` index with `?v=APP_VERSION` substitution (`app.py:266-286`); `/static/app.css` served before static-mount with no-cache + font-subset version (:288-311); mounts `/web`, `/static` (:363-370); `/healthz` (:324-334); signed `/media/{file_id}` (:341-361).

**API routers** (`app.py:180-260`): main `api_router` (/api; `web/api/routes.py` — big mixed file incl. /vision/*, /random/*, factcheck temporal), plus: chat_lore, memory (memory_agi.py), memory_overview, initiative_vitality, avatars, access (/api/access), gates, budget, oversight (/api/oversight; oversight.py + oversight_router.py), anticliche, analytics, summary_test, cover_styles, stories, oversight17c (/api/oversight), analytics_viz, speech. Module files in `web/api/`: access, analytics, analytics_viz, anticliche, avatars, chat_lore, cover_styles, deps, gates, initiative_vitality, memory_agi, memory_overview, oversight, oversight_router, routes, speech, stories, summary_test.

**Routing:** hash-based, vue-router NOT used (`app.js:1504-1599`): `ROUTE_TO_TAB` :1509-1559, `TAB_TO_ROUTE` :1560-1575, `ROOT_ROUTES` :1576-1577, legacy aliases :1580-1592, `ROUTE_PARENT` :1593+. Page map:
| Page | Route | Backend |
|---|---|---|
| Статус (витрина, «Новые факты», бюджеты) | `#/` (+ `#/status/graph` full graph) | /api/status, /api/oversight/dossier_feed, /api/workers/budget |
| Аналитика | `#/oversight` (tab `oversight`, label «Аналитика», `app.js:333-334`) | web/api/oversight.py, oversight_router.py, analytics.py, analytics_viz.py |
| Как это работает | `#/how` | static info |
| Модули (+ Бюджеты/Изображения/Vision) | `#/modules`, `#/modules/budgets`, `#/modules/images`, `#/modules/vision` | /api/config (flags/limits/keys), /api/vision/* |
| PERMsoc | `#/permsoc` | /api/config permsoc |
| ИИ (провайдеры, промпты, smart-cache, имена, Личность, Речь) | `#/ai`, `#/ai/llm`, `#/ai/prompts`, `#/ai/smart-cache`, `#/ai/names`, `#/ai/persona`, `#/ai/speech` | /api/config, provider probe blocks |
| Память (RAG, Лор, Связи) | `#/memory`, `#/memory/rag`, `#/memory/lore`, `#/memory/relations` | memory_agi.py, chat_lore.py |
| Доступы (роли/локальные/админы) | `#/access`, `#/access/roles`, `#/access/local`, `#/access/admins` | access.py |

Config tabs: 23 incl. `mod_vision`, `mod_initiative` (`TAB_SECTION_ORDER` `app.js:343-354`) — the Initiative settings home for EVOL-014 UI.

**Liquid glass renderer:** vendored **`@liquidglassjs/core` 0.5.3**, single mount point `web/static/glass.js` (HOTFIX10, ADR-1025-18 D1). Real refraction = `backdrop-filter: url(#lg-lens)` enabled only after render-probe (`web/static/glass-probe.js`, U08.3); WebKit → honest Tier B frost fallback (`web/static/glass-refraction.js`, WIN-GLASS-P0, WebKit bug 245510). Tokens/tiers A/B/C: `--glass-bg/-bg-strong/-blur` `web/static/app.css:49-60`.
**Polygonal background:** `web/static/polygon-background.js` — "POLYGONAL LUMINESCENCE" Canvas 2D scene (round 10.26, ADR-1026-3, kill-switch `UI_POLYGON_BG_ENABLED=OFF`); plus `web/static/aurora-flow.js` — Dark Aurora Flow fullscreen canvas + fragment shader (vendored OGL 1.0.11, Canvas2D fallback, HOTFIX9 ADR-1025-17 D6; palette #090D17/teal/blue/violet).

**Design tokens / CSS architecture:** single canonical block `:root` at `app.css:4-60` ("Дизайн-токены v2", palette §8 ADR-1025-9 D1): surfaces `--surface-0..3`, `--surface-border`, `--work-surface-bg`, text `--text-1/2/3`, brand teal/purple/magenta/lilac/indigo, status `--ok/--warn/--err` (+bg, `--err-text`), gradient tokens with speeds, Inter typography scale, radius/shadow/durations, `--page-padding`/`--navbar-height`, glass tiers. Reusable components: `.card` :404, `.badge` :744-755, `.badge-btn` :2182, `.modal-backdrop` :982/:1800, `.modal-card` :1579-1598, sticky-save :1932-1937. Beyond tokens, styles are per-page/section rules in the same single app.css (~4.6k+ lines) + Tailwind utilities in markup; app.css is served with server-side version substitution.

**Fullscreen mechanism:** `web/static/fullscreen-policy.js` — `FullscreenPolicy` matrix <client capability × launch mode> → TMA-fullscreen (asap8-v6.3 U07 + FS-HOTFIX 18.10); plain IIFE, CSP-safe, no Vue, no inline handlers; header button `.header-fs-btn` (also referenced by glass hotfix scope).

**Modal components:** pattern `.modal-backdrop` + `.modal-card` inline `v-if` overlays in index.html (module modal :4228-4256; access «Роли» :6722+, «Матрица ролей» :6774+; more of the same pattern). Reusable `x-template` components: `secret-field-tpl` :12059, `override-stack-tpl` :12094, `kv-editor-tpl` :12164, `list-editor-tpl` :12211. Sticky-save dirty-tracking in `app.js:5594-5609`.

**Existing search boxes:** chat scope switcher (`index.html:249`, `scopeSearch`), module search `.module-search` (:4145), execution filter (:5594), graph search `.graph-search__input` (:9979, :11111), speech block search (:9250), speech examples search (:8798), two generic page filters (:6830, :11347).

**Other static assets:** `execution_graph.js` — ExecutionGraph adapter (backend metrics → normalized graph → UI, ADR-1025-19); `telegram-init.js` + vendored `telegram-web-app.js` (`index.html:17`); self-hosted Material Symbols subset via PUA codepoints (`ICONS` map `app.js:366+`).

---

## Incidental notes
- `smart_messages` carries `reply_to_author_id`/`quote_author_id` since v16 but neither thread/window SELECTs nor extraction batch include them (same read-gap as quote_text).
- Attribution trace (`/api/memory/attribution/trace`, memory_agi.py:1077-1104) already exposes quote presence/speaker — useful for EVOL-015 acceptance diagnostics (`quote_present` vs delivered-to-context distinction is NOT yet instrumented).
- `Chat/Scope switcher` today = single dropdown with `scopeSearch` (index.html:249); no shared component — EVOL-023 scope confirmed.
