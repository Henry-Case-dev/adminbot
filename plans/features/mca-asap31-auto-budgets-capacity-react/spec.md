# spec.md — mca-asap31-auto-budgets-capacity-react (ASAP-3.1 Acceptance Addendum)

- **Статус:** Architect narrow reconcile (§113), режим design-reconcile. НЕ новый эпик — ревалидация §1–§146 фактами кода + фиксация контрактов/санкций перед Builder.
- **Источник требований:** `plans/current_task.md` 6067–9922 (§1–§146), прочитано полностью. Tasks: T-4051…T-4090 (`tasks.md` этой папки).
- **Baseline:** прод 2.58.36 (`config/settings.py: APP_VERSION = "2.58.36"`), DDL v19, каталог 483/423/458/105/103/21 (REGISTRY/Settings/categorized/GROUPS/TAB/tabs — числа релиза ASAP-3 из APP_VERSION-комментария).
- **Risk-Level: R3** — reason: правки касаются живой формулы бюджета одновременно в Direct (прод-инцидент 39371→27826 уже пережит) и Summary (прод-инцидент 21001/369), плюс P0-фронтенд фиксы (Analytics, bottom nav). Что подняло бы до R3+ / удержало бы: любая правка, ломающая OFF-парити kill-switch'ей, или Δ DDL ≠ 0 — запрещены этим spec'ом.
- **Browser-Verification: REQUIRED** — reason: фича меняет user-visible web UI (Бюджеты, Аналитика, Advanced, Polygon, bottom nav, human-readable copy). Playwright MCP — детерминированный канал; Browser Use — обязательное визуальное подтверждение (§61, §71, §95, §97, §107). Инвалидация: все acceptance §52/§71/§94/§97/§99/§100/§108 считаются невыполненными без реальных screenshots+geометрии.

---

## 0. Область (scope) и исключения (excluded)

### В scope
1. Model Capacity Resolver: перепись `services/model_capacity.py` (сейчас: карта `MODEL_CONTEXT_WINDOWS` префикс-матчем + env `CHAT_MODEL_CONTEXT_WINDOW` + fallback 16384 `unknown_fallback`, кэш на процесс без инвалидации, `resolve_effective_window` = preemptive min(primary, fallback)) → структурированный резолв `provider + base_url + model` (§3–§8, §37–§39).
2. Auto Budget Resolver поверх capacity: stage-aware формула, safety РОВНО один раз, output reserve per-stage, consumers = Direct composer, Summary L1/L2 packers, fallback recompose, `/api/direct/context-diagnostics`, `/api/analytics/context-budgets`, Status (§9–§12, §131–§133).
3. Model Slots registry + inheritance (§13–§14, §18–§19).
4. Per-chat Context Policy (Dynamic/Unlimited/Advanced Cap), разводка `budgetsUnlimitedKeys()` (7 ключей, `web/app.js:4751`), миграция без потерь (§15–§17, §43, §46, §51).
5. Summary Window = полный охват: lossless chunking, coverage-метрики, семантика без `skipped`, timeout-policy, manual cap per-request (§74–§82, §101–§102, §118–§146).
6. LLM REACT: выбор реакции LLM в том же decision-контуре; SILENT→🗿 единственный hardcode; Force→REPLY (§30–§33, §47–§48).
7. Miniapp: страница «Бюджеты», Developer/Advanced split, Direct Context UI, human-first copy (§18–§23, §83–§89, §135–§138).
8. Analytics «Автобюджеты моделей» + Status compact + fail-open (§24–§29, §45, §103–§105, §134–§135); фикс неоткрытия Аналитики (§70–§73, §99).
9. Polygon: flicker root-cause, живая форма с scene seed, global drift, diagnostics (§56–§69, §100).
10. Bottom nav: одна модель viewport geometry (§90–§94, §96, §98).
11. Observability/метрики (§49–§50), миграционные логи INFO (§79), релиз 2.58.37 + rollback (§53, §108–§111, §113–§117).

### Excluded (вне этого pass)
- Новый универсальный parser метаданных «на все провайдеры мира» (§6: только adapters по реальным подключениям).
- vLLM/llama.cpp/Ollama production-деплой (адаптеры + fixture-тесты; прод сегодня — generic OpenAI-compatible endpoints).
- Adaptive latency policy по корреляции timeout↔payload (§80: «затем, отдельно»).
- Удаление ключа `limits.summary_hybrid_context_chars` из БД (остаётся legacy/emergency, выводится из normal UI; Δ удалений = 0).
- Отдельная фича «rebuild за период» (см. Q12: контракт фиксируется, новой механики не строится).
- Image/STT/embeddings в text-context matrix (§13).

### Traceability
Полная матрица §→задачи→тесты — `tasks.md` (разделы Traceability/DoD mapping, проверены на полноту, расхождения — раздел 12 здесь). Этот spec фиксирует [ARCH]-разрешения: Q1–Q12 (раздел 2), контракты (разделы 3–9), санкции (раздел 10), производство (раздел 11).

---

## 1. Проверенные факты кода (ревалидация §1–§146)

| # | Факт (§) | Файл:строки |
|---|---|---|
| F1 | `budgetsUnlimitedKeys()` = ровно 7 ключей, один тумблер пишет `-1` во все; OFF пишет явные global-значения (§1, §17) | `web/app.js:4751–4826`, `web/index.html:855–865` |
| F2 | Context Mode UI уже пишет СУЩЕСТВУЮЩИЙ `limits.chat_context_budget_tokens` (derive −1/0/>0) (§22 основа) | `web/app.js:4828–4849` |
| F3 | `model_capacity.py`: env override → префикс-карта → 16384 fallback; кэш на процесс, инвалидации нет; `resolve_effective_window` = min(primary, fallback) ПРЕДВАРИТЕЛЬНО (§1, §3–§5 отклонение: fallback-модель сужает окно до запроса, recompose по факту нет) | `services/model_capacity.py:41–176` |
| F4 | Формула Direct D2: `available = safe_budget(window − external − output_reserve)`, safety один раз; policy −1/0/>0 (§10 уже выполнено для Direct) | `services/model_capacity.py:179–238` |
| F5 | Summary L1 бюджет = `limits.summary_hybrid_context_tokens` (default 30000) → `safe_budget(30000/1.15≈26086) − tokens(L1 system prompt) − SUMMARY_L1_OUTPUT_RESERVE_TOKENS(4000) = 21001`; truncation в `pack_l1_input`, лог `L1 truncated input … skipped=… kept=… limit=…` (§75 подтверждён) | `services/summary_hybrid_budget.py:50–128`; `services/summary_l1_clusterizer.py:758–787`; `services/token_counter.py:228–230` |
| F6 | Слот L1: hot `models.summary_l1_base_url/model_name/api_key` → env `SUMMARY_L1_*` → глобальная основная модель; L2 аналогично; слоты уже каталогизированы (§76 основа есть) | `services/summary_l1_clusterizer.py:538–577`; `services/param_catalog.py:877–893` |
| F7 | REACT сегодня — детерминированные наборы по классу `{😂,🤣}/{👍,👌}/{👍,🔥,❤️}/{🤨,🤔}` + stable-hash pick по message_id; kill-switch `flags.chat_decision_reactions_enabled`/env `CHAT_DECISION_REACTIONS_ENABLED`; `CoordinatorDecision` — 0 LLM, «wire-action не вводится — граница A7» (§30: менять здесь) | `services/direct_chat_service.py:619–750,869–911,1015–1048` |
| F8 | SILENT→🗿: строгая конъюнкция + гейты `DIRECT_SILENT_ACK_ENABLED` (env, default ON) и `flags.chat_silent_ack_enabled`; background silence без 🗿 (§32 уже так) | `services/direct_chat_service.py:762–765,1418–1420` |
| F9 | События: закрытый enum 28 типов уже содержит `CONTEXT_CAPACITY/CONTEXT_SELECT/CONTEXT_PRESSURE/CONTEXT_PHYSICAL_OVERFLOW/DIRECT_TRIGGER/DIRECT_SILENT_ACK(FAILED)/REACTION_SENT`; R17-whitelist полей per-event; kill-switch `AGENTIC_EVENTS_ENABLED` (§49 база есть, аддитивно) | `services/agentic_events.py:37–95,115–166` |
| F10 | Аналитика route/tab/template/endpoint'ы существуют: `ROUTE_TO_TAB['#/oversight']`, tab `{id:'oversight', type:'oversight'}`, template `activeTab === 'oversight'`, `/api/oversight/summary` + `/api/analytics/usage/*`, `/api/analytics/execution/latest` (§70 архив подтверждён) | `web/app.js:258,1106–1162`; `web/index.html:2326`; `web/api/oversight.py`; `web/api/analytics.py:193,227,281`; `web/api/routes.py:714` |
| F11 | **Root-cause Q3 (навигация):** `NAV_ITEMS_V2` (IA v2, 7 пунктов) НЕ содержит `oversight`; `navItems/bottomNavItems/«Ещё»/sidebar` строятся из него → в IA v2 «Аналитика» недостижима из навигации, единственная дверь — карточка на Статусе (§70 гипотеза подтверждена статически) | `web/app.js:360–375,1944–2004` |
| F12 | Клик-путь карточки статически цел: `navTo('#/oversight')` → hashchange → `applyRoute` (RBAC: `type==='oversight'` → `isGlobalAdmin`) → `setTab('oversight')` (грузит widgets); render-хелперы null-safe → **рантайм-воспроизведение по чеклисту §71 обязательно**, статических доказательств недостаточно (§95) | `web/app.js:5128–5221,7153–7171,7399–7403`; `web/index.html:3740–3749` |
| F13 | Bottom nav: `--app-usable-height = innerHeight − max(ih−viewportStableHeight, contentSafeAreaInset.bottom, safeAreaInset.bottom)`; `.bottom-nav` в flex-колонке БЕЗ собственного safe-area padding; `visualViewport` — только триггер пересчёта, высота строится из `innerHeight` (§91 подтверждён) | `web/static/telegram-init.js:36–85`; `web/static/app.css:1038–1075,2255` |
| F14 | Polygon: `SEED=20260923` фиксирован; `TOPO_HZ=4` → rebuild каждые ~250 мс → `topoFade=0` → яркость граней `0.55+0.45*topoFade` проваливается каждые 250 мс при fade 320 мс; доп. амплитуда: узловое свечение `(0.55+0.35*pulse)` (~64% swing) и halo `(0.22+0.12*pulse)` (~55%); `getDiagnostics()` не содержит seed/topologyRebuilds/center (§58, §62, §69 подтверждены) | `web/static/polygon-background.js:32–48,344,441,521,540,590–595,754–768` |
| F15 | Labels: `limits.summary_hybrid_context_tokens` = «Hybrid: потолок контекста (слов)»; `…_chars` = «Hybrid: потолок текста (символов)»; env `CHAT_CONTEXT_BUDGET_TOKENS` = «…бюджет, слов (кусочков текста)»; `CHAT_GLOBAL_KEY_BUDGET_TOKENS` = «Лимит слов общего ключа…»; `SUMMARY_MAX_CONTEXT_TOKENS` = «Legacy: потолок контекста пересказа, слов»; группа «Прямой чат: бюджеты слов» (§77, §89 подтверждены: tokens названы «словами») | `services/param_catalog.py:255,897–905,1346–1360,1434,1578–1594,1377–1378` |
| F16 | Прод-подключения LLM: generic OpenAI-compatible (nano-gpt.com, api.deepseek.com — по инциденту §74/§102); универсальной гарантии окна у `/v1/models` нет → registry первичен для прода | `current_task.md §74`; `config/settings.py` (LLM_BASE_URL-слой) |
| F17 | Migration custom-preservation существует (`config_migrations`, sentinel-логика «кастом владельца — НЕ трогаем»), логируется WARNING (§78–§79) | `services/config_migrations.py:42–57` |
| F18 | F8 frozen-hash пины каталога: прецедент переиздания атомарно при Δ≠0 (CRLF/LF eol-нормализация) | `tests/test_round1025_f8_registry.py`; `tasks.md` шапка |

---

## 2. Ответы на вопросы §114 + производные (Q1–Q12)

### Q1. Polygon flicker (→ T-4080)
**Да, подтверждается.** Основной источник — именно `TOPO_HZ=4` + `TOPO_FADE_MS=320` (F14): topology rebuild каждые ~250 мс сбрасывает `topoFade` в 0 до завершения 320-мс перехода; яркость ВСЕХ граней (`fade = 0.55 + 0.45*topoFade`) ритмично проваливается 4 раза/сек. Это не «скорость пульса» — это структурный fade-reset. **Вторичные слои с заметной амплитудой:** (а) свечение узлов `globalAlpha = (0.55+0.35*pulse)*baseAlpha` — относительный размах ~64%, воспринимается как «лампочки» даже при медленном pulse; (б) halo мелких узлов `(0.22+0.12*pulse)` — ~55%. `GLOW_SHIMMER_SPEED` влияет только на радиус — вторичен. **Фикс первопричины:** topology стабильна; rebuild только по displacement threshold / раз в десятки секунд; смена — crossfade old/new несколько секунд, без гашения всей mesh; амплитуду пульса уменьшить именно по размаху (ориентир: базовая альфа ≥0.80, амплитуда ≤0.10), проверка §61 визуально 60–90 с. Запреты §115 в силе (PULSE_SPEED/=2 и TOPO_HZ 4→3 — не фикс).

### Q2. Random seed + детерминизм тестов (→ T-4081)
Схема: (1) при `start()` один раз `sceneSeed = crypto.getRandomValues(new Uint32Array(1))[0]`; (2) детерминированный PRNG (mulberry32 или эквивалент) строит ВСЮ композицию из seed: center X/Y, scale (compact/medium/large §66), aspect, лёгкий rotation/skew, раскладка/размеры кластеров, плотность, число вторичных; (3) seed живёт весь lifetime страницы, `Math.random()` в кадре запрещён; (4) тест-оверрайд: `?bgseed=<uint32>` в URL и/или `window.__PolygonBackground.start({seed})` — production random и deterministic tests не конфликтуют; (5) global scene transform — отдельный слой: медленный drift центра по smooth path + малые колебания scale (+ едва заметный tilt), периоды десятки секунд/минуты; local node drift поверх; (6) reduced-motion: один статичный кадр из того же seed, без pulse/drift; (7) `getDiagnostics()` + `sceneSeed/sceneScale/sceneCenterX/Y/topologyRebuilds/lastTopologyRebuildAge/glowPhase` (§69) — Playwright доказывает смену seed между сессиями и отсутствие rebuild 4 Hz.

### Q3. Почему не открывается Аналитика (→ T-4082)
**Подтверждённая статически причина (навигационная, IA):** `NAV_ITEMS_V2` не содержит `oversight` (F11) — при `IA_V2_ENABLED=ON` (prod) раздел «Аналитика» не имеет ни sidebar-пункта, ни карточки в хабах, ни «Ещё»; единственная дверь — карточка на Статусе. Route/tab/template/endpoints/RBAC (`isGlobalAdmin`) клик-путь — целы (F10, F12), рендер-хелперы null-safe: **глобального бага рендера/routing в коде не видно**. Следствие: (1) структурный фикс — добавить `oversight` в `NAV_ITEMS_V2` (desktop sidebar + mobile «Ещё» строятся из него автоматически; один route `#/oversight`, вторая страница не создаётся; RBAC остаётся global-admin — текущий product contract подтверждён); (2) поскольку владелец сообщил реальный клик-фейл, а статический анализ пути цел — **T-4082 обязан воспроизвести 12-шаговым чеклистом §71 на реальном Browser Use** и задокументировать фактическую точку отказа (если воспроизведётся: кандидат — состояние `this.me`/RBAC в момент клика либо console-исключение конкретного блока); (3) fail-open §73: каждый блок (summary/tokens/budgets/execution) рендерит свою русскоязычную ошибку независимо; `try/catch вокруг всего render` запрещён (§115).

### Q4. Арифметика `limit=21001` (→ T-4055/T-4068/T-4069)
Точно (F5): `30000` (default `HYBRID_CONTEXT_TOKEN_DEFAULT`) → `safe_budget` делит на `models.token_safety_multiplier` (~1.15): `int(30000/1.15) = 26086` → минус токены L1 system prompt (`prompts.summary_l1_clusterizer_system_prompt`, в прод-ране ≈1085) → минус `SUMMARY_L1_OUTPUT_RESERVE_TOKENS = 4000` → `26086 − 1085 − 4000 = 21001`. Ни model capacity, ни окно выбранной L1-модели в этой арифметике НЕ участвуют — чистый статический артефакт legacy-ключа. **Как убрать:** в Auto (`0/null`) L1-бюджет = резолвер: effective_window(`models.summary_l1_base_url`+`model`) − tokens(system) − output_reserve(stage) − single safety; static 30000 в Auto не читается вовсе. Регрессия §101/§142 фиксирует.

### Q5. Summary ↔ resolver: граница soft targets и auto budget (→ T-4055/T-4068)
Две независимые оси, смешивание запрещено:
- **Вход (physical, exhaustive):** coverage полный по configured window (§118–§120); physical budget = только транспортный рубеж; при переполнении — lossless chunking, никогда не drop. Capacity L1/L2 — от реальной пары слота (F6). Safety `token_safety_multiplier` — один раз. Output reserve per-stage: `SUMMARY_L1_OUTPUT_RESERVE_TOKENS=4000` / `L2=6000` объявляются stage-policy дефолтами резолвера (фактический `max_tokens` stage'а приоритетнее).
- **Выход (semantic length policy):** `limits.summary_hybrid_response_mode/_target_chars/_target_paragraphs/_max_chars` и жёсткий §99 (498 абзацев / 32000 символов / 900) остаются политикой ФОРМЫ статьи (L2). Soft targets формируют выход, **никогда не режут входной source set**.
- **Manual cap:** `limits.summary_hybrid_context_tokens > 0` = «максимальный размер одного L1-запроса» (размер chunk), не «сколько сообщений обработать» (§137). `0/null` = Auto. `…_chars` — только legacy/emergency, из normal UI (§77); два равноправных caps не поддерживаются.
- Legacy `MAX_SUMMARY_PARTS` в Hybrid не используется (уже так, F6/ADR-1027-10) — закрепить тестом.

### Q6. Bottom nav: что мерить (→ T-4083)
Мерить в проблемных вьюпортах (320×640/360×800/390×844/430×932 + desktop 1440×900, режимы §96): `window.innerHeight`, `visualViewport.height/offsetTop`, `Telegram.WebApp.viewportHeight/viewportStableHeight`, `safeAreaInset.bottom`, `contentSafeAreaInset.bottom`, computed `--app-usable-height`, `document.querySelector('.bottom-nav').getBoundingClientRect()` (top/bottom/высота иконки/label), rect последнего интерактивного элемента main. Текущая схема (F13) субстрагирует guessed-offset из `innerHeight` и не учитывает случай `innerHeight` ≠ реально видимой области — отсюда clipping, переживший несколько hotfix'ов. **ЕДИНАЯ модель геометрии (решение Architect, §92–§93):** shell height = фактически видимая высота вьюпорта (источник: в Telegram — `viewportStableHeight` при expanded==stable, иначе `viewportHeight`; вне Telegram — `visualViewport.height+offsetTop`, fallback `innerHeight`; выбор фиксируется в T-4083 измеренной таблицей); inset применяется ровно один раз — `padding-bottom: max(env(safe-area-inset-bottom), var(--tg-safe-area-inset-bottom), var(--tg-content-safe-area-inset-bottom))` на самом `.bottom-nav` как flex-child; main — flex-1, единственный scroll container. Паттерн «innerHeight минус guessed bottom offset» уходит; инварианты §94 обязательны (rect.top≥0; rect.bottom ≤ visibleBottom+tolerance; icon/label видны; main не под nav; SaveBar-сосуществование §98). Ещё один padding/bottom/z-index запрещён (§115).

### Q7. Неверные labels (→ T-4067; полный список — санкция раздела 10)
Технически неверные/непонятные (F15): (1) `limits.summary_hybrid_context_tokens` «потолок контекста (слов)» — tokens≠слова + семантика меняется (→ «Максимальный размер одного L1-запроса»); (2) `limits.summary_hybrid_context_chars` «потолок текста (символов)» — уходит в legacy/emergency; (3) `CHAT_CONTEXT_BUDGET_TOKENS` «…бюджет, слов (кусочков текста)»; (4) `CHAT_GLOBAL_KEY_BUDGET_TOKENS` «Лимит слов общего ключа в сутки»; (5) `SUMMARY_MAX_CONTEXT_TOKENS` «…пересказа, слов»; (6) группа «Прямой чат: бюджеты слов». Плюс общий запрет §83–§86 (raw keys как заголовки, P0/P1, `provider_catalog`, `131072`, serialized_tokens) и переводы machine states §87. При слове «токены» — однократное пояснение «технические единицы текста модели».

### Q8. Provider adapters — состав первого релиза (→ T-4052/T-4053)
Реально в проде сегодня: **generic OpenAI-compatible endpoints** (nano-gpt.com, api.deepseek.com — F16), у которых `/v1/models` не гарантирует context window. Состав первого релиза:
1. **Verified internal registry** (наследник `MODEL_CONTEXT_WINDOWS`, резолв по `model` с учётом provider-класса) — первичный прод-источник; расширяется фактически используемыми моделями (deepseek-семейство и активные).
2. **Provider catalog adapter** (OpenRouter: `context_length` из model catalog, кэш) — включается по детекту base_url; активен, если владелец подключит такой endpoint.
3. **llama.cpp adapter** (`/props` → `n_ctx`), **Ollama adapter** (running model `context_length`) — fixture-тесты обязательно (§41), прод-активация по факту подключения.
4. **vLLM** — источник `max_model_len`: config introspection, если endpoint доступен; **иначе registry + developer override** (санкционировано; не выдумывать из имени модели).
5. **Generic OpenAI-compatible** — adapter отсутствует по определению протокола: registry → fallback. Regex-угадывание окна из имени запрещено (§6).
Precedence и семантика — раздел 3. Локальный runtime 16K при theoretical 128K обязателен к использованию (§5).

### Q9. TTL кэша capacity (→ T-4052/T-4065)
- Remote catalogs (OpenRouter-класс): TTL default **24 ч**.
- Локальные runtime-адаптеры (llama.cpp `/props`, Ollama): лёгкий локальный HTTP — TTL **300 с**.
- Инвалидация немедленная (§7/§38): смена model/base_url/stage-модели/fallback-модели/context override, config reload, explicit refresh (кнопка «Обновить» в Advanced diagnostics).
- Настраиваемость: env `MODEL_CAPACITY_CACHE_TTL_SECONDS` (default 86400) — **env-only, в каталог и обычный UI не попадает** (§20: «не нужен пользователю — env/code-only»); в Advanced — read-only отображение source/age/fallback (§7, §21).

### Q10. Финальный состав Model Slots (→ T-4058/T-4059)
Registry строится из **фактически резолвимых** stage→(base_url, model) пар кода; слот без резолвимой пары не показывается (§19 automatic visibility). Первый релиз:
| Slot | Источник пары | В матрице |
|---|---|---|
| `direct.primary` | `models.llm_base_url` + `models.llm_model_name` | да |
| `direct.fallback` | fallback-пара Direct (если настроена) | да, иначе не показывается |
| `summary.l1` | `models.summary_l1_base_url` + `models.summary_l1_model_name` (F6) | да; наследование от primary — компактной строкой |
| `summary.l2` | `models.summary_l2_*` (F6) | да; аналогично |
| `summary.legacy` | глобальная основная пара, ТОЛЬКО когда активен Legacy fallback контур | условно |
| `intel.background` (dream/ностальгия/анти-клише — worker-генерация) | глобальная основная пара | да, одной строкой |
| `intel.reflection` (self_reflection) | `generate_worker('reflection')` пара | да, если пара отличима |
| decision/react | выполняется моделью `direct.primary` | отдельный слот НЕ создаётся |
| video/text LLM stages, использующие context composer | композер сегодня один — Direct | НЕТ (расширение — отдельным решением при появлении второго composer-потребителя) |
| image/STT/embeddings | — | вне text-context matrix (§13) |
Один model id может быть в нескольких slots с разными auto budgets (§13). Frontend слоты не вычисляет (§13).

### Q11. Схема LLM-реакции (→ T-4078/T-4079)
- **Кто владеет action:** детерминированная decision-матрица ОСТАЁТСЯ владельцем REPLY/REACT/SILENT (F7: `CoordinatorDecision` 0-LLM, граница A7, 2-вызовность System 2 сохраняется). LLM не решает «реагировать или нет».
- **Что выбирает LLM:** только конкретный emoji при action=REACT — аддитивное поле в structured output СУЩЕСТВУЮЩЕГО Stage-1 (тот же вызов, что генерирует ответ; **второго/третьего LLM request нет**, await_count==2 сохранено, прецедент A1 tool-coordinator).
- **JSON-контракт (additive):** `{"action":"REACT","reaction":"💀","reason":"…"}` — `reaction` валидируется против allowed set; при action≠REACT поле игнорируется (`__post_init__` уже обнуляет, F7).
- **Allowed set:** стандартный Telegram reaction enum; source of truth — расширенные A8-наборы union: `{😂,🤣,👍,👌,❤️,🔥,🤨,🤔,💀,🤡}` (точный список финализируется в T-4078 из фактического enum-константов; расширяется только целыми Telegram-emoji).
- **Невалидный/отсутствующий ответ → fallback:** детерминированный выбор `_reaction_for_class`/`_stable_reaction_pick` (текущее поведение) — fail-soft молча; одинаковый контент НЕ обязан давать одинаковую реакцию (§31).
- **SILENT→🗿:** единственный hardcode, без изменений (F8); LLM не выбирает emoji для SILENT; background SILENT — без 🗿.
- **Force keyword:** остаётся выше decision → всегда REPLY (F: force-гейт приоритет 1).
- **Kill-switch:** env `DIRECT_LLM_REACTION_ENABLED` (default ON, per-call) + существующий per-chat `flags.chat_decision_reactions_enabled`; OFF (любой из двух) → байт-в-байт текущее детерминированное поведение.

### Q12. Explicit rebuild в exhaustive-контракте (→ T-4068/T-4069)
**Входит.** «Перестроить Summary за период» — exhaustive-функция (§132): source set = все сообщения явно заданного периода; coverage 100%; при переполнении — chunk_all. Механика: отдельная фича НЕ строится — T-4069 проводит ВСЕ инвокации L1 через общий budget path (run_l1 уже единственная точка упаковки, F5), поэтому rebuild получает контракт автоматически. В acceptance T-4069 добавить чек-пункт: «rebuild за период использует тот же budget path и показывает coverage» (верификация одним прогоном, без нового кода, если текущий rebuild уже идёт через run_l1 — ожидаемо так).

---

## 3. Контракт: Model Capacity Resolver (§3–§8, §37–§39)

- **Вход:** реальная тройка `provider/base_url + model (+ runtime identity)`, не display name (T-4053).
- **Выход (структура §3):** `{provider, model, declared_context_window, runtime_context_window, effective_context_window, max_output_tokens, source, confidence, resolved_at, fallback_used}`.
- **Precedence (§4), детерминированный:** 1) Developer override (`models.chat_context_window_override > 0`, source `developer_override`); 2) runtime metadata фактического backend (source `runtime`); 3) provider catalog (source `provider_catalog`); 4) verified internal registry (source `registry`); 5) conservative fallback (source `fallback`) — только последний, только аварийно. Unknown-model **без ручной заглушки как нормального пути и без env как нормального пути**: env-значение elevируется ТОЛЬКО в Advanced developer override; отсутствие данных → fallback + `MODEL_CAPACITY_FALLBACK` (provider, model, base_url class, fallback_window, reason) + badge «Capacity: fallback» (§8). Никаких молчаливых 16384.
- **runtime > theoretical (§5):** `effective = min(известный runtime limit, известный provider/model limit)`; для remote — близко к declared; локальный 16K при 128K — используется 16K.
- **Adapters:** Q8. Cache: ключ `provider/base_url/model/runtime identity`; TTL Q9; инвалидация §38 (смена model/base_url/stage/fallback/override, reload, explicit refresh); в diagnostics — source/age/fallback (§7).
- **Override-семантика (§39):** `0/null = Auto`; `>0 = Developer override`; `-1` НИКОГДА не capacity (только policy Unlimited). Не смешивать уровни.
- **Consumers (§37):** Direct composer, Summary L1/L2 packers, fallback recompose, `/api/direct/context-diagnostics`, `/api/analytics/context-budgets`, Status compact — все из одного резолвера; второй независимый расчёт запрещён (§29).
- **Fallback-модель (§14):** снимается preemptive-min F3: при переключении на fallback — resolve capacity fallback отдельно → пересчёт effective budget → recompose при необходимости; fallback не получает oversized primary payload; P0 сохраняется; pressure/overflow observable. Регрессия §42.

## 4. Контракт: Stage Auto Budget (§9–§12, §133)

- Вход: capacity + stage + фактический mandatory payload + output policy + context policy + developer overrides. Выход — структура §9 (`stage, model, context_window, mandatory_tokens, output_reserve, safety_reserve, auto_input_budget, policy_mode, manual_cap, effective_input_budget, source`); числа ТЗ — пример структуры, не defaults.
- **Формула:** `effective_window − mandatory_tokens − output_reserve(stage) − safety_reserve(один раз) = auto_input_budget`; policy-слой: Unlimited(−1) → auto_input_budget; Dynamic(0/None) → min(auto, soft target); Cap(>0) → min(auto, cap). Safety reserve применяется **ровно один раз** на расчёт (существующий `safe_budget`/`token_safety_multiplier` — единственная точка, §10; двойное применение = регрессия инцидента 39371→27826).
- **Output reserve stage-aware (§11):** 1) фактический `max_tokens/max_completion_tokens` stage'а; 2) stage-policy (для Summary L1/L2 — существующие env `SUMMARY_L1/L2_OUTPUT_RESERVE_TOKENS` 4000/6000 объявляются дефолтами policy); 3) safe default (floor 1024). Обычному админу не показывается как обязательное поле.
- **Token estimation (§12):** tokenizer-specific → существующий counter → conservative fallback; после ответа — provider-reported actual; Analytics различает estimated/actual.
- **Stage policy metadata (§133):** `summary.l1 → coverage_policy: exhaustive, overflow_strategy: chunk_all`; `summary.l2 → exhaustive, hierarchical_reduce`; `direct.primary → relevance_composed, priority_reduce`; `direct.fallback → как primary с recompose`; metadata живёт в registry slots (раздел 5), не в разбросанных `if summary`.
- **Все Smart Module LLM-стадии** получают capacity через общий resolver; потребительский код не хардкодит `30000/16000/21001/32000` как physical capacity (§131).

## 5. Контракт: Model Slots (§13–§14, §18–§19)

Состав — Q10. Registry backend отдаёт готовую структуру (§18/§25 shape): назначение, display name, model id, provider, context window, capacity source, auto input budget, policy mode, last payload, utilization, fallback warning. Наследование: `Summary L1 → наследует Direct Primary` (не дубликат); UI-компакт `L1 — наследует основную модель`. Автовидимость: отдельная модель L1 → отдельная строка; нет fallback → нет пустой карточки; capacity fallback → warning + «Подробнее в Advanced» (§19).

## 6. Контракт: Per-chat Context Policy + разводка бюджетов (§15–§17, §43, §46, §51)

- **Policy:** Dynamic (soft target 16000 — operational, не hard scissors; P0/P1 protected; шум режется первым; §35 тест) | Unlimited (без artificial cap, ограничен physical capacity) | Manual Cap — только Advanced. Реализация — существующий derive `limits.chat_context_budget_tokens` (−1/0/>0, F2), миграций ключа нет.
- **Никаких VIP/hardcoded chat path (§16):** generic per-chat механизм; acceptance на втором обычном chat_id (Dynamic→Save→Reload→Dynamic; Unlimited→…→Unlimited; вернуть исходное) + unit/integration на два chat_id. rg-проверка отсутствия hardcoded chat-id в policy-пути — в T-4060 acceptance.
- **Разводка тумблера (§17, точная карта ключей):**
  - **Context Unlimited** (тумблер → Context Policy): трогает ТОЛЬКО `limits.chat_context_budget_tokens`.
  - **«Без суточных квот»** (отдельная настройка): трогает ТОЛЬКО `limits.chat_global_key_budget_requests`, `limits.chat_global_key_budget_tokens`, `limits.worker_daily_llm_calls_per_chat`, `limits.worker_daily_llm_tokens_per_chat`.
  - **Больше не общие тумблеру** (уходят из обоих; остаются поканальными настройками/Advanced): `limits.chat_global_context_max_tokens`, `limits.chat_thread_max_tokens` — context-класс, в обычный «Безлимит» не входят.
  - Тест §46 в обе стороны; миграция §51: перед миграцией читаются existing значения; если старый toggle выставил все 7 в −1 — намерение сохраняется (context keys остаются −1 через policy; quota keys остаются −1 через «Без суточных квот»), связь одной кнопкой исчезает; destructive reset запрещён; effective после == до.
- **Episode 200+ (§34):** механизм существует (композер: детерминированное расширение хитов mca-07, APP_VERSION-комментарий D2); T-4062 подтверждает сценарий retrieval hit ≥200 → expansion → verbatim, evidence `distance_messages/episode_messages/episode_tokens/verbatim=true/source`; raw текст в prod-логах запрещён.

## 7. Контракт: Summary Window = полный охват (§118–§146)

- **Source set:** configured window (например 6 ч) определяет ПОЛНЫЙ набор сообщений; все обязаны быть обработаны; budget — транспортный рубеж, не semantic selection (§118–§119, §129). Смена окна 6→12 ч — workload пересчитывается автоматически, ручных knobs нет (§130, §145).
- **Fast path:** всё помещается → 1×L1 (весь набор) → 1×L2 (§119, §125). Запрещены: importance eviction, sampling, short-message filtering, oldest dropping, soft-target truncation, fixed 30K/21K в Auto.
- **Overflow path:** lossless chunking → L1 по каждому chunk → merge → L2 (§120, §125). Chunker (§121–§123): chronological order; stable message IDs; каждый source ID ≥1 primary chunk; без удаления коротких/standalone/«неважных»; учёт serialized size/metadata/reply relationships; overlap соседних chunks с дедупликацией по stable ID на merge; reply continuity — boundary packing (parent/соседи/фрагмент цепочки) = overlap, не замена coverage; oversized single message — lossless segmentation (message_id/author/timestamp/part index/связь частей), merge восстанавливает принадлежность. Существующий примитив `estimate_and_split` (F5-файл, overlap=1, последнее сообщение неприкосновенно) — база, расширяется до полного контракта.
- **Merge (§124, §126):** cross-chunk темы объединяются (stable IDs + semantic descriptors + overlap evidence; доп. merge LLM call ТОЛЬКО при реальном physical overflow); happy path не дробится; L2 — hierarchical semantic reduction, уникальные темы не удаляются ради soft target.
- **Coverage (§127–§128, §135):** метрики на run: `source_window_start/end`, `source_messages_total/processed/unprocessed`, `l1_chunks`, `duplicate_overlap_messages`, `coverage_percent`; успешный run: unprocessed=0, coverage=100%; `<100%` — явный degraded (`SUMMARY_COVERAGE_DEGRADED`, reason), не тихий успех; событие `SUMMARY_L1_CHUNKED {source, processed, chunks, coverage}`; семантика `skipped=N` из-за budget как normal behavior НЕ существует (место `skipped` в `L1 truncated input` занимает chunked-статус).
- **Timeout (§80, §81, §139):** timeout ≠ резать контекст: retry по policy → fallback model → при меньшем окне fallback — lossless rechunk ПОЛНОГО source set (не «kept» subset, §140) → fail-soft package. Audit контракта L1 (T-4073): effective timeout, retry budget, реальная длительность primary/fallback (прод ≈156 c), dedicated vs inherited slot, без неожиданного умножения; если контракт корректен — не перепроектировать. Analytics отдельно показывает transport (latency/timeout/attempt/fallback reason) vs capacity.
- **L1_FALLBACK_PACKAGE (§82, §141):** ожидаемая recovery-механика, строится из полного window насколько возможно локально (прод: chronology=369 — инвариант сохранить); UI: статус «Опубликовано» + badge «L1: резервный пакет» + «Основная модель не ответила вовремя».
- **Manual cap (§137, §138):** ограничивает размер одного L1-запроса (chunk), не общий coverage; название «Максимальный размер одного L1-запроса», описание §138; только Advanced.
- **Регрессии (§101, §142–§145, T-4074):** (1) 369/6h/большое окно → chunks=1, coverage=100%, нет `skipped=81`, нет `limit=21001`; (2) маленькая локальная 16K/32K → все 369 обработаны, chunks>1, chronological, replies у границ с контекстом, без prefilter; (3) смена L1 A(large)→B(small) → cache invalidated, autobudget пересчитан, авто multi-chunk, coverage 100%, без ручных правок; (4) 6h→12h → без ручных изменений, chunks растут при необходимости, coverage 100%; (5) timeout при полном влезании → retry/fallback/rechunk полного набора; (6) manual cap ≤ окна → только размер chunk.

## 8. Контракт: LLM REACT / SILENT / Force (§30–§33, §47–§48)

См. Q11. Дополнительно: observability — `DIRECT_REACT {source=llm_decision, reaction, trigger_type}`; недопустимое значение отклоняется валидацией → детерминированный fallback (не ошибка пользователя). Тесты §47/§48 (mock decision `{"action":"REACT","reaction":"💀"}` → отправлено 💀; `🤡` → 🤡; нет hardcoded `laughter→😂` как единственного пути; SILENT+чужой reaction от LLM → всё равно 🗿; background SILENT — без обязательной реакции; Force → text reply).

## 9. Контракт: Miniapp / Analytics / Status / human-first

- **«Бюджеты» (§18–§19):** read-only карточка «Автоматические бюджеты моделей» из активных slots (Q10); формат строки-примера §18; никакой required-обработки чисел.
- **Developer/Advanced split (§20–§21, §44, §85–§86):** в «Расширенные системные»: Model context window override (`0/empty=Auto`, условное поле, «Auto detected: …»; при неуверенности — «Не удалось определить автоматически — используется fallback 16 384» + только тогда подсказка override), capacity source/status read-only, manual context cap, output reserve override per stage (если нужен), fallback window read-only. Cache TTL и внутренние ratios (`CHAT_BUDGET_*_RATIO`, «Доля бюджета: …») в UI не выводятся (env/code-only). У каждого Advanced-поля — русское описание 1–3 предложения (что/когда/что значит «Авто»/когда менять). Raw key — мелким monospace в «Технические детали».
- **Direct Context UI (§22, §43):** Context Mode Dynamic|Unlimited; ниже Current model / Auto context window / Auto available budget / last payload / pressure; breakdown — `<details>`; ручные числовые caps с основного экрана убрать.
- **Analytics (§24–§27, §45, §88, §104, §134–§135):** `GET /api/analytics/context-budgets` (global admin, optional `?chat_id=`) — shape §25 (slots[]: capacity/budget/observed); read-side поверх resolver + существующих usage events + diagnostics snapshots; **второй usage store не создаётся** (§24, §50). UI: human-first карточки (пример §88; формула не первая), таблица/колонки §26, статусы OK/Высокая загрузка/Fallback capacity/Manual override/Physical overflow, utilization относительно physical/effective budget, Unlimited ≠ 100% progress bar; badges источника §27; группировка §104 (Модели и автобюджеты / Использование и стоимость / Надёжность моделей / Выполнение / Память); mobile — accordion; «Полнота источника» §135; Coverage Policy человекочитаемо §134; timeout stats §103; machine states → русский §87/§105.
- **Status (§28–§29):** компактные строки («Direct: 1.05M · Auto 982K · last 39K»), warning badge при fallback/manual override, ссылка в полную Аналитику; legacy `memoryContext` можно сохранить; цифры — из одного резолвера.
- **Human-first copy (§83–§89, §106):** T-4067 по списку Q7; Reviewer проходит UI как пользователь без знания keys.

## 10. САНКЦИИ

### 10.1 Δ каталога параметров (F8 переиздание обязателен)
| # | Ключ/группа | Изменение | Тип |
|---|---|---|---|
| 1 | `limits.summary_hybrid_context_tokens` | label «Hybrid: потолок контекста (слов)» → **«Hybrid: максимальный размер одного L1-запроса (токены)»** + описание §138 | rename, ключ сохранён, значение мигрирует по §78 (untouched default→Auto-семантика; custom→manual cap, «Ручное ограничение включено») |
| 2 | `limits.summary_hybrid_context_chars` | label → «Hybrid: аварийный символьный потолок (legacy)»; из normal UI (группа остаётся Advanced) | rename; удаления НЕТ |
| 3 | `CHAT_CONTEXT_BUDGET_TOKENS` | «Контекст: общий бюджет, слов (кусочков текста)» → «Контекст: бюджет Direct, токенов» | rename |
| 4 | `CHAT_GLOBAL_KEY_BUDGET_TOKENS` | «Лимит слов общего ключа в сутки (чат)» → «Лимит токенов общего ключа в сутки (чат)» | rename |
| 5 | `SUMMARY_MAX_CONTEXT_TOKENS` | «Legacy: потолок контекста пересказа, слов» → «…, токенов» | rename |
| 6 | группа `limits_chat_budgets` | «Прямой чат: бюджеты слов» → «Прямой чат: бюджеты (токены)» | rename |
| 7 | **НОВЫЙ** `models.chat_context_window_override` | int, default 0=Auto, settings-поле — существующий `CHAT_MODEL_CONTEXT_WINDOW`; группа: LLM/Advanced (models_llm) | +1 ключ |

- **Ожидаемые F8-числа:** baseline **483/423/458/105/103/21** → **484/424/459/105/103/21** (+1 REGISTRY / +1 Settings (первая каталогизация env ClassVar `CHAT_MODEL_CONTEXT_WINDOW`) / +1 categorized / GROUPS/TAB/tabs без изменений). Точные значения фиксируются из фактического вывода F8-харнесса в билд-коммите; санкционируется Δ≠0 при арифметически согласованном пересчёте (прецедент ASAP-3 §6). F8 переиздаётся атомарно той же серией коммитов.
- **Δ DDL = 0 — подтверждено:** coverage-метрики, budgets, reactions — через события/логи (раздел 10.3), PG-схема не расширяется; миграции настроек — на существующем config-механизме (§78), без DDL.
- **Δ зависимостей = 0.** R17/R18 — без изменений (новые события по whitelist-паттерну §49).

### 10.2 Kill-switch реестр новых механизмов (env-only ClassVar, default ON, резолв per-call, прецедент A1/D15)
| Флаг | Механизм | OFF-поведение (парити) |
|---|---|---|
| `MODEL_CAPACITY_RESOLVER_ENABLED` | новый capacity resolver | прежний путь: карта `MODEL_CONTEXT_WINDOWS` + 16384 (текущий `model_capacity.py`) |
| `AUTO_BUDGET_RESOLVER_ENABLED` | единый auto budget для стадий | прежние per-stage бюджеты (Summary: hybrid 30000-путь; Direct: D2) |
| `SUMMARY_COVERAGE_CHUNKING_ENABLED` | lossless chunking + coverage | прежний single-pass pack (семантика `L1 truncated … skipped=…`) |
| `DIRECT_LLM_REACTION_ENABLED` | выбор реакции LLM | детерминированные A8-наборы (текущие) |
| `UI_BUDGETS_SPLIT_ENABLED` | разводка тумблера «Безлимит»/«Без суточных квот» в Miniapp | прежний объединённый toggle (байт-в-байт) |
| `ANALYTICS_CONTEXT_BUDGETS_ENABLED` | endpoint + блок «Автобюджеты» в Analytics | endpoint скрыт (404), блок не рендерится; остальная страница без изменений |
| `CONFIG_MIGRATION_INFO_LOGGING_ENABLED` | INFO-логирование custom-preserved (§79) | прежнее WARNING-логирование |
- Без флагов (сознательно): Polygon и bottom-nav фиксы — чистый frontend render, rollback холодным revert-тегом (прецедент 10.20-UPD3 UI-rework «hot-флага нет и не должно быть»); IT-инварианты — parity-тесты + screenshots до/после.

### 10.3 Observability (§49–§50)
- **Новые события** (аддитивно к закрытому enum 28, коллизий нет — F9): `MODEL_CAPACITY_RESOLVED {slot, provider, model, effective_window, source, fallback_used}`; `AUTO_CONTEXT_BUDGET {slot, context_window, mandatory_tokens, output_reserve, safety_reserve, effective_input_budget, policy_mode}`; `DIRECT_REACT {source=llm_decision, reaction, trigger_type}`; `SUMMARY_L1_CHUNKED {source_messages, processed_messages, chunks, coverage}`; `SUMMARY_COVERAGE_DEGRADED {…, unprocessed_messages, reason}`. Whitelist-поля R17-safe: добавить `slot/provider/effective_window/fallback_used/mandatory_tokens/safety_reserve/effective_input_budget/coverage/chunks/processed_messages/unprocessed_messages` в `_NUM_FIELDS/_MODEL_FIELDS/_IDENT_RE`-слои по образцу D15.
- **Существующие переиспользуются:** `CONTEXT_CAPACITY/CONTEXT_SELECT/CONTEXT_PRESSURE/CONTEXT_PHYSICAL_OVERFLOW/DIRECT_SILENT_ACK/REACTION_SENT` — расширение полей аддитивное (`slot`, `selected_tokens`, `dropped_p2/dropped_p3`), имена не переименовываются.
- **Метрики §50:** capacity fallback count, manual override count, context pressure/physical overflow counts, P0/P1 protected count, per-slot p50/p95 input tokens, react count + distribution, silent ack count — process-local + grep-able по прецеденту `direct_metric name=… count=…`; события Summary — в существующий structured log/ExecutionGraph; **отдельная вторая система usage НЕ создаётся**.

---

## 11. DoD / production acceptance / rollout

- **DoD §55 (1–25) + §112 (26–58) + §146 (59–77):** mapping в `tasks.md` (DoD mapping) проверен поэлементно — gaps не найдены; каждый пункт имеет задачу и verification path. Спец-замечания: §112.36–38 (Analytics) закрывается F11-фиксом + T-4082 browser-доказательством; §112.57 и §146 закрываются T-4074-регрессиями; §55.23/§58 — T-4090.
- **Workflow gate §113:** порядок Architect (этот документ) → Builder → Browser Use verification → Playwright regression → Reviewer → rework → Approved → production deploy → live acceptance → screenshots/logs → §61 → `current_task continuation unblocked`.
- **Production acceptance §53 (11) + §108–§110:** mappable 1:1 на T-4089 (чеклист в tasks.md); §111 (8 вопросов инцидента) — T-4090. Ответы для §111 уже зафиксированы Q4/Q5/разделом 7 (21001 = legacy-артефакт, не physical limit; timeout — transport; fallback package сработал).
- **Rollout 2.58.36 → 2.58.37:** bump APP_VERSION; annotated-тег отката `pre-2.58.37`; soft-откат — kill-switch'и 10.2 (каждый → байт-в-байт прежний путь); cold — git revert до тега; deploy только после Reviewer Approved; secrets-дисциплина R17 (ключи/SSH только на шаге деплоя). Известные среды падения тестов (trafilatura, InputRichMessageMedia чужой WIP, `test_forbidden_paths_out_of_diff` якорный, F8 от eol-нормализованного вида) — учитывать в T-4087.
- **Открытые пункты (не блокируют design, фиксируются в T-acceptance):** рестарт-необходимость при смене capacity на конкретном runtime — UI сообщает честно (§38); диапазоны mesh compact/medium/large корректируются визуальным тестом (§66); тестовую смену model/config на проде (§53.6) согласовать с владельцем; вернуть исходные per-chat политики после acceptance-прогонов (§16).

## 12. Риски

| Риск | Уровень | Митигция |
|---|---|---|
| Неверная формула auto budget (ядро фичи) | высокий | safety ×1 инвариант тестом; parity OFF-путей всех kill-switch'ей; §42/§142–§145 регрессии до деплоя |
| Chunker сложнее ожидаемого | высокий | база `estimate_and_split` переиспользуется; chunk_all только в overflow; coverage-метрики доказывают полноту |
| Analytics Q3 — статически цел, а прод-фейл воспроизводится | средний | 12-шаговый §71 с измерениями обязателен; fix по факту, не по гипотезе |
| Bottom nav на реальном Telegram WebView не воспроизводится в тестовой среде | средний | измерения на 5 viewports + Telegram-переменные; fallback-приоритеты источников высоты зафиксированы Q6 |
| Деградация резолва для unknown-модели | средний | registry+fallback нижним этажом; badge всегда; §40 кейсы |
| Регрессия Direct (композер) | средний | известные composer-тесты ASAP-3; OFF parity |
| Пользовательская миграция тумблера | средний | non-destructive §51; effective до/после равны; тесты §46 |
| Визуальные критерии Polygon субъективны | низкий | diagnostics-поля Q2 + скриншоты §97 + §100 свойства |

## 13. Владение верификациями
- Builder: unit/integration (§40–§48, §142–§145), parity OFF-путей, F8-харнесс.
- Reviewer: Browser Use click-through (§71/§107), Playwright regression (§99/§100), screenshots §97, copy pass §106.
- DevOps/Orchestrator: prod-деплой 2.58.37, §53/§108–§110 evidence, §111/§116 отчёт (T-4089/T-4090).
