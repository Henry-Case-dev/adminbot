# REWORK REVIEW — W4 UI/UX (`asap-speech-arch` §8), lane REV-W4-UI

**Вердикт: Needs Fixes.** Кандидат: `5e7d986e8c7db6d7b677082d9f3983f4b089c09f`,
диапазон `924b3b51..5e7d986e`. `web/**`, `tools/**`, `tests/**` в рабочем дереве
чисты относительно кандидата; в дереве есть посторонние правки `plans/**` — к
этому ревью они не относятся. Evidence читал из коммита; свои прогоны писал в
`OPENCODE_WORKFLOW_SCRATCH/` и в `evidence` не писал.

## Acceptance ledger

| Пункт | Статус | Факт |
|---|---|---|
| U-01 стекло карточек | VERIFIED | Before/after `shots/before|after/*_1280/1440` показывают прежний «вырезанный» прямоугольник на `Промпты по модулям` и `Речь и характер`; после — цельная поверхность. Мой пиксельный прогон: карточка библиотеки (normal) mean Δ 0.62, changed 1.03 %, кромки 3.44/0.11/2.88/1.80, центр 0.28 %; hover 0.68/1.04; scroll 0.25/0.43. `speech-head`: mean 1.31, changed 5.42 %, кромки 4.06/3.51/8.16/1.72, центр 0.05 %. Baseline `speech_head`: низ **+109.7 %**, центр **+40.6 %** — дефект воспроизведён и устранён. Полигональный фон/геометрия/цвета/анимация не менялись: в диффе только `web/static/glass-refraction.js` (слой стекла), фон-код не затронут. |
| U-02 семь рядов | **FAILED** | `Core`, `Уроки`, `Примеры`, `Юмор` открывают секции; `SelfModel` — честный read-only: без шеврона, `cursor: default`, причина «правила кода о себе…», badge «только чтение». `L1` и `Writer` **не показывают** выбранный блок: после клика `#/ai/speech`, `scrollY=0`, `[data-speech-block-detail]` имеет `top=9081` при `innerHeight=900`; пользователь видит верх 77-строчного реестра, а не `direct.base.l1_planner` / `direct.base.l2_writer`. Это прямое нарушение §8 U-02 и §6 «не скроллит в пустоту». |
| U-03 каталог | VERIFIED | `prompt-module-grid`: 1 колонка <600, 2 при 768, 4 при 1280/1440; одинаковые ширины/ряды. Подпись `Direct: финальный ответ (Writer)` + «Преобразует план и данные… характер задаётся отдельно»; ключ `prompts.direct_chat_verbalizer_system_prompt` не изменён (проверено в DOM и в `services/param_catalog.py`). Кнопки этапов строятся по фактическим `workspacePromptItems`. |
| U-04 кодовые поля | VERIFIED | 320/360/390/430/667×375: `scrollWidth == clientWidth` у `.speech-pre` (252/322 px), `white-space: pre-wrap`, `overflow-wrap: anywhere`, `overflow-x: hidden`; страница без второй горизонтальной прокрутки. Скриншот 320/667 — текст «СИСТЕМНАЯ РОЛЬ:» читается с переносами. `textarea`: вставка/выделение/caret — e2e зелёный. |
| U-05 Core | VERIFIED (с замечанием) | Табы на 320 — по одному в строке, 390/430/667 — рядом, без обрезки. «Развернуть»: 320/390/430/667 — `w==vw`, `h==vh`, поле в фокусе, Esc/«Закрыть» закрывают. Сохранение compact уходит `POST /api/speech/block/core.personality.compact`; GLOBAL/CHAT — `scope=global` без `X-Chat-Id` / `scope=chat` с `X-Chat-Id`. Замечание: после закрытия фокус уходит в `BODY`, а не на «Развернуть»; при переключении редакции панель Save исчезает (badge «черновик не сохранён — полная редакция» остаётся). |
| U-06 header | VERIFIED | Один заголовок: крошка — только путь (`Статус / ИИ`), заголовок — `Библиотека промптов`; дубля нет. `header.bottom == main.top`: 320 — 116.17/116.17, 768 — 113.36/113.36, 1280 — 109.36/109.36, 1440 — 109.36/109.36, 667×375 — 86.56/86.56. «Ещё» на 320/390 — 5 разделов (все кроме трёх закреплённых), drawer 768/1024 — 8; fullscreen-кнопка не переизобретена. |
| U-07 sticky Save | **FAILED** | Pristine/dirty/saving/saved/error/conflict в целом работают, но в конфликте остаётся **активная** «Повторить сохранение» рядом с «Обновить данные» (мой прогон: `posts_before=2 → posts_after=3`, POST ушёл со старым payload). Это обходит заявленный запрет «не перезаписывать чужую редакцию вслепую». В error-состоянии одновременно видны «Сохранить» и «Повторить сохранение»; в evidence-скриншоте конфликта одновременно висят зелёный «Сохранено…» (старый успех), красный 503 и жёлтый 409. Таблица `report.md` «conflict: 0 активных Save» не соответствует DOM. |
| U-08 стекло/доступность | VERIFIED | Контраст пересчитан: 9.26 / 7.67 / 5.74:1 (порог 4.5). `prefers-reduced-motion`: 0.0 % изменённых пикселей (полный кадр, 390/1280); polling: 0.397 %/0.374 % по полному кадру (это статусные тексты; клип `.speech-head` — 0.0 %), фон не мерцает. `?glassrefract=off` — читаемый frost-fallback. |
| U-09 маршрут | VERIFIED | GLOBAL и CHAT: `Статус → ИИ → Речь и характер → Core → Expression → Библиотека → Direct Writer → Назад`; POST scope совпадает с выбранным; Back возвращает в библиотеку; resize 1280↔390 сохраняет hash/раздел; активный пункт подсвечен. |
| Pre-existing W6 | VERIFIED (не регрессия) | `tools/ui_soul1_w6_speech_e2e.py --no-shots` — `failures=2` («предпросмотр выражения не обновился», 390/1440) и на кандидате, и на чистом `924b3b51` (worktree). Идентичные две проверки; это рассинхрон фикстуры/теста, не W4. |

## Блокеры

### B1 — U-02: L1/Writer открывают блок «в пустоту»
- Где: `web/app.js:19883-19891` (`openSpeechLayerRow` очищает `speechQuery` и вызывает `openSpeechBlock` без прокрутки); детальная карточка — `web/index.html:9100`, после списка 77 блоков (`web/index.html:9088`).
- Repro: `#/ai/speech` → клик `[data-speech-layer=l1]` (или `writer`) → `scrollY=0`, `detail.top=9081`, `innerHeight=900`; на экране верх реестра `factcheck_base_single…`.
- Impact: пользователь не видит текст/источник/редакцию выбранного блока; U-02 и §6 не выполнены. E2E `tools/ui_w4_ui_e2e.py:478-484` проверяет только наличие текста в DOM, не видимость.
- Fix: после `openSpeechBlock` (nextTick) `scrollIntoView({block:'start'})` на `[data-speech-block-detail]` и/или `speechQuery = node.block_id` (фильтр реестра), не очищать запрос. Recheck: detail.top < innerHeight и `block_id` виден на 1280/390.

### B2 — U-07: конфликт не закрывает повторную отправку
- Где: `web/app.js:19791-19797` (409-конфликт ставит `speechConflict`, но не очищает `speechRetry`); `web/index.html:7906-7908` (retry рендерится без учёта конфликта), аналогично 8149/8308 для style/expression.
- Repro: Core → правка → 503 → «Сохранить» → 409 → в баре «Конфликт» + «Обновить данные» + «Повторить сохранение»; клик по retry даёт новый POST с прежним текстом (`POST /api/speech/block/core.personality`, `scope=global`), конфликт остаётся.
- Impact: обход защитного состояния; при разрешившемся на сервере конфликте — слепая перезапись. E2E `:732-742` считает только `.btn-accent`, поэтому ghost-retry не видит и даёт ложный зелёный.
- Fix: в 409-ветке `speechRetry = null`; в шаблоне `v-if="speechCanRetry(section) && !speechConflictFor(section)"` (core/style/expression); в error-состоянии оставить один CTA (retry вместо primary). Recheck: после 503→409 в баре только «Обновить данные», POST по retry не уходит.

## Неблокирующие замечания
- `N1` U-05: после Esc/«Закрыть» фокус в `BODY`, не на «Развернуть»; focus-trap нет. Мелкая a11y-правка.
- `N2` U-07: старый зелёный тост «Сохранено…» сосуществует с 409/503; очищать success-тосты при новой попытке сохранения.
- `N3` Evidence: заявленные «+33.4 % до» для `[data-prompt-library-modules]` **не воспроизводятся** тем же инструментом на `924b3b51` (0.0 % в точках top/center/bottom); визуальный before-скриншот дефект показывает, after — 0.0/1.7. Исправить таблицу/указать точку замера, иначе число недоказуемо.
- `N4` `services/param_catalog.py:641` всё ещё хранит старое имя; UI-override закрывает библиотеку, но серверный title остаётся для экспорта/CLI. Builder это честно указал.
- `N5` Мобильная шапка не показывает title/breadcrumb (pre-existing shell; не регрессия W4).
- `N6` При переключении редакции Save-панель скрывается, хотя badge «черновик не сохранён — полная редакция» виден; CTA для скрытой редакции недоступен без возврата. Показывать панель при dirty любой редакции.
- `N7` В CHAT-контексте select «Куда сохранить» по умолчанию `global` (виден пользователю, не «тихо»); формулировка отчёта «дефолт = chat» верна только после chat-override/явного выбора. Уточнить.
- `N8` Мой полный кадр polling: 0.37–0.40 % изменённых пикселей (статусные тексты), клип головы 0.0 %; фона/мерцания не видно.

## Прогоны (мои, не переиспользованные)
- `.venv/Scripts/python.exe tools/ui_w4_ui_e2e.py` (из scratch-обёртки, evidence в scratch): **failures=0, POST=8, notes=159**.
- `tests/ui_p0a_ux_speech_compact_e2e.py`: **failures=0, POST=22**.
- `tools/ui_win_glass_refraction_e2e.py`: **WG-REFRACT-E2E-OK** (A 21, C 4, B 10, D 2).
- `tools/ui_asap8_w2_shell_e2e.py`: **W2-SHELL-E2E-OK**.
- `tools/ui_soul1_w6_speech_e2e.py --no-shots`: **failures=2** на кандидате и на baseline `924b3b51` (одинаковые).
- `node tests/js/glass_refraction_test.js`, `glass_probe_test.js`, `round1025_hotfix10_glass_geometry_bg_test.js`: все OK.
- `pytest tests/test_soul1_w6_speech_ui.py tests/test_webapp_design_tokens_round1025.py tests/test_webapp_nav_disclosure_ui.py tests/test_webapp_js_unit.py tests/test_ui_verbilizer_tabs_round1023.py tests/test_webapp_parity_smoke.py tests/test_web_prompts.py -q`: **171 passed**.
- Browser Use: 390 — «Развернуть» покрывает 390×844, фокус в поле, Esc закрывает; 320 — мобильная шапка 147 px, `scrollWidth=320`. Скриншот 1280 без SDK-стаба даёт мобильный shell (артефакт стенда, не кандидата); desktop-визуал проверен Playwright-скриншотами 1280/1440.

## Можно ли в поезд
Нет в текущем виде: B1 — не выполнено явное требование U-02, B2 — обход защитного конфликта U-07. После двух локальных правок и точечного recheck (клик L1/Writer → видимый detail; 503→409 → нет retry/POST) — да, в контролируемый деплой по стоячему правилу проекта, без канареек; parent не DONE до закрытия U-02/U-07.

## Остаточные риски реального Telegram WebView
Chromium-стенд не равен Android WebView: `mask-image`/SVG-фильтр и `backdrop-filter` на слабом GPU не измерялись на устройстве (есть только `ui_win_glass_refraction_e2e`, paintMs<6 ms, p95<40 ms); sticky-savebar + клавиатура/safe-area и `html{scroll-padding-top}` на реальном WebView не проверялись; `ancestorVeil` добавляет `getComputedStyle` по цепочке предков на каждый refresh — на низком FPS это может быть заметно. Device-чек владельца по стоячему правилу не обязателен, но эти риски остаются `PENDING` для живого WebView.

**Артефакт:** `plans/features/asap-speech-arch/evidence/w4/review.md`.
