# F-13 — TMA: фиксы селектора чатов и интерфейса (раунд 10.3)

> Пересоздано @Architect 09.09.2026 по KG-канону сущности `feature-tma-chat-selector-fixes`
> (файл утрачен при реструктуризации 03.09.2026; дизайн и root-cause зафиксированы в KG).
> Пункты ТЗ владельца 1/2/3/5 → AC-1 / AC-2 / AC-3 / AC-5.
> База: HEAD `d30b203` (раунд 10.2), pytest 4760, прод PID 454654.
> ⚠️ Код НЕ пишется до этого файла (задачи T-934…T-938 — @Builder после spec).

## 1. Контекст

Мини-апп TMA (`web/index.html` 2135 строк, `web/app.js` 2927 строк, Vue3+Tailwind CDN zero-build)
получил в раунде 10 два инструмента выбора чата (нативный `<select>` + кнопка «💬 Выбрать чат»
с дропдауном), крестик принудительного закрытия Mini App, регрессию пустых конфиг-вкладок
(v-if/v-for) и перекрытие мобильного сайдбара шапкой. Все четыре дефекта подтверждены
реконами T-925…T-928 и исправляются фронтовыми правками (web/app.js + web/index.html +
маркер-тесты); `web/api/routes.py` в этой фиче НЕ меняется (протокол 84.5 — фронтовая правка).

## 2. Границы (НЕ трогать — diff-проверка в T-941)

- `bot.py`: порядок роутеров + гейт `flags.summary_enabled` (613-643) — без дифов;
- `services/chat_params.py` / `services/access.py` / `services/roles.py` — в ЭТОЙ фиче
  не меняются (их слой — F-14);
- `web/api/routes.py` — без дифов (пустая вкладка лечится фронтовой правкой);
- SQLite-схема; каноны `plans/docs/canon/`; `handlers/*`; `.env`; F-3 scam-followup T-663
  (admin_commands.py); кэш `hot_chat` TTL 120с/NOTIFY/409 (переиспользование, не инвалидация);
- LOW-012 (CSP) — вне скоупа; H3 (100dvh/viewportStableHeight) — вне скоупа (комментарий);
- MENU_ORDER (app.js:76-83) и TABS-структура — без изменений (AC-5).

## 3. Общие приёмки (NFR-5, все AC)

- `node --check web/app.js` — clean;
- полный pytest (≤300с, `.venv`) — 0 failed (база 4760 + обновлённые маркер-тесты,
  новые тесты F-14 в T-958);
- `git diff --check` — чист;
- ручные проверки в TMA (десктоп/мобилка): селектор один, крестика нет, вкладки
  рендерят группы в обоих скоупах (глобал и per-chat), «Статус» кликабелен после
  перехода в другой раздел и обратно.

---

## AC-1 — Единый селектор чата (пункт 1 ТЗ)

**Цель:** ровно ОДНА точка выбора чата; после выбора ВИДНО, какой чат выбран; компактно,
не мешает другим элементам шапки; селектор — единственная точка выбора для ВСЕХ вкладок
(конфиг-вкладки, «Реакции и триггеры», «Провайдеры», «Промпты», «Лимиты», «Памыть и RAG»,
«Функции PERMsoc», «Модули и Фичи»).

### 3.1. Что остаётся

- Нативный `<select>` (web/index.html:414-422) — ЕДИНСТВЕННЫЙ селектор:
  - условие показа `v-if="accessChats.length"` — БЕЗ изменений;
  - `@change="setActiveChat($event.target.value)"`, опции `c.title || ('Чат ' + c.chat_id)`,
    опция «Весь бот» при `isGlobalAdmin` — БЕЗ изменений (BUG-1-семантика: «Весь бот» —
    только глобальный админ; видимость при ≥1 чате);
  - **компактность**: убрать инлайн `style="min-width: 220px; max-width: 320px;"`,
    классы → `w-44 max-w-[280px]` (вместо `w-44 max-w-[200px]`; индикация title-опции
    остаётся полноценной — текст опции не обрезается CSS-шириной).
- Индикация выбора = значение селектора (текст выбранной опции) + компактный бейдж-дентификатор
  в шапке (взамен удаляемого бейджа-дубля):
  - `<span v-if="isChatContext()" class="badge badge-info shrink-0">#{{ activeChatId }}</span>`
    (после AC-1; в F-14 → «ЛС #{{ activeChatId }}» для DM-скоупа — см. F-14 §8);
  - бейдж — компактный (без `max-w-[160px]`/`truncate` — это был бейдж-дубль title).
- `activeChatTitle` / `syncActiveChatTitle` (index.html:945/1159, app.js:653-664) — СОХРАНЯЮТСЯ
  (используются в «Модули и Фичи» :945, :1159 и списке гейтов; ТЕСТ test_webapp_rbac_ui
  `test_chat_badge_in_header` — остаётся зелёным).

### 3.2. Что удаляется

| Объект | Файл:строки | Критерий |
|---|---|---|
| Кнопка «💬 Выбрать чат» | index.html:423-428 (div.relative + кнопка) | 0 вхождений «💬 Выбрать чат» в index.html |
| Дропдаун пикера | index.html:429-442 | `pickChat('')` / `pickChat(c.chat_id)` — 0 вхождений; строк нет |
| Стейт/методы `chatPickerOpen`, `openChatPicker`, `closeChatPicker`, `pickChat` | app.js:151, :675, :701-711 | grep по app.js: `chatPickerOpen` = 0, `openChatPicker` = 0, `pickChat` = 0 |
| Сброс стейта `this.chatPickerOpen = false;` внутри `setActiveChat` | app.js:675 | отсутствует (строка удаляется вместе с методом) |
| Бейдж-дубль `activeChatTitle` в шапке | index.html:444-446 | удаляется (заменяется бейджем `#{{ activeChatId }}`) |

### 3.3. Empty-states — переработка (без кнопки)

- **:519** (PERMsoc-карточка, блок «Без чата — только глобальные значения»): текст →
  «…выберите чат в селекторе в шапке»; кнопка «💬 Выбрать чат» удаляется.
- **:1006** (карточка PERMsoc в «Модули и Фичи»): тот же текст; кнопка удаляется.
- F-14 расширяет текст: «…выберите чат или Личные сообщения в селекторе в шапке» (F-14 §8).

### 3.4. Критерии приёмки AC-1

- index.html: ровно ОДИН select с `@change="setActiveChat($event.target.value)"`;
- «💬 Выбрать чат» / `openChatPicker` / `closeChatPicker` / `pickChat` / `chatPickerOpen` —
  0 вхождений (grep);
- бейдж `#{{ activeChatId }}` присутствует в шапке; `activeChatTitle` жив
  (index.html:945/1159, app.js:653-664; ТЕСТ test_webapp_rbac_ui не дифится);
- инлайн min/max-w у select удалены; класс `w-44 max-w-[280px]`;
- empty-states :519/:1006 — без кнопок, текст упоминает селектор;
- смена чата через select работает для всех вкладок (manual: переключить на каждую
  конфиг-вкладку после выбора — данные per-chat перерисованы; «Весь бот» — глобальные).

### 3.5. Негативные тесты AC-1 (что НЕ должно сломаться)

- «Весь бот» — опция существует ТОЛЬКО при `isGlobalAdmin` (BUG-1-тест :67-68 зелёный);
- селектор виден при `accessChats.length >= 1` (test_selector_visible_for_single_chat);
- `setActiveChat`/персист `adminbot.active_chat_id` — без изменений;
- «Лор чатов» (вкладка chat_lore) — свой рендер, выбор чата в её списке НЕ переводится
  на селектор (пересекающихся точек выбора нет; селектор — только шапка);
- BYOK-блок (:737) и «↪ глобальное» (:574-576/:679-681) не затронуты (в F-14 — расширение).

---

## AC-2 — Удаление крестика ✕ выхода (пункт 2 ТЗ)

**Цель:** убрать принудительный выход из Mini App; полноэкранный режим и мобильный
клозер сайдбара остаются.

### 4.1. Удаляется

- Кнопка `<button ... @click="closeApp()">✕</button>` — index.html:460-461;
- Метод `closeApp` — app.js:1180-1191.

### 4.2. НЕ трогается

- ⛶ `toggleFullscreen` — index.html:457-459, app.js:1193-1207;
- мобильный ✕ сайдбара — index.html:376-378 (`@click="sidebarOpen = false"`).

### 4.3. Критерии приёмки AC-2

- `closeApp` в app.js — 0 вхождений; `@click="closeApp()"` в index.html — 0;
- `toggleFullscreen` присутствует (grep ≥1); `>⛶</button>` присутствует;
- `>✕</button>` в index.html — ровно 1 (мобильный сайдбар);
- других вызовов closeApp в `web/*` нет (grep всей директории web/).

---

## AC-3 — Пустые конфиг-вкладки (пункт 3 ТЗ)

**Root cause (подтверждён T-927, регрессия `d30b203` из-за BUG-5-фикса «(0)»):**
Vue 3 v-if/v-for precedence — `v-if="basicItems(grp).length || advancedItems(grp).length"`
на ОДНОМ узле с `v-for="grp in currentTabGroups"` (index.html:551-552): v-if вычисляется
вне скоупа цикла → `grp == undefined` → `basicItems(undefined) == []` → условие всегда
false → ВСЕ конфиг-группы схлопываются → вкладки «Реакции и триггеры»/«Провайдеры»/
«Промпты»/«Лимиты» пустые для ЛЮБОЙ роли и в любом скоупе.

### 5.1. Фикс (шаблон)

- Узел v-for → `<template v-for="grp in currentTabGroups" :key="grp.uid">` (без v-if),
  v-if переносится на дочерний div с `class="card p-4 col-span-full"`:
  - дочерний div несёт `v-if="basicItems(grp).length || advancedItems(grp).length"`;
  - `groupedForTab` (app.js:1462-1464) УЖЕ фильтрует пустые группы — вторичный фильтр
    остаётся (дефенсив, BUG-5-семантика «нет карточек (0)»);
  - `:key="grp.uid"` — на элементах внутри (или на template — по Vue 3, допустимо;
    предпочтительно на дочернем div рядом с :key, но НЕ дублируя);
  - вложенные v-for по item (basic/advanced), `<details class="advanced">` и все кнопки
    карточки — БЕЗ изменений; закрытие div-карточки (index.html:731) сохраняется.
- Комментарий :559-562 скопирован из хотфикса 10.1 (там блоки БЕЗ v-for — валидно);
  при правке — поправить комментарий под новую структуру (v-if на дочернем узле).

### 5.2. Вторичное звено — configError-баннер (MED-021)

Молчаливый 403/ошибка в `loadConfig` (app.js:1373-1380) не даёт понять, почему
вкладка пустая. Фикс:

- новое состояние `configError: ''` (data);
- в `loadConfig.catch`: `e.status === 401` → существующий toast (БЕЗ изменений);
  `e.status !== 403` → существующий toast (БЕЗ изменений); **403** → `configError`
  («нет доступа к параметрам этого чата — выберите другой чат или глобальный режим»);
  503 → `configError` («PostgreSQL недоступен — попробуйте позже»); сеть/прочее →
  `configError` (кратко) вместо/в дополнение к тосту (тост остаётся как есть);
- рендер: баннер-карточка наверху конфиг-вкладок (рядом с поиском :541-544)
  при `configError`, с кнопкой «⟳ Повторить» (`this.configError=''; this.loadConfig()`)
  и «✕» скрыть; `configError` очищается при успешной `loadConfig` и при `setActiveChat`;
- при 403 в chat-скоупе юзер видит баннер, а не «пустую вкладку» (пустые группы
  теперь невозможны — но баннер объясняет отказ сервера).

### 5.3. Критерии приёмки AC-3

- `currentTabGroups`-рендер: на узле v-for НЕТ v-if (негатив: двухстрочная конкатенация
  `<div v-for="grp in currentTabGroups" :key="grp.uid"` + `v-if="basicItems(grp)..."`
  НЕ присутствует в index.html);
- `<template v-for="grp in currentTabGroups"` присутствует; дочерний div несёт
  `v-if="basicItems(grp).length || advancedItems(grp).length"` (выражение то же);
- группы рендерятся в ручных проверках: глобал-скоуп и per-chat скоуп,
  роли user (read-only) / local_admin / global — вкладки «Реакции и триггеры»,
  «Провайдеры», «Промпты», «Лимиты», «Память и RAG» открываются и показывают группы;
- BUG-5-поведение сохранено: пустая группа НЕ рендерится («(0)»-карточек нет);
- configError-баннер виден при фейке 403 (manual: временно вернуть 403 в любимой
  инструментальной проверке ИЛИ ручная проверка в роли без прав) — и после выбора
  другого чата исчезает; 401-тост как есть.

### 5.4. Негативные тесты AC-3

- Фичи не сломались: «Доступы» (access), «Лор чатов» (chat_lore), «Статус», «Как это
  работает», Oversight — другие ветки шаблона (v-else-if) без дифов;
- generic-рендер :545-731 используется всеми конфиг-вкладками — правка шаблона
  общая и не разрушает «Фичи/Параметры/Ключи» (это те же вкладки, не новые блоки);
- маркер `test_frontend_tab_mapping` / `test_webapp_tma_fixes_ui` — без изменений
  (TABS/TAB_RULES не тронуты).

---

## AC-5 — «Статус» недоступен (пункт 5 ТЗ)

**Root cause (подтверждён T-928):** мобильный `.sidebar` (index.html:346-350, media ≤768px)
`position:fixed; z-index:40` == `.header-sticky z-index:40` (:328-331); sidebar в DOM ПЕРВЫЙ,
header ПОЗЖЕ → шапка (rgba 0.96) рисуется ПОВЕРХ верха сайдбара = бренд + секция «Главная»
+ пункт «📊 Статус» (always:true, menu:'home', app.js:65-66); `setTab` (app.js:1120)
закрывает сайдбар → при повторном открытии перекрытие повторяется.

### 6.1. Фикс (CSS)

- В media-правиле (index.html:346-359) для `.sidebar`: `z-index: 45;`
  (> header 40; < модалки 50 (:283), тосты 60 (:255); > backdrop 35 (:358));
- `env(safe-area-inset-top)` аддитивно (H1-safe-area):
  - `.sidebar` в media-правиле: `padding-top: calc(0.75rem + env(safe-area-inset-top, 0px))`
    (база 0.75rem = существующий `p-3`; НЕ затирать класс-паддинг);
  - `.header-sticky`: `padding-top: calc(0.75rem + env(safe-area-inset-top, 0px))`
    (база 0.75rem = `py-3`); правило — в media-правиле (мобильный контекст).
- Десктоп: `.sidebar` — `md:sticky` (в потоке, слева от контента, без fixed) —
  перекрытия с шапкой нет; существующий классный слой НЕ трогаем (md-стек без z-index).
- Без изменений: `menu_labels`, TABS, MENU_ORDER (app.js:76-83), `setTab`-логика
  закрытия сайдбара (app.js:1120) — кэнон F-11.

### 6.2. Критерии приёмки AC-5

- `.sidebar { z-index: 45; }` присутствует (в media-правиле);
- `.header-sticky z-index: 40` — без изменений (маркер-тест test_sticky_header_class
  остаётся зелёным: «z-index: 40» в html — header);
- safe-area-инъекция аддитивна: `calc(0.75rem + env(safe-area-inset-top, 0px))`,
  НЕ литеральные px-замены вступающие в конфликт с p-3/py-3 (px-захошия отсутствует);
- MENU_ORDER/TABS — без дифов; `setTab` — без дифов;
- manual (TMA/мобилка): открыть сайдбар → «📊 Статус» кликабелен и открывает вкладку;
  перейти в другой раздел, вернуться (setMenu('home')/кнопка «Статус») — работает
  повторно; внутри сайдбара скролл прокручивается (overflow-y:auto сохранён).

### 6.3. Негативные тесты AC-5

- модалки (z-50) и тосты (z-60) рисуются ПОВЕРХ сайдбара (45 < 50/60 — без изменений);
- backdrop (z-35) остаётся ПОД сайдбаром;
- десктоп: сайдбар sticky, шапка sticky — визуально и по тестам без дифов.

---

## 7. Обновление маркер-тестов (MED-022)

| Файл | Изменение |
|---|---|
| `tests/test_webapp_nav_disclosure_ui.py` | `test_chat_picker_button_and_dropdown` (70-79) → `test_single_chat_selector_only`: нет openChatPicker/chatPickerOpen/pickChat/«💬 Выбрать чат»; есть `setActiveChat`+`$event.target.value`, `v-if="accessChats.length"`, «Весь бот», `#{{ activeChatId }}`; `test_group_card_skipped_when_empty` (110-122): ПОЗИТИВ `<template v-for="grp in currentTabGroups">` + `v-if="basicItems(grp).length \|\| advancedItems(grp).length"` (на дочернем узле, выражение сохраняется), НЕГАТИВ — двухстрочная конкатенация v-for+v-if на одном узле НЕ присутствует; `test_selector_visible_for_single_chat` — без изменений |
| `tests/test_webapp_avatars_ui.py` | `test_close_app_method` (204-210) → `test_no_close_app_method` (closeApp не в методах app.js); `test_close_and_fullscreen_buttons` (394-402): ✕ count == 1 (только сайдбар), ⛶ остался, `toggleFullscreen` есть; `test_sticky_header_class` (404-409) — без изменений + доп. маркер `z-index: 45` (sidebar) |
| `tests/test_webapp_rbac_ui.py` | `test_chat_badge_in_header` — БЕЗ изменений (activeChatTitle жив); при желании — бейдж `#{{ activeChatId }}` в маркеры |
| `tests/test_frontend_tab_mapping.py`, `tests/test_webapp_tma_fixes_ui.py` | без изменений |
| `tests/test_webapp_dm_ui.py` | НОВЫЙ — создаётся в T-958 (F-14); в этой фиче только набросок: селектор + DM-запись |

## 8. Связи с другими фичами

- **F-14 `dm-user-settings`** — поверх AC-1: запись «Личные сообщения» в единый селектор,
  бейдж «ЛС #{id}», empty-state «…или Личные сообщения…», canViewTab DM-правило (§8 F-14).
  F-13 выполняется ПЕРВОЙ (единый селектор — необходимое условие DM-записи).
- **F-4 `frontend-admin-bugfixes`** — Баг 4 («сверка синхронизации разделов») — тот же
  рендер-зон конфиг-вкладок → порядок: F-13 ДО Бага-4 (конфликт шаблона).
- **F-1 / F-3 / F-5 / F-6 / F-2** — пересечений нет (границы выше).

## 9. Приёмка (метрики)

- `node --check web/app.js` clean; полный pytest 0 failed; `git diff --check` чист;
- grep-проверки: «💬 Выбрать чат» 0, `closeApp` 0, `chatPickerOpen` 0, `openChatPicker` 0,
  `pickChat` 0 (web/); `toggleFullscreen` ≥1, `>`✕`</button>` == 1;
- ручные: все 6 проверок ТЗ (п.1-6 live-верификации T-944).
