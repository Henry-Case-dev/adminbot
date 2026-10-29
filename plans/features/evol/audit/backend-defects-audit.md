# Backend defects audit — EVOL-010/011/012/031/013

Read-only code audit, 2026-10-30. Repo HEAD `3193b657`; production `2.58.141 @ 5346e76`.
`git log 5346ee76..HEAD` touches **none** of the audited files (`services/embedding_control_plane.py`,
`services/summary_memory.py`, `services/mca_vision.py`, `services/prompt_migrations.py`,
`services/smart_cache.py`) — audit findings apply verbatim to production code.
Facts only; runtime-only uncertainties are marked explicitly.

---

## EVOL-010 — embedding `NameError` → fake budget exhaustion → backfill stalls (P0)

### Observations (production)
- `services.embedding_control_plane | embed transport error | error=NameError`, then
  `services.summary_memory | SmartModule graph backfill: embed failed — deferred | processed=0`.
- Telemetry: `graphgraph memorize: embedding unavailable for batch … state=EmbeddingBudgetExhausted |
  quota_group=unknown | next_allowed_at=- | facts_text_only=1`; `EMBED_API_DEFERRED outcome=skipped
  reason_code=embed_deferred` while `FACTS_EXTRACT outcome=success`.
- `smart_archive status=building, FTS-only (A06), build pending — durable job missing`.

### Code findings

**F1. Exact failure site — CANARY-03 metadata channel.**
`services/embedding_control_plane.py:1373` (`EmbeddingExecutor.embed`):

```python
_LAST_EMBED_META.set({"model": credential.model, "provider": credential.provider,
                      "alias": credential.alias, "source": MODEL_SOURCE_REQUEST})
```

`_LAST_EMBED_META` is a module-level `contextvars.ContextVar` defined at `:2488-2489` (same module,
later), consumer is the compat probe (`_compat_probe_once`, `:3087`, `:3097`). Both the `.set()` call
and the ContextVar definition were introduced by the **same commit** `60789cff` (2026-10-23,
EMBED-IDENTITY-GAPS). No committed version of the file ever had one without the other
(`git log -S` for both patterns returns only `60789cff`).

**F2. The failure happens AFTER a successful HTTP call.**
Full traceback (migration raw log `raw_pass3new2.out.txt`, 07:31:37Z, new VPS):

```
services.llm_client - INFO - LLM embed_once OK | model=gemini-embedding-001 | texts=1
services.embedding_control_plane - WARNING - embed transport error | error=NameError
File ".../embedding_control_plane.py", line 1373, in embed
  _LAST_EMBED_META.set({"model": credential.model,
NameError: name '_LAST_EMBED_META' is not defined
File ".../summary_memory.py", line 3860, in _save_graph_fact_embedding
File ".../summary_memory.py", line 2184, in _embed   → _embed_api → execute_embed → embed
```

Provider call succeeds (status 200, `embed_once OK`); the very next statement raises NameError.

**F3. Why it masquerades as a transport error.**
`_on_error()` (`:1464-1544`) classifies by `type(exc).__name__`: `"Auth"` in name → auth;
`"RateLimit"`/`"429"` in body → defer; **everything else** → `logger.warning("embed transport error |
error=%s", name)` and return `"transport"` (`:1543-1544`). A `NameError` (deterministic Python bug)
falls into the transport branch and is treated as retryable 5xx/timeout.

**F4. Fake `EmbeddingBudgetExhausted`.**
The retry loop (`:1338-1412`) then burns the whole attempt budget (`_ATTEMPT_BUDGET`, ≤4 logical
attempts) re-doing a fully successful HTTP call and re-hitting the same NameError each time
(`:1401-1406` transport backoff), then raises
`EmbeddingBudgetExhausted("embedding attempt budget exhausted …") from last_error` at `:1410-1412`.
`summary_memory._EmbedBatchState.mark()` (`services/summary_memory.py:322-326`) records
`state = type(exc).__name__`, `quota_group = getattr(exc, "group_id", "")`, `next_allowed_at =
getattr(exc, "next_allowed_at", None)`. `EmbeddingBudgetExhausted` carries **neither** attribute
(only `EmbeddingGroupCoolingDown` does, raised at `:1394-1398` on a real 429 path). Hence telemetry
`state=EmbeddingBudgetExhausted | quota_group=unknown | next_allowed_at=-` is the exact signature of
the attempt-budget terminal raise — **not** a proven provider quota state. `_embed_fail_reason`
(`summary_memory.py:371-372`) additionally maps it to `reason_code=budget_exceeded`.
A second, genuinely non-quota raise site exists: `:1349-1351` ("no usable embedding credential") —
same telemetry look.

**F5. Why `processed=0`.**
The graph backfill loop (`summary_memory.py:2650-2673`) calls `self._embed(batch)`; every call raises
(the NameError→BudgetExhausted chain), the `except` logs `graph backfill: embed failed — deferred |
processed=%d` and `break`s. Deterministic per-batch failure ⇒ `processed=0` forever. Facts are saved
text-only upstream (`:3853`), so `FACTS_EXTRACT=success` + `EMBED_API_DEFERRED` is consistent.
Backfill itself is an in-process maintenance pass (`_EMBED_BACKFILL_TICK_INTERVAL = 600.0`,
`summary_memory.py:303`), not a durable job.

**F6. "Durable job missing" is a separate pre-existing defect.**
Panel text `summary_memory.py:2050-2061`: after identity/compat checks it queries
`latest_rebuild_job(...)`; `job is None` → `" | build pending — durable job missing"`.
Documented pre-existing since 2.58.114 (`plans/features/_audit-2026-10-23/release-258114/deploy.md:70`,
…`release-258123/deploy.md:90`), i.e. smart_archive generation sits `building` with no `task_jobs`
rebuild row — independent of the NameError, but the NameError guarantees no progress even if the job
existed.

**F7. Root cause of the NameError itself is NOT provable from repository code alone.**
Static analysis eliminates every in-repo mechanism:
- the ContextVar is unconditionally defined at module top level (`:2488`), `import contextvars`
  present (`:70`);
- AST scan: **no module-level statement between the Executor class and `:2488` can raise at import**
  (only constant assigns; `note_backfill_progress` at `:1920`, `execute_embed` at `:1582` are plain defs);
- the module imports only stdlib at top (`:69-77`) — no circular import partner exists;
- exactly one `class EmbeddingExecutor`, one `def embed`;
- no runtime `importlib.reload` / `spec_from_file_location` / `sys.modules` stubbing in production
  code (all hits are tests/evidence harnesses);
- exactly one copy of the file in the repo (no shadow module).

A NameError on a global that a complete import would bind means **the running process's in-memory
module state does not correspond to a clean import of the deployed file**: stale/corrupt
`__pycache__` entry carried over the VPS migration, an on-disk file differing from the git checkout
(manual edit / partial hotfix), or a process holding mixed-version code. Which of these — requires
server-side runtime evidence (see below). Historical logs confirm this defect family predates the
migration (`plans/features/release-then-migrate/evidence/decommission-old-vps.md:88` labels it
"known pre-existing"; the 07:31 sample is from the **new** VPS process 72680).

### Required runtime evidence (server 192.255.209.205)
1. `git -C /var/www/admin_bot status --porcelain` + `git diff HEAD -- services/embedding_control_plane.py`
   + sha256 of the file vs repo blob at 5346e76.
2. `ls -la services/__pycache__/embedding_control_plane*` (mtime vs source mtime; pyc header source
   mtime/size vs actual).
3. In-process (safe, read-only): `python -c "import services.embedding_control_plane as m; print(m.__file__, hasattr(m,'_LAST_EMBED_META'))"`.
4. Process start time (`systemctl show admin_bot -p ExecMainStartTimestamp`) vs last git pull time.
5. Whether the error fires since process start (journalctl since ExecMainStartTimestamp) — if yes,
   the bad state was loaded at boot; a clean restart may already clear it.

### Minimal fix strategy (proposal, not implemented)
1. **Deployment-state repair first** (root cause of the missing binding): verify per above; if
   file/pyc mismatch — `git checkout -- services/embedding_control_plane.py` / remove stale pyc /
   clean restart. Do not hand-edit.
2. **Classification hardening in `_on_error`** (`embedding_control_plane.py:1464-1544`): classify
   programming errors (`NameError`, `AttributeError`, `TypeError`, …) as **non-retryable** hard
   failure with `exc_info=True` logging — satisfies the requirement "исключить бесконечные
   бесполезные ретраи для детерминированной ошибки кода" and stops budget burn + fake budget state.
3. Optionally isolate the CANARY-03 metadata channel: wrap `:1373-1376` so a telemetry-only
   side-channel cannot fail an already-successful embed (log at WARNING with traceback; never silent).
   This is defence-in-depth, not a substitute for 1–2.
4. Durable smart_archive rebuild job (F6) — separate work item, do not bundle into the hotfix.

### Risks / do-not-touch
- Do not reset quota state / clear `embedding_quota_state` based on the fake budget signal — real 429
  parking logic (`:1481-1538`) is healthy and independent.
- Do not add retries for NameError; do not disable the control plane or downgrade to the legacy
  3×(3+2+2) loop.
- FTS-only degradation of facts must remain as the honest fallback while embeddings are down; no
  history re-import, no vector space rebuild.

---

## EVOL-011 — `vision_adapt | outcome=failed | strategy=original | reason=fits | calls=1 | error=""`

### Code findings
- Emitter: `services/mca_vision.py:1765-1791` `_emit_adapt`. `outcome="success"` **only** for
  `status in ("ready", "no_text")` (`:1782-1784`); anything else → `failed` + WARN.
  `error` field = `error_class` — the exception class name; `error=""` ⇒ **no exception was raised**
  (success-path emit at `:1752-1754`, not the except-path at `:1758-1762`).
- So the log line decodes as: adapt plan `original` (image fit limits, `reason=fits`), exactly one
  `_adaptive_call` (`:1733-1738`, bounded `analyze_image_bytes` via `asyncio.wait_for`), which
  **returned** a `VisionAnalysis` whose `status ∉ {ready, no_text}`.
- The only such status reachable without an exception: `status="failed"` returned by the model-response
  parser — `mca_vision.py:1459` (`VisionAnalysis("failed", [], "", ["ответ модели не JSON"], …)`) and
  `:1462` (`["ответ модели не объект"]`): provider returned HTTP 200 but the payload was not valid
  JSON / not an object. Segment-merge path yields `failed` only with zero analyses (`:1644-1652`),
  which cannot happen on this path; `ready`/`no_text` at `:1483-1486`.
- The human-readable reason ("ответ модели не JSON") is stored in `VisionAnalysis.uncertainty`
  but **not emitted** — `error_json` carries only `{strategy, reason, calls, error:""}` (`:1788-1789`).

### Verdict
Not a false WARN and not a crash: a **real terminal parse failure of the vision model response**,
repeated. The observable defect is telemetry information loss — the WARN is unactionable because the
actual reason (non-JSON payload) is dropped, so "provider unavailable / vision broken" cannot be
distinguished from a transient bad payload by the log line alone.

### Minimal fix strategy
1. Propagate a `reason_code` (e.g. `model_payload_not_json` / `model_payload_not_object`) from the
   parser (`:1459`, `:1462`) into `_emit_adapt` `error_json`/`reason_code` — no behavior change.
2. Separately investigate why the provider repeatedly returns non-JSON (runtime: sample the raw
   payload at DEBUG level; check model/route). If a specific provider/model route is responsible,
   fix the route; do not invent a second vision pipeline.
3. Keep `pending`/`cancelled`/`timeout` distinct (they already flow as exceptions or job statuses;
   no new statuses invented).

### Risks / do-not-touch
- Do not reclassify parse-failure as success; do not silence the WARN.
- Preserve existing fallback chain (`pending→ready` queue, media/preview handling, normalize-retry at
  `:1674-1699`).

---

## EVOL-012 — prompt migration «кастом юзера — НЕ трогаем» blocks factory updates

### Mechanism (current)
- `services/prompt_migrations.py:716-763` `migrate_prompt_canons(cache)` — runs at **every startup**
  (called from `bot.py` main right after `cache.init()`).
- `PROMPT_MIGRATIONS` (`:146-348`): ~20 PG keys, each with hardcoded `(prev_canon, new_canon)`
  string pairs. Per key: `current = cache.get(key)`; `current == new` → "уже новый канон" (+ idempotent
  provenance attest `:749-754`); `== prev` → `cache.set(key, new, "prompts")` (`:756`);
  **else → WARNING `кастом юзера — НЕ трогаем` and skip** (`:745-748`). Rollback twin
  `rollback_prompt_canons` `:766-790`.
- Storage: PG prompts namespace (`cache.get/cache.set(key, ns="prompts")`); keys are the
  `prompts.*` PG keys catalogued for the admin UI in `services/param_catalog.py:547-675`.
- No classification state is persisted ⇒ the same WARNING repeats on every restart. Observed value
  `prompts.summary_narrator_system_prompt` 1788 chars (1850 in 20.10 logs) matches neither the new
  nor the prev canon string ⇒ permanently classified "custom" and **blocked from any future factory
  revision**. This is exactly the project error described in the task: single admin-UI edit freezes
  the key against all release-driven updates.

### What already exists toward EVOL-016 (important — do not rebuild)
`services/prompt_registry.py` (~2400 lines) already implements a registry layer:
`PromptBlockSpec` (`:237`), `block()/by_pg_key()/all_blocks()` (`:1381-1394`), `factory_text /
factory_revision / factory_texts / factory_set_fingerprint` (`:1421-1505`), `sha12` content hash
(`:1414`), provenance store — `provenance_doc / attested_revision / provenance_state`
(`:2290-2345`), layered resolution `effective_prompt` (`:1827`) and `known_canon_hashes /
is_known_canon` (`:2129-2157`), withholding logic (`:2245-2276`). `services/prompt_factory.py`
`_mark_provenance(... kind="factory_reset", reason=...)` writes the activation record; migrations
already attest through it (`prompt_migrations.py:689-713`).

### Gap analysis (what EVOL-016-style versioning must add)
1. **Policy switch**: replace string-equality gating with revision-based activation — new factory
   revision becomes active on release regardless of manual edits; manual edits preserved in history
   (owner decision 29.10). The "else = custom → skip" branch (`:745-748`) and its WARNING are removed
   as an update barrier.
2. **Origin tracking on every write path**: admin-UI writes (`param_catalog` → PG), chat-scoped
   overrides, migration attestation, restore — each must record origin (`factory | manual | restored
   | legacy`), revision id, content `sha256_12`, timestamp.
3. **Revision history + activation journal** (append-only): currently only a single attested-revision
   record per block exists (`attested_revision`); there is no browsable history of superseded manual
   edits.
4. One-time snapshot of current PG values before the first policy migration (incl. the current
   1788-char narrator text) so nothing is lost and the restart after migration is a no-op
   (acceptance: «повторный рестарт ничего самовольно не меняет»).

### Prompt-bearing inventory (file → keys) for the registry
- `services/prompt_migrations.py` — 17 canon keys + rollback map (`:146-348`, `:365-448`);
  `prompts.extract_system_prompt` deliberately excluded (`:349`).
- `services/param_catalog.py:547-675` — UI catalogue of all `prompts.*` keys (incl. legacy
  `summary_system_prompt`, `summary_editor`, `summary_narrator`, verbilizer mode prompts,
  `summary_cover_style`, `summary_cover_style_id`, `direct_l1_planner`).
- Resolvers: `checkup_service.py:57`; `factcheck_service.py:442,495,522,1098`;
  `direct_chat_service.py:3072,4564,5621,5902,6239,10013`; cover style:
  `cover_style_jobs.py:1088`, `cover_style_pipeline.py:390-402`; canonical context →
  `services/dream_prompts.py`.
- Registry/factory: `services/prompt_registry.py`, `services/prompt_factory.py`;
  legacy-speech handling `prompt_composer.py:689-690`.

### Risks / do-not-touch
- Do not mass-overwrite PG values on the switchover: snapshot first, activate factory revision per
  explicit release policy, keep rollback path.
- `prompts.extract_system_prompt` is intentionally outside migrations — keep excluded unless owner
  says otherwise.
- No WARN per load for the mere fact of manual modification; integrity/setup failures must remain
  real errors.

---

## EVOL-031 — Smart Cache / Exact Match Cache removal map

### Architecture facts
`services/smart_cache.py` = thin SQLite KV store (table `smart_cache`: `key TEXT PK, payload TEXT,
created_at REAL`; created lazily `:173-177`, also `services/database.py:2226`) with **four distinct
consumer families** on top:

1. **Finished-LLM-answer replay (the removal target)** — slug-keyed caches of generated answers,
   all gated by `flags.smart_cache_enabled` / `settings.SMART_CACHE_ENABLED`:
   - `handlers/search.py:141-168` — slug `search` (query → summary);
   - `handlers/web.py:172-197` — slug `web` (url → summary);
   - `handlers/youtube.py:1227-1293` — slug `youtube` (video_id → retelling);
   - `handlers/factcheck.py:524-569` — slug `factcheck` (text → verdict);
   - `services/factcheck_orchestrator.py:679,715` — slug `factcheck` (v2 input).
   Writes only successful generations (comment «59.2»). Hit/miss telemetry = INFO logs only
   (`smart cache: miss|expired|hit|set`, `smart_cache.py:258,264,266,303`); no MCA events.
2. **Direct-chat text dedup replay** — `get_dedup/set_dedup` (`smart_cache.py:331-348`), slug
   `direct_dedup`, key `md5(direct_dedup\0chat\0user\0…)` (`direct_chat_service.py:2695-2698`).
   Replay branch `:2699-2713` (`[direct] dedup replay` / `dedup silence`), write after each turn
   `:4439-4440`. **Own flag `flags.chat_dedup_enabled` (`CHAT_DEDUP_ENABLED`) and own TTL**
   (`limits.chat_dedup_ttl_seconds`, 300 s default) — `SMART_CACHE_ENABLED=False` does **not**
   disable it (`smart_cache.py:331-334`). This branch **replays stored answers on repeated identical
   user text** in Direct Chat.
3. **Update-identity idempotency (protected)** — `get_update_marker/set_update_marker`
   (`smart_cache.py:367-375`), used by `services/response_freshness.py` (slug `direct_update`,
   TTL 24 h); gate `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED`; explicitly independent of both legacy
   flags (`:350-365`); MCA event `DIRECT_UPDATE_DEDUP_HIT` (`direct_chat_service.py:2641`).
   This is idempotency/repeat-delivery protection — **must survive**.
4. **Shared utilities (protected)** — `normalize_url / normalize_text / build_key`
   (`smart_cache.py:47-102`) reused by `lore_compiler_service.py:43`, `temporal_factcheck.py:52`,
   `direct_chat_service.py:173`, `factcheck_context.py:41` (text normalization, not caching).

### Config/UI surface
- `param_catalog.py`: group `flags_smart_cache` «Умный кэш: рубильник» (`:382`), group
  `limits_smart_cache` (`:295`), flag `SMART_CACHE_ENABLED` labelled **«Exact Match Cache»** (`:1311`),
  limits `SMART_CACHE_TTL_SECONDS` (`:1660`), `SMART_CACHE_MAX_ROWS` (`:1662`), tab
  `TAB_SMART_CACHE = "smart_cache"` (`:3166`), category mapping `:3407-3408`.
- Gating asymmetry (removal-relevant): `get()` checks only static `settings.SMART_CACHE_ENABLED`
  (`:320-322`) while `set()` checks the hot flag (`:327-328`). UI-OFF therefore stops writes but
  existing rows keep being served by `get()` until TTL expiry if the env default is ON.
- Ancillary readers: `memory_health.py:140-141` (row count for panel), `mca_trace.py:612-618`
  (best-effort `size()` introspection, silently no-ops).
- DB: `services/database.py:2226` `CREATE TABLE smart_cache`; **shared storage** — answer-cache rows
  and 24 h update-markers live in the same table (cap `SMART_CACHE_MAX_ROWS` eviction applies to
  both, documented `:361-363`).

### Safe-to-remove vs protected (summary)
| Component | Verdict |
|---|---|
| Handler answer caches (`search`/`web`/`youtube`/`factcheck` slugs), `get/set` methods, `SMART_CACHE_ENABLED` flag + UI group/tab, TTL/MAX_ROWS limits **as applied to answer cache** | removal target (EVOL-031 scope) |
| `direct_dedup` replay branch | **product decision required**: it is a finished-answer replay in Direct Chat (owner-perceived «повторы» candidate) but sits on a separate flag; EVOL-031 text targets «кэширование готовых ответов для повторного воспроизведения» — argue inclusion, decide explicitly, do not silently keep or silently drop |
| `get/set_update_marker` (response_freshness, MCA-22) | protected — idempotency; explicitly documented as independent |
| `normalize_url/normalize_text/build_key` | protected — plain utilities (move/rename only if module is dissolved) |
| table `smart_cache` | keep while update-markers use it; no destructive migration |
| `memory_health` row count, `mca_trace` introspection | update or fail-soft after removal |

### Whether the observed «повторы» come from this branch — needs runtime data
No code path replays on «similar» questions — all hits are exact-key. For Direct Chat the only exact
replay is `direct_dedup` (identical text within 300 s, same chat+user). Confirm via runtime which
flags were on and whether `[direct] dedup replay` / `smart cache: hit` lines correlate with the
observed repeats before attributing them (EVOL-031 step 1 requirement).

### Risks / do-not-touch
- Do not drop the `smart_cache` table or its 24 h markers; do not touch provider-side prompt caching,
  embedding cache, `anticliche_cache`, `lore_cache`, config cache, Telegram event dedup — all separate.
- No semantic/vector answer cache as a replacement (explicit owner ban).
- Keep no-op backward compatibility only where update markers require it; no dead flag/endpoint
  residues.

---

## EVOL-013 — status/telemetry classification survey (top offenders only)

1. **`services/embedding_control_plane.py:1543-1544`** (`_on_error` fallback) — any non-Auth/non-429
   exception becomes `transport error` + retryable. Deterministic code errors (NameError today) are
   retried and masked. (Root of EVOL-010.)
2. **`services/llm_client.py:925, :1141`** — `LLM transport error after N attempts` — correctly
   scoped to `httpx.TransportError` (`:901`)/timeout (`:912-923`); acceptable, but the message is the
   only carrier of the cause class; downstream consumers logging only `type(exc).__name__` lose it.
3. **Type-name-only logging without message/traceback**: `services/direct_chat_service.py:6063,6127,6144`,
   `services/factcheck_service.py:506`, `services/direct_execution.py:803` — honest (no fake class)
   but insufficient for diagnosis; add exception message (R17-safe) at minimum.
4. **`services/summary_memory.py:322-326`** (`_EmbedBatchState.mark`) — exposes raw exception class
   names as user-visible `state` and silently defaults `quota_group="unknown"`,
   `next_allowed_at="-"`, making a real quota state and an attempt-budget terminal
   indistinguishable in the panel. Distinguish: CoolingDown carries `group_id/next_allowed_at`;
   BudgetExhausted (both raise sites `ecp:1349`, `ecp:1410`) carries neither — surface the
   distinction explicitly.
5. **`services/mca_vision.py:1782-1789`** — binary success/failed with empty `error` for
   payload-parse failures (see EVOL-011): real failures indistinguishable from telemetry noise.

General pattern: classification by exception **class name string** (`"Auth" in name`, `type(exc).__name__`)
instead of typed exception hierarchies is the common root of both false-positive "transport/quota"
states and information loss.

---

## Cross-cutting incidental findings
- `EmbeddingBudgetExhausted` at `ecp:1349` ("no usable credential") is a second honest-but-unlabelled
  source of the same telemetry signature — worth a distinct state label when EVOL-010 lands.
- `smart_cache.get()` env-only gating vs `set()` hot gating asymmetry is a latent config bug
  independent of removal.
- Backfill cadence constants (`summary_memory.py:296-303`) show backfill is in-process only; the
  "durable job" gap (smart_archive) is separate and pre-existing (2.58.114+).
