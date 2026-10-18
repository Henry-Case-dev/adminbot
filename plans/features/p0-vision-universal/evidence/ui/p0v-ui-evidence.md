# P0-Vision / VISION-UI — UI-срез D10–D12 + §4 (Android), 19.10.2026

Срез: `P0V-UI` (`plans/features/p0-vision-universal/requirements-map.json`:
`P0V-UI-NATIVE`, `P0V-UI-REASONS`, `P0V-UI-DISPLAY`, `P0V-UI-OVERFLOW`,
`P0V-UI-SECRETS`). Источник — §4 директивы
(`source-p0-vision-2026-10-19.md:33–38`) + recon D10–D12. Дельта только UI:
`web/app.js`, `web/index.html`, `web/static/app.css` + тесты/инструменты.
Маршруты/сервисы не менялись (вендор `76b156e0` уже отдаёт
`visible_reason/provider/api_type/source` и `base_url/api_type/provider/detail`).

`plans/current_task.md` не изменялся. Прод/SSH в этом срезе не использовались.

## 1. Изменённые/новые файлы (sha12 = `git hash-object`)

| Файл | sha12 | Что |
|---|---|---|
| `web/app.js` | `5ed15703f3ce` | D10: `visionStateLine` method → **computed**; D11: `visionVisibleReason`/`visionProbeResult` (человеческие причины, без кодов); D12: `visionStateFacts` + `visionApiTypeLabel`; `maybeLoadVisionState` грузит state и на вкладке «LLM Провайдеры» (фоновая загрузка — `api(..., {silent403:true})`: без права на ключ нет тоста «Доступ запрещён», fail-open MCA-19 сохранён); `saveBlock('vision')` перечитывает state (свежесть после смены настроек); проба `/api/vision/test` использует `visible_reason`, `state` из ответа сразу в линию/факты |
| `web/index.html` | `6e49c457b131` | D10: `{{ visionStateLine }}` — computed-значение (артефакт `function () { [native code] }` устранён на уровне источника); D12: блок `[data-vision-facts]` в двух местах — секция Vision вкладки «LLM Провайдеры» (строка `data-vision-effective-line`) и карточка модуля «Распознавание изображений» (`workspaceModelCards`) |
| `web/static/app.css` | `2d6f786728a7` | §4/P0V-UI-OVERFLOW: контейнерный трек `.prov-grid` `minmax(min(320px,100%),1fr)`; `.app-shell.ia-v2 .prov-grid` → `minmax(0,1fr)` (без min-content-пола); `.prov-grid > * {min-width:0}`; контракт `.prov-row/.prov-label/.prov-head` (+`@container prov-grid (max-width:479px)` — подпись над полем); `.conn-fact` wrap + `.conn-fact-value` |
| `tools/ui_vision_ui_e2e.py` | `36917e79c68b` | **новый** durable e2e: 26 сценариев (D10/D11/D12/секреты/переполнение/Android-шрифт), `--serve-only` стенд для реального браузера |
| `tests/test_p0_vision_ui_e2e.py` | `e77cb5369ffc` | **новый** pytest-обёртка над e2e (7 проверок контракта) |
| `tests/js/p0_vision_ui_test.js` | `8092b17d9b1d` | **новый** JS-юнит: computed-vs-method, маппинг причин, факты, разметка, `silent403` (403 фоновой загрузки без тоста, флаг не уходит в fetch-init) |
| `tests/test_webapp_ui_rework_round1020.py` | `5789df702a3f` | осознанный re-pin двух CSS-пинов: `.prov-grid` теперь имеет второе верхнеуровневое правило (контейнерный трек) — проверка резолвит эффективный каскад; новые значения закреплены `strictEqual` (не ослаблено) |

## 2. D10 — артефакт `function () { [native code] }` (P0V-UI-NATIVE)

Причина (recon): в `web/index.html` (секция Vision, вкладка «LLM
Провайдеры», якорь `data-vision-effective-line`) печаталось
`{{ visionStateLine }}` как значение, а функция жила в `methods:` → Vue
биндил метод. Исправление — на уровне источника: `visionStateLine` перенесён
в `computed:` (по образцу `stickyFieldFailed`, который, наоборот, ошибочно
лежал в computed). `v-if="b.id === 'vision' && visionStateLine"` теперь
скрывает линию честно: `''` — нет state/403; строка — «Распознавание
работает» / «Не активно: <причина>». CSS/regex-маскировки нет. Проверки:
e2e — `nativeText=false` во всех 26 сценариях (включая «state нет» и все
пробы); JS-тест — значение всегда строка, в `methods` ключа нет, шаблон не
вызывает метод в интерполяции.

## 3. D11 — человеческие причины (P0V-UI-REASONS)

Источник истины — `visible_reason` сервера (`services/mca_vision.
capability_visible_reason`, единый словарь кнопки/линии/витрины). UI
(`visionProbeResult`) показывает его в тосте и inline-статусе; локальный
маппинг (`visionVisibleReason`) — только страховка для неполного ответа и
покрывает ровно классы §2 директивы: конфиг (`api_type_unsupported`,
`vision_key_missing`, `not_configured`), авторизация (`access_error`/`http_401/403`),
нет модели (`model_not_found/http_404`), модальность (`no_vision`,
`image_modality`), плохое изображение (`image_rejected/image_http`), rate
(`rate_limited`, `vision_rate_limited`), timeout, 5xx (`http_5`), пустой ответ
(`empty_completion`), transport, выключенный модуль. Наружу не печатаются
`reason`-коды и `detail`; неизвестное → общая человеческая фраза.

## 4. D12 — факты подключения (P0V-UI-DISPLAY)

`GET /api/vision/state` (`runtime_snapshot`) → computed `visionStateFacts`:
`Провайдер` (host эффективного base_url), `Модель`, `Тип подключения`
(`openai_compatible` → «OpenAI-совместимый»), `Результат проверки`
(`visible_reason` + время `checked_at`), `Техническая деталь` (R17-safe
`detail`, если есть). Секретов state не отдаёт; маска ключа (`••••••••last4`)
не менялась. Факты рендерятся в двух местах: секция Vision вкладки
«LLM Провайдеры» и карточка модуля (вкладка «Модели») — один источник.
Актуальность: state грузится при входе на вкладки (кэш 30 с), после пробы
берётся `state` из ответа, после сохранения настроек Vision кэш сбрасывается
и state перечитывается. Для не-админов серверный гейт state строже видимости
вкладки: фоновая загрузка идёт с `silent403` — 403 → линии/фактов нет, без
тоста «Доступ запрещён» (fail-open MCA-19 сохранён; явные действия
save/test по-прежнему показывают отказ).

## 5. §4 — переполнение и компоновка Android (P0V-UI-OVERFLOW)

Первопричина (замерена): при `max-width:767px` правило
`.app-shell.ia-v2 .prov-grid { grid-template-columns: 1fr }` даёт
`minmax(auto,1fr)` — **min-content-пол**. Строка формы = rem-подпись
(`w-36`: 144px при 16px, 180px при 20px, 216px при 24px) + intrinsic-ширина
`<input>` + padding. При крупном системном шрифте Android (Telegram «Размер
текста», root 20–24px) min-content строки (355–424px) раздувал трек за
контейнер: `main.scroll-area` получал горизонтальный скролл/обрез (376>320,
449>360). Тот же класс дефекта уже был вылечен для `main.scroll-area`
(`minmax(0,1fr)`, комментарий app.css у этого правила) — здесь применено то
же структурное лечение к `.prov-grid` + контейнерный контракт строк:

- `.prov-grid` трек `repeat(auto-fit, minmax(min(320px, 100%), 1fr))` — пол
  320px только когда контейнер ≥320px; уже — одна колонка во всю ширину;
- `.app-shell.ia-v2 .prov-grid { minmax(0, 1fr) }` на ≤767px (без пола);
- `.prov-grid > * { min-width: 0 }`, `.prov-row { min-width: 0 }`,
  `.prov-row .field { min-width: 0 }` — цепочка не раздувает трек;
- `@container prov-grid (max-width: 479px)`: подпись НАД полем (вместо
  55px-поля ключа на 320px), `width:auto/max-width:100%`, `align-items:stretch`;
  скоуп — только контейнер `.prov-grid` (другие секции, где `.prov-row`
  используется вне формы провайдеров, не затрагиваются);
- `.prov-head` переносится, badge не распирает header; переносы —
  `overflow-wrap:anywhere` (НЕ разрыв по буквам).

Стекло/полигон не трогались: диф — только `.prov-grid/.prov-row/.prov-head/
.conn-fact*`; `backdrop-filter/background` правила не менялись.

### 5.1. DOMRect-замеры (Playwright, реальные `web/` байты)

Компоновка «стек» = подпись над полем (узкий контейнер), «ряд» = подпись слева.
На дефолтном шрифте переполнения в этих viewport не было и до фикса (дефект
владельца — D10/D12 + Android-масштаб); строка «до» показывает, что
переполнение появлялось именно при крупном системном шрифте.

| viewport | до: main scrollWidth/client | после: main scrollWidth/client | компоновка после | max right действия |
|---|---|---|---|---|
| 320×640 | 320/320 | 320/320 | стек | 295 (<320) |
| 360×740 | 360/360 | 360/360 | стек | 335 (<360) |
| 390×844 | 390/390 | 390/390 | стек | 365 (<390) |
| 430×932 | 430/430 | 430/430 | стек | 405 (<430) |
| 640×360 (landscape) | 640/640 | 640/640 | ряд | 615 (<640) |
| 844×390 (landscape) | 844/844 | 844/844 | ряд (2 колонки, блок 398) | 397 (<844) |
| **320, root 20px** | **376/320** | **320/320** | стек | 289 |
| **360, root 24px** | **449/360** | **360/360** | стек | 323 |
| 390, root 20px | 390/390 | 390/390 | стек | 359 |
| модуль 320 / 390 | — | 320/320, 390/390 | карточка | 215 |
| модуль, настройки раскрыты 360 | — | 360/360 | стек | 335 |

До фикса на крупном шрифте: `row#N right 355/424`, элементы управления
(`Адрес сервера…`, `Тип API…`, `Модель…`, «Заменить») выходили за viewport;
`documentElement.scrollWidth` при этом оставался равен viewport — переполнение
жило внутри `main.scroll-area` (потому и не ловилось прежними проверками).
После — 0 нарушений по всем 26 сценариям; `console_errors=0` везде.

## 6. Прогоны (финальные байты)

| Проверка | Результат | Артефакт |
|---|---|---|
| `tools/ui_vision_ui_e2e.py` (candidate) | **0 failures / 26 сценариев** | `evidence/ui/e2e_after.json`, шоты `evidence/ui/shots/**` |
| `tools/ui_vision_ui_e2e.py --webroot <HEAD-байты>` | **53 failures / 26** (RED: `[native code]`, нет фактов, коды в тосте, переполнение font20/24) | `evidence/ui/e2e_before.json`, шоты `evidence/ui/before/**` |
| `pytest tests/test_p0_vision_ui_e2e.py` | **7 passed** (~73 с; таймаут поднят точечно) | — |
| `node tests/js/*_test.js` (JS-sweep) | **88 / 0** (было 87; +1 новый) | — |
| `pytest` (все `test_webapp_*` + IA/shell/speech/font-subset + vision/mca19/routes) | **1515 passed** | — |
| `tests/ui_p0a_ux_speech_compact_e2e.py` | **0 FAIL / POST 21** (секция «Речь» не задета) | standalone-прогон |
| `tools/ui_round1025_matrix.py` (19 маршрутов × 8 viewport) | **178 / 178 — идентичный набор** с HEAD-байтами (0 различий; среда без GPU — pre-existing) | сравнение списков |
| `tests/ui_soul1_glass_tiera_e2e.py verify` | **33 pass / 45 fail = ровно как на HEAD-байтах**, diff `checks` = **0/78** (refraction-подмножество — среда/GPU, не правка) | два прогона: worktree HEAD vs candidate |
| Browser Use (реальный Chrome) | 390×844, 390/font20, 844×390, 1280×800, карточка модуля, тост пробы — без переполнения, без техмусора | `evidence/ui/browseruse/*.png` |

Секреты: во всех сценариях `hasRawSecret=false`, `secretInputs=[]` —
значение ключа в DOM не попадает (только `••••••••9f3c`).

Фингерпринт: e2e/JS/pytest-прогоны — финальные байты (`web/app.js
5ed15703f3ce`, `web/index.html 6e49c457b131`, `web/static/app.css
2d6f786728a7`). Сравнения `ui_round1025_matrix` и `ui_soul1_glass_tiera_e2e`
сделаны на кандидате `app.js 4327ea90` (различие с финальным — только
plumbing `silent403` в `api()` и условие успешного текста пробы; разметка/CSS
и раскладка байт-в-байт те же), HEAD-база — worktree-байты `e23a1205/ab8318d5/
6c923166`.

## 7. Остатки и классификация

- **PENDING POST-DEPLOY (не owner-гейт)**: реальный Telegram Android WebView
  (системный «Размер текста», полноэкранный режим) — проверка по факту
  публикации; эмуляция (Chromium + font scale 20/24px) в срезе выполнена.
  Согласно standing-правилу PET_PROJECT ручные device-чек-листы не вводятся.
- **Pre-existing (исправлено попутно, related)**: `tests/test_webapp_tma_fixes_ui.py`
  падал на HEAD из-за слова «break-all» в CSS-комментарии другого среза (blunt
  substring-пин). Комментарии переформулированы без токена — тест снова
  зелёный (17 passed), стиль не менялся.
- **Pre-existing (не моё, не блокирует)**: refraction-подмножество
  `ui_soul1_glass_tiera_e2e.py` (33/45) и 178 замечаний матрицы 1025 —
  идентичны на HEAD-байтах в этой среде (GPU/headless), к правке не относятся.
- **Incidental**: `tests/test_mca01_tx_task_supervisor_round1027.py::
  test_write_points_go_through_single_writer` (из design-note fix-core) —
  вне среза, не перепроверялся.

## 8. Воспроизведение

```
.venv/Scripts/python.exe tools/ui_vision_ui_e2e.py \
  --shots plans/features/p0-vision-universal/evidence/ui/shots \
  --json  plans/features/p0-vision-universal/evidence/ui/e2e_after.json

# стенд для реального браузера (те же API-стабы):
.venv/Scripts/python.exe tools/ui_vision_ui_e2e.py --serve-only --port 8875
#   открыть http://127.0.0.1:8875/#/ai/llm (initData засеян в sessionStorage)
```
