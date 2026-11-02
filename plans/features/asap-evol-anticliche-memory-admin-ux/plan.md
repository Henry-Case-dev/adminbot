# План исполнения FINAL v8 — AntiCliche, память, админ-UI

Источник (дословный, авторитетный): `plans/owner_inputs/2026-11-02-anticliche-memory-admin-ux-spec.md`,
§1–§17, извлечён из `plans/current_task.md` 2902–4025.
Задача: `asap-evol-anticliche-memory-admin-ux`. Вход: `OI-2026-11-02-ANTICLICHE-MEMORY-ADMIN-UX`.
Карта: `requirements-map.json` (521 инвентарная + 148 ручных строк; 573 обязательных
строки под 511 `req_id`; 96 контекстных). Граф: `slice-graph.json` (17 пакетов).

ТЗ — реализация, не аудит: отчёт, «нашли вероятную причину» и список предложений
результатом не считаются.

---

## 1. Классификация существующего кода против нового контракта

Статусы — по таксономии §1.2 ТЗ; проверено по текущему дереву ветки `evol/impl`
(база `19b5ee94`), не по планам прошлых волн.

### 1.1 AntiCliche

| Область | Статус | Факт в дереве | Что требует новый контракт |
|---|---|---|---|
| `services/anticliche_worker.py` — один источник, недельный интервал | **CONFLICTS_WITH_NEW_CONTRACT** | `SOURCE_ID_DEFAULT = "wikipedia"` (:43), `REFRESH_DAYS = 7` (:51), `fetch_source` (:337), `IntervalTrigger(days=REFRESH_DAYS, …)` (:405), `_refresh_impl` (:500) | §3.1 требует реестр из ≥3 независимых русских источников + local/manual + bibliography-only; §3.3 — per-source независимые исполнения, unchanged без LLM, per-source retry policy |
| `services/anticliche_cache.py` — PG кэш, монотонный `version` | **PARTIAL** | `ANTICLICHE_MAX_PATTERNS_DEFAULT = 200` / `HARD_CEILING = 1000` (:30–33), `SELECT patterns, source, source_url, version, fetched_at` (:60), `get_rules` (:125), `fetch_cache` (:145), `write_patterns` (:181) | LKG-поведение есть, но нет `rule_set_version`/`compiler_version`/`checksum`/`parent_version`/`publisher` (§2.1 `PublishedSnapshot`); `version=0` при сбое выглядит как «нет правил» (§1 инв. 8) |
| `services/negative_constraints.py::verbalize_validated` — retry при стиле | **CONFLICTS_WITH_NEW_CONTRACT** | функция на :651; на :871 `retry_system = CLICHE_RETRY_SYSTEM_PROMPT`, stats `retry_error` (:717) | §1 инв. 1 и §9.2 тест 43/46: cliche-only ход = ровно один generate_call, `CLICHE_RETRY_SYSTEM_PROMPT` недостижим; независимые numeric/form/metatext guard'ы (:837–866) остаются |
| Динамические правила идут в детектор, а не в промпт | **CONFLICTS_WITH_NEW_CONTRACT** | `DynamicClicheRule` (:354), `find_forbidden_cliches(..., dynamic_rules=…)` (:606–:609), `build_dynamic_rule` (:556); в `services/prompt_composer.py` нет ни одного упоминания anticliche/cliche | §2/§6.3: утверждённый snapshot обязан давать **PromptHintView** в Writer; селектор детерминированный, без LLM; блок вставляется в существующий слот Composer (`LAYER_STYLE_POLICY_HINT`, `prompt_composer.py`:59, трассировка слоя :1948–1978) |
| `services/prompt_style_blocks.py` — стилевые блоки и retry-промпты | **PARTIAL (переиспользуемо)** | `ANTI_BOT_BLOCK` (:47), `ASYMMETRY_BLOCK` (:79), `CLICHE_RETRY_SYSTEM_PROMPT` (:133), `render_style_policy_hint` (:837) | блоки и hint-рендерер годятся как слот и как источник дедупликации; сам retry-промпт должен стать недостижимым для AntiCliche |
| HTTP API AntiCliche | **PARTIAL** | `web/api/anticliche.py`: `GET /anticliche` (:72), `POST /anticliche/refresh` (:98), `PUT /anticliche` (:120); подключение в `web/app.py`:228–229 | §8 требует 8 read-операций (overview/sources/source/run/rules/preview/traces/events) и 7 мутаций с `expected_version`, operation id и conflict-ответом |
| Legacy-блок в «Библиотеке промптов» | **CONFLICTS_WITH_NEW_CONTRACT** | `web/index.html`:3968 `<details … data-block="anticliche-monitor">`, :3971 «Анти-клише: динамический список», :3979–3981 текст «Фразы, которые детектор Вербализатора бракует и просит перегенерировать»; загрузка через `web/app.js:20704 loadCliche`, fail-open `clicheAvailable` (:3353) | §5.1: блок удаляется вместе с fetch и ошибкой загрузки; остаётся одна ссылка «Настройки антиклише → Речь и характер» |
| Карточка AntiCliche в «Речь и характер» | **MISSING** | вкладка `activeTab === 'speech'` начинается на `web/index.html`:9328; AntiCliche-разметки внутри нет | §5.1: одна карточка с одним toggle, строкой состояния, версией и ссылкой «Открыть антиклише» |
| Карточка extractor-модели в «Фоновые задачи» | **MISSING** | `PROVIDER_BLOCKS` объявлен в `web/app.js`:856; сетка `prov-grid` (:3324, :2712); карточки AntiCliche среди них нет | §5.1: карточка «LLM для антиклише (извлечение и анализ)» через тот же компонент подключения; внутри AntiCliche только read-only «Модель: основная (наследуется)» |
| Six-tab admin page | **MISSING** | нет ни вкладок, ни route; есть только свёрнутый legacy-блок | §5.2–5.9: Обзор/Источники/Анализ/Правила/Промпт Writer/Журнал на реальных данных |
| Event ledger для AntiCliche | **MISSING** | `_event()`/`_emit()` в `anticliche_worker.py`:81/:111 пишут лог-строки, а не структурные run-события | §7.1: 13 семантик событий с `run_id`/`check_id`/`analysis_id`/`snapshot_version` |
| Snapshot publish (Hint+Observation views, rollback) | **MISSING** | `write_patterns` только увеличивает `version`; атомарной пары view нет | §4.2 Stage F, §6.3, §9.2 тест 52 |
| Форматные и стилевые guard'ы (`plain_no_tables`, metatext, numeric) | **DONE_AND_VERIFIED** | отдельные блоки и отдельные retry-промпты: `FORMAT_PLAIN_BLOCK` (:364), `METATEXT_RETRY_SYSTEM_PROMPT` (:164), `NUMERIC_CLAIM_RETRY_SYSTEM_PROMPT` (:150) | назначение не меняется (§1 инв. 2), требуется лишь отделить от стиля и покрыть тестами 44/45 |

### 1.2 Память и самореференция

| Область | Статус | Факт в дереве | Требование |
|---|---|---|---|
| `_memory_lookup_resolve` — имя без Telegram ID даёт `resolved` | **CONFLICTS_WITH_NEW_CONTRACT** | `services/tool_router.py`:3447 — `return {… "resolution": "resolved", …}` при `user_id = None`; ветка `ambiguous` есть только при >1 кандидате (:3431) | §14.3/§14.5: разделить `verified_id` / `name_only_unverified` / `ambiguous` / `unresolved` |
| `_memory_lookup_general` — выборка по имени | **CONFLICTS_WITH_NEW_CONTRACT** | `tool_router.py`:3612; `get_rag_facts(ctx.chat_id, name)` (:3621), `search_long_term(ctx.chat_id, keywords(name))` (:3635), `get_rag_context(ctx.chat_id, name)` (:3650) | §14.4: запрос и отбор по теме/интенту/reply/purpose, а не по одному имени |
| `_query_chat_memory` — `str(fact)` в модельно-видимые строки | **CONFLICTS_WITH_NEW_CONTRACT** | `tool_router.py`:1658–1659 `indirect_lines.extend(str(fact).strip() …)` | §14.3/§14.12 п.7: структурированный разбор, без Python repr и служебных полей как прозы |
| `_dig_into_lore` / `_get_user_context` / stats-ветка | **PARTIAL** | `_dig_into_lore` :1966, `_get_user_context` :3266, `_query_chat_memory_stats` :1887, reason-коды `author_ambiguous`/`author_unresolved` (:1729–1730) | §14.3: общий контракт релевантности/identity/provenance; вопрос «кто такой» не запускает массовый подсчёт |
| `mca_retrieval_context` — exact/lexical/vector/reply_graph/episodes + identity prior | **PARTIAL (переиспользуемо)** | `apply_identity_prior` (:368), `retrieve` (:541), `RetrievalRequest.subject_entity_ids` (:331), `subject_entity_id` (:358) | §14.3/§14.4: признаки существуют, но в вызывающих маршрутах не используются как контракт отбора |
| `summary_memory` — RAG/граф/rerank | **PARTIAL** | `get_rag_facts` (:4695), `rerank_rag_facts` (:4778), `_search_graph_facts` (:4990), `build_rag_context` (:1802) | §14.4 B: смысловая релевантность не подменяется source-only рейтингом; без нового LLM-вызова и нового индекса |
| `tool_loop`/`tool_result` — structured ToolResult + out-of-band telemetry | **PARTIAL** | `services/tool_result.py`, `services/tool_loop.py` существуют как канал | §14.12 п.7: отделить сырой payload от подготовленного контекста, проверить оба канала |
| Drill-down «Память/Истории/Аналитика» | **PARTIAL** | `services/mca_trace.py` существует | §14.8: цепочка query → candidates → selected/rejected с причинами → context → ответ |
| Инициативное вспоминание и owner voice | **DONE_AND_VERIFIED (сохранить)** | действующие инструкции Composer/Writer и профиль | §14.2/§14.7: не отключать, не превращать в отчёт по БД; тесты 44/48 §9.2 и §14.10 |
| Хардкод имени/темы/чата | **NOT_APPLICABLE (запрещено)** | — | §14.12 п.2, §16 п.4: механизм общий, никаких `if name == …` |

### 1.3 Админ-UI и журналы

| Область | Статус | Факт в дереве | Требование |
|---|---|---|---|
| Первичная загрузка Mini App | **PARTIAL** | `.boot-splash` `web/index.html`:101–112, снятие `body.app-ready` `web/static/app.css`:7302; `loadConfig` `web/app.js`:21010, `_markAppReady` в `finally` :21087, ошибки 401/403/503/сеть в баннер :21060–21080, `_scopeGuard` против устаревшего ответа :21018 | §15.1: явные `initializing/loading/ready/empty/degraded/error/retry`, skeleton исчезает всегда, прогрессивный показ оболочки, Android safe-area/клавиатура |
| Журнал: ring-buffer вместо полной истории | **CONFLICTS_WITH_NEW_CONTRACT** | `services/log_ring.py`:125 `deque(maxlen=…)` (env `LOG_RING_MAX_ENTRIES`, дефолт 1000), `get_entries` (:160), `level_counts` (:185), `get_errors_total` (:200); `services/status_service.py`:1193 `"errors_total": get_log_ring().get_errors_total()`; `web/api/routes.py`:1978 `/status/logs`, :2002 `get_entries`, :2007 `counts` | §15.2: durable sink, полный охват эпохи запуска, cursor-пагинация, единое определение ERROR между карточкой и журналом; maxlen-правка исправлением не считается |
| Селектор чата (scope popover) | **PARTIAL** | `toggleScope` `web/app.js`:19759, `positionScopePanel` :19781 (горизонтальная и вертикальная коррекция), `scope-panel` `web/static/app.css`:843; на мобильном выбирается `placement = 'sheet'` (`web/app.js`:2396, :2427), CSS `[data-placement="sheet"]` `app.css`:7377 | §15.3: popover у триггера, без bottom sheet, свой скролл, stacking поверх glass, safe-area |
| Тумблеры модулей GLOBAL/чат | **PARTIAL (почти готово)** | `web/index.html`:5686–5730 (решение §5 v2.1: один переключатель на scope, read-only строка «управляется глобально» :5714–5720, действие «Наследовать глобальное» :5723–5729); `web/app.js`:16591 `moduleScopeState`, :16602 `moduleScopeCanEdit`, :16662 `moduleOverrideResetAvailable`; CSS `.module-toggle.is-readonly` / `.module-global-hint` / `.module-global-btn` `app.css`:4778/4782/4784 | §15.4: довести до полной матрицы (global-only read-only с кнопкой «Настроить глобально», неприменимый модуль с причиной, `source/effective/editable_here` из backend) |
| Мем-инициатива в GLOBAL | **CONFLICTS_WITH_NEW_CONTRACT** | `web/index.html`:1609–1630 — блок мемов живёт в workspace-модуле и при `activeChatId == null` пишет «Выберите чат — мемы включаются и квотируются по чату»; сохранение только чатовое (:1704, :1707–1709) | §15.5: GLOBAL обязан содержать реальные настройки мемов, чат — наследовать/переопределять delta |
| Мем-инициатива backend effective | **PARTIAL (переиспользуемо)** | `services/meme_initiative.py`:308 `_param()` — chat override → `hot_config` → default; `load_settings` :322; `get_chat_param_sourced` `services/chat_params.py`:646 отдаёт `(значение, chat|global|factory)` | §15.5: backend уже умеет наследование и происхождение; нужен GLOBAL-контур сохранения и UI с source/effective |
| API мем-настроек | **PARTIAL** | `web/api/routes.py`:4010 `GET /api/initiative/meme-settings`, :4030 `POST` — только chat-scope | §15.5: глобальная запись + явные `source`/`effective`/`inherited` |
| Модульные/чатовые ключи конфигурации | **DONE_AND_VERIFIED (переиспользуемо)** | `services/chat_params.py` (`get_chat_param` :344, `get_chat_param_sourced` :646) | новый контракт не вводится, только UI-поверхность |

### 1.4 Сводка по статусам

- **CONFLICTS_WITH_NEW_CONTRACT: 9** — worker-single-source, verbalize retry,
  dynamic→detector, legacy prompt-блок, ring-buffer logs, `resolved` без ID,
  `general` по имени, `str(fact)` в model-visible, мемы chat-only.
- **PARTIAL: 13** — cache/LKG, prompt_style_blocks, HTTP API, dig_into_lore/
  get_user_context, retrieval-context, summary_memory, tool packaging, mca_trace,
  boot-состояния, scope selector, module toggles, meme backend, meme API
  (+ `chat_params` как переиспользуемый слой).
- **MISSING: 5 блоков** — карточка в «Речь и характер», карточка extractor-модели,
  шесть вкладок, event ledger AntiCliche, atomic publish snapshot.
- **DONE_AND_VERIFIED: 3** — независимые guard'ы формата/metatext/numeric,
  `chat_params`-слой с источником значения, инициативное вспоминание + owner voice
  (сохранить, не переписывать).
- **NOT_APPLICABLE: 2** — хардкод имени/чата/темы и второй логгер/движок памяти
  (запрещены ТЗ, вводить нечего).

---

## 2. Рабочие пакеты

`S` ≈ до полуволны, `M` ≈ одна волна, `L` ≈ полторы-две волны работы одного
писателя. «Параллельно» — только при отсутствии общих файлов и выполненных
зависимостях.

| ID | Пакет | Размер | Зависит от | Параллельно с | Область |
|---|---|---|---|---|---|
| **AC-P0** | Снять AntiCliche-retry, отделить стиль от guard'ов | S | — | MEM-CONTRACT, UI-BOOT, UI-LOGS-BE | `services/negative_constraints.py`, `services/prompt_style_blocks.py`, `services/direct_chat_service.py`, `services/factcheck_service.py` |
| **AC-DATA** | Источники, статусы, revisions, freshness, LKG, нет ложных нулей | L | AC-P0 *(serial join: один писатель подсистемы)* | MEM-CONTRACT, UI-BOOT, UI-LOGS-BE | `services/anticliche_worker.py`, `services/anticliche_cache.py`, `services/anticliche_sources.py` (new), `services/pg_db.py`, `web/api/anticliche.py` |
| **AC-PIPE** | parse → LLM → gate → staging → атомарная публикация + события | L | AC-DATA | MEM-IDENTITY, UI-SELECTOR | `services/anticliche_worker.py`, `services/anticliche_pipeline.py` (new), `services/mca_events.py`, `services/pg_db.py` |
| **AC-COMPILER** | Детерминированный компилятор в существующий Composer (слой `anticliche_hint`) | L | AC-P0, AC-PIPE | UI-MODULES | `services/anticliche_compile.py` (new), `services/prompt_composer.py`, `services/prompt_style_blocks.py`, `services/style_policy.py`, `services/prompt_registry.py` |
| **AC-API** | Read/mutation контракт шести вкладок | M | AC-DATA, AC-PIPE, AC-COMPILER | UI-MEME, UI-LOGS-FE | `web/api/anticliche.py` |
| **AC-UI** | Карточка «Речь и характер» + 6 вкладок + карточка модели + удаление legacy | L | AC-API, AC-COMPILER, UI-LOGS-FE, UI-MEME | — (барьер) | `web/index.html`, `web/app.js`, `web/static/app.css`, `web/api/speech.py` |
| **AC-LIVE** | Сквозная приёмка 84 сценариев + контролируемый live-smoke | M | AC-UI, AC-PIPE, MEM-TRACE, UI-LOGS-FE, UI-MEME | — | `plans/features/asap-evol-anticliche-memory-admin-ux/evidence/live/` |
| **MEM-CONTRACT** | Цель запроса и отбор кандидатов по смыслу/identity/времени | L | — | AC-P0, UI-BOOT, UI-LOGS-BE | `services/tool_router.py`, `services/mca_retrieval_context.py`, `services/summary_memory.py` |
| **MEM-IDENTITY** | Таксономия идентичности + самореференция бота | M | MEM-CONTRACT | AC-PIPE, UI-SELECTOR | `services/tool_router.py`, `services/summary_aliases.py` |
| **MEM-PACKAGE** | Model-visible сериализация tool-результатов, изоляция метрик | M | AC-COMPILER | AC-API, UI-MODULES | `services/tool_result.py`, `services/tool_loop.py`, `services/prompt_composer.py` |
| **MEM-TRACE** | Телеметрия отбора + drill-down | M | MEM-CONTRACT, MEM-IDENTITY, MEM-PACKAGE, AC-UI | — (после UI) | `services/mca_trace.py`, `web/app.js`, `web/index.html` |
| **UI-BOOT** | Состояния первичной загрузки | S | — | AC-P0, MEM-CONTRACT, UI-LOGS-BE | `web/index.html`, `web/app.js`, `web/static/app.css` |
| **UI-SELECTOR** | Popover выбора чата у триггера | S | UI-BOOT | AC-PIPE, MEM-IDENTITY | `web/app.js`, `web/static/app.css` |
| **UI-MODULES** | Матрица тумблеров GLOBAL/чат | S | UI-SELECTOR | AC-COMPILER, MEM-PACKAGE | `web/index.html`, `web/app.js` |
| **UI-LOGS-BE** | Полный журнал эпохи: sink + cursor API | M | — | AC-P0, MEM-CONTRACT, UI-BOOT | `services/log_ring.py`, `services/status_service.py`, `services/system_logs_fetcher.py`, `web/api/routes.py`, `bot.py` |
| **UI-MEME** | Мем-инициатива GLOBAL + наследование | M | UI-MODULES, UI-LOGS-BE | AC-API, MEM-PACKAGE | `web/index.html`, `web/app.js`, `services/meme_initiative.py`, `web/api/routes.py` |
| **UI-LOGS-FE** | Экран журнала на полных данных | M | UI-LOGS-BE, UI-MEME | AC-API | `web/index.html`, `web/app.js`, `web/static/app.css` |

### 2.1 Что именно сериализуется (общие файлы)

| Общий файл/путь | Пакеты, которые его трогают | Вывод |
|---|---|---|
| `services/anticliche_worker.py` | AC-DATA → AC-PIPE | строго последовательно |
| `services/pg_db.py` (inline DDL, `:290` `anticliche_cache`) | AC-DATA → AC-PIPE | последовательно, одна аддитивная миграция за раз |
| `web/api/anticliche.py` | AC-DATA → AC-API | последовательно |
| `services/prompt_style_blocks.py` | AC-P0 → AC-COMPILER | последовательно |
| `services/prompt_composer.py` | AC-COMPILER → MEM-PACKAGE | последовательно (общий слот Composer) |
| `services/prompt_registry.py` | AC-COMPILER | один писатель, высокая вероятность конфликта с другим EVOL — согласовать очередь |
| `services/mca_events.py` | AC-PIPE → (чтение из AC-API/AC-UI) | запись одним писателем, остальные читают |
| `services/tool_router.py` | MEM-CONTRACT → MEM-IDENTITY | последовательно |
| `web/api/routes.py` | UI-LOGS-BE → UI-MEME | последовательно |
| `web/api/speech.py` | AC-UI | один писатель (секции «Речь и характер») |
| `services/system_logs_fetcher.py` | UI-LOGS-BE | один писатель (источник истории логов) |
| `web/index.html` + `web/app.js` + `web/static/app.css` | UI-BOOT → UI-SELECTOR → UI-MODULES → UI-MEME → UI-LOGS-FE → AC-UI → MEM-TRACE | одна фронтенд-линия, параллельных UI-писателей нет |
| `services/log_ring.py` | UI-LOGS-BE | один писатель, остальные читают API |

---

## 3. Волны и последовательность

Три линии писателей по умолчанию (плюс одна бэкенд-линия журналов, если свободен четвёртый слот).

| Волна | Линия A (AntiCliche) | Линия B (память) | Линия C (админ-UI) | Доп. линия (журналы) |
|---|---|---|---|---|
| 1 | AC-P0 | MEM-CONTRACT | UI-BOOT | UI-LOGS-BE |
| 2 | AC-DATA | MEM-IDENTITY | UI-SELECTOR | — |
| 3 | AC-PIPE | — (MEM-PACKAGE ждёт AC-COMPILER) | UI-MODULES | — |
| 4 | AC-COMPILER | MEM-PACKAGE | UI-MEME | — |
| 5 | AC-API | — | UI-LOGS-FE | — |
| 6 | — | — | AC-UI | — |
| 7 | — | MEM-TRACE | — | — |
| 8 | AC-LIVE (барьер) | — | — | — |

`AC-DATA` идёт после `AC-P0` не из-за файлов (они не пересекаются), а по решению
Architect §8: подсистема AntiCliche (§1–§3) ведётся одним писателем, чтобы
отсечение повтора и модель данных не разъезжались. Это намеренный serial join и
он зафиксирован ребром графа.

Порядок важен по двум причинам: (а) backend-состояние и API обязаны появиться
раньше UI (§16 п.9, §10 п.5); (б) все UI-пакеты пишут одни и те же три файла,
поэтому волны внутри линии C последовательны, а не параллельны.

Очередь COG-MAP S2–S4 идёт раньше: этот план встаёт **после** неё. Пока очередь
не дошла, безопасны только read-only действия (сбор фактов, подготовка fixture).

---

## 4. Первые три пакета — готовы к запуску Builder

### 4.1 `AC-P0` — снять AntiCliche-retry (S)

- **Результат:** любой AntiCliche-сигнал даёт ровно один `generate_call`; ноль
  повторных генераций; `CLICHE_RETRY_SYSTEM_PROMPT` недостижим на cliche-only пути.
- **Файлы:** `services/negative_constraints.py` (ветка `:871`), `services/prompt_style_blocks.py`,
  `services/direct_chat_service.py`, `services/factcheck_service.py`.
- **Шаги:** зафиксировать трассой текущее поведение (`verbalize_validated` :651) →
  убрать cliche-ветку как причину retry, сохранив numeric/form/metatext ветки
  (:837–866) → добавить регрессионные тесты 43–46 §9.2 → убедиться, что стилевой
  отказ не переименован в `format`/`metatext`.
- **Приёмка (требования):** `AC-INV-01`, `AC-INV-02`, `AC-INV-04`, `AC-MET-RETRIES-ZERO`,
  `T-PR-NO-RETRY`, `T-PR-NUMERIC`, `T-PR-FORM`, `T-PR-NO-CLICHE-PROMPT`,
  `T-PR-FAILSAFE`, `AC-BAN-RETRY-PATHS`, `AC-BASELINE-FACTS`.
- **Доказательства:** тесты + трасса одного хода с cliche-hit и одним generate_call.
- **Риск:** R2 (трогаем горячий путь исходящих сообщений) — только через тесты и
  сравнение до/после, без правки текста ответа.

### 4.2 `AC-DATA` — честные источники, LKG, без ложных нулей (L)

- **Результат:** независимые источники с собственными статусами; 403 на одном не
  убивает остальные; `version=0`/`count=0` не показываются, когда действующий набор есть.
- **Файлы:** `services/anticliche_worker.py` (:43, :51, :337, :405, :500),
  `services/anticliche_cache.py` (:30–33, :60, :125, :145, :181),
  новый `services/anticliche_sources.py`, `services/pg_db.py` (:283–303), `web/api/anticliche.py`.
- **Шаги:** реестр источников (`ru-repo-a/b/c`, `local/manual`, `wikipedia`,
  bibliography-only) → adapter contract `fetch/check/parse` с revision/ETag/
  checksum → таксономия статусов §3.2 (10 значений) + отдельная `stale`-пометка →
  `anticliche_source_state` для последней проверки, история — события
  `mca_events` (`component='anticliche'`) → LKG-чтение при любой ошибке → запрет
  storm на 403 и уважение `Retry-After` на 429.
- **Приёмка:** `AC-SRC-*`, `AC-STATUS-*`, `AC-REFRESH-*`, `AC-HEALTH-SOURCE-REACH`,
  `AC-HEALTH-CONTENT`, `AC-INV-08`, `AC-INV-09`, `T-SRC-*`, `AC-FALLBACK-PARTIAL-SOURCE`,
  `AC-FALLBACK-ALL-SOURCES-DOWN`, `AC-OBJ-SOURCE`, `AC-OBJ-SOURCECHECK`.
- **Доказательства:** журнал реальных проверок, тесты 1–20 §9.2, скрин/API-выгрузка
  статусов A/B/C с разными исходами.
- **Риск:** R3 — внешние источники и политика Wikimedia; живая проверка может быть
  `NOT_VERIFIED` по внешнему блокеру, внутренний контракт проверяется fixture.

### 4.3 `MEM-CONTRACT` — память по смыслу, а не по имени (L)

- **Результат:** `person + topic` выбирает тематические сведения; высокий vector
  score не вытесняет верный `SourceRef`; исторический вопрос сохраняет старый эпизод.
- **Файлы:** `services/tool_router.py` (:1564, :3612, :1966, :3266),
  `services/mca_retrieval_context.py` (:368, :541), `services/summary_memory.py` (:4695, :4778, :4990, :1802).
- **Шаги:** протащить цель запроса (тема/интент/субъект/reply/время/чат)
  аддитивно через `ToolContext` → ранжировать внутри цели (предметная связь,
  identity, время, качество свидетельства, роль кандидата) → отбор **до**
  Composer/trimming → не вводить top-N как релевантность.
- **Приёмка:** `MEM-DEC-*`, `MEM-PATH-GENERAL`, `MEM-PATH-CANONICAL-RETRIEVAL`,
  `MEM-PATH-RAG-RERANK`, `MEM-REL-*`, `MEM-GOAL-A`, `MEM-GOAL-B`, `MEM-NO-GLOBAL-CAPS`,
  `MEM-ACC-SEMANTIC`, `MEM-EXTRA-TESTS`.
- **Доказательства:** 8–12 пар `query → candidates → response`, тесты §14.10 (7–16),
  fixture «транслит песни + имя» без хардкода.
- **Риск:** R3 — ядро качества ответов; изменения только через существующий
  retrieval, без нового LLM-проходa и без второго индекса.

---

## 5. Архитектурные контракты: заморожены Architect

Контракты зафиксированы в `plans/features/asap-evol-anticliche-memory-admin-ux/arch/integration-decisions.md`
(коммит `4ce92a75`, база ветки `evol/impl`). PM их не пересматривает и не
расширяет: пакеты ниже реализуют именно эти решения.

| Контракт | Замороженное решение | Точка в документе | Пакеты |
|---|---|---|---|
| Хранилище | 2 новые PG-таблицы `anticliche_source_state` + `anticliche_snapshot`; история/`DocumentProcessing`/`ModelAnalysis`/`AuditEvent` — существующий `mca_events` (`component='anticliche'`, `trace_id=run_id`); `anticliche_cache.patterns` = материализованный снимок активной версии | §1 | AC-DATA, AC-PIPE |
| Атомарная публикация и LKG | одна PG-транзакция «insert snapshot + upsert cache», затем инвалидация memo; сбой не меняет активную версию; «нет правил» отличается от «не загрузилось» статус-кодом | §1 | AC-PIPE, AC-COMPILER |
| Слот компиляции | новый слой `anticliche_hint` между `style_policy_hint` (10) и `channel_output` (11); единственный производитель текста `services/anticliche_compile.py::compile_hint(...)`; runtime и preview вызывают одну функцию | §2 | AC-COMPILER, AC-API |
| Трасса слоя | `LayerTrace(layer='anticliche_hint', block_id='style.anticliche.hints', owner='anticliche', source='snapshot:vN', revision=effective_hash, …)`; skip-причины `anticliche_off/no_snapshot/no_relevant_hints` | §2 | AC-COMPILER |
| Отсечение повтора | в `verbalize_validated` стилевые коды перестают быть условием повтора; ветка `CLICHE_RETRY_SYSTEM_PROMPT` (`:870-871`) недостижима; `STYLE_SIGNALS` → наблюдение, `FORMAT_GUARDS` → отдельная причина `format_retry`; `stats['anti_cliche_retries']` всегда 0 | §3 | AC-P0 |
| Самореференция и идентичность | резолв референта по `mca_bot_outputs` + reply-графу + AliasResolver; `_memory_lookup_resolve` отдаёт `verified_id/name_only_unverified/ambiguous/unresolved`; отождествление только по Telegram id | §4 | MEM-IDENTITY |
| Релевантность и сериализация | запрос из `ctx.query`/темы/reply; `str(fact)` заменён разбором структуры, метаданные остаются в конверте `tool_result`; stats только при явном намерении | §4 | MEM-CONTRACT, MEM-PACKAGE |
| Логи | история — journald через существующий `services/system_logs_fetcher.py` в режиме страниц; `run_epoch_id` из `_SYSTEMD_INVOCATION_ID`; кольцо остаётся live-tail; без journald — `history_source='ring'` и честное «покрытие частичное» | §5 | UI-LOGS-BE, UI-LOGS-FE |
| AntiCliche-история | вкладки «Анализ»/«Журнал» читают `mca_events`, а не `last_status`; точный блок Writer — из манифеста/трассы композера | §5 | AC-API, AC-UI |
| UI-поверхность | карточка в существующих speech-секциях (`web/api/speech.py`, `speechSection='anticliche'`), один `ctl-toggle`, config-путь с optimistic 409; четыре независимые оси здоровья в API | §6 | AC-UI |
| Селектор | `_ctlScopePlacement` больше не превращает панель в нижний лист по умолчанию: приоритет `below`, лист только при нехватке места, пересчёт на scroll/resize/`viewportChanged` | §6 | UI-SELECTOR |
| Модули | для `runtime_gate=='per_chat'` — трёхсостояние с записью в `chat_params.gates`, сброс = удаление ключа; для `global` — видимый read-only + «Настроить глобально» | §6 | UI-MODULES |
| Мемы | `GET/POST /api/initiative/meme-settings` принимают `chat_id=None` (Глобально), запись в hot-ключи `initiative.meme_*`, чатовые — дельта; квоты в GLOBAL — «не измерялось: считается по чату» | §6 | UI-MEME |
| Бюджеты | новые квоты запрещены; существующие константы сохраняются с прежней ролью; «0 релевантных подсказок» — валидный результат | §7 | все |

**ARCH_REUSE_CONFIRMED** (менять нечего, только использовать):

| Пакет | Существующий контракт | Почему применим |
|---|---|---|
| AC-P0 | `negative_constraints.verbalize_validated` + независимые guard'ы | точки отказа и guard'ы уже разделены по функциям |
| UI-BOOT / UI-SELECTOR / UI-MODULES | `boot-splash`+`app-ready`, `scope-panel`+`positionScopePanel`, `moduleScope*`+`.module-toggle.is-readonly` | механизмы и CSS-слой существуют |
| UI-MEME | `chat_params.get_chat_param_sourced` + `meme_initiative._param` | наследование и источник значения уже вычисляются backend'ом |
| MEM-PACKAGE | `tool_result`/`tool_loop` structured envelope | формат обмена есть, нужно отделить payload от прозы |

Открытых архитектурных развилок не осталось: §8 документа прямо фиксирует, что
все развилки инженерные и закрыты. Если Builder встретит реальное противоречие
замороженному решению, вопрос возвращается Architect узкой дельтой — не владельцу.

---

## 6. Обязательные доказательства и живые проверки

- `live_required` в карте: **278** строк (263 `preprod`, 15 `postdeploy`) —
  UI/провайдер/production-поведение.
  Основные: 84 сценария §9.3, живая цепочка `source → run → candidate → rule → prompt`,
  desktop 1536×960 и mobile 390×844, Android WebView, полный журнал эпохи,
  мем-инициатива в GLOBAL и наследование в чате.
- `live_when = postdeploy` — §9.1 демонстрация на живой системе, §10.8
  post-deploy проверка, §15.2 финальная приёмка журнала, §17 итоговые абзацы.
- Внешний блокер (Wikimedia robot policy) не отменяет внутренний контракт:
  Reviewer фиксирует `NOT_LIVE_VERIFIED` и проверяет fixture.
- Обязательные классы fixture (§9.4): «клише действительно мешает» и
  «оставить как есть»; негативный кейс (транслит песни + имя) и положительный
  эталон (FactCheck про Иран) в карте — контекстные строки, не хардкод.

---

## 7. Результат plan-gate

```
stage=plan inventory=521 manual=148 scoped=0 errors=0
```

- все 521 инвентарных строк источника классифицированы, 0 `unassigned`;
- каждый обязательный пакет имеет узел графа, циклов нет, конфликтующих
  write_scope у независимых пакетов нет;
- `strict_evidence: true`, `slice_graph_path: "slice-graph.json"` (как в
  `release-then-migrate` — актуальная конвенция проекта для новых карт).

## 8. Следующее действие

1. ~~Architect фиксирует контракты~~ — **сделано**: `arch/integration-decisions.md`
   (коммит `4ce92a75`) закрывает хранилище, слот компиляции, отсечение повтора,
   память, логи, UI, бюджеты. Открытых развилок нет.
2. Orchestrator ставит волну 1 (`AC-P0`, `MEM-CONTRACT`, `UI-BOOT`, `UI-LOGS-BE`)
   после завершения очереди COG-MAP S2–S4.
3. Во время ожидания допустима read-only подготовка: сбор fixture §9.4,
   инвентаризация существующих событий и тестов, без мутации кандидатов.
