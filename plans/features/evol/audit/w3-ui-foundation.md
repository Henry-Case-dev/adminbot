# W3 — UI foundation: health glass (EVOL-032) + token layer (EVOL-022)

Лейн: `w3-ui-foundation`. Ветка `evol/impl`, база `407e01fa`, изменения НЕ
закоммичены (по указанию оркестратора).

Основание: `plans/current_task.md` EVOL-032 (L447–476), EVOL-022 (L302–310),
привязка `plans/features/evol/arch/contracts.md` → **CONTRACT 2** (L313–440).

## 1. Кандидат и файлы

| Файл | Статус | sha256 (12) |
| --- | --- | --- |
| `web/app.js` | M (+454) | `1222A40A0281` |
| `web/index.html` | M (+53/−8) | `10CFA9D29892` |
| `web/static/app.css` | M (+138) | `3FFFCD606EA2` |
| `web/static/glass-refraction.js` | M (+16) | `8E28D0A64882` |
| `tests/js/evol032_health_glass_test.js` | new | `ABF666FEA827` |
| `tests/test_evol032_health_glass.py` | new | `2047E82864FB` |

Защищённая оптика (`web/static/glass.js`, `polygon-background.js`,
`aurora-flow.js`, `vendor/liquidglass.*`) — **нулевой diff** к `HEAD`,
подтверждено и `git diff` (пусто), и побайтовым sha256 в тесте (см. §7).

## 2. Механизм тонирования (и почему он не трогает физику стекла)

Реализован ровно путь CONTRACT 2 §2.2 — **цветовая составляющая уже
существующей заливки карточки**, без нового слоя:

- корень карточки получает `data-health-state` и `data-health-material`
  (`bg`/`strong`); заливку меняет селектор из двух атрибутов:
  `[data-health-state="degraded"][data-health-material="bg"]` →
  `rgba(91,55,67,.5)` (32 % `--err` `#F07178` + 68 % `rgb(21,27,42)`),
  `failed` → `rgba(141,74,85,.5)` (55 %); для `strong` те же RGB с alpha
  `0.85`. Alpha нормального материала (`--glass-bg`) остаётся байт-в-байт.
- `normal / unknown / disabled` **не получают** правил `background-color`.
- Не меняются: `backdrop-filter` / `url(#lg-lens)`, blur, saturate, радиус,
  border, `::before`/`::after`, z-index, padding, размеры. Нет `box-shadow`,
  второго blur, overlay, canvas и «второй рамки».
- Единственный механизм состояния — data-атрибуты. Дублирующий класс-маркер
  (`health-tint*`) из прерванной попытки **удалён**: он ничего не рисовал и
  создавал второе, не по контракту, представление состояния.

### 2.1 Решение по `glass-refraction.js::refreshTint()`

Проверял по букве контракта (§2.2, L357): «Слой `glass-refraction.js`:
добавить `refreshTint(el)`. На смене `data-health-state` перечитать
`surfaceTint(el)` в уже существующую запись и не пересоздавать canvas, не
менять размеры, маску, filter id, z-index. Если записи слоя нет — no-op».

**Решение: оставить (не откатывать).** Diff — 16 строк, ровно один новый
метод и его экспорт:

```js
function refreshTint(el) {
  if (!el || !st.layers || !st.layers.length) return false;
  var hit = false;
  for (var i = 0; i < st.layers.length; i++) {
    var rec = st.layers[i];
    if (!rec || rec.surface !== el) continue;
    try { rec.tint = surfaceTint(el); } catch (e) { /* прежний tint */ }
    hit = true;
  }
  return hit;
}
```

Доказательства, что это НЕ изменение физики/оптики:

- пишется только поле `rec.tint = {color, alpha}`; `surfaceTint()` — уже
  существующая функция, снимающая `backgroundColor` поверхности с уже
  существующим капом alpha `0.8` (не менялась);
- в теле нет `makeLayer`, `appendChild`, `removeLayer`, `canvas.width`,
  `applyRingMask`, `filter`, `z-index` — тест это утверждает регэкспом
  (`refreshTint does not rebuild the layer, mask, filter or z-index`);
- рецепт слоя (`blur(5px) saturate(140%) url(#lg-refract-lens-N)`), маска,
  радиус, DPR, интервалы отрисовки не тронуты;
- цвет подложки читается в `rebuild()` (как и раньше) и на кадре отрисовки
  применяется `ctx.globalAlpha = tint.alpha; fillStyle = tint.color` — это
  та же самая подложка поверхности, которая кладётся поверх преломлённых
  пикселей с тем же alpha (комментарий `U-01/U-02` в файле).

Замерено в реальном рендере (Tier A, слой активен): у проблемного корня
`backdrop-filter` нормали и сбоя совпадает
(`blur(5px) saturate(1.4) url("#lg-lens")`), у слоя тот же `z-index:-1`,
тот же радиус 22px, та же маска, тот же `<canvas>` (проверено маркером на
элементе: `layerStillSame = true`, количество слоёв 3 → 3).

Поэтому CSS-путь остаётся **основным**, а `refreshTint()` — только
синхронизация уже существующего слоя на клиентах, где `url()` внутри
`backdrop-filter` не рендерится (Android WebView/WebKit), чтобы слой-носитель
не держал старый цвет до resize.

### 2.2 Синхронизация с eased-переходом

CSS анимирует `background-color` 420 ms, а canvas-слой CSS-transition не
наследует и переключился бы скачком. Компонент `health-glass-surface`:

1. сразу вызывает `__GlassRefraction.refreshTint(root)`;
2. читает фактическую `transition-duration` корня; если она `0s`
   (`prefers-reduced-motion: reduce` → `transition: none`) — на этом всё,
   состояние мгновенное;
3. иначе ограниченный `requestAnimationFrame`-цикл ровно на длительность
   перехода (`+64 ms` запас, ≤ ~30 кадров), в котором подложка перечитывается
   и слой догоняет интерполяцию; отмена при смене состояния/размонтировании.

Физику это не меняет: меняется только `rec.tint`, как в §2.1.

## 3. Состояния

| state | заливка | текст/иконка | бейдж (существующий) |
| --- | --- | --- | --- |
| `normal` | без изменений (`--glass-bg`) | «Норма» + `monitoring` | `badge-ok` |
| `degraded` | `rgba(91,55,67,.5)` / `.85` | «Проблема» + `stop`, `--err-text` | `badge-err` |
| `failed` | `rgba(141,74,85,.5)` / `.85` | «Сбой» + `stop`, `--err-text` | `badge-err` |
| `unknown` | **нет** красной заливки | «Неизвестно» + `help`, янтарь `--warn` | `badge-warn` |
| `disabled` | **нет** заливки | «Выключено» + `visibility_off`, `--text-3` | `badge-muted` |

Плюс краткая причина и время последнего достоверного состояния, если источник
их дал (причина обрезается в одну строку, дата — отдельным span).

Внешнего свечения нет намеренно (CONTRACT 2 §2.2: gap сетки 12 px, мягкий
`box-shadow` читается как авария соседа).

### Геометрия при смене состояния

Строка статуса имеет фиксированную высоту (`--space-6` = 24 px),
`flex: 0 1 auto; min-width: 0; max-width: 100%`, потомки сжимаются и
обрезаются (`text-overflow: ellipsis`), а не переносятся. Измерено в браузере
(ширины 320/390/768/1280/1920): `getBoundingClientRect` корня при
`normal → failed` **идентичен**, горизонтального скролла страницы нет.

### Transition / reduced motion

```css
[data-health-state] { transition: background-color 420ms cubic-bezier(.2,0,0,1); }
@media (prefers-reduced-motion: reduce) { [data-health-state] { transition: none; } }
```

Замерено: смена `degraded → normal` даёт плавную интерполяцию
`rgba(91,55,67,.5) → … → rgba(21,27,42,.5)` за ~414 ms; при эмуляции
`prefers-reduced-motion: reduce` — `transition-duration: 0s`, цвет меняется
мгновенно. Никакие другие свойства не анимируются.

## 4. Доступность

- цвет — дополнительный канал: рядом всегда текстовый статус, иконка из
  существующего набора Material Symbols и `aria-label` корня
  (`«Бот, Сбой, polling_error»`);
- `aria-live="polite"` — на строке статуса (`role="status"`), не на карточке;
- корень получил `role="group"`, иначе `aria-label` на `div` без роли
  игнорируется скринридерами;
- при тонировании текст/цифры остаются на `--text-1` / `--text-2`;
- hover/pressed не снимают `data-health-state` (нет таких правил);
- ссылка на причину — только у бота и только в состоянии проблемы/сбоя, на
  **существующий** маршрут `#/oversight?tab=incidents` (deep-link читается
  `oversightApplyDeepLink`, `normalizeRoute` отбрасывает query).

## 5. Покрытые карточки

| Карточка | Форма | Scope |
| --- | --- | --- |
| «Бот» (`status-hero`) | `health-glass-surface` (стеклянный корень) | `global` |
| «Сон / Глубокий сон» | `health-glass-surface` | активный чат / `global` |
| «Опыт» | `health-glass-surface` | активный чат / `global` |
| Сердцебиение (секция `.status-block__pulse`) | только текст+иконка+aria | `global` |
| «Бот» (секция `.status-block__bot`) | только текст+иконка+aria | `global` |
| «Здоровье памяти» | только текст+иконка+aria | `global` |
| «Распознавание изображений» (смежные контуры) | только текст+иконка+aria | активный чат / `global` |

Общий `.status-block` (сердцебиение + бот + сервер в одной стеклянной
карточке) **не дробился** и не красится целиком — CONTRACT 2 §2.3 прямо
запрещает это в этой волне; красное стекло только у корней, которые уже
являются отдельной стеклянной карточкой одной подсистемы.

Per-card изоляция: заливка включается двумя атрибутами на конкретном корне;
custom property на `:root`/`.status-block` не выставляется. Проверено на двух
карточках в одном дереве: проблемная красная, соседняя — нормальный материал.

## 6. Источник статуса (только существующие эндпоинты)

Адаптер `healthStateFrom(subsystem, payload, scope)` в `web/app.js`; не парсит
логи, слово `error`, CSS и проценты.

| Подсистема | Источник | Решение |
| --- | --- | --- |
| Бот | `GET /api/status` → `bot.state` | `running/polling` → normal, `polling_error` → failed, `stopped/disabled` → disabled, `starting`/нет поля → unknown |
| Сердцебиение | существующий `hbState`/`hbReason` после `_heartbeatTransition` (пороги 0.90/0.70/0.65, dwell N=2 не копируются) | `healthy/warning/critical/unknown` → normal/degraded/failed/unknown |
| Память | `GET /api/memory/health` | счётчики и нули — не вердикт; ошибка запроса → unknown + причина |
| Сон / глубокий сон | `GET /api/memory/cognition/status` (`dream`, `deep_sleep`, `last_run_at`) | `enabled=false` у **обоих** → disabled; есть `running` или `last_run_at` → normal; включено, но прогонов не было → unknown («включено, прогонов ещё не было») |
| Опыт | `GET /api/status` → `experience` (`disabled/not_run/implemented/unavailable`) | disabled → disabled, implemented → normal, not_run/unavailable → unknown |
| Vision | `GET /api/vision/state` | вердикта распознавания в payload нет → unknown (HTTP 200 сам по себе не норма и не сбой) |
| Процесс (`/healthz`, `/api/health`) | — | всегда unknown, карточку не красит |

Не красят сами по себе: HTTP 200, один WARN, `errors_total`, скачок метрики,
пустая выборка, stale-снимок, чужой `chat_id`, выключенный модуль.

Устаревание: `stale` → unknown + «данные устарели»; фронтового таймера
«подержать красный» нет — снятие только по смене достоверного состояния.

Scope: cognition/vision запрашиваются с контекстом активного чата
(`chat_id` / `X-Chat-Id`), поэтому карточки объявляют `healthScope`, а не
жёсткий `global`; `api/status`/`memory/health` — global.

### Честные пробелы бэкенда (не правились, `services/**` вне scope)

1. `/api/vision/state` не отдаёт вердикт распознавания (`recognition_verdict`/
   `health_status`) — карточка Vision осознанно не краснеет.
2. `/api/memory/health` отдаёт счётчики/хранилище без поля-вердикта функции —
   «Память» остаётся unknown, пока такое поле не появится (иначе был бы ложный
   красный по тишине данных).
3. `/api/memory/cognition/status` не отдаёт `chat_id` в payload — изоляция
   чужого чата выполняется на сервере (`chat_id`/`X-Chat-Id`), адаптер не может
   перепроверить её сам.
4. CONTRACT 2 §2.4 требует, чтобы «бейдж и стекло читали один и тот же
   `hbState`». Существующий бейдж сердцебиения построен на legacy-порогах
   0.5/0.8 (`C2-OFF`, утверждённый откат) — переключение бейджа на `hbState`
   меняет утверждённую оптику, поэтому в этой волне не делалось: он показывает
   нагрузку, а health-текст идёт отдельной строкой.
5. Для «Медиа» адаптер есть (`GET /api/status/media-health`), но подходящей
   отдельной стеклянной карточки в «Статусе» нет — правило заведено, карточки
   нет; появится вместе с карточкой в `EVOL-033`.

## 7. Проверки

Команды (cwd = worktree), все PASS:

| Проверка | Результат |
| --- | --- |
| `python -m pytest tests/test_evol032_health_glass.py -q` | 4 passed |
| `node tests/js/evol032_health_glass_test.js` | `EVOL032-OK` |
| `node tests/js/round1020_ui_test.js` | `JS-UNIT-OK` |
| `node tests/js/round1020_ui_rework_test.js` | `JS-UNIT-OK` |
| Регресс структуры/токенов: `test_status_section_ui_merge_round1019`, `test_webapp_f11_round1025`, `test_webapp_hotfix10_round1025`, `test_font_subset`, `test_frontend_tab_mapping` | 116 passed |
| Регресс дизайн-токенов/полигонов/форм: `test_webapp_design_tokens_round1025`, `test_webapp_round1020_ui`, `test_webapp_ui_rework_round1020`, `test_webapp_round1026_polygon`, `test_cfg04_forms_contract`, `test_ia_shell_round1025` | 157 passed |

Что именно утверждают тесты:

- **маппинг state → атрибут**: `polling/running` → normal, `polling_error` →
  failed, `stopped` → disabled, `starting`/нет поля/HTTP 200 → unknown,
  `hbState warning` → degraded и не failed, `sleep enabled=false` (оба
  рубильника) → disabled, включено без прогонов → unknown, чужой `chat_id` не
  красит;
- **нейтральные состояния**: `unknown`/`disabled` → `paints=false`, в CSS нет
  правил заливки для `normal/unknown/disabled`;
- **текст рядом с цветом**: в отрендеренных корнях присутствует «Норма» /
  «Сбой», `aria-label` содержит подсистему и статус;
- **изоляция соседа**: две карточки в одном дереве, у проблемной
  `data-health-state="failed"`, у соседа `normal` и нет проблемных атрибутов;
- **reduced-motion**: в CSS `transition: none` под
  `prefers-reduced-motion: reduce`; `transitionMs()` возвращает 0 для `0s` и
  420 для `0.42s`; при нуле rAF-цикл не запускается;
- **только цвет заливки** в переходе (нет `filter/backdrop-filter/transform/
  box-shadow/width/height`);
- **хеш защищённых файлов**: `glass.js`, `polygon-background.js`,
  `aurora-flow.js` (+ vendor `liquidglass`) сравниваются с blob `HEAD`
  побайтово по sha256 и через `git diff` — совпадение;
- **`refreshTint`**: перечитывает `rec.tint` и не содержит вызовов
  пересоздания слоя/маски/фильтра/z-index.

### Живой рендер (Playwright + Browser Use)

Стенд — отдельная probe-страница вне репозитория
(`WorkspaceData/runs/.../glass-probe.html`) с **байт-в-байт копиями**
`app.css`, `polygon-background.js`, `glass-refraction.js`, шрифта иконок и
картой линзы `#lg-lens` из `index.html`; карточки — те же классы/атрибуты.
Фон — настоящий полигональный canvas, слой преломления активен
(`diagnostics().reason = 'active'`, 3 слоя).

Замеры (Chromium, Tier A):

| Проверка | Норма | Сбой |
| --- | --- | --- |
| `background-color` | `rgba(21,27,42,.5)` | `rgba(141,74,85,.5)` |
| `backdrop-filter` | `blur(5px) saturate(1.4) url("#lg-lens")` | идентичен |
| alpha | 0.5 | 0.5 (не 1) |
| `getBoundingClientRect` | 480×104.67 | идентичен |
| элемент слоя | тот же `<canvas>` (маркер сохранился) | тот же |
| слои | 3 | 3 |

Дополнительно: `degraded` = `rgba(91,55,67,.5)`, `unknown` = нормальная
заливка; ширины 320/390/768/1280/1920 — высота корня при смене состояния
неизменна, `scrollWidth == innerWidth`; `prefers-reduced-motion` — мгновенно.

Скриншоты (одна и та же пауза фона, отличаются только состояния):
`plans/features/evol/audit/evidence/evol032-1280.png`,
`.../evol032-390.png`.

Ограничение стенда: в probe-окружении не подхватываются лигатуры шрифта
иконок, поэтому вместо глифа видно текстовое имя (`monitoring`/`stop`/`help`).
Это артефакт стенда (в приложении шрифт грузится штатно), отображение иконок
проверено на уровне разметки/маппинга в тестах.

## 8. Слой токенов EVOL-022

Добавлено **в существующий** `:root` рядом с `--glass-bg`/`--card-bg`; второго
набора переменных нет, живые имена (`--radius-*`, `--glass-border`) не
переименовывались:

- `--border-hairline: 1px`;
- `--radius-xs` (= существующий `--radius-sm`), `--radius-xl: 16px`;
- ритм `--space-1..--space-8` = 4/8/12/16/24/32;
- высоты контролов `--control-h-sm: 32px`, `--control-h: 40px`,
  `--control-h-touch: 44px`;
- заготовки `--btn-h/--btn-h-sm/--btn-radius/--btn-hairline/--toggle-h/--toggle-hit`.
  На `.btn-*`/`.module-toggle` этой волной **не навешены** — иначе сдвинулась
  бы существующая геометрия контролов (это `EVOL-043`);
- health-токены `--health-fill-*`, `--health-dur: 420ms`, `--health-ease`.

Страницы токенами не перекрашивались: волна добавляет фундамент, потребители —
следующие срезы `EVOL-0xx`.

## 9. Находки по ходу (не блокеры этого лейна)

- `--tx-tiny`, `--warn`, `--err-text`, `--radius-sm/lg`, `.msr` — существующие,
  новых дублей не создано; темы/light-режима в проекте нет (`data-theme`,
  `prefers-color-scheme` не используются), поэтому жёсткие RGB контракта
  консистентны.
- `.health-glass-status` добавляет карточке постоянные 24 px + 8 px отступа.
  Это одинаково для всех состояний (смена состояния геометрию не меняет), но
  визуально карточки «Бот»/«Сон»/«Опыт» стали выше на одну строку — это плата
  за обязательный текстовый статус рядом с цветом.
- В общем `.status-block` рядом с health-строкой остаётся legacy-бейдж
  нагрузки (см. §6, п.4). Расхождение смыслов («спокойный 12 %» против
  «Норма») требует решения в `EVOL-033`, когда секции разъедутся по своим
  стеклянным корням.

## 10. Итог

- Защищённая оптика: нулевой diff, побайтовые хеши совпадают с `HEAD`.
- Тонирование: только RGB существующей заливки, alpha нормали, переход только
  по `background-color`, reduced-motion мгновенный, геометрия неизменна,
  соседи не затронуты.
- `refreshTint()` не расширен за рамки контракта: 16 строк, только `rec.tint`.
- Состояния и тексты покрывают normal/degraded/failed/unknown/disabled,
  источник — только существующие эндпоинты, пробелы перечислены честно.
- Тесты: 4 pytest + 3 node-набора + 273 структурных регресса — PASS.
