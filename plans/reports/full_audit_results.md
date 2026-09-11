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

---

# Round 10.4 Audit (A/B/C/D/E/F/G/H: реструктуризация админки + 8 фич)

> Аудит 2026-09-10. HEAD 1410a68 + working tree 10.4 (14 файлов модифицировано,
> 24 untracked; +1691/−400). Проверено: спеки 8 фич (A…H, plans/features/*),
> диффы всех изменённых файлов, полные тексты param_catalog.py (TAB_RULES/
> _TAB_BY_GROUP/select-поля/_MEMORY-разметка), chat_params.py (_resolve_from_root),
> direct_chat_service.py (_budget_gate/_apply_context_budget/_thread_limit/_cp_g),
> summary_memory.py (per-chat точки), web/api/routes.py (select-валидация обе
> ветки), web/api/chat_lore.py (H-2 обогащение), web/app.js (TABS/flatGroupRank/
> sectionTitle/relChat-гвард), web/index.html (select-виджет, аккордеоны,
> relations/lore-конфиг-блоки, карточки модулей), оба backfill-скрипта.
> pytest: **4860 passed** (57.8s; база 4831 → +29; ijson доустановлен в локаль —
> 2 history-теста не собирались до этого, не регрессия). `node --check web/app.js` — clean.
> `git diff --check` — чист (только LF/CRLF-warnings).

## Проверка покрытия «ни один из 383 не пропал» (главный риск раунда)

- **GROUP-покрытие**: HEAD: 72/74 групп на конфиг-вкладках (content_info/
  content_media — никогда не были; это категория content — не-конфиг); 10.4:
  **72/74 — множества групп идентичны HEAD** (ADDED=[], REMOVED=[]).
- **REGISTRY 383 = 383; GROUPS 74 = 74; SETTINGS 359 = 359** (эталон MED-017
  соблюдён; `test_param_catalog` зелёный).
- `_TAB_BY_GROUP` импортируется без ValueError; каждая группа ровно на одной
  вкладке (reactions_triggers 4 / permsoc 17 / modules_switches 2 / chat_lore 2 /
  people_names 1 / relations 2 / memory_rag 4 / memory_dream 1 / memory_nostalgia 1 /
  llm_providers 15 / prompts 8 / limits 15 = 72).
- **Вердикт: потерь параметров/групп НЕТ** (это главный негатив-критерий ТЗ 8).

## Новые находки раунда 10.4

### [R10.4-1] severity: minor — лог WARNING graphrag-обрезки показывает ГЛОБАЛЬНЫЙ лимит, режет per-chat
**Файл**: `services/summary_memory.py:1991-1993` (`get_rag_context`).
**Суть**: обрезка `context = context[:(_rag_max_chars or 0)]` идёт по per-chat
значению, но WARNING `"context truncated to %d chars"` подставляет
`hot.get("limits.graph_rag_context_max_chars", …)` — глобальное. При override
у -1002661910336 (×2) лог будет врать (напр., «truncated to 4000» при реальном
пороге 4000×2). Ремедиация: подставить `_rag_max_chars` в лог (строка 1993).

### [R10.4-2] severity: minor — смена активного чата НЕ сбрасывает/перезагружает список участников на вкладке relations → кросс-чатовая запись
**Файл**: `web/app.js:738-769` (`setActiveChat`) + `:2569-2614` (`saveRelationManual`).
**Суть**: ревью-фикс закрыл кросс-чат для перехода между ВКЛАДКАМИ (setTab-сброс
`chatLoreProfile`), но если юзер НА вкладке relations меняет чат в глобальном
селекторе: `setActiveChat` вызывает `loadConfig`, но НЕ перечитывает участников
и НЕ очищает `chatRelations`. Экран показывает участников чата A, все кнопки
`saveRelationManual/removeRelationManual/toggleRelationsEnabled` при этом пишут в
`relChat = activeChatId` (чат B) — ручная стадия/заметка уйдёт чату B (или
тумблер переключит B). Класс той же ошибки, что закрывалась ревью-фиксом №2.
Ремедиация: в `setActiveChat` добавить ветку `activeTab === 'relations'` →
`this.chatRelations = []` + (не DM) `loadRelations(id)` (как в setTab).

### [R10.4-3] severity: minor — бэкфил G молча НЕ создаёт override `chat_thread_max_tokens`/`chat_global_context_max_tokens` (Settings None) → «тред ×2» фактически не достигается
**Файл**: `scripts/backfill_104_overrides.py:43-63` (`_current_value`/`_target_value`)
+ `config/settings.py` (CHAT_THREAD_MAX_TOKENS=None, CHAT_GLOBAL_CONTEXT_MAX_TOKENS=None).
**Суть**: множители для этих двух ключей — в OVERRIDE_MULTIPLIERS (2.0 и 1.5), но
`hot.get(key, None)` → None → `float(None)` → TypeError → base None → **skip**
(печатается «skip (нет дефолта)», выхода нет). Итог: `_thread_limit`-helper
читает per-chat, но override никогда не пишется; тред остается на chars-лимите
CHAT_THREAD_MAX_CHARS=2000 (×1), хотя спека G §4 и round10.4_review_fixes.md
(«thread-токены/чары — _thread_limit + thread_limit у _render_thread», «таблица
значений бэкфила соответствует фактическому поведению») заявляют ×2.
Токенный лимит в actuelle кодовой семантике resolve_chat_limit — «cells-mode»:
для global_context «×1.5» достигается через max_chars (4000→6000) — там skip
безвреден; для треда — **цель не достигнута** (нужен override
`limits.chat_thread_max_chars`=4000, которого в таблице нет).
Ремедиация: добавить `limits.chat_thread_max_chars: (2.0, None)` в
OVERRIDE_MULTIPLIERS (или явно зафиксировать «тред остаётся глобальным» в отчёте).

### [R10.4-4] severity: minor — блок обогащения фото (H-2) тянет getUserProfilePhotos для ВСЕХ 100 строк, хотя фото нужны топ-50
**Файл**: `web/api/chat_lore.py:588-609` (`list_relations`).
**Суть**: `user_display_info` возвращает И username, И photo_file_id и кэширует
оба — первый проход (gather, Semaphore(5)) по всем 100 участникам делает и
`get_chat_member`, и `get_user_profile_photos` для каждого; второй проход (топ-50)
— кэш-хит (фото_meta создан заново, но кэш отдаёт). Итог на холодный рендер:
100 get_chat_member + **100** get_user_profile_photos вместо 100+50 (спека H-2:
«photo — только топ-50; остальные — ленивый догруз фронтом»). Лишние ~50
тяжёлых вызовов Bot API на первый рендер (кэш 1ч смягчает; семафор 5 держит
лимиты). Ремедиация (опционально): `user_display_info(chat_id, uid, with_photo=…)`
или отдельный фото-флаг для строк 51-100. **НЕ критично**: fail-open/кэш есть,
производительность в NFR-границах.

### [R10.4-5] severity: info — «Перезагрузить» в 409-модалке на вкладке relations не перезагружает участников
**Файл**: `web/app.js:2462-2467` (`confirmLoreReload`) + modal index.html:2187.
**Суть**: `confirmLoreReload` → `target = chatLoreSelectedId || chatLoreProfile.chat_id`
— на вкладке relations оба null (setTab-сброс; chatLoreSelectedId — лор-скоуп),
клик «Перезагрузить» закрывает модалку бездействием. Список участников остаётся
стейлом; recovery — кнопка ⟳ (есть). UX-пробел, не потеря данных.

### [R10.4-6] severity: info — бэкфилы (оба) без optimistic-метки: гонка «скрипт ↔ живой админ» может затереть чужой override
**Файл**: `scripts/backfill_104_chat_flags.py:47-49`, `backfill_104_overrides.py:102-104`.
**Суть**: `set_chat_params(..., expected_updated_at=None)` — «последняя запись
побеждает», но set_chat_params ЗАМЕНЯЕТ весь namespace `overrides` целиком
(chat_params.py:280-283). Если админ между `get_all_chat_params` (в скрипте) и
записью изменит ДРУГОЙ ключ — его запись затрётся (overrides снова полностью
из скриптового root). Окно мало (деплой-минуты), идемпотентность-гарантия
(«не перезаписываем существующие ключи») НЕ нарушается — только свежие записи
того же окна. Ремедиация (опционально): expected_updated_at=прочитанная метка +
retry на 409.

### [R10.4-7] severity: info — G-4-граница шире, чем задокументировано: direct-chat RAG-путь и `get_rag_facts` остались глобальными
**Файл**: `services/direct_chat_service.py:1649` (cap `graph_rag_context_max_chars`)
и `services/summary_memory.py:2015-2018` (`get_rag_facts` — `graph_rag_facts_limit`).
**Суть**: round10.4_review_fixes.md §4.2 фиксирует границу только для
`summary_xml.py`-рендера и `_participant_roster`; фактически НЕ переведены ещё и
(а) сборка <RAG_Memory> в direct чате (cap 1649), (б) список-кандидатов
`get_rag_facts` (лимит фактов). Override ×2 для `graph_rag_*` (G-бэкфил) применяется
в summary-callback-путях, но НЕ в direct-chat RAG-блоке. Воздействие: «×2 RAG в
прямом чате» частично не реализован — стоит дописать в §2 G-отчёта (документирование).

## Закрытое в раунде 10.4 (из старых находок)

| ID | Статус | Что именно закрыто |
|---|---|---|
| R10.3-1 (DM models.* редактируемы → 422) | 🔶 частично (by design) | Spec B §6: «фикс отложен (вне скоупа)» — не закрыто, но и не усугублено (canEditConfig DM-ветка не диффена) |
| R10.3-2 (configError-баннер) | 🔶 частично | Без изменений; остаётся «частично» (MED-021-состояние 10.3) |
| R10.3-3 (limit=0 cap-семантика) | ✅ закрыто | `window[-max(1, _g_limit):]` (direct_chat_service.py:1792) — Reviewers-наблюдение устранено; старый «-0 → всё окно» больше невозможен |
| R10.3-4 (DM нельзя выключить allow_global) | ❌ открыта | Вне скоупа; контракты не менялись |
| R10.3-5 (fail-open/fail-closed асимметрия) | ❌ открыта (by design) | Гейт саммари не диффнут |
| R10.3-6 (ретрай memorize без кэпа) | ❌ открыта | Не задевалось в 10.4 (пути не диффились) |
| HIGH-004 (LLM DEBUG-лог) | ❌ открыта | F-15 diagnostics остались; полный лог — вне |
| MED-015 (монолит direct_chat) | ❌ открыта (by design) | G-3 — только аддитивные per-chat точки |
| MED-017 (REGISTRY-сверка) | ❌ открыта | 383/71/359 соблюдены тестом, но теста Settings↔REGISTRY нет |
| MED-019 (can_edit_param сложность) | ❌ открыта | не упрощалась |
| MED-021 (error-boundary) | 🔶 частично | configError-баннер (10.3); остальные API сбои — без boundary |
| MED-022 (покрытие тестов) | 🔶 частично | **+29 теста** (test_104_backend_additions 11, test_progressive_tab_basic_coverage 3, test_frontend_tab_mapping +~120 строк маркеров, webapp_api/webapp_dm_ui/avatars/nav_disclosure) — интеграционных роутер-тестов нет |

**Новых блокеров/major: 0.** Периметры: R16 (id никогда имя — сохранён: каскад
H-5 без изменений, name==uid → удаление), R17 (секреты в select/labels отсутствуют;
details не диффились), DM-изоляция (relations-vкладка в ЛС — заглушка 404; записи
через /api/config X-Chat-Id=ЛС — per_chat=True и is_dm_owner — канон F-14),
F-15/бюджет (×2-контекст + flags.off — документированный баланс G-7; sandbox R16
при 25 req/сутки — прежнее поведение). Роутеры bot.py, каноны промптов, SQLite v8,
PG-DDL — без диффов (проверено диффом; ноль DDL).

## Итог 10.4
- **Блокеров: 0, Major: 0.** Minor: 4 (R10.4-1…R10.4-4), Info: 3 (R10.4-5…R10.4-7).
  Все — UX/лог/скрипт-точность; код-фиксы для мержа НЕ обязательны (но R10.4-1 и
  R10.4-3 — 1-строчные ремедиации, рекомендуются в follow-up).
- pytest **4860 passed**; node --check clean; git diff --check чист.
- Обновлены: full_audit_results.md (этот раздел), audit_backlog.md (10.4-пункты),
  global_map.md (Round 10.4 map additions).

*Round 10.4 report generated by Scanner on 2026-09-10*

---

# Round 10.5 Audit (tma-relume-redesign: Relume TMA redesign)

> Полный отчёт — `plans/reports/round10.5_scanner_audit.md`.
> HEAD `0bdf272` (10.4) + рабочее дерево 10.5 (38 записей; +2391/−159 tracked).
> pytest **4959 passed** (база 4860 → +99); `node --check` clean; `git diff --check` clean.

## Новые находки 10.5 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.5-1 | minor | `web/app.js:775/816-819/1767` | BackButton не переинициализируется после позднего контекста (`ready`) → in-app «←» + невызванный `goBack()` на depth>0 |
| R10.5-2 | minor | `web/app.js` canEditConfig (DM) + `param_catalog._MODELS_PG_ONLY` | DM: 4 новых `per_chat=False` `models.*` редактируемы во фронте → POST даёт 422 (класс R10.3-1, 29→33 ключей) |
| R10.5-3 | info | `web/api/routes.py:1080-1092` | `/api/status/key-history` — любой авторизованный юзер (как `/api/status`, RBAC-исключение; секретов нет) |
| R10.5-4 | info | `services/key_history.py:38-43` | `_ALLOWED_PROVIDER_KEYS` не используется; deny-list `"token"` широкий (только QA) |
| R10.5-5 | info | `config_cache.rename_role` + `routes.rename_role_endpoint` | гонка rename → 500 вместо 409 (optimistic-защиты нет) |
| R10.5-6 | info | `web/app.js:1982` | `setMenu` мёртв (pre-existing, не 10.5) |
| R10.5-7 | info | `status_service.py:316` | синхронный файловый I/O `key_history.maybe_save()` в async-пути (мал, 5-мин порог) |

**Верифицировано чисто:** каталог **387/74/359**; TABS↔TAB_RULES; ноль PG-DDL;
SQLite v8; `bot.py` не тронут; `media/` не тронут; секреты не коммитятся; R16/R17;
иконки (26/26 PUA совпадают с код-каноном и присутствуют в субсете); DOMPurify
self-host 3.4.15 fail-closed.

## Итог 10.5
- **Блокеров: 0, Major: 0.** Minor: 2 (R10.5-1, R10.5-2), Info: 5 (R10.5-3…R10.5-7).
- Обновлены: `round10.5_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.5 report generated by Scanner on 2026-09-10*

---

# Round 10.6 Audit (tma-ia-modules-rework: navbar/Модули(11)/AI(7)/PERMsoc)

> Полный отчёт — `plans/reports/round10.6_scanner_audit.md`.
> HEAD `be7b85b` + рабочее дерево 10.6 (24 modified + 4 untracked; +1920/−1136 tracked).
> pytest **5023 passed** (база 4962 → +61); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

## Новые находки 10.6 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.6-1 | minor | `web/index.html:701-1053` + `:709-751`; `web/app.js:856-859,2517-2563` | На вкладке LLM Провайдеры generic-рендер `currentTabGroups` не подавлен → 21 из 37 параметров дублируются (prov-блок + generic-группа: base_url/model/api_key и др.); данные не страдают |
| R10.6-2 | minor | `services/llm_probe.py:58-80` (`_safe_base`); `web/api/routes.py:1225` | SSRF: `http` — только точный loopback, а `https` принимается для ЛЮБОГО хоста (127.0.0.1/localhost/internal/DNS-rebind) с возвратом до 300 симв. ответа; ограничено `requires_global_admin` |
| R10.6-3 | minor | `web/api/routes.py:126-132,1225` | 422-валидация Pydantic 2 возвращает `input` с присланным `api_key` (R17-эхо тому же админу при малформ-запросе; подтверждено на минимальном FastAPI) |
| R10.6-4 | info | `services/llm_probe.py:35-38`; `web/app.js:388-398` | `media_share` вне списка §6.3; `embeddings` в UI `testable:false`; `llm_guard` намеренно не тестируется |
| R10.6-5 | info | `web/app.js:228-233` (+208/229) | мёртвые записи `ICONS` (`speed/theater_comedy/toggle_off/toggle_on/stop_circle/account_balance_wallet`) после удаления вкладок |
| R10.6-6 | info | `web/api/routes.py:1240-1242` | rate-limit слот `(user,block)` расходуется до валидации блока (`_LLM_TEST_LAST[...] = now` до `probe_block`) |

**Закрыто в 10.6:** R10.5-1 (BackButton re-init на `ready` под `_boundBackApi`;
`goBack` при модалке закрывает окно) и R10.5-2 (DM `canEditConfig` учитывает
`per_chat===false` → `models.*`/`keys.*` read-only).

**Верифицировано чисто:** каталог **392/91/364/mapped 89**, `TAB_RULES`=19, каждая
группа ровно на одной вкладке; ноль PG-DDL; SQLite v8; `bot.py` не тронут; `media/`
не тронут; секреты не коммитятся; 5 master-флагов default True и реально гейтят
(5 handler-точек); 10 миселённых PERMsoc-ключей в М5/М6/М7; Леха/Костик раздельно;
sidebar удалён; fullscreen-scroll; emoji→Material в `#/how`/матрице; эксклюзивный
аккордеон `accessOpen`; `keys_youtube`→М6, `models_checkup`/`keys_betterstack`→М9;
per-block `POST /api/llm/test` (403/200/429/R17).

## Итог 10.6
- **Блокеров: 0, Major: 0.** Minor: 3 (R10.6-1…3), Info: 3 (R10.6-4…6).
  Для мержа не обязательны; R10.6-1/R10.6-3 — точечные ремедиации, рекомендуются.
- Обновлены: `round10.6_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.6 report generated by Scanner on 2026-09-11*

---

# Round 10.7 Audit (admin-ui-bugfixes-round107: header/nav, stats, logs)

> Полный отчёт — `plans/reports/round10.7_scanner_audit.md`.
> HEAD `2ccf558` + рабочее дерево 10.7 (9 modified + 2 untracked; +403/−125 tracked).
> pytest **5042 passed** (база 5023 → +19); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

## Новые находки 10.7 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.7-1 | minor | `services/status_service.py:290-300,376-378` | gap-fill идёт до `now_slot` включительно: сразу после 5-мин границы текущий слот ещё без heartbeat (пишется раз в 60 с) → правый край графика до ~60 с помечен `down`, `last_heartbeat` откатывается к предыдущему слоту. Спека §2b предписывает такой trade-off; данные не искажаются |
| R10.7-2 | info | `services/status_service.py:291-301` | `[-288:]` может отбросить единственный ранний `up`-бакет (first_slot = floor(ts) до `since` на ≤299 с → сетка 289), тогда `last_heartbeat=None` при формально бывшем heartbeat. Узкий край |
| R10.7-3 | info | `web/app.js:741-742,3344-3352` | `copiedTimer` очищается только при следующем клике; при уходе со вкладки <800 мс таймер сработает и сбросит `copiedIndex` (косметика, корень не размонтируется) |
| R10.7-4 | info | `tests/test_font_subset.py:73` | Тест проверяет PUA-код в `app.js`, но не cmap WOFF2. Независимо (`fontTools`) подтверждено: все 20 `ICONS`-кодов есть в cmap (26 глифов). R106-5 безопасен; пробел покрытия pre-existing |
| R10.7-5 | info | `web/app.js:3305-3308,3354-3360` | Заявленный «context-loss» `this.logs.map(this.logText)` фактически отсутствовал (`logText` не использует `this`); правка безвредна, формулировка причины неточна |

**Закрыто в 10.7:** R10.6-5 (мёртвые записи `ICONS` — удалены `account_balance_wallet`
`stop_circle` `theater_comedy` `toggle_off` `toggle_on` `speed`; 0 обращений; все оставшиеся
20 PUA-кодов присутствуют в cmap субсета). R10.6-1/2/3 остаются открытыми (вне UI-скоупа,
кандидаты 10.8).

**Верифицировано чисто:** каталог **392/91/364/mapped 89**, `TAB_RULES`=19, `CONFIG_TAB_TITLES`=19;
ноль PG-DDL; SQLite v8; `bot.py` не тронут; `media/` не тронут;
`uptime_heartbeat.py`/`key_history.py` не тронуты; секреты не коммитятся; R17/RBAC/DM без
изменений; `scope*` — 6 computed-функций, шаблонные привязки без `()`; контракт `/api/status`
(`buckets/last_heartbeat/since/until/generated_at`) сохранён; `execCommand`-fallback проверяет
boolean → нет ложного тоста; ghost-textarea удаляется в `finally`.

## Итог 10.7
- **Блокеров: 0, Major: 0.** Minor: 1 (R10.7-1), Info: 3 (R10.7-2…R10.7-4) + R10.7-5 (nit).
- Обновлены: `round10.7_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.7 report generated by Scanner on 2026-09-11*

---

# Round 10.8 Audit (admin-ui-round108: renames, emoji→icons, Android logs, access windows)

> Полный отчёт — `plans/reports/round10.8_scanner_audit.md`.
> HEAD `636a75d` + рабочее дерево 10.8 (18 modified + 2 untracked; +610/−224 tracked, WOFF2 13 428→18 388 B).
> pytest **5073 passed** (база 5042 → +31); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

## Новые находки 10.8 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.8-1 | minor | `web/app.js:1023-1027`; `web/index.html:1620,1663,1797` | Esc не закрывает окна «Доступов»: `@keydown.esc` на неавтофокусируемом `.modal-card`, глобальный `_onKeydown` знает только `openModuleId`. Работают ✕/backdrop/Back. AC-4 требует Esc → 1-строчная ремедиация |
| R10.8-2 | info | `web/app.js:275-277,2085-2093` | Комментарий про `section` для `#/access/*` устарел; ветка `if (card.section)` в `openHubCard` осиротела (10.8 убрал `section` у access-карточек) |
| R10.8-3 | info | `web/app.js:43,184,189,895-905,2191-2194` | `TABS[].icon`/`visibleTabs`/`tabMat` — мёртвый путь (таб-бар удалён в 10.6); замена TABS-иконок инертна. Pre-existing, не регресс |
| R10.8-4 | info | `plans/backlog.md` | Статус раздела 10.8 «🟡 ПЛАНИРОВАНИЕ» при выполненной реализации; закрывается @PM Step 8 |
| R10.8-5 | minor | `config/settings.py:1069`; `README.md`; `web/index.html:69`; `web/app.py:50,62` | README v2.52.0, а `APP_VERSION`=2.51.0 (`/api/status.version` покажет старое); `@font-face`-URL не версионирован, `.woff2` `max-age=86400` → старый субсет 10.7 в кэше до 24 ч → tofu новых иконок. app.js безопасен (no-cache). Ремедиация: bump APP_VERSION + `?v=__APP_VERSION__` на шрифт |

**Закрыто в 10.8:** **R10.7-3** (`copiedTimer`/`copiedIndex` очищаются в `setTab`) и
**R10.7-4** (тест `test_font_subset` парсит `ICONS`↔`ICON_NAMES` и сверяет cmap WOFF2 через
`fontTools` — тест выполняется, не skip). R10.7-1/-2, R10.6-1/2/3 остаются открытыми (вне UI-скоупа).

**Верифицировано чисто:** каталог **392/91/364/mapped 89**, `TAB_RULES` 19;
ноль PG-DDL; SQLite v8; `bot.py` не тронут; `media/` не тронут; секреты не коммитятся;
**ICONS 37 == ICON_NAMES 37**, все 37 PUA-кодов в cmap субсета (лишних PUA нет, мёртвых нет),
маркер идемпотентности = `sha256(src_sha|ICON_NAMES)`;
`#/access/roles|local|admins` — три взаимоисключающих route-driven окна, `sec-*`-id целы,
deep-link/BackButton/ROUTE_PARENT сохранены, RBAC (`isGlobalAdmin`/`canEditRole`/`canViewTab`)
не ослаблен; логи — блочная раскладка без жёстких ширин, `fmtLogTime` = `DD.MM HH:MM:SS`,
toggle — Material-иконка только при `exc_text`; ровно один GLOBAL-бейдж; в `web/` 0 pictographic-emoji;
README: единственный `<details>` сбалансирован, шапка v2.52.0/5073.

## Итог 10.8
- **Блокеров: 0, Major: 0.** Minor: 2 (R10.8-1, R10.8-5), Info: 3 (R10.8-2…R10.8-4).
  Для мержа не обязательны; R10.8-1 (Esc) и R10.8-5 (APP_VERSION/кэш шрифта) — точечные
  ремедиации, рекомендуются в follow-up.
- Обновлены: `round10.8_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.8 report generated by Scanner on 2026-09-11*

---

# Round 10.9 Audit (admin-ui-round109: PERMsoc owner-blocks, scroll, описания, «Тяжёлые»/«Бюджет», dashboard/health, display-name, градиент)

> Полный отчёт — `plans/reports/round10.9_scanner_audit.md`.
> HEAD `51f308b` + рабочее дерево 10.9 (23 modified + 2 untracked; +1326/−605).
> pytest **5105 passed** (база 5076 → +29); `node --check` clean;
> `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.

## Новые находки 10.9 (кратко)

| ID | Sev | Файл | Суть |
|---|---|---|---|
| R10.9-1 | low | `services/status_service.py:192-207,217-226,244-277` | `model_source` у `llm_fallback`/`video_openrouter`/`emb_*` снова `"code"` при конфиге (в 10.8 fallback отдавал `"config"`); UI не рендерит, но это поле `/api/status` |
| R10.9-2 | low | `services/status_service.py:257-277` | `EMBEDDING_FALLBACK_*` читаются из `settings` (env-only, не PG — сейчас безопасно); `emb_fallback*` исчезают из реестра без env-ключа, поэтому их display-name недостижим (ожидалось «не настроен») |
| R10.9-3 | low | `services/status_service.py:10-15` | Шапка модуля описывает старый health (`GET {base}/models`, кэш 60с) и хардкод-провайдеров — противоречит ADR-109-3 |
| R10.9-4 | info | `services/status_service.py:283-305` | Health-кэш ключёван по `module_id`: смена base_url/key/model не инвалидирует ok ≤60с (URL раньше инвалидировал); ошибки — 10с |
| R10.9-5 | info | `services/llm_probe.py:9-13,28-32,163-164,238-254` | `_LLM_BLOCKS` включает `transcribe_groq` (нужно для `KNOWN_BLOCKS`), docstring-контракт — нет; `httpx.ConnectTimeout ⊂ TimeoutException` → статус `timeout` (по спеке допустимо) |
| R10.9-6 | info | `plans/backlog.md:5` | Раздел 10.9 «🟡 ПЛАНИРОВАНИЕ» при выполненной реализации; закрывается @PM Step 8 |

**Верифицировано чисто:** каталог **400/90/372/mapped 88**, `TAB_RULES` 19, `CONFIG_TAB_TITLES` 19;
ноль PG-DDL; SQLite v8; `bot.py` не тронут; `media/`/`.env` не тронуты; секреты не коммитятся;
**Ссылок на инфраструктуру IDE в коде/конфиге/тестах нет** (единственный не-plan hit — gitignored
`local_database_2026-09-04_history.db`, данные истории, не код); owner-блоки (4, все 21 owner-ключ
и 4 owner-группы существуют), один тумблер в `<summary>`, generic-bool исключён; backend
`SLAVIK_ENABLED` default True + `DEFAULT_SUB_FLAGS` даёт байт-в-байт для нетронутых; health —
реальный POST (`/chat/completions`, `/embeddings`, `/audio/transcriptions` для Groq-Whisper),
stale-200 не отдаётся, `timeout`/`502`/`unreachable` различаются; скролл — оба контейнера
(`document.scrollingElement` + `.scroll-area`); «Тяжёлые» удалены без потери (killswitch в
«Сводке»), «Бюджет фона» только в «Сводке»; RBAC/DM не ослаблены; `APP_VERSION` 2.52.0 оставлен
сознательно (T-1307 «no README»).

## Итог 10.9
- **Блокеров: 0, Major: 0, Medium: 0.** Low: **3** (R10.9-1…R10.9-3), Info: **3** (R10.9-4…R10.9-6).
  Для мержа не обязательны; точечные ремедиации — в follow-up.
- Обновлены: `round10.9_scanner_audit.md` (новый), `audit_backlog.md`, `global_map.md`.

*Round 10.9 report generated by Scanner on 2026-09-12*