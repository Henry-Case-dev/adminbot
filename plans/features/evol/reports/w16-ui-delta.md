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
| `py -3 -m pytest tests -q -p no:randomly -k "webapp or evol or ui" --ignore=tests/test_webapp_asap_cover_ui_v21_e2e.py` | 2987 passed; остались только внешние/предсуществующие падения: `test_webapp_avatars_ui::test_close_and_fullscreen_buttons` (6 ✕ против пина 5 — палитра W12 добавила шестую кнопку закрытия), `test_webapp_round1024_nodeflow::test_no_english_jargon`, `test_history_cli::test_scope_is_required`, `test_graphrag_rebuild_asap32::test_not_serviceable_warning_coalesced`, js-пины `round1021/round1024_image_module`, ошибка окружения `test_samples_ui_e2e` — **все воспроизводятся на базе** |
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
