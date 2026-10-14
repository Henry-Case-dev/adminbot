# F7 — Cover live preview + унификация компиляторов (ASAP 7, Wave 3)

- Дата: 09.10.2026. База: master `71b3b69` (Wave 2). Коммитов нет (по регламенту).
- Контракт: architecture.md §2.3 (унификация компиляторов), §2.5 (live editor preview), §5.1 (freeze SECTION-COVER-UI); current_task.md §9 (live preview, §9.4 honest placeholder), §22 п.15 (frontend не собирает prompt); audit-cover.md B3 + REV-2 #1.
- Fan-out: не использовался (leaf-lane, WRITER_BUDGET=0).
- **Candidate fingerprint**: sha256(8 файлов кандидата, конкатенация в порядке ниже) = `51ba1b44512d3cd093166a0061ed4b6b9a3eb0b6a212018f8196d266a68e7758`
  (web/api/summary_test.py, web/api/cover_styles.py, services/summary_generator.py, web/index.html, web/app.js, tests/test_asap7_cover_preview.py, tests/js/asap7_f7_cover_compile_test.js, tools/_asap7_f7_routes_pin.py)

## 1. Изменения (file:line по текущему дереву)

### 1.1 Summary Test = production-сборка (§2.3, B3 regression)
- `web/api/summary_test.py:349-505` — легаци `compose_cover_image_prompt(style, cover_prompt)` (2 компоненты, без SUMMARY_CONTEXT) **заменён** production-сборкой:
  - §11-гард `cover_context_decision(cover_prompt, document.title, paragraphs)` — тот же, что в `summary_generator._publish_rich_document_impl:2869`; recovered → story восстановлен + component reason `anomaly_recovered`; вырожденная статья → честный `COVER_GENERATION_FAILED`/`cover_context_missing` без генерации;
  - резолв лимита GENERATE §2.2 — `resolve_generate_prompt_limit_async()` (known → компиляция под `min(1000, limit_to_chars)`; unknown → assembly-кап без silent trim), байт-паритет с `summary_generator:2910-2933`;
  - `compose_base_cover_prompt(style, cover_prompt, summary_context)` + `shorter_prompt`-callback (тот же компилятор под observed limit) + `attempt_log` → **ровно один shorter-retry** (≤2 платные попытки);
  - **запись CoverPromptManifest**: `build_base_manifest(...)` → `record_base_cover_manifest(db, summary_run_id=test_id, ...)` — тот же durable-носитель/детерминированный ключ (task_jobs kind=cover_base), что production; пишется на ok/failed/exception (`_remember_base_manifest(ok=False)`); `final_prompt ==` фактически отправленному (инвариант §2.6.3, тест);
  - `db` = `generator.memory.db` (как production); fail-open, полный prompt НЕ в лог/ответ (R17 — ответ endpoint'а прежний: cover_status/preview_url).
- `compose_cover_image_prompt` в дереве больше не вызывается рантаймом (остаётся в cover_prompt_assembly как derive-fallback/legacy-паритет для тестов F6 — помечен для Phase 4 Scanner; файл заморожен после F6, не трогал).

### 1.2 POST /api/cover/preview-compile (§9.2–§9.4)
- `web/api/cover_styles.py:1401-1655` — новый endpoint в СУЩЕСТВУЮЩЕМ `cover_styles_router` (включён в web/app.py:225, prefix /api):
  - **global admin, fail-closed** (`requires_global_admin`); COVER_STYLES_ENABLED OFF → 404; compile-only — 0 генераций/платных вызовов (тест);
  - вход: `draft` (точный snapshot редактора, StyleDraftBody `extra=forbid`) / `profile_id` fallback / опциональный `context` (`chat_id` → последний ok-прогон ЭТОГО админа; `test_id` → конкретный свой прогон; чужие/неготовые/истёкшие → честный `no_context`, не ошибка — `_resolve_preview_context` fail-closed по `user.id`);
  - лимит — тот же резолв §2.2, что production Base; breakdown **единой формы** для обоих состояний: `components` (key/source/priority/original_text/original_chars/sent_text/sent_chars/status/reason) + `budget` (resolved_limit/limit_unit/limit_source/limit_known/compile_cap_chars/used_chars/remaining_chars + reserved: story_min 160, context_max 400);
  - с контекстом — production-семантика: §11-гард + `compose_base_cover_prompt` + `build_base_manifest(route="preview_compile")`; ответ: status ok + manifest + components + final_prompt + budget;
  - **без контекста — честный placeholder §9.4**: `status="no_context"`, `final_prompt=null` (никакого fake production промпта), BASE_STYLE = exact current draft (по капам компилятора), STORY_SCENE/SUMMARY_CONTEXT = `preview_context_not_selected`, зарезервированные бюджеты показаны; `cover_context_missing` прогона → отдельная честная причина;
  - R17: полный текст ТОЛЬКО в этом admin-ответе; в логи не пишется.

### 1.3 Live editor UI (SECTION-COVER-UI)
- `web/index.html:721-807` — блок «Фактическая сборка промпта» в редакторе стиля (после «Ограничение промпта», до референсов; гейт `coverStyles.isAdmin`): select test-контекста (чаты accessChats + «без test-контекста») + «Собрать промпт» → exact compiled text (`<pre>` + копировать), honest budget-строка, таблица компонент (отправлено/исходник chars, статус, причина), `<details>` «Тексты компонент (исходник → ушло модели)» (§9.3 «раскрываемо»).
- `web/index.html:874-884` — в «Что отправилось модели» (Test Style): полный **exact compiled prompt** из server-манифеста job'а + копировать (§9.4 «для Test Style — полный exact compiled prompt»).
- `web/app.js:1745-1752` (coverStyles state: compileBusy/compileChatId/compile), `:10598-10665` (методы `coverCompilePreview` — POST на server compiler, ответ as-is; `coverCompileFinalText` — exact только при status ok; `coverCompileReasonText` — «preview context not selected»; `coverCompileBudgetText`). Frontend промпт **не собирает** (§22 п.15): все тексты — из server-ответа. Секционная freeze §5.1 соблюдена (чужих секций нет).

### 1.4 Cleanup REV-2 #1
- `services/summary_generator.py` — дубль `_observed_limit_meta` (:3019, идентичное тело) удалён; единственное определение :2967, все вызовы без изменений. Тест: `def _observed_limit_meta` встречается ровно 1 раз.

### 1.5 ROUTES_SHA256
- Маршрут добавлен в `cover_styles_router` (не routes.py) → **byte-freeze цел, re-pin не требуется**; прецедент «routes.py НЕ менялся → ROUTES_SHA256_F11 без изменений» (MCA-10b/16/18; механизм re-pin при необходимости — `tools/_mca18_repin_routes.py`, f8_baseline reissue — `_mca20_reissue_f8.py`). Артефакт: `tools/_asap7_f7_routes_pin.py` (верифицирует пин + инвентарь f8_baseline Δ=0 + регистрацию маршрута) → `ASAP7-F7-ROUTES-PIN-OK`; плюс тесты `TestRoutesPinUnchanged` в тест-файле F7.

## 2. Тесты
- **Новый** `tests/test_asap7_cover_preview.py` (21 тест, `TEST-LIFECYCLE: CONTRACT owner=asap7/F7`):
  - production-сборка Summary Test (3 компоненты, канонический порядок, ctx доехал) + durable-манифест final==sent (§2.6.3);
  - regression B3: `compose_cover_image_prompt` НЕ вызывается (stub-boom);
  - shorter-retry: ровно 2 платные попытки, манифест `observed_provider_400`/resolved 220/attempts, story сохранён;
  - known-limit: компиляция под 400 chars + честные resolved_limit/limit_source;
  - failed-генерация → манифест всё равно записан (production-паритет);
  - пустая сцена → честный no_cover_prompt, 0 вызовов;
  - **compiler-parity golden**: production Base / Summary Test / preview-compile → идентичный `_manifest_contract` (components+final+hash+limit) на одинаковых входах;
  - preview-compile: 401; 403 не-глобал + отсутствие текстов; no_context honest (final=null, preview_context_not_selected, reserved); ok exact + budget; test_id/chat_id; чужой test_id не читается; running → not_usable; disabled 404; compile-only 0 генераций;
  - cleanup `_observed_limit_meta` (1 определение); routes-пин цел; маршрут в router; routes.py без preview-compile; JS-unit прогон.
- **Новый** `tests/js/asap7_f7_cover_compile_test.js` (подключён pytest-ом, skip без node): реальное поведение — POST на server compiler с draft+context, ответ as-is; exact только ok; honest reason/budget; сеть → message без результата; зона index.html (гейт admin, server-бинды, копировать, верхнеуровневые components, R17-секретов нет).

## 3. Результаты прогонов (targeted, без полного pytest)
- RED до фикса: `test_production_3_component_compile_and_manifest` на старом коде — легаци style-first промпт без ctx (воспроизведён, затем GREEN).
- `tests/test_asap7_cover_preview.py` → **21 passed**.
- Соседи: asap5_cover_prompt_manifest + asap7_cover_readpath + extra_cover_styles_ui + summary_test_api + **asap7_cover_fix (35)** → **121 passed**; extra_cover_style_pipeline/jobs/api → 86 passed.
- `py_compile` (summary_test, cover_styles, summary_generator, app.py) OK; `node --check web/app.js` OK; JS-unit → `ASAP7-F7-COVER-COMPILE-OK`; routes-pin → `ASAP7-F7-ROUTES-PIN-OK`.

## 4. UI/визуальная верификация (реальный рендер)
- Харнесс (scratch `f7_visual_server.py`, порт 8917): реальный web/index.html + реальный app.js + реальный vendor Vue 3.5.42, /api стаб (preview-compile считает манифест НАСТОЯЩИМ `cover_prompt_assembly`).
- Playwright (детерминированный флоу): открытие редактора → блок присутствует (admin); без контекста — message + БЕЗ final-блока + BASE_STYLE 55/55 kept + STORY/CONTEXT «preview context not selected» + резерв в budget; с контекстом — exact text 247 симв + копировать + 3 строки в каноническом порядке + детали текстов; гейт не-админа (обa admin-блока скрыты через реальный Vue-прокси); layout 1280×800 и 390×844 — без горизонтального overflow (blockFits, preOverflow=0); Test Style exact-блок из манифеста job'а + копировать.
- **Visual Neighborhood Sweep**: найденный и исправленный дефект шва — ok-ответ изначально не отдавал верхнеуровневые `components` (таблица пустовала при живом final-тексте); контракт выровнен (единая форма breakdown), тесты дополнены.
- Browser Use (реальный браузер): скриншоты desktop 1280 / mobile 390 (scratch `f7_desktop_1280.png`, `f7_mobile_390.png`) — блок визуально идентичен админке (карточка/бордер/типографика, REFINEMENT, не редизайн), перенос exact-текста корректный.

## 5. Веб-источники
- Не использовались: все решения — репо-локальные факты (архитектура/ТЗ/код). Внешних утверждений нет.

## 6. Остаточный риск
- `preview-compile` резолвит лимит через runtime-capabilities процесса (тот же резолв, что production) — в стендалоне/тестах unknown → честный assembly_cap (by design).
- Test-context берётся из in-memory store тест-контура (TTL 15 мин): истёкший прогон → честный `test_run_not_found`, не ошибка.
- Живой prod-рендер (Telegram WebView) — owner-чек при деплое Wave 3 (прецедент F8 §5).

## 7. Incidental findings
- **related-nonblocking (в моём прогоне, вне лейна)**: `tests/test_round1025_f8_registry.py` — 9 RED на чистом HEAD-дереве БЕЗ моего диффа (проверено stash-прогоном): `param_catalog.py` sha drift + REGISTRY 538 (fixture F3-reissue) → 560 (in-flight F2/F4 каталог, pg_db/analytics/usage_events — их зоны). Reissue fixture — ответственность F2/F4/wave-close тула, не F7. Мой routes-пин (`test_routes_file_unchanged`/`ROUTES_SHA256_F11`) зелёный.
- **unrelated/pre-existing**: `tests/test_extra_cover_style_runtime.py` — 4 RED (`test_no_style_base_cover_rich_regression`, `test_style_success_publishes_styled`, `test_style_failure_uses_base_no_regen`, `test_base_failure_degraded_rich_without_cover`) — идентично на дереве без моего диффа (stash-прогон: те же 4 failed), env-зависимые (aiogram без InputRichMessageMedia, см. F6-отчёт §4).
- Freeze-контроль: git diff моих файлов = только SECTION-COVER-UI (app.js), Cover-UI регион (index.html), cover_styles/summary_test/summary_generator(cleanup). Чужие M-файлы в дереве — in-flight F2/F4, не тронуты.

## REWORK-готовность
- Пункты приёмки из брифа: все закрыты (см. §1–§4); обязательных `LIVE_UNVERIFIED`/`FALLBACK_ACTIVE` в объёме лейна нет (live prod-рендер — owner-чек деплоя, не агентский).

@Orchestrator — на строгую независимую ревью-проверку.
