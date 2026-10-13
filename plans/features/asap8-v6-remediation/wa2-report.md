# W-A2 отчёт — ASAP 8 v6, Wave A (D01 + D09-хвост)

Lane: W-A2 (writer). Baseline: HEAD `1e98027` + незакоммиченные кандидаты W-A1
(`services/config_cache.py`, `services/dream_worker.py`) и W-A3
(`services/chat_lore_store.py`, `handlers/chat_lifecycle.py`) — не тронуты,
тесты прогнаны поверх как есть. Дата: 14.10.2026. Коммит: НЕТ (по брифу).

## FIX 1 — D01 P0: dossier stale-response guard (web/app.js)

Root cause (ledger D01, подтверждён на месте): `loadDossier`/`saveDossier`/
`startDossierRebuild`/`pollDossierRebuild` применяли ответ после await
безусловно — URL строился из мутабельных `this.activeChatId`/`dossierUserId`
на момент вызова/клика, без привязки к сессии редактора. Сценарий 18A.1
(A-load in flight → close → open B → A прибывает последним) перезаписывал
editor B и тостил в чужом контексте; Save строил endpoint из текущего выбора.

Фикс — паттерн settings epoch-guard (`persistItems`/`scopeEpoch`, F0), адаптированный
под identity-тройку. Файловые хелперы (не методы Vue) — старые unit-фейки без
новых полей продолжают работать (`undefined === undefined` = «одна вечная
сессия»), существующие JS-тесты НЕ правились:

- `dossierGuard(ctx, token, chatId, userId)` — ответ относится к сессии,
  только если с момента захвата identity (строго ДО первого await) не сменились
  открытый инстанс модалки (token), чат и участник;
- `_dossierSeq`/`dossierSessionToken` — монотонный счётчик: каждое открытие
  инкрементит, `closeDossier` гасит токен в `dossierSessionToken=null`, но
  НЕ сбрасывает счётчик (переоткрытие того же досье никогда не совпадёт
  с in-flight прошлой сессии — найдено и закрыто при саморевью);
- `loadDossier` — capture `(token, chatId, userId)` до await; stale-ответ
  (данные ИЛИ ошибка) не мутирует editor и не тостит;
- `saveDossier` — identity edit-сессии и снапшот черновика до await; URL
  из захваченной пары; success-ack снимает pending-черновик тихо даже при
  stale; success/error-тосты только в свой контекст; `dossierSaving`
  снимается безусловно (in-flight сессия не залипает кнопкой Save новой);
- `openDossier` — токен до await, stale-ветка не снимает `dossierBusy`
  новой сессии (не гасит чужой спиннер);
- rebuild-секция: `startDossierRebuild`, `loadDossierRebuild`,
  `pollDossierRebuild`, `cancelDossierRebuild` — тот же capture-до-await/
  guard-после-await; stale-старт не пишет job/localStorage, не стартует
  polling и не тостит; stale-done не перезагружает editor;
- тост сохранения называет target: «Сохранено для <участник> — <чат>»
  (`dossierTargetLabel`, подпись чата из того же кэша `oversightData.chats`,
  что и лента досье; fallback «чат <id>»/«ID <user>»); poll-done —
  «Досье пересобрано: <участник> — <чат>»;
- dirty-черновик переживает закрытие (ESC/backdrop/«Отмена»): pending-карта
  по паре (chat,user) — возвращается при переоткрытии того же досье,
  снимается после серверного ack или чистого закрытия (18A.1 acceptance
  «ESC/close с dirty draft сохраняет draft»);
- test-seam: `window.__adminbotVm = this` в `mounted()` (1 строка, поведения
  не меняет) — prod-сборка Vue 3.5 не оставляет dev-хендлов на DOM, а
  Playwright/Browser Use проверки и диагностика должны доставать vm без хаков.

## FIX 2 — D09-хвост: `or 7` в mca_gates.py (`_schedule_gate` ~:1764)

Тот же баг, что чинил W-A1 в `dream_worker._deep_tick`: `int(x or 7)` при
чтении `memory.deep_sleep_hour` подменял ВАЛИДНЫЙ 0 (00:00) целью 07:00 —
гейт расписания и его detail-трасса расходились с починенным воркером.
Уточнение к брифу/W-A1: call site в mca_gates ОДИН (резолв в `_schedule_gate`;
строка :1784 — лишь detail-трасса того же значения, отдельного чтения нет).

Фикс: применён импортируемый `services.dream_worker._hour_or` (тот же контракт:
None/пусто/мусор → env-дефолт `settings.DEEP_SLEEP_HOUR`, числовой 0/"0" → 0)
с дефолтом из env вместо литерала 7. Fail-open при ошибке резолва и ветка
`trigger != 'fixed'` не тронуты. Паритет гейт↔воркер теперь на одном хелпере.

## Acceptance — по пунктам

| Пункт | Статус | Доказательство |
|---|---|---|
| A-load in flight → switch B → A прибывает → editor B не тронут | PASS | unit: `asap8_v6_wa2_dossier_guard_test.js` №2/2b/2c; Playwright DOM: dossierData остаётся null, A-текст отсутствует в body, спиннер B жив; Browser Use: `dataUserId: null`, `staleVisible: false` |
| A-save in flight → switch B → A-completion не тостит success в B и не пишет B | PASS | unit №3b/3c/3d (+URL из захваченной identity, pending снят тихо, кнопка B не залипла); DOM: PUT ушёл на `/dossier/7` до смены, stale-resolve без тостов |
| save использует identity, захваченную в начале edit-сессии | PASS | unit №3/3b/3d: URL/PUT `{traits}` строятся из captured pair; DOM: PUT `/api/chat_lore/-100/dossier/7?name=Боря` при switch на другой контекст |
| rebuild-poll со сменой участника игнорирует старый | PASS | unit №6/6b/6c/7 (poll stale, fresh done + именованный тост, latest stale, stale-start без polling/localStorage) |
| ESC/close с dirty draft сохраняет draft | PASS | unit №4 (dirty→close→reopen→восстановлен; ack→чистое закрытие→черновик от сервера); Playwright: реальный ESC из textarea, reopen → `черновик до ESC` + «Есть правка» |
| Тост называет target «Сохранено для <участник/чат>» | PASS | Playwright DOM: `Сохранено для Боря — чат -100` (fallback без oversight-кэша); unit №3/6b с титулом чата |
| `node --check web/app.js` | PASS | exit 0 |
| Существующие dossier/settings JS-тесты зелёные | PASS | 13/13: round1020/1021/1022(rebuild+aliases)/1024(feed)/1025(save_state, scope, f4 store+catalog, f7)/routing/vue_mount — БЕЗ правок существующих фейков |
| mca_gates: 00:00 | PASS | `test_gate_open_at_midnight_when_configured_00`; RED: на старом `or 7` падает ровно этот + next (2 failed) |
| mca_gates: 01:00/23:00 | PASS | `test_gate_regular_hours_01_and_23` (+чужой час блокирует, detail называет реальную цель) |
| mca_gates: missing/мусор | PASS | `test_gate_missing_value_uses_env_default` (None→env, not literal), `..._garbage_...`; "0" строкой → 0 |
| Существующие mca_gates/sleep тесты зелёные | PASS | mca06_sleep_bc/de, asap5_paradigms, dream_worker, wa1 suites — зелёные |
| Команда брифа (py) | PASS | `pytest test_asap8_v6_wa2_mca_gates_hours.py test_asap8_v6_wa1_dream_hours.py test_asap8_v6_wa1_config_cache.py test_dream_worker.py test_mca06_sleep_bc/de test_asap7_chat_lifecycle.py test_chat_lifecycle.py -q` → 168 passed (смок поверх W-A1/W-A3) |
| Playwright deterministic flow | PASS | live DOM 1280×800 и 390×800: openA→close→openB→stale arrive→fresh B→save→тост→ESC→reopen; скриншоты в scratch |
| Browser Use real rendered | PASS | независимый рендер: stale не отображается, editor B = свежее значение, модалка визуально целостна |

## RED-доказательства

- D01: дефект существовал на HEAD (ledger confirmed); guard-тесты на фикс-коде
  зелёные, на behavior-уровне unit №2/3b воспроизводят сценарий 18A.1
  дословно (стейл-ответ мут бы их сломал — проверено внутренне: снятие гварда
  = dossierData перезаписан).
- D09-хвост: временно вернул старое `int(x or 7)` в `_schedule_gate` →
  `pytest` → ровно 2 failed (`test_gate_open_at_midnight_when_configured_00`,
  `test_gate_blocks_at_07_for_midnight_config`), фикс восстановлен → 9 passed.

## Файлы

- `web/app.js` — dossier-секция (load/save/rebuild-poll/helpers) + data-поле
  `dossierSessionToken` + file-scope guard-хелперы + test-seam в `mounted()`.
- `services/mca_gates.py` — ТОЛЬКО or-7 call site в `_schedule_gate`.
- `tests/js/asap8_v6_wa2_dossier_guard_test.js` — НОВЫЙ, 15 сценариев
  (TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/D01).
- `tests/test_asap8_v6_wa2_mca_gates_hours.py` — НОВЫЙ, 9 тестов
  (TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/D09).
- Существующие тесты НЕ правились (правки не потребовались — файловые
  хелперы сохраняют контракт старых фейков).

Не коммичено. Серверы/браузеры после проверок остановлены, скриншоты и
временный статик-сервер — в managed scratch.

## Incidental findings

1. `related-nonblocking` — `dossierSaving` разделяется между сессиями модалки:
   пока чужой save in flight, Save новой сессии кратко заблокирован до
   settles первого (наконец-то снимается безусловно, залипания нет). Для
   строгой изоляции нужен per-session busy — вне минимального фикса.
2. `related-nonblocking` — `resumeDossierRebuild` stale-потока openDossier
   выполняется уже в контексте новой сессии (дублирующий идемпотентный GET
   `rebuild/latest` того же участника); данных не портит (guard + GET),
   полный перенос токена в resume — опциональный рефактор.
3. `unrelated/pre-existing` — статик-путь `/web/app.js` при отсутствие
   backend даёт 404 на дефолтном http.server от `web/` (нужен маппинг
   `/static` → `web/static`); только локальная dev-обстоновка, прод не задет.

## Остаточный риск

- Live-проверка в прод-MiniApp (реальный Telegram WebApp + backend) не
  выполнялась — из Builder прод-выката нет; контракт доказан на реальном
  рендере приложения с вокербенч-stub'ом api (тот же код пути open/load/
  save/close/poll). Риск деградации оцениваю низким: изменения локальны
  в dossier-секции, существующие пины зелёные.
- Тост-лейбл чата зависит от `oversightData.chats` — если кэш не загружен,
  честный fallback «чат <id>» (проверено в DOM).
