# DEPLOY-W3 — asap7 wave3 (3e52b96, 2.58.74) — 09.10.2026

**Результат: VERIFIED** (прод 2.58.73 → **2.58.74**; первая DDL-миграция эпика v35 применена штатно; fail2ban-дисциплина: 1 recon + 1 основной прогон + 1 read-only проб по аномалии, ключ/пароль только через stdin, не печатались).

## Параметры
- **DEPLOY_SOURCE:** immutable commit `3e52b961e04a2cc64f520a79f369efa69bce8654` (origin/master, REV-3 Approved 17/17). **MUTABLE_WORKTREE_REQUIRED: no** (локальный шум 116 строк не тронут; прод забрал только origin/master, ff).
- Прод pre-state: HEAD `71b3b69` (2.58.73), healthz 200 @2.58.73 (внешне), UV=34, book v35=0.
- Rollback: cold `git reset --hard 71b3b69` + рестарт (v35 аддитивна/инертна — SQLite no-op, PG nullable-колонка старым кодом игнорируется); soft: `DIRECT_L1_ENABLED=false`, `SUMMARY_COVER_PROMPT_ORDER=style_first`. Бэкап guard'а: pre-migration копия на диске прода (VACUUM INTO target_version=34, read-back ok) — не потребовался.

## Ход
1. `git pull --ff-only`: `71b3b69 → 3e52b96` (fast-forward, cached creds), HEAD подтверждён `rev-parse`.
2. Restart #1 (MARK 03:58:31 UTC): healthz 200 c 67-й попытки (~3.5 мин — миграционное окно, штатно); тело сразу **2.58.74**. Status active/running, PID **765433**, NRestarts=0, ExecMainStatus=0.
3. **Миграция v35 (journal, ровно один раз, ERR=0):**
   - `migrations: start | current user_version=34 | pending=[35]`;
   - `backup-guard: start | target_version=34 (VACUUM INTO + read-back)` → `memory_backup: pre-migration copy created + read-back ok | target_version=34` (167.9s) → `backup-guard: done`;
   - `migration v35: llm_usage_events PG-only — SQLite no-op (DDL применяет PgDatabase.init)` → `migration v35 applied | llm_usage_plan_meta_v35` → `migrations: complete | user_version=35 | total 168.2s`.
   - Пост-стейт БД: `UV_AFTER=35`, `schema_migrations` v35 ровно 1 ряд (`35,'llm_usage_plan_meta_v35'`; последний ряд книги). Способ сверки: live `pragma user_version` (readonly) + книга + журнал мигратора.
   - PG-DDL фактически применён: `information_schema.columns` → `('plan_meta','jsonb')` в `llm_usage_events`.
4. **Идемпотентность (restart #2, 04:02:56 UTC):** `migrations: start | current user_version=35 | pending=[]` → `complete | total 0.0s`; НЕТ ни backup-guard, ни повторного v35 — no-op подтверждён. PID **766499**, NRestarts=0, active.
5. Boot-батарея: рестарт #1 — 232 строки, ERR=0, CRIT=0, Traceback=1 (известный embedding-canary quota cooldown, pre-existing W1/W2, fail-soft); «Bot started, listening for messages» есть. Рестарт #2 — ERR=0, CRIT=0, Traceback=1 (тот же класс).
6. Смоуки: `/healthz` 200 @**2.58.74** внутрь (127.0.0.1:8000) + внешне (8/8 подряд); `/web/` 200 (621561 байт, обе стороны); unauth `/api/config` **401**, `/api/access/chats` **401**, `POST /api/cover/preview-compile` unauth **401** (fail-closed) — RBAC жив.
7. Identity sha256 5/5 байт-в-байт прод = локальный `3e52b96`: `bot.py`, `config/settings.py`, `services/database.py`, `services/pg_db.py`, `services/direct_l1.py`. `.env` не менялся, новых env нет.

## Incidental finding (не блокирует деплой)
Единичный ответ `/healthz` с телом `"version":"2.58.55"` в 127.0.0.1:8000 на 9-й попытке опроса в окне рестарта #2 (~04:03:19 UTC) — ни текущий (2.58.74), ни предыдущий (2.58.73) процесс такой версии отдать не могут. Пост-проба (04:05:20 UTC): слушатель порта 8000 **ровно один** (python pid=766499 = MainPID), локальные healthz 5/5 = 2.58.74, внешние 8/8 = 2.58.74; zombie/второй процесс не обнаружен. Классификация: **transient, low** — возможен кратковременный сторонний слушатель в момент перезапуска или артефакт наблюдения; воспроизведения нет. Рекомендация owner'у: при повторе — поймать `ss -tlnp` в окне рестарта и сверить `journalctl` вне юнита admin_bot.

## Owner/acceptance-шаги (не блокируют деплой)
- Авторизованный live: карточка L1 Planner в настройках (effective source D-5), preview-compile с брейкдауном, подкарточки модулей, durable-оси plan_meta в Pipeline (наполнятся после первых L1-вызовов) — owner-гейт.

## Отчёт
pull ff: **y** (71b3b69→3e52b96) · v35: применена 1 раз (backup-guard VACUUM INTO+read-back 167.9s, SQLite no-op, PG `plan_meta jsonb` подтверждён), повторный рестарт no-op, UV 34→**35**, book 1 ряд · рестарты ok (PID 765433→766499, NRestarts=0) · healthz **200 @2.58.74** (внутрь+внешне) · boot: ERR/CRIT=0, Traceback=1 (embedding-canary, pre-existing) · смоуки: healthz/web/401-RBAC/401-preview зелёные · identity 5/5 · блокеров нет; incidental transient 2.58.55 — low, см. выше.
