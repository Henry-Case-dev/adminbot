# Global Map (architectural memory)

> Архитектурная память Scanner. Не источник правды о коде — только карта связностей.
> HEAD == 0bdf272 (10.4) + рабочее дерево 10.5 (tma-relume-redesign, 2026-09-10).
> origin/master == 0bdf272 (10.4 deployed; 10.5 — не задеплоен, сканирование).

## Stack
- **aiogram 3.31** (polling) + **FastAPI** webapp (`web/app.py`) + **asyncpg** (PG) + **aiosqlite** (memory v8). APP_VERSION=2.51.0.
- **httpx** for LLM/API calls, **sqlite-vec** (optional) for vector search, **FTS5** built-in fallback.
- **uvicorn** single event loop (R2: no threads, `loop="auto"`).

## Core Architecture

### Entry Point: `bot.py`
- **Router registration order (CRITICAL - DO NOT CHANGE):**
  1. `summary_observer_router` (0a) - catch-all, saves ALL messages, returns UNHANDLED
  2. `summary_router` (0b) - /summary command
  3. `factcheck_router` (0c) - fact-check replies
  4. `search_router` (0d) - smart search
  5. `youtube_router` (0e) - YouTube URL processing
  6. `web_router` (0f) - web URL processing
  7. `checkup_router` (0g) - checkup triggers
  8. `direct_chat_router` (0h) - reply/mention to bot
  9. `voice_transcription_router` (0i) - voice/video transcription
  10. `admin_commands_router` - admin test commands
  11. `menu_router` - /menu command
  12. `debug_config_router` - hidden diagnostics
  13. `info_router` - /info + /edit_info
  14. `slava_presence_router` - ChatMemberUpdated (Slava return detection)
  15. `alan_greeting_router` - ChatMemberUpdated (Alan greeting video)
  16. `chat_lifecycle_router` - ChatMemberUpdated (bot lifecycle + migrate)
  17. `kostik_router` - user ID 350803143
  18. `alan_router` - user ID 138811255 (reply engine, every 10 msgs)
  17. `dead_page_router` - reposts from @d_pages
  18. `dead_page_delete_router` - reply/quote on deleted repost
  19. `war_alert_router` - keyword + channel repost alerts
  20. `common_router` - otboy/danger/selfdev/work/mimic
  21. `olya_router` - video from @ole4444444ka
  22. `video_download_router` - "скачай <url>" trigger
  23. `slavik_router` - user ID 479167456 (catch-all)
  24. `vasya_router` - text filters, no user restriction

### Configuration System
- **`config/settings.py`** - frozen `Settings` dataclass, reads from `.env` + env vars. Helper functions: `_env_int`, `_env_float`, `_env_bool`, `_env_str`, `_env_duration`, `_env_int_tuple`, `_env_int_min`, `_env_float_min`, `_env_int_optional`.
- **`services/hot_config.py`** - `hot.get(pg_key, default)` runtime hot-config over PG. Two-tier typing: catalog-aware coercion (`_coerce`).
- **`services/config_cache.py`** - `ConfigCache`: in-memory cache of `bot_settings`, `bot_roles`, `bot_admins`. `init()` with retry + fail-open (R6: PG down → WARNING, bot works on settings defaults). Asyncio.Lock on writes. Hot-reload via POST /api/config.
- **`services/chat_params.py`** (Round 10) - per-chat override layer: `chat_params` JSONB + `gates_opt_in` + `chat_keys` (BYOK). `ChatParamsCache` with NOTIFY listener.

### RBAC & Permissions
- **`services/permissions.py`** - pure matcher (`Permissions` class, bitmask-style flags).
- **`services/roles.py`** / **`services/access.py`** - RBAC v2: `role_type` (built-in vs custom), `access_for` (global/chat/both), `can_edit_param`.
- **`services/param_catalog.py`** - `REGISTRY` of 383 `ParamSpec` (71 groups). Fields: `per_chat`, `progressive_level`. Single source of truth for config metadata.

### Database Layer
- **`services/database.py`** - SQLite (aiosqlite). Tables:
  - Core: `user_presence`, `message_counters`, `dead_page_posts`, `channel_state`, `relay_album_map`
  - SmartModule Summary (Epic 24): `smart_messages` (+ FTS5), `smart_archive_facts` (+ FTS5), `smart_archive` (sqlite-vec, lazy), `nodes`, `edges`, `graph_facts` (+ CHECK origin, `importance`, `source_ids`, `kind`, `belief_meta`, `weight`, `confirmed_at`, `expires_at`), `graph_facts_vec` (sqlite-vec), `embedding_cache`, `compression_log`, `user_memory`
  - DirectChat (Epic 50): `throttle_state`, `bot_replies`
  - Video (Round 3): `video_origins`
- **`services/pg_db.py`** - PostgreSQL (asyncpg). Idempotent DDL + seeds. Tables:
  - Config: `bot_settings` (key, value JSONB, category, updated_at), `bot_roles` (role_name, permissions JSONB, is_custom, role_type), `bot_admins` (telegram_id, role_name, added_by, created_at)
  - Uptime: `uptime_events`
  - Chat Lore (Round 7): `chat_profiles` (chat_id PK, manual_lore, auto_lore, auto_enabled, auto_period_hours, auto_window_hours, is_active, last_auto_at, updated_at, **relations JSONB**, **relations_enabled**, **chat_params JSONB**, **gates_opt_in**), `chat_lore_history`, `chat_links`, `chat_admins` (chat_id, telegram_id, added_by, created_at, **role_name**)
  - RBAC (Round 10): `param_permissions`, `chat_keys` (BYOK), `chat_usage` (daily budget), `worker_budget` (daily ledger)
  - Migrations: ALTER TABLE ... ADD COLUMN IF NOT EXISTS for additive deltas

### LLM Client (`services/llm_client.py`)
- Single `httpx.AsyncClient` per process (lazy, `close()` in `on_shutdown`).
- Endpoints: `/chat/completions`, `/embeddings` (OpenAI-compatible).
- **Epic 47**: Retries ALL transient errors (httpx.TransportError + HTTP 408/425/429/5xx). Exponential backoff + jitter. `Retry-After` header priority for 429/5xx. Hard total budget: `LLM_TOTAL_BUDGET` via `asyncio.timeout`. 401/403 → `LLMAuthError` immediately.
- **Epic 53**: `LLMServerError`/`LLMTransportError` classes. Optional fallback provider (`LLM_FALLBACK_*`). Circuit Breaker lives in `direct_chat_service` (llm_client knows nothing about it).
- **Epic 67**: `VoiceTranscriber` (Groq Whisper / OpenRouter) with shared `asyncio.Semaphore` (`GROQ_MAX_CONCURRENCY`).

### SmartModule (Epic 24/26/33/37/42/50/60/67)
- **Summary (Epic 24)**: Three-level memory (L1 window, L2 FTS5-RAG, L3 archive + vec). `SummaryGenerator`, `MemoryManager`, `SummarySchedulerService`.
- **GraphRAG v2 (Epic 46)**: `memorize_facts` (Fact Extractor, canon R46-2), hybrid RAG (`build_rag_context`, canon R46-4), fire-and-forget hooks, vec reactivation, backfill.
- **Epic 60 (Phases A-D)**: Graph dedup (cosine thresholds), episode merge, time-decay, user quota, fact touch, int8 vec compression.
- **FactCheck + SmartSearch (Epic 33)**: `SearchAggregator` (Tavily/Exa), `FactCheckService`, `SearchService`.
- **YouTube + Web (Epic 37)**: `YouTubeTranscriptEngine` (failover: transcript-api → yt-dlp → Cobalt), `WebContentExtractor`, `YoutubeSummarizerService`, `WebSummarizerService`, `OpenRouterVideoClient` (L1/L2 video cascade).
- **Checkup (Epic 42)**: `CheckupService` + `CheckupLogsFetcher` (Betterstack SQL API + journalctl fallback).
- **DirectChat (Epic 50)**: `DirectChatService` with tools (`ToolRouter`), persistent throttle (`PersistentThrottle`), dedup cache (`smart_cache`), ChatLoreCache injection.
- **VoiceTranscriber (Epic 67)**: Shared instance with YouTube media branch.

### Background Workers
- **SchedulerService** - dead page relay scheduling
- **SummarySchedulerService** - daily summary generation (starts BEFORE polling)
- **GoodmorningSchedulerService** - daily goodmorning media
- **MemoryBackupService** - daily VACUUM INTO + text export
- **MemoryMaintenanceService** - episode merge + fact review (JobStore)
- **UptimeHeartbeatService** - 60s heartbeat to `uptime_events`
- **LoreWorker** (Round 7) - auto-lore generation from chat messages (PG profiles)
- **DreamWorker** (Round 9) - "sleep": beliefs from recurring facts (SQLite state)
- **NostalgiaWorker** (Round 9) - "golden layer" nostalgia (1 year ago facts)
- **RelationsService** (Round 9) - users_meta lazy recompute + manual merge from PG

### Web Layer (TMA, Vue 3 global, no build)
- `web/app.py` - FastAPI app, creates `ConfigCache` + `ControlService`
- `web/index.html` + `web/app.js` - SPA, no build step
- API routes: `web/api/` (access, chat_lore, avatars, oversight, config, admins, roles, params, permissions, keys, usage, status, logs, direct_chat, relations, workers, system)
- Chat selector: GET `/api/access/chats` + `X-Chat-Id` header
- 5 menu sections + modules_feats + tabs: PERMsoc/Промпты/Лимиты/LLM/Память-RAG/Реакции-Триггеры/Доступы/Лор/Статус/Как это работает

### Deploy
- `deploy_v2.9.2.py` - prod deploy (DDL + backfills)
- `scripts/backfill_*` - backfill scripts
- Prod: 198.46.175.136:/var/www/admin_bot (systemd admin_bot)
- `docker-compose.yml` / `docker/` - local PG
- `ControlService` flag-file stop mechanism (Epic 85)

### Security Notes
- Raw API keys NEVER logged (R17); `/api/config` masks secrets `{configured,last4}`
- `BetterStackHandler` custom (logtail 0.4.0 had silent drops)
- `log_ring` in-memory ring buffer for `/api/status/logs` (secret masking in emit)
- fail2ban/ufw/SSH hardening on prod
- BYOK (Bring Your Own Key) per-chat via `chat_keys` (Round 10)

## Key Data Flows

### Message Processing
```
Update → Dispatcher → Router chain (fixed order)
  → summary_observer (save to smart_messages, UNHANDLED)
  → summary / factcheck / search / youtube / web / checkup / direct_chat / voice
  → admin / menu / debug / info
  → slava_presence / alan_greeting / chat_lifecycle (ChatMemberUpdated)
  → kostik / alan / dead_page / dead_page_delete / war_alert
  → common (otboy/danger/selfdev/work/mimic)
  → olya / video_download / slavik / vasya
```

### Config Read Path
```
Service → hot.get(pg_key, settings.DEFAULT)
  → ConfigCache.get(key) [sync, in-memory]
  → if miss: settings.DEFAULT
  → PG writes via ConfigCache.set() + hot-reload
```

### LLM Call Path
```
Handler → LLMClient._post()
  → retry loop (transient errors only)
  → asyncio.timeout(LLM_TOTAL_BUDGET)
  → 401/403 → LLMAuthError
  → 5xx exhausted → LLMServerError
  → TransportError exhausted → LLMTransportError
  → (optional) fallback provider
```

### Worker Budget (Round 10)
```
worker_budget.consume(scope, metric, cost)
  → PG ledger (worker_budget table)
  → Priority: nostalgia → lore → dream
  → Degradation when budget exceeded
```

## Module Dependencies (High-Level)
```
bot.py
├── config.settings
├── services.hot_config
├── services.config_cache (ConfigCache)
├── services.database (DatabaseService)
├── services.pg_db (PgDatabase)
├── services.llm_client (LLMClient)
├── services.summary_memory (MemoryManager)
├── services.summary_generator (SummaryGenerator)
├── services.direct_chat_service (DirectChatService)
├── services.lore_* (ChatLoreStore/Cache/Notify/Worker)
├── services.dream_worker (DreamWorker)
├── services.nostalgia_worker (NostalgiaWorker)
├── services.user_relations (RelationsService)
├── services.worker_budget
├── services.oversight
├── services.memory_backup
├── services.memory_maintenance
├── services.search_aggregator (SearchAggregator)
├── services.factcheck_service
├── services.youtube_* / web_*
├── services.voice_transcriber
├── handlers.* (23 routers)
├── web.app (FastAPI)
└── services.control_service (ControlService)
```

## Recent Changes (from git status)
- Round 10.3 (uncommitted, HEAD d30b203): F-13/F-14/F-15 — см. full_audit_results.md «Round 10.3».
- `plans/reports/` - audit infrastructure

## Round 10.3 map additions (F-13/F-14/F-15)

- **DM-скоуп** = `chat_id > 0 && chat_id == telegram_id` (`services/chat_params.py::is_dm_scope` —
  единственный идентификатор). DM-профили = строки `chat_profiles(chat_id=user.id)` (ноль DDL).
- **`services/roles.py`**: `AccessCtx.is_dm_owner: bool = False` (в конец полей); DM-ветка в
  `access_for` ДО chat_admins-лукапа: role_chat=None, perms_chat=`DM_OWNER_PRESET`
  (sections: prompts/limits/flags/reactions/content/memory; БЕЗ chat_lore), rank=max(ранг,3).
- **`services/access.py`**: `can_access_chat(ctx, chat_id=None)` — аддитивный chat_id: DM →
  только is_dm_owner (global admin в чужом ЛС → False). `eligible_type`: is_dm_owner →
  local_admin. `can_edit_param`: ветка is_dm_owner после is_global_admin, до role_chat-гейта.
- **`services/chat_params.py`**: `ensure_scope_profile(chat_id, dm=True)` (INSERT ON CONFLICT,
  auto_enabled=false, is_active=true, gates_opt_in=false) — перед первым write DM;
  `get_chat_param_defaulted(chat_id, key, fallback)` (override→cast→fallback, БЕЗ hot.get);
  `chat_summary_enabled(chat_id)` — группа: hot.get (байт-в-байт); ЛС: defaulted False.
- **Саммари-гейт S1/S2/S3**: summary_memory.get_window_messages (~:1291),
  direct_chat_service._build_global_context (~:1707), summary_scheduler._tick (skip chat_id>0).
  bot.py:613-643 — НЕ тронут. L3/GraphRAG — не гейтится.
- **Изоляция DM**: chat_lore_store LIST_ACTIVE_CHATS_SQL/LIST_ACTIVE_CHAT_IDS_SQL/list_profiles +
  oversight PROFILE_COLS_SQL + web/api/access CHATS_FOR_USER_SQL — WHERE chat_id < 0;
  web/api/chat_lore._require_chat → is_dm_scope → 404; gates PUT DM → 403 (GET read-only 200).
- **TMA**: /api/access/chats + /me синтезируют DM-строку {chat_id: user.id, title: «Личные
  сообщения», access:'dm', is_dm:true} для любого авторизованного; GET /api/config X-Chat-Id=ЛС:
  keys.* скрыты (не global admin), models.* — read-only справка (per_chat=False), ctx.is_dm=true.
- **Фронт**: единый select-селектор (F-13 AC-1; бейдж `#id`/`ЛС #id`); configError-баннер
  (403/503/сеть, MED-021) с «⟳ Повторить»; `<template v-for>` + v-if на дочернем div (AC-3);
  z-index sidebar 45 (AC-5); isDmCtx()/canViewTab-DM-ветка (config кроме permsoc)/canEditConfig-DM
  (все кроме keys.*)/resetChatOverride (+isDmCtx). BYOK-блок покрывает DM без изменений.
- **F-15**: `NoApiKeyForChat(chat_id, reason, details=None)` — details-снапшот (resolve_path/day/
  used/limit — R17); BYOK-фоллбэк: повторное чтение своего ключа ПОСЛЕ budget_exceeded (1 доп.
  SELECT, usage не тратится); WARNING `[direct] no key — sandbox answer | details=…`;
  summary_memory: `_mask_llm_raw` (500 симв., секрет-паттерны), WARNING memorize c raw-фрагментом;
  `_fallback_parse_facts` (JSON-в-тексте/тройки/csv/ёлочки/тире); 1 ретрай жёстким промптом
  `_FACT_RETRY_SYSTEM_PROMPT` ТОЛЬКО в _memorize_facts_inner (крон _extract_and_save_graph — нет).

## Round 10.4 map additions (A/B/C/D/E/F/G/H, HEAD 1410a68 + working tree)

- **Per-chat read-path (G-3) — расширение `get_chat_param` точки** (async, кэш 120с+NOTIFY):
  `direct_chat_service._build_user_content` (budget-гейт `flags.chat_context_budgets_enabled` +
  база `limits.chat_context_budget_tokens` → `_apply_context_budget(blocks, enabled, tokens)`),
  `_active_participants` (map hours/cap), `_build_global_context` (global_context_limit/max_tokens/
  max_chars, level2_max_chars), `_collect_thread_chain` (thread_max_depth),
  новый **`_thread_limit(chat_id)`** (thread_max_tokens/max_chars → `_render_thread` 3-й параметр,
  None → старое поведение), `summary_generator.generate` (summary_rag_l2_limit/
  max_context_tokens/max_context_chars), `summary_memory` get_window_messages (summary_max_window_
  messages), get_rag_context (graph_rag_facts_limit/context_max_chars), _compress_and_purge/
  _compress_purge_extract_only (full_memory_retention_days/summary_compress_batch), memorize
  edge_weight_increment, _purge_archive (archive_memory_retention_days).
- **G-2**: `chat_params._resolve_from_root` — после normalize_value проверка `_cast_type_ok`
  + `math.isfinite` для float (NaN/inf/мусор → hot.get-фолбэк; AC-G4).
- **B-12**: `summary_aliases.build_alias_resolver(chat_id)` — per-chat алиасы (override →
  глобальные; fail-open глобальные; НЕ зависит от summary_enabled). ↓ ДОСЛОВНО НЕ доведён до
  инжекта `<user_relations>` — documented limitation (user_relations.py), кандидат F-5.
- **B-7/B-8**: ParamSpec += `select_options/select_labels` (tuple, дефолт ()); запись
  `CHAT_TEMPERATURE_PRESET_DEFAULT` — widget select ("precise"/"balanced"/"chatty" +
  labels); применяется через dataclasses.replace после _build_registry (REGISTRY 383 без роста).
  Append-метка: `_SELECT_WIDGET_PRESETS`.
- **TAB_RULES (каталог)**: 10 вкладок-частей: llm_providers — 4 секции (повтор MODELS/KEYS),
  limits — except расширен (mimic/deadpage/media/lore/user_aliases/relations и флаги),
  memory_rag (infinite) + memory_dream + memory_nostalgia, reactions_triggers (4),
  permsoc (11+2+4), modules_switches, chat_lore (limits_lore+flags_lore — правило НЕ-config
  вкладки), people_names (limits_user_aliases), relations (limits_relations+flags_relations).
  `_TAB_BY_GROUP`: 72 группы (как HEAD; content_info/content_media — никогда не были на
  конфиг-вкладках). NEW правил: NONE потеряно/добавлено.
- **Фронт**: TABS-зеркало (new: memory_dream/memory_nostalgia/people_names/relations/
  modules_switches; chat_lore += sources), `flatGroupRank` (порядок ПРАВИЛ → витрина;
  fallback catFirst; для вкладок без повтора категорий = старой категориальной),
  `sectionTitle` (заголовок секции — раз на секцию; только у llm_providers),
  `chatLoreTab()`/`relationsTab()` (TABS-записи для groupedForTab конфиг-частей),
  setTab: relations-автозагрузка (не DM), сброс лор-профиля при уходе с chat_lore,
  relations-методы: relChat = activeTab==='chat_lore' ? p.chat_id : activeChatId.
- **B-9 (routes.py)**: GET items += select_options/select_labels (None для не-select);
  POST-валидация опций в ОБЕИХ ветках (per-chat :413-417 и _post_config_global :671-675).
- **H-2 (chat_lore.py list_relations)**: username-обогащение ВСЕМ строкам (Semaphore(5), gather),
  photo — только топ-50 (второй проход; кэши avatars 1ч); `_RELATIONS_SEMAPHORE_LIMIT=5`.
- **backfill_104_chat_flags.py (B-4)** / **backfill_104_overrides.py (G-5)**: ensure_scope_profile
  dm=False + set_chat_params (запись только отсутствующих ключей; expected_updated_at=None;
  --dry-run). Overrides: 14 × множитель (скрипт; 2 ключа с Settings=None — SKIP: см. отчёт).
- **Скрипты/отчёты**: plans/reports/round10.4_review_fixes.md — отчёт ревью-фиксов Builder.

## Round 10.5 map additions (tma-relume-redesign, HEAD 0bdf272 + working tree)

- **Каталог**: `services/param_catalog.py` += `_MODELS_PG_ONLY` (4 PG-only записи:
  `models.groq_base_url`, `models.groq_transcribe_model`, `models.openrouter_base_url`,
  `models.openrouter_transcribe_model`; group `models_extra_providers`, `settings_field=None`,
  `code_source` = код-литерал). Итог: **REGISTRY 387 / GROUPS 74 / Settings 359**.
  Сид в PG — `pg_db._seed_settings` (resolve_code_source → `INSERT … ON CONFLICT DO NOTHING`,
  safe migration: существующие keys.* не перезатрёт).
- **Key-availability (B1/OD8/OD12/OD19)**: новый `services/key_history.py` — `KeyHistory`
  (in-memory `deque(maxlen=288)`, 5-мин слот, персист `var/status_key_history.json`,
  атомарный `tmp`+`os.replace`, права 0o600/0o700, allowlist `module_id/provider/model/
  samples{ts,ok,http_status}`). Singleton `services.status_service.key_history`.
  `status_service.llm_registry()` += `module_id/module_title/model_source`; `_build_llm_card`
  → `key_history.record(...)`; `build_snapshot` → `key_history.maybe_save()` (1/5 мин).
  API: `GET /api/status/key-history` (any TMA user) → `key_history.api_payload()`.
  `conftest.py` — M6: `STATUS_KEY_HISTORY_FILE` → temp (тесты не пишут в `var/`).
- **Data-driven модели (OD11/OD16)**: `groq_transcriber`/`openrouter_transcriber`/
  `video_cascade_client` читают `models.*_base_url`/`models.*_transcribe_model` через
  `hot.get(pg_key, <прежний литерал>)`; клиенты инвалидируются и по смене base_url
  (`_client_base`). Литералы — документированный дефолт (safe migration).
- **Rename/Delete ролей (OD15)**: `web/api/routes.py` — `DELETE /api/roles/{name}`,
  `POST /api/roles/{name}/rename` (superuser→403, builtin→409, занятая/wildcard→409);
  `services/config_cache.py` — `rename_role` (транзакция: INSERT SELECT + UPDATE bot_admins
  + scrub + DELETE), `role_usage`, `_scrub_param_permissions` (DML-only, ноль DDL).
  `get_roles` += `role_type`. UI: `canEditRole`/`isSuperuserRole`/`renameRole`/`deleteRole`.
- **Матрица ролей (OD10)**: `web/api/access.py::param_permissions_list` +=
  `tab/tab_title/group/group_title/group_order/category/title/secret`; UI
  `loadMatrix/matrixSections` (секция = config-вкладка `TAB_SECTION_ORDER`, группы по
  `group_order`, read/write `user/moderator/local_admin`). Только global admin.
- **Hash-роутер + navbar/hub (OD1/OD13/T-1099/T-1100)**: `web/app.js` — `ROUTE_TO_TAB`/
  `TAB_TO_ROUTE`/`ROUTE_PARENT`/`ROOT_ROUTES`/`HUBS`/`NAV_ITEMS` (6 пунктов эталона),
  `normalizeRoute` (только `#/`), `initialRoute` (`#/`→sessionStorage→`#/`),
  `hashchange` — единственный применитель, `applyRoute` (hub-aware RBAC), `goBack`
  (по parent, без history.back), `initBackButton` (`BackButton.onClick` 1 раз, guard
  Bot API 6.1+), `syncBackButton` (depth>0 → show). `__TMA_BACK__=true`, `__TMA_DEEPLINK__=false`.
- **Scope-switcher (OD7/T-1127)**: `scopeKind/scopeLabel/scopeOptions/scopeTrigger*`,
  `toggleScope/scopeMove/scopePickFocused/pickScope/isScopeSelected/ensureScopeAvatars`;
  `setActiveChat` += `scopeEpoch++` + сброс chat-scoped состояния + relations-reload.
  Все chat-scoped загрузчики — `_scopeGuard(epoch)` в success/catch/finally (R1/R2/R3).
- **Дизайн-токены (OD4/OD5)**: `web/index.html` — токен-слой (`--surface-*`, `--teal-500`
  и пр.), `@property --grad-angle inherits:false`, `grad-spin`/`grad-drift`,
  `prefers-reduced-motion`/`prefers-contrast`; удалён hardcode `#8b5cf6/#3b82f6/#2b2b40`.
  `@font-face` Material Symbols Rounded (субсет `web/static/fonts/material-symbols-rounded.woff2`
  13 428 B + LICENSE); `app.js ICONS` — 26 PUA-кодов (сверено с код-каноном и cmap субсета).
  Self-host `web/static/vendor/dompurify-3.4.15.min.js`; `sanitizeHtml` fail-CLOSED.
  `web/app.py` монтирует `/static` (`CacheControlStaticFiles`, RuntimeError-guard).
- **Гигиена**: `.gitignore` += `relumesite_example/`, `MaterialSymbolsRounded*.woff2`,
  `var/`, `build/`; `scripts/build_font_subset.py` + `scripts/requirements-font.txt`
  (build-time only, `fonttools`/`brotli` НЕ в runtime).
- **Отчёты**: `plans/reports/round10.5_scanner_audit.md` (0 блокеров / 0 major,
  2 minor + 5 info); `full_audit_results.md` §Round 10.5; `audit_backlog.md` (10.5).