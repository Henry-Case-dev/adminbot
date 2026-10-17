# FS-ARCHAEOLOGY — fullscreen: прежняя рабочая версия, замена v6.3, минимальное восстановление

READ-ONLY разведка (git show/log/diff + чтение). Дерево не менялось. Дата: 2026-10-18.
Рев: prod=`448cc81a` (ветка `release/incident-2.58.83`, база `6d4b9a7d`=2.58.81), master=`9d8da1d7` + незакоммиченный W7.

## 0. Главный вывод

Замену сделал ОДИН коммит `c0535280` (asap8-v6.3 W2, U07, 15.10.2026), и он **уже на проде**
(`git merge-base --is-ancestor c0535280 448cc81a` → YES). FS-контур prod == master: фильтр полного
diff `448cc81a..HEAD` по токенам `fs-|fullscreen|header-fs` даёт **0 строк** в `app.js`, `index.html`, `app.css`;
`web/static/fullscreen-policy.js` — один и тот же blob (`18ee7ed72f`) в prod и master.
Единственное отличие — **незакоммиченный** W7-слой (SOUL-12.x), которого в проде нет.

## 1. Прежняя рабочая реализация (до v6.3) — `4b64b38e` = `c0535280^`

Кнопка всегда видима и напрямую дёргает SDK:

- `4b64b38e:web/index.html:165-169` — `<button v-if="me" class="btn-ghost ... header-fs-btn"
  :title="isFullscreen ? 'Выйти из полноэкранного режима' : 'Полноэкранный режим'"
  :aria-pressed="isFullscreen ? 'true':'false'" @click="toggleFullscreen()">⛶</button>` (глиф ⛶, без `fsSlot`).
- `4b64b38e:web/app.js:12802-12831` `toggleFullscreen()` — прямой SDK: вход `wa.requestFullscreen()` →
  `wa.requestFullScreen()` → `wa.expand()`; выход `wa.exitFullscreen()` → `wa.expand()`;
  далее: если SDK не даёт boolean `isFullscreen` — legacy-инверсия `this.isFullscreen = !this.isFullscreen`,
  если даёт — re-read через microtask + rAF.
- `4b64b38e:web/app.js:12835-12867` `initFullscreen()` (guard `_fsSubscribed`, подписки `fullscreenChanged`+`viewportChanged`);
  `12869-12898` `setFullscreenFromTma()` + redraw (`_hbResize`, `_auroraResize`); `12900-12911` `teardownFullscreen()`.
- CSS: `4b64b38e:web/static/app.css:1001` (legacy `order:99`), `1008-1012` (compact: `order:5;margin-left:auto;
  min-width/height:44px;inline-flex`). **Кнопка в потоке row A; float-правил и принудительного padding-top у шапки НЕТ.**
- Хаков `window.moveTo/resizeTo/WinAPI` не было ни до, ни после (grep; запрет U07.0).

## 2. Что изменила замена v6.3 (c0535280; в проде)

- Новый единственный источник — `web/static/fullscreen-policy.js`.
- Кнопка: `v-if="me"` → `v-if="me && fsSlot !== 'hidden'"` + `:class="'fs-slot-'+fsSlot"`
  (`web/index.html:191-201`; prod `448cc81a:web/index.html:191`).
- **Скрытие на tdesktop**: `web/static/fullscreen-policy.js:73-81` `slotFromGeometry()` —
  `if (platform === 'tdesktop') return 'hidden'`; `88-121` `decideOffer()` → `97-101` reason
  `tdesktop_disabled_until_e2e`, `canOfferFullscreen/canOfferExit=false`; текст причины `129-160`.
- **Авто-`exitFullscreen()` на старте launch-fullscreen — ЕСТЬ**: `fullscreen-policy.js:694-706` в `init()`:
  `actualFullscreen===true && platform==='tdesktop' && hasExitFullscreen && !_softExitTried` → один `wa.exitFullscreen()`
  + ack-таймер `479-499` → при игноре `TDESKTOP_LAUNCH_FULLSCREEN_EXIT_IGNORED`. Мобильный — без второго request,
  состояние сохраняется.
- Сохранить (ценнее старого): ack-таймаут 4000 мс без инверсии `451-468`; pending-guard `599-603`,`643-647`;
  ALREADY_FULLSCREEN без второго request `587-598`; события `510-529`, `531+`; DOM-зеркало `422-443`; `_fsRedraw`.
- **UI-заглушки (только W7, незакоммичено, в проде НЕТ)**:
  `web/index.html:333-360` `<details data-fs-diagnostics>` («Полноэкранный режим недоступен — почему и что делать»
  + `fsReasonText`/`fsNextStep`/`fsDiag`); `web/app.js:2371-2377` (state), `14646-14668` (`fsDiag`), `14671-14685`
  (toast причины); политика: `REASON_TEXT` `129-160`, `explainReason()` `162`, `explain()` `172`, `diagnostics()` `370`.
  На проде grep `data-fs-diagnostics` в `448cc81a:web/index.html` = 0 ⇒ там кнопка просто исчезает БЕЗ объяснения.

## 3. Геометрия / адаптив

Текущее (идентично prod и master), файл `web/static/app.css`:

- inline-база: `1040` (legacy `order:99`), `1047-1051` (compact: `order:5;margin-left:auto;min-width/height:44px`).
- float: `3380-3387` `html.fs-slot-float .header-fs-btn{position:fixed; top:calc(var(--tg-content-safe-area-inset-top)+6px);
  right:calc(max(env(safe-area-inset-right), --tg-content-safe-area-inset-right, --tg-safe-area-inset-right)+6px); z-index:60}`.
- **Форсированный резерв шапки**: `3394-3396` `html.fs-slot-float header.header-sticky{padding-top:
  calc(var(--tg-content-safe-area-inset-top) + 6px + 44px) !important}` — это и есть «высокий хедер».
- 32px визуал (28px ≤359px) `3335-3366`, `3398-3403`; light-тема `3368-3376`.
- База шапки: `.header-compact-v2` `1025-1032` (`.6rem + max(env,--tg-content,--tg-safe)`);
  `.fullscreen-mode header` `1149-1153` (= фикс `d9b7f389`, 667 landscape 651→607 — сохранить);
  `--header-h` = реальный rect шапки через ResizeObserver (`web/app.js:21517-21539`) ⇒ inflated шапка тянет
  `scroll-padding-top` (`app.css:1088`). `--app-usable-height` — `telegram-init.js:91-114`.

**Числа из собственного harness v6.3** (`plans/features/asap8-v6-3-live-correction/w2-evidence-fullscreen/_results.json`):
S1 android 390 (csa.top=36) → `headerPadTop=86`, **header h=189**, кнопка 49×44 y=42; S8: 320 → 189, 667×375 → 169;
S3 tdesktop → `headerPadTop=9.6`, header h=113, кнопки нет.
⇒ float-слот добавил шапке ≈+76 px (113→189), вопреки исходному требованию владельца
«шапка <=108–124 CSS px включая отступы … но никогда «половина экрана»» (`source-lines-37423-EOF.md:139`)
и цели U01 (header 225.6→116.2px). Прежние правила (row A, в потоке, без резерва) давали 113-116 px.

## 4. Прод vs мастер (что переносить на прод-версию)

| Файл | prod `448cc81a` | master `9d8da1d7` | FS-строк в diff |
|---|---|---|---|
| `web/static/fullscreen-policy.js` | `18ee7ed72f` | `18ee7ed72f` | SAME |
| `web/static/telegram-init.js` | `69bf1880db` | `69bf1880db` | SAME |
| `web/static/app.css` | `589086176b` | `3b616c1f61` | 0 (fs-блок 3380/3394/3398 — те же строки) |
| `web/index.html` | `eb9a0b3afb` | `3c5b713cba` | 0 (W7-диагностика в ДЕРЕВЕ, не в HEAD) |
| `web/app.js` | `38f6665458` | `a42a85ba44` | 0 |

Незакоммиченный W7 добавляет: `web/app.js +43`, `web/index.html +51`, `fullscreen-policy.js +219`, `tests/js +266`.
⇒ fs-правки делаются **заново на ветке `release/incident-2.58.83`** (cherry-pick невозможен: W7 смешан с SOUL-1).

## 5. Минимальное восстановление

**Вернуть:** (1) tdesktop не `hidden` — `fullscreen-policy.js:73-81` + `97-101`: скрывать только при отсутствии
`requestFullscreen`/Telegram; полноценный слот при `hasRequestFullscreen && hasBooleanIsFullscreen`; (2) кнопку
(`web/index.html:191`); (3) снять форсированный резерв `app.css:3394-3396` (Android 189 → ~113 px).

**Сохранить:** ack-модель, pending-guard, ALREADY_FULLSCREEN, события `fullscreenChanged/Failed`, launch без второго
request, `_fsRedraw`, формулы `max(env, --tg-content-safe-area-*, --tg-safe-area-*)` в padding шапки (фикс `d9b7f389`),
inline-фолбэк `app.css:1047-1051`, hit ≥44×44, 32px визуал.

**Удалить из продукта:** W7-заглушку (`index.html:333-360`, toast `app.js:14671-14685`); `diagnostics()`/`explain()`
оставить как dev-API `window.__FullscreenPolicy`, но не вместо кнопки.

**Точки, влияющие на «половинное/смещённое окно»:** (a) наша зона — `app.css:3394-3396` (резерв) и `3380-3387`
(fixed-позиция), доказательство повторяемо e2e S1/S8; (b) Windows — НЕ наша зона: CSS/JS не управляет нативным окном
(запрет REQ-U07-0-NOHACKS, `fullscreen-policy.js:23`; `source-lines-37423-EOF.md:200`). SDK лишь шлёт
`web_app_request_fullscreen`/`web_app_exit_fullscreen` (`web/static/vendor/telegram-web-app.js:2837-2844`) и принимает
`fullscreen_changed`/`fullscreen_failed` (`:3381-3382`); старт — из launch-параметра `tgWebAppFullscreen` (`:344-349`).
(c) «Запуск перестал открываться в fullscreen»: единственный код, САМ выходящий из стартового fullscreen, —
`fullscreen-policy.js:694-706` (мягкий exit на tdesktop); у остальных платформ поведение не менялось.

## 6. Требуется решение (не чинить молча)

`U07.1a` (`requirements-map.json:3775`) прямо требует «проблемный fullscreen-контрол **скрыт/disabled** с честной
подсказкой до успешного platform-specific e2e», а `REQ-U07-HARD` (`:642`) — «на Windows … выход из fullscreen должен
быть реально доступен». Новая директива владельца («вернуть работавший переключатель; заглушка — неверное решение»)
это **переопределяет** ⇒ нужен явный AMEND U07.1a + запись в `plans/features/soul-1/owner-decisions.md`
(сейчас там про fullscreen нет ни строки). Открытый вопрос к e2e на реальном клиенте: даёт ли `requestFullscreen()`
на текущем tdesktop рабочий fullscreen (в исходнике: «иногда … небольшое неудобное окно», `source-lines-37423-EOF.md:14`);
Playwright mock этого не доказывает (`U07.3b`).
