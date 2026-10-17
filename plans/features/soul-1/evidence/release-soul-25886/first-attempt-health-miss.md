# Первая попытка деплоя 21:46–21:48Z: health-miss и авто-откат, диагноз и фикс

## Что произошло

| Время (UTC) | Событие |
|---|---|
| 21:46:06 | graceful-стоп процесса 2.58.85 (polling stop → runtime sqlite closed → bye, 1.6 с) |
| 21:46:12 | «Started admin_bot.service» — старт нового кода 2.58.86 (PID 3240765) |
| 21:46:31–21:46:32 | pg pool/DDL/сиды, `config_cache initialized: settings=514 roles=4 admins=3`, prompt/config-миграции (в т.ч. `кастом юзера — НЕ трогаем | summary_editor | chars=2023`) |
| 21:46:32.100 | `[database] migrations: start | current user_version=35 | pending=[36]` |
| 21:46:32.101 | `[database] migration backup-guard: start | target_version=35 (VACUUM INTO + read-back копии; на прод-объёме может занимать минуты)` |
| 21:47:35 | healthz-loop (~90 с) исчерпан, `HEALTH1=` пустой (HTTP ещё не слушает: приложение не завершило миграции) |
| 21:47:48 | авто-откат: `git checkout release/win-glass-2.58.85` + graceful-рестарт |
| 21:48:10 | `Run polling for bot @PERMsoc_bot` — база 2.58.85 поднялась |
| 21:48:1x | `ROLLBACK_HEALTH={"status":"ok","version":"2.58.85"}` — **прод жив на базе** |

## Диагноз (доказательство)

* В окне 21:45–21:50 журнал содержит **0** ERROR/CRITICAL/Traceback — это не
  падение, а долгая инициализация.
* Процесс 2.58.86 (PID 3240765) замер на **backup-guard миграции v36**
  (`VACUUM INTO` + read-back перед применением шага; комментарий кода прямо
  говорит «на прод-объёме может занимать минуты», `services/database.py:2870`).
  CPU 44.6 с за 96 с wall — I/O-bound, что подтверждает VACUUM.
* Приложение начинает слушать HTTP **после** завершения миграционного
  раннера (`initialize()`), поэтому healthz в 90-секундном окне не мог быть 200.
* `PRAGMA user_version` на проде остался **35**, таблица `humor_samples`
  отсутствует — миграция была прервана откатом (безопасно: шаг идемпотентен,
  self-guard; книга `schema_migrations` пишется `INSERT OR REPLACE`).

## Фикс (в деплой-скрипте)

1. Новый шаг `F3_migration_wait`: ожидание строки журнала
   `[database] migrations: complete` до **10 минут** (60 × 10 с) + вывод строк
   миграции в лог;
2. health-окно первого рестарта: 150 × 2 с = **5 минут** (было 45 × 2 = 90 с),
   второго рестарта — то же (после завершённой миграции он быстрый);
3. авто-откат оставлен (он сработал корректно и вернул прод на базу).

## Состояние прода после неудачи (проверено read-only)

`HEAD=95526863`, ветка `release/win-glass-2.58.85`, `healthz={"status":"ok",
"version":"2.58.85"}`, `ActiveState=active`, `NRestarts=0`;
`ENV_AXES=0` в `.env` (оси не включались — фаза enablement не достигалась),
PG-ключи `flags.*` SOUL отсутствуют, документы `character.core`/`style.policy`
не создавались. Секретов в логах нет (авто-скраб).
