# Full Audit Results

> Comprehensive code audit of adminbot (C:\Code\Python\adminbot)
> Started: 2026-09-09
> Scanner: Autonomous code auditor

---

## Audit Summary

| Category | Files Scanned | Issues Found | Critical | High | Medium | Low |
|----------|---------------|--------------|----------|------|--------|-----|
| Total    | 180+          | 47           | 0        | 8    | 22     | 17  |

---

## Findings by Severity

### Critical (Production-blocking)
*None found*

### High (Significant risk)

#### [HIGH-001] bot.py: Global mutable state for services creates race conditions and testing difficulties
**Location**: `bot.py` lines 143-180 (16+ module-level globals)
**Issue**: Module-level globals hold service instances creating race conditions, testing impossibility, hidden dependencies
**Impact**: Flaky tests, potential production issues under load, maintenance burden
**Recommendation**: Use `ApplicationState` dataclass or DI container

#### [HIGH-002] bot.py: `on_shutdown` accesses globals without null checks
**Location**: `bot.py` lines 716-745
**Issue**: Some globals checked but others like `_search_aggregator`, `_web_extractor`, `_checkup_fetcher` accessed without verification
**Impact**: AttributeError on shutdown if SmartModule disabled
**Recommendation**: Add null checks or use centralized service registry

#### [HIGH-003] config/settings.py: Secrets in default values leak to `.env.example`
**Location**: `config/settings.py` - `LLM_API_KEY=""`, `TAVILY_API_KEY=""`, etc.
**Issue**: Default empty strings for secrets; `.env.example` contains all keys as templates
**Impact**: Developer may accidentally commit real secrets; secret rotation difficult
**Recommendation**: Use `None` defaults for secrets; separate secret schema from config

#### [HIGH-004] services/llm_client.py: No request/response logging for debugging LLM issues
**Location**: `services/llm_client.py` `_post` method
**Issue**: Only errors logged; successful requests/responses not logged at DEBUG level
**Impact**: Impossible to debug prompt issues, token usage, model behavior in production
**Recommendation**: Add structured DEBUG logging with request/response metadata (masked secrets)

#### [HIGH-005] services/database.py: SQL injection risk in dynamic queries
**Location**: Multiple methods using f-strings for table/column names
**Issue**: `_SCHEMA_SQL` uses f-strings; `insert_graph_fact` builds CHECK constraint dynamically
**Impact**: If origin values come from user input, potential injection
**Recommendation**: Use allowlists for dynamic SQL parts; validate origin against `_GRAPH_FACT_ORIGINS`

#### [HIGH-006] handlers/summary.py: Observer saves ALL messages including potential PII
**Location**: `handlers/summary.py` `summary_observer` function
**Issue**: No PII filtering; saves forward sources, user names, message content
**Impact**: GDPR/privacy compliance risk; sensitive data in SQLite
**Recommendation**: Add PII detection/filtering; configurable retention per chat

#### [HIGH-007] services/pg_db.py: No connection pool sizing for production load
**Location**: `services/pg_db.py` `PgDatabase` class
**Issue**: Default pool size not configured; no max_connections tuning
**Impact**: Connection exhaustion under load; "too many connections" errors
**Recommendation**: Configure pool size from settings; add pool monitoring

#### [HIGH-008] web/app.py: CORS allows all origins by default
**Location**: `web/app.py` FastAPI middleware
**Issue**: No explicit CORS configuration; defaults may be permissive
**Impact**: CSRF risk for TMA admin panel
**Recommendation**: Explicit CORS origins from config; credentials=false

### Medium (Should fix)

#### [MED-001] bot.py: Hardcoded router registration order fragile
**Location**: `bot.py` lines 632-710
**Issue**: Order critical but only enforced by comments; no tests verify
**Recommendation**: Add test validating router precedence; use priority system

#### [MED-002] bot.py: Duplicate LLMClient instantiation (5+ times)
**Location**: `bot.py` lines 467, 527, 557, 587, 617
**Issue**: DRY violation; inconsistent config possible
**Recommendation**: Extract `create_llm_client()` factory function

#### [MED-003] bot.py: Inconsistent `settings` vs `hot.get()` usage
**Location**: Throughout `bot.py`
**Issue**: Mix of static and dynamic config access confusing
**Recommendation**: Standardize on `hot.get()` for all runtime-configurable values

#### [MED-004] bot.py: No structured error handling for service init failures
**Location**: `bot.py` `on_startup()`
**Issue**: Broad `Exception` catches, only warnings logged
**Recommendation**: Structured error types; init status tracking via `/api/status`

#### [MED-005] config/settings.py: `_env_duration` parsing allows dangerous values
**Location**: `config/settings.py` `_parse_duration` function
**Issue**: No upper bounds; "999d" = 86M seconds accepted
**Recommendation**: Add max duration validation per parameter

#### [MED-006] config/settings.py: Type coercion silent failures
**Location**: `config/settings.py` `_env_int_min`, `_env_float_min`
**Issue**: Invalid values silently fall back to defaults with WARNING only
**Recommendation**: Fail-fast for critical config; structured config validation

#### [MED-007] services/config_cache.py: No cache invalidation TTL
**Location**: `services/config_cache.py` `ConfigCache` class
**Issue**: In-memory cache never expires; stale data until reload
**Recommendation**: Add TTL-based cache refresh; configurable max age

#### [MED-008] services/hot_config.py: No validation of coerced values
**Location**: `services/hot_config.py` `_coerce` function
**Issue**: Failed coercion returns original value silently
**Recommendation**: Raise on coercion failure for critical params; metrics

#### [MED-009] services/database.py: No WAL mode enforcement verification
**Location**: `services/database.py` `initialize()`
**Issue**: WAL mode set but not verified; could be disabled by SQLite config
**Recommendation**: Verify `PRAGMA journal_mode=WAL` after setting

#### [MED-010] services/database.py: FTS5 triggers not maintained
**Location**: `services/database.py` `save_smart_message`
**Issue**: Manual FTS sync; no triggers for UPDATE/DELETE
**Recommendation**: Use FTS5 triggers or explicit sync on all mutations

#### [MED-011] services/llm_client.py: Retry logic doesn't respect `Retry-After` for all 5xx
**Location**: `services/llm_client.py` `_post` method
**Issue**: `Retry-After` only for 429/5xx per code comment but implementation unclear
**Recommendation**: Explicit handling for all retryable status codes

#### [MED-012] handlers/common.py: Mimic victim IDs parsed once at module load
**Location**: `handlers/common.py` `_VICTIM_IDS` global
**Issue**: Changes to `MIMIC_VICTIM_USER_IDS` require restart
**Recommendation**: Parse dynamically in handler or use hot config

#### [MED-013] handlers/search.py: Exact match cache key doesn't include chat context
**Location**: `handlers/search.py` `smartsearch_handler`
**Issue**: Cache key only includes query; different contexts return same result
**Recommendation**: Include chat_id in cache key or disable cache for contextual search

#### [MED-014] handlers/factcheck.py: No rate limiting on external API calls
**Location**: `handlers/factcheck.py` (similar to search)
**Issue**: Tavily/Exa calls not rate-limited per provider
**Recommendation**: Add provider-level rate limiting in `SearchAggregator`

#### [MED-015] services/direct_chat_service.py: Massive function (800+ lines)
**Location**: `services/direct_chat_service.py` `generate_and_send`
**Issue**: Single function handles context building, LLM calls, tools, memory, sending
**Recommendation**: Split into pipeline stages; extract context builders

#### [MED-016] services/summary_memory.py: `rule_importance` magic numbers
**Location**: `services/summary_memory.py` `_IMPORTANCE_BASE` dict
**Issue**: Hardcoded importance weights per origin; not configurable
**Recommendation**: Move to param_catalog; hot-configurable

#### [MED-017] services/param_catalog.py: 383 parameters - no validation of registry completeness
**Location**: `services/param_catalog.py` `REGISTRY`
**Issue**: No test that all Settings fields have ParamSpec; drift likely
**Recommendation**: Add test comparing Settings fields to REGISTRY keys

#### [MED-018] services/permissions.py: Bitmask permissions lack audit trail
**Location**: `services/permissions.py` `Permissions` class
**Issue**: Changes to permissions not logged; no history
**Recommendation**: Log permission changes via `chat_lore_history`

#### [MED-019] services/access.py: `can_edit_param` logic complex, undertested
**Location**: `services/access.py` `can_edit_param` function
**Issue**: Multiple condition branches; edge cases for custom roles
**Recommendation**: Add comprehensive unit tests; simplify logic

#### [MED-020] web/api/config.py: Secret masking incomplete
**Location**: `web/api/config.py` `GET /api/config`
**Issue**: Only masks known secret keys; custom secrets may leak
**Recommendation**: Mask all values for keys containing secret patterns

#### [MED-021] web/app.js: No error boundary for WebSocket/API failures
**Location**: `web/app.js` Vue components
**Issue**: Failed API calls show generic errors; no retry UI
**Recommendation**: Add error boundaries; toast notifications; retry buttons

#### [MED-022] tests/: Low coverage for critical paths
**Location**: `tests/` directory
**Issue**: No integration tests for router chain; no contract tests for API
**Recommendation**: Add pytest-asyncio integration tests; API contract tests

### Low (Nice to have)

#### [LOW-001] bot.py: Inline SQL in channel_post handler
**Location**: `bot.py` lines 678-695
**Recommendation**: Move to `DatabaseService.save_relay_album_map()`

#### [LOW-002] bot.py: Magic numbers in router registration comments
**Location**: `bot.py` lines 632-710
**Recommendation**: Define `ROUTER_ORDER = [...]` constant

#### [LOW-003] config/settings.py: 400+ settings in single class
**Location**: `config/settings.py` `Settings` dataclass
**Recommendation**: Split into nested config objects (LLMConfig, MemoryConfig, etc.)

#### [LOW-004] services/database.py: `row_get` helper hides type errors
**Location**: `services/database.py` `row_get` function
**Issue**: Silently returns default on any access error
**Recommendation**: Use typed rows (dataclasses) or explicit dict access

#### [LOW-005] services/llm_client.py: `_mask_secrets` regex may miss edge cases
**Location**: `services/llm_client.py` `_mask_secrets`
**Issue**: Complex regex; new key formats may bypass
**Recommendation**: Use allowlist of known secret patterns; test extensively

#### [LOW-006] handlers/alan.py: Reply probability hardcoded in logic
**Location**: `handlers/alan.py` reply interval logic
**Issue**: `ALAN_REPLY_INTERVAL` used but probability not configurable
**Recommendation**: Add `ALAN_REPLY_PROBABILITY` setting

#### [LOW-007] handlers/kostik.py: Random reply uses `random.random()` without seed
**Location**: `handlers/kostik.py`
**Issue**: Non-deterministic; hard to test
**Recommendation**: Inject RNG for testing

#### [LOW-008] handlers/slavik.py: GIF counter logic mixed with message handling
**Location**: `handlers/slavik.py` `MessageCounterMiddleware`
**Issue**: Middleware does business logic (GIF trigger)
**Recommendation**: Separate counter persistence from reaction logic

#### [LOW-009] services/memory_backup.py: Backup path not validated
**Location**: `services/memory_backup.py` `MemoryBackupService`
**Issue**: Relative path; may write outside project if CWD changes
**Recommendation**: Resolve absolute path from project root

#### [LOW-010] services/memory_maintenance.py: No progress reporting for long jobs
**Location**: `services/memory_maintenance.py` `MemoryMaintenanceService`
**Issue**: Merge/review jobs can run minutes; no visibility
**Recommendation**: Add progress callbacks; expose via `/api/workers`

#### [LOW-011] services/oversight.py: Dashboard data not cached effectively
**Location**: `services/oversight.py` `build_summary`
**Issue**: 60-120s cache mentioned but implementation unclear
**Recommendation**: Explicit cache with TTL; cache invalidation on config change

#### [LOW-012] web/index.html: No CSP headers
**Location**: `web/index.html`
**Issue**: No Content-Security-Policy; inline scripts allowed
**Recommendation**: Add CSP meta tag; nonce for inline scripts

#### [LOW-013] docker-compose.yml: PostgreSQL no resource limits
**Location**: `docker-compose.yml` postgres service
**Issue**: No CPU/memory limits; can OOM host
**Recommendation**: Add `deploy.resources.limits`

#### [LOW-014] requirements.txt: Unpinned transitive dependencies
**Location**: `requirements.txt`
**Issue**: `aiogram>=3.31.0,<4.0.0` allows breaking patch updates
**Recommendation**: Pin exact versions; use `pip-tools` for lockfile

#### [LOW-015] pytest.ini: Timeout too short for integration tests
**Location**: `pytest.ini` `timeout = 60`
**Issue**: Some DB/LLM tests need >60s
**Recommendation**: Separate unit/integration test configs; longer timeout for integration

#### [LOW-016] .gitignore: `migrate_history/` ignored but 600MB+ files
**Location**: `.gitignore`
**Issue**: Large files in ignored dir still consume disk; no cleanup policy
**Recommendation**: Document cleanup; consider external storage for imports

#### [LOW-017] .env.example: Contains 200+ variables - overwhelming
**Location**: `.env.example`
**Issue**: New developers can't identify required vs optional
**Recommendation**: Split into `.env.required`, `.env.optional`, `.env.secrets`

---

## Detailed Findings by Component

### bot.py (Main Entry Point)
- **Architecture**: 700+ lines, single file orchestration
- **Globals**: 16 service instances as module-level variables
- **Startup**: 400+ line `on_startup()` violating SRP
- **Router Order**: 24 routers in fixed critical order
- **Positive**: Excellent spec-referencing comments; structured logging; secret masking

### config/settings.py (Configuration)
- **Size**: 77KB, 2000+ lines, 400+ settings
- **Parsing**: Custom `_env_*` helpers with validation
- **Issues**: No config schema validation; silent fallbacks; secret defaults
- **Positive**: Duration parsing; tuple parsing; comprehensive comments

### services/database.py (SQLite Layer)
- **Schema**: 8 migration versions; comprehensive tables
- **GraphRAG**: Complex fact storage with origins, importance, vectors
- **Issues**: Dynamic SQL; FTS sync manual; `row_get` hides errors
- **Positive**: Fail-open for infinite_retention; detailed migration logic

### services/pg_db.py (PostgreSQL Layer)
- **DDL**: Idempotent CREATE + ALTER statements
- **Tables**: 15+ tables for config, RBAC, chat profiles, budgets
- **Issues**: No pool sizing; no migration version tracking
- **Positive**: Comprehensive seeds; additive deltas pattern

### services/llm_client.py (LLM Client)
- **Resilience**: Retries, circuit breaker, fallback provider
- **Budget**: `LLM_TOTAL_BUDGET` hard timeout
- **Issues**: No request logging; secret masking regex complexity
- **Positive**: Structured error types; detailed retry logic

### services/direct_chat_service.py (Direct Chat)
- **Complexity**: 1200+ lines; single massive function
- **Features**: Token bucket, CB, tools, memory, RAG, personas
- **Issues**: Monolithic; hard to test; context building inline
- **Positive**: Comprehensive feature set; fail-open patterns

### services/summary_memory.py (Memory Manager)
- **Architecture**: 3-level (L1/L2/L3) + GraphRAG v2
- **Epic 60**: Phases A-D (dedup, merge, decay, quota, touch, int8)
- **Issues**: Magic numbers; complex MMR; vec reactivation logic
- **Positive**: Thorough documentation; spec references; pure functions

### handlers/ (23 routers)
- **Pattern**: Observer-style (UNHANDLED) for SmartModule routers
- **DI**: Global `_service`/`_db` pattern (testing difficult)
- **Filters**: Custom aiogram filters for word/user matching
- **Positive**: Clear separation; consistent error handling

### web/ (TMA Admin Panel)
- **Stack**: FastAPI + Vue 3 (no build) + vanilla JS
- **API**: 15+ endpoints; chat-scoped via header
- **Issues**: No CSP; CORS default; no error boundaries in JS
- **Positive**: Clean separation; spec-driven UI

### filters/ (12 custom filters)
- **Pattern**: aiogram `Filter` subclasses with `__call__`
- **Word Lists**: Centralized in `word_lists.py` (135+ danger words)
- **Issues**: Some filters compile regex at module load
- **Positive**: Reusable; well-documented

---

## Recommendations by Priority

### Immediate (Week 1-2)
1. **Fix bot.py globals**: Introduce `ApplicationState` class
2. **Add null checks in on_shutdown**: Guard all 16 globals
3. **Extract LLMClient factory**: Single creation point
4. **Validate pg_db pool sizing**: Configure from settings
5. **Add router order test**: CI gate for handler precedence

### Short-term (Month 1)
6. **Split bot.py**: `main.py`, `services.py`, `routers.py`, `lifecycle.py`
7. **Config validation**: Fail-fast schema validation at startup
8. **PII filtering in observer**: Detect/redact sensitive data
9. **Cache TTL in ConfigCache**: Auto-refresh stale entries
10. **Structured LLM logging**: DEBUG level request/response logs
11. **DirectChat refactor**: Pipeline stages for context/LLM/tools/memory
12. **Param catalog completeness test**: Settings ↔ REGISTRY sync

### Medium-term (Quarter)
13. **DI Container**: Lightweight dependency injection
14. **Integration Tests**: Router chain, API contracts, DB migrations
15. **Observability**: Metrics for LLM calls, cache hit rates, worker budgets
16. **CSP Headers**: Secure TMA admin panel
17. **Secret Management**: Vault integration; rotation automation

---

## Architecture Observations

### Strengths
1. **Fail-Open Resilience**: Services degrade gracefully (PG down → SQLite defaults)
2. **Hot Config**: Runtime parameter changes without restart (ConfigCache + NOTIFY)
3. **Spec-Driven Development**: Every feature references spec sections (T-XXX, Epic XX)
3. **Comprehensive Memory**: 3-level + GraphRAG + vector search + FTS fallback
4. **BYOK Support**: Per-chat API keys with budget enforcement
5. **Rich Observability**: In-memory log ring, uptime heartbeat, oversight dashboard

### Technical Debt
1. **God Object (bot.py)**: 700 lines, 16 globals, 400-line startup
2. **Global State Pattern**: Module-level `_service` in 20+ handlers
3. **Monolithic Functions**: `generate_and_send` (1200 lines), `on_startup` (400 lines)
4. **Config Sprawl**: 400+ flat settings in single dataclass
5. **Test Gaps**: No integration tests; globals prevent unit testing

### Scaling Risks
1. **SQLite Write Contention**: Single writer; WAL helps but not for high throughput
2. **PG Connection Pool**: Unconfigured; may exhaust under load
3. **LLM Budget**: Global daily limits; no per-chat fairness guarantees
4. **Memory Growth**: VACUUM INTO daily but no compaction of vec tables
5. **WebSocket Scaling**: Single-process uvicorn; no horizontal scaling design

---

## Security Posture

### Good
- ✅ Secrets never logged (R17 compliance throughout)
- ✅ BetterStack token only logged as length
- ✅ Custom log handler with secret masking
- ✅ BYOK keys stored in PG (not in code/.env.example)
- ✅ Fail2ban/UFW/SSH hardening on prod (per docs)

### Needs Attention
- ⚠️ No CSP headers on TMA
- ⚠️ CORS not explicitly configured
- ⚠️ PII in memory (names, forwards, message content)
- ⚠️ No secret rotation automation
- ⚠️ SQL injection surface in dynamic queries
- ⚠️ `.env.example` contains all secret keys as templates

---

## Test Coverage Assessment

| Area | Coverage | Notes |
|------|----------|-------|
| Config parsing | Medium | Unit tests for `_env_*` helpers |
| Database migrations | Low | No automated migration tests |
| Router precedence | None | Critical gap - order not tested |
| LLM client retries | Low | Mock tests only |
| DirectChat pipeline | None | Too monolithic to test |
| GraphRAG logic | Medium | Some pure function tests |
| API endpoints | Low | Manual testing only |
| Worker budgets | None | No integration tests |

---

## Final Assessment

**Overall Code Quality**: **B+** - Strong architecture with clear spec-driven development, excellent resilience patterns, but significant technical debt in monolithic entry point and global state management.

**Production Readiness**: **A-** for current scale (single chat, ~10 users) but **C+** for scaling due to global state, unconfigured PG pool, and test gaps.

**Recommended Investment**: 2-3 sprints to refactor `bot.py`, introduce DI, add integration tests, and harden security headers before any scale-out.

---

*Report generated by Scanner on 2026-09-09*
*180+ files scanned across 12 directories*

---

# Round 10.3 Audit (F-13 tma-chat-selector-fixes, F-14 dm-user-settings, F-15 direct-sandbox-budget-investigation)

> Аудит 2026-09-10. HEAD d30b203 + uncommitted working tree 10.3 (27 files, +1323/−171).
> Проверено: спеки F-13/F-14/F-15 (plans/features/*), диффы всех изменённых файлов, полные
> тексты services/access.py, roles.py, chat_params.py, llm_client.py, summary_memory.py
> (горячие зоны), web/api/routes.py, web/api/access.py, gates.py, chat_lore.py, web/app.js,
> web/index.html. pytest: **4831 passed** (66s; базa 4760 → +71). `node --check web/app.js` — clean.
> Бэклог: все пункты (включая новые файлы 10.3) просканированы → отмечены [x].

## Статус известных находок (из прошлых отчётов)

| ID | Статус в 10.3 | Комментарий |
|---|---|---|
| HIGH-004 | 🔶 частично | F-15 добавил диагностику budget-пути (details-снапшот в NoApiKeyForChat + WARNING `[direct] no key…` c `details=`) и маскированный raw-фрагмент в WARNING memorize. Полный LLM request/response DEBUG-лог — вне 10.3 (заявлено F-15 §6) → **остаётся открытой** |
| MED-021 | 🔶 частично | F-13 AC-3: configError-баннер в loadConfig (403/503/сеть) + «⟳ Повторить»/«✕», очистка при успехе/setActiveChat. Остальные API-сбои (гейты/оверсайт/лор) — без error-boundary → **частично закрыта** |
| MED-019 | 🔶 частично | F-14: can_edit_param/can_access_chat/eligible_type расширены is_dm-ветками; новые юнит-тесты test_dm_access.py + API-контракты (403 чужого ЛС, keys→False, fail-open). «Упрощение сложной логики» не выполнено (веток стало больше) → **частично** |
| MED-017 | ❌ открыта | REGISTRY 383/71, Settings 359 — без дифов (эталон test_param_catalog зелёный), но теста-сверки Settings↔REGISTRY не добавлено |
| MED-022 | 🔶 частично | +71 тест (маркеры F-13 AC-1/2/3/5, test_webapp_dm_ui, test_dm_access, fallback-парсер/ретрай, S1/S2/S3). Интеграционных тестов роутеров/миграций по-прежнему нет |
| MED-015 | ❌ открыта (by design) | direct_chat_service монолит не рефакторится; F-15 — только аддитивные правки (заявлено в границах) |

## Новые находки раунда 10.3

### [R10.3-1] severity: minor — DM-скоуп: контролы models.* (per_chat=False) редактируемы во фронте, но сервер всегда 422
**Файл**: `web/app.js` ~1334-1338 (`canEditConfig`, DM-ветка) + `web/index.html` ~599/705 (кнопки Save, `:disabled="!canEditConfig(item.key)"`).
**Суть**: ветка `if (this.isDmCtx() && String(key).split('.')[0] !== 'keys') return true;` включает редактирование ВСЕХ не-keys ключей, включая `models.*` (29 ключей, per_chat=False — проверено по REGISTRY). В DM-скоупе GET /api/config отдаёт models как «глобальную справку», но тумблеры/инпуты/«Сохранить» активны → каждый save даёт 422 «ключ нельзя переносить на уровень чата» (гейт routes.py POST). Спека F-14 §6.2/§3.2 явно требует **read-only** models в DM. Сервер защищён (не security-дыра), но UX-шум и несоответствие спеке; для group-local_admin этой проблемы нет (их canEditConfig упирается в sections/params) — регрессия только DM. Рекомендация: в DM-ветке учитывать `item.per_chat` (передавать item, а не key) либо скрывать per_chat=False на DM.

### [R10.3-2] severity: minor — configError-баннер не очищается при 401-тосте и дублирует 403-тост api()
**Файл**: `web/app.js` 1381-1398 (loadConfig.catch), `web/api`-обёртка api() (тост «Доступ запрещён»).
**Суть**: (а) при 403 баннер + toast api() одновременно (по спеке задумано, но шумно); (б) если после 403-баннера случится 401 (протухшая initData), баннер остаётся на экране (authLocked блокирует загрузку, баннер не очищен) — некритично, т.к. дальше идёт authError-экран. (в) `configError` не сбрасывается при переключении вкладок в том же чате — «✕» обязателен. Все три пункта — UX-мелочи; логика статус-кодов верная (403/503/сеть разделены, 401-тост не изменён).

### [R10.3-3] severity: info — несогласованная cap-семантика «лимит = 0» между parse_fact_list и _fallback_parse_facts
**Файл**: `services/summary_memory.py` ~416 (parse_fact_list) vs ~504-505 (_fallback_parse_facts).
**Суть**: parse_fact_list: `if len(facts) >= (hot.get(...) or 0): break` — при лимите 0 обрезает ПОСЛЕ ПЕРВОГО факта; fallback-парсер: `if limit and …` — 0 трактует как «без лимита». Дефолт каталога ненулевой (проверка: limits.graph_extract_max_triplets default), поэтому в проде не стреляет; код-стиль/консистентность. Заодно: поведение «0 = 1 факт» в parse_fact_list — pre-existing (не регрессия 10.3).

### [R10.3-4] severity: info — DM-владелец не может запретить allow_global для своего ЛС
**Файл**: контракты F-14 (web/api/routes.py POST /api/config keys.*→422; keys/own — только BYOK).
**Суть**: у ЛС-юзеров единственный способ не расходовать глобальный бюджет/ключ — поставить свой BYOK-ключ. Выставить `keys.allow_global=false` для своего ЛС нельзя (keys.* скрыты/422; oversight-global_key — только global admin). По спеке так задумано (§3.2), но это пробел приватности для юзера, который хочет «не пользоваться чужим ключом» без своего. DM key-status (GET /api/config/keys/status, 200 для владельца) показывает allow_global и бюджеты — видимость есть, управления нет.

### [R10.3-5] severity: info — fail-open/fail-closed асимметрия DM-гейта саммари (зафиксировать как поведение)
**Файл**: `services/chat_params.py` `chat_summary_enabled` / `get_chat_param_defaulted`.
**Суть**: DM-путь при недоступности PG/кэша (или пустом профиле) → False (fail-closed; саммари ЛС OFF), групповой путь → hot.get (fail-open). Осознанно (DM default OFF — единственное исключение из наследования), НО: при PG-down ЛС с явным override=True временно теряет инъекцию конспекта (S1/S2), пока кэш не восстановится. Плюс: ChatParamsCache негативно кэширует отсутствующий DM-профиль ({}, updated_at=None) до 120с — сразу после первого POST-создания профиля чтения консистентны (NOTIFY-инвалидация), но S1/S2 до профиля видят False — приемлемо.

### [R10.3-6] severity: info — F-15 fallback-ретрай memorize не лимитирован по числу параллельных фоновых вызовов
**Файл**: `services/summary_memory.py` ~1607-1626 (_memorize_facts_inner).
**Суть**: при «мусорном» ответе экстрактора каждый fire-and-forget memorize делает +1 LLM-вызов (жёсткий промпт). Всплеск «мусорных» ответов (промпт-дрейф/плохой фоллбэк-провайдер) = удвоение фоновых токенов memorize-хуков по всем чатам (бюджет LLM общий). Ретрай bounded = 1 на вызов, но не capped по частоте/чатам. Не блокер (фоновый, R16 не задет), но стоит держать в уме при бюджетах.

## Проверенные области — вердикты (логические дыры НЕ найдены)

1. **DM-матрица прав (roles.py/access.py)**: DM-ветка до chat_admins-лукапа, role_chat=None, is_local_admin=False (F-11-меню не открывается), DM_OWNER_PRESET без chat_lore/group-секций; rank=max(ранг,3). Чужой ЛС (в т.ч. global admin) → can_access_chat False → 403; gates PUT DM → 403; chat_lore DM → 404 (все эндпоинты через _require_chat); keys.* в POST /api/config → 422; BYOK-гейты DM-владельцу — открыты с ensure_scope_profile. Дыр обхода legacy-эндпоинтов не обнаружено (все X-Chat-Id-пути проверены: routes.py 364/380+/563+/590+, gates.py, chat_lore.py, oversight.py — oversight global-admin-only).
2. **Изоляция DM (П.1-П.6)**: chat_lore_store list_* + oversight PROFILE_COLS_SQL + access CHATS_FOR_USER_SQL — фильтр chat_id<0 добавлен везде, где списки. LoreWorker/ностальгия не видят DM. Ноль DDL — соблюдено.
3. **S1/S2/S3 саммари**: chat_summary_enabled — единственный резолвер; группа — байт-в-байт hot.get; ЛС — override→cast→fallback=False; scheduler _tick фильтрует chat_id>0 (None-guard есть). bot.py:613-643 не дифнут. L3/GraphRAG-память не гейтится (по спеке). Ретрай F-15 не попадает в крон _extract_and_save_graph (там parse_triplets, отдельный путь) и не в синхронные пути (все memorize-вызовы — fire_and_forget; summary_generator:153 — fire_and_forget).
4. **BYOK-фоллбэк (llm_client._resolve_api_key_and_source)**: повторное чтение своего ключа после budget_exceeded — ровно 1 доп. SELECT (нет циклов); usage-счётчик (_record_global_usage) вызывается только при source='global' → двойного расхода бюджета нет; details-снапшот секретов не содержит (used/limit/day/allow_global/resolve_path); WARNING direct_chat_service:546 логирует repr(details) — R17 ок. Исключение NoApiKeyForChat пробрасывается до _post (LLM не вызывается).
5. **Фронт F-13/F-14**: единый select (1 шт., picker-методы удалены, chatPickerOpen=0), `✕</button>` — 1 (сайдбар), closeApp=0, toggleFullscreen жив; v-for/v-if-развязка через `<template>` корректна (Vue3), выражение-фильтр сохранено на дочернем div; configError-логика (очистка в успехе/setActiveChat); isDmCtx/canViewTab/canEditConfig/resetChatOverride — серверные гейты дублируют фронт (403/422 защищают); setActiveChat не вызывает двойных loadConfig; бейдж «ЛС #id» и empty-states актуальны; z-index 45 (sidebar) < 50/60 — каскад соблюдён.
6. **int/str chat_id**: is_dm_scope делает int() с None-guard; _chat_id_or_none → int; scheduler int(chat_id) c None-guard; select String()/parseInt — консистентно. Отрицательные id групп не пересекаются с DM (>0). Гонок/двойных вызовов в изменённых путях не выявлено.

## Итог 10.3
- **Блокеров/major: 0.** Security-периметр (DM-изоляция, R17, бюджет) держится серверными гейтами.
- **Minor: 2** (R10.3-1, R10.3-2), **Info: 4** (R10.3-3…R10.3-6) — в основном UX/консистентность, код-правки не требуются для мержа.
- pytest **4831 passed**; node --check clean; git diff --check чист (проверено в выводе diff: только LF/CRLF-warnings).

*Round 10.3 report generated by Scanner on 2026-09-10*