# W2-FULLSCREEN — отчёт лейна (U07, Wave 2)

Фича: asap8-v6-3-live-correction · Лейн: W2-L2 FULLSCREEN · Базис: HEAD `f1418d7`
Контракт: `w2-contract.md` §1.2/§2/§4 · Коммит НЕ выполнялся (по брифу).

## 0. Кандидат

| Файл | Роль |
|---|---|
| `web/static/fullscreen-policy.js` | **НОВЫЙ**, вся политика (plain IIFE, без Vue). sha256 `C868A42E051A439823ACD70100EE7B41B1E6BBBB2C0666F20CF81F0F0E884818` |
| `web/app.js` | только fullscreen-зона (бывш. блок 12791–12911): `_fsPolicySync/toggleFullscreen/initFullscreen/setFullscreenFromTma/_fsRedraw/teardownFullscreen`; data-зеркала возле `isFullscreen`; computed `fsAriaPressed`; вызовы 4998/5059/18472 не менялись |
| `web/index.html` | узел `.header-fs-btn` (v-if слота, svg-иконка, aria) + `<script /static/fullscreen-policy.js>` перед app.js; строка 66 `.app-shell` не тронута (кроме чужого элемента SHELL `more-menu-open`) |
| `web/static/app.css` | append-only секция `/* ═══ W2-FULLSCREEN … ═══ */` (слот-геометрия ⛶, light-вариант, float-резерв). Секции SHELL/GLASS не тронуты |
| `tests/js/asap8_w2_fullscreen_policy_test.js` | **НОВЫЙ**, CONTRACT owner=REQ-U07-1/2 (matрица + машина состояний + структура) |
| `tools/ui_asap8_w2_fullscreen_e2e.py` | **НОВЫЙ**, Playwright-e2e c ROUTE-mock SDK (w2 §4.2) |
| `tests/js/round1024_providers_fullscreen_test.js` | канон-обновление CONTRACT-теста: fallback-путь (stub + co-методы), удалённые ветки rAF-re-read/инверсии заменены ассертами нового канона U07.1c |
| `tests/test_webapp_hotfix6_round1025.py` | канон-обновление: `requestFullScreen`-толерантность теперь в политике (assert POLICY), + чтение POLICY-файла |

## 1. Политика — поля и ветки (REQ-U07-1, U07.1)

`window.__FullscreenPolicy`: `state/request/exit/subscribe/init/teardown/setAckTimeoutMs/slotFromGeometry/decideOffer/launchExitIgnored`.

Поля state: `telegramPlatform` (android|ios|macos|tdesktop|weba|web|unknown), `sdkVersion`, `hasRequestFullscreen` (вкл. камел-алиас), `hasExitFullscreen`, `actualFullscreen` (**true|false|'unknown' — только из SDK, инверсии нет**), `launchFullscreen` (факт старта; null ≠ false), `requestPending`, `lastError{code,message}`, `canOfferFullscreen/canOfferExit/reason`, `slot` (inline|float|hidden), `viewport{width,height,stableHeight,safeAreaInset,contentSafeAreaInset}`.

Ветки, покрытые unit-матрицей (`FS-POLICY-OK`, 14 групп):
- **tdesktop → hidden** (`tdesktop_disabled_until_e2e`), request из UI невозможен; `expand()` НИГДЕ не используется как fullscreen-фолбэк (U07.1a);
- **float** только `android|ios|weba` + `hasRequestFullscreen` + `csaTop>=36` + SDK отдаёт boolean `isFullscreen` (иначе честный inline — контракт §2.1);
- **inline**: unknown/web/macos, csa=0, не-число csa, weba без boolean;
- **no Telegram → hidden** (`no_telegram_context`) — stand-alone не вводит в заблуждение (U07.3c);
- **ALREADY_FULLSCREEN**: пересчёт из SDK, кнопка=выход, без ложного SUCCESS, второй request не отправляется;
- **UNSUPPORTED**: прежнее состояние + retry разрешён + тост;
- **ack-таймаут**: задаётся/очищается (`setAckTimeoutMs`), факт НЕ инвертирует, pending снимается;
- **pending-guard**: повторный тап при pending = 1 запрос; rotation/viewportChanged/safeAreaChanged — ни одного запроса, slot пересчитывается, pending сохраняется;
- **Launch Mode=Fullscreen**: `init()` никогда не шлёт `requestFullscreen`; android → сразу canOfferExit; **tdesktop-launch → ровно один мягкий `exitFullscreen()`** (guard `_softExitTried`, повторный `init()` из `ready` не шлёт второй), игнор хоста → `TDESKTOP_LAUNCH_FULLSCREEN_EXIT_IGNORED` (documented limitation, diag `launchExitIgnored()`). BotFather программно не меняется — только ручная инструкция владельцу (см. §5).
- Non-reactivity-loop (§4.1): политика без Vue; app.js копирует только `isFullscreen/fsSlot/fsCanOffer/fsCanOfferExit/fsReason/fsPending/fsActualUnknown` по `subscribe()`; ошибки → тост (`toast`) с дедупом по коду.

## 2. Интеграция

- app.js: зеркала + `fsAriaPressed` (null при unknown — aria-pressed не ставится); `toggleFullscreen` → `policy.request()/exit()`; fallback-путь без политики сохранён (без инверсии); HOTFIX9-D7 redraw (canvas/aurora) сохранён через `_fsRedraw` + отдельная viewportChanged-подписка; `teardownFullscreen` отписывает и политику, и fallback.
- index.html: ЕДИНСТВЕННЫЙ узел `.header-fs-btn` (класс сохранён дословно — CONTRACT hotfix6), `v-if="me && fsSlot !== 'hidden'"`, `:class="'fs-slot-'+fsSlot"`, aria «На весь экран»/«Выйти из полноэкранного режима» по ACK, `aria-pressed` только по факту, иконка — инлайн-SVG fullscreen/fullscreen_exit 18px (шрифтовой глиф U+26F6 в headless/WebView давал тофу — заменён осознанно). Порядок скриптов: policy ДО app.js, telegram-init.js последним (проверено e2e-ассертом).
- app.css (своя секция): визуал 32px круг (28 на ≤359px), glass ::before c `pointer-events:none`, hit ≥44×44; **float**: `position:fixed; top: calc(var(--tg-content-safe-area-inset-top,0px)+6px); right: calc(max(env(safe-area-inset-right,0px), var(--tg-content-safe-area-inset-right,0px), var(--tg-safe-area-inset-right,0px))+6px)` — формула контракта §2.1 дословно; float-резерв row A `html.fs-slot-float header.header-sticky { padding-top: calc(csa+6px+44px)!important }` — `!important` намеренно: float-геометрия — overlay-геометрия U07 вне inline-бюджета, обязана переживать специфичные SHELL-правила (e2e S1 поймал реальный перехват: правило compact-v2 (0,4,2) перебивало резерв, row A уходил под кнопку — исправлено и покрыто ассертом padding-top ≥ csa+50); light-тема через `html[data-fs-scheme="light"]` (пишет app.js из `wa.colorScheme`, U07.2d).

## 3. Тесты и evidence

- **Node**: `node tests/js/asap8_w2_fullscreen_policy_test.js` → `FS-POLICY-OK` (матрица слотов 15 кейсов, decideOffer 6, машина состояний 12, структурные 9). Регресс-прогоны: `round1024_providers_fullscreen_test` → PROVIDERS-FS-OK; `vue_mount_test` → OK; `round1025_hotfix10` → OK; `round1025_shell_breakpoints` → OK.
- **Playwright (route-mock SDK, НЕ addInitScript)**: `tools/ui_asap8_w2_fullscreen_e2e.py` → **7/7 PASS, 70 проверок**. Артефакты: `w2-evidence-fullscreen/` (12 PNG + `_results.json`).
  - S1 android csa=36 → float: hit 44×44, визуал 32, y≥csa.top, right у края, `elementFromPoint` в зонах native ⋮/✕ — не наша кнопка; полный ack-цикл (1 request → aria-pressed+title exit → 1 exit → back), `.app-shell.fullscreen-mode`;
  - S2 csa=0 → inline в потоке row A (320/390, без h-overflow);
  - S3 tdesktop → кнопки нет, `html.fs-hidden`, `data-fs-reason=tdesktop_disabled_until_e2e`, 0 вызовов API;
  - S4 без Telegram → hidden (`no_telegram_context`);
  - S5 ALREADY_FULLSCREEN / UNSUPPORTED(+тост) / ack-таймаут(+тост, без инверсии) / pending-конфликт / SDK без boolean (aria-pressed отсутствует, fullscreen-mode не включён);
  - S6 launch-fullscreen android → 0 request на старте, сразу кнопка выхода;
  - S7 tdesktop-launch → ровно 1 мягкий exit, UI повторно fullscreen не предлагает;
  - S8 float на 320/390/667×375 — геометрия в `_results.json`.
- **Browser Use (real Chrome, real SDK)**: stand-alone — кнопки нет (v-if me/auth-gate + политика), auth-баннер честный, шапка целая, h-overflow нет.

## 4. Честные ограничения (VERIFIED_LIVE невозможно в W2 — Wave 4/V06, U07.3b)

1. Реальный `fullscreenChanged/fullscreenFailed` от живых клиентов (Android WebView, iOS, macOS, Telegram Desktop): поведение подтверждено только моком шины событий.
2. Фактическая геометрия `contentSafeAreaInset` на реальных устройствах (вырезы, ландшафт) и реальное соседство с native ⋮/✕ (тап по ним) — mock проверяет только отсутствие DOM-перехвата.
3. Windows Desktop (U07.3b): точные platform/version, источник открытия (BotFather vs direct link), isFullscreen до/после, drag/close — только ручной клиентский журнал Wave 4. VERIFIED_LIVE не заявлен.
4. `Launch Mode=Fullscreen` на реальном Windows: мягкий exit отправляется, но игнор хоста подтверждается только живым клиентом; если подтвердится — владельцу: **BotFather → Bot Settings → Main App → Launch Mode вручную** («Full»/обычный), программно не трогаем (ТЗ U07.1e).
5. iOS Safari/WebView safe-area (env ≠ 0) — формула max(env, --tg-*) покрыта unit/e2e подстановками, живой скриншот — Wave 4.
6. Feature-gate возврата кнопки на tdesktop — после успешного platform-specific e2e (константа/ветка `decideOffer('tdesktop')`, одна точка изменения).

## 5. Инцидентальные находки

- **current-blocker (эскалация @Orchestrator, не мой write-scope)**: во время W2 параллельный GLASS-лейн перезаписал `web/index.html` с устаревшей базы — из serialize-зоны (§1.3.4/HS-1) исчезли ПРАВКИ SHELL (row A brand, more-menu, class-binding `more-menu-open`) и МОИ два фрагмента (узел `.header-fs-btn`, строка `<script fullscreen-policy.js>`). Свои два фрагмента я восстановил в полном объёме (подтверждено структурными тестами + e2e 7/7). Потёртые правки SHELL в index.html я НЕ реконструирую по памяти — по HS-1 их версия принадлежит SHELL; app.js/app.css SHELL-части целы (`moreMenuOpen` в app.js, W2-SHELL секции в app.css), т.е. index.html сейчас временно НЕсогласован с app.js по more-menu до re-apply SHELL. Требуется re-apply версии SHELL (или их повторная запись) до REV-W2.
- **constraint владельца (подтверждено)**: прод-полигонный фон заморожён — `web/static/polygon-background.js` и связанные фоновые секции/CSS/SVG не менялись ни одной строкой; diff лейна ограничен policy-файлом, fullscreen-блоком app.js, узлом кнопки/скриптом index.html и секцией `W2-FULLSCREEN` в app.css.

- **related-nonblocking (чужие лейны, active)**: 7 pytest-провалов в `test_webapp_hotfix6/7_round1025.py` (TestAreaA lens-токены/css.supports/glass-probe.js; TestAreaB `mobile-topnav scroll-thin`-маркер) — вызваны параллельными правками GLASS (glass-probe.js, --lg-tint-*) и SHELL (row B канон), НЕ fullscreen-скоупом; маркер-тесты подлежат канон-обновлению владельцами лейнов (правило §1.2 контракта). Мой изменённый `test_fullscreen_preserved_and_hardened` зелёный.
- **related-fixed в своём скоупе**: (а) перебой float-резерва правилом compact-v2 (см. §2); (б) тофу-глиф ⛶ → SVG; (в) positioned-слой ::before поверх svg-иконки (z-index fix); (г) `_recompute` читал insets после decideOffer (первый расчёт слота с csa=0) — порядок исправлен, покрыто unit 3.1.
- **uncertain**: в реальном Chrome без TG политика остаётся в слоте inline с canOffer (реальный SDK отдаёт методы), но кнопка скрыта auth-gate (`me` отсутствует); если владелец захочет показывать ⛶ вне авторизации — отдельное решение, сейчас безопасно (S4/Browser Use: кнопки нет).

## 6. Статус приёмки

- REQ-U07-0/0-NOHACKS, U07.1(a–f), U07.2(a–e), U07.3a, REQ-U07-2-NOINJECT — IMPLEMENTED+TESTED (mock/e2e/юнит, доказательства выше).
- REQ-U07 / REQ-U07-HARD / U07.3b/3c / V06 — IMPLEMENTED, живая часть = **BLOCKED_ACCESS до Wave 4** (реальные Windows/Android клиенты), `live_required=true, live_when=postdeploy`.
