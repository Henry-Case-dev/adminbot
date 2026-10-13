# D07-остаток — global-view popover переопределивших чатов + quick actions + bulk confirm (ASAP 8 v6, Wave C, P0)

Lane W-C-D07 · HEAD base 8700628 · дата 14.10.2026 · writer-лейн, БЕЗ коммита.

## Контракт

v6 §C D07 + v5 §9B.2/§9B.3 (U11/U12): global view — avatar stack `[чат A] [чат B] [+N]`
у параметра с overrides; клик → popover со списком переопределивших чатов и их значениями
(§9B.2: «Chat A: OFF, Chat B: model=X, Chat C: timeout=...»); quick actions — «Открыть
настройки чата» (deep-link), «Отключить в этом чате» (пишет ТОЛЬКО chat override),
«Вернуть глобальные» (удаляет ТОЛЬКО chat override; global value не меняется); bulk —
только через explicit confirm с перечислением affected chats; D01-гонки применены
(scope/цель захватываются до await); backend отдаёт список только по доступным текущему
админу чатам (RBAC), секреты не возвращаются никогда (R17); мобильная компоновка 390px
без перекрытия контролов.

База из F5 (модель `value`/`chat_source`/`global_value` + badge/source-label/«Вернуть
глобальные» в chat scope) не тронута — работаем поверх.

## Изменения

### Backend — `web/api/routes.py`

Новый read-only `GET /api/config/overrides-map?key=<опционально>`:

- SQL `OVERRIDES_FOR_USER_SQL`: `chat_profiles` (строки с непустым `overrides`) LEFT JOIN
  `chat_admins` по текущему `telegram_id` — гранты считаются на сервере.
- RBAC-видимость строки: global admin → все группы; chat-grant local_admin/moderator →
  свой чат; ЛС (положительный id, F-14) → ТОЛЬКО свои (чужие ЛС не видит никто, включая
  global admin). Настройки чатов без гранта не утекают (skip до выдачи).
- Гейт «не-админ → 403»: `access_srv.can_access_chat(ctx)` ИЛИ пустая выдача → 403
  (plain user rank 1 без грантов/своих строк). Локальный админ с грантом видит СВОЙ чат,
  а не 403 (гейт применён ПОСЛЕ построения видимого списка). Глобальный moderator →
  200 с пустым списком (паритет с `/api/access/chats`).
- Каталог-фильтр: только `per_chat`-ключи; hidden/вне-каталога/`keys.*` — не отдаются
  (легаси-мусор в chat_params наружу не идёт). Секреты отфильтровываются конструктивно
  (per_chat исключает secret); `_mask_secret` оставлен как defense-in-depth. R17: секреты
  не возвращаются никогда — зафиксировано тестом.
- Форма строки: `{key, chat_id, chat_title, value, source:'chat', access, is_dm}`;
  `chat_title` — `chat_display_info` (кэш 1ч, best-effort), ЛС → «Личные сообщения»,
  фолбэк `Чат {id}`. Без `key` — все ключи (стеки на карточках), с `key` — один ключ
  (popover карточки).
- PG down / ошибка чтения → 503 (fail-closed, не пустой список).

Owner-contract «глобальный save никогда не переписывает chat override» усилен пином:
`_post_config_global` физически не имеет доступа к `chat_params` (тест-пин на исходник).

### Frontend — `web/app.js`

- `api()`: аддитивная опция `chatId` — явный X-Chat-Id popover-действий СТАРШЕ активной
  области (в global view `activeChatId==null`, но контракт явный: действие адресует
  конкретный чат). Прежнее поведение (activeChatId/global:true) байт-в-байт.
- data: `overrideMap[]`, `overrideMapBusy`, `overrideBusy{}` (ключи `key:chatId`,
  `all:key`).
- `loadConfig` (global scope) → `loadOverrideMap()` (D01: epoch-снимок до await,
  `_scopeGuard` после; устаревший ответ/ошибка не мутируют UI); в chat scope карта
  очищается (стек — только global view; badge chat scope из F5 как был).
- Методы: `overrideRowsFor`, `formatOverrideValue` (bool→ON/OFF, объект→JSON, обрезка 60),
  `overrideCanWriteRow` (паритет с серверным гейтом DELETE: global_admin/local_admin/dm),
  `overrideRowBusy`, `openOverrideChatSettings` (deep-link: `setActiveChat` — параметр
  перечитывается в скоупе чата на текущей config-вкладке), `disableOverrideInChat`
  (POST /api/config c chatId, value=false, confirm), `resetOverrideInChat`
  (DELETE /api/config/chat/<key> c chatId, confirm), `resetAllOverridesInChats`
  (bulk: explicit confirm С ПЕРЕЧИСЛЕНИЕМ affected chats; без confirm — ноль записей;
  epoch-гвард на весь цикл — смена scope прерывает остаток; флаг busy снимается и при
  abort).
- Компонент `override-stack` (props itemKey/itemTitle/itemType): стек `[A][B][+N]`,
  popover со списком чатов/значений и quick actions; «Отключить в чате» — только для
  bool (§9B.3 «если применимо») и строк с правом записи. Клик мимо/Escape закрывают.

### Шаблон — `web/index.html`

- `#override-stack-tpl` (x-template, zero-build): стек + панель.
- Подключение в карточках generic-сетки (basic `permsocRenderItems`/basicItems и
  advanced `advancedItems`) рядом с бейджами «чат»/«скрыт».

### Геометрия панели (важное решение)

Первая версия — absolute внутри карточки — НЕЖИЗНЕСПОСОБНА: `.card` создаёт stacking
context (backdrop-filter), поэтому панель с любым z-index всегда оказывалась ПОД
постоянным sticky-save (z5) — кнопки действий перехватывались футером (воспроизведено
Playwright: «sticky-save intercepts pointer events»). Итог: панель — `<teleport to="body">`,
`position:fixed`, z80, позиция по rect кнопки (`computePos`: не вылезает за viewport
по горизонтали, мало места снизу → раскрытие вверх); scroll/resize → перепозиционирование
(не закрытие — иначе гонка с programmatic scrollIntoView закрывает только что открытую
панель; воспроизведено), закрытие только когда якорь ушёл из вьюпорта. Клики мимо/Escape
закрывают; клик внутри панели (teleport) НЕ считается «мимо».

Tailwind-классы панели — только уже скомпилированные в `web/static/vendor/tailwind.css`
(сверено по файлу); геометрия (fixed/width/z/shadow) — inline style. Пересборка Tailwind
не требуется.

## Тесты

Новые:
- `tests/test_asap8_v6_d07_overrides.py` — 11 тестов (TestClient + ConfigCache-стаб,
  эмуляция LEFT JOIN chat_admins):
  `TEST-LIFECYCLE: CONTRACT owner=D07 (web/api/routes.py::config_overrides_map)`
  | Тест | Покрывает |
  |---|---|
  | global_admin_sees_all_chats_and_own_dm | все группы + свои ЛС; чужие ЛС (1312) и чат без override отсутствуют; source='chat'; секрет и не-per_chat легаси НЕ отдаются (R17); access/title |
  | key_filter_returns_only_requested_key | `?key=` — только заданный ключ |
  | plain_user_403 | не-админ → 403 |
  | plain_user_own_dm_override_visible | F-14: свои ЛС видны, чужие — нет |
  | plain_user_without_own_rows_403 | без грантов и строк → 403 |
  | local_admin_grant_sees_only_his_chat | chat-grant: свой чат виден, чужой — нет |
  | global_moderator_sees_nothing | moderator → пустой список (паритет access/chats) |
  | pg_down_503 / query_failure_503 | fail-closed 503 |
  | overrides_rows_never_leak_other_chats_for_dm_owner | запрос идёт с telegram_id текущего пользователя |
  | owner_contract_global_save_never_touches_chat_override | пин: `_post_config_global` без chat_params/set_chat_params |
- `tests/js/asap8_v6_d07_override_stack_test.js` — 9 секций: D01-гвард карты (stale
  ответ не применяется; R3-семантика busy), overrideRowsFor-группировка, OFF/ON/JSON/
  обрезка формата, reset = DELETE только chat (глобальный POST не вызывается; отказ
  confirm → ноль записей; moderator-строка без действий), disable = POST только chat
  value=false, deep-link setActiveChat, bulk (confirm с перечислением, только writable,
  отказ → ноль, смена scope посреди цикла прерывает остаток + busy снят), api() chatId
  старше активной области (и обратная совместимость), computed компонента
  (stack 2+N, canDisable только bool, writableRows без moderator, close перед action).
  `TEST-LIFECYCLE: CONTRACT owner=D07`

Существующие settings-тесты правок НЕ требовали (обоснование: `api()` — аддитивная
ветка только при явном `chatId`; loadConfig — аддитивный вызов в global-ветке;
badge/source-label chat scope из F5 не тронуты). Прогнано: `test_budget_global_toggle*
round1024`, `test_budget_settings_round1019`, `test_budget_overrides_merge_round1024`,
`test_budget_data_repair_round1024`, `test_chat_settings_seed_round1019`,
`test_settings_helpers`, `test_settings_persistence_round1014`,
`test_webapp_api`, `test_asap7_module_completeness`, `test_asap8_f5_module_truth` —
**378 passed**. JS: полный сьют `tests/js` — **75/75 OK** (вкл. `vue_mount_test` —
монтирование реального Vue с новым x-template/teleport; `node --check web/app.js` OK).

## UI-доказательство (Playwright, deterministic)

Харнесс: scratch `OPENCODE_WORKFLOW_SCRATCH/adminbot-ccef72c25768/d07_ui_check.py`
(локальный статик-сервер web/ + моки /api/*; TMA-stub). **25/25 PASS**:

- Desktop 1280×800: стек рендерится `[P][Ф][+1]`; popover — 3 строки с значениями
  (ON/OFF/custom), quick-кнопки, bulk; Escape закрывает; «Вернуть глобальные» → ровно
  один DELETE `/api/config/chat/<key>` с X-Chat-Id целевого чата, глобального POST нет;
  «Отключить в чате» → POST /api/config с X-Chat-Id чата, `items=[{key, value:false}]`;
  «Настройки чата» → scopeKind=chat, activeChatId=-100, последующий GET /api/config ушёл
  с X-Chat-Id=-100; bulk → 3 DELETE с chat-заголовками (confirm auto-accept).
- Mobile 390×844: панель полностью во вьюпорте (x≥0, right≤390), ширина ≤366, кнопки
  действий кликабельны (в вьюпорте без скролла), клик мимо закрывает.
- Скриншоты: `d07_desktop_global_stack.png`, `d07_desktop_popover.png`,
  `d07_desktop_chat_scope.png`, `d07_mobile_popover.png` (в scratch-каталоге лейна).

Визуальная окрестность: панель читаема на стекле, строки/значения контрастны, кнопки
не обрезаются; sticky-save и мобильная bottom-nav панель НЕ перехватывают (teleport z80).
Чужих визуальных дефектов вокруг зоны изменений не обнаружено; дефект «панель под
футером» был в собственном первом варианте и устранён в этой же волне.

## Acceptance

| Пункт | Статус | Доказательство |
|---|---|---|
| Backend: список override только для заданного ключа; RBAC 403; маскировка/непопадание секретов; чужой чат не виден | PASS | 11 backend-тестов (таблица выше); R17-тест |
| UI: avatar stack; popover список | PASS | Playwright desktop (stack/+1/popover 3 строки) + скриншоты |
| «Вернуть глобальные» удаляет ТОЛЬКО chat override (global до/после одинаков) | PASS | JS-тест (глобальный POST не вызывается) + Playwright (единственный DELETE с chat-заголовком, `reset_no_global_write`) |
| «Отключить в этом чате» пишет только chat | PASS | JS-тест + Playwright (POST c X-Chat-Id, value=false) |
| Deep-link открывает настройки чата | PASS | Playwright (scopeKind=chat, activeChatId, X-Chat-Id на конфиге) |
| Bulk с confirm и перечислением | PASS | JS-тест (confirm-текст содержит affected chats; отказ → 0) + Playwright (3 DELETE) |
| D01-паттерн (capture до await) | PASS | JS-тесты: stale-карта, abort bulk при смене scope |
| Существующие settings-тесты зелёные | PASS | 378 passed backend + 75/75 JS |
| Мобильная компоновка 390px, не перекрывает контролы | PASS | Playwright mobile 25/25 + скриншот |

## Ограничения / реальные риски

- Стек подключён в generic-сетки конфига (basic+advanced). Спец-шаблоны (workspace
  модулей `activeModuleGroups`, prompts-витрина, llm_providers-секции) стек пока НЕ
  показывают — это другой рендер-путь; карта/API к ним применимы без изменений
  (расширение — одна строка `<override-stack>`). Не является part of acceptance D07
  (§9B.2 говорит про параметры в global view — основная settings-сетка покрыта).
- `chat_display_info` — best-effort Bot API (кэш 1ч); без бота — фолбэк «Чат {id}».
- Live-проверка в проде (реальный PG + Telegram WebView) не выполнялась лейном —
  std-ограничение writer-лейна (Chromium ≠ Telegram WebView; live-приёмка — owner).
- Секретные override-значения невозможны по каталогу (per_chat исключает secret);
  фильтр keys.*/secret — defense-in-depth, покрыт тестом.

## Fan-out / артефакты

Leaf-лейн, сабагентов не запускал. Кандидат в дереве НЕ закоммичен. Файлы:
`web/api/routes.py`, `web/app.js`, `web/index.html`, `tests/test_asap8_v6_d07_overrides.py`
(новый), `tests/js/asap8_v6_d07_override_stack_test.js` (новый).

**Шов с Direct-лейном (W-C):** в общем worktree `web/api/routes.py` содержит и их
незакоммиченную правку (`direct_context_diagnostics` → `out["l1"]`,
direct_l1.get_l1_diagnostics, ~:778) — другой регион файла, мои изменения
(импорт chat_display_info + OVERRIDES_FOR_USER_SQL + endpoint после
`delete_chat_param`, ~:1025) с ней не пересекаются. Общий прогон на совмещённом
дереве зелёный (378 backend + 75/75 JS). При ревью/мердже — обе правки
сохранить; reconciles тривиален (разные hunk'и).
