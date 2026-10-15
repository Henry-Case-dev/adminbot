# Live canary — ASAP 8 v6.3 / релиз 2.58.79

Compact current record. Секретов нет. Сырые логи не хранятся — только оперативные факты.

## Deploy binding

| Поле | Значение |
| --- | --- |
| DEPLOY_SOURCE | локальный репо `C:\Code\Python\adminbot`, branch `master`, commit `c2775a54258512a3e20c97341d3e8a6738b1a33b` (`c2775a54`) |
| Push | `f58a644c..c2775a54 master -> master` — origin/master синхронизирован с HEAD |
| ΔDDL | `git diff f58a644..HEAD -- services/database.py services/pg_db.py` → 0 совпадений `CREATE TABLE`/`ALTER TABLE` (backup-шаг не требуется) |
| Pre-deploy SHA (rollback target) | `b9ea4907ffa52e7b2974e9511113e03350820a6e` (`b9ea4907`, bump 2.58.78, 2026-10-14) |
| Deploy-механика | сервер: `git -c credential.helper=… pull --ff-only` из origin/master → HEAD сервера == кандидат точно |
| Локальный mutable worktree | **не требовался**: деплой шёл из закоммиченного immutable commit. Локальный шум (`services/disk_retention.py`, `tools/_ui_mca12_stories_e2e.json`, `plans/*`) в деплое не участвовал |
| MUTABLE_WORKTREE_REQUIRED | **no** — следующая фича может идти параллельно |
| Записная зона деплоя (сервер) | `/var/www/admin_bot` (git pull обновил tracked-файлы); до деплоя и после — 13 предсуществующих dirty-путей, `--ff-only` их не тронул |
| Серверное состояние | `/etc/systemd/system/admin_bot.service`: WorkingDirectory=/var/www/admin_bot, ExecStart=/var/www/admin_bot/venv/bin/python /var/www/admin_bot/bot.py |

## Version / commit

- Версия: **2.58.78 → 2.58.79**
- Pre: PID 2591774, `ActiveEnterTimestamp=2026-10-15 14:44:06 UTC`
- Post: PID 2594113, `ActiveEnterTimestamp=2026-10-15 14:55:08 UTC` (`systemctl is-active` = active)
- Post HEAD на сервере = `c2775a5` (полный `c2775a54…`), `origin/master` = `c2775a54…`

## Live-проверки (выполнены НА СЕРВЕРЕ)

Локальная сеть хоста: DNS внешнего домена не работает (`admin-bot.duckdns.org` не резолвится, HTTPS:000 с этой машины) — поэтому все проверки шли с самого сервера.

| Проверка | Результат |
| --- | --- |
| `GET http://127.0.0.1:8000/healthz` | **200**, тело `{"status":"ok","version":"2.58.79"}` — рантайм подтверждает целевую версию |
| `GET http://127.0.0.1:8000/api/health` | **200** |
| `GET http://127.0.0.1:8000/web/` | **200** |
| Внешний HTTPS-путь (эмуляция с сервера: `curl --resolve admin-bot.duckdns.org:443:127.0.0.1`) | `/healthz` **200**, `/web/` **200**, `/api/health` **200** |
| `journalctl -u admin_bot --since 14:55:00` | **0** совпадений `ERROR\|CRITICAL\|Traceback\|NameError` |

Артефакт способа проверки (НЕ прод-отказ): прямой TLS на `127.0.0.1:443` даёт `000` — у caddy нет сайта/сертификата под SNI `127.0.0.1`; на `:80` отдаётся `308` (редирект). Приложение слушает `127.0.0.1:8000`, caddy (`*:443`, `*:80`) проксирует внешний путь — подтверждено проверкой через `--resolve`.

## Journal-хвост после рестарта (сжато, без секретов)

Стабильный рабочий цикл без ошибок: `ingestion_live` outcome=success по нескольким чатам (duration 6–14 ms), `WATCHDOG_SWEEP` success, `F7v2: silence threshold not reached` (INFO, таймер сброшен без приветствия), `[mca09] intent heartbeat tick ran`, `[anticliche] skip: cache fresh version=10`, `initiative_observer_scan` success, `[b01] initiative observer tick completed`. Startup/alarm-строк отсутствуют.

## B11 — прод-факты (read-only)

Запуск: `venv/bin/python tools/v63_b11_mechanisms_report.py --db local_database.db --json /tmp/b11_prod.json` → RC=0, JSON сохранён на сервере.

Итог: `SUMMARY {'ok': 8, 'never_run': 2}`

- **ok**: dream, deep_sleep, belief_revision, paradigms, self_model, experience, initiative, summary_scheduler (gate on, producer registered, вход есть, попытки свежие)
- **never_run (честный не-зелёный)**: `graph_memory` (GraphRAG rebuild) и `embeddings` (инкрементальный embedding/backfill) — gate on, producer зарегистрирован, вход есть, но ни одной попытки/события
- Покрытие прогона (ограничения, честно): PG-слой гейтов не покрыт — `POSTGRES_DSN` не передан (`pg_available=false`, `pg_dsn_not_provided`); 2 `db_read_errors` «no such module: vec0» (sqlite-vec не загружается в этом интерпретаторе) → `backlog_missing_embedding` не посчитан

### Nad-наблюдения (не блокируют релиз, вынести в backlog)

1. `summary_scheduler`: последний run `state=DEGRADED`, `publication_status=published`, `pipeline_health=degraded` (2026-10-15) — диагноз `ok`, но деградация зафиксирована.
2. `experience`: последняя попытка `status=failure` (2026-10-10, kind=tool_chain) при job `experience.review completed` — диагноз `ok`; расхождение заслуживает внимания.

## Rollback

Роллбэк **не выполнялся** (не потребовался). Инструкция при необходимости:

```bash
ssh nik@198.46.175.136
cd /var/www/admin_bot
git checkout -f b9ea4907ffa52e7b2974e9511113e03350820a6e
sudo systemctl restart admin_bot
curl -s http://127.0.0.1:8000/healthz   # ожидаем {"status":"ok","version":"2.58.78"}
```

## Внешняя проверка (статус)

**unverified-from-this-host (local DNS down)** — с машины исполнителя `admin-bot.duckdns.org` не резолвится, HTTPS по 443 недоступен (HTTP:000). Живой evidence в этом отчёте собран с сервера (127.0.0.1:8000 + эмуляция внешнего пути через caddy). Внешнюю проверку по домену должен подтвердить владелец.

## Release coverage gate

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/asap8-v6-3-live-correction/requirements-map.json \
  --stage release --candidate c2775a54258512a3e20c97341d3e8a6738b1a33b \
  --deployed-commit c2775a54258512a3e20c97341d3e8a6738b1a33b
→ FAIL (exit 1)
```

Причина — карта покрытия не привязана к кандидату: `candidate_commit` пуст, `deployed_commit` пуст, все 148 позиций в статусе `PENDING`. Это бухгалтерия покрытия, созданная до данного лейна (карта закоммичена однажды в `bc91b902` без биндинга). **Карта не редактировалась** — правка ради «зеленого» запрещена. Нужен биндинг кандидата + статусы + evidence со стороны PM/Reviewer.

## Итог лейна

- Деплой-механика: **выполнена** — точный кандидат `c2775a54` на проде, сервис активен, healthz/api/web = 200, ошибок в journal нет, B11 собран.
- Release coverage gate: **красный** (не привязанная карта) — принятый релиз не объявляется.
- Замечаний по продукту из деплоя нет; два nad-наблюдения выше — в backlog.
