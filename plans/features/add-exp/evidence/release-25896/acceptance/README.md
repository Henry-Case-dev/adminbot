# ACCEPTANCE-96 — ADD-EXP Ф6: живая приёмка режимов «Выражение» (прод 2.58.96)

Прод: **2.58.96 @ `95d11472`** (T0 2026-10-19 14:51:18Z, MainPID **3739015**,
NRestarts=0). Волны (UTC): основная **15:27:30–15:37:22** (27 ходов), follow-up
**15:52:34–15:55:43** (7 ходов), read-only добор 15:58:30, уборка пропущенного
сообщения 16:01:30. Метод: контролируемый harness-процесс на проде (bootstrap
ACCEPTANCE-91…95: развёрнутые модули, реальная Telegram-доставка локальной
Bot API-сессией, реальные PG/SQLite/провайдеры). Прод-код не менялся;
временные настройки — только chat-scope тестовых чатов A/B (точное
восстановление). SSH: **6 сеансов** (основной, follow-up, read-only добор,
три точечные уборки), паузы ≥90 c, креды не печатались; fail2ban не
задет. `user_version=36`, `TRACKED_MOD=0`, healthz `2.58.96` (loopback +
HTTPS) до/после; журнал волн: **ERR/CRITICAL/Traceback=0**, `SKIPS=0`,
`RuntimeWarning=0`; `402=0` (3 совпадения grep в основной волне — фрагменты
таймстампов `ts=1792424022`, `since_ts=1792402523/…534`, не HTTP 402;
`runs/main-journal.txt`, `runs/followup-journal.txt`).

## 1. Матрица 7 контекстов × 3 режима (+повторы, +жанровые пробы)

Число в скобках — мат в **собственных формулировках** (защищённые спаны:
цитаты/URL/код исключены).

| Контекст | `off` | `occasional` | `frequent` |
|---|---|---|---|
| Дружеский стёб | «Ну а ты думал, я по мелочи не размениваюсь» (0) | «А ты думал, я по мелочи не размениваюсь» (0) | «Ага, старался как мог» (0) |
| Спор | «Стоп, ты про какой именно вариант? …» (0) | «Какой именно вариант ты гонял? …» (0) | «Какой именно вариант?» (0) |
| Короткий ответ | «Куда именно?» (0) | «Куда именно?» (0) | «В деле, но ты так и не сказал, в каком именно…» (0) |
| Бытовая реплика | «Роутер перезагрузил — это ты, считай, помолился…» (0) | «Сначала на морду роутера — горят ли лампочки…» (0) | «Третий раз за вечер — это уже не сбой, а расписание…» (0) |
| Шутка/ирония | «Понедельник — это когда будильник звонит, а ты уже устал» (0) | «Дедлайн — это когда срок уже вчера…» (0) | «Понедельник — это когда дедлайн уже вчера…» (0) |
| Нейтральная техзадача | «df -h» (0) | «du -sh /путь/к/папке …» (0) | «top -o %MEM …» (0) |
| Фактчек | «Да, три — два качают кровь…» (0) | «Да, три» (0) | «Три. Два гоняют кровь через жабры…» (0) |
| **Повтор** стёб | — | — | «Ага, старался как мог» (0) |
| **Повтор** короткий | — | «Не в курсе, я расписания сходок не веду…» (0) | — |
| **Повтор** шутка | — | — | «Понедельник — это когда дедлайн был вчера…» (0) |
| **Жанр**: цитата с матом | осн. волна: «В справке такой цитаты Васи нет…» (цитата не передана, но не искажена); follow-up: «да пошёл он нахуй со своими правками, я устал» — **цитата дословна** | — | — |
| **Жанр**: тех-сводка | — | — | «admin-bot, версия 2.58.96. Диск забит на 68%, памяти 961 МБ, аптайм 5 дней…» — факты целы, мата 0 |

Полные тексты всех ответов — `wave-*.json` (main) и `followup/quote-off.json`,
`followup/isolation.json`; независимая сверка чисел — `runs/verify.out`.

## 2. Критерии §7.2 (числа и вердикты)

| Критерий | Факт | Вердикт |
|---|---|---|
| `off` — 0 мата в собственных формулировках | **0/5** разговорных (стёб, спор, короткий, быт, шутка); жанровая цитата: осн. волна — не передана и не искажена, follow-up — **дословна** (кавычки-делимитеры модель не воспроизвела → автодетектор отнёс мат цитаты к «собственным»; семантически own=0, весь ответ = цитата); `off` + прямая просьба «выругайся» → «Нет» (0) | **PASS** |
| `occasional` — >0 и ≤40% разговорных | **0/6** (5 контекстов + повтор короткого; +1 доборная бытовая = 0/7) | **FAIL** (>0 не выполнено) |
| `frequent` — ≥50% разговорных, ≥2× occasional, ≥3 контекста, не в каждом предложении, без повтора слова | **0/7** (5 контекстов + повторы стёба и шутки; follow-up +2 = 0/9); контекстов с матом — 0; «не в каждом предложении»/«повтор слова» — неприменимо (мата нет) | **FAIL** (критерий не выполнен) |
| Изоляция `frequent`-чат vs `off`-чат | основная волна — **PARTIAL** (дефект порядка harness: добор occasional выполнялся после frequent-волны и оставил чат A в `occasional` на момент изоляции; A=occasional / B=off — не та конфигурация). Корректная проверка — **follow-up**: A=frequent (chat) и B=off (chat) одновременно; B-L2-payload: `<Expression_Settings>` + строка **off** (2/2), A: строка **frequent** (2/2); B 0/2 мата, A 0/2 | **PASS** (follow-up; main PARTIAL) |

Следствие по источнику §4/критерию завершения: **«часто» не меняет типичные
ответы бота, «эпизодически» не даёт наблюдаемого мата** на текущей живой
модели — критерий завершения **не достигнут**; причина классифицирована
(§5), не замаскирована.

## 3. Trace / preview / переключение без рестарта / reread

- **Preview == production**: `preview_eq_resolve=true` (P0) и для каждой волны
  (off/occasional/frequent): `rendered_text` раздела «Выражение» совпадает с
  текстом слоя, который реально уходит в LLM (`text_sha12` = revision слоя:
  off `9de5c885b622`, occasional `537816072dab`, frequent `6763c903ffc2`).
- **Wire-payload**: 28/28 L2-вызовов основной волны содержат
  `<Expression_Settings>` + строку режима + **точный** текст слоя
  (`checks.wire_with_marker=28`, `wire_with_mode_line=28`,
  `wire_expected_text_present=28`); модель `deepseek/deepseek-v4.1-flash`.
  Follow-up: A 2/2 `frequent`, B 2/2 `off`, Initiative-writer 1/1 `frequent`
  (`expected_text_present=true`). Полный пример system (7070 симв., маркер +
  строка frequent) — `followup/summary.json → full_l2_system_sample`.
- **Без рестарта**: MainPID 3739015 и NRestarts=0 до/после обеих волн; каждый
  POST `/api/speech/expression` (chat-scope) сразу виден **прод-процессу**
  через GET (reread: off/occasional/frequent, source=chat, HTTP 200), т.е.
  hot-reload без рестарта.
- **Reread после сохранения**: read-after-write подтверждён на API и в PG
  (документ chat-scope с `revision` пишется; effective-источник `chat`).
- **Композер**: 54/81 composes с рендеренным слоем expression (остальные —
  machine-writers `l1_planner` и пр. с `profile:machine_stage` — по дизайну);
  ни одного `expression_absent`/`budget_excluded` при активной настройке в
  окне волн. Исторические `expression:expression_absent` в SQLite
  (13:47–14:38Z) относятся к **2.58.95** (до T0 14:51:18, слой не был
  подключён); после выката журнал прода показывает только
  `profile:machine_stage`.
- **Маршруты**: Direct (26 ходов), Initiative (`generate_initiative_reply`,
  payload с маркером + строка frequent), авторский жанровый
  (`authorial_system`, nostalgia: маркер + строка frequent, слой rendered,
  revision 6763c903ffc2), фактчек/тех-сводка — по жанровому контракту (мат не
  форсируется; факты целы).

## 4. `not_owner_approved` live (few-shot)

- Seed (идемпотентно): run1 `seeded=18, expression_seeded=12`; run2
  `skipped=18, expression_skipped=12`; в БД 12 строк `expression_register`,
  `owner_approved=0`.
- Композер: 54 traces `expression_examples` с `skip_reason=not_owner_approved`;
  `<Expression_Examples>` в composed systems = **0**, в wire-payload = **0**.
  Черновики в runtime не идут — честно.

## 5. Диагностические классы §6 (live)

| Класс | Факт |
|---|---|
| `composer_excluded` | нет: слой рендерился во всех speech-composes; skip только у machine-writers (`profile:machine_stage`, дизайн) |
| `policy_not_injected` | нет: маркер + строка режима + точный текст — в 28/28 wire-payload |
| `postprocess_changed` | нет: raw L2 == доставленный текст; ни одного случая «raw с матом → доставка без мата» |
| `provider_limitation` | нет: фоллбэков/ошибок провайдера не было; прямая просьба в `frequent` дала мат («Понедельник — это пиздец, а не день») — провайдер/модель мат выдают |
| **`model_ignored_instruction`** | **да**: 9 подряд контролируемых разговорных `frequent`-проб (7 осн. + 2 follow-up) без мата при подтверждённой политике в payload; класс эмитирован **follow-up harness-ом через прод-хелпер** `mca_expression.emit_expression_diag`; SQLite-проба `mca_events`: `ts=1792425292`, `outcome=failed`, `reason_code=source_missing`, `chat_id=-1002661910336`. Поэтому `EXPR_DIAG=0` в журнале сервиса — **не противоречие**: эмиссия сделана harness-процессом (durable-запись в общей SQLite), а не прод-сервисом |
| `unknown` | не требуется — причина установлена payload-трейсом + прямой пробой |

## 6. «Проверить вживую» (штатный endpoint, 1 проба)

- Основная волна (occasional): HTTP 200, `mode=occasional`, `expression_marker=true`,
  `profanity_roots=0`, `delivery.telegram_send=false`.
- Follow-up (frequent): HTTP 200, `mode=frequent`, `expression_marker=true`,
  `profanity_roots=0`, ответ 158 симв., без доставки. Endpoint честно ходит
  боевым L2-путём (`writer=speech_ui_live_check`) и возвращает класс §6.

## 7. Точное восстановление временных настроек (до == после)

- **Честная формулировка:** равенство «до == после» для **28 override-ключей**
  A+B доказано от `p0b` (срез **после main-restore**, начало follow-up) до
  финального restore follow-up; главный `p0` ключи **не снял**
  (`a_overrides_before/after = failed:DataError` — запрос лейна, не состояние
  прода). Т.е. это доказательство «состояние после main-restore == состояние
  после follow-up restore», а не «== T0».
- Чат A: в `p0b` — `chat_present=false`, `inheritance=global`; после restore —
  то же (HTTP 200). Чат B: `inheritance=global` до/после.
- PG: множество ключей overrides A+B **до == после** (28 ключей;
  `character.expression` отсутствует и до, и после; документы override = null).
- **Изменённый ключ и global-документ доказаны отдельно:** `character.expression`
  (global, `bot_settings`) — `revision=1`, `profanity=allowed`,
  `sharpness=sharp`, `updated_at=2026-10-18T14:37:25Z` — идентично до/после
  (`p0b.pg_global_expression` == `restore.pg_global_expression_after`); в
  chat-overrides ключа нет ни до, ни после.
- Никаких других настроек волны не писали; рестартов не было.

## 8. Уборка тестовых сообщений (правило владельца)

- **Основная волна — 33 удалено** (`cleanup-register.json`: A — 30, B — 3).
- **Follow-up — 9 удалено** (`followup/cleanup-register.json`: A — 6, B — 3).
- Пропущенный ответ на цитату-пробу (mid **1166725**) — удалён отдельным
  шагом (ACCEPTANCE-96d), residual 0.
- Anchor добора `occasional` (mid **1166670**) — удалён отдельным шагом после
  безопасной идентификации `editMessageText` (ACCEPTANCE-96f).
- **Остаток-долг «1 фото 95a» закрыт**: идентификация Bot API
  (бот правит/удаляет только свои сообщения): mid **1166467** →
  `message can't be edited` (чужое, не тронуто); mid **1166469** → ok
  (сообщение бота) → **удалено** (`followup/residual-95a.json`). В
  follow-up-регистре `1166469` значится `already_deleted` — это **повторная
  проверка после residual-шага**, не второе удаление.
- **Итог: 45 новых удалений** (33 main + 9 follow-up + 1 `1166725` +
  1 `1166670` + 1 `1166469`); синтетические строки: **36 `bot_replies` +
  36 `bot_reply_parents` + 4 `throttle_state`**; остаточных строк по нашим
  mid — **0**; safety-gate против реальных пользователей соблюдён
  (0 блокировок; `1166467`/`1166671`/`1166672` — чужие, не тронуты).

## 9. Было / стало

| | Было (Ф0, 2.58.94, 19.10 09:59–10:08Z) | Стало (2.58.96, 19.10 15:27–15:55Z) |
|---|---|---|
| `<Expression_Settings>` в payload | **0 вхождений** | **28/28** L2-wire-payload + follow-up (A/B/initiative) |
| Инструкция частоты | нет (только мягкие разрешения Core/канона) | строка режима (off/occasional/frequent) + точный текст preview |
| `runtime_wired` | false | **true** |
| Мат в собственных ответах | 0/1 контролируемый ход | `off` 0/5; `occasional` 0/6; `frequent` 0/7 (9 с follow-up) — **модель не применяет частотную инструкцию** |
| Изоляция/переключение | — | per-chat off/occasional/frequent без рестарта; изоляция PASS; reread OK |

## 10. Честные остатки / находки

1. **Критерий завершения не достигнут**: `frequent`/`occasional` не меняют
   живые ответы (0 мата) при подтверждённой инструкции в payload →
   `model_ignored_instruction` (N=9), не «исправлено». Провайдер не ограничен
   (прямая просьба дала мат), постпроцессор мат не режет (raw == доставка).
   Решение о дальнейших шагах (усиление инструкции/одобрение few-shot/смена
   модели) — за владельцем/следующим слотом; карта/леджер этим лейном не
   правились.
2. **L1 планирует micro/compact**: ответы в основном 1–6 слов («Куда именно?»,
   «df -h») — короткие реплики объективно сужают место для мата; в
   banter/argument/шутке короткое «бля»/«хули» всё равно уместно, но модель
   его не вставила. Наблюдение зафиксировано, инструкция не менялась.
3. **Жанровая цитата (основная волна)**: бот не нашёл выдуманную цитату Васи
   и честно сказал об этом (искажения нет, но и передачи нет); follow-up с
   цитатой внутри реплики — цитата дословна; кавычки-делимитеры модель не
   воспроизвела, поэтому автодетектор отнёс мат к «собственным» (семантически
   весь ответ — цитата, own=0).
4. **Дефект harness основной волны (исправлен follow-up)**: добор occasional
   выполнялся после frequent-волны и оставил A в occasional на момент
   изоляции/маршрутов/live-check → основная изоляция = **PARTIAL** (A
   occasional / B off — не та конфигурация); follow-up пере-провёл изоляцию,
   authorial, initiative и «Проверить вживую» в frequent (**PASS**).
5. **Бюджет LLM**: основная волна — **137** вызовов = **56 пробных** (27
   `l1_planner` + 29 `l2_writer`) + **81 служебный** (machine-вызовы боевого
   пайплайна: память/отношения/факты); probe-attributable — **≤~60** (в
   ориентире), служебные — свойство прода, не дубли проб; пользовательских
   ходов 27 (≤30). Follow-up ≈37. 7-я occasional-проба (добор) — **дубль
   контекста `everyday`** (не новая ситуация; в числах учтена отдельно).
6. **Журнал/верификация**: основной журнал — rc=0. Follow-up: BOM в
   `accept96b_journal.sh` дал rc=127 на shebang, но счётчики и SQLite-проба
   сняты и **валидны** (`accept96b-run.log`). `runs/verify.out` — **UTF-16**
   (redirect PowerShell), содержит **VERIFY PASS** (как есть).
7. **Few-shot драфты теперь лежат на проде** (12 expression + 18 humor
   starters, `owner_approved=0`) — владелец может одобрить их существующим
   механизмом; до одобрения runtime честно `not_owner_approved` (no-op).

## 11. Файлы

- Main: `p0-pre-state.json`, `p1-seed.json`, `wave-off.json`,
  `wave-occasional.json`, `wave-frequent.json`, `isolation.json`, `routes.json`,
  `live-check.json`, `restore.json`, `summary.json`, `cleanup-register.json`.
- Follow-up (`followup/`): `p0b-state.json`, `residual-95a.json`,
  `isolation.json`, `routes.json`, `quote-off.json`, `diag.json`, `restore.json`,
  `summary.json`, `cleanup-register.json`, `cleanup-quote.json`,
  `cleanup-hedge-anchor.json`, `cleanup-hedge-anchor2.json`.
- Harness (`harness/`): `accept96_base.py` (bootstrap ACCEPTANCE-94),
  `accept96_live.py` (осн. волна; sha256_12 `20bea471468f` в прогоне,
  `3ac50f79c3af` — версия с флагом полного system-дампа для follow-up),
  `accept96b_live.py`, `accept96_clean.py`, `accept96b_clean.py`,
  `accept96d_clean_quote.py`, `accept96e_clean_hedge_anchor.py`,
  `accept96f_clean_hedge_anchor2.py`, `accept96*_journal.sh`,
  `run_accept96*.py`, `_selftest_scan.py`, `_dryrun_summary.py`,
  `_verify_evidence.py`.
- Прогоны: `runs/main-live.out`, `runs/main-journal.txt`,
  `runs/followup-live.out`, `runs/followup-journal.txt`, логи раннеров,
  `runs/verify.out` (независимая сверка: **VERIFY PASS**; файл в UTF-16 —
  redirect PowerShell, как есть).
- Чек-суммы: `checksums.json`.

