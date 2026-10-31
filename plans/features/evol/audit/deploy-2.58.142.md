# EVOL — деплой 2.58.142: попытка выката и откат

Дата: 31.10.2026, 22:18–22:27 +12:00 (10:18–10:27 UTC).
Роль: DevOps. Итог: **ВЫКАТ НЕ ВЫПОЛНЕН, ПРОД ОТКАЧЕН НА 2.58.141 (ЗДОРОВ)**.

## 1. Кандидат

| Параметр | Значение |
|---|---|
| Кандидат (ветка) | `evol/impl`, worktree `…\WorkspaceData\worktrees\c742e4de9e92c489\evol-71536a366a11-c63f6f44` |
| HEAD до bump | `a6d28750` (ASAP-UI-02 §2 review-fix3) |
| Bump-коммит | `06283422a876648e77b4d0037437ffe8f00e0393` (2.58.141 → 2.58.142, 31 файл / 32 вхождения) |
| Релизная ветка | `release/2.58.142` = `06283422` (FF от прод-базы `5346ee76`), **запушена** |
| `evol/impl` | **запушена** = `06283422` |
| Прод-база до выката | `5346ee76` (2.58.141, detached HEAD), SQLite `user_version=37` |

## 2. Предрелизные проверки (на `06283422`)

- `compileall services handlers web config bot.py` → rc=0 (дважды: до и после bump).
- Фокусные смоуки: `test_evol_fc_evidence_style` + `test_evol_vision_sync_core` + `test_evol014_meme_initiative` + `test_webapp_evol_w7_nav` → **133 passed**.
- Пин-набор (24 py + 4 js): node 4/4 OK; pytest **866 passed, 2 failed** — оба воспроизводятся **до** bump (stash-прогон), т.е. bump нейтрален:
  - `test_mca17c_invariants_round1047::test_no_ddl_catalog_ks_tools_delta` — пин устарел: ждёт `user_version == 38`, фактически 40 (санкционированный хвост v39 `prompt_revision_journal` + v40 `meme_quota_journal`). Только тест, продукт корректен.
  - `test_summary_publish_integration_round1026::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article` — падает **и на прод-базе `5346ee76`** (отдельный worktree), т.е. предсуществующее на деплой-линии, не регрессия релиза.
- Дельта `4aa91baf..HEAD`: 430 файлов, +94 640 / −19 811; кластеры совпадают с утверждённым списком (plans 183, tests 162, services 47, media 7, handlers 6, web 6, tools 11, docs 2, config 1, root 5).
- Медиа: 65 файлов в ветке, 7 новых (`goodmorning_07..12.jpg`, `slavic_testo.jpg`); `media/srv_cookies.txt` **не отслеживается** (`git ls-files media | grep cookie` = 0).
- Схема: v38 `quote_metadata`, v39 `prompt_revision_journal`, v40 `meme_quota_journal` — все аддитивные и зарегистрированы.

## 3. Выкат (2 SSH-коннекта: recon + основной прогон)

- recon: `HEAD=5346ee76`, detached HEAD, грязь = только `?? .cache/`, сервис active, media 59 файлов / 96 MB, `media/srv_cookies.txt` 47 265 байт присутствует локально и gitignored.
- основной прогон: `git fetch --prune` → `git checkout release/2.58.142` → HEAD `06283422` **совпал с кандидатом**; медиа на месте (66 файлов, 97 MB; `goodmorning_07..12.jpg` + `slavic_testo.jpg`, размеры совпадают с локальными); `systemctl restart admin_bot`.
- **Отказ**: сервис ушёл в crash-loop (`activating (auto-restart)`, status=1, счётчик рестартов 13→25), `/healthz` локально и публично → 502.

### Причина (продуктовая, Builder-owned)

```
services/prompt_release_policy.py:1285 _apply_scope_release
  → :1380 _write_active_value → :850 set_chat_override
  → asyncpg.exceptions.IndeterminateDatatypeError:
    could not determine data type of parameter $2
```

SQL `_SET_CHAT_OVERRIDE_SQL` (`services/prompt_release_policy.py:126-134`):

```sql
jsonb_build_object($2, $3::jsonb)
```

`$3` приведён (`::jsonb`), а `$2` — нет; `jsonb_build_object` вариадический (`"any"`), поэтому PostgreSQL не может вывести тип параметра на этапе Parse. Настоящий asyncpg-пул на проде → падение; локально и в тестах путь идёт через SQLite-двойники (`default_journal` возвращает `None`, если пул не asyncpg), поэтому зелёные тесты дефект не ловят.

Минимальная правка: `jsonb_build_object($2::text, $3::jsonb)`. Соседние запросы (`_DROP_CHAT_OVERRIDE_SQL` с `- $2`, `_UPSERT_BOT_SETTING_SQL` с `INSERT … VALUES ($1, $2::jsonb, $3)`) типизируются корректно.

Побочный эффект на данные: **отсутствует**. `apply_release` выполняет весь пакет в одной транзакции и при срыве откатывает её целиком (§1.4 кода), а падение произошло до коммита.

## 4. Откат (выполнен)

- `git checkout --detach 5346ee76` + `systemctl restart admin_bot`.
- `HEAD=5346ee76`, `active=active`, `MainPID=741269`, старт 11:23:26 UTC, `NRestarts=25` (историческое значение, после старта не растёт).
- Один процесс бота (`nprocs=1`), PG доступен (`pg_available=True`), воркеры поднялись (`NostalgiaWorker`, `AntiClicheWorker`, `VisionMediaWorker tick=5s`, `Goodmorning scheduler`), `Bot started, listening for messages...`, идут `mca_event=ingestion_live`.
- SQLite: `user_version=37`, `quick_check=ok`, таблиц v38/v39/v40 нет → **дрейфа схемы нет**, откат кода полный.
- Медиа: 7 новых файлов сняты вместе с откатом, каталог вернулся к 59 файлам; `srv_cookies.txt` не тронут.
- HTTP после отката: `/healthz` → 200 `{"status":"ok","version":"2.58.141"}` (4 пробы подряд), `/web/` → 200, 930 269 байт (идентично состоянию до выката).

## 5. Состояние прода сейчас

Прод жив на 2.58.141 (`5346ee76`), схема v37 без дрейфа, один поллер, PG подключён.
`release/2.58.142` (`06283422`) остаётся в origin и готов к повторному выкату **после исправления дефекта и ре-ревью**.

## 6. Что осталось сделать (не DevOps)

1. **Builder**: правка `$2::text` в `_SET_CHAT_OVERRIDE_SQL` + регресс, который реально исполняет PG-путь (или явная проверка каста параметров); после фикса — новый review-fix-коммит, затем DevOps повторяет bump-оценку и выкат.
2. **Builder/Reviewer**: обновить пин `test_no_ddl_catalog_ks_tools_delta` на санкционированный `user_version=40`.
3. **PM**: `requirements-map.json` — `candidate_commit` устарел (`432c7593`), у 567 из 616 строк нет вердикта; `deployed_commit` остаётся пустым (выката не было).
4. **Backlog**: `test_summary_publish_integration_round1026::test_on_l1_not_usable_level2_l2_publishes_article` — предсуществующее падение на деплой-линии.
