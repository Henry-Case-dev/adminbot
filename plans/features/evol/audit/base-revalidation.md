# W0 audit revalidation on production base 2.58.141 (read-only, 30.10.2026)

Re-verification of `backend-defects-audit.md` + `context-ui-audit.md` (both written against
master `3193b657`, 304 commits ahead of the production line) against the **evol/impl base**
= production `2.58.141 @ 5346ee76` + docs (merge `2e612d5c`, HEAD `4aa91baf`).
Method: every material claim re-opened in the worktree; audited files diffed
`git diff 3193b657 HEAD -- <file>` to separate line shifts from mechanism changes.

Verdicts: **CONFIRMED** (mechanism + lines transfer) / **CORRECTED** (mechanism holds, lines/affect
details changed) / **REFUTED** (claim false on production base) / **CHANGED** (mechanism replaced).

File-delta baseline (3193b657 → HEAD): embedding_control_plane 295, mca_vision 648,
prompt_migrations 240, prompt_registry 245, smart_cache 24, handlers/summary 22,
database 603, direct_chat_service 584, summary_memory 115, initiative_observer 68,
routes.py 98, app.js 28, index.html 8.

---

## CRITICAL FINDING — EVOL-010 root cause is IN the committed production code

Master audit F7 hypothesized a deployment-state defect (stale pyc / on-disk file differing from
git) because on master the ContextVar `_LAST_EMBED_META` is defined at module level, making the
NameError "not provable from repository code". **On the production base this is refuted.**

`git grep _LAST_EMBED_META HEAD` → **one single hit**: the `.set()` call at
`services/embedding_control_plane.py:1373`. The ContextVar definition (master `:2474` comment,
`:2488-2489`), the `MODEL_SOURCE_*` constants (master `:2470-2473`) and the compat-probe consumer
(master `:3087`, `:3097`) **do not exist** in the production version of the file
(diff hunks: `@@ -2465,29 +2465,6`, `@@ -3037 +2949`, `@@ -3082 +3097` — all removals of exactly
this machinery). Lines 1..2464 are byte-identical between master and production; everything the
production file dropped sits after `:2465` — except the `.set()` at `:1373`, which survived.

⇒ On 2.58.141 every successful `EmbeddingExecutor.embed` HTTP call deterministically raises
`NameError: name '_LAST_EMBED_META' is not defined` at `:1373`, immediately after the provider
returns 200. Consequences for W1:
- **No server-side runtime evidence is required** to prove root cause (master audit's "Required
  runtime evidence" items 1–5 are obsolete as *proof of cause*; they remain useful as cleanup).
- **Fix strategy changes**: minimal fix = remove the dead 4-line telemetry `.set()` block at
  `:1373-1376` (it has **no consumer** on production: `_compat_probe_once` no longer reads it) OR
  restore the definition + consumer; classification hardening in `_on_error` (below) stays
  mandatory; deployment-state repair is no longer a fix step.
- The observed prod telemetry (`embed transport error | error=NameError`, `processed=0`,
  fake `EmbeddingBudgetExhausted`, `quota_group=unknown | next_allowed_at=-`) matches this
  deterministic path exactly.

---

## EVOL-010 — embedding NameError → fake budget exhaustion → backfill stalls

| # | Claim (master audit) | Verdict on production base | Note for implementer |
|---|---|---|---|
| F1 | Failure site `ecp:1373` `_LAST_EMBED_META.set(...)` in `EmbeddingExecutor.embed` | **CONFIRMED** (`:1373`) — and upgraded: definition missing entirely (see above) | Remove-or-restore decision needed; no consumer exists on production |
| F1 | ContextVar defined `:2488-2489`, consumer `_compat_probe_once :3087/:3097`, both from `60789cff` | **REFUTED** for production base | Definition + consumer absent at 2.58.141; `import contextvars` present (`:70`) |
| F2 | Failure AFTER successful HTTP call | **CONFIRMED** (mechanism deterministic from code) | `embed transport error` after `LLM embed_once OK` reproduced by code path |
| F3 | `_on_error` `:1464-1544` classifies by exception-name; everything non-Auth/non-429 → `"transport"` at `:1543-1544` | **CONFIRMED** (`:1464` def, `:1543-1544` fallback) | Classification hardening (NameError/AttributeError/TypeError → non-retryable + exc_info) still valid and required |
| F4 | Retry loop `:1338-1412`; `_ATTEMPT_BUDGET=4`; transport backoff `:1401-1406`; final `EmbeddingBudgetExhausted` raise `:1410-1412`; CoolingDown `:1394-1398`; second raise "no usable credential" `:1349-1351` | **CONFIRMED** (same lines; `_ATTEMPT_BUDGET=4` at `:1251`) | Fake-budget chain identical; `EmbeddingBudgetExhausted` (`:1088`) carries neither `group_id` nor `next_allowed_at` (only `EmbeddingGroupCoolingDown` `:1075-1081` does); `_SERVICEABILITY_ERRORS` tuple `:1097-1098` (T-4878) unchanged |
| F4 | `summary_memory._EmbedBatchState.mark :322-326` exposes raw class name; defaults `quota_group=""`, `next_allowed_at=None`; `_embed_fail_reason` maps to `budget_exceeded` | **CONFIRMED** (`mark` `:322-326`, `state=type(exc).__name__` `:324`; `_embed_fail_reason` `:365-381`, mapping `:371-372`) | Telemetry indistinguishability ( CoolingDown vs BudgetExhausted vs no-credential) still to fix |
| F5 | Graph backfill loop `:2650-2673`: `_embed(batch)` raises → log + `break` → `processed=0` forever | **CORRECTED** → loop now `summary_memory.py:2645-2680`; log line at `:2662-2663`; `break` `:2664` | Mechanism identical; deterministic per-batch failure ⇒ `processed=0` |
| F5 | Facts saved text-only upstream (`:3853`) | **CORRECTED** → memorize path `summary_memory.py:3496-3513` (`batch.unavailable` → dedup skipped; T-4878 serviceability gate `:3508`); text-only outcome mapping `:3297` (`text_only_vector_deferred → success/embed_deferred`) | `FACTS_EXTRACT=success` + `EMBED_API_DEFERRED` behavior unchanged |
| F5 | Backfill is in-process (`_EMBED_BACKFILL_TICK_INTERVAL=600.0 :303`) | **CONFIRMED** (`:303`) | — |
| F6 | Panel "durable job missing" `summary_memory.py:2050-2061` via `latest_rebuild_job` | **CORRECTED** → `:2055-2063` (message at `:2063`); `latest_rebuild_job` in `services/graphrag_rebuild.py:705`, `FAILED_BUILD_JOB_STATUSES :100` | Pre-existing 2.58.114+ defect unchanged; separate work item |
| F7 | Root cause not provable from repo; deployment-state repair first | **REFUTED** | Root cause is committed code (missing definition); server checks demoted to optional hygiene |

---

## EVOL-011 — `vision_adapt outcome=failed strategy=original reason=fits error=""`

| Claim | Verdict | Note |
|---|---|---|
| `_emit_adapt` emits `outcome="success"` only for `status in ("ready","no_text")`; `error` = exception class; parse failure ⇒ `error=""` | **CONFIRMED** — `_emit_adapt` now `mca_vision.py:1946-1972` (success gate `:1963-1965`; `error_json={"strategy","reason","calls","error":error_class}` `:1969-1970`; no exception ⇒ `error_class=""`) | Same information loss |
| Non-JSON payload → `VisionAnalysis("failed",…)` from parser (`:1459`, `:1462`) | **CORRECTED** → parser is now `parse_analysis_payload` `:1633-1668`; non-JSON `:1640-1641`, non-dict `:1643-1644` | HTTP 200 + non-JSON → `failed` mechanism unchanged |
| Reason stored but not emitted | **CHANGED (partially fixed upstream)** — `VisionAnalysis` gained field `error_reason: str = ""` (dataclass after `self_reported_confidence`); parser passes `"parse_error"` as 6th positional (`:1641`, `:1644`) | **`_emit_adapt` still does not read `error_reason`** — reason_code still lost in telemetry. W1 fix is now trivial: include `getattr(merged, "error_reason", "")` in `error_json` |
| `_adaptive_call` bounded call `:1733-1738`; success-path emit `:1752-1754`; except-path `:1758-1762` | **CORRECTED** → `_adaptive_call` `:1840-1848`; adaptive driver is now `analyze_adaptive` `:1876-1943` (emit `:1933-1935` success, `:1940-1942` except); normalize-retry `_adaptive_retry` `:1851-1873`, retryable-rejection gate `:1920-1932` | Chain preserved; new `MCA_VISION_NORMALIZE_ENABLED` gate + `image_normalize.plan_vision` preprocessing `:1887-1913` |
| Segment-merge yields `failed` only with zero analyses (`:1644-1652`); `ready`/`no_text` at `:1483-1486` | **CORRECTED** → `merge_segment_analyses` `:1798+`; parser success statuses at `:1666-1668` | Same semantics; new statuses `unreadable`/`unsupported` exist in pipeline event mapping (`:2312`, `:2554`, `:3512`) — do not conflate with parse `failed` |

Verdict on the defect itself: unchanged — real terminal parse failure of the vision model
response; WARN unactionable because `error_reason` is not propagated. Minimal fix unchanged in
intent, now one field read away.

---

## EVOL-012 — prompt migration «кастом юзера — НЕ трогаем» + EVOL-016 foundation

### EVOL-012 mechanism

| Claim | Verdict | Note |
|---|---|---|
| `migrate_prompt_canons` runs every startup from `bot.py` after `cache.init()` | **CONFIRMED** — `bot.py:1347` `cache.init()`, `:1381-1382` `migrate_prompt_canons(cache)` | — |
| String-equality gate: `==new` → attest; `==prev` → set; else WARNING + skip | **CORRECTED** → `prompt_migrations.py:862-909`; multi-step chains now supported (`PROMPT_MIGRATIONS: dict[str, list[tuple[str,str]]]` at `:155`, per-key step list `:884-890`); custom-skip branch `:891-894` (message now «канон юзера — не трогаем \| key=… \| chars=…») | Barrier unchanged: any value matching neither prev nor new canon is frozen |
| Storage = PG prompts namespace; keys catalogued in `param_catalog.py:547-675` | **CONFIRMED** (`cache.set(key,new,"prompts")` `:902`; catalogue from `:555`, e.g. `prompts.summary_narrator_system_prompt` `:624`) | — |
| No persisted classification state ⇒ WARNING every restart | **CONFIRMED** | — |
| Attestation through prompt_factory `:689-713` | **CORRECTED** → `_attest_migrated_canon` `prompt_migrations.py:835-859` — now registry-aware: `pr.by_pg_key`, `withholding_required`, `attested_revision`, `sha12`, `_mark_provenance(kind="factory_reset", reason="canon_migration")` | Stronger than master version |
| Rollback twin `:766-790` | **CORRECTED** → `rollback_prompt_canons` `:912+`; `ROLLBACK_MIGRATIONS` `:452+` | — |
| `prompts.extract_system_prompt` excluded | **CONFIRMED** (comment `:433`) | — |

### NEW on production base (master audit did not see — W1 must build on these)

1. **B1 (24.10.2026) `migrate_core_owner_patch`** — `prompt_migrations.py:757-832`, invoked at the
   end of `migrate_prompt_canons` (`:908`). Owner-preserving surgical patch of the **Full Core
   document** (`character.core` → `full_text`): pure-function transformer
   `owner_preserve_core_full_patch` (`:678`), superseded-note guard via `prompt_registry.core_selection`
   (`:803-807`), write through `prompt_factory.write_speech_value(..., reason="core_patch_migration",
   set_level=False)` (`:813-815`), idempotent no-op on second restart. **This is a working
   precedent of exactly the EVOL-016 update-without-clobbering policy, currently special-cased to
   Full Core only.**
2. **Legacy-speech normalization machinery** — `_load_migration_snapshots` `:975`,
   `_classify_legacy_value` `:995` (classes `absent/invalid/already_normalized/…`),
   `plan_legacy_speech_removal` `:1024`, `normalize_legacy_speech(apply=)` `:1072`,
   `rollback_legacy_speech` `:1164`.
3. **History journal exists** — master gap-analysis item 3 ("no browsable history") is **stale**:
   `prompt_factory.py` `_load_history` `:214`, `_append_history` `:234-266` — bounded append-only
   per block in PG doc `character.prompt_history` (entries: `revision=act:<sha12>`, `sha256_12`,
   `chars`, **full text**, `source`, `kind` (factory_reset|backup_restore|legacy_strip), `at`,
   `by`, `reason`; consecutive-sha dedup, `HISTORY_MAX_PER_BLOCK` trim); `history_for` `:320`.
4. **Unified write path with optimistic locking** — `write_speech_value` `prompt_factory.py:424+`
   (single API for MiniApp/API writes; `expected_updated_at` → `FactoryConflict`; per-chat
   overrides `_write_chat_speech_value` `:519`, `reset_chat_override` `:600`; `restore_backup`
   `:736`). Provenance `_mark_provenance` `:269-317` (kinds `owner_edit|factory_reset`, scope,
   chat_id, actor) into the same `character.prompt_history` doc (`provenance` map).
   ⇒ master gap items 2 (origin tracking) and 3 (history) are **largely already implemented**;
   EVOL-016's real remaining gap = **the migration policy switch** (revision-based activation
   replacing the string-equality skip) + one-time snapshot of current PG values.
5. **One-time snapshot before first policy migration** — still absent; keep as acceptance item
   (master item 4 unchanged).

### prompt_registry.py API on 2.58.141 (foundation inventory — use these, do not rebuild)

- `REGISTRY_VERSION="soul1-w3-1"` `:95`; `PROVENANCE_DOC_KEY="character.prompt_history"` `:102`;
  `PROVENANCE_WRITE_KINDS=("owner_edit","factory_reset")` `:109`;
  `FACTORY_PREFIX="fac:"` / `ACTIVE_PREFIX="act:"` `:113-114`;
  `FACTORY_REVISION_LABELS` `:118` (human labels per block).
- `PromptBlockSpec` `:284-315` (block_id/purpose/family/scope/pg_key/code_source/consumers/
  composition_point/enabled_by/migration/owner_lane/speech/legacy_persona/ui/code_index/code_call/
  code_members/pg_doc_field); `_PG_BLOCK_META` `:321+`; catalog specs `:1353`.
- Lookup: `all_blocks :1392`, `block :1428`, `by_pg_key :1433`, `block_for :1438`,
  `speech_blocks :1443`, `legacy_persona_blocks :1447`, `unregistered_catalog_keys :1451`,
  `reset_cache :1405`.
- Hash scheme: `sha12(text) = sha256(utf8)[:12]` `:1461-1462`.
- Factory layer: `factory_text` `:1468` (code_source resolution incl. `code_call`/`code_members`/
  `code_index`), `factory_default :1514`, **`factory_revision(block_id) = "fac:<sha12>(label)"`**
  `:1519-1526`, `production_kind` `:1529` (factory | factory_document | managed_message |
  registered), `factory_texts :1542`, `factory_set_fingerprint :1552-1561`.
- Core document machinery (NEW): `CORE_DOC_KEY="character.core"` `:1105`,
  `CORE_FULL_BLOCK_ID="core.personality"` `:1106`, `CORE_COMPACT_BLOCK_ID` `:1107`,
  detail levels/fields `:1108-1109`, `CORE_SOURCE` v1/v2 `:1131-1155`, `doc_field_text` `:1161`,
  `_superseded_core_shas` `:1182`, **`core_selection(doc, source)` `:1203`**,
  **`core_active_revision(text, document_revision) = "r<doc>.<sha12>" | "fac:<sha12>"`** `:1285-1298`
  (activation/revision pointer scheme — the model for EVOL-016 revision ids),
  `core_selection_view` `:1301`.
- Effective resolution: `EffectivePrompt` `:1900`, `effective_prompt` `:2043`,
  `resolve_speech_value`/`SpeechResolution` `:2615/:2564`, `resolve_persisted_speech` `:2747`,
  `resolve_hot_prompt(_ex)` `:2758/:2771`, `resolve_chat_speech(_ex)` `:2778/:2794`,
  `payload_custom_clean_scope` `:1958`, `suppress_legacy_speech`/`LegacySuppression`
  `:1969/:2033`, `style_policy_view` `:2165`, `registry_view` `:2127`.
- Canon-hash knowledge: `known_canon_hashes` `:2345`, `is_known_canon` `:2374`,
  `legacy_persona_present` `:2378`.
- Withholding: classes `:2403-2405` (legacy_incompatible | identical_to_factory | unclassified),
  `withheld_classification` `:2462`, `is_legacy_incompatible` `:2469`,
  `withholding_required` `:2476`, `withholding_blocks` `:2493`, `withheld_values` `:2686`.
- Provenance reads: `provenance_doc` `:2507`, `attested_revision` `:2526-2541`,
  `provenance_state` `:2544-2560` (`attested | provenance_missing | provenance_mismatch |
  provenance_unavailable`).

---

## EVOL-031 — Smart Cache / Exact Match Cache removal map

| Claim | Verdict | Note |
|---|---|---|
| Thin SQLite KV (`smart_cache` table), created lazily | **CONFIRMED** — `smart_cache.py:163-177` (`_ensure_db`, CREATE TABLE `:173`); mirrored DDL `database.py:2286` (master `:2226`) | Shared storage with update-markers unchanged |
| Four answer-cache slugs: `search` / `web` / `youtube` / `factcheck` | **CHANGED** — on 2.58.141 the **`factcheck` answer cache is already removed** (Epic 72/D275: `handlers/factcheck.py:668` «Exact Match Cache (`factcheck`) удалён — вердикт теперь ищется в durable-хранилище по smart_messages»; `factcheck_temporal` slug registration removed FC-06C 28.10.2026, `_NORMALIZERS` comment `:49-52`; orchestrator `FactcheckPlan.cache_slug` is now a **provenance label only**, `factcheck_orchestrator.py:95`, `:497` — no verdict get/set). Legacy slug `factcheck` remains registered in `_NORMALIZERS :48` (OFF-path/label; tests) | **W1 removal scope = 3 slugs**: `search` (handlers/search.py `:141-142`, `:168`), `web` (handlers/web.py `:172-173`, `:197`), `youtube` (handlers/youtube.py `:1227-1228`, `:1278`, `:1293`) |
| `factcheck_orchestrator.py:679,715` slug `factcheck` (v2 input) | **CHANGED** — orchestrator's smart_cache use is now the **suitability/wide-context gate**: `:327-329` passes `get_smart_cache()` into `factcheck_suitability` (`protected`, CFG-06 `factcheck_wide_context` slug, `factcheck_context.py:64`, key build `:405`, read `:615`); new consumer `tool_router.py:3180-3186` | Do not remove `factcheck_wide_context` |
| direct_dedup replay, own flag `CHAT_DEDUP_ENABLED` + TTL 300s, independent of SMART_CACHE_ENABLED | **CONFIRMED** — `smart_cache.py:344-356` (now hot-resolved T-619); `direct_chat_service.py` key build `:2841-2844`, `get_dedup :2845`, replay log `:2856` / silence `:2859`, write `:4614-4615` (master `:2695-2713`/`:4439-4440`) | Product decision item unchanged |
| update-markers (response_freshness) protected, independent, 24h | **CONFIRMED** — `smart_cache.py:375-383`; `response_freshness.py:38-39` slug `direct_update` TTL 24h, get `:111-115`, set `:141`; MCA event `DIRECT_UPDATE_DEDUP_HIT` `direct_chat_service.py:2787-2790` | — |
| normalize utilities protected | **CONFIRMED** — `normalize_url :67`, `normalize_text :88`, `build_key :93-101`; consumers unchanged (`lore_compiler_service.py:43`, `temporal_factcheck.py:52`, `direct_chat_service.py:177`, `factcheck_context.py:41`) | — |
| Gating asymmetry: `get()` env-only vs `set()` hot | **REFUTED (fixed on production)** — 28.10.2026 hot-toggle fix: `get()` `:316-328` now reads `hot.get("flags.smart_cache_enabled", …)` + hot TTL (docstring «P0 admin-toggle-save»); `set()` `:332-337` hot | Latent bug no longer exists; do not "fix" again |
| UI surface: groups/flag/tab | **CORRECTED** (shifts) — `param_catalog.py`: `limits_smart_cache :295`, `flags_smart_cache :382-383`, flag label «Exact Match Cache» `:1320` (master `:1311`), `SMART_CACHE_TTL_SECONDS :1694`, `SMART_CACHE_MAX_ROWS :1696` (master `:1660/:1662`), `TAB_SMART_CACHE :3198`, category map `:3439-3441` | — |
| Ancillary readers memory_health/mca_trace | **CONFIRMED** — `memory_health.py:140-141` (same lines); `mca_trace.py:612` | Update after removal |
| «Повторы» attribution needs runtime data | **CONFIRMED** (no code change) | — |

---

## EVOL-015 — Telegram quote pipeline

| Claim | Verdict | Note |
|---|---|---|
| aiogram `>=3.31.0,<4.0.0` delivers `Message.quote` / `TextQuote` | **CONFIRMED** — `requirements.txt:1` | venv install not re-checked in worktree; constraint identical |
| Router: `bot.py:899`; `handlers/summary.py:35` router, `:318` catch-all | **CONFIRMED** (same lines) | — |
| Quote extraction reads ONLY `quote.text` + `quote_author_id`; `position/entities/is_manual` never extracted | **CORRECTED** → `handlers/summary.py:388-403` (`quote.text :392`, author `:400-403`); repo-wide grep: zero reads of `quote.position/entities/is_manual` | DROP POINT #1 intact; save call passes `quote_text/quote_author_id` at `:460-461` (+ newer fields forward_author_id/sender_chat_id/thread_id) |
| Storage: `message_identity.save_live_message :154` (param `:160`, normalize `:181`, payload `:235`); column `database.py:304` | **CONFIRMED** — payload `:235-236`; column at `database.py:305` | — |
| edited_message handler `:485-514` | **CORRECTED** → `handlers/summary.py:507+` | No quote relevance, unchanged |
| ChainItem no quote field; `format_context_item` no quote param | **CONFIRMED** — `thread_chain.py:30-42` (same fields); `canonical_context.py:252` `format_context_item`, zero quote references | — |
| Context SELECTs exclude quote columns | **CONFIRMED** — `get_smart_window` `database.py:7785-7796` (master `:7541-7552`), `get_smart_raw :7798+`, `get_recent_messages :7821+` (SELECT at `:7849`, same column list) | DROP POINT #2 intact |
| Thread/Branch render `_render_thread` `dcs:9811-9849`, chain collect `:9764-9785`; `_context_row_line :9742-9759` | **CORRECTED** → `_collect_thread_chain :10163`, `_render_thread :10210-10248`, `_context_row_line :10141` | No quote anywhere |
| MCA-22 resolver `_resolve_quote_live :7600-7634`, gate default ON | **CORRECTED** → `dcs:7839`; `mca_gates.canonical_attribution_enabled :991-998` default ON | Attribution only |
| Prompt gets only generic directive («Цитата принадлежит её автору…»), never the quoted text | **CONFIRMED** — `claim_envelope.py:850-852` (`if u.quote:`) | Effective loss unchanged |
| Fact-extraction input drops quote (`_build_batch_text` `[author]: text`) | **CONFIRMED** — `summary_memory.py:946` | — |
| Dead-in-prod renderer `format_canonical_envelope` renders quote, tests only | **CONFIRMED** — `canonical_messages.py` (fields `:65-67`, `:85`) | — |
| Diagnostic API exposes quote fields | **CONFIRMED** — `web/api/memory_agi.py:1100-1101` (same lines) | — |
| — (new) | **NEW** — `quote_text` is now used as a **stats FILTER**: `database.py:1897-1936` `_message_measure_filters(quote_forward=exclude|only)` + `database.py:8615/8648/8685` query params, consumed by chat-statistics tool (`chat_statistics.py`, `tool_router.py:1501/1537`, `tool_schemas.py:185`). Filter only — still never returned into any prompt | Do not confuse with context delivery |

---

## EVOL-006/007 — facts pipeline & «Новые факты» widget

| Claim | Verdict | Note |
|---|---|---|
| Extraction cron hour=0,6,12,18 in `limits.summary_timezone` | **CONFIRMED** — `summary_scheduler.py:140-141` | 4 runs/day bottleneck intact |
| `EXTRACT_PROMPT` no stability/temporality dimension | **CONFIRMED** — `summary_prompts.py:1076` (master `:988-998`); `FACT_EXTRACT_PROMPT`/`PREV_…`/`_FACT_ORIGINS`/`_FACT_RETRY` at `summary_memory.py:152/143/159/173` (same lines) | — |
| Widget: `db.dossier_feed` random sample without created_at | **CORRECTED** → `database.py:11729-11758` (master `:11248-11277`): pool `limit*20` by `id DESC`, `ORDER BY RANDOM()`, SELECT only `chat_id, name, fact`; **NEW optional `chat_id` param** (per-chat scoping, used by API) | Dates still impossible — root cause intact |
| `GET /api/oversight/dossier_feed` limit 1..40 default 12, fail-open | **CORRECTED** → `web/api/oversight.py:380-381` (limit default now 16 in UI call `app.js:10828`; DB default 12; fail-open `:402`, `chat_id` pass-through `:400`) | — |
| UI: card `index.html:10473-10500`, `factsFeed` computed `app.js:5574-5587`, loader `:10800-10825` | **CORRECTED** → card now a glass ticker card `index.html:6456-6468+` (`dossier-ticker-wrap`); `factsFeed` `app.js:5598-5611` (maps `created_at`/`ts` **if present** — they never are, `:5601-5602`); `loadDossierFeed` `app.js:10824` | Widget presentation changed on production; the defect (no dates, random sample semantics) unchanged |
| Dedup/idempotency helpers | **CONFIRMED** — `meme_exists :11765`, `person_fact_exists :11776` | — |
| Dream/Deep Sleep constants | **CONFIRMED** — `dream_worker.py:284` `_DEEP_SLEEP_MIN_INTERVAL_HOURS=20`, IntervalTrigger jobs `:650/:658` | — |

---

## EVOL-014 prerequisites

| Claim | Verdict | Note |
|---|---|---|
| `mca_random_source.py` closed purpose set: 10a + exactly 5 sanctioned 10b extensions | **CONFIRMED** — purposes at `:73-86` (`LESS_STUDIED`, `activation_selfcheck`, `sleep_after_consolidation` + `conversation_variant`, `memory_recall`, `archive_sample`, `belief_review`, `association_pair`); comment `:78-81` reaffirms new purposes require sanctioned extension | "meme trigger" purpose → 10b-style extension needed (unchanged) |
| Modes `quantum|pseudorandom`, `memory.random_source`, ANU provider, key fingerprinting | **CONFIRMED** (header `:1-31`) | — |
| `image_generation.py` daily quota machinery | **CONFIRMED** — `image_daily_limit_enabled :242-247` (env-only, default ON), `image_reserve_mode :252+` (atomic reserve/journal/commit-release; honest reasons `kill_switch_off`/`budgets_off`), `image_quota_reset_note :275-303`, `probe :1428+` | Same lines as master audit |
| `worker_budget.py` `limits.image_daily_limit :66`, `image_day :613`, `image_timezone :623`, `image_next_reset :628` | **CONFIRMED** | Calendar-day-in-chat-TZ machinery reusable |
| Initiative: durable `initiative.observe` `:75`, coalesce `:77`, `INITIATIVE_OUTPUT_KINDS=("initiative_reply",) :136`, REASON_LABELS `:210` (incl. `random_fallback :236`), `reason_label :268-273`, gates/keys `:277-286` (`flags.initiative_observer_enabled`, `initiative.frequency_profile` etc.), profiles 6h/2700/1200 `:162-180` | **CONFIRMED** | Meme capability = new output kind + purposes extension |
| `handle_initiative` single publish entry | **CORRECTED** → `direct_chat_service.py:11066` (master `:10620`) | — |
| `initiative_diagnostics.py` exists (event/window machinery) | **CONFIRMED** (`:73-156+`) | Hook point for EVOL-014 diagnostics |

---

## EVOL-019/020/021 backend surfaces + EVOL-013

| Claim | Verdict | Note |
|---|---|---|
| `/api/vision/test` `routes.py:2274-2328`, `/api/vision/state` `:2331-2360`, RBAC + 10s/user rate limit, always-200 verdict | **CORRECTED** → test `:2366+` (comment block `:2314-2318`), state `:2423+`; rate-limit helper `reset_vision_test_rate_limit :2326` | Same contract |
| `probe_connection` real-image probe, `config_revision` verdict cache, `_classify_success` (2xx + non-empty choices), no content verification | **CONFIRMED** — `mca_vision.py` `_classify_success :926`, `probe_connection :950+` (master `:843-864`/`:867-951`); 512×512+ real image probe (header `:43`), `config_revision` hashing `:268/:321/:343` | EVOL-019 gap (no meaningful-recognition proof) intact |
| Vision UI card `b.id === 'vision'` `index.html:2143-2164` | **CONFIRMED** — `:2149/:2157` (+ facts variant `:1800`) | — |
| MCA-16 experience job deterministic, v28 tables | **CONFIRMED** — `mca_experience_jobs.py` (`experience.review`, `CANONICAL_RECOMMENDATIONS`); DDL `database.py:1135-1192` (`mca_experience_episodes` `:1135`, idem index `:1165-1166`) | — |
| Episodes: `mca05-episodes-1`, honest states, `NO_SOURCES_MESSAGE` | **CONFIRMED** — `mca_episodes.py:54`, `:77-78`, `is_auto_stub_title :296`; `mca_episode_jobs.py`/`mca_episode_prompts.py` present; `web/api/stories.py` present | Fallback-storm root cause intact |
| Schema: SQLite user_version cascade, latest 37 (+36 alias) | **CONFIRMED** — `database.py:1707-1708` (master `:145-203` block) | Additive-only contract unchanged |
| llm_client transport error `:925/:1141` scoped to TransportError/timeout | **CORRECTED** → `:964`, stream `:1180` (scoping header `:188`) | Same info-loss caveat |
| Type-name-only logging (dcs `:6063,6127,6144`; factcheck_service `:506`; direct_execution `:803`) | **CORRECTED** → dcs `:4879/:4908/:5391/:6282/:6346/:6363`; factcheck_service `:504-505` (**now includes message**: `f"{type(exc).__name__}: {exc}"`); direct_execution `:800` | Slightly improved on production for factcheck; dcs/direct_execution unchanged |
| Embedding telemetry survey (EVOL-013 items 1/4/5) | **CONFIRMED** — see EVOL-010/F3-F4 rows and EVOL-011 rows | — |

---

## UI inventory (context-ui-audit §6)

| Claim | Verdict | Note |
|---|---|---|
| Stack: Vue 3 Options API zero-build; vendored vue.global.prod.min.js; DOMPurify 3.4.15; prebuilt Tailwind; no bundler | **CONFIRMED** — `index.html:12254` (vue), `:12258` (DOMPurify 3.4.15); `app.js` 1 333 482 B (~1.33 MB), `index.html` 930 374 B (~929 KB) | Sizes match audit |
| Liquid glass: vendored `@liquidglassjs/core` 0.5.3, single mount `web/static/glass.js` (HOTFIX10), probe + WebKit fallback files | **CONFIRMED** — `glass.js` header (`@liquidglassjs/core 0.5.3`, HOTFIX10, ADR-1025-18 D1); `glass-probe.js` 13 445 B, `glass-refraction.js` 36 905 B present | — |
| Polygonal background + aurora | **CONFIRMED** — `polygon-background.js` 44 018 B, `aurora-flow.js` 15 639 B | — |
| Tokens block `app.css:4-60` «Дизайн-токены v2» (ADR-1025-9 D1), glass tiers `--glass-bg` | **CONFIRMED** — `:root` at `app.css:4`, glass tokens `:58`; second `:root` at `:148` (Epic 85 media/scoped additions — pre-existing) | Single canonical block intact |
| `fullscreen-policy.js` | **CONFIRMED** (32 473 B) | — |

---

## Summary for W1 lanes (material deltas master → production)

1. **EVOL-010 is a committed deterministic bug on 2.58.141** (`_LAST_EMBED_META` used at
   `embedding_control_plane.py:1373`, never defined). Drop the deployment-mystery branch of the
   fix plan; the minimal fix is removing the dead `.set()` block (no consumer) or restoring
   definition+consumer, plus `_on_error` classification hardening. All supporting telemetry
   mechanisms (fake budget, processed=0, durable-job gap) confirmed with small line shifts.
2. **EVOL-016 foundation is much richer than the master audit believed**: revision scheme
   (`fac:`/`act:`/`r<doc>.<sha12>`), provenance + bounded history journal
   (`character.prompt_history`), unified write path with optimistic locking
   (`write_speech_value`), and a working owner-preserving update precedent
   (`migrate_core_owner_patch`, B1 24.10). Remaining EVOL-016 work = migration policy switch +
   pre-migration snapshot (+ optional history UI), not building provenance/history from scratch.
3. **EVOL-031 scope shrank**: the `factcheck` answer cache was already removed on production
   (Epic 72/FC-06C); removal target = `search`/`web`/`youtube` slugs (+ the smart-cache flag/UI
   group), with `factcheck_wide_context` + `direct_update` markers + utilities protected; the
   gating asymmetry bug is already fixed (hot toggle in `get()`).
4. **EVOL-011 fix got easier**: `VisionAnalysis.error_reason` ("parse_error") already exists —
   `_emit_adapt` just needs to include it in `error_json`.
5. Everything else (EVOL-012 barrier, EVOL-015 quote drop points, EVOL-006/007 widget mechanics,
   EVOL-014 prerequisites, EVOL-019/020/021 surfaces, UI inventory) survived with line shifts
   only; corrections are listed per-row above.
