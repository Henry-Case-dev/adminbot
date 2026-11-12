# Деплой 2.58.194 — S5b (оплаченное изображение) + S6 (свежесть времени и слоёв)

Адресат: **production** (192.255.209.205, `/var/www/admin_bot`).
База: выложенный `7a7cd0ce` (2.58.193). Схема БД не меняется (v47, DDL=0),
новых флагов, настроек и зависимостей нет.

## 1. Привязка кандидата

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.194`, deployed SHA `6c11fc08ddade1edf0c4fb274e7f1bf93f852a26` |
| База релиза | `7a7cd0ce` (2.58.193) — общий предок с `83eb0b9b` = `c087253d` (2.58.188) |
| MUTABLE_WORKTREE_REQUIRED | **no** — иммутабельный checkout по SHA |
| Repo write scope выкладки | 53 файла: 23 файла содержимого + 30 файлов пинов версии |

Ветки `init/meme-s5b` / `init/meme-s6` **не сливались**: `83eb0b9b` не
потомок `7a7cd0ce` (общий предок `c087253d`, 2.58.188), слияние притащило бы
чужую историю. Перенос сделан черри-пиками на новую ветку от `7a7cd0ce`.

| # | Кандидат | Коммит релиза | Что | Diffstat |
|---|---|---|---|---|
| 1 | `e92cdcd5` | `8337d323` | S5b: оплаченное изображение не выбрасывается при `publisher_not_bound` | 9 файлов, +1145/−13 |
| 2 | `80ad6587` | `065015f8` | evidence-привязка S5b к `e92cdcd5` | 1 файл, +191 |
| 3 | `83eb0b9b` | `70899d60` | backlog: два наблюдения S5b вне приёмки | 1 файл, +25/−1 |
| 4 | `15241925` | `872fcb98` | S6: слой каждого гейта, пояс чата из ответа сервера | 6 файлов, +471/−62 |
| 5 | `288a4311` | `66be926f` | S6: тесты (слой, пояс, scope, штамп) | 3 файла, +738/−9 |
| 6 | `f6905098` | `ea533e81` | S6: время событий обзора в поясе чата, слои компактно, e2e | 3 файла, +335/−19 |
| 7 | `dc699c72` | `540b32f9` | evidence-привязка S6 к `f6905098` | 8 файлов, +2477 |
| 8 | — | `6c11fc08` | бамп 2.58.193 → 2.58.194 | 30 файлов, +31/−32 |

Конфликтов разрешения не потребовалось: `git` сделал авто-merge
`web/app.js` (3 раза) и `web/index.html` (1 раз) — правки S5b/S6 не
пересекаются с правками ov-honesty линии 2.58.193. Других файлов нет:
`git cherry-pick` ни разу не остановился.

**Дельта `7a7cd0ce..6c11fc08` = 53 файла, +5397/−120**, все — `M` (38) и `A`
(15), удалений (`D`) нет. Состав: 23 файла одобренного содержимого (4 файла
кода, 5 тестов, 13 evidence, 1 `plans/backlog.md`) + 30 файлов пинов версии (28
тестов-пинов + `config/settings.py` + `plans/docs/param-registry-round1025.meta.md`).
Пересечений между наборами нет. Полный список — `git diff --name-status 7a7cd0ce 6c11fc08`.

Байт-в-байт с `7a7cd0ce` (blob SHA-1 идентичны):
`services/permissions.py` (`e20d46eb`), `web/api/avatars.py`, `web/api/deps.py`,
`web/api/routes.py` (`de3d57d6`), `services/direct_chat_service.py`
(`3073ca97`), `services/database.py` (`aa6db89b`),
`tests/fixtures/round1025/f8_baseline.json`.

DDL=0: в дельте 0 вхождений `CREATE TABLE`/`ALTER TABLE`/`ADD COLUMN`/
`DROP TABLE`/`_env_bool`/`ClassVar`; единственное совпадение по
`SCHEMA_VERSION` — `DIAG_SCHEMA_VERSION` (версия read-model диагностики, не БД).
`user_version` на живой БД до и после — 47.

`routes.py` не менялся → дайджест F11 **не** переутверждался.

Интерфейс не потерян (крупнее `master`):

| Файл | `6c11fc08` | `7a7cd0ce` | `master` |
|---|---|---|---|
| `web/app.js` | 2 278 069 б, blob `3da63eb5` | 2 264 877 б | 1 331 753 б (+946 КБ) |
| `web/index.html` | 1 330 512 б, blob `fe8801e6` | 1 328 384 б | 929 056 б (+401 КБ) |

## 2. Контрольные точки ревьюера — что наблюдалось после переноса

| # | Точка | Наблюдение |
|---|---|---|
| 1 | честная строка «Последнее действие» без старого `v-if/v-else` | `web/index.html:1880` — обычный `<span data-module-last-action>` с `{{ moduleLastEventLine(workspaceModule) }}`, ветки `v-else` нет; вторая такая же строка (`:1035`) тоже без условия. Строки «Последних действий в журнале нет» в файле **0** вхождений |
| 2 | формулировка про пояс другого чата ↔ `iniOtherChatView` | `web/index.html:1937-1939` — «Время — в поясе этого чата, пояс назван в карточке». Парная правка в `web/app.js` `iniOtherDiagView` (`:10285-10301`) берёт `iniTzOf(d)` из ответа чужого чата и отдаёт `timezone`/`timezoneSource`/`timezoneLabel`; карточка печатает `data-ini-card-tz` c тем же источником. Обе правки в одном дереве; на живой сборке карточка чужого чата показала `data-ini-card-tz-source=utc_fallback` |
| 3 | `iniChatTimezone` = 0 вхождений | `git grep iniChatTimezone` по всему дереву — **0**. Определение заменено на `iniTzOf`/`iniOverviewTz`; оба прежних вызова (`:10033`, `:10041` до патча) переписаны. `ReferenceError` на обзоре не наблюдался: консоль живой сборки чистая (0 ошибок) |
| 4 | `initiativeLastActionFact` читает `iniOverviewTimezone` как строку | `web/app.js:23150` — `var tz = this.iniOverviewTimezone;` → `iniWhen(at, tz)`; `iniOverviewTimezone` (`:10202`) возвращает `iniTzOf(...).format`, т.е. строку. Честность строки сохранена (см. живое подтверждение ниже) |
| 5 | тесты не перенесены слепо | `tests/test_webapp_js_unit.py` **не** трогался: он идентичен `7a7cd0ce` (blob `de0ea78b`), `test_js_unit_p0im_ov_honesty` и `tests/js/p0im_ov_honesty_test.js` на месте — проба прогнана и дала `P0IM-OV-HONESTY-OK`. `tests/ui_initiative_rework_e2e.py` перенесён патчем `f6905098` (база патча `e4497d1c` == база `7a7cd0ce`, потерь нет); `tests/js/initiative_ui_rework_test.js` — база `4e581127` == база `7a7cd0ce`, блоки S5b/S6 добавлены поверх ov-honesty-блоков, проба `INITIATIVE-UI-OK` |

## 3. Преддеплойная валидация (worktree `release/2.58.194`)

| Проверка | Результат |
|---|---|
| `tests/js/p0im_ov_honesty_test.js` | `P0IM-OV-HONESTY-OK` |
| `tests/js/initiative_ui_rework_test.js` | `INITIATIVE-UI-OK` |
| `tests/test_p0im_s6_fresh.py` | **10 passed** |
| `tests/test_meme_init_diagnostics.py` | **43 passed** |
| `tests/test_p0im_s5_meme_marker_interrupt.py` | **15 passed** |
| `tests/test_publication_binding_delivery.py` | **8 passed** |
| два API-файла (публикации + диагностика) | **72 passed** |
| мемы/инициатива/публикации (19 файлов) | **404 passed / 4 failed** |
| инспектор шаг 1/2/3_ui | **59 + 19 + 44 = 122 passed** |
| JS-юниты `tests/test_webapp_js_unit.py` | **45 passed** |
| web/api (`tests/test_web*.py`, 68 файлов) | **1539 passed / 11 failed** |
| e2e-стенд `tests/ui_initiative_rework_e2e.py` | `failures=2`, `run_row_wrap` на 1536/390/360 — `docSw == docCw`, `offenders: []` |

Базовые линии сняты на отдельном checkout `7a7cd0ce`:

- 4 падения — ровно те же в `test_initiative_coordination.py`
  (`test_act_on_opportunity_conflict_defers_to_intent`,
  `test_evaluate_phase_precheck_blocks_before_llm`,
  `test_t1_nostalgia_delegated_refusal_sends_nothing`,
  `test_t5_every_text_send_site_passes_publish_guard`); на базе 396 passed при
  тех же 4 (тот же набор файлов даёт 404 passed здесь: +8 тестов S5b);
- 11 падений web/api — **побайтово тот же список файлов и тестов**, что на
  `7a7cd0ce` (1539 passed / 11 failed в обоих прогонах, расхождений в списке
  `FAILED` — 0);
- 2 падения e2e — те же два сообщения («после снятия override источник не
  «Исходный из кода»: 'Состояние неизвестно · журнал недоступен'»).

Новых падений нет. Особенность локальной оболочки: pytest с fd-захватом падает
на `OSError: [WinError 6]` при spawn node, поэтому все прогоны — с `-s`.

## 4. Деплой (один логин по ключу, без ретраев)

- `git fetch --prune origin` → `origin/release/2.58.194` = `6c11fc08` (сверено
  до checkout; при расхождении скрипт прерывается — не совпало бы, выкладки нет).
- Снимок данных ДО выкладки (sqlite backup API) → `/tmp/predeploy-258194.db`
  (**2 441 658 368 б**), read-back: `user_version 47`, `quick_check ok`, 325
  объектов схемы, 40 с.
- `git checkout -B release/2.58.194 6c11fc08` → HEAD совпал, tracked-правок 0
  (только ожидаемое `?? .cache/`).
- `systemctl restart admin_bot` в **2026-11-11T23:19:13Z**; healthz отдал
  `2.58.194` на втором опросе (~3 с).

## 5. Постдеплой (read-only, окно 23:19:13Z → 23:32Z)

| Проверка | Значение |
|---|---|
| `HEAD` на сервере | `6c11fc08ddade1edf0c4fb274e7f1bf93f852a26` = кандидат |
| ветка на сервере | `release/2.58.194`, tracked-изменений 0 |
| `GET /healthz` (localhost и публично) | `{"status":"ok","version":"2.58.194"}` |
| systemd | `active`/`running`, `NRestarts=0`, поднят 23:19:15 UTC |
| journal с рестарта (1192 строки) | `TRACEBACK=0`, `CRITICAL=0`, `ERROR=2`, `WARNING=4` |
| схема живой БД | `user_version 47` (DDL не было) |
| отданный `web/app.js` | 2 278 069 б, sha256 `3da63eb5…29ed4` — **байт-в-байт** с блобом релиза (и на диске, и через HTTPS) |
| отданный `web/index.html` | версия `2.58.194` подставлена (17 маркеров `__APP_VERSION__`) |

Оба `ERROR` — один и тот же периодический шаг `anticliche_worker` (7-дневный
джоб, не связан с релизом), ровно та же пара строк была на предыдущем
процессе в 20:56:27Z:

```
[pipeline] event=pipeline_step component=anticliche step=fetch status=error reason=sources_unavailable problems=0 version=11
[pipeline] event=pipeline_step component=anticliche step=refresh status=fetch_error reason=wikipedia count=0 version=11
```

`WARNING` (4): `SmartModule: embedding generation not serviceable … FTS-only
(A06) | build pending — source empty`, `[vision] claim sweep slow` ×2,
`[anticliche] no usable source | problems=0`. Всё — прежнее фоновое поведение;
в окне прошлой выкладки (20:51–23:19Z) было 4 ERROR, включая `INCIDENT` и
`aiogram … Request timeout`, которых сейчас нет.

## 6. Живые подтверждения на реальных данных

Авторизованная сессия владельца (initData, подписанный токеном самой
выкладки), живая сборка `#/modules/initiative`, оба реальных чата.

**(а) Строка обзора называет реальное действие.**
```
Последнее действие: 11.11 23:29 · Текстовая инициатива — пропущено
```
на обоих чатах; `last_attempt.at = 1794439462` из живого ответа
`/api/initiative/mechanism-diagnostics` совпадает с напечатанным временем.
Строки «Последних действий в журнале нет» в тексте страницы нет (`false`),
«Последнее действие: нет данных» не показано (`false`). Независимо
подтверждено вторым браузерным движком (Browser Use) на той же сборке:
`falseEmptyExact: False`, `lastActionNoData: False`.

**(б) Время с поясом и его источником, шапка «(сервер)».**
```
пояс чата не задан — UTC (заводское значение, не часы сервера)   снимок: 11.11 23:31 (сервер)
```
`data-ini-tz-source=utc_fallback`, `data-ini-tz-name=UTC`,
`data-ini-tz-known=true`, `data-ini-snapshot-basis=штамп снимка — сервер`.
Ни у одного из двух реальных чатов чатовый пояс не задан — поэтому честно
назван заводской слой, а не часы сервера. В режиме «Другой чат» карточка
печатает пояс ЧУЖОГО чата из его ответа: `data-ini-card-tz-source=utc_fallback`
(«Время: пояс чата не задан — UTC …»), то есть формулировка в шапке и данные
карточки согласованы. Слои решения по каждому гейту пришли из сервера:
«модуль инициативы — общий слой; наблюдатель — общий слой; тумблер этого чата —
общий слой» (`data-ini-layers-count=3`) для одного чата и слой чата для
«настроек мемов» у другого.

**(в) Истёкший маркер `/meme` читается как истёкший, а не как занятость.**

| Чат | state | manual_priority_until | manual_priority_active | manual_priority_expired |
|---|---|---|---|---|
| −1004482340693 | `released` | 1794403592 (истёк) | `false` | `true` |
| −1002661910336 | `released` | 1794403499 (истёк) | `false` | `true` |

Полосы координации на обзоре нет вовсе (`[data-ini-coordination]` отсутствует)
— «отложено: приоритет ручного /meme» не показано ни на одном чате.

**(г) Поля S5b в read-model на реальных данных.** Мемы, оба чата:
```
"limit": 3, "used": 3, "remaining": 0, "limit_reached": true,
"delivered": 2, "not_delivered": 1,
"not_delivered_reasons": {"publisher_not_bound": 1}
```
Текстовая инициатива (фактов доставки нет): `delivered: null`,
`not_delivered: null`, `not_delivered_reasons: {}` — «нет данных», а не «0».
`last_delivery` мема: `status=confirmed`, `message_id=10472`,
`reason_code=""`. На экране это одна строка:
«Генерации сегодня: 3 / 3 · Осталось: 0 · сброс: 2026-11-12T00:00:00+00:00 ·
израсходовано без отправки: 1 (отправитель не привязан в этом процессе)».

**Честная граница.** Новый живой случай отложенной публикации
(`publication deffered → доставка первым проходом с привязанным ботом`) в этом
окне не воспроизведён: суточная квота мемов исчерпана в обоих чатах
(`daily_quota_reached`, сброс `2026-11-12T00:00:00Z`), поэтому новых попыток
мемов с реальной отправкой нет. Поля S5b при этом уже populated реальными
данными (2 доставлено / 1 израсходовано без отправки), а сам путь deferral
доказан на уровне кода и тестов (`test_publication_binding_delivery.py`, 8).
Наблюдение нового случая — предмет отдельного реального события после сброса
квоты, не блокер этой выкладки.

Кадры: `live-overview-chatA-2.58.194.png`, `live-other-chat-2.58.194.png`.
Числовые выгрузки: `live-overview-2.58.194.json`, `live-modes-2.58.194.json`,
`live-peek-2.58.194.json`.

## 7. Откат

```
git checkout -B release/2.58.193 7a7cd0ce959a320cef1c70a76a4483ffe5817d9a && systemctl restart admin_bot
```

Данные **не откатываются**: DDL=0, миграций нет, `user_version` 47 до и после;
снимок `/tmp/predeploy-258194.db` (2 441 658 368 б, `quick_check ok`) — только
страховка. Правки релиза не пишут новых таблиц и не меняют формат строк:
старый код читает те же данные без миграции.

## 8. Гейт требований

`requirements_gate.py check --stage release --candidate 6c11fc08…
--deployed-commit 6c11fc08…` — **не зелёный по бухгалтерии**, не по продукту:
`errors=205`, `stage=release inventory=42 manual=90 scoped=114`.

Причины (все — ведение карты, не поведение): `map candidate_commit` всё ещё
`7a7cd0ce` (FAIL candidate mismatch); существующие строки привязаны к прошлому
кандидату и старым путям evidence (18 + 17 + 8 FAIL); 6 обязательных строк
остаются `PENDING`. Строк S5b и S6 в карте пока нет — их заводит PM.
Гейт не отключался и не «зеленился» вручную.

Дальнейший шаг: PM/Orchestrator проставляет `candidate_commit =
deployed_commit = 6c11fc08…`, добавляет строки S5b / S6-FRESH, привязывает их
к `release-258194/deploy.md` и повторяет гейт.
