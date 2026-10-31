# EVOL — деплой 2.58.143: выполнен, прод на новой версии

Дата: 31.10.2026, 12:24–12:28 UTC. Роль: DevOps.
Итог: **ВЫКАТ ВЫПОЛНЕН, ПРОД ЗДОРОВ НА 2.58.143.**

## 1. Кандидат и источник деплоя

| Параметр | Значение |
|---|---|
| `DEPLOY_SOURCE` | commit `273be95c8ff4f70e08dceef1daccbdd3082fc909` (ветка `release/2.58.143` = `evol/impl`) |
| Bump-коммит | `273be95c` (2.58.142 → 2.58.143, 31 файл / 32 вхождения — тот же пин-набор, что у 2.58.142: 3 статических + 24 py + 4 js с экранированными точками) |
| Fix-коммит в составе | `2e48bfed` — `jsonb_build_object($2::text, $3::jsonb)` + регресс на живом PG |
| Прод-база до выката | `5346ee76` (2.58.141, detached HEAD), SQLite `user_version=37` |
| FF-проверка | `git merge-base --is-ancestor 5346ee76 273be95c` → да |
| Push | `origin/release/2.58.143` = `origin/evol/impl` = `273be95c` |
| `MUTABLE_WORKTREE_REQUIRED` | **no** — деплой шёл из Git-коммита; рабочий каталог агента после выката свободен для следующей фичи |

`release/2.58.142` (`06283422`) остаётся в origin как след неудачной попытки; деплой-таргет — `release/2.58.143`.

## 2. Предрелизные проверки (на `273be95c`)

- `compileall services handlers web config bot.py` → rc=0.
- JS-пины: node 4/4 OK (`hotfix7/8/9/10`).
- PY-пины: **867 passed**, 1 failed — `test_summary_publish_integration_round1026::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article`; воспроизводится до bump (задокументировано в `deploy-2.58.142.md` §2 и в бэклоге), к релизу отношения не имеет.
- Пин `test_no_ddl_catalog_ks_tools_delta` (`user_version=40`) после коммита `2e48bfed` — **проходит** (ранее падал на 38).

## 3. Выкат (2 SSH-коннекта: recon + основной прогон; + 1 контрольный, см. §6)

- **recon** 12:24:54 UTC: `HEAD=5346ee76` (detached), грязь = только `?? .cache/`, сервис `active`, `MainPID=741269`, `NRestarts=25`, 1 процесс бота, `/healthz` 200 `2.58.141`, `/web/` 200, `/api/health` 200, SQLite `user_version=37` `quick_check=ok`, media tracked=58, `media/srv_cookies.txt` присутствует (untracked, 47 265 байт), ошибок в журнале за 30 мин нет.
- **основной прогон** 12:26:28 UTC: preflight чистый → `git fetch --prune` → `git checkout -B release/2.58.143 origin/release/2.58.143` → `HEAD=273be95c` **совпал с кандидатом** (иначе скрипт завершается без рестарта) → `systemctl restart admin_bot`.

## 4. Результат на проде

| Проверка | Факт |
|---|---|
| `/healthz` | **200** `{"status":"ok","version":"2.58.143"}` (первая же проба) |
| `/web/` | **200**, 1 064 836 байт |
| `/api/health` (публично и `127.0.0.1:8000`) | **200** / **200** |
| Сервис | `active`, `MainPID=754390`, старт 12:26:29 UTC, **`NRestarts=0`** |
| Процессы бота | **1** |
| Журнал с момента рестарта | 357 строк, **0** `Traceback`/`ERROR`, `IndeterminateDatatype` = 0 |
| Критический путь (прошлый крах) | `apply_release` **выполнен**: `release=evol-016-cutover | blocks=109 | changed=121 | retired=0`; chat-scope override записан (`chat=-1002661910336`, `action=legacy_snapshot | outcome=applied`) — именно этот вызов падал на `$2` в 2.58.142 |
| SQLite | миграции 37 → 38 → 39 → 40 применены за 30.3 с (backup-guard 30.3 с, копия с read-back ok); `user_version=40`, `quick_check=ok` |
| SQLite v40 | `meme_initiative_reservation` PRESENT, `meme_initiative_attempt` PRESENT |
| PostgreSQL | `prompt_revisions` PRESENT (138 строк), `prompt_activations` PRESENT (133 строки), всего 28 таблиц |
| Медиа | 7 новых файлов на месте, размеры **совпадают с локальными** (138 659 / 20 384 / 149 166 / 136 904 / 37 341 / 157 041 / 216 224); tracked=65 |
| `srv_cookies.txt` | в Git **не попал** (`cookies_tracked=0`), на диске сохранён (47 265 байт) |

## 5. Откат

Не потребовался. Состояние отката известно и готово: `5346ee76` (2.58.141) в origin, откат = `git checkout --detach 5346ee76` + рестарт; скрипт выката содержал автоматический откат при не-200 `/healthz` (не сработал).

## 6. Контроль стабильности (12:27:40 UTC, +71 с)

Тот же `MainPID=754390`, `NRestarts=0`, 5 проб `/healthz` подряд → 200 (`2.58.143`), `/web/` и `/api/health` 200, 410 строк журнала, **0** ошибок, воркеры тикают (`VisionMediaWorker` каждые 5 с, «executed successfully»).

## 7. Найденное вне скоупа (не блокирует выкат)

1. **PM/evidence:** `plans/features/evol/requirements-map.json` — `candidate_commit` устарел (`432c7593`), `deployed_commit` пуст, у всех 616 пунктов вердикта нет; `source_path=plans/current_task.md` в этом worktree отсутствует, поэтому `requirements_gate.py check --stage release` даёт EXIT 1 (1168 ошибок инвентаря). Проверено: на предыдущем кандидате `fe411bc8` — те же 1169 ошибок, т.е. дефект карты **предсуществующий**, не следствие выката. Карта остаётся `strict_evidence=false`. Биндинг `deployed_commit=273be95c` и разбор инвентаря — за PM; фальсифицировать вердикты не допускается.
2. **Backlog:** предсуществующее падение `test_summary_publish_integration_round1026::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article` (воспроизводится и на прод-базе `5346ee76`).
3. Наблюдение: при первом коннекте в этом сеансе `deploy_commands.txt` содержал старый VPS первым блоком — скрипт ушёл на декомиссованный `198.46.175.136` (там нет `/var/www/admin_bot`, rc 9, без последствий). Раннер исправлен на разбор секции «НОВЫЙ VPS». Рекомендация: не полагаться на «первый `ip:` в файле».
