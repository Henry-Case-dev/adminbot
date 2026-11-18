# Post-deploy runbook — 2.58.219 (VMQ-TIME-09)

**Статус:** только процедура для DevOps после отдельного разрешённого деплоя.
В этой сборке деплой не выполнялся, production не затрагивался.
**Откат:** `e6239230` (2.58.218); схема остаётся 48, DDL/данные не меняются.

## 0. Предусловия (до рестарта)

1. `git -C /var/www/admin_bot status --porcelain --untracked-files=no` пуст;
   `git rev-parse HEAD` = выкладываемый SHA (ветка
   `release/vmq-time09-2.58.219`).
2. Свободное место проверено: `python manage.py disk audit` — не начинать при
   недостатке места. Штатный deploy-бэкап создаётся существующим workflow
   (пул `deploy_backup keep=2`); отдельная полная копия БД вручную не нужна.
3. `python tools/release_manifest.py` пишет `.deploy/release.json` на
   фактическом checkout **до** рестарта; в манифесте `version=2.58.219`,
   `previous_sha=e6239230`, `dirty_tracked=false`.
4. `sudo systemctl restart admin_bot`.

## 1. Health / identity / schema / disk

| Проверка | Ожидание |
|---|---|
| `curl -fsS https://<host>/healthz` | HTTP 200 |
| версия в UI/`/api/status` | `2.58.219` |
| `git -C /var/www/admin_bot rev-parse HEAD` | равен `release.json.deployed_sha` |
| `release.json` | `version=2.58.219`, `previous_sha=e6239230`, `dirty_tracked=false` |
| схема | `PRAGMA user_version` = **48**; `config_fingerprint`/`external_ref` есть; pending-шагов нет |
| `python manage.py disk audit` | свободное место в норме |
| `python manage.py disk cleanup --apply` | deploy-пул keep=2, без удаления активных данных |
| журнал запуска | нет ERROR миграций; F-01/QRNG-пути не изменились |

Схема не менялась: DDL 0, новых миграций/таблиц/колонок нет.

## 2. Playwright на ТОЧНЫХ выложенных байтах

Запускать в самом production checkout (не на копии и не на локальном дереве):

```
cd /var/www/admin_bot
python tests/ui_vmq_status_analytics_e2e.py \
  --out /tmp/time09-219-playwright.json \
  --shots /tmp/time09-219-shots
```

Ожидание: `ok=true`, **66/66** проверок true, `console_errors=[]`,
`retrieval_coverage=0`, `no_overflow` true на 1280/390/320. Скрипт использует
стабы из реальных payload-схем и локальный сервер; production-БД не читает.
После проверки удалить `/tmp/time09-219-*` (компактный JSON можно сохранить
как evidence, PNG — только при необходимости).

**Browser Use:** остаётся **blocked** (`BU_CDP_URL=http://127.0.0.1:9222`
недоступен, WinError 10061). Это не отменяет Playwright на выложенных байтах;
Browser Use не заявляется как выполненный.

## 3. Живой ход: per-run Status/Analytics (агентская проверка)

Выполнять **после** реального пользовательского хода, когда в
`mca_events` появится `mca07_retrieval` с `trace_id`. Синтетический ход в
production ради проверки не запускать; владельца не привлекать к QA.

1. Найти последний retrieval-хол:

```sql
SELECT ts, trace_id, chat_id, outcome, reason_code, usage_json
FROM mca_events
WHERE event = 'mca07_retrieval' AND trace_id IS NOT NULL
ORDER BY ts DESC LIMIT 5;
```

2. Взять `trace_id` и сверить связанные события (retention короткий — снимать
   evidence сразу):

```sql
SELECT ts, event, chat_id, outcome, reason_code
FROM mca_events
WHERE trace_id = '<trace_id>'
ORDER BY ts;
```

3. В UI:
   - **Статус** → секция «Покрытие годов» после «Здоровья памяти»: годы,
     причины исключений, «последний ход»/выбранный ход, 44 px, без обрезки;
   - **Аналитика** → «Покрытие годов по ходам»: строка хода с теми же числами,
     список `retrieve()` (≤6 вызовов), `memory_period`, «нет фактов» для
     измеренного нуля и «нет данных» для отсутствия измерения;
   - при переключении хода старые числа не выдаются за новые (спиннер/`aria-busy`),
     aggregate `/api/memory/retrieval-coverage` не вызывается.

4. Сверить SQL и UI: `usage_json.years`, `excluded`, `period_fill` совпадают с
   строкой; `stages.retrieval=true`; `retrieval[]` содержит только коды/числа/
   хост (R17), без текстов/ключей.

5. Зафиксировать в evidence: `live_turn: checked`, `trace_id`, `chat_id`,
   время, результат сверки. **Если реального хода после деплоя ещё не было** —
   честно записать `live_turn: no_real_turn`, не выдумывать данные и не
   блокировать релиз; статус остаётся `delivered_awaiting_evidence`, пока ход
   не появится.

## 4. Откат (при проблеме)

```
git -C /var/www/admin_bot checkout e6239230
python tools/release_manifest.py --effect rollback
sudo systemctl restart admin_bot
```

Проверить `/healthz`, версию `2.58.218`, identity (`HEAD=e6239230`), схему 48.
Данные не откатывать, DDL/DROP не выполнять; TIME-09 не писал новых данных.
