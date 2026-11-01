# W16 — дельта ASAP-UI-02: единый слой overlay, Back-стек, motion-токены, палитра, окно записи

**Дата:** 01.11.2026 · **Ветка:** `fix/asap-ui-02-delta` (база — `evol/impl` @ `9cdc45f2`)
**Правило волны:** matrix-first, delta-only. Ничего не «улучшалось» повторно: сначала
проверялось фактическое состояние в коде и живом рендере, затем правилась только
отсутствующая часть.

Строки карты, к которым относится волна: `L01843` (ASAP-UI-02-08), `L01848`
(ASAP-UI-02-08), `L01854` (ASAP-UI-02-09S), `L01940`/`L01943` (ASAP-UI-02-15),
`L01950` (ASAP-UI-02-16T), `L01958` (ASAP-UI-02-17B), `L01971`/`L01979`
(ASAP-UI-02-18). Источник требований — `plans/current_task.md` §4.2, §9, §10, §11, §12.

## 1. Вердикты по пунктам

| Пункт | Вердикт | Что реально изменено | Файлы | Тест | Доказательство |
|---|---|---|---|---|---|
| **L01848** — один z-index/portal/focus/backdrop | **ИСПРАВЛЕНО** | Один ранг слоя вместо «магических» чисел: добавлена лестница `--z-*` (`base 0 … content 1, inline 5, sidebar 30, scrim 35, nav 40, local 45, overlay-z 50, menu 55, modal-scrim 75, modal 80, toast 90, palette 100, dev 110, dev-top 120`) и 27 правил переведены на неё (шапка, drawer+подложка, dropdown области, модалка, окно записи, меню, тосты, палитра, fullscreen-редактор/сцена, exec-panel, dev-инструменты). Исправлены реальные перекосы: скрим модалки был на ранге dropdown (50), окно записи жило на отдельном 80, палитра — на 1300, dev-панель — на 57 вне системы. `--overlay-z: 50` (контракт EVOL-023) не менялся; `.ctl-pop`/`.ctl-sheet` остались производными `+10/+20`. | `web/static/app.css` | `tests/test_webapp_asap_ui02_delta.py` (лестница, порядок, «нет чисел вне лестницы», привязка поверхностей), `tests/test_webapp_avatars_ui.py` (пин шапки переведён на ранг), `tests/js/asap8_w2_fullscreen_policy_test.js` (dev-слой на `--z-dev-top`) | `evidence/asap-ui-delta/asap-ui-delta-e2e.json` → `layers` (живой computed: header 40, drawer 40, scrim 35, scope 50, скрим записи 75, toast 90, palette 100); скрины `asap-ui-delta-1280-scope.png`, `asap-ui-delta-390-drawer.png` |
| **L01854** — единый select/combobox, на телефоне лист | **УЖЕ СООТВЕТСТВУЕТ** (кода не менял) | Кастомный комбобокс в приложении один — селектор области; он уже flip'ается и становится листом (`_ctlPlacePopover` + `.scope-panel[data-placement="top"/"sheet"]`) и берёт подложку из общего overlay-контракта (`.glass-overlay, .scope-panel { background-color: var(--overlay-bg) … }`). Остальные select'ы — нативные `select.field`: на телефоне открывается системный лист, «desktop-dropdown за границей окна» физически не возникает. | — | `tests/test_webapp_asap_ui02_delta.py::test_scope_combobox_flip_and_sheet_states`, `::test_dropdown_is_opaque_and_not_clipped` | живой замер: 1280 — панель 260×372 целиком внутри вьюпорта, `data-placement=bottom`, alpha 0.94, тап перехватывает сама панель (`hitInside=true`); 667×375 — панель 207×310 внутри вьюпорта с внутренним скроллом (`asap-ui-delta-667x375-scope.png`) |
| **L01950** — единые motion-токены для переходов и лент | **ИСПРАВЛЕНО** | Второй набор длительностей устранён: `--dur-fast/-normal/-slow` и `--ease-out` стали алиасами `--motion-*`. Добавлены токены лент `--motion-feed-speed/-resume/-end-hold/-rewind/-start-hold`. Движок лент (`SFeed`) больше не держит собственные числа: `DEFAULTS = resolveMotionTokens(readCssMotionToken, MOTION_FALLBACK)`, значения читаются из вычисленного стиля `:root`; пустой/битый/нулевой токен даёт честный фолбэк. | `web/static/app.css`, `web/app.js` | `tests/test_webapp_asap_ui02_delta.py::test_motion_tokens_single_source`, `::test_feed_engine_reads_motion_tokens`, `tests/js/asap_ui02_delta_test.js` (разбор `ms/s/px`, ноль и мусор → фолбэк, шаг ленты берёт скорость из того же DEFAULTS) | живой замер `tokens` в `asap-ui-delta-e2e.json`: `--dur-fast` = `--motion-fast`, `--ease-out` = `--motion-ease`, а `__StatusFeed.DEFAULTS` = `{16, 2600, 1600, 900, 600}` ровно как `--motion-feed-*` |
| **L01958 / L01971** — Back закрывает вложенную область, а не Mini App | **ИСПРАВЛЕНО** | Введён **один** Back-стек: `backStackLayers(vm)` (порядок сверху вниз: палитра → полноэкранный редактор промпта → окно записи → полноэкранный редактор речи → меню речи → guard обложки → dev-панель → dropdown области → drawer → под-табы Аналитики → полный граф → панель деталей → досье → окно модуля → окно «Доступов») и единственный закрыватель `backStackClose(vm)`. `escClose()` и `goBack()` делегируют ей (раньше это были два независимых if-чейна в разном порядке), а `syncBackButton()` показывает нативный Back при открытом слое даже на корневом маршруте — до этого Telegram Back на корне закрывал всё Mini App. | `web/app.js` | `tests/js/asap_ui02_delta_test.js` (порядок, «ровно один слой за Back», маршрут не меняется, негативный случай «пустой стек», BackButton show при открытом слое на корне), `tests/test_webapp_asap_ui02_delta.py::test_back_stack_is_single_source_of_order`, `::test_back_button_visible_for_nested_layers` | живой прогон: палитра поверх корневого `#/ai` → Telegram BackButton получает `show()` (`backCalls:['show']`), Esc закрывает **только** палитру, маршрут остаётся `#/ai`; на 390 два Esc закрывают ровно два слоя (палитра → drawer), `closeOrder390.palette=false` |
| **L01940 / L01943 / L01979** — палитра/поиск | **УЖЕ СООТВЕТСТВУЕТ** (реализовано в W12, кода не менял) | Палитра существует и работает: desktop — кнопка в шапке + `Ctrl+K`/`Cmd+K`, телефон — вход в drawer; индекс строится из живых структур с RBAC (`canViewTab`, `isGlobalAdmin` для «Аналитики»), секреты и `category=keys` не индексируются; выбор открывает **конкретный** объект через `?focus=<токен>`, повторный выбор того же адреса дофокусирует; отсутствующий объект даёт честное сообщение, а не прыжок на верх раздела; уход с dirty-страницы защищён confirm'ом (черновик не теряется молча). | — | `tests/test_webapp_evol_w12_internals.py` (единичная палитра, входы, Ctrl+K/Esc, RBAC/секреты, deep-link), `tests/js/asap_ui02_delta_test.js` (выбор ведёт на конкретный объект, а не на раздел) | живой прогон: 1280 — панель 720 px внутри вьюпорта, ввод в фокусе, alpha 0.94; 390 — лист во всю ширину (390×844), ввод 44 px, honest-empty; 320 — читаемо, без горизонтального скролла. Скрины `asap-ui-delta-1280-palette.png`, `-390-palette.png`, `-320-palette.png` |
| **L01843** — один стандарт детального просмотра | **ИСПРАВЛЕНО (дельта)** | Окно записи уже было одним диалогом на общем `.modal-card` с тем же `record_id`, раздельными датами (`graph_facts.created_at` / `message_timestamp` / `last_confirmed_at`), происхождением и адресными переходами. Дельта волны: окно переведено на общий ранг скрима (`--z-modal-scrim`, как остальные модалки) и у мобильного листа кнопка закрытия получила hit-area ≥44 px (замер ревью был 42×38 — единственный очевидный выход из листа был ниже тач-минимума). | `web/static/app.css` | `tests/test_webapp_asap_ui02_delta.py::test_record_detail_uses_the_single_dialog_standard`, `::test_record_detail_keeps_same_record_and_separate_dates`, `tests/test_evol001_005_status_widgets.py` | 1280: `asap-ui-delta-1280-record.png` (запись #4242, три разных даты с полями БД, TG-источник #777, «нет данных» вместо подмены); 390: `asap-ui-delta-390-record.png` — режим листа (`w9-sheet-bottom`), ✕ 44 px, внутренний скролл, Esc закрывает только лист и возвращает фокус в строку (`record390Esc.row=true`) |

## 2. Точные команды и результаты

| Команда | Результат |
|---|---|
| `node tests/js/asap_ui02_delta_test.js` | `ASAP-UI02-DELTA-OK` |
| `node <каждый файл tests/js/*.js>` (99 файлов) | 95 OK, 4 падения — **все четыре существуют на базе `9cdc45f2`** (проверено отдельным чистым worktree): `asap6_wave2_ux_tabs_test.js`, `round1021_ui_audit_test.js`, `round1024_budget_toggle_test.js`, `round1024_image_module_test.js` (пины количества вкладок/маркеров шаблона) |
| `py -3 -m pytest tests/test_webapp_asap_ui02_delta.py -q -p no:randomly` | 11 passed |
| `py -3 -m pytest tests/test_webapp_evol_w7_nav.py tests/test_webapp_evol_w9_responsive.py tests/test_webapp_evol_w10_sections.py tests/test_webapp_evol_w11_controls.py tests/test_webapp_evol_w12_internals.py tests/test_webapp_back_button.py tests/test_evol001_005_status_widgets.py tests/test_evol032_health_glass.py tests/test_webapp_design_tokens_round1025.py tests/test_webapp_hotfix10_round1025.py tests/test_webapp_round1026_polygon.py tests/test_webapp_f11_round1025.py tests/test_webapp_f6_round1025.py tests/test_webapp_round108_ui.py -q -p no:randomly` | 331 passed |
| `py -3 -m pytest tests -q -p no:randomly -k "webapp or evol or ui" --ignore=tests/test_webapp_asap_cover_ui_v21_e2e.py` | **2990 passed, 8 failed, 1 error — все девять воспроизводятся на базе `9cdc45f2`** (проверено в отдельном чистом worktree): `test_webapp_avatars_ui::test_close_and_fullscreen_buttons` (6 ✕ против пина 5 — палитра W12 добавила шестую кнопку закрытия), `test_webapp_round1024_nodeflow::test_no_english_jargon`, `test_history_cli::test_scope_is_required`, `test_graphrag_rebuild_asap32::test_not_serviceable_warning_coalesced`, `test_asap_w1_semantics::test_91_factory_and_active_revisions_distinguishable`, `test_webapp_tma_fixes_ui::test_logs_block_layout_mono`, js-пины `round1021/round1024_image_module`, ошибка окружения `test_samples_ui_e2e` |
| `py -3 -m pytest tests/test_webapp_js_unit.py::test_js_unit_asap_ui02_delta -q -p no:randomly` | 1 passed (новый JS-тест подключён к стандартному JS-unit набору, а не только запускается вручную) |
| `py -3 tools/ui_asap_ui02_delta_e2e.py` | `ASAP-UI02-DELTA OK` (1280×800, 390×844 touch, 667×375 touch, 320×700 touch) |

## 3. Обновлённые пины (честно заменены, не ослаблены)

Старые проверки фиксировали **реализацию** (конкретные if-строки в `escClose/goBack`
и магические z-index). Каждый заменён на проверку поведения/ранга, а не удалён:

- `tests/js/asap8_w2_shell_mobile_nav_test.js`, `tests/js/evol_w7_nav_test.js` — порядок слоёв теперь проверяется вызовом `backStackLayers`/`escClose` (что именно закрылось), а не поиском строки в методе;
- `tests/js/round1025_f6_analytics_memory_test.js` — Esc закрывает детали: проверяется факт вызова закрытия;
- `tests/js/asap8_w2_fullscreen_policy_test.js` — dev-панель на ранге `--z-dev-top` вместо числа 57;
- `tests/test_webapp_avatars_ui.py` — шапка на `--z-nav`, локальный подъём на `--z-local`;
- `tests/test_webapp_evol_w7_nav.py`, `tests/test_webapp_evol_w12_internals.py`, `tests/test_evol001_005_status_widgets.py`, `tests/test_webapp_f11_round1025.py`, `tests/test_webapp_f6_round1025.py`, `tests/test_webapp_round108_ui.py` — те же слои проверяются через единый стек.

## 4. Остаточные риски и что НЕ доказано этой волной

1. **Фильтры/позиция при возврате.** Чат и scope сохраняются (localStorage + `X-Chat-Id`), черновик защищён confirm'ом при уходе, но локальные фильтры каталога (`moduleFilter` и подобные) живут в памяти вкладки и сбрасываются при переходе. Это подпункт `L01943`, который волна **не закрывала**; отдельного требования «персистить фильтры» в ТЗ нет — фиксирую как открытое наблюдение, а не как выполненное.
2. **RBAC палитры проверен контрактными и юнит-тестами**, не живым входом под ограниченной ролью: живые прогоны идут под `global_admin` (стаб `/api/me`).
3. **Порядок «`--z-dev*` выше палитры»** — осознанное изменение: dev-панель включается только внутренним флагом, зато измерения геометрии не перекрываются палитрой. Прод-поведение не затронуто.
4. **`--motion-*` читается один раз** при первом обращении (лента не меняет скорость на ходу) — это осознанно и зафиксировано комментарием в коде.
5. **Browser Use**: получить аутентифицированный рендер в Browser Use не удалось — страница грузит настоящий `telegram-web-app.js`, который перетирает `initData`, а CDP-инъекция на document-start в этой сессии не применялась; вне Telegram приложение показывает честный барьер «Миниапп открыт без Telegram-контекста». Поэтому визуальная проверка выполнена по **реальным пикселям реального `index.html`** (Chromium-скриншоты Playwright-прогона на 1280/390/667/320), а не по Browser Use. Это ограничение среды, а не пропущенный шаг: все экраны выше просмотрены глазами на снимках, стенд не имитирует продукт (тот же `web/index.html` + стабы API).

## 5. Наблюдения вне скоупа (не блокируют)

- `.ctl-pop`/`.ctl-pop__search` объявлены в `app.css` как канонический комбобокс, но применений в разметке 0: единственный кастомный комбобокс (селектор области) использует `.scope-panel` с теми же overlay-токенами. Сводить их в один класс нужно при касании конкретного экрана, иначе легко сломать позиционирование; сейчас это мёртвый, но безвредный канон.
- Предсуществующие падения тестов (см. §2) — не связаны с этой волной; на базе воспроизводятся.
- **Гигиена тестов:** прогон UI-наборов (`tests/test_webapp_evol_w10_sections.py`, `w11`, `w12`) **перезаписывает** закоммиченные артефакты `plans/features/evol/audit/evidence/w1x-*`: снимки и `w10-sec-probe.json` на HEAD содержат ключи/состав, которых в актуальном инструменте уже нет (`moduleScopeToggles`, `favoritesAny`, `statusOrder` без `hero`). Это существующая проблема репозитория, не этой волны; после прогонов файлы восстановлены байт-в-байт из HEAD, в коммит не попали.
- Клик по строке ленты на 390 возвращает фокус в строку, но после закрытия листа страница остаётся на той же позиции прокрутки — это ожидаемое поведение (лист не меняет scroll родителя).

## 6. Вопрос владельцу (не блокирует релиз)

`§9` требует «mobile — компактная точка входа **в панели вторичных действий** → читаемый поисковый sheet». Панель «…» удалена позднейшим решением владельца (§6.1 v2.1), поэтому сейчас на телефоне поиск открывается из **drawer** (`data-palette-open-drawer`): одно открытие панели → пункт «Поиск». Варианты:

- **A (сейчас):** drawer — достаточно (поиск в одном открытии, шапка не раздута);
- **B:** вернуть компактную иконку поиска прямо в шапку на телефоне (1 тап, но + одна кнопка в тесную строку);
- **C:** отдельный пункт поиска в… — не предлагается: панели вторичных действий больше нет.

Реализация оставлена как **A** (соответствует последнему явному решению владельца); переключение на **B** — небольшая правка шапки + тест.

## 7. Гигиена

- База `9cdc45f2` разворачивалась отдельным временным worktree только для классификации
  предсуществующих падений; после классификации он удалён (чистый detached checkout).
- Одноразовые скрипты проб лежали в `<GLOBAL_CONFIG>/WorkspaceData/runs/`, в репозиторий
  не попадали. Устойчивые артефакты — только `plans/features/evol/audit/evidence/asap-ui-delta/`.

---

# После ревью (Needs Fixes → разбор трёх блокеров)

Кандидат ревью: `d5ecd795`. Ревью: `plans/features/evol/reports/w16-ui-delta-review.md`
(код дельты принят; блокеры 1–2 — про доказательства, блокер 3 — реальный UI-пробел L01854).
Ниже — что сделано по каждому, с командами и фактическими результатами.

## 1. Блокер 3 (UI): панель области на телефоне — ЛИСТ (L01854)

**Что изменено (минимально, на существующей механике):**

- `web/app.js`: чистая функция `_ctlScopePlacement(box, view, isPhone)` — при `<768`
  (тот же `shellMode === 'mobile'`, что и вся адаптивная раскладка) панель области
  принудительно становится **листом**: `placement="sheet"`, `maxHeight` от видимой
  области. На ≥768 возвращается прежний якорный dropdown с flip — поведение не менялось.
- `web/app.js`: лист позиционируется в системе **содержащего блока**. Живой прогон
  поймал настоящий дефект: `position: fixed` внутри шапки ограничен её
  `backdrop-filter`, поэтому лист «улетал» над вьюпортом (замер: `top −452` при видимой
  области 504). Добавлен `_ctlFixedContainingBlock(el)` и расчёт `left/width/bottom/
  maxHeight` от найденного блока — второго поповера не появилось, используется тот же
  `.scope-panel[data-placement="sheet"]` и тот же overlay-ранг.
- `web/index.html`: у подписи опции появился хук `scope-option__title` + полное имя в
  `title`; утилита `truncate` убрана, чтобы не бороться специфичностями.
- `web/static/app.css`: в листе подпись **переносится до двух строк**
  (`.scope-panel[data-placement="sheet"] .scope-option > span > .scope-option__title`),
  на desktop остаётся одна строка с многоточием (правило W11 не переписано, новое
  правило стоит после него и выровнено по специфичности).

**Живой замер (Playwright, touch-контексты):**

| ширина | placement | позиция | ширина листа | самое длинное название | пункт |
|---|---|---|---|---|---|
| 320×700 | `sheet` | `fixed`, снизу (gap 9) | 304 из 320 | перенос 2 строки, `scrollWidth−clientWidth = 0`, текст 60 символов виден | 49 px |
| 360×780 | `sheet` | `fixed`, снизу (gap 9) | 344 из 360 | 2 строки, clip 0 | 49 px |
| 390×844 | `sheet` | `fixed`, снизу (gap 9) | 374 из 390 | 2 строки, clip 0 | 49 px |
| 667×375 | `sheet` | `fixed`, снизу (gap 9) | 651 из 667 | 1 строка (места хватает), clip 0 | 49 px |
| 768×1024 | `bottom` (dropdown) | `absolute`, под триггером | 380 | одна строка + ellipsis (полное имя в `title`) | 49 px |
| 1280×800 | `bottom` (dropdown) | `absolute`, под триггером | 380 | одна строка + ellipsis | 49 px |

Выбор работает тапом на всех телефонах: на 320 тап по второму пункту дал
`activeChatId=-1001234567890`, `scopeKind=chat`, лист закрылся. Скрины:
`evidence/asap-ui-delta/asap-ui-delta-{320,360,390,667x375}-scope-sheet.png`,
`asap-ui-delta-1280-scope.png`.

Тесты: `tests/js/asap_ui02_delta_test.js` (блок 7: phone → `sheet` + `maxHeight`,
desktop/compact → прежний `bottom`/`top`), `tests/test_webapp_asap_ui02_delta.py::
test_scope_is_sheet_on_phone_only`, `::test_scope_sheet_title_wraps_instead_of_ellipsis`.
Существующие live-инструменты W7/W9/W11 не переписаны: они принимают
`placement in ("top","bottom","sheet")` и проверяют «внутри видимой области» — прогнаны
зелёными (см. §4).

**Строка L01854: закрывать можно.**

## 2. Блокер 1 (доказательства): сценарии 6 и 14 §12

Оба сценария прогнаны на фактической сборке тем же инструментом
(`tools/ui_asap_ui02_delta_e2e.py`, сервер/стабы — из `tools/ui_round1025_matrix.py`),
результаты — машинный JSON `evidence/asap-ui-delta/asap-ui-delta-e2e.json` (ключи
`scenario6`, `scenario14`) + снимки.

**Сценарий 6 «Scroll и Back» — ПРОЙДЕН:**

| проверка | результат |
|---|---|
| шапка не прыгает: `top`/высота до и после прокрутки контента | `top 0 → 0`, высота `58 → 58` px (390) |
| два реальных слоя одновременно (dropdown области + палитра) | стек `["palette","scope"]` |
| первый Back | закрыл **только** палитру, стек `["scope"]`, маршрут `#/` не изменился |
| второй Back | закрыл только dropdown, стек пуст, маршрут `#/` не изменился |
| лист записи на корневом маршруте | стек `["record"]`; Back закрыл только лист (`modal:false`), маршрут `#/` |
| fullscreen-граф | стек `["graph-full"]`; Back вернул на родителя `#/`, стек пуст |
| Telegram Back | при слое на корневом маршруте вызван `BackButton.show()` (живой лог `__backCalls`) |

**Сценарий 14 «Поиск и deep link» — ПРОЙДЕН:**

| клаузула | результат |
|---|---|
| поиск из любого экрана | `Ctrl+K` на `#/ai/speech` открыл палитру, метка области `ЧАТ` |
| конкретный объект, не «верх раздела» | выбрана цель `module:mod_initiative`; маршрут `#/modules/initiative?focus=module-card%3Amod_initiative`, целевой элемент подсвечен (`focus-pulse`) |
| scope соблюдён | до/после перехода `kind=chat, chat=-1001234567890` (область не сброшена) |
| отсутствующий объект — честное состояние | `#/ai?focus=nope…` → сообщение «Не удалось перейти к параметру: он не отображается на открытом экране», без молчаливого прыжка |
| черновик не теряется молча | ввод в редактор промпта → `dirty=true`; уход по цели вызвал подтверждение; **отказ** удержал маршрут и текст; **согласие** + возврат вернули редактор с тем же текстом (`dirty=true`) |
| возврат сохраняет позицию | прокрутка 420 px → переход по цели → `history.back()` → 420 px, маршрут `#/modules` |
| RBAC | см. §3 (ограниченная роль) |

**Найдено и исправлено живыми прогонами (не косметика):**

1. **Падение приложения на Back из fullscreen-графа** — `closeGraphFull()` вызывал
   общий `goBack()`, а граф сам стал слоем стека: `goBack → верхний слой = граф →
   closeGraphFull → goBack` (переполнение стека, живой `RangeError`). Исправление:
   закрыватель возвращает на **родительский маршрут** графа (`routeParent`), плюс у
   стека появился guard от повторного входа (`_backStackBusy`). Тест:
   `tests/js/asap_ui02_delta_test.js` блок 6, `tests/test_webapp_asap_ui02_delta.py::
   test_back_stack_has_no_recursion_into_itself`.
2. **Палитра предлагала раздел, недоступный роли** — статические адреса
   (`SEARCH_STATIC_ENTRIES`) индексировались без проверки вкладки: у роли без «Доступов»
   пункт «Доступы и роли» был в выдаче и отказывал при выборе. Теперь адрес проходит
   через `routeToTab(...)` + `canViewTab(...)`. Тест: `::test_palette_static_entries_are_rbac_gated`.
3. **`?focus=module-card:<id>` не находился на странице модуля** — токен висел только на
   карточке каталога, поэтому переход «модуль» из палитры через 4 с давал ложное «не
   удалось перейти». Страница модуля получила тот же токен на своей шапке. Тест:
   `::test_palette_target_focus_resolves_on_module_page`.

**Честно про набор §12:** доказаны **сценарии 6 и 14**, весь набор из 17 — нет.
Строки `L01966–L01982` остаются `PENDING`: закрывать `L01971`/`L01979` как «набор
выполнен» по-прежнему нельзя, хотя механика обоих сценариев подтверждена живьём.

## 3. Блокер 2 (RBAC + позиция/черновик, L01943)

**Ограниченная роль собрана существующими средствами** (без нового стенда): тот же
сервер матрицы, переопределён только `/api/me` —

```
role_name: "reader", permissions: {sections:["memory"], params:[], keys:[]},
is_global_admin: false, is_custom: false   (никакого wildcard)
```

| проверка | админ | ограниченная роль |
|---|---|---|
| записей в индексе палитры | 627 | **536** |
| записи «Аналитика: запуски/токены/модели» (admin-only) | есть | **нет** |
| адрес `#/access` | есть | **нет** (появилось после RBAC-гейта статических адресов) |
| адреса модулей недоступных вкладок | — | **0 утечек** (`blockedModuleLeaks: []`) |
| секреты в индексе | 43 секретных ключа, 0 в индексе | 43 → **0 утечек** |
| разрешённая цель «Память» (секция memory) | есть | **есть** (фильтр не вырезал всё) |
| deep-link в недоступный раздел `#/access` | — | маршрут отклонён (`#/`), сообщение «Нет доступа к разделу» |
| deep-link к недоступному объекту (`?focus=module-card:mod_x`) | — | честное «Не удалось перейти к параметру…», без silent fallback |
| возврат после перехода по палитре | — | чат/scope сохраняются (`chat 424242` до/после/при возврате) |

**Позиция прокрутки** (подпункт, который раньше был открыт) реализована на существующем
слое маршрутов: `_rememberRouteScroll` при уходе со своего адреса + `_restoreRouteScroll`
после рендера (двойной `requestAnimationFrame`, чтобы не спорить с `$nextTick`-сбросом
`setTab`); берётся реально прокручиваемый контейнер (`main.scroll-area` в shell,
документ на desktop). Живой замер: 420 px → возврат → 420 px. Переход в **новый** раздел
по-прежнему начинается сверху (память есть только у посещённого адреса).
Тест: `tests/test_webapp_asap_ui02_delta.py::test_route_scroll_position_survives_return`.

**Строка L01943: закрывать можно** — чат/scope, фильтры (проверял Reviewer), черновик
(guard + возврат), позиция (420→420) и RBAC (живой ограниченный payload) доказаны.

## 4. Команды и результаты (после правок)

| команда | результат |
|---|---|
| `node tests/js/asap_ui02_delta_test.js` | `ASAP-UI02-DELTA-OK` (в т.ч. лист на телефоне и guard от рекурсии) |
| `node <каждый tests/js/*.js>` (100 файлов) | 96 OK; 4 падения — те же, что на базе `9cdc45f2` (`asap6_wave2_ux_tabs`, `round1021_ui_audit`, `round1024_budget_toggle`, `round1024_image_module`) |
| `py -3 -m pytest tests/test_webapp_asap_ui02_delta.py -q -p no:randomly` | **17 passed** |
| `py -3 -m pytest tests/test_webapp_evol_w7_nav.py tests/test_webapp_evol_w9_responsive.py tests/test_webapp_evol_w11_controls.py tests/test_webapp_evol_w12_internals.py tests/test_webapp_back_button.py tests/test_webapp_asap_ui02_delta.py tests/test_scope_selector_round1025.py -q -p no:randomly` | **160 passed** (включая живые прогоны W7/W11) |
| `py -3 -m pytest tests -q -p no:randomly -k "webapp or evol or ui" --ignore=tests/test_webapp_asap_cover_ui_v21_e2e.py` | **2997 passed, 8 failed, 1 error** — все девять воспроизводятся на базе `9cdc45f2` (`test_webapp_avatars_ui::test_close_and_fullscreen_buttons`, `round1024_nodeflow::test_no_english_jargon`, `test_history_cli::test_scope_is_required`, `test_graphrag_rebuild_asap32::test_not_serviceable_warning_coalesced`, `test_asap_w1_semantics::test_91_…`, `test_webapp_tma_fixes_ui::test_logs_block_layout_mono`, js-пины `round1021/round1024_image_module`, окружение `test_samples_ui_e2e`) |
| `py -3 tools/ui_asap_ui02_delta_e2e.py` | `ASAP-UI02-DELTA OK` — 1280×800, 390×844 touch, 667×375 touch, 320×700 touch, 360×780 touch, 768×1024 touch; сценарии 6 и 14; RBAC-роль |

## 5. Что закрывать, а что нет (после этой итерации)

**Можно закрывать:** `L01848`, `L01843`, `L01950`, `L01958`, `L01940` (подтверждены
ревью), **`L01854`** (лист на телефоне + читаемые названия + выбор тапом),
**`L01943`** (RBAC ограниченной роли, чат/scope, черновик, позиция).

**Пока нельзя:** `L01971` и `L01979` — их acceptance = **весь** набор 17 сценариев §12.
Сценарии 6 и 14 доказаны, остальные строки набора (`L01966–L01982`) остаются `PENDING`,
поэтому строку нельзя закрыть «набором» (это работа PM/приёмки, не этой дельты).

**Остаточные риски, которые я не выдаю за проверенные:**

1. **Browser Use с аутентифицированным рендером** недоступен: страница грузит настоящий
   `telegram-web-app.js`, который перетирает `initData`, а CDP-инъекция на document-start
   в этой сессии не применяется (вне Telegram — честный барьер). Визуальная проверка всех
   изменённых экранов сделана по реальным пикселям реального `index.html` (Chromium-
   снимки Playwright на 320/390/667/768/1280), которые я просмотрел глазами.
2. **Скрытие BackButton** после закрытия последнего слоя в браузере не воспроизводится:
   `isVisible` у реального объекта non-configurable, поэтому фикстура видит только
   `show()`. Скрытие подтверждено юнит-тестом, не живым клиентом.
3. **Полноэкранный редактор промпта** (переехал с 1250 на общий ранг модалок) в этой
   дельте живьём не открывался — риск из ревью сохраняется.
4. Остальные сценарии §12 (карта EVOL-COG, fullscreen-карта, health tint в движении и
   т.д.) не входили в эту итерацию.
