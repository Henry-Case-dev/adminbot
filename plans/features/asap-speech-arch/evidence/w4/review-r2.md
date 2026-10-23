# REVIEW R2 — W4 UI/UX (`asap-speech-arch` §8), lane REV-W4-UI-R2

**Вердикт: Approved** (для контролируемого деплоя по стоячему правилу проекта;
parent не DONE). Кандидат: `dd4e052256181a4d3b78e7083292b417bde911e6`.
Фактический diff кандидата — 14 файлов (родитель `02f5473f`); диапазон
`5e7d986e..dd4e0522` включает посторонние embed-коммиты `30a2f868`/`02f5473f`,
в скоуп W4 они не входят. `web/app.js`, `web/index.html`,
`tools/ui_w4_ui_e2e.py` в рабочем дереве совпадают с кандидатом (blob SHA
сверены); мои прогоны писали в `OPENCODE_WORKFLOW_SCRATCH/` (единственное
исключение — штатная перезапись W6-отчёта, см. раздел прогонов).

## Acceptance ledger

| Пункт | Статус | Факт (этот раунд) |
|---|---|---|
| **B1 / U-02** detail L1/Writer | **VERIFIED** | После клика ряд фильтрует реестр до 1 строки и detail реально под шапкой: PW 1280×900 — `top=134`, `headerBottom=109`, видно 738/738 px; 390×844 — `top=248`, header 116, видно 596 px; мой отдельный пробник 1280×800 — `top=125`, `elementFromPoint` попадает внутрь карточки. Реальный Chrome (Browser Use, активная вкладка): 390 — `top=248` при header 116, видно 596 px; 320 — `top=248`, видно 452 px, `scrollWidth==320`; desktop 1280 — `top=135` при header 108, видно 737 px; `elementFromPoint` внутри карточки на всех трёх. Ключ в карточке: `direct.base.l1_planner` / `direct.base.l2_writer`; реестр — ровно 1 строка; на мобильном карточка ниже шапки на 132 px (`--header-h` 116 + 1rem scroll-padding), на desktop — на 27 px; перекрытия шапкой нет. |
| **B2 / U-07** конфликт 409 | **VERIFIED** | 503: в панели ровно один CTA «Повторить сохранение», `primary=0`, `savedText=""`. Повтор из error → 409: в панели ровно один CTA «Обновить данные», retry-кнопки в DOM **0**, `primary=0`, `savedText=""`, зелёного «Сохранено» в тостах нет; POST 1→2 (только сам повтор), клик по «Обновить данные» POST не добавляет (2→2). То же воспроизведено в реальном Chrome. |
| U-01 стекло | VERIFIED | Кандидат не меняет `web/static/**` и CSS (в diff их нет); `ui_win_glass_refraction_e2e` — OK (A21/C4/B10/D2); before/after-кадры прежние. |
| U-03 каталог | VERIFIED | Мой полный `ui_w4_ui_e2e` — failures=0 (проверки сетки/подписи/ключей). |
| U-04 кодовые поля | VERIFIED | failures=0; `pre-wrap`/скроллы не тронуты (в diff только save/layer-логика). |
| U-05 Core / «Развернуть» | VERIFIED | failures=0; остаётся прежнее N1 (фокус после Esc в BODY) — не блокер. |
| U-06 header/крошка | VERIFIED | failures=0; `header.bottom==main.top` на всех вьюпортах. |
| U-08 контраст/motion/polling | VERIFIED | Контраст 9.26/7.67/5.74:1; reduced-motion 0.0 %; polling 0.0 %. |
| U-09 маршрут | VERIFIED | failures=0 для GLOBAL и CHAT. |

## B1 — закрыто, факты

- Механизм: `web/app.js:19902-19937` — `openSpeechLayerRow` теперь async:
  `openSpeechSection('all')` возвращает промис загрузки, `speechQuery =
  block_id`, `speechFamily=''`, `await Promise.all([load, openSpeechBlock])`,
  затем `reveal(true)` в `$nextTick` и повторный `reveal(false)` через 80 мс.
  `reveal` учитывает `.main-header` (`headerBottom`) и `scrollIntoView`.
- Мой прогон `tools/ui_w4_ui_e2e.py` (raw, без правок): `1280/visible_l1` —
  `{top:134, headerBottom:109, visibleH:738, rows:1, inViewport:true}`;
  `390/visible_l1` — `{top:248, headerBottom:116, visibleH:596, rows:1}`;
  writer — те же координаты и свой ключ. Скриншоты моего прогона
  (scratch) визуально совпадают с закоммиченными
  `shots/row_l1_visible_1280.png`, `row_writer_visible_1280.png`,
  `row_l1_visible_390.png`.
- 248 px на 390 — это не «под шапкой»: `top=248 > headerBottom=116`, ключ и
  hit-test видны, на экране 596 px карточки (на 320 — 452 px). Это
  `--header-h` 116 + 1rem scroll-padding на `main.scroll-area`; на desktop
  135/108. Реальный Chrome (активная вкладка) даёт те же числа, что Playwright;
  мой промежуточный замер 132 px был сделан в фоновой вкладке, где
  ResizeObserver не успел выставить `--header-h` (см. ниже).

## B2 — закрыто, факты

- `web/app.js:19793-19798` — любой 409 снимает `speechRetry`;
  шаблоны `web/index.html:7890-7916`, `8136-8157`, `8297-8318` — одна цепочка
  «конфликт → повтор (только без конфликта) → сохранить»; в error акцентный
  Save не рендерится, в конфликте нет retry.
- `web/app.js:19686-19690` + `clearSpeechSaved(...)`/`dismissSpeechSavedToast()`
  в начале каждой попытки — старый «Сохранено ✓» и зелёный тост не переживают
  новую попытку.
- Мой прогон e2e: `390/save_error` — `actions=["Повторить сохранение"]`,
  `activeSaves=0`, `savedText=""`; `390/save_conflict` — `actions=["Обновить
  данные"]`, `retry=false`, `refresh=true`, `activeSaves=0`, `savedText=""`;
  то же на 1280. POST: error→1, retry→2, refresh→2.
- Реальный Chrome (Browser Use, 390): error — `[Повторить сохранение]`;
  conflict — `[Обновить данные]`, `retryBtn=0`, `primaryBtn=0`, `savedText=""`;
  POST 1→2→2; скриншоты сняты.

## Мои прогоны (не переиспользованные)

- `tools/ui_w4_ui_e2e.py`: **failures=0, POST=8, notes=163** (совпадает с
  закоммиченным `ui-report.json`; evidence писал в scratch, прод-каталог
  evidence не менял).
- `tests/ui_p0a_ux_speech_compact_e2e.py`: **failures=0, POST=22**.
- `tools/ui_win_glass_refraction_e2e.py`: **WG-REFRACT-E2E-OK**.
- `tools/ui_asap8_w2_shell_e2e.py`: **W2-SHELL-E2E-OK**, console_errors=[].
- Node: `glass_refraction_test`, `glass_probe_test`,
  `round1025_hotfix10_glass_geometry_bg_test` — все OK.
- pytest (`test_soul1_w6_speech_ui`, `test_webapp_design_tokens_round1025`,
  `test_webapp_nav_disclosure_ui`, `test_webapp_js_unit`,
  `test_ui_verbilizer_tabs_round1023`, `test_webapp_parity_smoke`,
  `test_web_prompts`): **171 passed**.
- `tools/ui_soul1_w6_speech_e2e.py --no-shots`: **failures=2** — те же
  pre-existing «предпросмотр выражения не обновился» (390/1440), что и в
  первом ревью; новых нет. Оговорка: этот инструмент не имеет опции
  перенаправления отчёта и перезаписал
  `plans/features/soul-1/evidence/w6/ui-report.json` (файл и до прогона был
  modified в рабочем дереве; код/тесты/карты не менялись).
- Browser Use: реальный Chrome 320/390/1280 — B1; 390 — 503→409. Скриншоты в
  scratch.

## Скоуп и регрессии

`git show --name-only dd4e0522` — ровно 14 файлов: `web/app.js`,
`web/index.html`, `tools/ui_w4_ui_e2e.py`, evidence (`report.md`,
`ui-acceptance.md`, `ui-report.json`, 8 PNG). `services/**` и
`web/static/**` не тронуты; полигональный фон/цвета/анимация не менялись.
Правки не затрагивают U-01/U-03/U-04/U-05/U-06/U-08/U-09 — полный e2e зелёный.

## Остаточные риски и замечания (не блокируют этот кандидат)

- **N-R2-1 (pre-existing, W6 `a5902b15`).** Клик по строке *реестра* «Все
  инструкции» (77 строк) не прокручивает detail: мой замер — `top=9060` при
  `vh=800`, `scrollY=21`; пользователь видит «мёртвый» клик. Это не 7 рядов
  U-02 и не регрессия dd4e0522. Дешёвая правка на будущее: вызвать тот же
  `reveal` из `openSpeechBlock` (одна точка) или после клика строки.
- **N-R2-2 (pre-existing).** «Обновить данные» снимает конфликт, но черновик
  раздела сохраняется (`state=dirty`, снова «Сохранить»): пользователь не
  видит серверный текст, хотя слепой перезаписи нет — сервер снова ответит
  409. Политика «черновик важнее снапшота» из W6; менять — отдельное решение.
- **N-R2-3 (pre-existing).** Fullscreen-редактор Core (`index.html:11083-11086`)
  не гасит свой Save в состоянии конфликта; payload тот же, сервер reject’ит,
  ложного успеха нет. Косметическая несогласованность.
- **N-R2-4 (pre-existing).** UI не отправляет `expected_updated_at`
  (`web/api/speech.py:1987` его принимает, `app.js:20124` — нет), поэтому
  обычная параллельная правка двух редакторов не даёт 409 (last-write-wins).
  U-07 этого не требует; для одного владельца в 1–2 чатах риск низкий.
- **N-R2-5.** В конфликте рядом с жёлтым тостом остаётся старый красный 503 —
  не «Сохранено», но два разных сообщения; косметика.
- **Риски автора.** «Мобильный detail 248 px» — подтверждаю в реальном Chrome: 248 при header 116,
  видно 596 px (390) / 452 px (320), ключ и hit-test в порядке. Полоса 132 px
  над карточкой — это контекст реестра (заголовок/строка), не перекрытие; не
  блокер. «Серверный стаб» — стенд не доказывает текст
  конкретного блока (fixture один), но доказывает ключ/фильтр/видимость;
  контракт GET `/api/speech/block/{id}` возвращает запрошенный блок. «Конфликт
  только в Playwright» — неверно: 409 воспроизведён в реальном Chrome на
  серверном стабе, а в проде есть реальные 409-ветки (`FactoryConflict`,
  `ChatParamsConflict`, `applied=false`).
- **Стенд-артефакт.** В фоновой вкладке Browser Use `--header-h` остаётся
  пустым (ResizeObserver throttling) — там я получил 132 вместо 248. После
  `activate_tab` переменная = 116/108, и замеры совпали с Playwright
  (248/248/135). Для точных Browser Use-замеров вкладку нужно активировать.

## Requirements gate

`requirements_gate.py check --stage review --slice UI-U02|UI-U07 --candidate
dd4e0522` сейчас падает **только на учётных полях карты**: `candidate_commit`
в карте = `0f3ed53a`, строки `PENDING`. Это работа Orchestrator: после
обновления карты (candidate `dd4e0522`, evidence из этого файла) гейт нужно
перезапустить; к коду претензий нет.

## Можно ли в поезд 2.58.113

**Да.** B1 и B2 закрыты на кандидате `dd4e0522` (координаты/ключ/POST — выше),
регрессий по U-01…U-09 нет, все локальные прогоны зелёные. Остаточные риски —
pre-existing/косметические, не блокируют контролируемый деплой по стоячему
правилу проекта; post-deploy проверки (реальный WebView, живой API) остаются
штатными.

**Артефакт:** `plans/features/asap-speech-arch/evidence/w4/review-r2.md`.
