# Раунд 10.9 — admin-ui-round109 (UI/UX + model-status)

> **✅ СТАТУС: ЗАВЕРШЕНО И ЗААРХИВИРОВАНО (12.09.2026, @PM Step 8 Archive Phase).**
> Фича перенесена из `plans/features/admin-ui-round109/` в
> **`plans/archive/admin-ui-round109/`** (плоский kebab-case, как существующие архивы).
> **Итог:** полный pytest — **5105 passed / 0 failed** (база 10.8 = 5076 → **+29**); @Reviewer —
> **APPROVED WITH MINOR ISSUES** (1 Critical + 1 High + 2 Medium + 3 Low — все устранены, follow-ups
> закрыты); @Scanner — **CLEAN: 0 blocker / 0 major / 0 medium** (3 low R10.9-1/-2/-3 +
> 3 info R10.9-4/-5/-6 — известный точечный техдолг) (`plans/reports/round10.9_scanner_audit.md`);
> @Architect — архитектура влита в `plans/ARCHITECTURE.md` (**§30** + связанные §1/§9/§25).
> **Каталог-инвариант:** REGISTRY **400** / GROUPS **90** / Settings **372** (mapped 88).
> Артефакты сохранены: `spec.md`, `ADR-109.md`, `tasks.md`.
> **⚠️ Пункт 2 (инфраструктура IDE) — ВНЕ СКОУПА проекта:** инструмент локального IDE
> владельца (OpenCode), **не часть бота**; в коде/конфиге/тестах проекта ссылок нет. Операционного
> содержимого (systemd-юнит, firewall, `opencode.jsonc`) в архиве **нет** — только маркеры
> «out of scope».
> **ОТКРЫТО (live-верификация на реальном Android):** **T-1277, T-1290, T-1292, T-1294, T-1302,
> T-1305** — реальное Android-устройство/Telegram в среде @Builder недоступно; статически покрыто
> (`tests/test_webapp_round109_ui.py`, JS-юниты). Финальная live-проверка — за владельцем/QA.
> **ВНИМАНИЕ:** пост-архивная фаза @DevOps (commit/push/deploy/live-smoke, T-1309…T-1311) —
> после архивации; статусы `[ ]` ниже — снимок на момент архивации.

> **Фича:** `plans/archive/admin-ui-round109/` (kebab: `admin-ui-round109`; перенесена @PM Step 8 12.09.2026).
> **Нумерация:** **T-1270…T-1314** (продолжает T-1269 — финал 10.8).
> **Преемник:** 10.8 `admin-ui-round108` (архив; задеплоен 11.09.2026; commit `31d2ce7`, health 200).
> **Дата планирования:** 12.09.2026 (@PM, Step 1). **Дата архивации:** 12.09.2026 (@PM Step 8).
> **Статус:** ✅ **РЕАЛИЗАЦИЯ ЗАВЕРШЕНА; фича заархивирована 12.09.2026** (@PM Step 8).
> **Дословный запрос владельца (пункты 1, 3–8)** — §1 ниже. **Пункт 2 (инфраструктура IDE) — вне скоупа проекта** (инструмент локального IDE владельца, не часть бота; см. §0).

---

## 0. Базовая линия и инварианты (не ломать)

- **pytest baseline: 5076 passed / 0 failed** (10.8). Регрессий быть не должно; цель 10.9 — **≥ 5076 + новые**.
- `node --check web/app.js` — clean.
- `node tests/js/routing_test.js` — `JS-UNIT-OK`.
- `git diff --check` — чист (только LF/CRLF-предупреждения допустимы).
- Каталог-инвариант: **REGISTRY 392 / GROUPS 91 / Settings 364 / mapped 89**, `TAB_RULES` 19, `CONFIG_TAB_TITLES` 19 — **если добавляются новые ParamSpec/GroupSpec (п.7.2 «Название модели») — числа меняются осознанно и синхронно с тестами-пинами**.
- **Ноль новых PG-DDL** (никаких `CREATE TABLE/ALTER TABLE/ADD COLUMN`). SQLite `user_version` не трогать.
- `bot.py` router order — **не трогать**. `media/` — **не трогать**. `.env` — **не трогать**.
- Секреты не коммитить (R17); реальные ключи — только на сервере.
- **Пункт 2 (инфраструктура IDE) — ВНЕ СКОУПА проекта:** инструмент локального IDE (OpenCode) владельца, **не часть бота**. В коде/конфиге/тестах проекта ссылок на него нет; серверный infra-deliverable и `opencode.jsonc` в репозиторий не входят.

---

## 1. Дословный запрос владельца (capture exactly, пункты 1 и 3–8)

> Пункт 2 из исходного ТЗ **исключён**: это инфраструктура локального IDE владельца (OpenCode), не часть бота (см. §0).

1. **PERMsoc:** split «Персоны (ID): Славик и Оля» into separate «Оля» and «Славик»; GROUP all section params by owner (e.g. all Славик params incl. deadpage + mimicry that belong solely to him in ONE block); each block = collapsible sub-section; each block gets an on/off toggle; ensure NO duplicate toggle inside the block (only one); toggles must really work (not decorative).
3. Parameter changes must not reset page scroll to top.
4. Rewrite ALL parameter/section descriptions: concise, clear, simple, no jargon/abbreviations, no AI patterns, ironic tone, understandable to a novice.
5. «Модули» bottom has «Тяжелые фичи»: investigate; if it duplicates the per-module toggles, remove it.
6. «Бюджет фона» in «Модули» shows zeros regardless of chat: verify functionality; check duplication with «Сводка»; possibly move it to «Сводка».
7. Refactor UI + model status:
   - **7.1 Dashboard:** merge provider cards (deepseek, groq, openrouter, deepseek_fallback) into ONE block «Доступность ключей»; remove hardcoded provider names; group by function: «Основные функции ИИ» (main + fallback), «Транскрибация» (groq), «Саммаризация видео» (openrouter), «Эмбеддинги» (main + two fallbacks). Row format: custom name (7.2), real provider/model, masked key, latency, Health. Health bugfix: show REAL availability/error code (502/503/Timeout), not cached 200 (e.g. apinet.cloud down).
   - **7.2 Provider settings:** add «Название модели» as the FIRST field of each provider/function form (feeds dashboard name). Layout: constrain form width in fullscreen (max-w-3xl/max-w-4xl), left/center aligned.
8. Speed up background gradient animation slightly.
   **Plus:** README (ironic tone), Russian commit, push, deploy, plain-language report.

---

## 2. Рекогносцировка (file:line, HEAD `51f308b`)

### 2.1 п.1 — PERMsoc: персоны/группы/тумблеры
- Группа-нарушитель: `services/param_catalog.py:300` `GroupSpec("reactions_persons", …, "Персоны (ID): Славик и Оля", …, 1)`; описание `:301`.
- Персоны в этой группе: `param_catalog.py:1104` `SLAVIK_USER_ID` → `reactions_persons`; `:1156` `OLYA_USER_ID` → `reactions_persons`.
- Владение группами (owner-scoped):
  - **Славик:** `reactions_slavik` (`:308`; `SLAVIC_RANDOM_DIR` `:1130`, `SLAVIC_PHOTO_PATH` `:1132`), `reactions_deadpage` (`:306`; `DEAD_PAGE_*` `:1112–1118`), `limits_deadpage` (`:200`; `:719–723`), `limits_mimic` (`:198`; `SLAVIK_MIMIC_MIN_WORDS/COOLDOWN` `:745/:747`), `reactions_mimic` (`:321`; `MIMIC_VICTIM_USER_IDS` `:1148`), `reactions_permsoc` (`:335`; `ALAN_MIMIC_ENABLED` `:1150`), `flags_media` (`:289`).
  - **Оля:** `reactions_olya` (`:323`; `OLYA_MEDIA_BASE` `:1158`, `OLYA_SAVEASBOT_*` `:1160/:1162`, `OLYA_CAPTION_TEXT` `:1164`, `OLYA_MEDIA_TYPE` `:1166`), `flags_permsoc` `OLYA_ENABLED` (`:668`), `flags_media` `OLYA_CAPTION_ENABLED/REPOST/ALWAYS_SEND/CAPTION_MENTION` (`:670–676`), `limits_media_permsoc` (`:196`; `OLYA_COOLDOWN` `:749`).
- Состав вкладки PERMsoc: `param_catalog.py:1668–1680` (`TAB_PERMSOC`: reactions `reactions_persons…reactions_olya`, flags `flags_permsoc/media/behavior`, limits `limits_*`).
- Реестр модулей/под-флагов: `services/permsoc.py:51–72` (`PERMSOC_MODULES`, `sub_flag_key`: `flags.olya_enabled`, `flags.mimic_enabled`), `:34` `MASTER_FLAG_KEY`, `:93–133` `master_enabled/module_enabled`.
- UI PERMsoc: мастер-карточка `web/index.html:812–854` (мастер-тумблер `@change="togglePermsoc"` `:823`; сводка 5 модулей `:836–847`); generic-рендер групп ниже `:887–1105` (bool-тумблер `:926–944`, `saveConfigItem` `:935`); окно параметров модуля `web/index.html:1252–1485`, JS `openModuleWindow` `web/app.js:1924–1949`, `activeModuleGroups` `:840–844`.
- **Дубль тумблера (root cause п.1):** `PERMSOC_ENABLED` — обычный `bool` в группе `flags_permsoc` (`param_catalog.py:662`) и рендерится generic-тумблером (`index.html:926–944`) НИЖЕ мастер-карточки с тем же смыслом (`index.html:818–826`). Аналогично `OLYA_ENABLED` (`:668`) и `MIMIC_ENABLED` (`:680`) дублируют состояние модулей из сводки.

### 2.3 п.3 — Скролл при сохранении
- `web/app.js:2234–2238` — `setTab` сбрасывает `sc.scrollTop = 0` (переключение вкладки — это ок).
- `saveConfigItem` `web/app.js:2658–2717` → `await this.loadConfig()` `:2706` (и ветка 409 `:2710`). `loadConfig` `:2457–2504` заменяет `configItems/configGroups` (полный ре-рендер) — **проверить, не теряется ли позиция скролла** при перерисовке карточек/`<details>`.
- Дополнительно: `web/app.js:3303` (`panel.scrollTop = 0` — логи, вне скоупа), `web/app.js:2099` `scrollToId` (hub-карточки, вне скоупа).
- **Метод фикса (для @Builder):** снять `document.scrollingElement.scrollTop` ДО `saveConfigItem`, восстановить после `loadConfig()` в `$nextTick`; не трогать `setTab` (переключение вкладки должно остаться с top). Проверить `keydown`/фокус.

### 2.4 п.4 — Где живут описания
- `ParamSpec` (`title_ru`, `description`): датакласс `services/param_catalog.py:73–108`.
- `GroupSpec` (`title_ru`, `description`): датакласс `services/param_catalog.py:127–140`.
- Все группы: `param_catalog.py:180–336`, `:650–709`, `:1104–1166` (и далее) — **91 группа**; описания параметров — inline в ~392 записях.
- Рендер в UI: описание группы `web/index.html:902`; параметра — `:942` (bool «Что это?»), `:948` (kv), `:954` (json/prompts/content), `:967` (keys), `:993` (select), `:1005` (generic), `:1050` (advanced).

### 2.5 п.5 — «Тяжёлые фичи» (дубль?)
- UI: `web/index.html:1213–1250` (2 ветки: без чата `:1213–1222`, с чатом `:1223–1250`); тумблеры гейтов `:1234–1244` `@change="toggleGate"`.
- JS: `loadGateInfo` `web/app.js:1591–1607`, `toggleGate` `:1629–1645`, `whoCanToggle` `:1659`, `optInCount` `:1706`.
- Реестр «тяжёлых» фич: `services/feature_gates.py:26` (ровно 3: dream / nostalgia / auto-lore).
- Per-module тумблеры: список модулей `web/index.html:1153–1172` (`moduleEnabled/toggleModule`), `MODULES` `web/app.js:~325–360` — есть `mod_sleep` (`memory.dream_enabled`) и `mod_nostalgia` (`memory.nostalgia_enabled`).
- **Вывод рекогносцировки:** `gateInfo.gates` для `dream`/`nostalgia` **дублирует** per-module тумблеры «Сон»/«Ностальгия»; авто-лор гейтится только через gate-card. @Builder подтвердить и, если дубль подтверждён, **удалить карточку** (сохранив авто-лор-гейт там, где он не дублируется).

### 2.6 п.6 — «Бюджет фона» (нули)
- UI: `web/index.html:1176–1211`; источник `GET /api/workers/budget` — `web/api/gates.py:148–157` → `worker_budget.get_day_summary(cache.pg)`.
- JS: `loadBudgetInfo` `web/app.js:1609–1616` (`budgetInfo = await api('/api/workers/budget')`), `budgetRatio` `:1685`; вызов пары `Promise.all([loadGateInfo(), loadBudgetInfo()])` `:1623` (проверить, из какого метода — вероятно «Модули»).
- Дубль со «Сводкой»: `web/index.html:1520–1572` (таблица Oversight, колонка «Бюджет» `c.budget`, `:1566`), `loadOversight` `web/app.js:1694`.
- **Задачи:** воспроизвести нули (per-chat scope vs global), проверить `scope`-ключ в ответе, и либо починить, либо перенести блок в «Сводку» и убрать дубль.

### 2.7 п.7 — Dashboard/статус и форма провайдеров
- **Карточки провайдеров (dashboard):** `web/index.html:2546–2564` (`v-for="card in statusData.llm"`, заголовок-хардкод `card.provider` `:2548`, health `:2560–2561`).
- **Серверный источник:** `services/status_service.py:139–183` `llm_registry()` (хардкод имён `deepseek`/`groq`/`openrouter`/`deepseek_fallback`), `:386–412` `_build_llm_card`, `:187–201` `_check_health` (**кэш 60 с** `_HEALTH_CACHE_SECONDS`), `:203–224` `_ping_models` (ok только `200`; иначе `unreachable`; **таймаут и код не различаются**), `build_snapshot` `:319–384`, `permsoc_telemetry` `:414–457`.
- **История/код доступности:** `services/key_history.py` (allowlist-сэмплы), endpoint `web/api/routes.py:1090–1102`; фронт `web/app.js:3206–3231` (`loadKeyHistory`, `latestSample`, `availabilityClass`, `availabilityCode`), `web/index.html:2574–2613` (таблица `.keys-avail`).
- **Health-баг (гипотезы для @Builder):** (а) `_health_cache` на 60 с отдаёт старый `200`, пока провайдер уже лежит; (б) `_ping_models` пингует `/models`, а падает chat-completions (502/503) → важно различать код/таймаут; (в) при exception `http_status=None` и UI показывает `unreachable` без кода. Нужно: реальный код (502/503), distinguish `timeout`, не отдавать stale-200 (или инвалидировать кэш при ошибке), плюс реальный upstream (`apinet.cloud down`).
- **Группировка по функциям (п.7.1):** main+fallback → «Основные функции ИИ»; groq → «Транскрибация»; openrouter → «Саммаризация видео»; embeddings (main + два фоллбэка) → «Эмбеддинги». В текущем `llm_registry()` эмбеддинг-провайдеров НЕТ — @Architect/@Builder определить источник (ключи `models.embedding_model_name` и фоллбэки из `config/settings.py`), иначе блок «Эмбеддинги» пуст.
- **Форма провайдеров (п.7.2):** `web/index.html:762–804` (блоки `providerBlocks`), `PROVIDER_BLOCKS` `web/app.js:364–430` (поля `base_url/model/api_key`). Добавить первым полем «Название модели» (кастомное имя) + ограничить ширину формы (`max-w-3xl`/`max-w-4xl`, left/center).
- **Где хранить кастомные имена:** открытый вопрос §7 — либо новые `models.*_display_name` ParamSpec (каталог 392→N), либо карта в коде/`bot_settings`. @Architect решает.

### 2.8 п.8 — Градиент
- Токены/анимации: `web/index.html:37–39` (`--grad-speed:18s`, `--grad-ease`), `@keyframes grad-spin` `:88`, `grad-drift` `:89`, применение `:90–95`, фон `body::before` `:111–121` (`grad-drift 24s`), `prefers-reduced-motion` `:122–126`.
- **Ускорить «слегка»:** уменьшить длительности (напр. `--grad-speed` 18s→~14s, `body::before` 24s→~18s), не ломая `prefers-reduced-motion`/`prefers-contrast`.

---

## 3. План задач

### 3.1 п.1 — PERMsoc: персоны, owner-блоки, тумблеры (T-1271…T-1277)

- [x] **T-1271 (@Builder):** Разделить `reactions_persons` на «Славик (ID)» и «Оля (ID)»; перенести `SLAVIK_USER_ID` (`param_catalog.py:1104`) → блок Славика, `OLYA_USER_ID` (`:1156`) → блок Оли. Обновить `TAB_PERMSOC` (при необходимости), `GROUPS`-инвариант и тесты-пины.
- [x] **T-1272 (@Builder):** Сгруппировать параметры по владельцу: у Славика — `reactions_persons(SLAVIK_USER_ID)` + `reactions_slavik` + `reactions_deadpage` + `limits_deadpage` + `limits_mimic(SLAVIK_MIMIC_*)`; у Оли — `OLYA_USER_ID` + `reactions_olya` + `flags_permsoc(OLYA_ENABLED)` + `flags_media(OLYA_*)` + `limits_media_permsoc(OLYA_COOLDOWN)`. Спорные (общая мимикрия, `reactions_permsoc`) — отдельным блоком «Общее».
- [x] **T-1273 (@Builder):** Каждый owner-блок — **collapsible** подсекция (нативный `<details>`/аккордеон в стиле «Расширенные»), с заголовком владельца.
- [x] **T-1274 (@Builder):** На каждый owner-блок — **ровно ОДИН on/off тумблер**, реально управляющий модулем через существующий `permsoc`-гейт (`flags.olya_enabled`/`flags.mimic_enabled`/мастер). Тумблер НЕ декоративный: `@change` → `PUT /api/chat/{id}/gates` или `POST /api/config` и ре-фетч состояния.
- [x] **T-1275 (@Builder):** Убрать **дублирующий** тумблер внутри блока: `PERMSOC_ENABLED` (generic bool `index.html:926–944`), `OLYA_ENABLED`, `MIMIC_ENABLED` не должны рендериться вторым тумблером там, где уже есть owner-тумблер (скрыть/вывести как read-only состояние, не как второй переключатель).
- [x] **T-1276 (@Builder):** Проверить парность UI↔бэкенд: один и тот же тумблер не должен одновременно писать `gates` и `flags` (единый источник — `permsoc.master_enabled/module_enabled`). Обновить JS-юнит/маркер-тест.
- [ ] **T-1277 (@QA):** Live Android: блоки сворачиваются, тумблер один, включение/выключение реально меняет поведение (per chat).

### 3.3 п.3 — Скролл при сохранении (T-1287)

- [x] **T-1287 (@Builder):** Сохранение параметра (`saveConfigItem`) не должно сбрасывать `document.scrollingElement.scrollTop`. Снять позицию до запроса, восстановить после `loadConfig()` в `$nextTick` (сохранить для bool/int/float/str/json и `saveKeyItem`/`saveSettings`). Не трогать `setTab`-сброс. Маркер-тест/JS-юнит.

### 3.4 п.4 — Переписать описания (T-1288…T-1290)

- [x] **T-1288 (@Builder):** Переписать **все** `GroupSpec.description` (91) и `ParamSpec.description` (~392): кратко, простым языком, без жаргона/аббревиатур (RAG/LLM/token/JSON → человеческие слова), без AI-паттернов, с лёгкой иронией, понятно новичку. Технические имена ключей оставить.
- [x] **T-1289 (@Builder):** Проверить, что новые описания корректно рендерятся в UI (bool «Что это?» / карточки) и что пустых описаний не осталось (тест: `description` непустой и без запретных аббревиатур).
- [ ] **T-1290 (@QA):** Выборочно прочитать вслух «глазами новичка» ключевые группы (PERMsoc, Модули, Ключи, Лимиты) — тон ровный, ирония уместна, смысл не потерян.

### 3.5 п.5 — «Тяжёлые фичи» (T-1291…T-1292)

- [x] **T-1291 (@Builder):** Подтвердить дубль `gateInfo.gates` (dream/nostalgia) с per-module тумблерами. Если дубль подтверждён — **удалить** блок «Тяжёлые фичи» с вкладки «Модули» (`index.html:1213–1250`) вместе с осиротевшими `gateInfo`-вызовами (если больше нигде не нужны). Авто-лор-гейт, если он остаётся без дубля, перенести/сохранить отдельно (не терять функционал).
- [ ] **T-1292 (@QA):** Убедиться, что удаление не убило управление гейтами (dream/nostalgia — через модули; авто-лор — где осталось) и что нет мёртвого кода/ссылок.

### 3.6 п.6 — «Бюджет фона» (T-1293…T-1294)

- [x] **T-1293 (@Builder):** Воспроизвести «нули» (`GET /api/workers/budget`): проверить форму ответа и `scope` per-chat; найти root cause (детерминация дня/скоуп/лимиты=0) и починить данные/рендер. Если дублируется со «Сводкой» — **перенести блок в «Сводку»** (`#/oversight`) и убрать дубль с «Модулей».
- [ ] **T-1294 (@QA):** Проверить с реальным чатом и «Весь бот»: цифры непустые и совпадают со «Сводкой»; после переноса блок не пропал.

### 3.7 п.7 — Dashboard/статус + форма провайдеров (T-1295…T-1305)

- [x] **T-1295 (@Architect):** Контракт данных: `llm_registry()` → сгруппированные по функциям записи (Основные функции ИИ / Транскрибация / Саммаризация видео / Эмбеддинги). Определить источник эмбеддинг-строк (main + два фоллбэка) и custom-name (T-1299).
- [x] **T-1296 (@Builder):** Убрать хардкод имён `deepseek/groq/openrouter/deepseek_fallback` из вывода (провайдер — отдельное поле, имя — из T-1299). Обновить API-allowlist (leak-safe) и тесты `test_status_service.py:527`.
- [x] **T-1297 (@Builder):** Слить карточки в **ОДИН** блок «Доступность ключей»; рендер по группам функций (4 группы). Строка: custom name, real provider/model, masked key (`••••last4`/configured), latency, Health.
- [x] **T-1298 (@Builder):** Health bugfix: показывать реальный статус/код (502/503/Timeout), не stale-200 из 60-с кэша. Пиновать `/models` недостаточно — при необходимости дополнить/заменить реальным upstream-тестом; при ошибке инвалидировать кэш; различать `timeout`/`unreachable`/`http_status`. Обновить `_check_health`/`_ping_models` (`status_service.py:187–224`) + фронт `healthBadge` (`app.js:3161`) + тесты. Согласовать с open R10.7-1/-2.
- [x] **T-1299 (@Architect/@Builder):** «Название модели» — первое поле формы провайдера (`index.html:762–804`, `PROVIDER_BLOCKS` `app.js:364–430`); решить хранение кастомных имён (ParamSpec vs карта), синхронизировать с каталогом/тестами-пинами; имя попадает в dashboard (T-1297).
- [x] **T-1300 (@Builder):** Layout формы провайдеров: ограничить ширину (`max-w-3xl`/`max-w-4xl`) и выровнять (left/center) в fullscreen.
- [x] **T-1301 (@Builder):** Обновить маркер-тесты UI: `test_webapp_key_availability_ui.py`, `test_webapp_api.py`, `test_status_service.py`, `test_webapp_round*.py` — под новые имена/группы/формат строк.
- [ ] **T-1302 (@QA):** Live: при `apinet.cloud` down показан реальный код/timeout (не 200); при живом — 200 и latency; группы совпадают с ТЗ.
- [x] **T-1303 (@Builder):** Проверить, что «Название модели» — именно ПЕРВОЕ поле в каждом провайдер-блоке, и что сохранение имени не ломает существующие `base_url/model/api_key`.
- [x] **T-1304 (@Builder):** Проверить, что после merge нет двойного рендера провайдеров (generic-группы `models_*` vs блоки) — учесть открытый R10.6-1.
- [ ] **T-1305 (@QA):** Мобильный/Android: блок «Доступность ключей» не разъезжается, маскирование ключей сохраняется.

### 3.8 п.8 — Градиент (T-1306)

- [x] **T-1306 (@Builder):** Ускорить анимацию фона «слегка» (`--grad-speed` и `grad-drift 24s`), сохранив `prefers-reduced-motion`/`prefers-contrast` и читаемость (WCAG AA). Маркер-тест на новые значения.

### 3.9 Финал: README / commit / push / deploy / report (T-1307…T-1311)

- [ ] **T-1307 (@Builder/@PM):** README (ироничный тон): обновить шапку (**v2.53.0**, новый счётчик тестов), changelog раунда 10.9. Синхронно поднять `APP_VERSION` `config/settings.py:1069` → `2.53.0` (закрыть риск R10.8-5).
- [x] **T-1308 (@Builder):** Полный прогон: `pytest` (baseline 5076 + новые), `node --check web/app.js`, `node tests/js/routing_test.js`, `git diff --check`.
- [ ] **T-1309 (@DevOps):** Русский conventional-commit, `git push`.
- [ ] **T-1310 (@DevOps):** Деплой: `git pull --ff-only`, `systemctl restart admin_bot`; `/api/health` = 200, 0 ERROR/Traceback.
- [ ] **T-1311 (@PM):** Plain-language отчёт владельцу (что изменилось, что стало лучше, что осталось).

---

## 4. Acceptance criteria (по пунктам)

| # | AC |
|---|---|
| 1 | «Персоны (ID)» разделены на Славика и Олю; параметры сгруппированы по владельцу едиными collapsible-блоками; в каждом блоке ровно ОДИН рабочий тумблер; дублей нет; тумблеры реально меняют поведение (проверено на живом Android). |
| 3 | После сохранения любого параметра позиция скролла сохраняется (не прыгает наверх). |
| 4 | Все 91 описаний групп и ~392 описаний параметров переписаны: просто, без жаргона/аббревиатур, без AI-паттернов, с иронией; пустых нет. |
| 5 | «Тяжёлые фичи» либо удалены (если дубль подтверждён), либо обоснованно оставлены; управление гейтами не потеряно. |
| 6 | «Бюджет фона» показывает реальные цифры (не нули) для чата/глобала ИЛИ перенесён в «Сводку» без дубля; функционал не утрачен. |
| 7 | Один блок «Доступность ключей», 4 группы функций, строки в заданном формате; хардкод имён убран; Health показывает реальный код/timeout (в т.ч. при падении apinet); «Название модели» — первое поле формы; ширина формы ограничена. |
| 8 | Фоновая градиент-анимация заметно (но не резко) быстрее; reduced-motion уважается. |
| + | README (v2.53.0, ирония) обновлён; русский commit; push; деплой; plain-language отчёт. |

---

## 5. QA / test plan

- **Python:** `py -m pytest tests/ -v` — baseline **5076**, цель 0 failed и +новые.
- **Синтаксис JS:** `node --check web/app.js`.
- **JS-юниты:** `node tests/js/routing_test.js` → `JS-UNIT-OK`.
- **Маркеры/парность:** `tests/test_webapp_key_availability_ui.py`, `test_webapp_round108_ui.py`, `test_webapp_api.py`, `test_status_service.py`, `test_font_subset.py` (если менялся каталог/иконки), `tests/test_round106_ia_smoke.py`, `test_webapp_back_button.py`.
- **Каталог-пины:** `REGISTRY/GROUPS/Settings/mapped/TAB_RULES/CONFIG_TAB_TITLES` — обновить синхронно при добавлении ParamSpec/GroupSpec.
- **Секреты:** grep `sk-/gsk_/AIza/xox/bot-token` по `git diff` — пусто.
- **Live Android (обязательно):** п.1 (блоки/тумблеры), п.3 (скролл), п.7 (dashboard/health/форма).
- **Совместимость:** `git diff --check`; `media/`/`bot.py` не тронуты.

---

## 6. Feature flags & progressive delivery

- **UI (п.1, 3–8):** фича-флаг не нужен — это UI/описания/статус; rollback = `git revert`. При желании — за существующими гейтами модулей, но декоративных флагов не вводить.
- **Один деплой-релиз** для UI. **Пункт 2 (инфраструктура IDE) — вне проекта** (feature flags не применяются).

---

## 7. Открытые вопросы (нужно решение @Architect / владельца)

> Вопросы по пункту 2 сняты — он вне скоупа проекта (см. §0).

1. **7.2:** где хранить «Название модели» — новые `models.*_display_name` ParamSpec (каталог 392→N, тесты-пины) или карта в коде/`bot_settings`? Как это отражается per-chat/BYOK?
2. **7.1 «Эмбеддинги»:** в `llm_registry()` нет эмбеддинг-провайдеров/их фоллбэков — какие ключи считать «main + two fallbacks» и как маскировать?
3. **7.1 Health:** какой тест считать «реальным» — `/models`, chat-completions или оба? Нужна ли отдельная индикация «timeout» vs «502»?
4. **п.1:** куда отнести общие параметры (общая мимикрия `reactions_mimic`, `reactions_permsoc`, `flags_media` common) — «Общее»-блок или к владельцу?
5. **п.5/п.6:** окончательное решение — удалить «Тяжёлые фичи» и перенести «Бюджет фона» в «Сводку» (зависит от подтверждения дублей).

---

## 8. Учёт аудита @Scanner (R10.8) — что включено

- Прочитан `plans/reports/round10.8_scanner_audit.md` (0 blocker / 0 major; minor R10.8-1/-5, info R10.8-2/-3/-4).
- **Учтено:** **R10.8-5** (`APP_VERSION` vs README + cache-bust субсета) → **T-1307** (поднять `APP_VERSION` до 2.53.0; `?v=__APP_VERSION__` уже есть `index.html:72`).
- **Учтено:** **R10.7-1/-2** (`services/status_service.py` gap-fill / health) пересекаются с п.7 → **T-1298**.
- **Учтено:** **R10.6-1** (дубль generic-рендера `llm_providers`) → **T-1304**.
- **Вне UI-скоупа 10.9 (кандидаты follow-up):** R10.8-1 (Esc не закрывает окна «Доступов» — `web/app.js:1023-1027`; 1-строчный фикс, можно взять при малой цене), R10.8-2 (stale-комментарий `section`), R10.8-3 (мёртвый `TABS[].icon`/`visibleTabs`/`tabMat`), R10.6-2/-3 (SSRF/422-эхо `api_key`).
- Инварианты 10.8 соблюдены (392/91/364, 0 PG-DDL, SQLite v8, `bot.py`/`media/` не тронуты) — 10.9 их сохраняет.

---

## 9. Статус реализации @Builder (12.09.2026)

**Сделано (UI-трек, код):** п.1 (PERMsoc owner-блоки + `SLAVIK_ENABLED`),
п.3 (скролл), п.4 (описания без жаргона — все `GroupSpec.description` и
`ParamSpec.description` проходят тест-маркер §4.2.2: запрещённых подстрок
нет, пустых нет; отдельный скан на AI-паттерны §4.2.3 — 0 совпадений),
п.5 (удаление дубля гейтов), п.6 («Бюджет фона» → «Сводка»),
п.7.1/7.2 (dashboard + реальный health + «Название модели» первым полем),
п.8 (градиент).
Каталог: **REGISTRY 400 / GROUPS 90 / Settings 372 / mapped 88 / TAB_RULES 19**.
Тесты: **5100 passed / 0 failed** (+24 к baseline 5076); `node --check` clean;
`node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check` clean.
Новый `tests/test_webapp_round109_ui.py` (18 тестов — все зелёные).
SQLite v8 / 0 PG-DDL / `bot.py` / `media/` не тронуты.
Секретов в `git diff` нет (grep пуст).

**Верификация @Builder (повторный прогон, 12.09.2026):** незакоммиченный
дифф проверен по пунктам 1, 3–8 — все реализованы; тесты-пины обновлены
синхронно (не ослаблены), каталог-инварианты сходятся; полный `pytest -q`
зелёный. Дополнительно закрыт пропуск п.1: read-only сводка 5 модулей
(она жила в удалённой мастер-карте) возвращена **внутрь** owner-блока
«Общее / Мастер» (`permsocModuleBadge` снова используется, не мёртвый код);
на это добавлен маркер-тест.

**Осталось (вне реализованной части):**
- **T-1307** (README v2.53.0 + `APP_VERSION`) — **не сделано** по прямому
  указанию заказчика («no README»); `APP_VERSION` оставлен `2.52.0`, чтобы
  не ломать `test_app_version_matches_readme`.
- QA/live-задачи (**T-1277, T-1290, T-1292, T-1294, T-1302, T-1305**) —
  за @QA (Android/сервер).
- **T-1309…T-1311** (commit/push/deploy/report) — по указанию заказчика не
  выполнялись (no commit/push).

---

## 10. Правки по ревью @Reviewer (12.09.2026)

Ревью забраковало раунд (1 Critical + 1 High + 2 Medium + 3 Low) — все устранены:

- **CRITICAL-1 (STT health):** `stt_groq` больше не пингуется как chat
  (`kind="stt"` → `POST {base}/audio/transcriptions`, multipart, минимальный
  WAV `_silent_wav`). `stt_openrouter` оставлен `kind="chat"` с обоснованием:
  его расшифровка идёт через `chat.completions` + `input_audio`
  (`openrouter_transcriber`) — отдельного STT-эндпоинта нет. Документировано
  в spec §7.1.2c и §10 (Q3). Тесты: `test_probe_stt_endpoint`,
  `test_registry_kind_stt_vs_chat` + маркеры в `test_webapp_round109_ui.py`.
- **HIGH-2 (AI-шаблон «Включает… Выключено…»):** переписаны 12 описаний
  (флаги) в короткие consequence-focused тексты. Маркер-тест
  `test_no_ai_template_pattern` (regex `включ\w*.*выключ`).
- **MEDIUM-3 (title_ru):** переписаны все 64 заголовка параметров и 5
  заголовков групп с запрещёнными подстроками (§4.2.2); ключи не тронуты.
  Тест §4.3 теперь проверяет и `title_ru`, и `description` — расхождение
  теста и spec устранено.
- **MEDIUM-4 (скролл TMA):** `_preserveScroll` снимает/восстанавливает оба
  скроллера — `document.scrollingElement` и `main.scroll-area`
  (`querySelector('.scroll-area')`, fullscreen). Обёрнуты `kv-editor.save`
  (`this.root._preserveScroll`) и `resetChatOverride` (+409-ветка).
- **LOW-5:** удалена недостижимая legacy-ветка в
  `status_service._model_from` (source уже даёт `_resolve`).
- **LOW-6:** `_permsocOwnerGroups` больше не фильтрует пустые owner-блоки;
  HTML рендерит `details`, даже если тело пустое. Маркер
  `test_all_four_owner_blocks_always_render`.
- **LOW-7:** JS-юниты в `tests/js/routing_test.js` — `_preserveScroll`
  (сохранение/восстановление `scrollTop` обоих скроллеров со stubbed
  `$nextTick`) и условие спиннера `configLoading && !configItems.length`.

**Итог:** `pytest -q` → **5105 passed / 0 failed**; `node --check web/app.js`
clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `git diff --check`
clean. Ссылок на инфраструктуру IDE в коде/тестах нет (только «out of scope» в планах).

**Дешёвые follow-up (закрыты):**
- `ADR-109.md` (ADR-109-3) дополнен решением про `stt`: `probe_openai`
  `kind="stt"` → `POST /audio/transcriptions` (multipart, тихий WAV);
  `stt_groq` → `"stt"`, `stt_openrouter` остаётся `"chat"` (расшифровка
  через `chat.completions` + `input_audio`). Синхронно с spec §7.1.2c/§10.
- `web/app.js` `_ownerDescription` Славика: «dead page» → «посты из старого
  канала» (без англ. жаргона).
- `services/status_service.py`: у `_model_from` удалён неиспользуемый
  параметр `settings_field` (3 call-site обновлены).
- `web/app.js` `resetPermPicker`: `loadConfig()` обёрнут в
  `_preserveScroll` (единый путь сохранения позиции скролла).

---

*План создан @PM 12.09.2026 (Step 1). Код не писался. **Пункт 2 (инфраструктура IDE) — вне скоупа проекта:** инструмент локального IDE владельца, не часть бота. Передача @Architect (дизайн п.1/п.7) и @Builder (реализация).*
