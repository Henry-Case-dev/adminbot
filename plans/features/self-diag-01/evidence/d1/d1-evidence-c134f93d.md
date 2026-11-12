# SELF-DIAG-01 D1 — read-only evidence на проде (c134f93d / 2.58.195)

Срез: **D1-EVID**, только доказательства, кода не меняли. Владелец строк —
PM/Reviewer; здесь **ни одна строка не объявляется VERIFIED**.

Привязка:

| Поле | Значение |
|---|---|
| deployed commit | `c134f93d5c4a68f0ea906498cb9e0b78fc795f1e` |
| deployed version | `2.58.195` (ветка `release/2.58.195`, tracked-правок 0) |
| candidate_commit для строк | `c134f93d5c4a68f0ea906498cb9e0b78fc795f1e` |
| релиз 2.58.196 | **не выложен** (остановлен на преддеплойной проверке, см. отчёт DevOps); дельта поезда не трогает ни один файл D1 (проверено `git diff --name-only c134f93d..HEAD` — 47 файлов, ни одного checkup/self-diag) |
| метод | один read-only SSH-сеанс (без restart/записи), плюс локальный разбор того же кода и локальные тесты |
| отправлено сообщений в чаты | 0 |
| изменено настроек/промптов/флагов | 0 |

Побайтовая привязка к деплою: sha256 восьми файлов на сервере совпал с blob'ами
`c134f93d` (`git show c134f93d:<path>`):

| Файл | sha256 (сервер = c134f93d) |
|---|---|
| `services/system_logs_fetcher.py` | `2eb39df8…c2e0f5` |
| `handlers/checkup.py` | `7f1c1501…c962cc9` |
| `services/checkup_service.py` | `0d20794e…08129d` |
| `config/settings.py` | `1b53d4e3…d942b` |
| `services/betterstack_handler.py` | `5ab4e174…7ec87e` |
| `services/external_log.py` | `ebc680a9…d1edc4` |
| `web/app.js` | `f81d1e07…cdb0` |
| `web/index.html` | `d5debe85…b6ea10` |

Первичный артефакт: `plans/features/self-diag-01/evidence/d1/d1-probe-c134f93d.txt`
(sha256 `a24f603f28c430255bdb7198d354b1fced224e99c51191ef602548e556ee8e21`,
10 181 б). Секретные значения не печатались: только имена ключей, длины,
счётчики и хеши.

## 1. Наблюдённые факты (сняты с прода)

| Факт | Значение |
|---|---|
| HEAD / ветка | `c134f93d…` / `release/2.58.195`, tracked-правок 0 до и после |
| unit | `active`, `NRestarts=0`, `ActiveEnterTimestamp=2026-11-12 05:24:31 UTC`, `InvocationID=cc6bc988c4cd4536abea12dcb59732be` |
| `/healthz` | `{"status":"ok","version":"2.58.195"}` |
| схема БД | `user_version=47` |
| журнал за 30 мин | 1 605 строк: `Traceback=0`, `ERROR=0`, `CRITICAL=0`, `WARNING=12`, `attempt LOST=0` |
| диск / БД | `/` 99G, занято 52G, свободно 42G (56%); `local_database.db` 2 547 322 880 б |
| импорты сетевых модулей в checkup-пути | `[]` (нет `httpx/requests/aiohttp/urllib/socket/http`) |
| `create_subprocess_shell` / `CHECKUP_JOURNALCTL_CMD` в коде | 0 вхождений во всём репозитории |
| настройки журнала чекапа | только `CHECKUP_LOG_WINDOW_LINES=300` и пустой `CHECKUP_LOG_UNIT`; `CHECKUP_JOURNALCTL_CMD` отсутствует как атрибут |
| идентичность сервиса (из его же cgroup) | `unit=admin_bot.service`, `invocation_match=True` |
| argv чтения журнала | `["journalctl","--no-pager","--quiet","--output=short-iso","--lines=300","_SYSTEMD_INVOCATION_ID=cc6bc988c4cd4536abea12dcb59732be"]` |
| реальное чтение журнала сервиса | `state=info_only`, `backend=systemd`, `read=300`, `matched=0`, unit — тот же, invocation совпал |
| сетевые попытки при реальном `fetch()` | **0** (гард на `socket.connect` / `create_connection` / `asyncio.open_connection`) |
| честность пустого/INFO-журнала | отчёт печатает `state=info_only` и не заявляет «здоров» (`has_healthy_claim=false`, 201 символ провенанса) |
| лучше-стек в коде checkup | 0 упоминаний в `handlers/checkup.py`, `services/checkup_service.py`, `services/system_logs_fetcher.py` |
| UI-поля Better Stack | в `web/index.html` — 0; серверного каталога `keys_betterstack` нет; в `web/app.js:193` остался только зеркальный идентификатор группы |
| `/api/checkup` | 0 эндпоинтов |

Локальные тесты на том же кандидате (read-only): `tests/test_checkup_logs_fetcher.py`
**33 passed**, `tests/test_checkup_handlers.py` **37 passed**.

## 2. Строки D1 — что реально наблюдено (не VERIFIED)

| Строка | Наблюдение | Тип | Честный статус |
|---|---|---|---|
| SD1-D1-01 | `detect_runtime` различает systemd/container/standalone; у живого сервиса unit взят из его cgroup (`admin_bot.service`), invocation совпал с systemd | live+code | подтверждено для systemd-плеча |
| SD1-D1-02 | фиксированный argv через `create_subprocess_exec` (fetcher:298), без shell; реальное чтение 300 строк именно этого invocation | live+code | подтверждено |
| SD1-D1-03 | контейнерное плечо — только код+тесты; хост не контейнер (`marker=None`), живого прогона нет | code+tests | частично |
| SD1-D1-04 | standalone-плечо живьём не исполнялось: SSH-процесс сам оказался `systemd` (`session-148.scope`); код+тесты есть | code+tests | частично |
| SD1-D1-05 | состояния `ok/empty/info_only/unreadable` и фильтр по invocation есть в коде; живьём наблюдён только `info_only` (read=300, matched=0) | live+code | частично |
| SD1-D1-06 | произвольного shell нет (0 вхождений), argv фиксирован, таймаут 15 с, окно/длина ограничены | code | подтверждено кодом |
| SD1-D1-07 | инвентарь: checkup-модули 0; глобальный `BETTERSTACK_HOST` (env-only) и `services/betterstack_handler.py` — это общий logging-ingest, не чекап; в `web/app.js` остался мёртвый идентификатор группы | live+code | инвентарь снят |
| SD1-D1-08 | HTTP SQL-клиента, retry-путей и кред-ридера в чекапе нет; мёртвых ключей каталога нет (`get_by_pg_key` → `None` для всех 5 legacy-ключей); эндпоинтов `/api/checkup` нет | code+live | подтверждено, кроме persisted-строк (см. §3) |
| SD1-D1-09 | интерфейс `fetch()/close()` сохранён, хендлер вызывает `_fetcher.fetch()`; 33+37 локальных тестов зелёные | code+tests | подтверждено |
| SD1-D1-10 | **не выполнено**: в PostgreSQL `bot_settings` остались 5 legacy-строк Better Stack (см. §3); удаление по требованию — только после доказанного отсутствия потребителей и бэкапа | live | противоречие/ожидает решения |
| SD1-D1-11 | глобальные `services/betterstack_handler.py` и `services/external_log.py` на месте (хеши совпали с `c134f93d`), не удалялись по совпадению слова | live+code | подтверждено |
| SD1-D1-12 | отчёт фиксирует: 0 сетевых запросов в реальном `fetch()`, прямое чтение журнала после переезда VPS работает (300 строк), сохранённые сторонние интеграции перечислены | live | подтверждено |
| SD1-D1-13 | `CHECKUP_JOURNALCTL_CMD` и `create_subprocess_shell` — 0 вхождений; argv строится из инвентаря | live+code | подтверждено |
| SD1-D1-14 | runtime чист (0 потребителей), **но** «в настройках отсутствует» неверно: 5 persisted-строк остались, из них пароль маскируется API, а `models.*`-строки отдаются как сырые legacy-элементы | live | **противоречие** |
| SD1-D1-17 | серверного каталога `keys_betterstack` нет, `/api/checkup` нет, в `index.html` 0 упоминаний; в `web/app.js:193` остался мёртвый зеркальный id; остальные интеграции не тронуты | live+code | частично |
| SD1-AC-07 | перенос на другой VPS/юнит живьём не выполнялся; фактическое поведение переносимо по коду, а на этой среде чтение идёт через реальный systemd-бэкенд с честным `info_only` | live+code | частично |
| SD1-AC-08 | 0 сетевых попыток в реальном `fetch()`, в каталоге нет checkup-ключей Better Stack, внешние интеграции целы; **но** persisted-строки остались (см. §3) | live | частично/противоречие |

## 3. Найденное расхождение (важно для D1-10 / D1-14 / AC-08)

В PostgreSQL `bot_settings` на проде остались 5 legacy-строк прежнего SQL-чекапа
Better Stack (значения **не** читались и не копировались):

| Ключ | Длина значения |
|---|---|
| `keys.checkup_betterstack_sql_password` | 66 (секрет; API маскирует как `{configured,last4}`) |
| `keys.checkup_betterstack_sql_user` | 35 |
| `models.checkup_betterstack_sql_host` | 40 |
| `models.checkup_betterstack_sql_table` | 20 |
| `models.checkup_betterstack_sql_query` | 2 |

- потребителей в коде нет: `git grep -rn checkup_betterstack_sql -- services handlers config web bot.py` → rc=1;
- в каталоге параметров их нет (`get_by_pg_key` → `None`), группы `keys_betterstack` на сервере нет;
- `GET /api/config` перебирает **все** строки `bot_settings`: ключи категории `keys` маскируются, `models.*` уходят как обычные значения (это не секреты, но мёртвые элементы);
- удаление требует отдельного шага по SD1-D1-10 (доказанное отсутствие потребителей + бэкап) — это решение PM/Builder, не DevOps-выкладки.

## 4. Честные границы этого доказательства

- D1-03/D1-04 (container/standalone) живьём не исполнялись: прод — systemd-VPS, а SSH-процесс тоже попадает в systemd-scope. Покрытие — код + локальные тесты.
- Перенос на другой VPS/юнит не выполнялся (нет обслуживания); AC-07 подтверждён только фактической работой бэкенда и честным отказом, не реальным переездом.
- `chat_params` в PG как таблица отсутствует (`UndefinedTableError`) — per-chat проверка persisted-строк не выполнена.
- UI-рендер админки в этом окне не прокликивался (нет авторизованной сессии); выводы по UI — по серверному каталогу, API и статике.
- Первый probe-заход использовал системный `python3` без зависимостей и не смог импортировать приложение; это зафиксировано в артефакте, рабочий прогон — на `venv/bin/python`.
- Строки D1 **не** объявляются VERIFIED: решение за PM/Reviewer после сверки с §3.
