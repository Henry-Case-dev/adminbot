# Global Map (architectural memory)

> Архитектурная память Scanner. Не источник правды о коде — только карта связностей.
> HEAD == da85b60 (10.9 docs) + рабочее дерево 10.10 (admin-ui-round1010, 2026-09-12).
> origin/master == d2d1215 (10.9 deployed; 10.10 — не задеплоен, сканирование).
> Каталог-инвариант 10.10: REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88 / TAB_RULES 19.
> П.6 (Headroom) — OUT OF SCOPE репозитория, в коде ссылок нет.

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
- **`services/param_catalog.py`** - `REGISTRY` of 392 `ParamSpec` (91 groups) — 10.6. Fields: `per_chat`, `progressive_level`. Single source of truth for config metadata (`TAB_RULES` 19 вкладок).

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
- 6 пунктов навигации (10.8): Статус / Справка / Модули / ИИ / PERMsoc / Доступы
  (+ хаб «Доступы»: подразделы Матрица ролей / Локальные админы / Роли — route-driven модалки)

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

## Round 10.6 map additions (tma-ia-modules-rework, HEAD be7b85b + working tree)

- **Каталог**: `services/param_catalog.py` — REGISTRY **392** / GROUPS **91** /
  Settings **364** / mapped **89**; `TAB_RULES` (19 вкладок) + `CONFIG_TAB_TITLES` (19) +
  `_TAB_BY_GROUP` (89). Расщепления: `limits_media`→`limits_media_permsoc`(7)+
  `limits_transcribe`(6)+`limits_video_summary`(3)+`limits_media_download`(1);
  `limits_persons`→`limits_alan`(3)+`limits_kostik`(1); `limits_youtube_web`→
  `limits_youtube`(2)+`limits_web`(2); `limits_cooldowns`→0; `flags_modules`→7 групп
  (`flags_module_*`, checkup→`flags_service`); `flags_chat_behavior`→7 + `flags_summary` +
  `flags_permsoc_behavior`; `reactions_persons`→2 + `reactions_alan`(3) + `reactions_kostik`(1);
  `limits_chat_budgets`→10 (flags+9), `limits_chat`→25; NEW `limits_rag`(2)→`memory_rag`.
  5 NEW master-флагов: `FACTCHECK_ENABLED`/`SEARCH_ENABLED`/`VIDEO_SUMMARY_ENABLED`/
  `WEBPAGE_ENABLED`/`CHECKUP_ENABLED` (default True; `_FLAGS`). PG-ключи/значения НЕ мигрируют.
- **Runtime-гейты (A1)**: `handlers/factcheck.py:169`, `search.py:109`, `web.py:104`,
  `checkup.py:77` — `hot.get("flags.*_enabled", settings.*)` → `UNHANDLED`;
  `youtube.py:1019` — только `request.mode == "summary"` (transcript продолжает работать).
  `bot.py` порядок роутеров НЕ тронут; `services/database.py`/`pg_db.py` без диффа
  (SQLite v8, ноль PG-DDL; seed новых флагов = `true` через `_seed_settings`).
- **`POST /api/llm/test` (T-1210/A4/D4)**: `web/api/routes.py:1225` (`LlmTestRequest:126`),
  `requires_global_admin`, rate-limit `(user,block)` ≥5с → 429, TTL-прунинг `_LLM_TEST_LAST`;
  `reset_llm_test_rate_limit()` — тест-точка. Логика — `services/llm_probe.py`:
  `_safe_base` (https/loopback-http), `sanitize_error` (R17), `KNOWN_BLOCKS`
  (`direct_main/direct_fallback/transcribe_groq/transcribe_openrouter/
  video_summary_openrouter/embeddings/search_keys[:tavily|:exa]/media_share/
  checkup_betterstack`; `llm_guard` намеренно отсутствует), `_probe_search`
  (Exa/Tavily фиксированные endpoints).
- **TMA-каркас**: `web/app.js` — `MODULES` (11: self-flag `toggleKey` + `tab`),
  `PROVIDER_BLOCKS` (9 блоков по модулям; `testable:false` у `embeddings`/`llm_guard`;
  `perFieldTest` у `search_keys`), `accessOpen ∈ {null,'roles','local','admins'}` +
  `setAccess`, `activeModule/activeModuleGroups/_syntheticGroup('content','content_media')`,
  `openModuleWindow/closeModule/_ensureModuleData` (Сон/Ностальгия-панели в модалке),
  глобальный Esc (`_onKeydown`), `ROUTE_ALIAS` (legacy hash → канон через `replaceState`),
  `TAB_SECTION_ORDER` 19, `TAB_TO_ROUTE`/`ROUTE_TO_TAB` без удалённых роутов;
  `NAV_ITEMS` 6, `iconGlyph` Material. `web/index.html` — sidebar/☰/MENU_ORDER удалены,
  `.navbar-band`/`.nav-label`, `.app-shell`/`.scroll-area`/`.fullscreen-mode`,
  модуль-карточки + модалка, prov-блоки + test-кнопка, аккордеон `acc-*`,
  `#/how` и матрица — Material-иконки. DM `canEditConfig` учитывает `per_chat===false`
  (R10.5-2 closed); `initBackButton` на `ready` (R10.5-1 closed).
- **PERMsoc**: 10 миселённых ключей → М5(6)/М6(3)/М7(1); Леха=Леха (`reactions_alan`+
  `limits_alan`), Костик (`reactions_kostik`+`limits_kostik`) — раздельно; `flags_media`
  остаётся в PERMsoc. `keys_youtube`→М6; `models_checkup`/`keys_betterstack`→М9.
- **Находки**: `plans/reports/round10.6_scanner_audit.md` (0 блокеров/0 major;
  3 minor: R10.6-1 LLM-дубль редакторов, R10.6-2 https-SSRF, R10.6-3 422-эхо `api_key`;
  3 info).

## Round 10.7 map additions (admin-ui-bugfixes-round107, HEAD 2ccf558 + working tree)

- **TMA scope-производные (1a)**: `web/app.js` — 6 `scope*` (`scopeKind/scopeLabel/
  scopeOptions/scopeTriggerTitle/scopeTriggerInitial/scopeTriggerAvatar`) перенесены из
  `methods` (~:1313-1371) в `computed` (`:914-974`). Потребители — только property-доступ
  (`{{ scopeLabel }}`, `scopeOptions.length`, `scopeOptions[i]` в `scopeMove`
  `:2097`/`scopePickFocused` `:2103`); вызовов `()` нет. Исправляет рендер
  `function () { [native code] }` и клавиатурную scope-навигацию. `scopeEpoch`-гварды не тронуты.
- **CSS шапки/навбара (`web/index.html`)**: `header.header-sticky` (0,1,1) + horizontal
  `env(safe-area-inset-left/right)` (1b); компактный user block `w-6/gap-1.5/text-xs/
  max-w-[7rem]` (1c); `.nav-label` `word-break:keep-all` + `-webkit-line-clamp:2` +
  `text-overflow:ellipsis` + `0.625rem` (1d); scoped `.keys-avail .avail-list`
  `table-layout:fixed` + ширины 34/18/30/8/10% + ellipsis + `:title` (2a); `.clipboard-ghost`
  `opacity:0` + `contain:strict` (без `visibility:hidden`) (3a); `.log-level/.log-ts/.log-logger/
  .log-msg` + `.log-panel .log-code` (3b); `.log-copied` (3c).
- **Логи (`web/app.js`)**: `fmtLogTime` (`:3285`) HH:MM:SS (полный ts — в `:title` через
  `fmtLogTs`); `copyText` — `focus({preventScroll:true})`, `execCommand` по boolean,
  `ta.remove()`+обнуление `window.__adminbotClipGhost` в `finally` (`:3309-3342`);
  `copyLogRow(log,i)` + `copiedIndex`/`copiedTimer` 800 мс + `.log-copied` (`:3344-3353`);
  `copyAllLogs` — `self.logText(l)`.
- **ICONS (R106-5)**: удалены 6 мёртвых ключей (`account_balance_wallet/stop_circle/
  theater_comedy/toggle_off/toggle_on/speed`); осталось 20; независимая проверка `fontTools`
  — все 20 PUA-кодов в cmap субсета (26 глифов), ребилд шрифта не нужен. `test_font_subset`
  теперь проверяет `\ue887` (`help`).
- **Uptime (2b, `services/status_service.py`)**: `_bucketize` (`:260-301`) — непрерывная
  5-мин сетка от `min(buckets)` до `now_slot` включительно; пустые слоты `status="down"`
  (нет heartbeat ⇒ простой); `[]` при пустых rows; `ts < since` отсекается; `[-288:]`.
  `build_snapshot` → `last_heartbeat` = ts последнего `up`-бакета, иначе `None`
  (`:376-378`). `uptime_heartbeat.py:26` не тронут (пишет только `'up'`; down деривится).
  Фронт `renderUptimeChart` не менялся (`down→0`, `spanGaps:false`).
- **Находки 10.7**: `plans/reports/round10.7_scanner_audit.md` (0 блокеров/0 major;
  1 minor: R10.7-1 граничный ложный `down`/`last_heartbeat` до ~60 с после 5-мин границы;
  3 info: R10.7-2 `[-288:]` может отсечь единственный ранний `up`; R10.7-3 `copiedTimer`
  не чистится при смене вкладки; R10.7-4 `test_font_subset` не сверяет cmap WOFF2).
  R10.6-5 закрыт; R10.6-1/2/3 открыты (кандидаты 10.8).

## Round 10.8 map additions (admin-ui-round108, HEAD 636a75d + working tree)

- **Имена разделов (видимые подписи, route-ключи НЕ менялись)**: `NAV_ITEMS`/`TABS`/`HUBS`
  (`#/how`→«Справка», `#/ai`→«ИИ», `#/permsoc`→«PERMsoc», `#/access`→«Доступы»,
  `#/oversight`→«Сводка»); каталог-группа `flags_permsoc` («Функции PERMsoc: рубильники»)
  НЕ переименована.
- **Иконки/субсет (ADR-002)**: `web/app.js ICONS` **37** (20 базовых + 17 новых 10.8;
  6 мёртвых 10.7 удалены) == `scripts/build_font_subset.py ICON_NAMES` (37). PUA —
  из GSUB reverse-cmap (`build/icon_codepoints.json`). Маркер идемпотентности =
  `sha256(src_sha + "|" + ",".join(ICON_NAMES))` (`_marker_key`). Субсет
  `web/static/fonts/material-symbols-rounded.woff2` 18 388 B, cmap = ровно 37 PUA-кодов.
  `test_font_subset`: Test A (паритет), Test B (cmap через `fontTools`), C (нет
  pictographic-emoji в `web/`), D (6 мёртвых имён) — **R10.7-4 закрыт**.
- **Логи (`web/app.js`/`web/index.html`)**: блочная раскладка — `div.log-code` →
  `div.log-row` → `div.log-head` (flex-wrap) + `div.log-msg` (width:100%, pre-wrap,
  overflow-wrap:anywhere); жёсткие `.log-level{min-width:4.5rem}`/`.log-ts{width:8ch}`/
  `.log-logger{max-width:8rem}` и Tailwind `break-all` удалены; toggle — Material
  `chevron_right`/`expand_more` ТОЛЬКО при `log.exc_text` (иначе `log-toggle-spacer`),
  `@click.stop`, `:aria-expanded`; `fmtLogTime` = `DD.MM HH:MM:SS` (`fmtLogTs` — `:title`);
  `setTab` чистит `copiedTimer`/`copiedIndex` (**R10.7-3 закрыт**). Контракт `/api/logs`,
  `logText`/`copyAllLogs`/ghost-fallback — без изменений.
- **«Доступы» (ADR-001)**: `accessOpen ∈ {null,'roles','local','admins'}` — производная hash
  в `applyRoute` (`route.indexOf('#/access/')===0 ? substring : null`; не-access маршрут
  обнуляет → нет stale-окна). `openAccessWindow(id)`/`closeAccessWindow()` (`setAccess`
  удалён), `isAccessOpen` сохранён. Разметка: 3 `hub-card`-плитки + 3 взаимоисключающих
  `modal-backdrop` (роли/локальные/роли-назначения), id `sec-roles/sec-matrix/sec-local/
  sec-admins` сохранены; `#/access` — hub-карточки без `section`; `ROUTE_PARENT`
  `#/access/*`→`#/access` (BackButton/`goBack`), RBAC (`canViewTab`, `isGlobalAdmin`,
  `canEditRole`) сохранён. «Администраторы»→«Роли».
- **Шапка**: внешний дубль GLOBAL-бейджа удалён; `{{ scopeLabel }}` — ровно 1 раз внутри
  trigger; computed `scopeLabel`/`isChatContext()` сохранены.
- **README**: «Самое важное для пользователя» + «Управление и деплой» наверх; changelog
  10.3–10.8 под единственным `<details>`; шапка v2.52.0 / 5073 / раунд 10.8.
- **Находки 10.8**: `plans/reports/round10.8_scanner_audit.md` (0 блокеров/0 major;
  2 minor: R10.8-1 Esc не закрывает access-окна при фокусе вне модалки; R10.8-5
  `APP_VERSION`=2.51.0 vs README v2.52.0 (`/api/status`) + `@font-face`-URL не версионирован,
  `.woff2` `max-age=86400` → старый субсет в кэше до 24 ч → tofu новых иконок; 3 info:
  R10.8-2 stale-комментарий `section`/осиротевшая ветка `openHubCard`; R10.8-3 мёртвый
  `TABS.icon`/`visibleTabs`/`tabMat` (pre-existing); R10.8-4 backlog-статус «ПЛАНИРОВАНИЕ»).
- **Открыто** (кандидаты 10.9): R10.7-1/-2 (`services/status_service.py` gap-fill);
  R10.6-1 (дубль generic-рендера `llm_providers`); R10.6-2/-3 (SSRF/422-эхо `api_key`).

## Round 10.9 map additions (admin-ui-round109, HEAD 51f308b + working tree)

- **PERMsoc owner-блоки (ADR-109-4)**: `web/app.js PERMSOC_OWNER_BLOCKS` — 4 блока
  (`slavik`/`olya`/`mimic`/`common`); один тумблер в `<summary>` (`PERMSOC_TOGGLE_KEYS`
  исключает 4 флага из тела). Принадлежность: `key∈owner.keys` → `group∈owner.groups &&
  key∉∪owner.keys` → `common`. Backend: новый `SLAVIK_ENABLED` (default **True**) +
  `PermsocModule("slavik", …, sub_flag_key="flags.slavik_enabled")` +
  `DEFAULT_SUB_FLAGS[...] = True`. `reactions_persons` удалена (GROUP 91→90),
  `SLAVIK_USER_ID`→`reactions_slavik`, `OLYA_USER_ID`→`reactions_olya`. Переключение:
  `toggleOwner` (common+чат → `togglePermsoc`/`gates.permsoc`; иначе `saveConfigItem`).
  Сводка 5 модулей (`permsocModuleBadge`) переехала внутрь «Общего».
- **Скролл (п.3)**: `web/app.js _preserveScroll(fn)` — снимок/restore
  `document.scrollingElement` **и** `main.scroll-area` (fullscreen TMA) в `$nextTick`;
  обёрнуты все save-пути. `web/index.html`: спиннер только при
  `configLoading && !configItems.length` (ре-фетч не подменяет карточки). `setTab`-сброс вверх не тронут.
- **Одностраничный dashboard/health (ADR-109-3)**: `web/index.html` — ОДИН блок
  «Доступность ключей» (`llmGroups` из `/api/status.llm` по `group_id`): 4 группы
  (`llm_functions`/`transcription`/`video_summary`/`embeddings`). `status_service.llm_registry`
  отдаёт `module_id/module_title/group_*/display_name/provider=host(base_url)/model/key/
  latency_key/kind`; `_check_health(module_id,…)` → `llm_probe.probe_openai`:
  `kind="chat"` `/chat/completions`, `"embeddings"` `/embeddings`, `"stt"` (только `stt_groq`)
  `/audio/transcriptions` (multipart, `_silent_wav`); таймаут 5с; кэш по `module_id`
  (2xx 60с / ошибки 10с, stale-200 нет); статусы `ok|error|timeout|unreachable|not_configured`.
  `stt_openrouter` — `kind="chat"` (input_audio через `chat.completions`). Старый блок
  переименован в «История доступности ключей».
- **Кастомные имена моделей (ADR-109-1)**: 7 `ParamSpec` `models.*_display_name` (+Settings)
  — первое поле каждого provider-блока (`PROVIDER_BLOCKS`), глобальные; питают dashboard
  через `_display()`. REGISTRY 392→400, Settings 364→372.
- **«Тяжёлые фичи» (п.5) / «Бюджет фона» (п.6, ADR-109-5)**: карточки с «Модулей» удалены;
  per-chat `dream/nostalgia/lore_auto` — только в «Сводке» (модалка → `toggleKillswitch`);
  «Бюджет фона (день)» — полоса в `#/oversight`, источник `loadBudgetInfo()` из `loadOversight`.
  Backend `worker_budget.py`/endpoint без изменений.
- **Итоговые инварианты 10.9**: REGISTRY **400** / GROUPS **90** / Settings **372** /
  mapped **88** / TAB_RULES **19** / CONFIG_TAB_TITLES **19**.
- **Находки 10.9**: `plans/reports/round10.9_scanner_audit.md` (0 блокеров/0 major/0 medium;
  3 low: R10.9-1 `model_source` запасных записей снова «code»; R10.9-2 `EMBEDDING_FALLBACK_*`
  из settings + display-name исчезает без env-ключа; R10.9-3 stale docstring `status_service`;
  3 info: R10.9-4 health-кэш по `module_id`; R10.9-5 doc `_LLM_BLOCKS`/`ConnectTimeout`;
  R10.9-6 backlog-статус).
## Round 10.10 map additions (admin-ui-round1010, HEAD da85b60 + working tree)

- **Fullscreen-шапка (п.1, CSS-only)**: `web/index.html` — новое правило
  `.fullscreen-mode header.header-sticky { padding-{top,right,left}: calc(base + max(env(safe-area-inset-*),
  var(--tg-content-safe-area-inset-*), var(--tg-safe-area-inset-*))) }` (Bot API 8.0 device/content
  safe-area CSS-переменные). Специфичность `(0,2,1)` перекрывает Tailwind `px-4 py-3` и `@media`.
  10.7 (горизонтальный env-safe-area) и 10.9 (`.fullscreen-mode .scroll-area`) не тронуты; JS не менялся.
- **Mobile key-chart (п.2, render-only)**: `web/app.js` — константы `SAMPLE_BUCKET=300` (==
  `services/key_history.SAMPLE_BUCKET_SECONDS`) и `MIN_BUCKETS=12`; чистая `keyHistoryChartModel(providers)`
  (дорожки `lane+0.75/0.25`, `y.max=laneCount+0.2`, временная сетка от `endBucket` с cap
  `MAX_HISTORY_POINTS` и полом `MIN_BUCKETS`, пропуск=null, `pointRadius:3` при ≤1 сэмпле,
  `height=max(120,44+lanes*22)`); `renderKeyHistoryChart` → `maintainAspectRatio:false` + `$nextTick`;
  реактивное `keyHistoryChartHeight` биндится на обёртку `.keys-chart` (`web/index.html`).
  Контракт `GET /api/status/key-history` (`api_payload`) НЕ изменён.
- **«Провайдеры» (п.3)**: `web/index.html` — `:value="blockFieldValue(f)"` + `@input` вместо
  `v-model="blockDrafts[f.key]"`; `web/app.js` — `blockFieldValue` возвращает `''` для пустого
  черновика (не откат), `blockDrafts`/`blockResults` сбрасываются в `loadConfig` (success) и
  `setActiveChat`; `saveBlock`/MINOR-3 (`null`=не трогать, `''`=очистить) без изменений.
- **DM heavy-modules OFF (п.4, DATA)**: `services/chat_params.py` — единые константы
  `_DM_DISABLED_GATES={"dream":False,"nostalgia":False}` и `_DM_DISABLED_OVERRIDES={memory.dream_enabled,
  memory.nostalgia_enabled, flags.summary_enabled, flags.chat_running_summary_enabled}`;
  `ensure_scope_profile(dm=True)` вставляет v-1-лейаут с этими дефолтами (INSERT ON CONFLICT, 0 DDL).
  Новый `scripts/disable_dm_heavy_modules.py` — dry-run (default)/`--apply`/`--chat-id`/`--snapshot-out`/
  `--restore`; raw `SELECT ... chat_profiles WHERE chat_id>0 AND is_active ORDER BY chat_id`; запись
  только через `set_chat_params` (merged overrides/gates, namespace-replace); snapshot только
  overrides/gates до записи (abort при ошибке), пустой патч = no-op (идемпотентность), `--restore`
  не трогает `meta`; partial-failure → exit 1. Групповой путь и `bot.py` (F-14) не тронуты.
- **«Роли»: enrichment (п.5)**: `web/api/avatars.py` — новый `global_user_display_info(user_id)`
  (`bot.get_chat(user_id)` → first/last → username без `@`; фото через общий `_user_photo_cache` +
  `getUserProfilePhotos(limit=1)`; RAM-TTL 1ч (`_user_name_cache`), fail-open; транзиентные
  `TelegramRetryAfter`/`TelegramNetworkError` НЕ негатив-кэшируются — паттерн BUG-4). `web/api/routes.py`
  `GET /api/admins` (`requires_permission("access")`) — обогащение КОПИЙ строк (`dict(a)`) через
  `asyncio.gather`+`Semaphore(5)`, поля `display_name`/`photo_file_id`, старые поля сохранены.
  Фронт `web/app.js` — `loadAdmins` грузит blob-аватары (`loadAvatar('user', id, admin)`), `adminInitial`;
  `web/index.html` — аватар/инициал + `display_name||username`, ID `text-[10px] text-gray-500 font-mono`,
  селектор `w-24`, ID-инпут `flex-1 min-w-0`, кнопка `shrink-0`.
- **Инварианты 10.10**: REGISTRY **400** / GROUPS **90** / Settings **372** / mapped **88** /
  TAB_RULES **19** / CONFIG_TAB_TITLES **19**; ноль PG-DDL; SQLite **v8**; `bot.py`/`media/`/`.env`
  не тронуты; секретов нет; Headroom в коде отсутствует (п.6 out of scope).
- **Находки 10.10**: `plans/reports/round10.10_scanner_audit.md` (0 blocker/0 high/0 medium;
  3 low: R10.10-1 staged-отчёт скрипта, R10.10-2 `meta.note` вне snapshot, R10.10-3 chart-return
  без destroy; 2 info: R10.10-4 аватары админов, R10.10-5 дубль `adminInitial`).
