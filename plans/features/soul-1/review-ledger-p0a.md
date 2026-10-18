# REVIEW-LEDGER-P0A — независимая сверка леджера P0-A

Проверяемый коммит: `3d97448e94093be905bdc6690198ff3562455126`
(`plans/features/p0-save-init-ux/requirements-map.json`, 1 файл, +205/−39).
Отдельный docs-коммит каталога аудита: `8cdddd57` (18 файлов,
`evidence/audit-2026-10-18/**`, карту не трогал). Режим: read-only + две мои
правки: точечная коррекция одной строки карты (`3d0e3c7f`, +2/−2) и этот
документ.

## 1. Состав/дифф — подтверждён

Ровно 13 строк (7 в `items` + 6 в `additional_requirements`; сверка JSON
`3d97448e^` ↔ `3d97448e`):
* **VERIFIED (8):** `P0A-PERSIST-AUDIT` (2 ev), `P0A-PERSIST-CAUSE` (2 ev),
  `P0A-PERSIST-CENTRAL` (2 ev), `P0A-INIT-CURSOR` (2 ev + live_note),
  `P0A-INIT-DIRECT` (1 ev), `P0A-INIT-COOLDOWN` (1 ev + live_note),
  `P0A-INIT-STATUS` (2 ev + live_note), `P0A-INIT-PROOF` (1 ev + live_note —
  см. §5: мной исправлено на RFL).
* **READY_FOR_LIVE (5):** `P0A-PERSIST-SECTIONS`, `P0A-PERSIST-TRUTH`,
  `P0A-PERSIST-APPLY`, `P0A-PERSIST-PAYLOADS` (live_note: цикл
  изменить→сохранить→перечитать→вернуть / payloads) и `P0A-INIT-DIAG`
  (reason честно отделяет dry-run мини-фикс: «ещё на ревью», в закрытие не
  входит).
Кандидаты в пинах: persist `29a9517334df495a1dfd2a4bc9fecfd7341887bc`,
init `f0bd29e2777eb78c6d7cabe18eb5ba03111beca6` (оба — предки HEAD; полные
sha сверены по всем evidence-записям).
**Не тронуто — подтверждено:** 22 PENDING без изменений (P0A-UX-×6,
P0A-OPS-REVIEW/NODUP/NOFAKE/REPORT, L-строки, M-A-03, P0A-OPS-CONTINUE,
P0A-ACCEPT-PERSIST/PERSIST-EDGE/UX/INITIATIVE, P0A-DONE); top-level
`candidate_commit`/`deployed_commit` — '' до и после (rolling); soul-карты в
коммит не входят.

## 2. Пины — 10/10 на диске, 9/10 в коммитах-кандидатах

Сверено (диск + git-блоб в указанном `candidate_commit`): prod-dump
`186e02cc…`, `tests/test_p0_initfix_initiative_observer.py` `6da2fcc4…`,
ui-png `888c073f…` (все f0bd29e2 ✓); `persistence-audit.md` `449e587b…`,
`review-persist-fix.md` `f3787f8f…`, `persist-fix/report.md` `efccabb1…`,
`sweep-130-final.txt` `5bdc8af4…`, `green-final-pytest.txt` `4dafe475…`,
`tests/test_p0_persistfix_speech_chat_scope.py` `e9481e55…` (все 29a95173 ✓);
`evidence/audit-2026-10-18/probe_persistence_audit.json` `c27d225e…` — на
диске ✓ и в HEAD ✓, в `29a95173` отсутствует — **закоммичен отдельным
docs-коммитом `8cdddd57`**, как и описано в брифе (пин по байтам валиден).
Содержимое выборочно: sweep — «1 failed, 2985 passed» (чужой mca12 js;
позже исправлен `3e044c8a`), green — «145 passed», review-persist-fix.md —
Approved с решениями леджеру.

## 3. Счётчики — пересчитано

Всего 35 строк (22 items + 13 additional): **до моей коррекции — VERIFIED=8,
READY_FOR_LIVE=5, PENDING=22** (совпадает с заявленным); **после
коррекции — VERIFIED=7, READY_FOR_LIVE=6, PENDING=22**.

## 4. Гейт — verbatim

`check --stage plan --map plans/features/p0-save-init-ux/requirements-map.json`
→ `stage=plan inventory=22 manual=13 scoped=0 errors=0` **EXIT 0** — до и
после моей правки (22/13/0).

## 5. Нюанс PROOF — исправлено на READY_FOR_LIVE

Оценка по существу: acceptance строки содержит прод-клаузы («обрабатывает
актуальный чат», «зафиксирована воронка до стадии отправки/причины») при
`live_required=true/live_when=postdeploy`; evidence — тест на синтетических
входах с fake-Writer/бо́том (честно: публикаций не было, «не имитировать»
соблюдено). Независимое ревью §7 (`review-init-fix.md`) уже рекомендовало
RFL. Дом-конвенция VERIFIED+live_required в других картах опирается на
live/production/ui-артефакты, а не только на тесты. Поэтому внесена точечная
правка (`3d0e3c7f`): `P0A-INIT-PROOF` → **READY_FOR_LIVE**, evidence и
live_note сохранены, reason приведён в соответствие. Это не потеря работы:
release-стадия гейта структурно потребует live/production evidence, привязанный
к задеплоенному кандидату, — строка не сможет закрыться без реального
прод-эха воронки. `P0A-INIT-CURSOR/STATUS` оставлены VERIFIED: их приёмка
опирается на реальные артефакты (прод-дамп лага; UI-пробы + прод-RBAC), а
live_note фиксирует пост-деплойный чек.

## 6. Индекс — чисто

`3d97448e` = 1 файл (+205/−39); `git diff --cached` на момент проверки пуст;
каталог аудита — отдельный коммит `8cdddd57`; моя правка — `3d0e3c7f`
(1 файл, +2/−2).

## Замечания (редакционные, не блокеры)

1. live_note у `P0A-PERSIST-SECTIONS/-TRUTH` — краткий («реальный цикл на
   production PostgreSQL»); явный цикл «изменить→сохранить→перечитать→вернуть»
   есть у `APPLY/PAYLOADS`. При след. правке карты можно выровнять формулировки.
2. `P0A-INIT-DIAG` корректно указывает, что dry-run мини-фикс в это закрытие
   не входит; его ревью позже вернуло Needs Fixes — консистентно.

## Вердикт

**Approved.** Состав/статусы/пины/счётчики/гейт/индекс леджера `3d97448e`
подтверждены; одна строка (`P0A-INIT-PROOF`) переведена в READY_FOR_LIVE
точечной правкой `3d0e3c7f` с сохранением evidence и live_note. Блокирующих
находок нет.