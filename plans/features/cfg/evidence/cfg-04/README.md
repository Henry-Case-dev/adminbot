# CFG-04 — мобильные формы MiniApp: один save-сценарий, dirty, панель, ключ, поворот

**Кандидат:** master `7a3c1f92` + правки этого лейна (без коммита; независимое ревью следующим шагом).
**Дата:** 20.10.2026 (UTC+12). **Прод не затрагивался**, SSH не использовался.
**Источник требований:** `plans/features/cfg/source-cfg-addendum.md`
L149/L153/L157–L161/L165–L169/L173–L177; карта CFG-04 (20 строк);
подготовка — `prep-cfg-04.md`.
**Тестовая жизнь:** `tests/test_cfg04_forms_contract.py` и
`tests/js/cfg04_forms_contract_test.js` — `TEST-LIFECYCLE: CONTRACT/REGRESSION owner=CFG-04`.

## Что исправлено (видимые дефекты)

| # | Дефект (было) | Причина | Правка |
|---|---|---|---|
| 1 | **Две одновременные save-CTA** на mobile: чип в шапке (`index.html:176–184` + `app.js:3094–3108`) и панель `<sticky-save>` | D13 держал чип как кликабельный Save; поздний L157 меняет его роль | Чип → **не-CTA индикатор** `role="status"`/`data-save-indicator` («N · не сохранено»), единственное сохранение — панель. `_dirtyLeaveGuard` (защита черновика) сохранён |
| 2 | **safe-area только `env()`** (`app.css:1898`) | Telegram Android сообщает нижнюю зону и через `--tg-safe-area-inset-bottom` / `--tg-content-safe-area-inset-bottom` | `padding-bottom: calc(.45rem + max(env(...), var(--tg-safe...), var(--tg-content-safe...)))` — **ровно один раз**; `.modal-actions` по-прежнему без safe-area (D3) |
| 3 | **`--kb-offset` не двигает панель** | offset применялся только к `scroll-margin`/padding модалки | `bottom: var(--kb-offset, 0px)` у `.sticky-save`; `.modal-card` ужимается на клавиатуру; `scroll-padding` панели/модалки = высота панели + kb + 4 px |
| 4 | **`--sticky-save-h: 4.5rem` не соответствовал панели на 320 px** (панель переносится) | фикс. токен | `app.js::_syncPanelHeight` (+ ResizeObserver) пишет **измеренную** высоту в `--sticky-save-h`; clean → 0. Токен в CSS остался fallback-значением |
| 5 | **Ключ — голый `truncate`** без title/копирования/раскрытия (18 мест) | не было affordance | Компонент `<tech-key>`: `title`, раскрытие (`aria-expanded`, перенос строк), «копировать» (Clipboard API + фолбэк), `data-copied` |
| 6 | **Touch-зоны**: переключатель 44×24, кнопки панели 37–38 px | наследие компактных стилей | `.card .param-toggle` ≥44×44; `.sticky-save .btn-accent/.btn-ghost` `min-height:44px` |
| 7 | **Поворот терял прокрутку** (mobile ↔ compact меняет скроллер: `.scroll-area` → документ) | позиция не переносилась | `_captureEditViewport`/`_restoreEditViewport`/`_preserveOnViewportChange`, поля размечены `data-cfg-key`; значение/dirty/маршрут и так живут в Vue |

## Метод и доказательства

- **Статический контракт (код/review):** `tests/test_cfg04_forms_contract.py` (29 проверок, CSS парсится по селекторам, не по подстроке) и `tests/js/cfg04_forms_contract_test.js` (поведение компонентов: индикатор, измерение панели, tech-key, поворот, dirty).
- **RED→GREEN:** `red-green.txt` (13 падений на базовом SHA по дефектам B.1/B.2/B.3/C.2/C.3/A.1; после — 0).
- **Геометрия until/after:** `baseline.json` (master `7a3c1f92`, отдельный worktree) и `after.json` (кандидат), сводка — `matrix.md`.
- **Матрица:** 320×640, 360×740, 390×844, 430×932 (портрет) и 667×375, 844×390, 915×412 (ландшафт), DPR 2/3, `is_mobile/has_touch`; синтетический Telegram chrome: 56 px портрет / 24 px ландшафт; клавиатура — эмуляция `--kb-offset` (портрет до 280 px, ландшафт ~½ высоты).
- **Скриншоты:** `ui/before/*.png`, `ui/after/*.png` — 14 на сторону: 7 режимов
  `*-config-dirty.png` (config-вкладка) + 7 `*-module-dirty.png` (модалка модуля).
- **Визуальная проверка:** Playwright-матрица (`tools/ui_cfg04_forms_e2e.py`) **и** реальный рендер в Browser Use на `--serve` (статика + те же `/api`-стабы + TMA-стаб) — `visual-check.md`.

## Принятые решения

1. **Один основной сценарий сохранения** (L157): панель — CTA; шапка — статус-индикатор. На desktop второй доступ к тому же действию отсутствует (чип нигде не кликабелен) — конфликтующих сохранений нет ни в одном viewport.
2. **Safe-area ровно один раз** в `.sticky-save`; `.modal-actions` её не добавляет (инвариант §64 D3 / F9-пин сохранён).
3. **Фиксированная высота панели запрещена**: запас считается от измеренной высоты; 4 px подстраховки от субпиксельного округления.
4. **Один движок dirty/save** (F0/F9) не переписывался: value-based dirty, ack сервера, baseline не сдвигается при ошибке, «Отмена» откатывает только текущую форму — подтверждено тестами и повторно кодом.
5. **Protected:** `param_catalog.py`/backend не тронуты (Δ каталога = 0, DDL = 0); glass-токены, фон, палитра, навигация, fullscreen, логотип не менялись.

## Честные ограничения

- **TMA-стаб ≠ реальный Telegram WebView.** Playwright и Browser Use видят одинаковую верстку, но реальную клавиатуру/жесты сообщает только клиент → D.4 (живые приёмки) остаётся `PENDING_OWNER_E2E`; фиктивного PASS нет.
- **Клавиатура эмулирована** через `--kb-offset` (visualViewport-формула). Реальная высота клавиатуры в Android/iOS различается.
- **Telegram chrome синтетический** (56/24 px): точные величины сообщает клиент; формула `max(env, --tg-safe, --tg-content-safe)` проверена на ненулевых переменных.
- **Эмуляция поворота** в E2E — `set_viewport_size` (Playwright) и `Emulation.setDeviceMetricsOverride` (Browser Use); реальный поворот с открытой клавиатурой — зона D.4.
- **Прод-лейн** (деплой 2.58.x, preprod/postdeploy проверки B.1/B.2/B.3/C.1/C.2/C.4/C.5/A.1/D.1/D.5) — вне этого лейна.

## Быстрый прогон

```powershell
py -3 -m pytest tests/test_cfg04_forms_contract.py -q
node tests/js/cfg04_forms_contract_test.js
.venv\Scripts\python.exe tools\ui_cfg04_forms_e2e.py           # after.json + ui/after
.venv\Scripts\python.exe tools\ui_cfg04_forms_e2e.py --baseline  # baseline.json + ui/before
.venv\Scripts\python.exe tools\ui_cfg04_forms_e2e.py --serve     # ручной осмотр (Browser Use)
```

## Кандидат: файлы и sha12 (полный sha256 — в `e2e-log.json`)

| файл | sha12 |
|---|---|
| `web/app.js` | `885094459700` |
| `web/index.html` | `528f358a6589` |
| `web/static/app.css` | `6b5ca0cc1d47` |
| `tests/test_cfg04_forms_contract.py` | `7cf6681c255e` |
| `tests/js/cfg04_forms_contract_test.js` | `b2cd731dcc35` |
| `tests/js/asap8_d1213_save_contract_test.js` | `afba6b969e89` |
| `tests/js/round1021_ui_audit_test.js` | `3f26c301045c` |
| `tests/test_webapp_ui_rework_round1020.py` | `d9cbca971155` |
| `tools/ui_cfg04_forms_e2e.py` | пересчитывается в `e2e-log.json.tool_sha256` |

База: master `7a3c1f92` (на момент лейна HEAD параллельно ушёл вперёд на
`c48fe4cf` из-за соседнего поезда add-exp/CFG-05-prep; `web/*` эти коммиты не
затрагивали — baseline снят в отдельном worktree на `7a3c1f92`).

