# CFG-04 — дефекты: причина → правка → тест → evidence

Каждый пункт воспроизведён на базовом SHA (master `7a3c1f92`) до правки. «Было»
— измерение в `baseline.json`; «стало» — `after.json` (матрица 7 viewport).

## F1. Две конкурирующие save-CTA (CFG-04B.1, L157)
- **Было:** в dirty одновременно видимы чип-кнопка шапки («N · Сохранить») и
  панель «Сохранить изменения». E2E: `save-CTA = 2` на всех 7 viewport (и в
  config-вкладке, и в модалке модуля).
- **Причина:** D13 (§18I.13) держал чип как кликабельный Save; поздний источник
  L157 меняет роль чипа.
- **Правка:** `web/index.html:176–186` — `<div role="status" data-save-indicator>`
  вместо `<button @click="saveModalEdits()">`; `web/app.js::headerSaveChip`
  отдаёт `actionable:false`, подпись «не сохранено», `title` со счётчиком;
  `web/static/app.css` — нейтральный фон/бордер индикатора (не accent).
  Защита черновика `_dirtyLeaveGuard` не тронута (проверено вручную: закрытие
  dirty-модалки даёт confirm «Есть несохранённые изменения (1) …»).
- **Тесты:** `test_cfg04_forms_contract.py::TestOneSaveFlow` (4),
  `cfg04_forms_contract_test.js` §1, пере-пин `asap8_d1213` (L157).
- **Evidence:** `matrix.md` (CTA b/a), `after.json.config_dirty.cta`, `ui/*` скриншоты.

## F2. safe-area считалась только через `env()` (CFG-04B.2, L158)
- **Было:** `padding-bottom` панели = 7.2 px при сообщённом Telegram safe-area
  56 px; при реальном клиенте кнопки могли уйти в нативную зону.
- **Причина:** `.sticky-save` использовал только `env(safe-area-inset-bottom)`.
- **Правка:** `app.css` — `calc(.45rem + max(env(...), var(--tg-safe-area-inset-bottom),
  var(--tg-content-safe-area-inset-bottom)))`; `.modal-actions` safe-area не
  добавляет (двойного вычета нет, §64 D3).
- **Тесты:** `TestPanelSafeArea` (2), F9-пин «safe-area ровно один раз» сохранён,
  E2E: `panelPadBottom` = base + safe (63.2 / 31.2).
- **Evidence:** `matrix.md` колонка «panel pad b/a».

## F3. `--kb-offset` не двигал геометрию панели (CFG-04B.2, L158)
- **Было:** при клавиатуре 280 px панель оставалась `bottom = 568…860` (ниже
  видимой области) — кнопки под клавиатурой.
- **Причина:** offset применялся только к `scroll-margin`/padding модалки.
- **Правка:** `.sticky-save { bottom: var(--kb-offset, 0px) }`;
  `.modal-card max-height` вычитает kb; `scroll-padding-bottom` панели и
  `.modal-body` = `--sticky-save-h + kb + 4px`.
- **Тесты:** `TestPanelSafeArea::test_keyboard_moves_panel_geometry`, E2E-сценарий
  «kb» (панель и обе кнопки в видимой области, `top >= 0`).
- **Evidence:** `matrix.md` колонка «kb: panel bottom b/a».

## F4. Фиксированная высота панели `4.5rem` (CFG-04B.3, L159)
- **Было:** на 320/360 панель переносится (факт. 168.4 px), а запас прокрутки
  остаётся 72 px → последнее поле может оказаться под панелью (запас −28 px до
  правки при `scrollIntoView block:end`).
- **Причина:** статический токен `--sticky-save-h: 4.5rem`.
- **Правка:** `app.js::_syncPanelHeight` (+`ResizeObserver`) пишет измеренную
  высоту (max по видимым `.sticky-save`), clean → `0px`; CSS-токен остаётся
  fallback-значением. `scroll-padding-bottom`/`scroll-margin-bottom` считаются
  от него + kb + 4 px. M-1 сохранён: `padding-bottom` контейнера = 0.
- **Тесты:** `TestLastField` (3), E2E «last_field» (`overlap ≤ 0`, каретка видна).
- **Evidence:** `matrix.md` «panel h b/a» и «last-field overlap b/a».

## F5. Голый `truncate` технического ключа (CFG-04C.3, L167)
- **Было:** 18 карточек показывали ключ с `font-mono truncate` без `title`,
  раскрытия и копирования — полное значение недоступно (на 320 обрезано).
- **Правка:** компонент `<tech-key>` (title, раскрытие `aria-expanded` с переносом,
  «копировать» через Clipboard API + фолбэк `execCommand`, `data-copied`),
  все 18 мест (config, relations, permsoc-карточки, speech/prompt workspace).
  Русское название/описание/значение остаются отдельными элементами.
- **Тесты:** `TestTechnicalKey` (3), `cfg04_forms_contract_test.js` §3, E2E:
  `truncated=false` после раскрытия, clipboard == полный ключ на каждом viewport.
- **Evidence:** `after.json.tech_key_open/copy`, скриншоты `ui/after`.

## F6. Touch-зоны меньше 44 px (CFG-04C.2, L166)
- **Было:** переключатель 44×24, «Сохранить» 37.6 px, «Отмена» 38.0 px.
- **Правка:** `.card .param-toggle { min-width:44px; min-height:44px }`,
  `.sticky-save .btn-accent/.btn-ghost { min-height:44px }` (визуальный трек
  переключателя не менялся).
- **Тесты:** `TestLayoutAndTouch`, E2E (toggle 44×44, кнопки ≥44).

## F7. Поворот терял прокрутку (CFG-04A.1, L153)
- **Было:** 390×844 → 844×390: `scroll 220 → 0`, активное поле терялось
  (ввод/маршрут/dirty сохранялись, т.к. живут в Vue).
- **Причина:** на mobile скроллится `.scroll-area`, на compact/desktop — документ;
  при смене shell-ветки DOM пересоздаётся, позиция не переносилась.
- **Правка:** `_captureEditViewport`/`_restoreEditViewport`/
  `_preserveOnViewportChange` (вызывается из `_onResize`); позиция переносится в
  тот контейнер, который сейчас скроллится; фокус/каретка — best effort по
  `data-cfg-key`. Конфиг на resize не перезагружается.
- **Тесты:** `TestOrientation` (3), `cfg04_forms_contract_test.js` §4, E2E
  orientation: `scroll_ok`, `active_ok`, `dirty_ok`, `hash_ok`, `value_ok`.
- **Evidence:** `after.json.orientation`.

## Не дефекты (проверено, поведение сохранено)
- Dirty value-based, возврат к исходному снимает индикатор (`TestDirtySaveContract`).
- Сохранение ждёт ack; baseline не сдвигается при ошибке; «Отмена» откатывает
  только текущую форму (тесты + чтение `saveModalEdits`/`cancelModalEdits`).
- Один write-path: `persistItems`/`saveModalEdits` по одному вхождению.
- Glass/фон/палитра: токены не изменены (`TestProtectedSurfaces`), 178 проверок
  широкой матрицы совпадают с master (см. `blast-radius.txt`).
