# DEPLOY-258114 — выкат 2.58.114 на прод (24.10.2026)

## Итог

**PASS** по всем пунктам, кроме двух честно отложенных наблюдений (`plan_meta` на новых L1-вызовах — `WAITING_EXTERNAL`; тик Summary 19:00Z — `WAITING_EXTERNAL`).

## Источник деплоя

- **DEPLOY_SOURCE (код):** commit `e9f7595bad3f56145078ad599edf4b7182d2e1df` (`release/2.58.114`, = master-1).
- **Финальный HEAD на сервере:** `4f64d9c730e35084dc10c377c0ad16731e13a85f` (master HEAD). Дельта `e9f7595b..4f64d9c7` — **только** `plans/features/asap-speech-arch/evidence/r3b/rollback.md` (правка F1-R1 из ревью), **0 `.py`-файлов** → рестарт не требовался, работающий код идентичен `e9f7595b`. Ветка на сервере: detached HEAD, tracked-дерево чистое.
- **MUTABLE_WORKTREE_REQUIRED:** нет для следующей разработки; сервер после выката не зависит от локального рабочего дерева.
- **Проверено на сервере:** `REL_DELTA=0` (delta `requirements.txt`/`requirements-dev.txt`/`pyproject.toml` = 0 файлов) → `pip install` не требовался; `FILE_COUNT=288`.
- **Версия:** `2.58.114` (healthz + `APP_VERSION` в `config/settings.py`).

## Предусловия (факт)

| Проверка | Факт |
|---|---|
| UTC сервера (авторитетные часы) | `2026-10-23T13:55:33Z` (локально 24.10, UTC+12) |
| healthz до | `200 {"status":"ok","version":"2.58.113"}` |
| HEAD до | `e4ee54f3cc12c…` (2.58.113), branch `master`, tracked-дельта 0, untracked 13 (`/.env` не тронут) |
| `systemctl` до | `active`, MainPID `726282`, NRestarts `0` |
| Диск до | 5 580 MB свободно (≥2 GB) |
| Бэкап БД | `backups/pre_deploy_258114_20261023.db`, 1 526 747 136 B, `integrity_check=ok`, `user_version=37`; после бэкапа 4 124 MB |
| Rollback-точка | локально + **запушена** `release/fix-2.58.113` = `e4ee54f3` (origin подтвердил создание ветки) |

## Деплой

1. `git fetch origin master release/2.58.114 --prune` — ok (`origin/master` → `845d40eb`).
2. `git checkout e9f7595b` — HEAD совпал, tracked-дерево чистое.
3. `systemctl restart admin_bot` — rc 0, T0 `14:02:2xZ`.
4. Healthz: `TRY1=502` (процесс ещё стартовал), `TRY2=200` → `{"status":"ok","version":"2.58.114"}`.
5. PID/NRestarts после: **MainPID 812309, NRestarts 0, ExecMainStatus 0** (подтверждено дважды, в конце прогона то же).

### Инцидент по ходу выката (устранён до рестарта)

Первый `git checkout` упал: `unable to create file plans/features/_audit-2026-10-23/… Permission denied` — каталог `plans/features/_audit-2026-10-23` принадлежал `root` (наследие прошлых root-операций), дерево осталось частично обновлённым (5 файлов).

- Рестарт **не выполнялся**, сервис продолжал работать на 2.58.113 из памяти.
- Лечение: `chown -R nik:nik /var/www/admin_bot/plans` → `git checkout -f e4ee54f3` (`DIRTY_AFTER_CLEAN=0`) → повторный `git checkout e9f7595b`.
- Влияния на прод-данные нет; повторный бэкап не делался (использован уже проверенный).

## Пост-проверки

| # | Пункт | Факт | Вердикт |
|---|---|---|---|
| 7 | healthz 2.58.114, active | `200 {"status":"ok","version":"2.58.114"}`, `active`, MainPID 812309, NRestarts 0, ExecMainStatus 0 | **PASS** |
| 8 | Миграции канонов R3/R3B, sha L1/L2, fingerprint, withheld, журнал | журнал: `[prompt_migration] канон обновлён | key=prompts.direct_l1_planner_system_prompt`, `… key=prompts.direct_chat_verbalizer_system_prompt`, `уже новый канон | key=prompts.direct_chat_system_prompt`; пользовательские кастомы (`summary_*`, `factcheck_*`, `search`, `youtube*`, `checkup`, `webpage`, `summary_editor`) — `кастом юзера — НЕ трогаем` (без изменений). Read-only PG (значение декодировано, sha12 = `prompt_registry.sha12`): **L1 `6c2ddc17c998`** (8261, `known_canon=True`), **L2 `83ff62bbee40`** (3081, `known_canon=True`), `factory_set_fingerprint()` = **`0163a686c401`**. `CRITICAL=0`, `Traceback=0`, `database is locked=0`, `ERROR=0`, `withheld`-событий 0, `PROMPT_RB=0` | **PASS** |
| 9 | Embedding: adopt не повторён, BUILD_START=0, vec active, serviceable | журнал: `ADOPTED=0`, `BUILD_START=0`, `SmartModule: embedding index serviceable | index=graph_facts_vec | class=ADMITTED_COMPATIBLE`. Read-only SQLite: `graph_facts_vec` gen1 `status=active`, `activated_at=1792734815` (прежний adopt от 2.58.113), `fingerprint=96f80838f683…`, `config_revision=adopt1:e540d4ad890e121d:a93485483697c3c3:12:1.00` — **новая генерация не создавалась** | **PASS** |
| 10 | Style: `hint_limits` отсутствует/OFF, правило `dash` активно | PG `style.policy` (rev 12): `hint_limits` в документе **отсутствует** (`STYLE_HINT_LIMITS_PRESENT=False`) → скрытой обрезки нет. `rules` = `emoji.hard.off`, `quotation_marks.hard.no_graphic`, `trailing_period.hard.strip` (все `enabled=True`); строки `dash` у владельца нет → по коду `e9f7595b` (`style_policy.py:947-970,1019`) синтезируется заводское `dash.hard.factory` (`enabled=True`, hard, global) — **dash активен**. `GET /api/speech/style` не вызывался (TMA-подпись недоступна), вывод — из персистентной политики + кода кандидата | **PASS** (basis: PG + код) |
| 11 | Aliases merged-вид, read-only | `manage.py diag aliases --chat-id -1002661910336 --show-names` → 39 пользователей, merged-цепочка; чатовый override отличается от глобального только у `uid=529151103` (`chat=Папаха / global=Толян → effective=Папаха`). Данные не менялись | **PASS** |
| 12 | `plan_meta`: `needs_clar`/`clar_target_present` на новых L1 | Новых L1-вызовов после рестарта нет: в `llm_usage_events` за 4 ч 21 строка, последняя `13:47:29Z` (до деплоя), `plan_meta` пуст, `needs_clar=0 / clar_target_present=0`. Код-путь подтверждён в кандидате: `services/direct_chat_service.py:344` пишет оба поля, `services/usage_events.py:48-58` держит их в R17-whitelist | **WAITING_EXTERNAL** (проверяется первым реальным L1-сообщением) |
| 13 | B11: Summary не зелёный при проблемах, backlog числом | `B11_RC=0`, `diagnoses: ok=7, attention=2, unknown=1`, `not_green_rule: never_run/producer_off/no_input/unknown/degraded/attention никогда не считаются зелёными`. `attention` — `graph_memory`, `embeddings` (`job cancelled — не успешный` после adopt), `unknown` — `experience` (pre-existing). Backlog: `backlog_status=ok`, `backlog_missing_embedding=-113` (отрицательный = пропущенных вложений нет; в vec есть строки для истёкших фактов) | **PASS** |
| 14 | Тик Summary 19:00Z | не наступил (`2026-10-24T19:00Z`), не ждали | **WAITING_EXTERNAL** |

### Числа хранилища (read-only)

`graph_facts=20 198`, `graph_facts_vec=20 311` (загружен `sqlite_vec`), eligible (не истёкшие) `15 936`, `user_version=37`. Расхождение vec/eligible — pre-existing (истёкшие факты остаются в vec, retention не чистит `graph_facts_vec`); нового роста от выката нет.

## Откат

- Код: `cd /var/www/admin_bot && git checkout e4ee54f3 && systemctl restart admin_bot` → healthz `2.58.113`. Ветка `release/fix-2.58.113` = `e4ee54f3` (есть в origin).
- БД: `backups/pre_deploy_258114_20261023.db` (1.53 GB, integrity ok).
- Каноны (если понадобится): цепочка `plans/features/asap-speech-arch/evidence/r3b/rollback.md` — L1 2 вызова, L2 1 вызов, 3-й контрольный no-op. На сервере теперь лежит **исправленная** версия runbook (коммит `4f64d9c7`, `git worktree add /tmp/rel114 e9f7595b`).
- ΔDDL = 0, миграций схемы нет.

## Находки по проду

1. **MEDIUM (инфраструктура, устранено):** `plans/features/_audit-2026-10-23` принадлежал `root` → любой `git checkout` падал с `Permission denied` и оставлял частично обновлённое дерево. Вылечено `chown -R nik:nik plans`. Риск остаётся, если root-операции снова создадут файлы в репозитории; стоит не выполнять git-операции под root.
2. **LOW (pre-existing, не от 2.58.114):** `smart_archive` gen1/gen2 — `building`, `smart_archive_facts=0`, durable-джобы нет; в журнале один WARNING `embedding generation not serviceable | index=smart_archive … build pending — durable job missing`. `graph_facts_vec` работает штатно; B11 помечает это как `attention`.
3. **LOW (pre-existing):** `graph_facts_vec` содержит строки для истёкших фактов (20 311 против 15 936 eligible); `backlog_missing_embedding=-113` — метрика «не хватает вложений» корректна, но знак отрицательный из-за этого расхождения.
4. **INFO:** `GET /api/speech/style` и `/api/memory/embeddings` не вызывались — нет TMA initData; проверка сделана read-only PG + журналом процесса.

## Соединения SSH

5 подключений, все — один логин `nik`, интервал ≥60 с, без ретраев и поллеров: recon → основной (упал на правах, рестарта не было) → resume (починка прав + выкат) → read-only верификация (каноны/style/B11/vec) → перевод дерева на docs-коммит `4f64d9c7` (без рестарта).

## Артефакты прогона

- Логи: `OPENCODE_WORKFLOW_SCRATCH/deploy-258114/{run.log,run2.log,verify.log,final.log}`; на сервере `/tmp/d258114_boot.log`, `/tmp/b11_258114.json`.
- Скрипты: `tools/_dep258114.py` (recon/деплой), `tools/_dep258114_verify.py`, `tools/_dep258114_final.py`.
