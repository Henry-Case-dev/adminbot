# DEPLOY-W4 — asap7 wave4 (0c4f3a5, 2.58.74 + каноны INFO v8 / GUIDE v5) — 09.10.2026

**Результат: VERIFIED** (прод HEAD `3e52b96` → **`0c4f3a5`**, версия без изменений **2.58.74**; доставка канонов справки INFO v7→v8 / GUIDE v4→v5 миграцией при старте — подтверждена; идемпотентность — подтверждена; fail2ban-дисциплина: 1 recon + 2 основных прогона (pull+restart1, restart2+PG-сверка) + 1 read-only проба + 1 битый по кавычкам коннект (bash-ошибка, без действий), все с интервалами, пароль только через stdin-скрипт, не печатался).

## Параметры
- **DEPLOY_SOURCE:** immutable commit `0c4f3a5e8b348b43997dec17d65b293092a3141a` (origin/master: `0c4f3a5` test(asap7-sweep) поверх `a1b3279` docs(asap7-f9)). **MUTABLE_WORKTREE_REQUIRED: no** (локальный шум `plans/*` не тронут; прод забрал только origin/master, ff).
- Прод pre-state: HEAD `3e52b96` (2.58.74, W3), healthz 200 @2.58.74 (внешне, pre-проба), DIRTY=13 (unchanged untracked-хвост, ff не мешает), UV=35 (v35 с W3 — ΔDDL=0 подтверждён отсутствием миграционных строк в boot).
- Rollback: cold `git reset --hard 3e52b96` + рестарт; канон-механика самовосстанавливается — старый код увидит v8-текст как unknown при отсутствии маркера доставки v7 (`cdv`=8≠7) → одноразовая force-deliver v7 с prev_html-бэкапом v8. Не потребовался.

## Ход
1. Pull ff: `3e52b96 → 0c4f3a5` (fast-forward, cached creds), HEAD подтверждён `rev-parse` = `0c4f3a5`.
2. Restart #1 (MARK 06:43:04 UTC): healthz 200 с 6-й попытки (~30 с — быстро, ΔDDL=0 штатно); тело сразу 2.58.74. active/running, PID **797895**, NRestarts=0, ExecMainStatus=0.
3. **Канон-миграция (boot #1, журнал, ровно один раз каждая, ERR=0):**
   - `[config_cache] guide canon migrated | v=4→5` (06:43:24.567);
   - `[config_cache] info canon migrated | v=7→8` (06:43:24.578);
   - обе — INFO-level, путь snapshot-match (безопасная перезапись прошлых канонов); WARNING `drift`/`force-delivered` отсутствуют.
4. **PG-сверка доставки** (read-only, venv-python/asyncpg, тот же `POSTGRES_DSN`, что у приложения): `bot_settings` → `content.info_how_it_works`: `canon_version=8`, `canon_delivered_version=8`; `content.intelligence_guide`: `guide_version=5`, `guide_delivered_version=5`. Маркеры доставки выставлены — каноны v8/v5 в проде.
5. **Идемпотентность (restart #2, MARK 06:45:33 UTC):** PID **798494**, NRestarts=0, active; PID-scoped grep (python[798494]): canon-строк **0**, ERR **0** — повторный старт silent no-op (путь «уже актуально» кода `_migrate_info_how_it_works_v1015`). TB=1 (известный embedding-canary quota cooldown, pre-existing W1–W3, fail-soft).
6. Boot-батарея: рестарт #1 — ERR/CRIT=0, Traceback=1 (тот же embedding-canary), «Bot started» есть. Рестарт #2 — ERR/CRIT=0 (PID-scoped).
7. Смоуки: `/healthz` 200 @**2.58.74** внутрь (127.0.0.1:8000, оба старта) + внешне 4/4 подряд; `/web/` 200 (621561 байт, обе стороны); unauth `/api/config` **401**, `/api/access/chats` **401**, `/api/info` **401** (внутрь+внешне) — RBAC жив.
8. Identity 8/8 байт-в-байт прод = локальный `0c4f3a5` (`git hash-object`): `bot.py`, `config/settings.py`, `services/database.py`, `services/pg_db.py`, `services/direct_l1.py`, `services/info_service.py`, `services/config_cache.py`, `services/param_catalog.py`. `.env` не менялся.

## Owner/acceptance-шаги (не блокируют деплой)
- Авторизованный live `GET /api/info` → `canon_version: 8`, `GET /api/info/guide` → `guide_version: 5` — веб-админ-креды вне deploy-скоупа, на уровне PG версии подтверждены (п.4); остаётся owner-гейт рендера в UI (карточка справки/гайда в миниаппе, §11/§13 новые тексты вживую).

## Отчёт
pull ff: **y** (3e52b96→0c4f3a5) · канон-миграция: **guide v4→5 + info v7→8, ровно 1 раз, ERR=0**, PG `canon_version=8`/`guide_version=5` + delivered-маркеры подтверждены, повторный рестарт **no-op (0 канон-строк)** · ΔDDL=0 (boot ~30 с) · рестарты ok (PID 797895→798494, NRestarts=0) · healthz **200 @2.58.74** (внутрь+внешне 4/4) · boot: ERR/CRIT=0, Traceback=1 (embedding-canary, pre-existing) · смоуки: healthz/web/401-RBAC зелёные (обе стороны) · identity 8/8 · блокеров нет · incidental-находок нет (транзиент 2.58.55 из W3 не повторился).
