# Задачи: tma-chat-selector-fixes (F-13)

> Раунд 10.3, пункты 1/2/3/6 ТЗ владельца (AC-1 / AC-2 / AC-3 / AC-5).
> База: HEAD `d30b203` (раунд 10.2, задеплоен), pytest 4760, прод PID 454654.
> Спецификация: `spec.md` — **пересоздаёт @Architect** по KG-канону (файлы утрачены
> при реструктуризации 03.09.2026; дизайн зафиксирован в наблюдениях сущности
> `feature-tma-chat-selector-fixes`). ⚠️ Никто не пишет код в этой фиче раньше
> пересозданного spec.md.
> Порядок исполнения: реконы (done) → spec @Architect → AC-1 → AC-2 → AC-3 → AC-5
> (обычные циклы @Builder) → @Reviewer → @Scanner → общая финальная фаза
> T-941…T-944 (ОДНА на раунд 10.3, исполняется ОДНОКРАТНО ПОСЛЕ F-14).

## Рекон-база (@PM, подтверждено — переотражено из KG)

- [x] **T-925** — рекон AC-1: дубль выбора чата. Двойной UI в шапке:
  нативный `<select>` (web/index.html:414-422, `style="min-width: 220px; max-width: 320px;"`,
  классы `w-44 max-w-[200px]`) + кнопка «💬 Выбрать чат» (:426-428) + дропдаун
  `v-if="chatPickerOpen"` (:429-442) + бейдж-дубль `activeChatTitle` (:444-446);
  empty-states с кнопкой «💬 Выбрать чат» → :519 (permsoc-блок) и :1006 (модули);
  методы `openChatPicker`/`closeChatPicker`/`pickChat` + стейт `chatPickerOpen`
  (web/app.js:151, 675, 702-711).
- [x] **T-926** — рекон AC-2: ✕ `closeApp` (web/index.html:460-461,
  web/app.js:1180-1191) — принудильный выход из Mini App; ⛶ `toggleFullscreen`
  (app.js:1193-1207, index.html:457-459) НЕ трогать; ✕ сайдбара (index.html:376-378,
  `sidebarOpen = false`) — мобильный клозер панели, НЕ трогать.
- [x] **T-927** — рекон AC-3 (root cause ПОДТВЕРЖДЁН эмпирически): Vue 3
  v-if/v-for-precedence — `v-if="basicItems(grp).length || advancedItems(grp).length"`
  на ОДНОМ узле с `v-for="grp in currentTabGroups"` (web/index.html:551-552);
  в Vue 3 `v-if` вычисляется вне скоупа цикла → `grp == undefined` →
  `basicItems(undefined) == []` → условие всегда false → **все** конфиг-группы
  схлопываются → вкладки «Реакции и триггеры»/«Провайдеры»/«Промпты»/«Лимиты»
  пустые для ЛЮБОЙ роли и в любом скоупе. Регрессия внесена в `d30b203`
  (фикс 10.2 BUG-5 «(0)»; до него v-if не было). Комментарий :559-562 скопирован
  из хотфикса 10.1 (там блоки БЕЗ v-for — валидно).
- [x] **T-928** — рекон AC-5: мобильный `.sidebar` (web/index.html:347-350,
  media ≤768px) `position:fixed; z-index:40` == `.header-sticky` `z-index:40`
  (:328-331); sidebar в DOM первый, header ПОЗЖЕ → шапка (rgba 0.96) рисуется
  ПОВЕРХ верха сайдбара = бренд + дочерние меню «Главная» + «Статус»
  (always:true, menu:'home', app.js:65-66); `setTab` (app.js:1120) закрывает
  сайдбар → при повторном открытии перекрытие повторяется — «Статус»
  недостижим. `sidebar-backdrop` z-index:35 (:358), модалки 50 (:283), тосты 60 (:255).

## Спецификация (@Architect — пересоздание по KG-канону)

- [ ] **T-929** — spec AC-3 (пустые вкладки): фикс `<template v-for>` + v-if на
  дочернем узле; `groupedForTab` уже фильтрует пустые группы (app.js:1462-1464);
  вторичное звено — configError-баннер на молчаливый 403 (app.js:1373-1380, MED-021).
- [ ] **T-930** — spec AC-1 (единый селектор): остаётся ТОЛЬКО нативный `<select>`
  (компактный: убрать инлайн `min/max-w`, классы `w-44 max-w-[280px]`);
  индикация выбора = значение селектора + компактный бейдж `#{activeChatId}`
  (DM: «ЛС #{id}»); `activeChatTitle`/`syncActiveChatTitle` СОХРАНЯЮТСЯ
  (index.html:945/1159); empty-states :519/:1006 → текст «…выберите чат в
  селекторе в шапке» (без кнопки).
- [ ] **T-931** — spec AC-2 (крестик): удалить `closeApp` (index.html:460-461 +
  app.js:1180-1191); grep-проверка других вызовов; `toggleFullscreen` и ✕ сайдбара —
  без изменений.
- [ ] **T-932** — spec AC-5 («Статус»): `.sidebar { z-index:45; }` в media-правиле
  (между header 40 и modal 50; backdrop 35) + аддитивное `env(safe-area-inset-top)`
  на `.header-sticky`/`.sidebar` (H1-safe-area); MENU_ORDER (app.js:76-83)/TABS —
  без изменений; H3 (100dvh/viewportStableHeight) — вне скоупа (комментарий).
- [ ] **T-933** — spec: план обновления маркер-тестов (медиум MED-022) + протокол
  приёмки (NFR-5): `node --check web/app.js`, полный pytest, ручные проверки.

## Реализация (@Builder — после spec.md)

- [ ] **T-934** — AC-1: удалить кнопку «💬 Выбрать чат» + дропдаун + бейдж-дубль
  (`openChatPicker`/`closeChatPicker`/`pickChat`/`chatPickerOpen` — app.js:151/675/702-711);
  ↓ критерии: в index.html ровно ОДИН select-селектор чата (условие
  `accessChats.length`): нативный `<select>` компактный (без инлайн min/max-w,
  `w-44 max-w-[280px]`), `@change="setActiveChat($event.target.value)"`,
  опции `c.title || ('Чат ' + c.chat_id)`; кнопок «💬 Выбрать чат» НЕТ (0 вхождений);
  `chatPickerOpen`/`openChatPicker`/`pickChat` отсутствуют в app.js;
  бейдж `#{activeChatId}` → `#{{ activeChatId }}` в шапке (или title-подсказка
  по дизайну spec); empty-states :519/:1006 — без кнопки, текст с упоминанием
  селектора; `activeChatTitle` жив (не удалён ни в index.html, ни в app.js).
- [ ] **T-935** — AC-2: удалить ✕ `closeApp` (index.html:460-461 + app.js:1180-1191);
  ↓ критерии: `closeApp` отсутствует в app.js (grep = 0); ⛶ `toggleFullscreen`
  осталась (app.js:1193-1207, индекс 457-459); ✕ мобильного сайдбара остался
  (index.html:376-378); других вызовов closeApp в web/* нет.
- [ ] **T-936** — AC-3: `<template v-for="grp in currentTabGroups">` + `v-if` на
  дочернем узле (index.html:551-552); ↓ критерии: на узле v-for-шаблона НЕТ
  `v-if`; дочерний div несёт `v-if="basicItems(grp).length || advancedItems(grp).length"`
  и `:key="grp.uid"`; группа/секции рендерятся в обоих скоупах (глобал и per-chat)
  для ролей user/local_admin/global (проверка вручную в TMA); вторично —
  configError-баннер на 403/503/сетевую ошибку в loadConfig (app.js:1373-1380);
  ↓ критерий: баннер виден при фейке 403 (manual), 401-тост как есть.
- [ ] **T-937** — AC-5: `.sidebar { z-index:45; }` в media-правиле + `env(safe-area-inset-top)`;
  ↓ критерии: CSS z-index:45 для .sidebar (между 40 header и 50 modal);
  `.header-sticky` z-index:40 без изменений; safe-area-инъекция аддитивна
  (px-захошия отсутствует); MENU_ORDER/TABS без дифов.
- [ ] **T-938** — обновление маркер-тестов (MED-022): `test_webapp_nav_disclosure_ui.py` —
  `test_chat_picker_button_and_dropdown` (70-79) → `test_single_chat_selector_only`
  (нет openChatPicker/chatPickerOpen/pickChat/«💬 Выбрать чат»; есть setActiveChat/
  `$event.target.value`, `v-if=accessChats.length`, «Весь бот», `#{activeChatId}`)
  и `test_group_card_skipped_when_empty` (110-122; негатив: v-for+v-if на одном
  узле — точная двухстрочная конкатенация); `test_webapp_avatars_ui.py` —
  `test_close_app_method` (204-210) → `test_no_close_app_method` и
  `test_close_and_fullscreen_buttons` (394-402: ✕ count == 1 только сайдбар,
  ⛶ остался, toggleFullscreen есть); `test_webapp_rbac_ui` (`test_chat_badge_in_header`)
  — оставить (activeChatTitle жив); НОВЫЙ `tests/test_webapp_dm_ui.py` (общая точка
  F-13+F-14, создаётся в T-958 F-14 — здесь только набросок-стабы не понадобятся);
  `test_frontend_tab_mapping`/`test_webapp_tma_fixes_ui` — без изменений.
  ↓ критерии: `node --check web/app.js` clean; маркер-тесты зелёные; полный pytest
  0 failed.

## Ревью и сканирование

- [ ] **T-939** — @Reviewer: полный ревью диффов на соответствие spec.md + границы
  (см. ниже); APPROVED без блокеров.
- [ ] **T-940** — @Scanner: выборочный аудит фичи (web/*-файлы, маркер-тесты);
  находки — в отчёт plans/reports/, блокеры — закрыть до финала.

## Общая финальная фаза раунда 10.3 (T-941…T-944 — ОДНА на раунд, после F-14)

- [ ] **T-941** (AC-6) — конфликт-проверка: полный pytest (≤300с, .venv) 0 failed
  (4760 + новые); целевые проверки: порядок роутеров bot.py — без дифов; F-3
  `scam-incident-security-followup` (admin_commands.py без дифов; T-663 остаётся
  ОТКРЫТОЙ); param_permissions/DEFAULT_MATRIX — дефолты целы; кэш hot_chat
  (TTL 120с/NOTIFY/409-оптимизм) без инвалидаций; SummaryScheduler (ЛС не в
  smart-чатах); DM-команды /clear /persona /tone /forget — без дифов;
  gates/permsoc/worker_budget — не затронуты; `git diff --check` чист.
- [ ] **T-942** (AC-7) — README: ироничный абзац (прецедент «бот взял себя в руки»,
  хотфикс 10.1), счётчик тестов, строки версии.
- [ ] **T-943** (AC-8) — коммит master: русский conventional (fix(admin,web,api…)),
  grep секретов (`api[_-]?key|token|secret|password` + значения из контекста — R17),
  `git diff --check`, полный pytest; планы/README — тем же коммитом (прецедент D123).
- [ ] **T-944** (AC-9) — деплой: ssh nik@198.46.175.136 (пароль интерактивно/
  sshpass; в планы НЕ писать — R17; осторожно fail2ban maxretry=3), `git pull
  --ff-only`, .env при необходимости, `systemctl restart admin_bot`, status active,
  journal чист; live-проверка пунктов 1-6 ТЗ (селектор один, крестика нет,
  вкладки открываются, «Статус» кликабелен, DM-настройки — саммари OFF по
  умолчанию, правка параметров юзером, наследование).

## Границы (НЕ трогать — diff-проверка в T-941)

- bot.py: порядок роутеров + гейт `flags.summary_enabled` (613-643);
- `services/chat_params.py` / `services/access.py` / `services/roles.py` — в ЭТОЙ
  фиче не меняются (их слой — F-14);
- `web/api/routes.py` (AC-3 — фронтовая правка, протокол 84.5);
- SQLite-схема; каноны `plans/docs/canon/`; `handlers/*`; `.env`;
- F-3 scam-followup T-663 (admin_commands.py); кэш hot_chat TTL 120с/NOTIFY/409
  (MED-007/008 — переиспользование, не инвалидация);
- LOW-012 (CSP) — вне скоупа.
